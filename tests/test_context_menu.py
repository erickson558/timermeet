"""Tests for the month/week right-click context menu (SDD.md v2.10.0):
right-click on an existing entry shows "Editar"/"Eliminar" and each does the
same thing left-click-to-edit / the list view's own delete button already
do; right-click on empty cell/slot background shows "Nueva reunión" and
behaves exactly like the existing left-click-to-create flow; right-click on
"+N más" does nothing (unchanged non-goal). Also covers the new
`<Button-3>` bindings' own leak-safety (reusing `_rebind`, same as
`<Button-1>`) and the single, long-lived `tk.Menu`'s reuse across many
right-clicks.

`tk_popup()` on Windows uses the native Win32 popup-menu API
(`TrackPopupMenu`), which blocks pumping real Windows messages until a
human dismisses the menu (click-away/Escape) -- confirmed directly in this
environment: a bare `menu.tk_popup(...)` call with nothing to dismiss it
hangs indefinitely. There is no synthetic/virtual event that can dismiss a
*native* Windows menu the way `event_generate` can for an ordinary Tk
widget, so no test here ever calls the real `MainWindow._show_context_menu`/
`tk_popup()` path -- every test patches `_show_context_menu` to a no-op
recorder instead. That still exercises everything this module's own code is
responsible for (which handler populates the menu with which entries, that
each entry's command does the right thing, and that the `<Button-3>`
`.bind()` calls are leak-safe) without depending on `tk_popup()`'s own
already-mature (not this app's) native-menu behavior."""

import unittest
from datetime import date, timedelta
from unittest.mock import patch

from tests.testutils import count_tcl_commands
from timermeet_app import i18n

try:
    import tkinter as tk

    from timermeet_app import main_window
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    main_window = None


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
        "on_delete_series": _no_op,
        "on_set_app_theme": _no_op, "on_gadget_resize": _no_op,
    }
    fields.update(overrides)
    return main_window.Callbacks(**fields)


def _blank_calendar_cell(day: date) -> "main_window.CalendarCellData":
    return main_window.CalendarCellData(day=day, in_current_month=True, is_today=False, entries=[], overflow_count=0)


def _calendar_cell_with_entry(
    day: date, meeting_id: str, series_occurrence_count: int = 0
) -> "main_window.CalendarCellData":
    entry = main_window.CalendarEntry(
        meeting_id=meeting_id, time_text="09:00", title="Standup", color="#ffffff",
        series_occurrence_count=series_occurrence_count,
    )
    return main_window.CalendarCellData(day=day, in_current_month=True, is_today=False, entries=[entry], overflow_count=0)


def _blank_week_cell(day: date, hour: int) -> "main_window.WeekCellData":
    return main_window.WeekCellData(day=day, hour=hour, entries=[], overflow_count=0)


def _week_cell_with_entry(
    day: date, hour: int, meeting_id: str, series_occurrence_count: int = 0
) -> "main_window.WeekCellData":
    entry = main_window.CalendarEntry(
        meeting_id=meeting_id, time_text="09:00", title="Standup", color="#ffffff",
        series_occurrence_count=series_occurrence_count,
    )
    return main_window.WeekCellData(day=day, hour=hour, entries=[entry], overflow_count=0)


