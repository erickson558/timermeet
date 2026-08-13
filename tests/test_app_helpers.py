"""Tests for small pure-function helpers in app.py that don't need a live
Tkinter root -- the gadget-position settings coercion (a real
crash-on-corrupted-settings.json bug found during review of the gadget/skin
mode feature, see SDD.md), plus the monthly calendar view's date-grouping
and month-navigation helpers added in v2.7.0."""

import unittest
from datetime import date

from timermeet_app import main_window, models
from timermeet_app.app import (
    _assign_week_duration_blocks,
    _coerce_app_theme,
    _coerce_gadget_coordinate,
    _coerce_gadget_size,
    _color_for_work_name,
    _group_meetings_by_date,
    _shift_month,
)


class CoerceGadgetCoordinateTests(unittest.TestCase):
    def test_accepts_int(self):
        self.assertEqual(_coerce_gadget_coordinate(150), 150)

    def test_accepts_float_and_truncates(self):
        self.assertEqual(_coerce_gadget_coordinate(150.9), 150)

    def test_rejects_non_numeric_string(self):
        self.assertIsNone(_coerce_gadget_coordinate("unknown"))

    def test_rejects_bool(self):
        # bool is a subclass of int in Python; a stray True/False is not a
        # sensible screen coordinate and must not be coerced to 1/0.
        self.assertIsNone(_coerce_gadget_coordinate(True))
        self.assertIsNone(_coerce_gadget_coordinate(False))

    def test_rejects_none(self):
        self.assertIsNone(_coerce_gadget_coordinate(None))

    def test_rejects_list(self):
        self.assertIsNone(_coerce_gadget_coordinate([1, 2]))

    def test_rejects_nan_and_infinity(self):
        # Python's `json` module accepts the non-standard NaN/Infinity
        # literals on load, so a hand-edited settings.json with
        # `"gadgetX": NaN` parses cleanly into `float("nan")` -- which then
        # passed the old `isinstance(value, (int, float))` check and
        # crashed on `int(value)` (ValueError for NaN, OverflowError for
        # +/-Infinity) instead of falling back to the default position.
        self.assertIsNone(_coerce_gadget_coordinate(float("nan")))
        self.assertIsNone(_coerce_gadget_coordinate(float("inf")))
        self.assertIsNone(_coerce_gadget_coordinate(float("-inf")))


class CoerceGadgetSizeTests(unittest.TestCase):
    def test_accepts_int(self):
        self.assertEqual(_coerce_gadget_size(300, default=280), 300)

    def test_accepts_float_and_truncates(self):
        self.assertEqual(_coerce_gadget_size(300.7, default=280), 300)

    def test_rejects_non_numeric_string_and_falls_back_to_default(self):
        self.assertEqual(_coerce_gadget_size("wide", default=280), 280)

    def test_rejects_list_and_falls_back_to_default(self):
        self.assertEqual(_coerce_gadget_size([300], default=280), 280)

    def test_rejects_bool_and_falls_back_to_default(self):
        # Same bool-is-a-subclass-of-int trap as `_coerce_gadget_coordinate`.
        self.assertEqual(_coerce_gadget_size(True, default=280), 280)

    def test_rejects_none_and_falls_back_to_default(self):
        self.assertEqual(_coerce_gadget_size(None, default=280), 280)

    def test_rejects_nan_and_infinity_and_falls_back_to_default(self):
        # Same crash-on-corrupted-settings.json risk as
        # `_coerce_gadget_coordinate`'s NaN/Infinity case above: a hand-edited
        # `"gadgetWidth": Infinity` parses cleanly via `json.loads` but used
        # to raise OverflowError/ValueError out of `int(value)` before this
        # helper's downstream caller (`MainWindow._resolve_gadget_size`'s
        # min/max clamp) ever got a chance to run.
        self.assertEqual(_coerce_gadget_size(float("nan"), default=280), 280)
        self.assertEqual(_coerce_gadget_size(float("inf"), default=280), 280)
        self.assertEqual(_coerce_gadget_size(float("-inf"), default=280), 280)


