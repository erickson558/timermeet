"""Tests for creating a new meeting from the calendar view (SDD.md v2.8.0):
clicking a day cell's number/background clears the form and pre-fills only
the date, mirroring the existing click-a-meeting-entry-to-edit flow
(`_handle_calendar_entry_click`) without disturbing it.

Builds a real `MainWindow` (real `tk.Tk()`/`tk.Canvas`/`tk.Label` widgets),
so this whole module is skipped automatically if no display is available,
same as `tests/test_alarm_queue.py`. Unlike that file, every test here
shares one `tk.Tk()`/`MainWindow` built once in `setUpClass` instead of one
per test: mapping this app's full widget tree (header x2 + form + summary +
42 calendar cells) on screen for the first time -- required for
`event_generate("<Button-1>")` to reach a real bound handler at all, a
withdrawn root never delivers synthetic click events -- measured at ~3.5s on
this hardware, all in that one first `root.update()` call; every later
`render_calendar`/`update()` call is under half a second. Sharing the window
avoids paying that fixed cost five times over. Each test still gets its own
isolated `Callbacks` (swapped onto `view.callbacks`, read at click-time, not
bind-time) and its own freshly rendered cell data, so there is no behavioral
cross-test leakage -- only the widget tree itself is reused."""

import unittest
from datetime import date, timedelta

from timermeet_app import models

try:
    import tkinter as tk

    from timermeet_app import main_window
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    main_window = None


def _no_op(*_args, **_kwargs):
    return None


def _make_callbacks(**overrides):
    """A `Callbacks` bundle where every field is a no-op unless overridden --
    tests only care about the handful of callbacks their scenario exercises."""
    fields = {
        "on_save": _no_op,
        "on_clear": _no_op,
        "on_edit": _no_op,
        "on_delete": _no_op,
        "on_open_link": _no_op,
        "on_test_sound": _no_op,
        "on_set_now": _no_op,
        "on_toggle_language": _no_op,
        "on_test_notification": _no_op,
        "on_filter_change": _no_op,
        "on_clear_past": _no_op,
        "on_exit": _no_op,
        "on_add_company": _no_op,
        "on_remove_company": _no_op,
        "on_toggle_gadget_mode": _no_op,
        "on_enter_tray_mode": _no_op,
        "on_set_active_view": _no_op,
        "on_calendar_prev_month": _no_op,
        "on_calendar_next_month": _no_op,
        "on_calendar_today": _no_op,
        "on_calendar_day_click": _no_op,
        "on_week_prev": _no_op,
        "on_week_next": _no_op,
        "on_week_today": _no_op,
        "on_week_slot_click": _no_op,
        "on_toggle_week_column_mode": _no_op,
        "on_delete_series": _no_op,
    }
    fields.update(overrides)
    return main_window.Callbacks(**fields)


def _blank_cell(day: date) -> "main_window.CalendarCellData":
    return main_window.CalendarCellData(
        day=day, in_current_month=True, is_today=False, entries=[], overflow_count=0,
    )


