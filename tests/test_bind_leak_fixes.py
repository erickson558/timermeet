"""Regression tests for the v2.10.0 Tcl-command-leak fix in
`_update_calendar_cell`/`_update_week_cell` (see SDD.md's v2.10.0 section and
`.claude/skills/timermeet-python-builder/references/module-map.md`'s
"Recurring footgun" note).

Root cause (confirmed empirically, not assumed): both functions rebind fresh
closures onto long-lived cell widgets (`day_label`/`frame`/`entry_label`) on
every REAL re-render (a month/week navigation, an edit, a language toggle --
already gated behind app.py's own dirty-check signature). Gating stops
*wasted* rebinds when nothing changed, but a real, correctly-triggered
rebind still leaked: on this Tk/Python version, calling `.bind()` again on
the same widget+sequence replaces which callback fires but never releases
the previous callback's Tcl command. `main_window._rebind()` fixes this by
capturing and releasing the previous funcid before rebinding.

Every test here uses the CORRECTED leak metric
(`tests/testutils.py::count_tcl_commands`, i.e. real `info commands`), not
`root._tclCommands` -- see that module's docstring and module-map.md's
methodology-correction note for why `root._tclCommands` is blind to a leak
from a plain (non-`bind_all`) `.bind()` call on a non-root widget, which is
exactly what these two functions do."""

import datetime as datetime_module
import shutil
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from tests.testutils import count_tcl_commands
from timermeet_app import models

try:
    import tkinter as tk

    from timermeet_app import main_window
    from timermeet_app.app import TimerMeetApp
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    main_window = None
    TimerMeetApp = None


# Substrings Tcl/Tk itself actually uses when a display genuinely isn't
# reachable (a headless CI runner, no X server, etc.) -- lowercased for a
# case-insensitive match against a real `TclError`'s message.
_NO_DISPLAY_ERROR_SIGNATURES = ("no display name", "couldn't connect to display", "no display")

# How many times to retry a `tk.Tk()` construction that raised a `TclError`
# whose message does NOT name an actual display problem, and how long to
# pause between attempts -- see `_build_tk_root_or_skip`'s docstring for why
# this exists at all.
_TK_ROOT_CONSTRUCTION_RETRIES = 3
_TK_ROOT_CONSTRUCTION_RETRY_DELAY_SECONDS = 0.3


def _is_no_display_error(exc: "tk.TclError") -> bool:
    message = str(exc).lower()
    return any(signature in message for signature in _NO_DISPLAY_ERROR_SIGNATURES)


def _construct_or_skip_on_no_display(construct):
    """Calls `construct()` (no arguments), raising `unittest.SkipTest` only
    for an actual "no display" condition -- never for a same-machine
    transient `TclError`. Callable from both a `setUp` (instance) and a
    `setUpClass` (classmethod) context, since `unittest.SkipTest` is a
    plain exception unittest recognizes from either -- same pattern this
    codebase's other `setUpClass` methods already use directly (e.g.
    `tests/test_week_column_mode.py::WeekColumnModeWidgetTests`). Generic
    over what's being constructed (a bare `tk.Tk()`, or a whole
    `TimerMeetApp()`, whose own `__init__` calls `tk.Tk()` as its literal
    first line -- confirmed directly, so retrying the whole constructor on
    that specific failure is exactly equivalent to retrying the bare
    `tk.Tk()` call, with nothing else built yet to leak on a retry) so both
    of this file's construction sites share one fix instead of two
    almost-identical copies.

    Found by adversarial review of v2.10.0's leak-fix test suite: catching
    bare `tk.TclError` at construction and treating ANY instance as "no
    display available, skip" is too broad on a real (non-headless) Windows
    machine -- confirmed directly, `tk.Tk()` construction here can
    intermittently raise `TclError` from ordinary resource contention after
    this same test file's earlier classes already created and destroyed
    several real Tk roots back-to-back, nothing to do with display
    availability. Left unguarded, that misclassifies a transient hiccup as
    "skip this whole class" -- and because WHICH class hits the hiccup
    varies run to run, a "green" full-suite run could silently skip the
    exact test meant to prove this round's critical leak fix without any
    failure/warning ever surfacing.

    Two-part fix: (1) only ever treat a `TclError` as "no display" if its
    own message actually names one (`_is_no_display_error` -- checked
    first, since a genuine no-display condition will not resolve itself, so
    there is no point retrying it); (2) for any other `TclError`, retry
    construction a few times with a brief real pause before concluding
    something is genuinely, persistently wrong -- at which point this
    re-raises the original error so the test ERRORS loudly instead of
    silently skipping, which is the correct outcome for an unexplained
    failure this specific, narrow retry didn't resolve."""
    last_exc: "tk.TclError" = None  # type: ignore[assignment]
    for attempt in range(_TK_ROOT_CONSTRUCTION_RETRIES):
        try:
            return construct()
        except tk.TclError as exc:
            last_exc = exc
            if _is_no_display_error(exc):
                raise unittest.SkipTest(f"No display available for Tk: {exc}") from exc
            if attempt < _TK_ROOT_CONSTRUCTION_RETRIES - 1:
                time.sleep(_TK_ROOT_CONSTRUCTION_RETRY_DELAY_SECONDS)
    raise last_exc


