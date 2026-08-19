"""Tests for the v2.15.0 "meeting duration" feature's propagation paths --
SDD.md's own explicitly-listed acceptance criteria: `app.py::_save_new`/
`_save_edit` (the two real bugs the SDD.md design calls out by name --
duration NOT traveling "for free" via a generic field copy), plus the month
view's "HH:MM-HH:MM" range text (`_refresh_calendar`). The pure lane-
assignment math (`_assign_week_meeting_blocks`) and `models.py`'s own
normalize/validate clamping are covered in
`tests/test_app_helpers.py`/`tests/test_models.py` respectively; the weekly
renewal engine's propagation is covered in `tests/test_recurrence.py`.

Built against a real `TimerMeetApp` pointed at an isolated scratch data
directory (never `data/meetings.json` -- see MEMORY's "never test against
live data" note), same harness `tests/test_delete_series.py::DeleteSeriesAppTests`
already established for this exact class of test.
"""

import shutil
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

try:
    import tkinter as tk

    from timermeet_app import main_window
    from timermeet_app.app import TimerMeetApp
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    main_window = None
    TimerMeetApp = None


def _no_op(*_args, **_kwargs):
    return None


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
class SaveDurationPropagationTests(unittest.TestCase):
    def setUp(self):
        self._scratch_dir = tempfile.mkdtemp(prefix="timermeet_duration_test_")
        self._base_dir_patcher = patch("timermeet_app.storage.base_dir", return_value=Path(self._scratch_dir))
        self._base_dir_patcher.start()

    def tearDown(self):
        self._base_dir_patcher.stop()
        shutil.rmtree(self._scratch_dir, ignore_errors=True)

    def _build_app(self):
        try:
            app = TimerMeetApp()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            self.skipTest(f"No display available for Tk: {exc}")
            return None
        self.addCleanup(self._destroy_app, app)
        return app

    @staticmethod
    def _destroy_app(app):
        try:
            app.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def _valid_payload(self, **overrides):
        payload = {
            "meetingId": "",
            "workName": "Acme",
            "title": "Standup",
            "date": "2026-08-10",  # a Monday
            "time": "09:00",
            "reminderMinutes": "15",
            "durationMinutes": "45",
            "soundProfile": "soft",
            "recurrenceType": "none",
            "occurrenceCount": "1",
            "teamsUrl": "",
            "notes": "",
        }
        payload.update(overrides)
        return payload

    def test_save_new_single_meeting_keeps_the_chosen_duration(self):
        """SDD.md v2.15.0 acceptance criterion, and the exact real bug it
        calls out by name: `_save_new` must include `durationMinutes` from
        the payload in the dict it builds for a new meeting, or every new
        meeting silently saves as the 30-minute default."""
        app = self._build_app()
        app.handle_save(self._valid_payload(durationMinutes="45"))

        self.assertEqual(len(app.meetings), 1)
        self.assertEqual(app.meetings[0].durationMinutes, 45)

    def test_save_new_recurring_series_propagates_duration_to_every_occurrence(self):
        app = self._build_app()
        app.handle_save(
            self._valid_payload(
                durationMinutes="90", recurrenceType="weekly", occurrenceCount="4",
            )
        )

        self.assertEqual(len(app.meetings), 4)
        for meeting in app.meetings:
            self.assertEqual(meeting.durationMinutes, 90)

    def test_save_new_default_duration_is_not_silently_dropped(self):
        # A payload that legitimately chose the 30-minute preset must still
        # persist that value explicitly, not merely "happen" to read back as
        # 30 because normalize_meeting() defaults an absent key to it.
        app = self._build_app()
        app.handle_save(self._valid_payload(durationMinutes="30"))
        self.assertEqual(app.meetings[0].durationMinutes, 30)

    def test_save_edit_updates_duration_on_the_existing_meeting(self):
        """SDD.md v2.15.0 acceptance criterion, and the second real bug it
        calls out by name: `_save_edit` mutates `existing` field by field,
        so without an explicit `existing.durationMinutes = ...` assignment,
        editing ONLY the duration from the form would silently no-op."""
        app = self._build_app()
        app.handle_save(self._valid_payload(durationMinutes="30"))
        meeting_id = app.meetings[0].id

        app.handle_save(self._valid_payload(meetingId=meeting_id, durationMinutes="60"))

        self.assertEqual(len(app.meetings), 1, "editing must not create a second meeting")
        self.assertEqual(app.meetings[0].durationMinutes, 60)

    def test_save_edit_persists_the_new_duration_to_disk(self):
        from timermeet_app import storage

        app = self._build_app()
        app.handle_save(self._valid_payload(durationMinutes="30"))
        meeting_id = app.meetings[0].id

        app.handle_save(self._valid_payload(meetingId=meeting_id, durationMinutes="120"))

        on_disk = storage.load_meetings()
        self.assertEqual(len(on_disk), 1)
        self.assertEqual(on_disk[0].durationMinutes, 120)

    def test_invalid_duration_in_payload_rejects_the_save_and_never_creates_a_meeting(self):
        app = self._build_app()
        toast_mock = MagicMock()
        with patch.object(app.view, "show_form_feedback"), patch.object(app.view, "show_toast", toast_mock):
            app.handle_save(self._valid_payload(durationMinutes="9999"))

        self.assertEqual(app.meetings, [])
        toast_mock.assert_called_once()


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class MonthViewDurationRangeTextTests(unittest.TestCase):
    """`app.py::_refresh_calendar`'s "HH:MM-HH:MM" entry text (SDD.md
    v2.15.0 decision #4) -- built against a real `TimerMeetApp` (same
    scratch-dir harness as above) so this exercises the exact production
    code path, with `render_calendar` itself mocked out (same style
    `tests/test_week_view.py::WeekViewGatingTests` already uses for
    `render_week_grid`) so only the DATA this method builds is inspected."""

    def setUp(self):
        self._scratch_dir = tempfile.mkdtemp(prefix="timermeet_duration_calendar_test_")
        self._base_dir_patcher = patch("timermeet_app.storage.base_dir", return_value=Path(self._scratch_dir))
        self._base_dir_patcher.start()
        try:
            self.app = TimerMeetApp()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            self._base_dir_patcher.stop()
            shutil.rmtree(self._scratch_dir, ignore_errors=True)
            self.skipTest(f"No display available for Tk: {exc}")
            return

    def tearDown(self):
        try:
            self.app.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass
        self._base_dir_patcher.stop()
        shutil.rmtree(self._scratch_dir, ignore_errors=True)

    def _entries_for_day(self, day, render_mock):
        cells = render_mock.call_args[0][2]
        matching = [c for c in cells if c.day == day]
        self.assertEqual(len(matching), 1)
        return matching[0].entries

    def test_entry_time_text_shows_start_and_end_range(self):
        from timermeet_app import models

        self.app._calendar_year, self.app._calendar_month = 2026, 8
        self.app.meetings = [
            models.normalize_meeting(
                {"workName": "Acme", "title": "Standup", "datetime": "2026-08-10T09:00", "durationMinutes": 45}
            )
        ]
        render_mock = MagicMock()
        with patch.object(self.app.view, "render_calendar", render_mock):
            self.app._refresh_calendar(datetime(2026, 8, 10, 8, 0))

        entries = self._entries_for_day(date(2026, 8, 10), render_mock)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].time_text, "09:00-09:45")

    def test_default_duration_meeting_still_shows_a_correct_range(self):
        # SDD.md's explicit acceptance criterion: a meeting that never
        # explicitly set a duration (defaults to 30 in normalize_meeting())
        # must still show the correct 30-minute range, not an empty/zero one.
        from timermeet_app import models

        self.app._calendar_year, self.app._calendar_month = 2026, 8
        self.app.meetings = [
            models.normalize_meeting(
                {"workName": "Acme", "title": "Standup", "datetime": "2026-08-10T14:00"}
            )
        ]
        render_mock = MagicMock()
        with patch.object(self.app.view, "render_calendar", render_mock):
            self.app._refresh_calendar(datetime(2026, 8, 10, 8, 0))

        entries = self._entries_for_day(date(2026, 8, 10), render_mock)
        self.assertEqual(entries[0].time_text, "14:00-14:30")

    def test_range_crossing_midnight_rolls_over_to_the_next_day_in_the_text(self):
        # `_refresh_calendar` doesn't clip like the week view's duration bar
        # does (SDD.md's cross-midnight clip decision is week-view-only,
        # see decision #6) -- the month view is pure text, so a late
        # meeting's end time simply rolls into the next calendar day's
        # HH:MM, unclipped.
        from timermeet_app import models

        self.app._calendar_year, self.app._calendar_month = 2026, 8
        self.app.meetings = [
            models.normalize_meeting(
                {"workName": "Acme", "title": "Late", "datetime": "2026-08-10T23:30", "durationMinutes": 60}
            )
        ]
        render_mock = MagicMock()
        with patch.object(self.app.view, "render_calendar", render_mock):
            self.app._refresh_calendar(datetime(2026, 8, 10, 8, 0))

        entries = self._entries_for_day(date(2026, 8, 10), render_mock)
        self.assertEqual(entries[0].time_text, "23:30-00:30")


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class DurationFieldWidgetTests(unittest.TestCase):
    """SDD.md v2.19.1: a real user wanted to type 80 into `duration_entry`
    and found no dropdown preset close to it, then separately asked for
    protection against typing letters/stray characters -- widens the
    dropdown to 5-minute increments and adds keystroke-level numeric-only
    validation, without giving up the combobox's original "quick presets,
    but still type-anything" design (see the widget's own construction
    comment in `main_window.py`)."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        cls.root.geometry("1000x700+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def test_dropdown_offers_5_minute_increments_including_80(self):
        values = self.view.duration_entry.cget("values")
        self.assertEqual(values, tuple(str(m) for m in range(5, 121, 5)))
        self.assertIn("80", values)

    def test_validate_digits_only_accepts_empty_and_pure_digit_strings(self):
        self.assertTrue(self.view._validate_digits_only(""))
        self.assertTrue(self.view._validate_digits_only("8"))
        self.assertTrue(self.view._validate_digits_only("80"))

    def test_validate_digits_only_rejects_letters_symbols_and_signs(self):
        for proposed in ("8a", "abc", "-5", "1.5", "80 ", "8/0"):
            self.assertFalse(self.view._validate_digits_only(proposed), f"{proposed!r} must be rejected")

    def test_inserting_a_non_digit_value_into_the_real_widget_is_rejected(self):
        """End-to-end proof the `validatecommand` is actually wired on the
        real widget, not just that the standalone method is correct --
        `.insert()` validates the same way a real keystroke would (`%P` is
        the value the edit would produce), so an invalid edit is reverted
        and the field's prior content survives untouched."""
        self.view._set_entry(self.view.duration_entry, "45")
        try:
            self.view.duration_entry.insert(0, "8a")
            self.assertEqual(self.view.duration_entry.get(), "45")
        finally:
            self.view._set_entry(self.view.duration_entry, "30")

    def test_inserting_a_digit_value_into_the_real_widget_is_accepted(self):
        self.view._set_entry(self.view.duration_entry, "")
        try:
            self.view.duration_entry.insert(0, "80")
            self.assertEqual(self.view.duration_entry.get(), "80")
        finally:
            self.view._set_entry(self.view.duration_entry, "30")


if __name__ == "__main__":
    unittest.main()
