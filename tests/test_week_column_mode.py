"""Tests for the work-week (Mon-Fri) / full-week (Mon-Sun) toggle in the
weekly calendar view (SDD.md v2.10.0).

Two layers, mirroring the feature's own split between view and controller:

- `WeekColumnModeWidgetTests` (real `tk.Tk()`/`MainWindow`): proves
  `set_week_column_mode("work")` actually collapses the Saturday/Sunday
  columns to 0px -- not just `.grid_remove()`s them while a still-weighted
  column silently keeps reserving their share of space (confirmed as a real
  Tk behavior before writing the fix, not assumed) -- and that "full" mode
  restores them exactly.
- `WeekColumnModeAppTests` (real `TimerMeetApp` against an isolated scratch
  settings directory, never `data/meetings.json`/real `settings.json` --
  see MEMORY's "never test against live data" note): proves persistence
  through a real save/reload cycle without clobbering sibling
  `settings.json` keys, defensive fallback for a corrupt/missing value, and
  the Saturday/Sunday "now"-line edge case."""

import datetime as datetime_module
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from timermeet_app import storage

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
        "on_delete_series": _no_op,
        "on_set_gadget_skin": _no_op, "on_gadget_resize": _no_op,
    }
    fields.update(overrides)
    return main_window.Callbacks(**fields)


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class WeekColumnModeWidgetTests(unittest.TestCase):
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
        # Every test below mutates shared, class-level widget state (the
        # column mode) -- always leave it back at the default "full" so
        # later tests in this class (and this suite's own dirty-check
        # gating elsewhere) never see a surprise leftover "work" mode.
        self.view.set_week_column_mode("full")
        self.root.update()

    def _weekend_indices(self):
        return main_window._WEEKEND_COLUMN_INDICES

    def test_work_mode_collapses_weekend_columns_to_zero_width_not_just_hidden(self):
        """The load-bearing assertion for this feature: `grid_remove()`
        alone does NOT shrink a `weight=1` column to 0px (confirmed against
        real Tk behavior before writing the fix) -- a real column
        redistribution only happens once that column's `weight` is ALSO
        zeroed. Proven here by a real pixel measurement (Monday's column
        must get WIDER once Saturday/Sunday stop claiming a share), not
        just by checking `grid_info()`."""
        monday_before = self.view._week_day_header_labels[0].winfo_width()

        self.view.set_week_column_mode("work")
        self.root.update()

        monday_after = self.view._week_day_header_labels[0].winfo_width()
        self.assertGreater(
            monday_after, monday_before,
            "Monday's column must actually widen once the weekend columns' weight is zeroed, "
            "proving they really collapsed rather than merely being hidden in place",
        )
        for offset in self._weekend_indices():
            self.assertEqual(
                self.view._week_day_header_labels[offset].grid_info(), {},
                f"weekend day-header label at offset {offset} must be grid_remove()d in work mode",
            )
            self.assertEqual(
                self.view._week_grid_frame.grid_columnconfigure(offset + 1)["weight"], 0,
                f"weekend column {offset + 1}'s weight must be zeroed in the scrollable grid frame",
            )
            self.assertEqual(
                self.view._week_day_header_row.grid_columnconfigure(offset + 1)["weight"], 0,
                f"weekend column {offset + 1}'s weight must be zeroed in the fixed day-header row too",
            )
            for row in range(main_window.WEEK_ROWS):
                cell = self.view._week_cells[row * main_window.WEEK_COLS + offset]
                self.assertEqual(
                    cell.frame.grid_info(), {},
                    f"hour-cell at row {row}, weekend offset {offset} must be grid_remove()d in work mode",
                )

    def test_full_mode_restores_weekend_columns_without_rebuilding_any_widget(self):
        monday_full_before = self.view._week_day_header_labels[0].winfo_width()
        original_cell_ids = {id(w.frame) for w in self.view._week_cells}
        original_label_ids = {id(lbl) for lbl in self.view._week_day_header_labels}

        self.view.set_week_column_mode("work")
        self.root.update()
        self.view.set_week_column_mode("full")
        self.root.update()

        self.assertEqual(monday_full_before, self.view._week_day_header_labels[0].winfo_width())
        for offset in self._weekend_indices():
            self.assertNotEqual(self.view._week_day_header_labels[offset].grid_info(), {})
            self.assertEqual(self.view._week_grid_frame.grid_columnconfigure(offset + 1)["weight"], 1)
            self.assertEqual(self.view._week_day_header_row.grid_columnconfigure(offset + 1)["weight"], 1)
            for row in range(main_window.WEEK_ROWS):
                cell = self.view._week_cells[row * main_window.WEEK_COLS + offset]
                self.assertNotEqual(cell.frame.grid_info(), {})
        # No cell/label was ever destroyed and rebuilt -- same Python
        # objects throughout (same discipline as every other calendar/week
        # rebuild-avoidance in this codebase since v2.7.0).
        self.assertEqual({id(w.frame) for w in self.view._week_cells}, original_cell_ids)
        self.assertEqual({id(lbl) for lbl in self.view._week_day_header_labels}, original_label_ids)

    def test_toggle_button_label_announces_the_state_a_click_leads_to(self):
        """Same convention `language_button` already uses: the button's text
        names the state a click switches TO, not the current state."""
        self.view.set_week_column_mode("full")
        self.view.apply_translations("es")
        self.assertEqual(
            self.view.week_column_toggle_button.cget("text"),
            main_window.i18n.t("weekViewWorkWeekButton", "es"),
        )
        self.view.set_week_column_mode("work")
        self.view.apply_translations("es")
        self.assertEqual(
            self.view.week_column_toggle_button.cget("text"),
            main_window.i18n.t("weekViewFullWeekButton", "es"),
        )

    def test_now_line_snaps_to_new_column_geometry_immediately_after_toggle_not_stale_for_60s(self):
        """Direct regression test for a real bug found by adversarial review
        of v2.10.0 (SDD.md v2.10.0's work-week toggle section): the live "now" line is a separately
        `.place()`d widget with ABSOLUTE pixel x/width (see
        `_apply_week_now_line`'s docstring) -- before this fix, toggling
        this mode left it rendered at its PRE-toggle width/x (a real,
        empirically-measured example: a column that grew from 151px to
        213px after switching to work-week mode left the line stuck at the
        old 151px) until the next per-minute heartbeat tick happened to
        re-invoke `update_week_live_indicators` on its own -- up to ~60 real
        seconds later, since neither `today_index`/`hour`/`minute` (that
        tick's own dirty-check key) changes just because the column layout
        did.

        Proven here against REAL Tk geometry, not mocked `winfo_width`: a
        single ordinary `root.update()` -- the same one event-loop pass any
        real user interaction naturally gets, nothing more, and definitely
        not a 60-second wait -- must already be enough for the line to
        match Wednesday's actual new column width/x. (A synchronous call
        with no `update()` at all still can't observe this: confirmed
        directly, not assumed, that Tk does not recompute a grid column's
        real width inside the same call that changes
        `grid_columnconfigure`/`.grid_remove()` -- this is exactly why the
        production fix reacts to a real `<Configure>` event instead of
        guessing at a fixed delay, see `_schedule_week_now_line_update`'s
        docstring.)"""
        self.view.set_week_column_mode("full")
        self.root.update()

        self.view.update_week_live_indicators(today_index=2, hour=9, minute=0)  # Wednesday
        # Deterministically settle any cold-start geometry retry (same
        # technique `tests/test_week_view.py::_settle_week_live_indicators`
        # uses) before taking the "before" baseline, so this test is not
        # accidentally exercising that unrelated retry mechanism instead of
        # the toggle fix under test here.
        attempts = 0
        while self.view._week_live_retry_job is not None and attempts <= main_window._WEEK_LINE_MAX_RETRIES:
            self.root.after_cancel(self.view._week_live_retry_job)
            self.root.update()
            self.view._apply_week_now_line()
            attempts += 1

        reference_cell = self.view._week_cells[2].frame
        before_place = dict(self.view._week_now_line.place_info())
        self.assertNotEqual(before_place, {}, "must already be placed before this test can prove it stays fresh")
        self.assertEqual(int(before_place["width"]), reference_cell.winfo_width())

        self.view.set_week_column_mode("work")
        self.root.update()

        after_place = dict(self.view._week_now_line.place_info())
        self.assertEqual(
            int(after_place["width"]), reference_cell.winfo_width(),
            "the now-line's placed width must match Wednesday's real new column width immediately "
            "after a single ordinary update() pass, not stay stuck at the pre-toggle width",
        )
        self.assertEqual(int(after_place["x"]), reference_cell.winfo_x())
        self.assertNotEqual(
            int(before_place["width"]), int(after_place["width"]),
            "this assertion is only meaningful if the column width actually changed by the toggle",
        )


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class WeekColumnModeAppTests(unittest.TestCase):
    def setUp(self):
        self._scratch_dir = tempfile.mkdtemp(prefix="timermeet_week_column_mode_test_")
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

    def test_defaults_to_full_week_when_setting_is_absent(self):
        app = self._build_app()
        self.assertEqual(app.week_column_mode, "full")
        self.assertEqual(app.view._week_column_mode, "full")

    def test_toggle_persists_across_a_save_reload_cycle(self):
        app = self._build_app()
        self.assertEqual(app.week_column_mode, "full")
        app.handle_toggle_week_column_mode()
        self.assertEqual(app.week_column_mode, "work")

        on_disk = json.loads((Path(self._scratch_dir) / "data" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["weekColumnMode"], "work")

        self._destroy_app(app)
        app2 = self._build_app()
        self.assertEqual(app2.week_column_mode, "work")
        self.assertEqual(app2.view._week_column_mode, "work")

    def test_toggle_back_to_full_persists_too(self):
        app = self._build_app()
        app.handle_toggle_week_column_mode()  # -> work
        app.handle_toggle_week_column_mode()  # -> full
        self.assertEqual(app.week_column_mode, "full")
        on_disk = json.loads((Path(self._scratch_dir) / "data" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["weekColumnMode"], "full")

    def test_toggle_does_not_clobber_sibling_settings_keys(self):
        """Same read-merge-write discipline `language`/`gadgetMode` already
        follow (see MEMORY's settings-merge note, fixed for real in
        v2.4.0) -- a partial `save_settings()` call here would silently
        wipe out `language`/`companies`/`gadgetMode`."""
        settings = storage.load_settings()
        settings["language"] = "en"
        settings["companies"] = ["Acme", "Globex"]
        settings["gadgetMode"] = True
        storage.save_settings(settings)

        app = self._build_app()
        app.handle_toggle_week_column_mode()

        on_disk = json.loads((Path(self._scratch_dir) / "data" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["weekColumnMode"], "work")
        self.assertEqual(on_disk["language"], "en")
        self.assertEqual(on_disk["companies"], ["Acme", "Globex"])
        self.assertEqual(on_disk["gadgetMode"], True)

    def test_corrupt_or_unrecognized_saved_value_falls_back_to_full(self):
        storage.save_settings({"weekColumnMode": "bogus-value"})
        app = self._build_app()
        self.assertEqual(app.week_column_mode, "full")

    def test_missing_settings_file_falls_back_to_full_without_crashing(self):
        # No settings.json at all yet (fresh install) -- storage.load_settings()
        # already returns {} for this case; just confirming the app doesn't
        # choke reading `weekColumnMode` from an empty dict.
        app = self._build_app()
        self.assertEqual(app.week_column_mode, "full")

    def test_weekend_plus_work_mode_hides_now_line_without_exhausting_retries(self):
        """SDD.md's explicit edge case: today falling on Sat/Sun while in
        work-week mode must hide the "now" line through the SAME
        already-proven "not the current week" path (today_index=None), not
        by burning through `_apply_week_now_line`'s retry budget against a
        permanently-collapsed column."""
        app = self._build_app()
        app.week_column_mode = "work"
        app.view.set_week_column_mode("work")
        app.active_view = "week"
        app.view.set_active_view("week")

        saturday = date(2026, 8, 15)
        app._week_anchor = saturday
        app._last_rendered_week_signature = None
        app._last_rendered_week_live_state = None

        render_mock = MagicMock()
        # Nivel A (`render_week_grid`, the expensive 168-cell rebind pass)
        # is mocked -- irrelevant to this edge case. Nivel B
        # (`update_week_live_indicators`) is left REAL so the actual
        # view-layer guard (never scheduling a retry when `today_index` is
        # `None`) is exercised for real, not just asserted about app.py's
        # own computed argument.
        with patch.object(app.view, "render_week_grid", render_mock):

            class _Frozen(datetime_module.datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime_module.datetime(2026, 8, 15, 9, 0, 0)  # a Saturday

            with patch("timermeet_app.app.datetime", _Frozen):
                app._refresh_week(_Frozen.now())

        self.assertIsNone(
            app.view._week_live_state[0],
            "today_index must be None on a Saturday/Sunday while in work-week mode",
        )
        # The real view-layer guard: with a None index, `_apply_week_now_line`
        # takes the plain "hide" branch and never reaches (let alone
        # exhausts) its retry logic at all.
        self.assertIsNone(app.view._week_live_retry_job)
        self.assertEqual(app.view._week_live_retry_count, 0)
        self.assertEqual(app.view._week_now_line.place_info(), {})


if __name__ == "__main__":
    unittest.main()