class CoerceAppThemeTests(unittest.TestCase):
    """Renamed from `CoerceGadgetSkinTests` in v2.14.0 alongside
    `_coerce_gadget_skin` -> `_coerce_app_theme` (the gadget-only skin
    picker grew into a whole-app theme picker, SDD.md v2.14.0) -- same
    coercion behavior, just against the renamed `APP_THEMES` registry."""

    def test_accepts_known_theme_key(self):
        self.assertEqual(_coerce_app_theme("glass"), "glass")

    def test_rejects_unknown_theme_key(self):
        self.assertEqual(_coerce_app_theme("does-not-exist"), main_window.APP_DEFAULT_THEME)

    def test_rejects_non_string(self):
        self.assertEqual(_coerce_app_theme(123), main_window.APP_DEFAULT_THEME)

    def test_rejects_none(self):
        self.assertEqual(_coerce_app_theme(None), main_window.APP_DEFAULT_THEME)


def _meeting(when: str, title: str = "Standup"):
    return models.normalize_meeting({"workName": "Acme", "title": title, "datetime": when})


class GroupMeetingsByDateTests(unittest.TestCase):
    def test_groups_same_day_meetings_together(self):
        morning = _meeting("2026-08-10T09:00", "Daily")
        evening = _meeting("2026-08-10T18:00", "Retro")
        other_day = _meeting("2026-08-11T09:00", "Planning")

        groups = _group_meetings_by_date([morning, evening, other_day])

        self.assertEqual(set(groups.keys()), {date(2026, 8, 10), date(2026, 8, 11)})
        self.assertEqual({m.id for m in groups[date(2026, 8, 10)]}, {morning.id, evening.id})
        self.assertEqual([m.id for m in groups[date(2026, 8, 11)]], [other_day.id])

    def test_meeting_with_empty_datetime_is_dropped_not_crashed_on(self):
        # local_datetime() returns None for an empty/unparseable value --
        # such a meeting has no calendar cell to belong to (see SDD.md's
        # acceptance criteria for the calendar view) and must never appear
        # in any group.
        broken = models.normalize_meeting({"workName": "Acme", "title": "Broken", "datetime": ""})
        groups = _group_meetings_by_date([broken])
        self.assertEqual(groups, {})

    def test_meeting_with_malformed_nonempty_datetime_is_dropped_not_crashed_on(self):
        # A genuinely malformed but non-empty value -- e.g. hand-edited
        # meetings.json, or a value that merely LOOKS date-shaped but isn't
        # a real calendar date -- must be dropped exactly like the
        # empty-string case above, not raise out of `strptime` and crash the
        # heartbeat's calendar rebuild.
        unparseable = models.normalize_meeting(
            {"workName": "Acme", "title": "Garbled", "datetime": "not-a-date"}
        )
        invalid_calendar_date = models.normalize_meeting(
            {"workName": "Acme", "title": "OutOfRange", "datetime": "2026-13-45T09:00"}
        )
        groups = _group_meetings_by_date([unparseable, invalid_calendar_date])
        self.assertEqual(groups, {})

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(_group_meetings_by_date([]), {})


class ShiftMonthTests(unittest.TestCase):
    def test_advances_within_the_same_year(self):
        self.assertEqual(_shift_month(2026, 3, 1), (2026, 4))

    def test_rewinds_within_the_same_year(self):
        self.assertEqual(_shift_month(2026, 3, -1), (2026, 2))

    def test_advancing_past_december_rolls_into_next_january(self):
        self.assertEqual(_shift_month(2026, 12, 1), (2027, 1))

    def test_rewinding_before_january_rolls_into_previous_december(self):
        self.assertEqual(_shift_month(2026, 1, -1), (2025, 12))

    def test_zero_delta_is_a_no_op(self):
        self.assertEqual(_shift_month(2026, 6, 0), (2026, 6))