def _full_week(monday: date, filled, filled_row: int, filled_col: int):
    cells = []
    for row in range(main_window.WEEK_ROWS):
        for col in range(main_window.WEEK_COLS):
            if row == filled_row and col == filled_col:
                cells.append(filled)
            else:
                cells.append(_blank_week_cell(monday + timedelta(days=col), row))
    return cells


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class ContextMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        # Not withdrawn: event_generate("<Button-3>") needs the widget
        # actually mapped, same reasoning as test_calendar_day_click.py.
        cls.root.geometry("1000x700+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def setUp(self):
        # Never call the real tk_popup() -- see module docstring. Every test
        # gets a fresh spy so assertions about "was the menu even shown"
        # don't leak between tests.
        self.popup_calls = []
        self._popup_patch = patch.object(
            self.view, "_show_context_menu", side_effect=lambda event: self.popup_calls.append(event)
        )
        self._popup_patch.start()
        self.addCleanup(self._popup_patch.stop)

    def _menu_labels(self):
        menu = self.view._context_menu
        last = menu.index("end")
        if last is None:
            return []
        return [menu.entrycget(i, "label") for i in range(last + 1)]

    # -- month view -----------------------------------------------------------

    def test_right_click_on_calendar_entry_shows_edit_and_delete(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1")] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]

        widgets.entry_labels[0].event_generate("<Button-3>")

        self.assertEqual(len(self.popup_calls), 1, "must show the popup exactly once")
        self.assertEqual(self._menu_labels(), [i18n.t("edit", "es"), i18n.t("delete", "es")])

    def test_calendar_entry_menu_edit_entry_edits_like_left_click(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1")] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]
        calls = {"edited": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_edit=lambda mid: calls.__setitem__("edited", mid),
            on_set_active_view=lambda v: calls["views"].append(v),
        )

        widgets.entry_labels[0].event_generate("<Button-3>")
        self.view._context_menu.invoke(0)  # "Editar"

        self.assertEqual(calls["edited"], "meeting-1")
        self.assertEqual(calls["views"], ["list"])

    def test_calendar_entry_menu_delete_confirms_and_deletes_without_switching_view(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1")] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]
        calls = {"deleted": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_delete=lambda mid: calls.__setitem__("deleted", mid),
            on_set_active_view=lambda v: calls["views"].append(v),
        )

        widgets.entry_labels[0].event_generate("<Button-3>")
        with patch.object(main_window.messagebox, "askyesno", return_value=True) as askyesno:
            self.view._context_menu.invoke(1)  # "Eliminar"
            askyesno.assert_called_once_with(i18n.t("delete", "es"), i18n.t("deleteConfirm", "es"))

        self.assertEqual(calls["deleted"], "meeting-1")
        self.assertEqual(calls["views"], [], "delete from the context menu must not switch views")

    def test_calendar_entry_menu_delete_declined_does_not_delete(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1")] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]
        calls = {"deleted": None}
        self.view.callbacks = _make_callbacks(on_delete=lambda mid: calls.__setitem__("deleted", mid))

        widgets.entry_labels[0].event_generate("<Button-3>")
        with patch.object(main_window.messagebox, "askyesno", return_value=False):
            self.view._context_menu.invoke(1)  # "Eliminar", declined

        self.assertIsNone(calls["deleted"])

    def test_right_click_on_empty_calendar_cell_shows_new_meeting_and_creates(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 22)
        cells = [_blank_calendar_cell(target)] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]
        calls = {"day": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_calendar_day_click=lambda d: calls.__setitem__("day", d),
            on_set_active_view=lambda v: calls["views"].append(v),
        )

        widgets.frame.event_generate("<Button-3>")

        self.assertEqual(self._menu_labels(), [i18n.t("contextMenuNewMeeting", "es")])
        self.view._context_menu.invoke(0)
        self.assertEqual(calls["day"], target)
        self.assertEqual(calls["views"], ["list"])

    def test_right_click_on_calendar_overflow_label_shows_no_menu(self):
        """"+N más" stays non-interactive for right-click too -- same
        non-goal already vigente for left-click since v2.7.0/v2.8.0."""
        self.view.set_active_view("calendar")
        self.root.update()
        entry = main_window.CalendarEntry(meeting_id="m1", time_text="09:00", title="A", color="#fff")
        overflow_cell = main_window.CalendarCellData(
            day=date(2026, 8, 23), in_current_month=True, is_today=False,
            entries=[entry, entry, entry], overflow_count=5,
        )
        cells = [overflow_cell] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]

        widgets.overflow_label.event_generate("<Button-3>")

        self.assertEqual(self.popup_calls, [], "the overflow label must never show a context menu")

    # -- "Eliminar serie completa" (SDD.md v2.11.0) -----------------------------

    def test_right_click_on_calendar_entry_with_no_live_siblings_hides_delete_series(self):
        """`series_occurrence_count` of 0 (not part of an active recurring
        series) or 1 (recurring, but only one occurrence exists right now)
        must both leave the menu at exactly 2 items -- "Eliminar serie
        completa" only ever appears at 2+."""
        self.view.set_active_view("calendar")
        self.root.update()
        for count in (0, 1):
            target = date(2026, 8, 21)
            cells = [_calendar_cell_with_entry(target, "meeting-1", series_occurrence_count=count)] + [
                _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
            ]
            self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
            widgets = self.view._calendar_cells[0]

            widgets.entry_labels[0].event_generate("<Button-3>")

            self.assertEqual(
                self._menu_labels(), [i18n.t("edit", "es"), i18n.t("delete", "es")],
                f"series_occurrence_count={count} must not offer 'Eliminar serie completa'",
            )

    def test_right_click_on_calendar_entry_with_live_siblings_shows_delete_series(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1", series_occurrence_count=3)] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]

        widgets.entry_labels[0].event_generate("<Button-3>")

        self.assertEqual(
            self._menu_labels(), [i18n.t("edit", "es"), i18n.t("delete", "es"), i18n.t("deleteSeries", "es")]
        )

    def test_calendar_entry_menu_delete_series_confirms_with_count_and_calls_on_delete_series(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1", series_occurrence_count=5)] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]
        calls = {"deleted_series": None}
        self.view.callbacks = _make_callbacks(on_delete_series=lambda mid: calls.__setitem__("deleted_series", mid))

        widgets.entry_labels[0].event_generate("<Button-3>")
        with patch.object(main_window.messagebox, "askyesno", return_value=True) as askyesno:
            self.view._context_menu.invoke(2)  # "Eliminar serie completa"
            askyesno.assert_called_once_with(
                i18n.t("deleteSeries", "es"), i18n.format_text("deleteSeriesConfirm", "es", count=5)
            )

        self.assertEqual(calls["deleted_series"], "meeting-1")

    def test_calendar_entry_menu_delete_series_declined_does_not_call_callback(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1", series_occurrence_count=2)] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]
        calls = {"deleted_series": None}
        self.view.callbacks = _make_callbacks(on_delete_series=lambda mid: calls.__setitem__("deleted_series", mid))

        widgets.entry_labels[0].event_generate("<Button-3>")
        with patch.object(main_window.messagebox, "askyesno", return_value=False):
            self.view._context_menu.invoke(2)

        self.assertIsNone(calls["deleted_series"])

    # -- week view --------------------------------------------------------------

    def test_right_click_on_week_entry_shows_edit_and_delete(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1")
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]

        widgets.entry_labels[0].event_generate("<Button-3>")

        self.assertEqual(self._menu_labels(), [i18n.t("edit", "es"), i18n.t("delete", "es")])

    def test_week_entry_menu_edit_edits_like_left_click(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1")
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]
        calls = {"edited": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_edit=lambda mid: calls.__setitem__("edited", mid),
            on_set_active_view=lambda v: calls["views"].append(v),
        )

        widgets.entry_labels[0].event_generate("<Button-3>")
        self.view._context_menu.invoke(0)

        self.assertEqual(calls["edited"], "meeting-week-1")
        self.assertEqual(calls["views"], ["list"])

    def test_week_entry_menu_delete_confirms_and_deletes_without_switching_view(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1")
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]
        calls = {"deleted": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_delete=lambda mid: calls.__setitem__("deleted", mid),
            on_set_active_view=lambda v: calls["views"].append(v),
        )

        widgets.entry_labels[0].event_generate("<Button-3>")
        with patch.object(main_window.messagebox, "askyesno", return_value=True):
            self.view._context_menu.invoke(1)

        self.assertEqual(calls["deleted"], "meeting-week-1")
        self.assertEqual(calls["views"], [])

    def test_right_click_on_empty_week_slot_shows_new_meeting_and_creates(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        target_hour = 14
        target_day = monday + timedelta(days=2)
        cell = _blank_week_cell(target_day, target_hour)
        cells = _full_week(monday, cell, filled_row=target_hour, filled_col=2)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[target_hour * main_window.WEEK_COLS + 2]
        calls = {"slot": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_week_slot_click=lambda d, h: calls.__setitem__("slot", (d, h)),
            on_set_active_view=lambda v: calls["views"].append(v),
        )

        widgets.frame.event_generate("<Button-3>")

        self.assertEqual(self._menu_labels(), [i18n.t("contextMenuNewMeeting", "es")])
        self.view._context_menu.invoke(0)
        self.assertEqual(calls["slot"], (target_day, target_hour))
        self.assertEqual(calls["views"], ["list"])

    def test_right_click_on_week_overflow_label_shows_no_menu(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        entry1 = main_window.CalendarEntry(meeting_id="m1", time_text="09:00", title="A", color="#fff")
        entry2 = main_window.CalendarEntry(meeting_id="m2", time_text="09:15", title="B", color="#fff")
        overflow_cell = main_window.WeekCellData(day=monday, hour=9, entries=[entry1, entry2], overflow_count=3)
        cells = _full_week(monday, overflow_cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]

        widgets.overflow_label.event_generate("<Button-3>")

        self.assertEqual(self.popup_calls, [])

    # -- "Eliminar serie completa" (SDD.md v2.11.0), week view ------------------

    def test_right_click_on_week_entry_with_no_live_siblings_hides_delete_series(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        for count in (0, 1):
            cell = _week_cell_with_entry(monday, 9, "meeting-week-1", series_occurrence_count=count)
            cells = _full_week(monday, cell, filled_row=9, filled_col=0)
            self.view.render_week_grid(
                "10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells
            )
            widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]

            widgets.entry_labels[0].event_generate("<Button-3>")

            self.assertEqual(
                self._menu_labels(), [i18n.t("edit", "es"), i18n.t("delete", "es")],
                f"series_occurrence_count={count} must not offer 'Eliminar serie completa'",
            )
        self.view.clear_week_selection()

    def test_right_click_on_week_entry_with_live_siblings_shows_delete_series(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1", series_occurrence_count=4)
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]

        widgets.entry_labels[0].event_generate("<Button-3>")

        self.assertEqual(
            self._menu_labels(), [i18n.t("edit", "es"), i18n.t("delete", "es"), i18n.t("deleteSeries", "es")]
        )
        self.view.clear_week_selection()

    def test_week_entry_menu_delete_series_confirms_with_count_and_calls_on_delete_series(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1", series_occurrence_count=6)
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]
        calls = {"deleted_series": None}
        self.view.callbacks = _make_callbacks(on_delete_series=lambda mid: calls.__setitem__("deleted_series", mid))

        widgets.entry_labels[0].event_generate("<Button-3>")
        with patch.object(main_window.messagebox, "askyesno", return_value=True) as askyesno:
            self.view._context_menu.invoke(2)
            askyesno.assert_called_once_with(
                i18n.t("deleteSeries", "es"), i18n.format_text("deleteSeriesConfirm", "es", count=6)
            )

        self.assertEqual(calls["deleted_series"], "meeting-week-1")
        self.view.clear_week_selection()

    def test_right_click_on_week_entry_also_selects_it_as_a_side_effect(self):
        """SDD.md v2.11.0's explicit decision: right-click on an entry
        selects it too (Windows' own precedent), so the action toolbar
        never disagrees with what the context menu is about to act on."""
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1")
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]

        widgets.entry_labels[0].event_generate("<Button-3>")

        self.assertEqual(self.view._week_selected_meeting_id, "meeting-week-1")
        self.assertEqual(str(self.view.week_edit_button["state"]), "normal")
        self.assertEqual(str(self.view.week_delete_button["state"]), "normal")
        self.view.clear_week_selection()

    def test_right_click_on_empty_week_slot_does_not_touch_an_existing_selection(self):
        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1")
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        entry_widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]
        slot_widgets = self.view._week_cells[10 * main_window.WEEK_COLS + 1]
        entry_widgets.entry_labels[0].event_generate("<Button-1>")  # select it first
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-week-1")

        slot_widgets.frame.event_generate("<Button-3>")

        self.assertEqual(
            self.view._week_selected_meeting_id, "meeting-week-1",
            "right-click on empty slot background must not change or clear the selection",
        )
        self.view.clear_week_selection()

    # -- shared-menu / leak-safety proofs ---------------------------------------

    def test_context_menu_is_a_single_reused_widget_never_rebuilt(self):
        menu_identity = id(self.view._context_menu)
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1")] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        widgets = self.view._calendar_cells[0]
        for _ in range(20):
            widgets.entry_labels[0].event_generate("<Button-3>")
        self.assertEqual(id(self.view._context_menu), menu_identity)

    def test_repeated_right_clicks_on_the_same_cells_do_not_leak_tcl_commands(self):
        """SDD.md's own acceptance criterion: 500+ repeated right-clicks
        (simulated, no real `sleep()`) over the same cells must leave the
        Tcl command count unchanged -- checked via the CORRECTED metric
        (`count_tcl_commands`/`info commands`), not `root._tclCommands` (see
        `tests/testutils.py`). Exercises both the entry-menu path (delete +
        re-add 2 commands each click, safe per `tkinter.Menu.delete`'s own
        `deletecommand` behavior) and the empty-slot path (1 command each
        click) on both month and week cells."""
        self.view.set_active_view("calendar")
        self.root.update()
        target = date(2026, 8, 21)
        cells = [_calendar_cell_with_entry(target, "meeting-1")] + [
            _blank_calendar_cell(date(2025, 12, 1) + timedelta(days=i)) for i in range(41)
        ]
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        entry_widgets = self.view._calendar_cells[0]
        day_widgets = self.view._calendar_cells[1]

        self.view.set_active_view("week")
        self.root.update()
        monday = date(2026, 8, 10)
        week_cell = _week_cell_with_entry(monday, 9, "meeting-week-1")
        week_cells = _full_week(monday, week_cell, filled_row=9, filled_col=0)
        self.view.render_week_grid(
            "10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], week_cells
        )
        week_entry_widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]
        week_slot_widgets = self.view._week_cells[10 * main_window.WEEK_COLS + 1]

        # Settle the live "now" line's own cold-start geometry retry (see
        # `_apply_week_now_line`'s docstring and
        # `tests/test_bind_leak_fixes.py`'s identical settle step) BEFORE
        # capturing the baseline -- an unsettled retry job is a real,
        # legitimate pending `after()` Tcl command unrelated to the
        # right-click bindings under test here, but self-cancels the moment
        # it happens to fire during this test's own event processing,
        # which would otherwise read as a false "-1" leak signal.
        attempts = 0
        while self.view._week_live_retry_job is not None and attempts <= main_window._WEEK_LINE_MAX_RETRIES:
            self.root.after_cancel(self.view._week_live_retry_job)
            self.view._apply_week_now_line()
            attempts += 1

        # `self._context_menu` is ONE shared widget re-populated with a
        # different number of entries depending on which kind of cell was
        # right-clicked last (2 for an entry: "Editar"/"Eliminar"; 1 for an
        # empty slot: "Nueva reunión") -- by design, see SDD.md v2.10.0. So
        # the *absolute* Tcl command count depends not just on "did this
        # leak" but also on "how many menu items happen to be populated
        # right now", which has nothing to do with a leak. This one warm-up
        # click (matching the exact same kind -- a slot click -- that the
        # loop below always ends on) normalizes the menu into that same
        # resting state BEFORE the baseline is captured, so the baseline and
        # the post-loop count are directly comparable: both are "right after
        # a slot click", eliminating that unrelated variable rather than
        # fighting it with a tolerance.
        week_slot_widgets.frame.event_generate("<Button-3>")

        baseline = count_tcl_commands(self.root)
        for _ in range(150):
            entry_widgets.entry_labels[0].event_generate("<Button-3>")
            day_widgets.frame.event_generate("<Button-3>")
            week_entry_widgets.entry_labels[0].event_generate("<Button-3>")
            week_slot_widgets.frame.event_generate("<Button-3>")
        # 150 iterations x 4 right-clicks/iteration = 600 popups.
        self.assertEqual(
            count_tcl_commands(self.root), baseline,
            "600 repeated right-clicks over unchanged cells must not leak Tcl commands",
        )

    # -- gadget skin menu vs. keep_gadget_on_top (SDD.md v2.13.0) -------------

    def test_keep_gadget_on_top_is_noop_while_skin_menu_open(self):
        """Regression test: `keep_gadget_on_top` is heartbeat-driven (every
        1s) and used to unconditionally call `root.lift()` +
        `root.attributes("-topmost", True)` even while the gadget skin
        picker's native popup menu was on screen. On Windows, `tk_popup()`
        posts a native popup menu that owns a nested Win32 message loop on
        the same thread, but Tcl's `after()` timer still gets dispatched
        through that nested loop -- so the heartbeat kept firing while the
        menu was open, and every z-order/foreground reassertion is exactly
        what makes Windows auto-dismiss a native popup menu. `_gadget_menu_open`
        (set for the whole duration of `_show_gadget_skin_menu`'s
        `_show_context_menu` call) must make this call a true no-op."""
        self.view._gadget_active = True
        self.view._gadget_menu_open = True
        try:
            with patch.object(self.view.root, "lift") as mock_lift, \
                    patch.object(self.view.root, "attributes") as mock_attributes:
                self.view.keep_gadget_on_top(is_alarm_active=False)
            mock_lift.assert_not_called()
            mock_attributes.assert_not_called()
        finally:
            self.view._gadget_active = False
            self.view._gadget_menu_open = False

    def test_keep_gadget_on_top_still_reasserts_topmost_when_menu_closed(self):
        """Companion to the test above: confirms the guard is specific to
        `_gadget_menu_open`, not an accidental blanket no-op -- gadget mode
        active with the menu closed must still lift/re-pin as before."""
        self.view._gadget_active = True
        self.view._gadget_menu_open = False
        try:
            with patch.object(self.view.root, "lift") as mock_lift, \
                    patch.object(self.view.root, "attributes") as mock_attributes:
                self.view.keep_gadget_on_top(is_alarm_active=False)
            mock_lift.assert_called_once()
            mock_attributes.assert_called_once_with("-topmost", True)
        finally:
            self.view._gadget_active = False


if __name__ == "__main__":
    unittest.main()
