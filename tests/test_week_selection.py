"""Tests for the week view's "last click" selection + action toolbar
(SDD.md v2.11.0): left-click on a week-view entry now selects it (accent
border, toolbar enablement) instead of editing directly -- a deliberate,
week-view-only behavior change. The month view's own click-to-edit is
untouched (see `tests/test_calendar_day_click.py`; one direct regression
check is also included here).

Builds a real `MainWindow` against a real `tk.Tk()`, shared across the whole
class (same setup style/cost tradeoff as `tests/test_week_view.py`'s
`WeekViewWidgetTests` and `tests/test_week_column_mode.py`'s
`WeekColumnModeWidgetTests`) -- `event_generate` needs a mapped widget to
reach a real bound handler."""

import unittest
from datetime import date, datetime, timedelta
from unittest import mock

from tests.testutils import count_tcl_commands

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


def _blank_week_cell(day: date, hour: int) -> "main_window.WeekCellData":
    return main_window.WeekCellData(day=day, hour=hour, entries=[], overflow_count=0)


def _week_cell_with_entry(day: date, hour: int, meeting_id: str) -> "main_window.WeekCellData":
    entry = main_window.CalendarEntry(meeting_id=meeting_id, time_text="09:00", title="Standup", color="#ffffff")
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


_HEADERS = ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"]
_MONDAY = date(2026, 8, 10)


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class WeekSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        cls.root.geometry("1180x760+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())
        cls.view.set_active_view("week")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def tearDown(self):
        # Shared class-level widget tree -- always leave selection cleared
        # and week view active so later tests never see leftover state.
        self.view.clear_week_selection()
        if self.view._primary_view != "week":
            self.view.set_active_view("week")
        if self.view._gadget_active:
            self.view.set_gadget_mode(False)
        self.view.set_week_column_mode("full")

    def _render_single_entry(self, meeting_id: str, row: int = 9, col: int = 0):
        cell = _week_cell_with_entry(_MONDAY + timedelta(days=col), row, meeting_id)
        cells = _full_week(_MONDAY, cell, filled_row=row, filled_col=col)
        self.view.render_week_grid("10-16 Ago 2026", _HEADERS, cells)
        return self.view._week_cells[row * main_window.WEEK_COLS + col], cells

    # -- left-click selects instead of editing (week-only) ----------------------

    def test_left_click_selects_entry_shows_border_does_not_edit_or_switch_view(self):
        calls = {"edited": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_edit=lambda mid: calls.__setitem__("edited", mid),
            on_set_active_view=lambda v: calls["views"].append(v),
        )
        widgets, _cells = self._render_single_entry("meeting-1")

        widgets.entry_labels[0].event_generate("<Button-1>")

        self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")
        self.assertEqual(int(widgets.entry_labels[0]["highlightthickness"]), 2)
        self.assertEqual(widgets.entry_labels[0]["highlightbackground"], main_window.ACCENT)
        self.assertIsNone(calls["edited"], "left-click in week view must not edit directly")
        self.assertEqual(calls["views"], [], "left-click in week view must not switch away from week")

    def test_left_click_on_already_selected_entry_is_idempotent(self):
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")

        widgets.entry_labels[0].event_generate("<Button-1>")  # click it again

        self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")
        self.assertEqual(int(widgets.entry_labels[0]["highlightthickness"]), 2)

    def test_left_click_on_a_different_entry_moves_the_selection(self):
        monday = _MONDAY
        entry_a = main_window.CalendarEntry(meeting_id="meeting-A", time_text="09:00", title="A", color="#fff")
        entry_b = main_window.CalendarEntry(meeting_id="meeting-B", time_text="10:00", title="B", color="#fff")
        cell_a = main_window.WeekCellData(day=monday, hour=9, entries=[entry_a], overflow_count=0)
        cell_b = main_window.WeekCellData(day=monday + timedelta(days=1), hour=9, entries=[entry_b], overflow_count=0)
        cells = []
        for row in range(main_window.WEEK_ROWS):
            for col in range(main_window.WEEK_COLS):
                if row == 9 and col == 0:
                    cells.append(cell_a)
                elif row == 9 and col == 1:
                    cells.append(cell_b)
                else:
                    cells.append(_blank_week_cell(monday + timedelta(days=col), row))
        self.view.render_week_grid("10-16 Ago 2026", _HEADERS, cells)
        widgets_a = self.view._week_cells[9 * main_window.WEEK_COLS + 0]
        widgets_b = self.view._week_cells[9 * main_window.WEEK_COLS + 1]

        widgets_a.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-A")
        self.assertEqual(int(widgets_a.entry_labels[0]["highlightthickness"]), 2)

        widgets_b.entry_labels[0].event_generate("<Button-1>")

        self.assertEqual(self.view._week_selected_meeting_id, "meeting-B")
        self.assertEqual(int(widgets_b.entry_labels[0]["highlightthickness"]), 2)
        self.assertEqual(
            int(widgets_a.entry_labels[0]["highlightthickness"]), 0,
            "the previously-selected entry's border must be cleared when selection moves",
        )

    def test_left_click_on_empty_slot_still_creates_regardless_of_a_prior_selection(self):
        """Regression: SDD.md's explicit "unchanged" call for empty-cell
        click -- must behave identically whether or not some other entry
        happens to already be selected."""
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")

        calls = {"slot": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_week_slot_click=lambda d, h: calls.__setitem__("slot", (d, h)),
            on_set_active_view=lambda v: calls["views"].append(v),
        )
        empty_widgets = self.view._week_cells[14 * main_window.WEEK_COLS + 3]

        empty_widgets.frame.event_generate("<Button-1>")

        self.assertEqual(calls["slot"], (_MONDAY + timedelta(days=3), 14))
        self.assertEqual(calls["views"], ["list"])

    # -- backstop: render_week_grid re-validates the selection -------------------

    def test_render_week_grid_clears_selection_when_the_selected_meeting_is_no_longer_visible(self):
        widgets, _cells = self._render_single_entry("meeting-gone")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-gone")

        blank_cells = _full_week(_MONDAY, _blank_week_cell(_MONDAY, 9), filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", _HEADERS, blank_cells)

        self.assertIsNone(self.view._week_selected_meeting_id)
        self.assertEqual(str(self.view.week_edit_button["state"]), "disabled")
        self.assertEqual(str(self.view.week_delete_button["state"]), "disabled")

    def test_selection_border_survives_a_real_rerender_via_the_camino_2_fallback(self):
        """`_update_week_cell` re-derives the highlight from
        `self._week_selected_meeting_id` on every real render (camino 2),
        independent of the immediate click path (camino 1) -- proven here
        by re-rendering the SAME still-selected entry and checking the
        border is still applied."""
        widgets, cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(int(widgets.entry_labels[0]["highlightthickness"]), 2)

        self.view.render_week_grid("10-16 Ago 2026", _HEADERS, cells)  # a second, real re-render

        self.assertEqual(
            int(widgets.entry_labels[0]["highlightthickness"]), 2,
            "a real re-render must not silently drop a still-valid selection's border",
        )

    # -- action toolbar -----------------------------------------------------------

    def test_editar_and_eliminar_disabled_without_selection_enabled_with_selection(self):
        self.assertEqual(str(self.view.week_edit_button["state"]), "disabled")
        self.assertEqual(str(self.view.week_delete_button["state"]), "disabled")

        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")

        self.assertEqual(str(self.view.week_edit_button["state"]), "normal")
        self.assertEqual(str(self.view.week_delete_button["state"]), "normal")

        self.view.clear_week_selection()

        self.assertEqual(str(self.view.week_edit_button["state"]), "disabled")
        self.assertEqual(str(self.view.week_delete_button["state"]), "disabled")

    def test_editar_button_acts_on_the_currently_selected_id_read_at_click_time(self):
        calls = {"edited": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_edit=lambda mid: calls.__setitem__("edited", mid),
            on_set_active_view=lambda v: calls["views"].append(v),
        )
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")

        self.view.week_edit_button.invoke()
        self.assertEqual(calls["edited"], "meeting-1")
        self.assertEqual(calls["views"], ["list"])

        # Move the selection to a different id -- the SAME button object
        # (never rebuilt) must now act on the NEW id, proving the lambda
        # reads `self._week_selected_meeting_id` live, not a value captured
        # once when the button was constructed.
        widgets2, _cells2 = self._render_single_entry("meeting-2", row=10, col=1)
        widgets2.entry_labels[0].event_generate("<Button-1>")
        self.view.week_edit_button.invoke()
        self.assertEqual(calls["edited"], "meeting-2")

    def test_eliminar_button_reuses_the_single_occurrence_confirm_delete_flow(self):
        """Deliberately the SINGLE-occurrence delete, never "Eliminar serie
        completa" (SDD.md's explicit non-goal for the toolbar)."""
        calls = {"deleted": None}
        self.view.callbacks = _make_callbacks(on_delete=lambda mid: calls.__setitem__("deleted", mid))
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")

        with mock.patch.object(main_window.messagebox, "askyesno", return_value=True) as askyesno:
            self.view.week_delete_button.invoke()
            askyesno.assert_called_once_with(
                main_window.i18n.t("delete", "es"), main_window.i18n.t("deleteConfirm", "es")
            )
        self.assertEqual(calls["deleted"], "meeting-1")

    def test_eliminar_button_declined_does_not_delete(self):
        calls = {"deleted": None}
        self.view.callbacks = _make_callbacks(on_delete=lambda mid: calls.__setitem__("deleted", mid))
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")

        with mock.patch.object(main_window.messagebox, "askyesno", return_value=False):
            self.view.week_delete_button.invoke()
        self.assertIsNone(calls["deleted"])

    def test_agregar_button_always_enabled_and_uses_today_and_current_hour(self):
        self.assertEqual(str(self.view.week_add_button["state"]), "normal")
        calls = {"slot": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_week_slot_click=lambda d, h: calls.__setitem__("slot", (d, h)),
            on_set_active_view=lambda v: calls["views"].append(v),
        )
        expected_day = date.today()
        expected_hour = datetime.now().hour

        self.view.week_add_button.invoke()

        self.assertEqual(calls["slot"], (expected_day, expected_hour))
        self.assertEqual(calls["views"], ["list"])

    def test_agregar_button_stays_enabled_even_with_a_selection_active(self):
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(str(self.view.week_add_button["state"]), "normal")

    # -- disabled-button hover guard (_button(), one-line fix) -------------------

    def test_disabled_toolbar_button_does_not_light_up_on_hover_but_does_once_enabled(self):
        """SDD.md v2.11.0's one-line fix to the shared `_button()` helper:
        `<Enter>`/`<Leave>` are bound unconditionally for every button, but a
        `state="disabled"` button must not repaint its background on
        `<Enter>` (mouse hover) since its `command` can't fire anyway. The
        contrast case matters just as much: the guard must not kill hover
        feedback for an ENABLED button, so the same button object is
        re-checked after a selection flips it to `state="normal"`."""
        self.assertEqual(str(self.view.week_edit_button["state"]), "disabled")
        disabled_bg = str(self.view.week_edit_button["bg"])
        self.assertEqual(disabled_bg, main_window.GHOST_BG)

        self.view.week_edit_button.event_generate("<Enter>")

        self.assertEqual(
            str(self.view.week_edit_button["bg"]), disabled_bg,
            "a disabled button must not repaint its background on hover",
        )

        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(str(self.view.week_edit_button["state"]), "normal")

        self.view.week_edit_button.event_generate("<Enter>")

        self.assertEqual(
            str(self.view.week_edit_button["bg"]), main_window.GHOST_HOVER,
            "an ENABLED button must still repaint on hover -- the disabled guard must not "
            "suppress hover feedback once selection re-enables the button",
        )

    # -- clearing rules -----------------------------------------------------------

    def test_selection_clears_on_prev_next_today_navigation(self):
        for wrapper in ("_handle_week_prev_click", "_handle_week_next_click", "_handle_week_today_click"):
            widgets, _cells = self._render_single_entry("meeting-1")
            widgets.entry_labels[0].event_generate("<Button-1>")
            self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")

            getattr(self.view, wrapper)()

            self.assertIsNone(self.view._week_selected_meeting_id, f"{wrapper} must clear the selection")
            self.assertEqual(str(self.view.week_edit_button["state"]), "disabled")

    def test_selection_clears_on_toggling_work_week_mode(self):
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")

        self.view.set_week_column_mode("work")

        self.assertIsNone(self.view._week_selected_meeting_id)
        self.assertEqual(str(self.view.week_edit_button["state"]), "disabled")

    def test_selection_clears_on_leaving_week_view_for_list_or_calendar(self):
        for target in ("list", "calendar"):
            self.view.set_active_view("week")
            widgets, _cells = self._render_single_entry("meeting-1")
            widgets.entry_labels[0].event_generate("<Button-1>")
            self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")

            self.view.set_active_view(target)

            self.assertIsNone(self.view._week_selected_meeting_id, f"leaving week view for {target!r} must clear it")
            self.view.set_active_view("week")  # back to week for the next iteration/test

    def test_selection_does_not_clear_on_a_gadget_mode_round_trip(self):
        """SDD.md's explicit, deliberate exception: `set_gadget_mode` never
        routes through `set_active_view`'s clear-on-leave block (it
        `.grid_remove()`s week_view directly), and nothing about the
        underlying week/data actually changed -- see that section's
        reasoning for why this one case preserves the selection instead of
        clearing it by reflex."""
        widgets, _cells = self._render_single_entry("meeting-1")
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")

        self.view.set_gadget_mode(True)
        self.view.set_gadget_mode(False)

        self.assertEqual(
            self.view._week_selected_meeting_id, "meeting-1",
            "a gadget-mode round trip must NOT clear the week-view selection",
        )

    # -- right-click also selects (cross-checked against test_context_menu.py) --

    def test_right_click_on_an_entry_also_selects_it(self):
        widgets, _cells = self._render_single_entry("meeting-1")
        with mock.patch.object(self.view, "_show_context_menu"):
            widgets.entry_labels[0].event_generate("<Button-3>")
        self.assertEqual(self.view._week_selected_meeting_id, "meeting-1")

    # -- month view regression (Parte 2 is week-only) ----------------------------

    def test_month_view_left_click_on_an_entry_still_edits_and_switches_view_unchanged(self):
        self.view.set_active_view("calendar")
        self.root.update()
        target_day = date(2026, 8, 21)
        entry = main_window.CalendarEntry(meeting_id="meeting-month-1", time_text="09:00", title="X", color="#fff")
        blank = main_window.CalendarCellData(
            day=date(2025, 12, 1), in_current_month=True, is_today=False, entries=[], overflow_count=0
        )
        cell = main_window.CalendarCellData(
            day=target_day, in_current_month=True, is_today=False, entries=[entry], overflow_count=0
        )
        cells = [cell] + [blank] * 41
        self.view.render_calendar("Agosto 2026", ["L", "M", "M", "J", "V", "S", "D"], cells)
        calls = {"edited": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_edit=lambda mid: calls.__setitem__("edited", mid),
            on_set_active_view=lambda v: calls["views"].append(v),
        )

        self.view._calendar_cells[0].entry_labels[0].event_generate("<Button-1>")

        self.assertEqual(calls["edited"], "meeting-month-1")
        self.assertEqual(calls["views"], ["list"])
        self.view.set_active_view("week")

    # -- leak safety ----------------------------------------------------------------

    def test_repeated_select_and_clear_cycles_do_not_leak_tcl_commands(self):
        widgets, _cells = self._render_single_entry("meeting-leak")
        # Warm-up: the very first selection of a slot that has never shown a
        # border before can register real, one-time (non-leaking) state --
        # exclude it from the baseline, same discipline
        # tests/test_bind_leak_fixes.py uses for its own warm-up renders.
        widgets.entry_labels[0].event_generate("<Button-1>")
        self.view.clear_week_selection()

        baseline = count_tcl_commands(self.root)
        for _ in range(500):
            widgets.entry_labels[0].event_generate("<Button-1>")
            self.view.clear_week_selection()
        self.assertEqual(
            count_tcl_commands(self.root), baseline,
            "500 select/clear cycles (pure .configure(), no .bind()) must not leak Tcl commands",
        )

    def test_repeated_navigation_wrapper_calls_do_not_leak_tcl_commands(self):
        baseline = count_tcl_commands(self.root)
        for _ in range(500):
            self.view._handle_week_prev_click()
            self.view._handle_week_next_click()
            self.view._handle_week_today_click()
        self.assertEqual(
            count_tcl_commands(self.root), baseline,
            "1500 navigation-wrapper calls (each only clearing an already-cleared selection) must not leak",
        )


if __name__ == "__main__":
    unittest.main()