def _dated_meeting(datetime_str: str, duration: int = 30, title: str = "Standup"):
    return models.normalize_meeting(
        {"workName": "Acme", "title": title, "datetime": datetime_str, "durationMinutes": duration}
    )


class AssignWeekDurationBlocksTests(unittest.TestCase):
    """Pure lane-assignment/cap logic (SDD.md v2.15.0), tested directly
    against plain data -- no Tk widgets involved, so this is the fast/
    deterministic layer for the week view's duration-bar math; the widget-
    level `.place()` geometry itself is covered separately in
    tests/test_week_view.py."""

    def test_non_overlapping_meetings_all_get_lane_zero(self):
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=30),
            _dated_meeting("2026-08-10T10:00", duration=30),
            _dated_meeting("2026-08-10T11:00", duration=30),
        ]
        blocks = _assign_week_duration_blocks(0, meetings)
        self.assertEqual(len(blocks), 3)
        self.assertTrue(all(b.lane == 0 for b in blocks))
        self.assertTrue(all(b.day_index == 0 for b in blocks))

    def test_two_overlapping_meetings_get_different_lanes(self):
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=60),
            _dated_meeting("2026-08-10T09:30", duration=60),  # overlaps the first
        ]
        blocks = _assign_week_duration_blocks(3, meetings)
        self.assertEqual(len(blocks), 2)
        self.assertEqual({b.lane for b in blocks}, {0, 1})
        self.assertTrue(all(b.day_index == 3 for b in blocks))

    def test_a_lane_is_reused_once_its_previous_occupant_has_ended(self):
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=30),  # ends 09:30
            _dated_meeting("2026-08-10T09:15", duration=30),  # overlaps -> lane 1
            _dated_meeting("2026-08-10T09:30", duration=30),  # first lane free again -> lane 0
        ]
        blocks = sorted(_assign_week_duration_blocks(0, meetings), key=lambda b: b.start_hour_float)
        self.assertEqual([b.lane for b in blocks], [0, 1, 0])

    def test_a_fourth_concurrent_meeting_beyond_the_lane_cap_gets_no_block(self):
        base = "2026-08-10T09:00"
        meetings = [_dated_meeting(base, duration=60) for _ in range(main_window.WEEK_MAX_DURATION_LANES + 1)]
        blocks = _assign_week_duration_blocks(0, meetings)
        self.assertEqual(len(blocks), main_window.WEEK_MAX_DURATION_LANES)
        self.assertEqual({b.lane for b in blocks}, set(range(main_window.WEEK_MAX_DURATION_LANES)))

    def test_more_than_the_per_day_cap_stops_producing_blocks(self):
        # Every meeting starts at a different, non-overlapping hour, so the
        # lane cap alone would never kick in -- only the independent
        # per-day total-block cap should limit this.
        meetings = [
            _dated_meeting(f"2026-08-10T{hour:02d}:00", duration=15)
            for hour in range(main_window.WEEK_MAX_DURATION_BLOCKS_PER_DAY + 5)
        ]
        blocks = _assign_week_duration_blocks(0, meetings)
        self.assertEqual(len(blocks), main_window.WEEK_MAX_DURATION_BLOCKS_PER_DAY)

    def test_empty_day_returns_no_blocks(self):
        self.assertEqual(_assign_week_duration_blocks(0, []), [])

    def test_block_fields_mirror_the_source_meeting(self):
        meeting = _dated_meeting("2026-08-10T14:30", duration=45, title="Retro")
        blocks = _assign_week_duration_blocks(5, [meeting])
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block.meeting_id, meeting.id)
        self.assertEqual(block.duration_minutes, 45)
        self.assertAlmostEqual(block.start_hour_float, 14.5)
        self.assertEqual(block.day_index, 5)
        self.assertEqual(block.color, _color_for_work_name("Acme"))


if __name__ == "__main__":
    unittest.main()
