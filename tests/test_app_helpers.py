"""Tests for small pure-function helpers in app.py that don't need a live
Tkinter root -- the gadget-position settings coercion (a real
crash-on-corrupted-settings.json bug found during review of the gadget/skin
mode feature, see SDD.md), plus the monthly calendar view's date-grouping
and month-navigation helpers added in v2.7.0."""

import unittest
from datetime import date

from timermeet_app import main_window, models
from timermeet_app.app import (
    _assign_week_meeting_blocks,
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


class AssignWeekMeetingBlocksTests(unittest.TestCase):
    """Pure clustering/column-split/aggregate-chip logic (SDD.md v2.16.0,
    replaces v2.15.0's lane-only `AssignWeekDurationBlocksTests`), tested
    directly against plain data -- no Tk widgets involved, so this is the
    fast/deterministic layer for the week view's full-color block math; the
    widget-level `.place()` geometry itself is covered separately in
    tests/test_week_view.py."""

    def test_non_overlapping_meetings_all_get_full_width_column_zero(self):
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=30),
            _dated_meeting("2026-08-10T10:00", duration=30),
            _dated_meeting("2026-08-10T11:00", duration=30),
        ]
        blocks, covered = _assign_week_meeting_blocks(0, meetings)
        self.assertEqual(len(blocks), 3)
        self.assertTrue(all(b.column_index == 0 for b in blocks))
        self.assertTrue(all(b.column_count == 1 for b in blocks))
        self.assertTrue(all(b.day_index == 0 for b in blocks))
        self.assertEqual(covered, {m.id for m in meetings})

    def test_two_overlapping_meetings_split_into_two_columns(self):
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=60),
            _dated_meeting("2026-08-10T09:30", duration=60),  # overlaps the first
        ]
        blocks, covered = _assign_week_meeting_blocks(3, meetings)
        self.assertEqual(len(blocks), 2)
        self.assertEqual({b.column_index for b in blocks}, {0, 1})
        self.assertTrue(all(b.column_count == 2 for b in blocks))
        self.assertTrue(all(b.day_index == 3 for b in blocks))
        self.assertEqual(covered, {m.id for m in meetings})

    def test_three_overlapping_meetings_split_into_thirds(self):
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=60),
            _dated_meeting("2026-08-10T09:15", duration=60),
            _dated_meeting("2026-08-10T09:30", duration=60),
        ]
        blocks, _covered = _assign_week_meeting_blocks(0, meetings)
        self.assertEqual(len(blocks), 3)
        self.assertEqual({b.column_index for b in blocks}, {0, 1, 2})
        self.assertTrue(all(b.column_count == 3 for b in blocks))

    def test_meetings_ending_exactly_when_another_starts_do_not_overlap(self):
        # Explicit acceptance criterion: back-to-back meetings (one ends at
        # exactly the moment the next starts) must NOT be treated as
        # concurrent -- each gets its own full-width column, not a split.
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=30),  # ends 09:30
            _dated_meeting("2026-08-10T09:30", duration=30),  # starts exactly then
        ]
        blocks, _covered = _assign_week_meeting_blocks(0, meetings)
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(b.column_index == 0 for b in blocks))
        self.assertTrue(all(b.column_count == 1 for b in blocks))

    def test_a_column_index_stays_fixed_even_once_a_later_slot_frees_up(self):
        # SDD.md decision #1: column_index/column_count are fixed for a
        # block's whole duration, computed once per overlap CLUSTER (a
        # connected component), not re-derived instant-by-instant. All 3
        # meetings below are transitively connected (1-2 overlap, 2-3
        # overlap) even though 1 and 3 alone don't overlap each other --
        # they must all share one cluster's column_count, not each get
        # their own independent 1-column assignment.
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=30, title="A"),  # ends 09:30
            _dated_meeting("2026-08-10T09:15", duration=30, title="B"),  # overlaps A -> col 1
            _dated_meeting("2026-08-10T09:30", duration=30, title="C"),  # A's slot free again -> col 0
        ]
        blocks, _covered = _assign_week_meeting_blocks(0, meetings)
        by_title = {b.title: b for b in blocks}
        self.assertEqual(by_title["A"].column_index, 0)
        self.assertEqual(by_title["B"].column_index, 1)
        self.assertEqual(by_title["C"].column_index, 0)
        # Fixed cluster-wide column_count (peak concurrency = 2), not
        # varying per meeting even though C itself never overlaps B.
        self.assertTrue(all(b.column_count == 2 for b in blocks))

    def test_two_non_overlapping_clusters_the_same_day_are_independent(self):
        meetings = [
            _dated_meeting("2026-08-10T09:00", duration=30, title="Solo"),
            _dated_meeting("2026-08-10T14:00", duration=30, title="PairA"),
            _dated_meeting("2026-08-10T14:15", duration=30, title="PairB"),
        ]
        blocks, _covered = _assign_week_meeting_blocks(0, meetings)
        by_title = {b.title: b for b in blocks}
        self.assertEqual(by_title["Solo"].column_count, 1)
        self.assertEqual(by_title["PairA"].column_count, 2)
        self.assertEqual(by_title["PairB"].column_count, 2)

    def test_concurrency_at_the_structural_cap_gets_no_aggregate_chip(self):
        # Exactly WEEK_MAX_CONCURRENT_SPLIT concurrent meetings must all get
        # their own real block -- the aggregate only kicks in once
        # concurrency EXCEEDS the cap, not when it merely reaches it.
        cap = main_window.WEEK_MAX_CONCURRENT_SPLIT
        base = "2026-08-10T09:00"
        meetings = [_dated_meeting(base, duration=60) for _ in range(cap)]
        blocks, covered = _assign_week_meeting_blocks(0, meetings)
        self.assertEqual(len(blocks), cap)
        self.assertTrue(all(not b.is_overflow for b in blocks))
        self.assertEqual({b.column_index for b in blocks}, set(range(cap)))
        self.assertEqual(covered, {m.id for m in meetings})

    def test_concurrency_beyond_the_cap_gets_a_shared_aggregate_chip(self):
        cap = main_window.WEEK_MAX_CONCURRENT_SPLIT
        base = "2026-08-10T09:00"
        meetings = [_dated_meeting(base, duration=60) for _ in range(cap + 2)]  # 6 with a cap of 4
        blocks, covered = _assign_week_meeting_blocks(0, meetings)
        real_blocks = [b for b in blocks if not b.is_overflow]
        aggregate_blocks = [b for b in blocks if b.is_overflow]
        # At most cap - 1 real, individually-titled blocks...
        self.assertEqual(len(real_blocks), cap - 1)
        # ...plus exactly one shared aggregate chip covering the rest.
        self.assertEqual(len(aggregate_blocks), 1)
        aggregate = aggregate_blocks[0]
        self.assertIsNone(aggregate.meeting_id)
        self.assertEqual(aggregate.overflow_count, len(meetings) - (cap - 1))
        self.assertEqual(aggregate.column_index, cap - 1)
        self.assertTrue(all(b.column_count == cap for b in blocks))
        # No meeting from this cluster is left with zero representation.
        self.assertEqual(covered, {m.id for m in meetings})

    def test_more_than_the_per_day_cap_stops_producing_blocks(self):
        # Every meeting starts at a different, non-overlapping hour, so the
        # concurrency cap alone would never kick in -- only the independent
        # per-day total-block cap should limit this.
        meetings = [
            _dated_meeting(f"2026-08-10T{hour:02d}:00", duration=15)
            for hour in range(main_window.WEEK_MAX_DURATION_BLOCKS_PER_DAY + 5)
        ]
        blocks, covered = _assign_week_meeting_blocks(0, meetings)
        self.assertEqual(len(blocks), main_window.WEEK_MAX_DURATION_BLOCKS_PER_DAY)
        self.assertEqual(len(covered), main_window.WEEK_MAX_DURATION_BLOCKS_PER_DAY)

    def test_empty_day_returns_no_blocks(self):
        blocks, covered = _assign_week_meeting_blocks(0, [])
        self.assertEqual(blocks, [])
        self.assertEqual(covered, set())

    def test_block_fields_mirror_the_source_meeting(self):
        meeting = _dated_meeting("2026-08-10T14:30", duration=45, title="Retro")
        blocks, covered = _assign_week_meeting_blocks(5, [meeting])
        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block.meeting_id, meeting.id)
        self.assertEqual(block.duration_minutes, 45)
        self.assertAlmostEqual(block.start_hour_float, 14.5)
        self.assertEqual(block.day_index, 5)
        self.assertEqual(block.color, _color_for_work_name("Acme"))
        self.assertEqual(block.title, "Retro")
        self.assertEqual(block.time_text, "14:30")
        self.assertFalse(block.is_overflow)
        self.assertEqual(covered, {meeting.id})

    def test_series_occurrence_count_is_looked_up_for_recurring_meetings(self):
        meeting = models.normalize_meeting(
            {
                "workName": "Acme", "title": "Standup", "datetime": "2026-08-10T09:00",
                "recurrenceType": "weekly", "seriesId": "series-1",
            }
        )
        blocks, _covered = _assign_week_meeting_blocks(0, [meeting], series_sizes={"series-1": 4})
        self.assertEqual(blocks[0].series_occurrence_count, 4)


if __name__ == "__main__":
    unittest.main()
