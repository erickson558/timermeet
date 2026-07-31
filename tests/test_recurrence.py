"""Tests for the recurrence engine and the weekly series auto-renewal engine
-- the highest-regression-risk logic ported from legacy-php/assets/app.js
(this is exactly what silently stopped reminding users before v1.3.0 of the
web app)."""

import unittest
from datetime import datetime, timedelta

from timermeet_app import models, recurrence


class AddRecurrenceToDateTests(unittest.TestCase):
    def test_daily_steps_by_one_day(self):
        base = datetime(2026, 8, 3, 9, 0)  # Monday
        self.assertEqual(recurrence.add_recurrence_to_date(base, "daily", 3), datetime(2026, 8, 6, 9, 0))

    def test_weekly_steps_by_seven_days(self):
        base = datetime(2026, 8, 3, 9, 0)
        self.assertEqual(recurrence.add_recurrence_to_date(base, "weekly", 2), datetime(2026, 8, 17, 9, 0))

    def test_biweekly_steps_by_fourteen_days(self):
        base = datetime(2026, 8, 3, 9, 0)
        self.assertEqual(recurrence.add_recurrence_to_date(base, "biweekly", 2), datetime(2026, 8, 31, 9, 0))

    def test_monthly_overflows_short_month_like_js_date(self):
        # Mirrors JS `date.setMonth()` overflow semantics: Jan 31 + 1 month
        # lands on Mar 3 in a non-leap year, not clamped to Feb 28.
        base = datetime(2026, 1, 31, 9, 0)
        self.assertEqual(recurrence.add_recurrence_to_date(base, "monthly", 1), datetime(2026, 3, 3, 9, 0))

    def test_weekdays_skips_saturday_and_sunday(self):
        friday = datetime(2026, 8, 7, 9, 0)
        result = recurrence.add_recurrence_to_date(friday, "weekdays", 1)
        self.assertEqual(result, datetime(2026, 8, 10, 9, 0))  # next Monday, not Saturday

    def test_none_and_zero_step_return_base_unchanged(self):
        base = datetime(2026, 8, 3, 9, 0)
        self.assertEqual(recurrence.add_recurrence_to_date(base, "none", 5), base)
        self.assertEqual(recurrence.add_recurrence_to_date(base, "daily", 0), base)


def _series_meeting(when, series_id="series-1"):
    return models.normalize_meeting(
        {
            "workName": "Acme",
            "title": "Daily",
            "datetime": when.strftime("%Y-%m-%dT%H:%M"),
            "recurrenceType": "daily",
            "seriesId": series_id,
            "occurrenceIndex": 1,
            "seriesSize": 1,
        }
    )


class WeeklySeriesRenewalTests(unittest.TestCase):
    def test_extends_series_and_is_idempotent_on_a_second_run(self):
        now = datetime(2026, 8, 7, 19, 0)  # Friday, after the 18:00 trigger
        meetings = [_series_meeting(datetime(2026, 8, 7, 9, 0))]

        created_first = recurrence.run_weekly_series_renewal(meetings, now)
        self.assertGreater(created_first, 0)
        total_after_first = len(meetings)

        created_second = recurrence.run_weekly_series_renewal(meetings, now)
        self.assertEqual(created_second, 0)
        self.assertEqual(len(meetings), total_after_first)

    def test_never_creates_past_dated_occurrences_after_a_short_absence(self):
        now = datetime(2026, 8, 7, 19, 0)
        stale = _series_meeting(datetime(2026, 7, 28, 9, 0))  # 10 days stale, well under the safety cap
        meetings = [stale]

        recurrence.run_weekly_series_renewal(meetings, now)

        newly_created = [m for m in meetings if m.id != stale.id]
        self.assertTrue(newly_created)
        for meeting in newly_created:
            self.assertGreaterEqual(meeting.local_datetime(), now)

    def test_safety_cap_is_a_known_limit_for_a_daily_series_stale_beyond_it(self):
        # RENEWAL_MAX_STEPS_PER_SERIES=60 daily steps only reaches ~60 days
        # ahead of a stale occurrence. If that's still short of `now`, no
        # occurrence gets materialized (nothing to attach the next run's
        # cursor to), so a *daily* series abandoned for more than ~2 months
        # cannot self-heal -- inherited from the original app's identical
        # cap (see legacy-php/assets/app.js), documented here rather than
        # silently "fixed" underneath a faithful port. Weekly/biweekly/
        # monthly series tolerate much longer absences (7x/14x/~30x this
        # margin per step) so this only really bites daily recurrence.
        now = datetime(2026, 8, 7, 19, 0)
        stale = _series_meeting(datetime(2026, 6, 1, 9, 0))  # 67 days stale
        meetings = [stale]

        recurrence.run_weekly_series_renewal(meetings, now)

        self.assertEqual(len(meetings), 1)
        self.assertEqual(meetings[0].local_datetime(), stale.local_datetime())

    def test_series_size_stays_in_sync_across_all_occurrences(self):
        now = datetime(2026, 8, 7, 19, 0)
        meetings = [_series_meeting(datetime(2026, 8, 7, 9, 0))]
        recurrence.run_weekly_series_renewal(meetings, now)
        sizes = {m.seriesSize for m in meetings}
        self.assertEqual(len(sizes), 1)
        self.assertEqual(sizes.pop(), len(meetings))

    def test_meeting_without_series_id_is_ignored(self):
        now = datetime(2026, 8, 7, 19, 0)
        one_off = models.normalize_meeting(
            {"workName": "Acme", "title": "One-off", "datetime": "2026-06-01T09:00", "recurrenceType": "none"}
        )
        meetings = [one_off]
        created = recurrence.run_weekly_series_renewal(meetings, now)
        self.assertEqual(created, 0)
        self.assertEqual(len(meetings), 1)


class MostRecentFridayEodTests(unittest.TestCase):
    def test_returns_this_friday_when_its_trigger_already_passed(self):
        now = datetime(2026, 8, 7, 19, 0)  # Friday 19:00, after 18:00
        self.assertEqual(recurrence.most_recent_friday_eod(now), datetime(2026, 8, 7, 18, 0))

    def test_returns_last_week_friday_when_this_fridays_trigger_is_still_ahead(self):
        now = datetime(2026, 8, 7, 10, 0)  # Friday 10:00, before 18:00
        self.assertEqual(recurrence.most_recent_friday_eod(now), datetime(2026, 7, 31, 18, 0))

    def test_never_returns_a_time_in_the_future(self):
        for offset in range(14):
            now = datetime(2026, 8, 1, 0, 0) + timedelta(days=offset, hours=offset % 5)
            self.assertLessEqual(recurrence.most_recent_friday_eod(now), now)


if __name__ == "__main__":
    unittest.main()