def _build_tk_root_or_skip() -> "tk.Tk":
    return _construct_or_skip_on_no_display(tk.Tk)


def _no_op(*_args, **_kwargs):
    return None


def _frozen_datetime(fixed_now: "datetime_module.datetime"):
    """A `datetime.datetime` subclass whose `.now()` always returns
    `fixed_now`, everything else delegating to the real class -- used to
    patch `timermeet_app.app.datetime` for the real-navigation leak tests
    below. Real-time `_refresh_all()` also re-renders the (unrelated)
    meeting-list panel on every call via its own independent dirty-check
    signature, which includes each card's countdown text
    (`_format_relative`, floored to the minute) -- confirmed directly that
    a 200-iteration loop can genuinely cross a real minute boundary
    mid-test, triggering a real (correct, not a leak) destroy/rebuild of
    that one meeting's card widgets that has nothing to do with the
    calendar/week grid fix under test here, and made an early version of
    this test flaky by a small, real, but irrelevant amount. Freezing time
    removes that unrelated variable entirely."""

    class _Frozen(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    return _Frozen


def _make_callbacks(**overrides):
    fields = {
        "on_save": _no_op, "on_clear": _no_op, "on_edit": _no_op, "on_delete": _no_op,
        "on_open_link": _no_op, "on_test_sound": _no_op, "on_set_now": _no_op,
        "on_toggle_language": _no_op, "on_test_notification": _no_op, "on_filter_change": _no_op,
        "on_clear_past": _no_op, "on_exit": _no_op, "on_add_company": _no_op, "on_remove_company": _no_op,
        "on_toggle_gadget_mode": _no_op, "on_enter_tray_mode": _no_op, "on_set_active_view": _no_op,
        "on_calendar_prev_month": _no_op, "on_calendar_next_month": _no_op, "on_calendar_today": _no_op,
        "on_calendar_day_click": _no_op, "on_week_prev": _no_op, "on_week_next": _no_op,
        "on_week_today": _no_op, "on_week_slot_click": _no_op, "on_toggle_week_column_mode": _no_op,
        "on_delete_series": _no_op, "on_edit_series": _no_op,
        "on_set_app_theme": _no_op, "on_gadget_resize": _no_op,
    }
    fields.update(overrides)
    return main_window.Callbacks(**fields)


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class RebindHelperTests(unittest.TestCase):
    """Direct proof of `_rebind()`'s own contract, isolated from any cell
    widget -- a plain `tk.Frame` is enough."""

    def setUp(self):
        self.root = _build_tk_root_or_skip()
        self.root.withdraw()
        self.frame = tk.Frame(self.root)

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def test_rebind_releases_the_previous_command_every_time(self):
        baseline = count_tcl_commands(self.root)
        funcid = None
        for i in range(500):
            funcid = main_window._rebind(self.frame, "<Button-1>", lambda _e, i=i: None, funcid)
        # Exactly +1, not +500: 499 of the 500 rebinds released their
        # predecessor; only the final, still-live one remains registered.
        self.assertEqual(count_tcl_commands(self.root), baseline + 1)

    def test_deletecommand_on_the_wrong_target_corrupts_bookkeeping_and_crashes_on_destroy(self):
        """Direct proof for `_rebind()`'s corrected docstring (found by
        adversarial review; the previous docstring's "silently doesn't
        release the command" claim for this wrong-target case was itself
        wrong): calling `deletecommand()` through the WRONG target
        (`widget._root()`, the `bind_all()` idiom -- NOT what this plain-
        bind case should ever do) does not silently fail to release the
        underlying Tcl command at all -- it deletes it via the one Tcl
        interpreter shared by every widget under this root, regardless of
        which widget object the call is made through. What actually breaks
        is the Python-side `_tclCommands` bookkeeping cleanup, which
        targets whichever object `deletecommand()` was called on (root's
        list here, not this widget's own) -- leaving a stale,
        already-deleted funcid stranded in the WIDGET's own list. That
        stale entry crashes with an uncaught `TclError` the instant this
        widget is later `.destroy()`ed (e.g. cascading from `root.destroy()`
        at real app shutdown) -- a double-delete crash, not a silent
        leak."""
        funcid = self.frame.bind("<Button-1>", lambda _e: None)
        self.assertIn(funcid, self.frame._tclCommands)

        # The wrong target: succeeds with no exception raised here...
        self.root.deletecommand(funcid)
        # ...but the funcid is stranded in the WIDGET's own bookkeeping
        # list -- root's `except ValueError: pass` swallowed the mismatch
        # silently, so nothing about this call site looked wrong yet.
        self.assertIn(
            funcid, self.frame._tclCommands,
            "the wrong-target delete must leave the funcid stranded in the widget's own list",
        )

        with self.assertRaises(
            tk.TclError, msg="destroy() must crash on the stale, already-deleted funcid left behind above"
        ):
            self.frame.destroy()

    def test_rebind_itself_never_leaves_a_widget_in_that_broken_destroy_state(self):
        """The flip side of the test above: `_rebind()`'s own (correct)
        `widget.deletecommand(...)` target must never corrupt bookkeeping
        the way the wrong target does -- a real `.destroy()` after many
        real rebinds must always succeed cleanly."""
        funcid = None
        for i in range(50):
            funcid = main_window._rebind(self.frame, "<Button-1>", lambda _e, i=i: None, funcid)
        try:
            self.frame.destroy()
        except tk.TclError as exc:
            self.fail(f"a widget correctly rebound via _rebind() must destroy() cleanly, got: {exc}")

    def test_plain_bind_without_rebind_leaks_for_comparison(self):
        """Demonstrates the exact bug `_rebind` exists to fix, so a future
        reader has a live, executable proof rather than only this module's
        prose -- same value `tests/test_scrollable_panel.py`'s own
        documentation-by-measurement already provides for the `bind_all`
        case."""
        baseline = count_tcl_commands(self.root)
        for i in range(500):
            self.frame.bind("<Button-1>", lambda _e, i=i: None)
        self.assertEqual(
            count_tcl_commands(self.root), baseline + 500,
            "a plain repeated .bind() must leak one command per rebind on this Tk/Python version",
        )

    def test_root_tclcommands_is_blind_to_the_plain_bind_leak_above(self):
        """The methodology-correction half of this fix (Fix B): proves
        directly that `root._tclCommands` -- correct for `bind_all()`, see
        `tests/test_scrollable_panel.py` -- does NOT move at all for the
        exact same plain-`.bind()` leak `count_tcl_commands` (via `info
        commands`) already caught above. Any earlier "verified leak-free"
        claim for a plain `.bind()` that only checked `root._tclCommands`
        could not have caught this."""
        baseline_info = count_tcl_commands(self.root)
        baseline_root_bookkeeping = len(self.root._tclCommands or [])
        for i in range(500):
            self.frame.bind("<Button-1>", lambda _e, i=i: None)
        self.assertEqual(count_tcl_commands(self.root), baseline_info + 500)
        self.assertEqual(
            len(self.root._tclCommands or []), baseline_root_bookkeeping,
            "root._tclCommands must NOT reflect a plain, non-bind_all .bind() leak on a non-root widget",
        )


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class CalendarAndWeekGridDirectRebindLeakTests(unittest.TestCase):
    """Drives `render_calendar`/`render_week_grid` directly (bypassing
    app.py's own dirty-check gate) with genuinely different content each
    call -- proving `_update_calendar_cell`/`_update_week_cell` themselves
    stay leak-free across repeated real rebinds, independent of whichever
    gate happens to sit in front of them in production."""

    @classmethod
    def setUpClass(cls):
        cls.root = _build_tk_root_or_skip()
        cls.root.geometry("1000x700+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def test_repeated_real_month_cell_rerenders_stay_bounded(self):
        """300 real re-renders of the whole 42-cell grid, changing which day
        (and whether an entry is present) sits at position 0 every time --
        every call is a genuine, correctly-triggered rebind, not a repeat of
        unchanged data."""
        self.view.set_active_view("calendar")

        def cells_for(i: int):
            day = date(2026, 1, 1) + timedelta(days=i)
            if i % 2 == 0:
                cell = main_window.CalendarCellData(
                    day=day, in_current_month=True, is_today=False, entries=[], overflow_count=0
                )
            else:
                entry = main_window.CalendarEntry(
                    meeting_id=f"meeting-{i}", time_text="09:00", title="Standup", color="#ffffff"
                )
                cell = main_window.CalendarCellData(
                    day=day, in_current_month=True, is_today=False, entries=[entry], overflow_count=0
                )
            padding = [
                main_window.CalendarCellData(
                    day=date(2025, 12, 1) + timedelta(days=k), in_current_month=True,
                    is_today=False, entries=[], overflow_count=0,
                )
                for k in range(41)
            ]
            return [cell] + padding

        # Warm up through BOTH states (no entry, then one entry) before
        # taking the baseline: the very first time position 0 ever shows an
        # entry, `entry_labels[0]`'s left/right bindings get their first-ever
        # `.bind()` call (previous_funcid is None, so `_rebind` has nothing
        # to release) -- a real, permanent +2 as long as that slot has EVER
        # shown an entry, not a leak. Only growth AFTER both states have
        # already been exercised once reflects a genuine per-rebind leak.
        self.view.render_calendar("Enero 2026", ["L", "M", "M", "J", "V", "S", "D"], cells_for(0))
        self.view.render_calendar("Enero 2026", ["L", "M", "M", "J", "V", "S", "D"], cells_for(1))
        baseline = count_tcl_commands(self.root)
        for i in range(2, 300):
            self.view.render_calendar("Enero 2026", ["L", "M", "M", "J", "V", "S", "D"], cells_for(i))
        self.assertEqual(
            count_tcl_commands(self.root), baseline,
            "298 further real re-renders (each genuinely changing cell 0's content) must not leak",
        )

    def test_repeated_real_week_cell_rerenders_stay_bounded(self):
        """Same proof, for the 168-cell week grid via `render_week_grid` --
        one FIXED position (hour=5, day-column=3) alternates between no
        entry and one entry every call; every other one of the 168 cells
        stays identically blank across every call (so a real per-rebind
        leak at any of those 167 "unchanging" positions would also show up,
        not just at the one deliberately-alternating position)."""
        self.view.set_active_view("week")
        monday = date(2026, 8, 10)
        target_hour, target_col = 5, 3

        def cells_for(i: int):
            if i % 2 == 0:
                filled = main_window.WeekCellData(
                    day=monday + timedelta(days=target_col), hour=target_hour, entries=[], overflow_count=0
                )
            else:
                entry = main_window.CalendarEntry(
                    meeting_id=f"meeting-{i}", time_text="09:00", title="Standup", color="#ffffff"
                )
                filled = main_window.WeekCellData(
                    day=monday + timedelta(days=target_col), hour=target_hour, entries=[entry], overflow_count=0
                )
            cells = []
            for row in range(main_window.WEEK_ROWS):
                for col in range(main_window.WEEK_COLS):
                    if row == target_hour and col == target_col:
                        cells.append(filled)
                    else:
                        cells.append(
                            main_window.WeekCellData(
                                day=monday + timedelta(days=col), hour=row, entries=[], overflow_count=0
                            )
                        )
            return cells

        headers = ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"]
        # Same warm-up reasoning as the month test above.
        self.view.render_week_grid("10-16 Ago 2026", headers, cells_for(0))
        self.view.render_week_grid("10-16 Ago 2026", headers, cells_for(1))
        baseline = count_tcl_commands(self.root)
        for i in range(2, 300):
            self.view.render_week_grid("10-16 Ago 2026", headers, cells_for(i))
        self.assertEqual(
            count_tcl_commands(self.root), baseline,
            "298 further real re-renders (each genuinely changing one cell's content) must not leak",
        )


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class RealNavigationLeakTests(unittest.TestCase):
    """End-to-end proof through the REAL production entry points
    (`app.py::handle_calendar_next_month`/`handle_week_next`, which go
    through `_refresh_all` -> `_refresh_calendar`/`_refresh_week` -> their
    own dirty-check signatures -> `render_calendar`/`render_week_grid`) --
    not just calling the view-layer render functions directly. Built
    against an isolated scratch data directory, never `data/meetings.json`
    (see MEMORY's "never test against live data" note)."""

    @classmethod
    def setUpClass(cls):
        cls._scratch_dir = tempfile.mkdtemp(prefix="timermeet_bind_leak_test_")
        cls._base_dir_patcher = patch(
            "timermeet_app.storage.base_dir", return_value=Path(cls._scratch_dir)
        )
        cls._base_dir_patcher.start()
        try:
            cls.app = _construct_or_skip_on_no_display(TimerMeetApp)
        except BaseException:
            # Covers both a genuine no-display skip and a construction
            # error that survived the retries above -- either way, this
            # class's isolated scratch dir/patcher must not leak past a
            # failed setUpClass.
            cls._base_dir_patcher.stop()
            shutil.rmtree(cls._scratch_dir, ignore_errors=True)
            raise
        cls.app.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass
        cls._base_dir_patcher.stop()
        shutil.rmtree(cls._scratch_dir, ignore_errors=True)

    def test_real_repeated_month_navigation_does_not_leak(self):
        self.app.meetings = [
            models.normalize_meeting({"workName": "Acme", "title": "Standup", "datetime": "2026-01-15T09:00"})
        ]
        self.app.active_view = "calendar"
        self.app.view.set_active_view("calendar")
        self.app._calendar_year, self.app._calendar_month = 2026, 1
        self.app._last_rendered_calendar_signature = None
        self.app._last_rendered_signature = None
        fixed_now = datetime_module.datetime(2026, 1, 15, 9, 0, 0)
        with patch("timermeet_app.app.datetime", _frozen_datetime(fixed_now)):
            self.app._refresh_all()  # pay for this test's own first render

            baseline = count_tcl_commands(self.app.root)
            for _ in range(200):
                self.app.handle_calendar_next_month()  # each call is a real, different month
        self.assertEqual(
            count_tcl_commands(self.app.root), baseline,
            "200 real month navigations (each a genuine re-render) must not leak Tcl commands",
        )

    def test_real_repeated_week_navigation_does_not_leak(self):
        self.app.meetings = [
            models.normalize_meeting({"workName": "Acme", "title": "Standup", "datetime": "2026-08-12T09:00"})
        ]
        self.app.active_view = "week"
        self.app.view.set_active_view("week")
        self.app._week_anchor = date(2026, 8, 12)
        self.app._last_rendered_week_signature = None
        self.app._last_rendered_signature = None
        fixed_now = datetime_module.datetime(2026, 8, 12, 9, 0, 0)
        with patch("timermeet_app.app.datetime", _frozen_datetime(fixed_now)):
            self.app._refresh_all()  # pay for this test's own first render
            # Settle the live "now" line's own cold-start geometry retry
            # (see `_apply_week_now_line`'s docstring, and
            # `test_week_view.py::_settle_week_live_indicators`) BEFORE
            # capturing the baseline: an unsettled retry job is a real,
            # legitimate pending `after()` Tcl command that is unrelated to
            # the bind-rebinding fix under test here, but would otherwise
            # get cancelled (a real, correct `-1`, not a leak) the moment
            # the first navigation below moves away from the current week
            # -- confirmed directly to be the actual cause of an early,
            # flaky `-1` in this exact test before this settle step was added.
            attempts = 0
            while (
                self.app.view._week_live_retry_job is not None
                and attempts <= main_window._WEEK_LINE_MAX_RETRIES
            ):
                self.app.root.after_cancel(self.app.view._week_live_retry_job)
                self.app.view._apply_week_now_line()
                attempts += 1

            baseline = count_tcl_commands(self.app.root)
            for _ in range(200):
                self.app.handle_week_next()  # each call shifts to a real, different week
        self.assertEqual(
            count_tcl_commands(self.app.root), baseline,
            "200 real week navigations (each a genuine re-render) must not leak Tcl commands",
        )


if __name__ == "__main__":
    unittest.main()