def _cell_with_entry(day: date, meeting_id: str) -> "main_window.CalendarCellData":
    entry = main_window.CalendarEntry(meeting_id=meeting_id, time_text="09:00", title="Standup", color="#ffffff")
    return main_window.CalendarCellData(
        day=day, in_current_month=True, is_today=False, entries=[entry], overflow_count=0,
    )


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class CalendarDayClickCreateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        # Not withdrawn: `event_generate("<Button-1>")` in these tests needs
        # the widget actually mapped to dispatch to a real bound handler --
        # confirmed empirically that a withdrawn root's widgets never
        # receive synthetic Button-1/Enter/Leave events at all.
        cls.root.geometry("300x300+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())
        # A calendar cell's widgets only actually receive synthetic click
        # events once `calendar_view` is the gridded (mapped) frame -- by
        # default `MainWindow` starts on the list view (see
        # `_build_layout`), which leaves `calendar_view` and its 42 cells
        # built but ungridded.
        cls.view.set_active_view("calendar")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def _render_single_cell(self, cell) -> "main_window._CalendarCellWidgets":
        """Renders one real cell (position 0) via the same `render_calendar`
        path app.py uses, padding the other 41 with distinct blank days so
        the call shape matches production (42 cells, one call)."""
        cells = [cell] + [_blank_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)]
        self.view.render_calendar("Enero 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        return self.view._calendar_cells[0]

    def test_clicking_the_day_number_prefills_only_the_date_and_switches_view(self):
        calls = {"day": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_calendar_day_click=lambda d: calls.__setitem__("day", d),
            on_set_active_view=lambda view: calls["views"].append(view),
        )
        target = date(2026, 8, 21)
        widgets = self._render_single_cell(_blank_cell(target))

        widgets.day_label.event_generate("<Button-1>")

        self.assertEqual(calls["day"], target)
        self.assertEqual(calls["views"], ["list"])

    def test_clicking_empty_cell_background_behaves_like_clicking_the_day_number(self):
        calls = {"day": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_calendar_day_click=lambda d: calls.__setitem__("day", d),
            on_set_active_view=lambda view: calls["views"].append(view),
        )
        target = date(2026, 8, 22)
        widgets = self._render_single_cell(_blank_cell(target))

        widgets.frame.event_generate("<Button-1>")

        self.assertEqual(calls["day"], target)
        self.assertEqual(calls["views"], ["list"])

    def test_clicking_empty_background_of_a_cell_that_also_has_meetings_still_creates(self):
        """A cell with existing meetings still has clickable empty
        background around its entries (SDD.md v2.8.0: 'clic en el fondo
        vacío de una celda... con reuniones' must behave like an empty
        cell, not accidentally fall back to edit)."""
        calls = {"day": None, "edited": None}
        self.view.callbacks = _make_callbacks(
            on_calendar_day_click=lambda d: calls.__setitem__("day", d),
            on_edit=lambda mid: calls.__setitem__("edited", mid),
        )
        target = date(2026, 8, 24)
        widgets = self._render_single_cell(_cell_with_entry(target, "meeting-456"))

        widgets.frame.event_generate("<Button-1>")

        self.assertEqual(calls["day"], target)
        self.assertIsNone(calls["edited"], "clicking the cell's own background must never trigger edit")

    def test_clicking_an_existing_entry_still_edits_and_does_not_trigger_day_click(self):
        edit_calls = []
        day_click_calls = []
        self.view.callbacks = _make_callbacks(
            on_edit=lambda mid: edit_calls.append(mid),
            on_calendar_day_click=lambda d: day_click_calls.append(d),
        )
        target = date(2026, 8, 23)
        widgets = self._render_single_cell(_cell_with_entry(target, "meeting-123"))

        # Tkinter does not propagate a child widget's click up to its parent
        # -- clicking the meeting entry must fire only its own binding, never
        # the cell frame's, even though the entry is a child of that frame.
        widgets.entry_labels[0].event_generate("<Button-1>")

        self.assertEqual(edit_calls, ["meeting-123"])
        self.assertEqual(day_click_calls, [], "clicking an entry must not also fire the day-click handler")

    def test_navigating_months_rebinds_the_same_grid_position_to_the_new_date(self):
        """Direct proof the rebind-per-render pattern works: the SAME cell
        widget (grid position 0) must invoke on_calendar_day_click with
        whichever date was rendered most recently, never a stale date from
        a previously-visited month (see SDD.md's explicit acceptance
        criterion for this)."""
        calls = []
        self.view.callbacks = _make_callbacks(on_calendar_day_click=lambda d: calls.append(d))

        august_1 = date(2026, 8, 1)
        widgets = self._render_single_cell(_blank_cell(august_1))
        widgets.day_label.event_generate("<Button-1>")

        september_1 = date(2026, 9, 1)
        # Re-render the very same grid position (index 0) with a new month's
        # date, exactly like Prev/Next month navigation would in app.py.
        self._render_single_cell(_blank_cell(september_1))
        widgets.day_label.event_generate("<Button-1>")

        self.assertEqual(calls, [august_1, september_1])

    def test_navigating_months_rebinds_the_same_grid_position_to_the_new_date_via_frame(self):
        """Same proof as
        `test_navigating_months_rebinds_the_same_grid_position_to_the_new_date`
        above, but for `widgets.frame` (the cell's background) rather than
        `widgets.day_label`. `_update_calendar_cell` rebinds a fresh closure
        to BOTH widgets on every render (see main_window.py); a bug that
        rebinds only one of them -- e.g. accidentally reusing the frame's
        closure from construction time instead of rebinding it every call --
        would still pass the `day_label` variant above while leaving clicks
        on the cell background stuck firing whichever month was on screen
        the first time that grid position was ever rendered."""
        calls = []
        self.view.callbacks = _make_callbacks(on_calendar_day_click=lambda d: calls.append(d))

        august_1 = date(2026, 8, 1)
        widgets = self._render_single_cell(_blank_cell(august_1))
        widgets.frame.event_generate("<Button-1>")

        september_1 = date(2026, 9, 1)
        # Re-render the very same grid position (index 0) with a new month's
        # date, exactly like Prev/Next month navigation would in app.py.
        self._render_single_cell(_blank_cell(september_1))
        widgets.frame.event_generate("<Button-1>")

        self.assertEqual(calls, [august_1, september_1])

    def test_prefill_new_meeting_matches_clear_form_except_the_date(self):
        self.view.callbacks = _make_callbacks()

        # Populate the form with a real meeting first, so prefill_new_meeting
        # has to actually reset every field back to clear_form's defaults,
        # not just happen to already be blank.
        meeting = models.normalize_meeting(
            {
                "workName": "Acme", "title": "Old Meeting", "datetime": "2026-08-10T09:00",
                "reminderMinutes": 30, "teamsUrl": "https://teams.microsoft.com/x",
            }
        )
        self.view.populate_form(meeting)

        target = date(2026, 8, 25)
        self.view.prefill_new_meeting(target)

        self.assertEqual(self.view.meeting_id_var.get(), "", "must be a new meeting, not still editing the old one")
        self.assertEqual(self.view.work_entry.get(), "")
        self.assertEqual(self.view.title_entry.get(), "")
        self.assertEqual(self.view.date_entry.get(), target.isoformat())
        self.assertEqual(self.view.time_entry.get(), "")
        self.assertEqual(self.view.reminder_entry.get(), "15")
        self.assertEqual(self.view.url_entry.get(), "")


if __name__ == "__main__":
    unittest.main()
