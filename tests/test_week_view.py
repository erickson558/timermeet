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
        "on_delete_series": _no_op,
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

    def _settle_week_live_indicators(self, today_index, hour, minute):
        """Drives `update_week_live_indicators` through to a final,
        geometry-resolved placement without waiting on the real 300ms retry
        timer -- same manual-firing technique
        `test_now_line_retries_until_geometry_resolves_then_places_correctly`
        uses, generalized into a helper so other tests can get a
        deterministic placed line regardless of how much real wall-clock
        time has already elapsed since this session's one-time cold-start
        geometry delay (see `_apply_week_now_line`'s docstring)."""
        self.view.update_week_live_indicators(today_index=today_index, hour=hour, minute=minute)
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
