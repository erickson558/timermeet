"""Tests for AlarmController's FIFO alert queue (alarm_ui.py) -- covers the
data-loss bug where a second meeting becoming due in the same heartbeat tick
used to silently destroy the first meeting's not-yet-dismissed overlay/sound
before the user ever saw it (see alarm_ui.py's class docstring).

AlarmController's entire job is building/destroying real tk.Toplevel
overlays, so there's no lower-level pure-function path to test this against
without a real Tk root; these tests open one (skipped automatically if no
display is available, e.g. a headless CI runner). Sound playback and the OS
toast are monkeypatched to no-ops for the duration of these tests -- both are
best-effort side channels irrelevant to the queue logic under test, and
running them for real would beep the speaker / pop a toast on every test
run."""

import unittest
from unittest.mock import patch

from timermeet_app import models

try:
    import tkinter as tk

    from timermeet_app import alarm_ui
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    alarm_ui = None


def _meeting(title: str) -> models.Meeting:
    return models.normalize_meeting(
        {"workName": "Acme", "title": title, "datetime": "2026-08-10T09:00"}
    )


def _label_texts(widget) -> list:
    """Recursively collect every tk.Label's text under `widget`, so a test
    can confirm the overlay actually rendered a specific meeting's content
    (not just that *some* overlay exists)."""
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            texts.append(child.cget("text"))
        texts.extend(_label_texts(child))
    return texts


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class AlarmControllerQueueTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            self.skipTest(f"No display available for Tk: {exc}")
            return

        self._patchers = [
            patch("timermeet_app.audio.AlarmPlayer.play"),
            patch("timermeet_app.audio.AlarmPlayer.stop"),
            patch("timermeet_app.notifications.notify", return_value=False),
        ]
        for patcher in self._patchers:
            patcher.start()

        self.controller = alarm_ui.AlarmController(self.root, get_language=lambda: "es")

    def tearDown(self):
        for patcher in self._patchers:
            patcher.stop()
        try:
            self.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def test_second_notify_while_active_is_queued_not_shown(self):
        meeting_a = _meeting("Meeting A")
        meeting_b = _meeting("Meeting B")
        calls = {"a": 0, "b": 0}
        self.controller.notify(meeting_a, "start", lambda: calls.__setitem__("a", calls["a"] + 1))
        overlay_a = self.controller._overlay
        self.assertIsNotNone(overlay_a, "meeting A's overlay must be shown immediately")

        self.controller.notify(meeting_b, "start", lambda: calls.__setitem__("b", calls["b"] + 1))

        # A's overlay must still be the one on screen, completely untouched --
        # this is the exact behavior the data-loss bug violated.
        self.assertIs(self.controller._overlay, overlay_a)
        self.assertEqual(len(self.controller._queue), 1)
        self.assertEqual(calls, {"a": 0, "b": 0})

    def test_dismiss_shows_next_queued_alert_automatically_with_its_own_content(self):
        meeting_a = _meeting("Meeting A")
        meeting_b = _meeting("Meeting B")
        calls = {"a": 0, "b": 0}

        self.controller.notify(meeting_a, "start", lambda: calls.__setitem__("a", calls["a"] + 1))
        overlay_a = self.controller._overlay
        self.controller.notify(meeting_b, "start", lambda: calls.__setitem__("b", calls["b"] + 1))

        self.controller.dismiss()  # simulates the user dismissing A (button or window close)

        self.assertEqual(calls, {"a": 1, "b": 0}, "A's on_dismiss must fire, B's must not fire yet")
        self.assertTrue(self.controller.is_active(), "queue hand-off must leave an overlay showing")
        overlay_b = self.controller._overlay
        self.assertIsNotNone(overlay_b)
        self.assertIsNot(overlay_b, overlay_a, "B must get a fresh overlay, not reuse A's")

        rendered = _label_texts(overlay_b)
        self.assertTrue(
            any("Meeting B" in text for text in rendered),
            f"expected meeting B's title text on the new overlay, got: {rendered}",
        )

    def test_dismissing_last_queued_alert_leaves_queue_empty_and_inactive(self):
        meeting_a = _meeting("Meeting A")
        meeting_b = _meeting("Meeting B")

        self.controller.notify(meeting_a, "start", lambda: None)
        self.controller.notify(meeting_b, "start", lambda: None)

        self.controller.dismiss()  # A -> B shown
        self.assertTrue(self.controller.is_active())

        self.controller.dismiss()  # B dismissed, nothing left queued
        self.assertFalse(self.controller.is_active(), "no third alarm should appear")
        self.assertEqual(self.controller._queue, [])

    def test_shutdown_dismiss_does_not_advance_the_queue(self):
        """Mirrors app.py::_on_close's call site: dismiss(run_callback=False,
        advance_queue=False) while the app is tearing down must never build a
        fresh Toplevel for a still-queued alert."""
        meeting_a = _meeting("Meeting A")
        meeting_b = _meeting("Meeting B")

        self.controller.notify(meeting_a, "start", lambda: None)
        self.controller.notify(meeting_b, "start", lambda: None)
        self.assertEqual(len(self.controller._queue), 1)

        self.controller.dismiss(run_callback=False, advance_queue=False)

        self.assertFalse(self.controller.is_active())
        self.assertEqual(self.controller._queue, [], "shutdown must drop pending alerts, not defer them")

    def test_is_active_reflects_post_handoff_state_inside_outgoing_callback(self):
        """Regression test: is_active() must never observably flip to False
        during the outgoing alert's own on_dismiss callback while another
        alert is about to take its place -- app.py::_refresh_all reads
        is_active() from inside that exact callback (via
        keep_gadget_on_top(self.alarms.is_active())) to decide whether the
        gadget should stay pinned on top, so a momentary False there is a
        real, user-visible bug, not just an internal inconsistency."""
        meeting_a = _meeting("Meeting A")
        meeting_b = _meeting("Meeting B")
        meeting_c = _meeting("Meeting C")
        observed = {}

        self.controller.notify(meeting_a, "start", lambda: observed.__setitem__("a", self.controller.is_active()))
        self.controller.notify(meeting_b, "start", lambda: observed.__setitem__("b", self.controller.is_active()))
        self.controller.notify(meeting_c, "start", lambda: observed.__setitem__("c", self.controller.is_active()))
        self.assertEqual(len(self.controller._queue), 2, "B and C must both be queued behind A")

        self.controller.dismiss()  # A dismissed; B is presented immediately behind it
        self.assertTrue(observed["a"], "B is still queued/about to show behind A's own callback")

        self.controller.dismiss()  # B dismissed; C is presented immediately behind it
        self.assertTrue(observed["b"], "C is still about to show behind B's own callback")

        self.controller.dismiss()  # C dismissed; queue is genuinely empty this time
        self.assertFalse(observed["c"], "nothing is left queued behind C, so this one must be False")

    def test_title_blink_phase_resets_on_queue_handoff(self):
        """Regression test: a newly-presented queued alert's title-blink
        cycle must always start on the "announcing" phase, regardless of
        what phase the previous alert's blink cycle happened to leave
        self._blink_on at. Without the reset in _start_title_blink, a
        hand-off landing on a "dirty" True value would flip straight to the
        plain base-title phase on the new alert's very first (synchronous)
        tick, instead of announcing the new alert immediately."""
        meeting_a = _meeting("Meeting A")
        meeting_b = _meeting("Meeting B")

        self.controller.notify(meeting_a, "start", lambda: None)
        self.controller.notify(meeting_b, "start", lambda: None)

        # Simulate the previous alert's blink cycle having already ticked
        # an odd number of times, leaving the flag "dirty" at True right
        # before the hand-off -- the exact state the bug depended on.
        self.controller._blink_on = True

        self.controller.dismiss()  # A -> B, a synchronous hand-off (no mainloop turn in between)

        self.assertTrue(
            self.controller._blink_on,
            "the reset must make the new alert's first tick flip False -> True, "
            "not leave it stuck at the pre-hand-off dirty value",
        )
        self.assertNotEqual(
            self.root.title(),
            self.controller._base_title,
            "immediately after the hand-off, the title must already be announcing "
            "the new alert, not sitting on the plain base-title phase",
        )


if __name__ == "__main__":
    unittest.main()
