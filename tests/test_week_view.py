"""Tests for the weekly calendar view (SDD.md v2.9.0): the new third
primary view (List/Month/Week), its empty-hour-cell click-to-create flow,
and -- the load-bearing part of this whole feature -- the Nivel A/Nivel B
split for the live "now" time-line.

Two test classes, mirroring the two layers this feature touches:

- `WeekViewWidgetTests` builds a real `MainWindow` against a real `tk.Tk()`
  (same setup style as `tests/test_calendar_day_click.py`): click behavior,
  and a direct Tcl-command-leak check on `update_week_live_indicators`
  (Nivel B) proving it never calls `.bind()` -- the exact bug class already
  found and fixed twice in this codebase for `.bind()`/`bind_all()` on a
  long-lived widget (see `.claude/skills/timermeet-python-builder/references
  /module-map.md`).
- `WeekViewGatingTests` builds a full `TimerMeetApp` against an isolated
  scratch data directory (never the real `data/meetings.json` -- see
  MEMORY's "never test against live data" note) to prove `app.py`'s own
  dirty-check signatures behave as designed: Nivel A
  (`_last_rendered_week_signature`) never re-fires from the clock alone,
  and Nivel B (`_last_rendered_week_live_state`) fires at most once per
  simulated minute.
"""

import shutil
import tempfile
import unittest
import warnings
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from timermeet_app import models

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
        "on_delete_series": _no_op, "on_edit_series": _no_op,
        "on_set_app_theme": _no_op, "on_gadget_resize": _no_op,
        "on_set_now_line_color": _no_op, "on_set_company_color": _no_op, "on_reset_company_color": _no_op,
    }
    fields.update(overrides)
    return main_window.Callbacks(**fields)


def _blank_week_cell(day: date, hour: int) -> "main_window.WeekCellData":
    return main_window.WeekCellData(day=day, hour=hour, entries=[], overflow_count=0)


def _week_cell_with_entry(day: date, hour: int, meeting_id: str) -> "main_window.WeekCellData":
    entry = main_window.CalendarEntry(meeting_id=meeting_id, time_text="09:00", title="Standup", color="#ffffff")
    return main_window.WeekCellData(day=day, hour=hour, entries=[entry], overflow_count=0)


