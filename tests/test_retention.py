"""Tests for purging stale (past + fully alerted) meetings so the saved
list doesn't grow forever."""

import unittest
from datetime import datetime, timedelta

from timermeet_app import models, retention


def _meeting(id_, when, reminder_sent=True, start_sent=True, series_id="", **overrides):
    data = {
        "id": id_,
        "workName": "Acme",
        "title": "Daily",
        "datetime": when.strftime("%Y-%m-%dT%H:%M"),
        "reminderSent": reminder_sent,
        "startSent": start_sent,
        "seriesId": series_id,
        "recurrenceType": "daily" if series_id else "none",
    }
    data.update(overrides)
    return models.normalize_meeting(data)


class PurgeStaleMeetingsTests(unittest.TestCase):
    def test_old_fully_alerted_meeting_is_purged(self):
        now = datetime(2026, 8, 1, 9, 0)
        stale = _meeting("m1", now - timedelta(days=10))
        kept, purged_count = retention.purge_stale_meetings([stale], now=now)
        self.assertEqual(kept, [])
        self.assertEqual(purged_count, 1)

    def test_meeting_within_grace_period_is_kept(self):
        now = datetime(2026, 8, 1, 9, 0)
        recent = _meeting("m1", now - timedelta(days=2))
        kept, purged_count = retention.purge_stale_meetings([recent], now=now)
        self.assertEqual([m.id for m in kept], ["m1"])
        self.assertEqual(purged_count, 0)

    def test_future_meeting_is_never_purged(self):
        now = datetime(2026, 8, 1, 9, 0)
        future = _meeting("m1", now + timedelta(days=30), reminder_sent=False, start_sent=False)
        kept, purged_count = retention.purge_stale_meetings([future], now=now)
        self.assertEqual([m.id for m in kept], ["m1"])
        self.assertEqual(purged_count, 0)

    def test_meeting_with_pending_alert_is_never_purged_even_if_old(self):
        now = datetime(2026, 8, 1, 9, 0)
        # Old, but the start alert never fired (e.g. app was closed) -- must
        # not vanish silently, that would be indistinguishable from the bug
        # this whole rewrite was meant to fix.
        old_but_pending = _meeting("m1", now - timedelta(days=30), reminder_sent=True, start_sent=False)
        kept, purged_count = retention.purge_stale_meetings([old_but_pending], now=now)
        self.assertEqual([m.id for m in kept], ["m1"])
        self.assertEqual(purged_count, 0)

    def test_latest_occurrence_of_a_series_is_kept_even_if_stale(self):
        now = datetime(2026, 8, 1, 9, 0)
        older = _meeting("m1", now - timedelta(days=20), series_id="s1")
        latest = _meeting("m2", now - timedelta(days=10), series_id="s1")
        kept, purged_count = retention.purge_stale_meetings([older, latest], now=now)
        self.assertEqual([m.id for m in kept], ["m2"])
        self.assertEqual(purged_count, 1)

    def test_does_not_mutate_input_list(self):
        now = datetime(2026, 8, 1, 9, 0)
        meetings = [_meeting("m1", now - timedelta(days=10))]
        original_length = len(meetings)
        retention.purge_stale_meetings(meetings, now=now)
        self.assertEqual(len(meetings), original_length)


if __name__ == "__main__":
    unittest.main()
