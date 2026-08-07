"""Tests for `_ScrollablePanel`'s mouse-wheel bind lifecycle
(main_window.py) -- covers the confirmed unbounded memory leak where
`<Enter>` called `self.canvas.bind_all("<MouseWheel>", ...)` and `<Leave>`
called `self.canvas.unbind_all("<MouseWheel>")`, but `unbind_all` never
released the Tcl command `bind_all` registered. Every ordinary mouse
enter/leave over the meeting-form panel or the meeting-list panel (the two
busiest panels in the app, used constantly in a long-running session) grew
that count forever: measured at 100,000 realistic cycles, +101,253 orphaned
Tcl commands and +79MB RSS.

`_ScrollablePanel` only builds real `tk.Canvas`/`tk.Scrollbar`/`tk.Frame`
widgets, so this needs a real `tk.Tk()` root; skipped automatically if no
display is available, same as `tests/test_alarm_queue.py`."""

import unittest

try:
    import tkinter as tk

    from timermeet_app import main_window
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    main_window = None


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class ScrollablePanelWheelBindTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            # Not withdrawn (unlike test_alarm_queue.py): a couple of tests
            # below need `event_generate` to actually dispatch pointer
            # events (<Enter>/<Leave>/<MouseWheel>) to real bindings, which
            # requires the window to be mapped.
            self.root.geometry("200x200+0+0")
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            self.skipTest(f"No display available for Tk: {exc}")
            return

        self.panel = main_window._ScrollablePanel(self.root, bg="#000000")
        self.panel.pack(fill="both", expand=True)
        self.root.update()

    def tearDown(self):
        if self.root is None:  # already destroyed by the test itself
            return
        try:
            self.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def _root_tcl_command_count(self) -> int:
        return len(self.root._tclCommands or [])

    def test_repeated_bind_unbind_cycles_leave_zero_orphaned_commands(self):
        # Directly drives the same methods <Enter>/<Leave> are bound to,
        # the same way test_alarm_queue.py calls AlarmController methods
        # directly rather than only through synthetic Tk events -- this is
        # the same stress shape (a long-running session's worth of ordinary
        # mouse movement) that originally exposed the leak, just compressed.
        baseline = self._root_tcl_command_count()
        for _ in range(1000):
            self.panel._bind_wheel()
            self.panel._unbind_wheel()
        self.assertEqual(
            self._root_tcl_command_count(), baseline,
            "unbind must fully release the Tcl command bind_all registered, not just the Tk binding",
        )
        self.assertIsNone(self.panel._wheel_funcid)

    def test_real_enter_leave_events_leave_zero_orphaned_commands(self):
        # Same assertion as above, but driven through real synthetic Tk
        # events on the canvas instead of calling the bound methods
        # directly, to also exercise the actual <Enter>/<Leave> bindings.
        baseline = self._root_tcl_command_count()
        for _ in range(500):
            self.panel.canvas.event_generate("<Enter>", x=5, y=5)
            self.panel.canvas.event_generate("<Leave>", x=5, y=5)
        self.root.update()
        self.assertEqual(self._root_tcl_command_count(), baseline)

    def test_stray_double_enter_registers_only_one_binding(self):
        baseline = self._root_tcl_command_count()
        self.panel._bind_wheel()
        self.panel._bind_wheel()  # stray double-<Enter>, no <Leave> in between
        self.assertEqual(self._root_tcl_command_count(), baseline + 1)
        self.panel._unbind_wheel()
        self.assertEqual(self._root_tcl_command_count(), baseline)

    def test_stray_leave_without_enter_is_a_noop(self):
        baseline = self._root_tcl_command_count()
        self.panel._unbind_wheel()  # no matching <Enter> ever happened
        self.assertEqual(self._root_tcl_command_count(), baseline)
        self.assertIsNone(self.panel._wheel_funcid)

    def test_mousewheel_scrolls_while_hovered_and_not_after_leaving(self):
        canvas = self.panel.canvas
        scroll_calls = []
        original_scroll = canvas.yview_scroll
        canvas.yview_scroll = lambda *a, **kw: scroll_calls.append((a, kw)) or original_scroll(*a, **kw)
        self.addCleanup(setattr, canvas, "yview_scroll", original_scroll)

        canvas.event_generate("<Enter>", x=5, y=5)
        self.root.update()
        canvas.event_generate("<MouseWheel>", delta=120, x=5, y=5)
        self.root.update()
        self.assertTrue(scroll_calls, "scrolling must work while the panel is hovered")

        scroll_calls.clear()
        canvas.event_generate("<Leave>", x=5, y=5)
        self.root.update()
        canvas.event_generate("<MouseWheel>", delta=120, x=5, y=5)
        self.root.update()
        self.assertFalse(scroll_calls, "scrolling must stop once the mouse leaves the panel")

    def test_root_destroy_does_not_raise_after_bind_unbind_cycle(self):
        # Regression guard for the fix's own subtlety: bind_all()'s Tcl
        # command is tracked in the ROOT widget's bookkeeping list (see
        # CPython's Misc.bind_all -> self._root()._bind(...)), not the
        # canvas's -- deleting it against the wrong widget object leaves a
        # stale name behind that raises `_tkinter.TclError: can't delete
        # Tcl command` the next time root.destroy() tries to clean it up
        # itself. Confirmed empirically before landing the real fix.
        self.panel._bind_wheel()
        self.panel._unbind_wheel()
        self.root.destroy()  # must not raise
        self.root = None  # tearDown's destroy() would otherwise double-destroy

    def test_root_destroy_does_not_raise_while_still_hovered(self):
        # app.py's real shutdown path (`_on_close`) calls `self.root.destroy()`
        # unconditionally -- there is no guarantee the user's mouse isn't
        # sitting on top of a scrollable panel (meeting form/list) at that
        # exact moment, in which case `_unbind_wheel` (bound to <Leave>)
        # never runs before teardown. Unlike the bind-then-unbind-then-destroy
        # case above, this leaves `_wheel_funcid` set and the global
        # <MouseWheel> binding live going into `destroy()`, exercising
        # whatever Tk's own root teardown does with a bind_all Tcl command it
        # never got asked to release itself.
        self.panel.canvas.event_generate("<Enter>", x=5, y=5)
        self.root.update()
        self.assertIsNotNone(
            self.panel._wheel_funcid, "test setup must actually leave the panel hovered before destroying"
        )
        self.root.destroy()  # must not raise, even though <Leave> never fired
        self.root = None  # tearDown's destroy() would otherwise double-destroy


if __name__ == "__main__":
    unittest.main()