def _full_week(monday: date, filled: "main_window.WeekCellData", filled_row: int, filled_col: int):
    """168 WeekCellData in the exact row-major (hour outer, day inner)
    order `MainWindow._week_cells`/`render_week_grid` expect -- one real
    cell at (filled_row, filled_col), blanks everywhere else."""
    cells = []
    for row in range(main_window.WEEK_ROWS):
        for col in range(main_window.WEEK_COLS):
            if row == filled_row and col == filled_col:
                cells.append(filled)
            else:
                cells.append(_blank_week_cell(monday + timedelta(days=col), row))
    return cells


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class WeekViewWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        # Not withdrawn: event_generate("<Button-1>") needs the widget
        # actually mapped, same reasoning as test_calendar_day_click.py.
        cls.root.geometry("1000x700+0+0")
        cls.view = main_window.MainWindow(cls.root, _make_callbacks())
        cls.view.set_active_view("week")
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    def _root_tcl_command_count(self) -> int:
        return len(self.root._tclCommands or [])

    def test_clicking_empty_hour_cell_prefills_date_and_hour_and_switches_to_list(self):
        calls = {"slot": None, "views": []}
        self.view.callbacks = _make_callbacks(
            on_week_slot_click=lambda d, h: calls.__setitem__("slot", (d, h)),
            on_set_active_view=lambda view: calls["views"].append(view),
        )
        monday = date(2026, 8, 10)
        target_hour = 14
        cell = _blank_week_cell(monday + timedelta(days=2), target_hour)  # Wednesday 14:00
        cells = _full_week(monday, cell, filled_row=target_hour, filled_col=2)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[target_hour * main_window.WEEK_COLS + 2]

        widgets.frame.event_generate("<Button-1>")

        self.assertEqual(calls["slot"], (monday + timedelta(days=2), target_hour))
        self.assertEqual(calls["views"], ["list"])

    def test_clicking_an_existing_week_entry_selects_it_instead_of_editing_directly(self):
        """SDD.md v2.11.0: left-click on a week-view entry now SELECTS it
        (accent border + toolbar enablement, see tests/test_week_selection.py
        for the dedicated coverage) instead of jumping straight to edit --
        a deliberate, week-view-only behavior change (the month view's own
        click-to-edit is untouched, see test_calendar_day_click.py).
        `_handle_week_entry_click` (the old left-click target) still exists
        unchanged and is still reachable via "Editar" (context menu +
        toolbar) -- only what left-click itself is bound to changed."""
        edit_calls = []
        slot_calls = []
        self.view.callbacks = _make_callbacks(
            on_edit=lambda mid: edit_calls.append(mid),
            on_week_slot_click=lambda d, h: slot_calls.append((d, h)),
        )
        monday = date(2026, 8, 10)
        cell = _week_cell_with_entry(monday, 9, "meeting-week-1")
        cells = _full_week(monday, cell, filled_row=9, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        widgets = self.view._week_cells[9 * main_window.WEEK_COLS + 0]

        try:
            widgets.entry_labels[0].event_generate("<Button-1>")

            self.assertEqual(edit_calls, [], "left-click in week view must no longer edit directly")
            self.assertEqual(slot_calls, [], "clicking an entry must not also fire the empty-slot handler")
            self.assertEqual(self.view._week_selected_meeting_id, "meeting-week-1")
        finally:
            # This class shares one `MainWindow` across every test in it
            # (see setUpClass) -- leave selection state clean for later
            # tests, same discipline `WeekColumnModeWidgetTests.tearDown`
            # already applies to the column-mode toggle.
            self.view.clear_week_selection()

    def test_prefill_new_meeting_with_hour_sets_time_field(self):
        self.view.callbacks = _make_callbacks()
        meeting = models.normalize_meeting(
            {"workName": "Acme", "title": "Old", "datetime": "2026-08-10T09:00", "reminderMinutes": 30}
        )
        self.view.populate_form(meeting)

        self.view.prefill_new_meeting(date(2026, 8, 12), hour=14)

        self.assertEqual(self.view.date_entry.get(), "2026-08-12")
        self.assertEqual(self.view.time_entry.get(), "14:00")
        self.assertEqual(self.view.meeting_id_var.get(), "")

    def test_prefill_new_meeting_without_hour_leaves_time_blank_unchanged_behavior(self):
        # Regression guard: the month calendar's existing day-click call
        # site never passes `hour` -- its exact previously-shipped behavior
        # (blank time field) must be untouched.
        self.view.prefill_new_meeting(date(2026, 8, 12))
        self.assertEqual(self.view.time_entry.get(), "")

    def test_update_week_live_indicators_never_calls_bind(self):
        """Direct proof of the Nivel A/Nivel B split's whole reason to
        exist: instrument every widget `update_week_live_indicators` could
        conceivably touch and assert `.bind()` is never called on any of
        them, across both the "current week" and "not current week" paths."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)

        bind_calls = []
        originals = {}
        widgets_to_watch = list(self.view._week_day_header_labels) + [self.view._week_now_line]
        widgets_to_watch += [w.frame for w in self.view._week_cells]
        for widget in widgets_to_watch:
            originals[widget] = widget.bind
            widget.bind = lambda *a, _w=widget, **kw: (bind_calls.append(_w), originals[_w](*a, **kw))[-1]
        try:
            self.view.update_week_live_indicators(today_index=2, hour=9, minute=30)
            self.view.update_week_live_indicators(today_index=None, hour=10, minute=0)
            self.view.update_week_live_indicators(today_index=0, hour=23, minute=59)
        finally:
            for widget, original in originals.items():
                widget.bind = original

        self.assertEqual(bind_calls, [], "Nivel B must never call .bind() on any widget")

    def test_repeated_update_week_live_indicators_calls_leave_zero_orphaned_tcl_commands(self):
        """Same leak-detection method already established in this codebase
        (tests/test_scrollable_panel.py): call the Nivel B function many
        times with an unchanging (and then a changing) minute and assert
        the root's own Tcl command bookkeeping never grows -- proving the
        split-path design actually avoids the leak class it exists to
        avoid, not just that it looks like it should on paper."""
        baseline = self._root_tcl_command_count()
        for _ in range(500):
            self.view.update_week_live_indicators(today_index=1, hour=9, minute=30)
        self.assertEqual(self._root_tcl_command_count(), baseline)

        for minute in range(500):
            self.view.update_week_live_indicators(today_index=1, hour=9, minute=minute % 60)
        self.assertEqual(self._root_tcl_command_count(), baseline)

    def test_now_line_retries_until_geometry_resolves_then_places_correctly(self):
        """Direct regression test for a real, empirically-confirmed bug
        found while implementing this feature (not a hypothetical): the
        very first time the week view is ever activated in a session,
        `winfo_width()` on a just-`.grid()`ed hour cell can report a small,
        real-looking but WRONG pre-layout width (measured as low as 18px
        against a real ~120px column) instead of an obvious "not mapped"
        sentinel like 0/1 -- so the guard must compare against a plausible
        floor, not just `<= 1`, and must keep retrying (never placing at a
        stale position) until a plausible width shows up. Simulates that
        exact sequence by monkeypatching `winfo_width` on the reference
        cell to return the confirmed-real stale value for the first two
        calls, then hand back the real geometry -- and drives the retry
        loop by invoking `_apply_week_now_line` directly instead of waiting
        on the real 300ms timer, so this test is fast and deterministic."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)

        reference_frame = self.view._week_cells[0].frame  # today_index=0
        real_winfo_width = reference_frame.winfo_width
        state = {"calls": 0}

        def fake_winfo_width():
            state["calls"] += 1
            return 18 if state["calls"] <= 2 else real_winfo_width()

        reference_frame.winfo_width = fake_winfo_width
        try:
            self.view.update_week_live_indicators(today_index=0, hour=9, minute=0)
            self.assertEqual(
                self.view._week_now_line.place_info(), {},
                "must stay hidden rather than place at an implausible pre-layout width",
            )
            self.assertIsNotNone(self.view._week_live_retry_job, "must self-schedule a retry")

            # Simulate the retry timer firing (without waiting on the real
            # 300ms delay): first retry still sees the stale value...
            self.root.after_cancel(self.view._week_live_retry_job)
            self.view._apply_week_now_line()
            self.assertEqual(self.view._week_now_line.place_info(), {})

            # ...second retry sees the now-resolved real width and places.
            self.root.after_cancel(self.view._week_live_retry_job)
            self.view._apply_week_now_line()
            place_info = self.view._week_now_line.place_info()
            self.assertNotEqual(place_info, {}, "must place once a plausible width is available")
            self.assertEqual(int(place_info["width"]), real_winfo_width())
        finally:
            reference_frame.winfo_width = real_winfo_width
            if self.view._week_live_retry_job is not None:
                self.root.after_cancel(self.view._week_live_retry_job)
                self.view._week_live_retry_job = None

    def _settle_week_meeting_blocks(self, blocks):
        """Same manual-firing technique `_settle_week_live_indicators` uses
        for the live line's own cold-start retry -- drives
        `render_week_meeting_blocks`'s geometry retry through to a final,
        resolved placement without waiting on the real 300ms timer."""
        self.view.render_week_meeting_blocks(blocks)
        attempts = 0
        while (
            self.view._week_meeting_block_retry_job is not None
            and attempts <= main_window._WEEK_LINE_MAX_RETRIES
        ):
            self.root.after_cancel(self.view._week_meeting_block_retry_job)
            self.view._apply_week_meeting_blocks()
            attempts += 1

    def _placed_block_widgets(self):
        return [w for w in self.view._week_meeting_blocks if w.frame.place_info()]

    def test_block_places_at_the_correct_pure_arithmetic_y_and_height(self):
        """SDD.md v2.16.0: Y/height are pure arithmetic against
        `WEEK_ROW_HEIGHT_PX` -- never `winfo_y()` -- mirroring
        `_apply_week_now_line`'s own Y math exactly."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        block = main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=9.5, duration_minutes=60,
            color="#ff0000", title="Standup", time_text="09:30", meeting_id="m1",
        )
        try:
            self._settle_week_meeting_blocks([block])
            placed = self._placed_block_widgets()
            self.assertEqual(len(placed), 1)
            place_info = placed[0].frame.place_info()
            self.assertAlmostEqual(float(place_info["y"]), main_window.WEEK_ROW_HEIGHT_PX * 9.5)
            self.assertAlmostEqual(float(place_info["height"]), main_window.WEEK_ROW_HEIGHT_PX * 1.0)
            column_width = self.view._week_cells[0].frame.winfo_width()
            self.assertAlmostEqual(float(place_info["width"]), column_width, delta=1.0)
            self.assertEqual(int(place_info["x"]), self.view._week_cells[0].frame.winfo_x())
        finally:
            self._settle_week_meeting_blocks([])

    def test_two_overlapping_meetings_split_the_column_width_in_half(self):
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        blocks = [
            main_window.WeekMeetingBlock(
                day_index=2, column_index=0, column_count=2, start_hour_float=9.0, duration_minutes=60,
                color="#ff0000", title="A", time_text="09:00", meeting_id="m1",
            ),
            main_window.WeekMeetingBlock(
                day_index=2, column_index=1, column_count=2, start_hour_float=9.0, duration_minutes=60,
                color="#00ff00", title="B", time_text="09:00", meeting_id="m2",
            ),
        ]
        try:
            self._settle_week_meeting_blocks(blocks)
            placed = sorted(self._placed_block_widgets(), key=lambda w: float(w.frame.place_info()["x"]))
            self.assertEqual(len(placed), 2)
            info0 = placed[0].frame.place_info()
            info1 = placed[1].frame.place_info()
            column_width = self.view._week_cells[2].frame.winfo_width()
            column_x = self.view._week_cells[2].frame.winfo_x()
            expected_block_width = (column_width - main_window.WEEK_BLOCK_GAP_PX) / 2
            self.assertAlmostEqual(float(info0["width"]), expected_block_width, delta=1.0)
            self.assertAlmostEqual(float(info1["width"]), expected_block_width, delta=1.0)
            self.assertEqual(int(info0["x"]), column_x)
            self.assertAlmostEqual(
                float(info1["x"]) - float(info0["x"]),
                expected_block_width + main_window.WEEK_BLOCK_GAP_PX,
                delta=1.0,
            )
        finally:
            self._settle_week_meeting_blocks([])

    def test_a_block_crossing_midnight_clips_at_the_end_of_its_own_day(self):
        """SDD.md's explicit decision (unchanged since v2.15.0): a meeting
        whose block would cross midnight clips at the end of its OWN day's
        column, never spilling into the next day's."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        block = main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=23.5, duration_minutes=120,
            color="#ff0000", title="Late", time_text="23:30", meeting_id="m1",
        )
        try:
            self._settle_week_meeting_blocks([block])
            placed = self._placed_block_widgets()
            self.assertEqual(len(placed), 1)
            place_info = placed[0].frame.place_info()
            total_height_px = main_window.WEEK_ROWS * main_window.WEEK_ROW_HEIGHT_PX
            expected_height = total_height_px - main_window.WEEK_ROW_HEIGHT_PX * 23.5
            self.assertAlmostEqual(float(place_info["height"]), expected_height)
        finally:
            self._settle_week_meeting_blocks([])

    def test_a_very_short_meeting_still_gets_the_minimum_height_floor(self):
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        # 5 minutes at WEEK_ROW_HEIGHT_PX=70 would compute to ~5.8px --
        # well under WEEK_BLOCK_MIN_HEIGHT_PX -- without the floor.
        block = main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=9.0, duration_minutes=5,
            color="#ff0000", title="Quick", time_text="09:00", meeting_id="m1",
        )
        try:
            self._settle_week_meeting_blocks([block])
            placed = self._placed_block_widgets()
            self.assertEqual(len(placed), 1)
            place_info = placed[0].frame.place_info()
            self.assertGreaterEqual(float(place_info["height"]), main_window.WEEK_BLOCK_MIN_HEIGHT_PX)
        finally:
            self._settle_week_meeting_blocks([])

    def test_fewer_blocks_than_the_pool_hides_the_unused_slots(self):
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        block = main_window.WeekMeetingBlock(
            day_index=1, column_index=0, column_count=1, start_hour_float=8.0, duration_minutes=30,
            color="#ff0000", title="Solo", time_text="08:00", meeting_id="m1",
        )
        try:
            self._settle_week_meeting_blocks([block])
            placed = self._placed_block_widgets()
            self.assertEqual(len(placed), 1, "every other pool slot must stay hidden")
        finally:
            self._settle_week_meeting_blocks([])

    def test_meeting_blocks_retry_until_geometry_resolves_then_place_correctly(self):
        """Same cold-start race `test_now_line_retries_until_geometry_resolves_then_places_correctly`
        proves for the live line, for the meeting-block overlay's own
        independent retry job."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        reference_frame = self.view._week_cells[0].frame
        real_winfo_width = reference_frame.winfo_width
        state = {"calls": 0}

        def fake_winfo_width():
            state["calls"] += 1
            return 18 if state["calls"] <= 2 else real_winfo_width()

        reference_frame.winfo_width = fake_winfo_width
        block = main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=9.0, duration_minutes=30,
            color="#ff0000", title="Standup", time_text="09:00", meeting_id="m1",
        )
        try:
            self.view.render_week_meeting_blocks([block])
            self.assertEqual(
                self._placed_block_widgets(), [],
                "must stay hidden rather than place at an implausible pre-layout width",
            )
            self.assertIsNotNone(self.view._week_meeting_block_retry_job, "must self-schedule a retry")

            self.root.after_cancel(self.view._week_meeting_block_retry_job)
            self.view._apply_week_meeting_blocks()
            self.assertEqual(self._placed_block_widgets(), [])

            self.root.after_cancel(self.view._week_meeting_block_retry_job)
            self.view._apply_week_meeting_blocks()
            placed = self._placed_block_widgets()
            self.assertEqual(len(placed), 1, "must place once a plausible width is available")
        finally:
            reference_frame.winfo_width = real_winfo_width
            if self.view._week_meeting_block_retry_job is not None:
                self.root.after_cancel(self.view._week_meeting_block_retry_job)
                self.view._week_meeting_block_retry_job = None
            self._settle_week_meeting_blocks([])

    def test_block_click_selects_and_right_click_opens_context_menu(self):
        """SDD.md v2.16.0 decision #9 -- the highest-risk part of this
        feature: a block is now the meeting's PRIMARY clickable surface."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        block = main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=9.0, duration_minutes=30,
            color="#ff0000", title="Standup", time_text="09:00", meeting_id="meeting-block-1",
            series_occurrence_count=2,
        )
        try:
            self._settle_week_meeting_blocks([block])
            # A `.place()`d widget only becomes real-event-deliverable
            # ("viewable") once Tk actually runs a geometry pass -- unlike
            # the `.grid()`-based cells above (already mapped once at
            # construction, see `_build_week_view`), this pool's widgets are
            # freshly placed by the call just above, so a plain
            # `event_generate` here needs one real event-loop pass first.
            # (Test-only: this project's "no synchronous `update()`" rule
            # targets production code, not test setup -- see `setUpClass`'s
            # own `cls.root.update()` for the existing precedent.)
            self.root.update()
            widgets = self._placed_block_widgets()[0]

            widgets.frame.event_generate("<Button-1>")
            self.assertEqual(self.view._week_selected_meeting_id, "meeting-block-1")

            # `_show_context_menu` must be patched here, same as EVERY other
            # real `<Button-3>` test in this codebase (see
            # `tests/test_context_menu.py`'s own module docstring): its real
            # `tk_popup()` call uses the native Win32 popup-menu API, which
            # blocks pumping real Windows messages until a human dismisses
            # it -- confirmed directly to hang this exact test (and, by
            # extension, the whole suite behind it) indefinitely when this
            # patch was missing. No synthetic event can dismiss a *native*
            # menu the way `event_generate` can for an ordinary Tk widget.
            with patch.object(self.view, "_show_context_menu"):
                widgets.label.event_generate("<Button-3>")
            # Right-click both selects (already was) and opens the context
            # menu -- same production path `_show_week_entry_context_menu`
            # already uses for `entry_label`; the patch above proves this
            # reaches that call (and the selection survives) without
            # depending on `tk_popup()`'s own already-mature native-menu
            # behavior, same reasoning `test_context_menu.py` already uses.
            self.assertEqual(self.view._week_selected_meeting_id, "meeting-block-1")
        finally:
            self.view.clear_week_selection()
            self._settle_week_meeting_blocks([])

    def test_aggregate_chip_is_never_bound_to_a_click_handler(self):
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        aggregate = main_window.WeekMeetingBlock(
            day_index=0, column_index=3, column_count=4, start_hour_float=9.0, duration_minutes=60,
            color="", title="", time_text="", meeting_id=None, is_overflow=True, overflow_count=2,
        )
        try:
            self._settle_week_meeting_blocks([aggregate])
            self.root.update()  # see the same-reasoning comment above
            widgets = self._placed_block_widgets()[0]
            calls = []
            self.view.callbacks = _make_callbacks(
                on_edit=lambda mid: calls.append(mid),
            )
            widgets.frame.event_generate("<Button-1>")
            self.assertEqual(self.view._week_selected_meeting_id, None)
            self.assertEqual(calls, [])
        finally:
            self._settle_week_meeting_blocks([])

    def test_hovering_a_meeting_block_shows_a_tooltip_with_exact_date_and_time(self):
        """SDD.md v2.17.2: the weekly view's blocks only ever show
        "HH:MM Título" -- too little for an overlapping-heavy day, hence
        the hover tooltip surfacing the full, unambiguous date/time."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        block = main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=9.5, duration_minutes=30,
            color="#ff0000", title="Standup", time_text="09:30", meeting_id="meeting-block-1",
            start_dt=datetime(2026, 8, 10, 9, 30), end_dt=datetime(2026, 8, 10, 10, 0),
        )
        try:
            self._settle_week_meeting_blocks([block])
            self.root.update()  # see the same-reasoning comment above
            widgets = self._placed_block_widgets()[0]

            widgets.frame.event_generate("<Enter>")
            self.assertEqual(self.view._week_tooltip.state(), "normal")
            tooltip_text = self.view._week_tooltip_label.cget("text")
            self.assertIn("Standup", tooltip_text)
            self.assertIn("10 ago 2026, 09:30", tooltip_text)
            self.assertIn("10:00", tooltip_text)
        finally:
            self._settle_week_meeting_blocks([])

    def test_leaving_a_meeting_block_hides_the_tooltip(self):
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        block = main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=9.5, duration_minutes=30,
            color="#ff0000", title="Standup", time_text="09:30", meeting_id="meeting-block-1",
            start_dt=datetime(2026, 8, 10, 9, 30), end_dt=datetime(2026, 8, 10, 10, 0),
        )
        try:
            self._settle_week_meeting_blocks([block])
            self.root.update()
            widgets = self._placed_block_widgets()[0]

            widgets.frame.event_generate("<Enter>")
            self.assertEqual(self.view._week_tooltip.state(), "normal")
            widgets.frame.event_generate("<Leave>")
            self.assertEqual(self.view._week_tooltip.state(), "withdrawn")
        finally:
            self._settle_week_meeting_blocks([])

    def test_aggregate_chip_shows_no_tooltip_on_hover(self):
        """Mirrors `test_aggregate_chip_is_never_bound_to_a_click_handler`
        above -- the shared "+N más" chip stays fully non-interactive,
        hover included."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        aggregate = main_window.WeekMeetingBlock(
            day_index=0, column_index=3, column_count=4, start_hour_float=9.0, duration_minutes=60,
            color="", title="", time_text="", meeting_id=None, is_overflow=True, overflow_count=2,
        )
        try:
            self._settle_week_meeting_blocks([aggregate])
            self.root.update()
            widgets = self._placed_block_widgets()[0]

            widgets.frame.event_generate("<Enter>")
            self.assertEqual(self.view._week_tooltip.state(), "withdrawn")
        finally:
            self._settle_week_meeting_blocks([])

    def test_repeated_re_renders_of_the_block_pool_do_not_leak_tcl_commands(self):
        """Same leak-detection method already established in this codebase
        (tests/test_bind_leak_fixes.py) -- applied here to the new
        `_week_meeting_blocks` pool's own click/right-click bindings, which
        (unlike v2.15.0's purely decorative bars) are a REAL new `.bind()`
        surface introduced by this feature (SDD.md decision #9)."""
        from tests.testutils import count_tcl_commands

        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)

        def block_for(i: int) -> "main_window.WeekMeetingBlock":
            return main_window.WeekMeetingBlock(
                day_index=0, column_index=0, column_count=1, start_hour_float=9.0, duration_minutes=30,
                color="#ff0000", title=f"Standup {i}", time_text="09:00", meeting_id=f"meeting-{i}",
            )

        try:
            # Warm-up (same discipline as every other leak test in this
            # codebase): the very first bind on a never-before-bound slot
            # registers a real, permanent (non-leaking) Tcl command.
            self._settle_week_meeting_blocks([block_for(0)])
            self._settle_week_meeting_blocks([block_for(1)])
            baseline = count_tcl_commands(self.root)
            for i in range(2, 300):
                self._settle_week_meeting_blocks([block_for(i)])
            self.assertEqual(
                count_tcl_commands(self.root), baseline,
                "298 further real re-renders (each genuinely changing the one block's meeting) must not leak",
            )
        finally:
            self._settle_week_meeting_blocks([])

    # -- SDD.md v2.16.0 decision #5: text-degradation ladder -------------------

    def _make_block(self, title="Standup", time_text="09:00"):
        return main_window.WeekMeetingBlock(
            day_index=0, column_index=0, column_count=1, start_hour_float=9.0, duration_minutes=30,
            color="#ff0000", title=title, time_text=time_text, meeting_id="m1",
        )

    def test_full_text_shown_when_it_fits(self):
        block = self._make_block(title="Standup")
        text = self.view._format_week_block_text(block, available_px=10_000)
        self.assertEqual(text, "09:00 Standup")

    def test_truncates_with_ellipsis_when_only_partial_title_fits(self):
        block = self._make_block(title="A Very Long Meeting Title That Cannot Possibly Fit")
        font = self.view._get_week_block_font()
        # Wide enough for the prefix plus a handful of title characters,
        # narrow enough that the full text does not fit.
        available = font.measure("09:00 A Very")
        text = self.view._format_week_block_text(block, available_px=available)
        self.assertTrue(text.endswith("…"))
        self.assertTrue(text.startswith("09:00 "))
        self.assertGreater(len(text), len("09:00 …"))

    def test_falls_back_to_bare_time_when_not_one_title_character_fits(self):
        block = self._make_block(title="Standup")
        font = self.view._get_week_block_font()
        # Just enough room for "09:00" alone, not even "09:00 S…".
        available = font.measure("09:00")
        text = self.view._format_week_block_text(block, available_px=available)
        self.assertEqual(text, "09:00")

    def test_empty_string_when_not_even_bare_time_fits(self):
        block = self._make_block(title="Standup")
        text = self.view._format_week_block_text(block, available_px=1)
        self.assertEqual(text, "")

    def test_zero_or_negative_available_width_returns_empty_string(self):
        block = self._make_block(title="Standup")
        self.assertEqual(self.view._format_week_block_text(block, available_px=0), "")
        self.assertEqual(self.view._format_week_block_text(block, available_px=-5), "")

    def test_every_header_has_the_right_pair_of_view_switch_buttons(self):
        """Direct proof of SDD.md's v2.9.0 wiring requirement: each of the
        three primary headers gets exactly 2 "go to view X" buttons (never
        a 1-button cycle), each calling `on_set_active_view` with its own
        target -- zero regression on the two already-shipped buttons
        (`calendarViewButton` on the list, `listViewButton` on the month),
        plus the new `weekViewButton`/pairing on each."""
        calls = []
        self.view.callbacks = _make_callbacks(on_set_active_view=lambda v: calls.append(v))
        expected = {
            # "week" listed before "calendar" on the list/full header only
            # (SDD.md v2.10.0 discoverability fix) -- the launch screen
            # where a user actually picks a view for the first time; the
            # month header's own pairing is untouched.
            "full": ["weekViewButton", "calendarViewButton"],
            "calendar": ["listViewButton", "weekViewButton"],
            "week": ["listViewButton", "calendarViewButton"],
        }
        headers = {"full": self.view.full_header, "calendar": self.view.calendar_header, "week": self.view.week_header}
        for name, header in headers.items():
            keys = [key for _btn, key in header.view_switch_buttons]
            self.assertEqual(keys, expected[name], f"{name} header's view-switch buttons")
            for btn, key in header.view_switch_buttons:
                calls.clear()
                btn.invoke()
                target_view = {"calendarViewButton": "calendar", "listViewButton": "list", "weekViewButton": "week"}[key]
                self.assertEqual(calls, [target_view], f"{name} header's {key!r} button")

    def test_primary_view_four_way_round_trip_through_gadget_mode(self):
        for target in ("list", "calendar", "week"):
            self.view.set_active_view(target)
            self.assertEqual(self.view._primary_view, target)
            self.view.set_gadget_mode(True)
            self.assertTrue(self.view._gadget_active)
            self.view.set_gadget_mode(False)
            self.assertFalse(self.view._gadget_active)
            self.assertEqual(
                self.view._primary_view, target,
                f"leaving gadget mode must restore '{target}', not silently land elsewhere",
            )
            self.assertEqual(str(self.view._primary_view_frame()), str(getattr(self.view, {
                "list": "full_view", "calendar": "calendar_view", "week": "week_view",
            }[target])))
        # Restore a known, ungadgeted state for later tests in this class.
        self.view.set_active_view("week")

    def test_exactly_one_primary_frame_is_ever_gridded_across_every_view_and_gadget_transition(self):
        """Real Tk `grid_info()` proof, not just a check of the logical
        `_primary_view` string (already covered above): after every
        List/Month/Week switch, and after every gadget-mode round-trip from
        each of those three, exactly one of the four sibling frames sharing
        root's single grid cell (`full_view`/`calendar_view`/`week_view`/
        `gadget_view`) is ever the one actually gridded. A purely-logical
        check couldn't catch a real regression where e.g. two frames both
        stayed `.grid()`ed (visually stacked) or none did (a blank window)
        -- `_primary_view` could still read correctly in either of those
        broken scenarios.

        `grid_info()` -- not `winfo_ismapped()` -- is the sole hard
        assertion. `grid_info()` reflects the geometry manager's own
        request state, committed synchronously the instant
        `.grid()`/`.grid_remove()` returns, independent of the Tk event
        loop or the window manager; that alone already fully covers this
        test's stated purpose (catching "two stacked" or "none gridded"),
        with no settling window at all.

        `winfo_ismapped()` is still cross-checked (it can catch a
        *different* real bug that `grid_info()` cannot: the right frame
        gridded correctly inside a root window that itself never got
        `deiconify()`d back onto the screen), but only as a best-effort,
        non-fatal check behind a generous settle loop, never as a second
        hard assertion. Measured directly in this sandbox: after a
        gadget-mode round trip -- which wraps *two* `overrideredirect()`
        toggles, each itself wrapped in its own withdraw()/deiconify() pair
        (see `set_gadget_mode`'s docstring) -- the window manager's
        Map-notification delivery for the *root* window can lag the very
        next grid change by anywhere from one extra `update()` pass up to
        multiple real seconds, depending on how much window-creation churn
        the shared Windows session has recently done (desktop-heap/DWM
        pressure, not anything this app controls). One captured flake
        showed `grid_info()` already correctly settled on `['calendar']`
        while `winfo_ismapped()` reported ALL FOUR sibling frames unmapped
        (a global root-mapped-notification hiccup, not a selectively wrong
        frame) and resolved one `update()` pass later; another, under
        heavier session churn, still hadn't resolved after 60 settle passes
        spanning ~2.7 real seconds. No fixed bound is provably sufficient,
        so failing the test on it would just move the flake instead of
        fixing it -- hence non-fatal."""
        frames = {
            "full": self.view.full_view,
            "calendar": self.view.calendar_view,
            "week": self.view.week_view,
            "gadget": self.view.gadget_view,
        }
        target_to_frame_key = {"list": "full", "calendar": "calendar", "week": "week"}
        # Comfortably covers ordinary settling (observed: usually 1 pass,
        # occasionally a few more); intentionally NOT relied upon as a hard
        # guarantee -- see docstring.
        MAX_SETTLE_UPDATES = 20

        def gridded_frame_keys():
            # No update() needed -- grid_info() is the geometry manager's
            # own synchronously committed state.
            return [key for key, frame in frames.items() if frame.grid_info()]

        def best_effort_mapped_check(expected, label):
            mapped = []
            for _ in range(MAX_SETTLE_UPDATES):
                self.root.update()
                mapped = [key for key, frame in frames.items() if frame.grid_info() and frame.winfo_ismapped()]
                if mapped == expected:
                    return
            # Non-fatal: winfo_ismapped() lag here is a measured window-
            # manager/session-churn artifact (see docstring), not proof of a
            # real bug -- grid_info() (asserted separately, and hard) is the
            # authoritative signal for this test's actual purpose.
            warnings.warn(
                f"{label}: winfo_ismapped() still reported {mapped!r} (wanted {expected!r}) after "
                f"{MAX_SETTLE_UPDATES} settle passes -- grid_info() was already correct; treating this "
                "as window-manager notification lag, not a real bug.",
                stacklevel=2,
            )

        try:
            for target in ("list", "calendar", "week", "list", "calendar", "week"):
                self.view.set_active_view(target)
                expected = [target_to_frame_key[target]]
                self.assertEqual(gridded_frame_keys(), expected, f"after set_active_view({target!r}) (grid_info)")
                best_effort_mapped_check(expected, f"after set_active_view({target!r})")

                self.view.set_gadget_mode(True)
                self.assertEqual(
                    gridded_frame_keys(), ["gadget"], f"after entering gadget mode from {target!r} (grid_info)"
                )
                best_effort_mapped_check(["gadget"], f"after entering gadget mode from {target!r}")

                self.view.set_gadget_mode(False)
                self.assertEqual(
                    gridded_frame_keys(), expected, f"after leaving gadget mode back to {target!r} (grid_info)"
                )
                best_effort_mapped_check(expected, f"after leaving gadget mode back to {target!r}")
        finally:
            # Restore a known, ungadgeted state for later tests in this class.
            self.view.set_active_view("week")

    def _settle_week_live_indicators(self, today_index, hour, minute, scroll_to_now=False):
        """Drives `update_week_live_indicators` through to a final,
        geometry-resolved placement without waiting on the real 300ms retry
        timer -- same manual-firing technique
        `test_now_line_retries_until_geometry_resolves_then_places_correctly`
        uses, generalized into a helper so other tests can get a
        deterministic placed line regardless of how much real wall-clock
        time has already elapsed since this session's one-time cold-start
        geometry delay (see `_apply_week_now_line`'s docstring)."""
        self.view.update_week_live_indicators(
            today_index=today_index, hour=hour, minute=minute, scroll_to_now=scroll_to_now,
        )
        attempts = 0
        while self.view._week_live_retry_job is not None and attempts <= main_window._WEEK_LINE_MAX_RETRIES:
            self.root.after_cancel(self.view._week_live_retry_job)
            self.view._apply_week_now_line()
            attempts += 1

    def test_now_line_column_moves_to_the_next_day_across_the_midnight_boundary(self):
        """Not just "no exception at the 23:59->00:00 boundary" -- a
        concrete pixel assertion that the live line's X position actually
        moves from Wednesday's column to Thursday's column when the clock
        crosses midnight. `today_index` (supplied by app.py's
        `_refresh_week`, see its own docstring on `days.index(today_date)`)
        is the only thing that tells this view which column is "today";
        this proves the view layer actually repositions on a changed index
        instead of silently leaving the line on the previous column."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)

        self._settle_week_live_indicators(today_index=2, hour=23, minute=59)  # Wednesday, 1 min to midnight
        wednesday_place = self.view._week_now_line.place_info()
        self.assertNotEqual(wednesday_place, {})

        self._settle_week_live_indicators(today_index=3, hour=0, minute=0)  # Thursday, just past midnight
        thursday_place = self.view._week_now_line.place_info()
        self.assertNotEqual(thursday_place, {})

        self.assertNotEqual(
            int(wednesday_place["x"]), int(thursday_place["x"]),
            "the now-line must move to Thursday's column, not stay on Wednesday's",
        )
        self.assertEqual(int(thursday_place["x"]), self.view._week_cells[3].frame.winfo_x())
        # And Y resets to the top of the grid for 00:00, not left wherever
        # Wednesday's near-midnight Y happened to be.
        self.assertEqual(float(thursday_place["y"]), 0.0)

    def test_now_line_stays_pinned_to_its_cell_at_several_scroll_positions(self):
        """The live line is a child of `grid_frame` -- the SAME frame that
        scrolls as one unit inside the `_ScrollablePanel` (see
        `_build_week_view`'s docstring, SDD.md decision #1/#3) -- so its
        `.place()` coordinates are relative to that scrolling frame, not to
        the visible viewport, and should never need to change when the user
        scrolls. Proves that by scrolling to several different real
        positions (not just checking once at the initial unscrolled
        position) and asserting the line's `place_info()` is identical
        every time."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        self._settle_week_live_indicators(today_index=2, hour=12, minute=0)
        baseline = dict(self.view._week_now_line.place_info())
        self.assertNotEqual(baseline, {}, "must be placed before this test can prove it stays pinned")

        # `_week_now_line`'s parent is `grid_frame` (== the ScrollablePanel's
        # `body`), and `body`'s own parent is the ScrollablePanel's canvas --
        # so two `.master` hops up from the line reaches the real
        # `tk.Canvas` this test needs to actually scroll.
        canvas = self.view._week_now_line.master.master
        self.root.update_idletasks()
        seen_scroll_fractions = set()
        for fraction in (0.0, 0.3, 0.7, 1.0):
            canvas.yview_moveto(fraction)
            self.root.update_idletasks()
            seen_scroll_fractions.add(round(canvas.yview()[0], 3))
            self.assertEqual(
                dict(self.view._week_now_line.place_info()), baseline,
                f"now-line must stay at the same offset from its cell when scrolled to {fraction}",
            )
        self.assertGreater(
            len(seen_scroll_fractions), 1,
            "the scroll itself must have actually moved the viewport, or this test proves nothing",
        )

    def test_switching_away_from_week_view_cancels_the_pending_now_line_retry(self):
        """Direct regression test for a second real bug found by adversarial
        review of v2.9.0, documented in SDD.md's v2.9.0 "Resultado real vs.
        diseño" section: before this
        fix, switching away from week view before the cold-start width
        resolved left `_apply_week_now_line`'s `root.after(300, ...)` retry
        chain running forever, rescheduling itself every 300ms for the rest
        of the app session even though week view was no longer on screen.
        Forces the implausible-width path, switches to List before it would
        resolve, and asserts both halves of the fix: the pending job is
        actually cancelled, AND the guarded method itself refuses to
        reschedule even if something still manages to invoke it after the
        switch (belt-and-suspenders proof of the active-view bail-out, not
        just of the `set_active_view` cancellation call site)."""
        monday = date(2026, 8, 10)
        self.view.set_active_view("week")
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)

        reference_frame = self.view._week_cells[0].frame
        real_winfo_width = reference_frame.winfo_width
        reference_frame.winfo_width = lambda: 18  # forever implausible
        try:
            self.view.update_week_live_indicators(today_index=0, hour=9, minute=0)
            self.assertIsNotNone(self.view._week_live_retry_job, "must have scheduled a retry")

            self.view.set_active_view("list")

            self.assertIsNone(
                self.view._week_live_retry_job,
                "set_active_view must cancel a pending now-line retry when leaving week view",
            )

            # Belt-and-suspenders: even if some stale callback still managed
            # to invoke _apply_week_now_line after the switch, it must
            # still refuse to reschedule -- the active-view guard, not just
            # the cancellation call site, is what makes this actually safe.
            self.view._apply_week_now_line()
            self.assertIsNone(
                self.view._week_live_retry_job,
                "_apply_week_now_line must not reschedule while week view isn't the active primary view",
            )
        finally:
            reference_frame.winfo_width = real_winfo_width
            if self.view._week_live_retry_job is not None:
                self.root.after_cancel(self.view._week_live_retry_job)
                self.view._week_live_retry_job = None
            self.view.set_active_view("week")

    def test_now_line_retry_gives_up_after_the_cap_even_if_geometry_never_resolves(self):
        """Defense-in-depth proof for the new `_WEEK_LINE_MAX_RETRIES` cap:
        with week view genuinely still active/gridded the whole time (so
        the Fix-1 active-view guard above never kicks in), a width that
        never becomes plausible must still stop rescheduling once the cap
        is reached -- proving the cap is a real, independent backstop
        against a hypothetical future window state that never resolves,
        not just a theoretical comment."""
        monday = date(2026, 8, 10)
        self.view.set_active_view("week")
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)

        reference_frame = self.view._week_cells[0].frame
        real_winfo_width = reference_frame.winfo_width
        reference_frame.winfo_width = lambda: 18  # never resolves
        try:
            self.view.update_week_live_indicators(today_index=0, hour=9, minute=0)
            self.assertIsNotNone(self.view._week_live_retry_job)

            # Manually fire the retry chain well past the cap, exactly the
            # way `test_now_line_retries_until_geometry_resolves_then_places_correctly`
            # drives it without waiting on the real 300ms timer.
            for _ in range(main_window._WEEK_LINE_MAX_RETRIES + 5):
                if self.view._week_live_retry_job is None:
                    break
                self.root.after_cancel(self.view._week_live_retry_job)
                self.view._apply_week_now_line()

            self.assertIsNone(
                self.view._week_live_retry_job,
                f"must give up after {main_window._WEEK_LINE_MAX_RETRIES} retries instead of retrying forever",
            )
            self.assertEqual(
                self.view._week_now_line.place_info(), {},
                "must stay hidden, never placed with the implausible width, once retries are exhausted",
            )
        finally:
            reference_frame.winfo_width = real_winfo_width
            if self.view._week_live_retry_job is not None:
                self.root.after_cancel(self.view._week_live_retry_job)
                self.view._week_live_retry_job = None
            self.view.set_active_view("week")

    def _expected_scroll_to_now_fraction(self, hour, minute):
        total_height_px = main_window.WEEK_ROWS * main_window.WEEK_ROW_HEIGHT_PX
        margin_px = main_window.WEEK_AUTOSCROLL_MARGIN_HOURS * main_window.WEEK_ROW_HEIGHT_PX
        y = main_window.WEEK_ROW_HEIGHT_PX * (hour + minute / 60)
        return max(0.0, (y - margin_px) / total_height_px)

    def test_scroll_to_now_centers_the_current_hour_with_margin_once_geometry_resolves(self):
        """Direct regression test for the reported bug: the week grid used
        to always open scrolled to 00:00, forcing the user to manually
        scroll ~7 rows to see their morning meetings and the live "now"
        line. `scroll_to_now=True` (the flag app.py passes on the specific
        triggers documented in `update_week_live_indicators`'s docstring)
        must move the scroll close to -- but with a small margin above,
        never flush against -- the current hour, the instant real geometry
        is available."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        canvas = self.view._week_scroll.canvas
        canvas.yview_moveto(0.0)
        try:
            self._settle_week_live_indicators(today_index=2, hour=10, minute=0, scroll_to_now=True)

            self.assertFalse(
                self.view._week_scroll_to_now_pending, "the one-shot request must be consumed once applied",
            )
            self.assertAlmostEqual(
                canvas.yview()[0], self._expected_scroll_to_now_fraction(10, 0), delta=0.01,
            )
        finally:
            canvas.yview_moveto(0.0)
            self.view._week_scroll_to_now_pending = False

    def test_scroll_to_now_clamps_to_the_top_for_early_morning_hours(self):
        """A current time within the first `WEEK_AUTOSCROLL_MARGIN_HOURS` of
        the day (e.g. 00:30) would compute a negative target -- must clamp
        to the very top of the grid instead of a nonsensical negative
        scroll."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        canvas = self.view._week_scroll.canvas
        canvas.yview_moveto(0.5)  # start away from the top, so a no-op couldn't pass by accident
        try:
            self._settle_week_live_indicators(today_index=2, hour=0, minute=30, scroll_to_now=True)

            self.assertAlmostEqual(canvas.yview()[0], 0.0, delta=0.001)
        finally:
            canvas.yview_moveto(0.0)
            self.view._week_scroll_to_now_pending = False

    def test_scroll_to_now_is_not_reapplied_by_a_later_call_without_the_flag(self):
        """The load-bearing usability guarantee: a per-minute-style
        heartbeat call (`scroll_to_now=False`, the default every real
        heartbeat tick uses) must never yank the scroll position away from
        wherever the user left it -- proven here by manually scrolling
        elsewhere first, then calling `update_week_live_indicators` again
        with the SAME today_index/hour/minute and no scroll request, and
        asserting the scroll position is untouched."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        canvas = self.view._week_scroll.canvas
        try:
            self._settle_week_live_indicators(today_index=2, hour=10, minute=0, scroll_to_now=True)
            first_fraction = canvas.yview()[0]
            # Requesting 0.9 outright (rather than reading back whatever
            # Tk actually applied) would be a fragile assumption here: this
            # panel's real viewport covers a large fraction of the total
            # scrollable content, so `yview_moveto` legitimately CLAMPS a
            # request that would push the bottom of the view past 1.0 --
            # confirmed directly (not assumed) against this same widget
            # tree. What matters for this test is only that the manual
            # scroll actually moved the view somewhere else, and that the
            # later no-flag call doesn't move it AGAIN -- not the exact
            # fraction Tk settles on.
            canvas.yview_moveto(0.9)
            manual_fraction = canvas.yview()[0]
            self.assertNotAlmostEqual(
                manual_fraction, first_fraction, delta=0.01,
                msg="the manual scroll itself must have actually moved the view, or this test proves nothing",
            )

            # Same state as before, no scroll_to_now -- mirrors a real
            # heartbeat tick re-confirming an unchanged minute.
            self._settle_week_live_indicators(today_index=2, hour=10, minute=0, scroll_to_now=False)

            self.assertAlmostEqual(
                canvas.yview()[0], manual_fraction, delta=0.01,
                msg="a call without scroll_to_now must never move the user's own scroll position",
            )
        finally:
            canvas.yview_moveto(0.0)
            self.view._week_scroll_to_now_pending = False

    def test_scroll_to_now_is_skipped_when_the_shown_week_has_no_today(self):
        """Navigating to a week that isn't the real current one has no
        "now" to center on -- `today_index=None` -- so even a (defensively
        impossible in real app.py usage, see `update_week_live_indicators`'s
        docstring) stray `scroll_to_now=True` request must be a no-op,
        leaving whatever scroll position was already there untouched."""
        monday = date(2026, 8, 10)
        cells = _full_week(monday, _blank_week_cell(monday, 0), filled_row=0, filled_col=0)
        self.view.render_week_grid("10-16 Ago 2026", ["L 10", "M 11", "M 12", "J 13", "V 14", "S 15", "D 16"], cells)
        canvas = self.view._week_scroll.canvas
        canvas.yview_moveto(0.4)
        try:
            self._settle_week_live_indicators(today_index=None, hour=9, minute=0, scroll_to_now=True)

            self.assertFalse(self.view._week_scroll_to_now_pending)
            self.assertAlmostEqual(canvas.yview()[0], 0.4, delta=0.01)
        finally:
            canvas.yview_moveto(0.0)
            self.view._week_scroll_to_now_pending = False


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class WeekViewGatingTests(unittest.TestCase):
    """app.py's own Nivel A/Nivel B dirty-check gating -- built against a
    real TimerMeetApp so `_refresh_week`'s signature logic is exercised
    exactly as production runs it, but pointed at an isolated scratch data
    directory (never `data/meetings.json`) and with every side-effecting
    subsystem (tray icon show, native notifications) left untouched since
    this suite never calls them."""

    @classmethod
    def setUpClass(cls):
        cls._scratch_dir = tempfile.mkdtemp(prefix="timermeet_week_view_test_")
        cls._base_dir_patcher = patch(
            "timermeet_app.storage.base_dir", return_value=__import__("pathlib").Path(cls._scratch_dir)
        )
        cls._base_dir_patcher.start()
        try:
            cls.app = TimerMeetApp()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            cls._base_dir_patcher.stop()
            shutil.rmtree(cls._scratch_dir, ignore_errors=True)
            raise unittest.SkipTest(f"No display available for Tk: {exc}")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass
        cls._base_dir_patcher.stop()
        shutil.rmtree(cls._scratch_dir, ignore_errors=True)

    def setUp(self):
        # Every test gets a clean slate for the two gates under test and a
        # fixed anchor week, independent of whatever the real current week
        # is when this suite happens to run.
        self.app.active_view = "week"
        self.app._week_anchor = date(2026, 8, 12)  # a Wednesday
        self.app.meetings = []
        self.app._last_rendered_week_signature = None
        self.app._last_rendered_week_live_state = None
        self.render_mock = MagicMock()
        self.live_mock = MagicMock()
        self._render_patch = patch.object(self.app.view, "render_week_grid", self.render_mock)
        self._live_patch = patch.object(self.app.view, "update_week_live_indicators", self.live_mock)
        self._render_patch.start()
        self._live_patch.start()

    def tearDown(self):
        self._render_patch.stop()
        self._live_patch.stop()

    def test_nivel_a_never_rerenders_from_the_clock_alone(self):
        base_now = datetime(2026, 8, 12, 9, 0)
        self.app._refresh_week(base_now)
        self.assertEqual(self.render_mock.call_count, 1)

        # Same week, same (empty) meetings -- only the clock moved forward
        # across several different minutes. Nivel A must not fire again.
        for offset_minutes in (1, 5, 30, 61, 120):
            self.app._refresh_week(base_now + timedelta(minutes=offset_minutes))
        self.assertEqual(
            self.render_mock.call_count, 1,
            "render_week_grid (Nivel A, which re-binds 168 cells) must never re-fire from time alone",
        )

    def test_nivel_a_signature_has_no_hour_minute_component(self):
        # Direct regression guard matching SDD.md's explicit acceptance
        # criterion: the *signature tuple itself* must not embed hour/minute
        # -- inspected directly, not just inferred from call counts above.
        self.app._refresh_week(datetime(2026, 8, 12, 9, 0))
        signature = self.app._last_rendered_week_signature
        self.app._last_rendered_week_signature = None
        self.app._refresh_week(datetime(2026, 8, 12, 23, 59))
        signature_later = self.app._last_rendered_week_signature
        self.assertEqual(signature, signature_later)

    def test_nivel_a_rerenders_when_meeting_data_actually_changes(self):
        self.app._refresh_week(datetime(2026, 8, 12, 9, 0))
        self.assertEqual(self.render_mock.call_count, 1)

        self.app.meetings.append(
            models.normalize_meeting({"workName": "Acme", "title": "New", "datetime": "2026-08-12T10:00"})
        )
        self.app._refresh_week(datetime(2026, 8, 12, 9, 0))
        self.assertEqual(self.render_mock.call_count, 2)

    def test_nivel_b_fires_at_most_once_per_simulated_minute(self):
        now = datetime(2026, 8, 12, 9, 30, 0)
        self.app._refresh_week(now)
        self.assertEqual(self.live_mock.call_count, 1)

        # Same minute, different second -- must NOT re-fire.
        self.app._refresh_week(now.replace(second=45))
        self.assertEqual(self.live_mock.call_count, 1)

        # Minute advances -- must fire exactly once more.
        self.app._refresh_week(now + timedelta(minutes=1))
        self.assertEqual(self.live_mock.call_count, 2)

    def test_now_line_index_is_none_when_shown_week_is_not_the_real_current_week(self):
        # _week_anchor is fixed to 2026-08-12 in setUp; a `now` far outside
        # that week must report today_index=None to the view.
        self.app._refresh_week(datetime(2030, 1, 1, 9, 0))
        called_today_index = self.live_mock.call_args[0][0]
        self.assertIsNone(called_today_index)

    def test_now_line_index_is_set_when_shown_week_is_the_real_current_week(self):
        # 2026-08-12 (Wednesday) is inside its own Monday-first week
        # (2026-08-10..16) -- index 2 (Mon=0).
        self.app._refresh_week(datetime(2026, 8, 12, 9, 0))
        called_today_index = self.live_mock.call_args[0][0]
        self.assertEqual(called_today_index, 2)

    def test_refresh_week_forwards_scroll_to_now_to_the_view(self):
        self.app._refresh_week(datetime(2026, 8, 12, 9, 0), scroll_to_now=True)
        self.assertTrue(self.live_mock.call_args.kwargs.get("scroll_to_now"))

    def test_refresh_week_defaults_scroll_to_now_to_false(self):
        self.app._refresh_week(datetime(2026, 8, 12, 9, 0))
        self.assertFalse(self.live_mock.call_args.kwargs.get("scroll_to_now"))

    def test_refresh_week_forces_the_call_through_even_when_live_state_is_unchanged(self):
        """Nivel B's dirty-check exists to skip redundant `.configure()`/
        `.place()` calls when nothing changed -- but a real scroll-to-now
        request carries no footprint of its own inside `live_state`
        (today_index/hour/minute), so it must bypass that gate entirely or
        it would be silently swallowed on the (rare but real) tick where the
        state happens to already match the last recorded one."""
        now = datetime(2026, 8, 12, 9, 30, 0)
        self.app._refresh_week(now)
        self.assertEqual(self.live_mock.call_count, 1)

        # Unchanged state, no request -- Nivel B's ordinary gate applies.
        self.app._refresh_week(now)
        self.assertEqual(self.live_mock.call_count, 1)

        # Unchanged state, WITH a request -- must still reach the view.
        self.app._refresh_week(now, scroll_to_now=True)
        self.assertEqual(self.live_mock.call_count, 2)
        self.assertTrue(self.live_mock.call_args.kwargs.get("scroll_to_now"))

    def test_handle_set_active_view_requests_scroll_to_now_only_when_entering_week_from_elsewhere(self):
        """Two of `app.py`'s three documented auto-scroll triggers funnel
        through `handle_set_active_view`: a real transition INTO week view
        must request it, but a redundant call/heartbeat tick while already
        in week view must not keep re-requesting it forever (which would
        defeat the whole point -- the user's own later manual scroll would
        get yanked back on the very next heartbeat)."""
        self.app.active_view = "list"
        refresh_week_mock = MagicMock()
        with patch.object(self.app, "_refresh_week", refresh_week_mock):
            self.app.handle_set_active_view("week")
            self.assertTrue(refresh_week_mock.call_args.kwargs.get("scroll_to_now"))

            # A later heartbeat-style refresh while already in week view
            # (not a fresh handle_set_active_view("week") call) must not
            # see the request again -- it was a one-shot, already consumed.
            refresh_week_mock.reset_mock()
            self.app._refresh_all()
            self.assertFalse(refresh_week_mock.call_args.kwargs.get("scroll_to_now"))

    def test_handle_set_active_view_does_not_request_scroll_to_now_when_leaving_week_view(self):
        self.app.active_view = "week"
        refresh_week_mock = MagicMock()
        with patch.object(self.app, "_refresh_week", refresh_week_mock):
            self.app.handle_set_active_view("list")
            self.assertEqual(refresh_week_mock.call_count, 0, "list view must never call _refresh_week at all")

    def test_handle_week_today_requests_scroll_to_now(self):
        self.app.active_view = "week"
        refresh_week_mock = MagicMock()
        with patch.object(self.app, "_refresh_week", refresh_week_mock):
            self.app.handle_week_today()
            self.assertTrue(refresh_week_mock.call_args.kwargs.get("scroll_to_now"))

    def test_handle_week_prev_and_next_do_not_request_scroll_to_now(self):
        """Navigating between weeks (Prev/Next) is deliberately excluded
        from the auto-scroll triggers -- the user is looking at a specific
        week on purpose, not asking to see "now" again."""
        self.app.active_view = "week"
        refresh_week_mock = MagicMock()
        with patch.object(self.app, "_refresh_week", refresh_week_mock):
            self.app.handle_week_prev()
            self.assertFalse(refresh_week_mock.call_args.kwargs.get("scroll_to_now"))
            refresh_week_mock.reset_mock()
            self.app.handle_week_next()
            self.assertFalse(refresh_week_mock.call_args.kwargs.get("scroll_to_now"))

    def test_refresh_all_skips_both_week_render_levels_while_gadget_mode_is_active(self):
        """Drives the REAL `app.py::_refresh_all()` heartbeat entry point
        (not `_refresh_week()` directly) with `active_view == "week"` AND
        `gadget_mode == True` together -- protects the actual guard at the
        real call site (`_refresh_all`'s `self.active_view == "week" and
        not self.gadget_mode` check), not just `_refresh_week`'s own
        internal dirty-check logic in isolation. Gadget mode doesn't change
        `active_view` (see `MainWindow.set_gadget_mode`'s docstring -- it's
        an orthogonal reskin of the same root window), so this exact
        combination is what a real user produces by opening week view and
        then toggling into the gadget, and is the scenario `_refresh_all`'s
        skip exists to make cheap."""
        self.app.gadget_mode = True
        try:
            self.app._refresh_all()
        finally:
            self.app.gadget_mode = False

        self.render_mock.assert_not_called()
        self.live_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
