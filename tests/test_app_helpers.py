"""Tests for small pure-function helpers in app.py that don't need a live
Tkinter root -- the gadget-position settings coercion (a real
crash-on-corrupted-settings.json bug found during review of the gadget/skin
mode feature, see SDD.md), plus the monthly calendar view's date-grouping
and month-navigation helpers added in v2.7.0."""

import unittest
from datetime import date

from timermeet_app import models
from timermeet_app.app import _coerce_gadget_coordinate, _group_meetings_by_date, _shift_month


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


if __name__ == "__main__":
    unittest.main()
