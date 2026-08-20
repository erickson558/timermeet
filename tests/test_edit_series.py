"""Tests for "Editar serie completa" (SDD.md v2.19.0): editing a recurring
meeting's shared fields (title, workName, time-of-day, duration, sound,
Teams link, notes) across EVERY occurrence sharing its `seriesId`, not just
the one that was right-clicked -- the edit-side counterpart to "Eliminar
serie completa" (`tests/test_delete_series.py`).

Two layers, mirroring that file's own split:

- `EditSeriesFormUITests` (bare `MainWindow` against a real `tk.Tk()`, no
  `TimerMeetApp`): proves `populate_form(meeting, edit_series=True)` locks
  exactly the fields `_save_edit_series` does NOT apply across the series
  (own date, recurrence pattern, occurrence count) so the user is never
  offered a control this feature would silently ignore, swaps the Save
  button to "Actualizar serie", and that `_handle_save` forwards the flag
  in its payload -- and that a later plain edit (or Clear) fully unlocks
  those fields again.
- `EditSeriesAppTests` (real `TimerMeetApp` against an isolated scratch data
  directory, never `data/meetings.json` -- see MEMORY's "never test against
  live data" note): the real `handle_edit_series`/`_save_edit_series`
  wiring -- every live sibling's shared fields change, each occurrence's OWN
  date is preserved (only the time-of-day changes), `recurrenceType`/
  `occurrenceIndex`/`seriesSize` are left untouched, both alert flags reset,
  isolation from an unrelated second series and from standalone meetings,
  the two defensive no-op guards (empty `seriesId`, nonexistent id), and a
  real disk persist.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from timermeet_app import i18n, models, storage

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
        "on_set_now_line_color": _no_op, "on_set_company_color": _no_op, "on_reset_company_color": _no_op,
    }
    fields.update(overrides)
    return main_window.Callbacks(**fields)


def _meeting(id_, **overrides):
    data = {
        "id": id_,
        "workName": "Acme",
        "title": "Daily",
        "datetime": "2026-08-10T09:00",
    }
    data.update(overrides)
    return models.normalize_meeting(data)


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class EditSeriesFormUITests(unittest.TestCase):
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

    def _meeting_for_form(self):
        return _meeting(
            "series-1", seriesId="s1", recurrenceType="weekly", datetime="2026-08-10T09:00",
        )

    def test_edit_series_locks_date_recurrence_and_occurrence_count(self):
        self.view.populate_form(self._meeting_for_form(), edit_series=True)
        try:
            self.assertEqual(str(self.view.date_entry.cget("state")), "disabled")
            self.assertEqual(str(self.view._recurrence_menu_widget.cget("state")), "disabled")
            self.assertEqual(str(self.view.occurrence_entry.cget("state")), "disabled")
            self.assertEqual(self.view.save_button.cget("text"), i18n.t("updateSeriesButton", "es"))
            # Everything else the series-wide save DOES apply stays editable.
            self.assertEqual(str(self.view.work_entry.cget("state")), "normal")
            self.assertEqual(str(self.view.title_entry.cget("state")), "normal")
            self.assertEqual(str(self.view.time_entry.cget("state")), "normal")
        finally:
            self.view.clear_form()

    def test_plain_edit_after_a_series_edit_unlocks_the_form_again(self):
        self.view.populate_form(self._meeting_for_form(), edit_series=True)
        self.view.populate_form(self._meeting_for_form(), edit_series=False)
        try:
            self.assertEqual(str(self.view.date_entry.cget("state")), "normal")
            self.assertEqual(str(self.view._recurrence_menu_widget.cget("state")), "normal")
            self.assertEqual(self.view.save_button.cget("text"), i18n.t("updateButton", "es"))
        finally:
            self.view.clear_form()

    def test_clear_form_after_a_series_edit_unlocks_the_form_and_resets_the_flag(self):
        self.view.populate_form(self._meeting_for_form(), edit_series=True)
        self.view.clear_form()

        self.assertEqual(str(self.view.date_entry.cget("state")), "normal")
        self.assertEqual(str(self.view._recurrence_menu_widget.cget("state")), "normal")
        self.assertFalse(self.view._form_edit_series)
        self.assertEqual(self.view.save_button.cget("text"), i18n.t("saveButton", "es"))

    def test_handle_save_payload_carries_the_edit_series_flag(self):
        self.view.populate_form(self._meeting_for_form(), edit_series=True)
        captured = {}
        self.view.callbacks = _make_callbacks(on_save=lambda payload: captured.update(payload))
        try:
            self.view._handle_save()
            self.assertTrue(captured["editSeries"])
            self.assertEqual(captured["meetingId"], "series-1")
        finally:
            self.view.clear_form()

    def test_handle_save_payload_omits_edit_series_for_a_plain_edit(self):
        self.view.populate_form(self._meeting_for_form(), edit_series=False)
        captured = {}
        self.view.callbacks = _make_callbacks(on_save=lambda payload: captured.update(payload))
        try:
            self.view._handle_save()
            self.assertFalse(captured["editSeries"])
        finally:
            self.view.clear_form()


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class EditSeriesAppTests(unittest.TestCase):
    def setUp(self):
        self._scratch_dir = tempfile.mkdtemp(prefix="timermeet_edit_series_test_")
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

    def _series(self):
        """3 occurrences sharing `seriesId="s1"`, each on its own date, each
        already alerted (`reminderSent`/`startSent` both `True`) so the
        "editing a series re-arms its alerts" assertion below is meaningful."""
        return [
            _meeting(
                f"series-{i}", seriesId="s1", recurrenceType="weekly", occurrenceIndex=i + 1, seriesSize=3,
                datetime=f"2026-08-{10 + i:02d}T09:00", reminderSent=True, startSent=True,
            )
            for i in range(3)
        ]

    def _payload_for(self, meeting_id, **overrides):
        payload = {
            "meetingId": meeting_id,
            "workName": "Updated Corp",
            "title": "Updated Standup",
            "date": "2026-08-10",  # only the anchor's own date -- must NOT propagate
            "time": "10:30",
            "reminderMinutes": "20",
            "durationMinutes": "45",
            "soundProfile": "urgent",
            "recurrenceType": "weekly",
            "occurrenceCount": "1",
            "teamsUrl": "https://teams.example.com/updated",
            "notes": "Updated notes",
            "editSeries": True,
        }
        payload.update(overrides)
        return payload

    def test_edit_series_updates_shared_fields_on_every_occurrence_but_keeps_each_own_date(self):
        app = self._build_app()
        series = self._series()
        app.meetings = list(series)

        with patch.object(app.view, "show_toast"), patch.object(app.view, "show_form_feedback"):
            app.handle_save(self._payload_for("series-0"))

        by_id = {m.id: m for m in app.meetings}
        self.assertEqual(len(by_id), 3)
        expected_dates = {"series-0": "2026-08-10", "series-1": "2026-08-11", "series-2": "2026-08-12"}
        for meeting_id, meeting in by_id.items():
            own_date, _, own_time = meeting.datetime.partition("T")
            self.assertEqual(own_date, expected_dates[meeting_id], "each occurrence keeps its OWN date")
            self.assertEqual(own_time, "10:30", "the new time-of-day applies to every occurrence")
            self.assertEqual(meeting.workName, "Updated Corp")
            self.assertEqual(meeting.title, "Updated Standup")
            self.assertEqual(meeting.reminderMinutes, 20)
            self.assertEqual(meeting.durationMinutes, 45)
            self.assertEqual(meeting.soundProfile, "urgent")
            self.assertEqual(meeting.teamsUrl, "https://teams.example.com/updated")
            self.assertEqual(meeting.notes, "Updated notes")
            self.assertFalse(meeting.reminderSent, "editing the series re-arms both alerts")
            self.assertFalse(meeting.startSent)
            # Untouched by design -- see `_save_edit_series`'s own docstring.
            self.assertEqual(meeting.recurrenceType, "weekly")
            self.assertEqual(meeting.seriesId, "s1")
            self.assertEqual(meeting.seriesSize, 3)

        # And actually persisted, not just mutated in memory.
        on_disk = {m.id: m for m in storage.load_meetings()}
        self.assertEqual(on_disk["series-1"].workName, "Updated Corp")
        self.assertEqual(on_disk["series-1"].datetime, "2026-08-11T10:30")

    def test_edit_series_does_not_touch_an_unrelated_second_series_or_standalone_meetings(self):
        app = self._build_app()
        series_a = self._series()
        series_b = [
            _meeting(f"b{i}", seriesId="sB", recurrenceType="weekly", datetime=f"2026-09-{10 + i:02d}T09:00")
            for i in range(2)
        ]
        standalone = _meeting("standalone", seriesId="", recurrenceType="none", datetime="2026-10-01T08:00")
        app.meetings = series_a + series_b + [standalone]
        untouched = {m.id: (m.workName, m.title, m.datetime) for m in series_b + [standalone]}

        with patch.object(app.view, "show_toast"), patch.object(app.view, "show_form_feedback"):
            app.handle_save(self._payload_for("series-1"))

        by_id = {m.id: m for m in app.meetings}
        for meeting_id, snapshot in untouched.items():
            meeting = by_id[meeting_id]
            self.assertEqual((meeting.workName, meeting.title, meeting.datetime), snapshot)

    def test_target_with_empty_series_id_shows_error_and_touches_nothing(self):
        """Same defensive guard as `handle_delete_series`'s own -- unreachable
        from the real UI today (the menu only offers "Editar serie completa"
        when `series_occurrence_count > 1`), kept as a second line of
        defense, not the first."""
        app = self._build_app()
        standalone = _meeting("standalone", seriesId="", recurrenceType="none", datetime="2026-08-20T10:00")
        app.meetings = [standalone]
        before = (standalone.workName, standalone.title, standalone.datetime)

        feedback_mock = MagicMock()
        with patch.object(app.view, "show_form_feedback", feedback_mock):
            app.handle_save(self._payload_for("standalone"))

        meeting = app.meetings[0]
        self.assertEqual((meeting.workName, meeting.title, meeting.datetime), before)
        feedback_mock.assert_called_once()

    def test_nonexistent_meeting_id_is_a_no_op(self):
        app = self._build_app()
        series = self._series()
        app.meetings = list(series)
        before = [(m.id, m.workName, m.title, m.datetime) for m in app.meetings]

        with patch.object(app.view, "show_form_feedback"):
            app.handle_save(self._payload_for("does-not-exist"))

        after = [(m.id, m.workName, m.title, m.datetime) for m in app.meetings]
        self.assertEqual(after, before)

    def test_toast_and_form_feedback_report_the_real_occurrence_count(self):
        app = self._build_app()
        app.meetings = self._series()

        toast_mock = MagicMock()
        feedback_mock = MagicMock()
        with patch.object(app.view, "show_toast", toast_mock), patch.object(
            app.view, "show_form_feedback", feedback_mock
        ):
            app.handle_save(self._payload_for("series-0"))

        toast_mock.assert_called_once()
        self.assertIn("3", toast_mock.call_args[0][0])
        feedback_mock.assert_called_once()
        self.assertIn("3", feedback_mock.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
