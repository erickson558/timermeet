"""Tests for the merge-on-save conflict resolution in storage.py -- the
desktop replacement for the web app's multi-tab sync, now covering two
OneDrive-synced machines writing the same data/meetings.json instead."""

import unittest
from datetime import datetime, timedelta

from timermeet_app import models, storage


def _meeting(id_, updated_at, **overrides):
    data = {
        "id": id_,
        "workName": "Acme",
        "title": "Daily",
        "datetime": "2026-08-10T09:00",
        "updatedAt": updated_at,
        "createdAt": updated_at,
    }
    data.update(overrides)
    return models.normalize_meeting(data)


class MergeMeetingPairTests(unittest.TestCase):
    def test_newer_updated_at_wins_on_content(self):
        older = _meeting("m1", "2026-08-01T09:00:00", title="Old title")
        newer = _meeting("m1", "2026-08-02T09:00:00", title="New title")

        merged = storage.merge_meeting_pair(older, newer)
        self.assertEqual(merged.title, "New title")

        merged_reversed = storage.merge_meeting_pair(newer, older)
        self.assertEqual(merged_reversed.title, "New title")

    def test_sent_flags_are_always_ored_regardless_of_which_side_wins(self):
        disk = _meeting("m1", "2026-08-02T09:00:00", reminderSent=True, startSent=False)
        memory = _meeting("m1", "2026-08-01T09:00:00", reminderSent=False, startSent=True)

        merged = storage.merge_meeting_pair(disk, memory)
        self.assertTrue(merged.reminderSent)
        self.assertTrue(merged.startSent)


class MergeMeetingListsTests(unittest.TestCase):
    def test_disk_only_meeting_is_kept(self):
        disk = [_meeting("from-disk", "2026-08-01T09:00:00")]
        merged = storage.merge_meeting_lists(disk, [])
        self.assertEqual({m.id for m in merged}, {"from-disk"})

    def test_brand_new_local_meeting_survives_within_grace_period(self):
        now = datetime(2026, 8, 10, 12, 0, 5)
        just_created = _meeting("brand-new", now.isoformat())
        merged = storage.merge_meeting_lists([], [just_created], now=now)
        self.assertEqual({m.id for m in merged}, {"brand-new"})

    def test_old_local_only_meeting_is_dropped_as_a_legitimate_deletion(self):
        now = datetime(2026, 8, 10, 12, 0, 0)
        old_created_at = (now - timedelta(minutes=5)).isoformat()
        stale_local = _meeting("deleted-elsewhere", old_created_at)
        merged = storage.merge_meeting_lists([], [stale_local], now=now)
        self.assertEqual(merged, [])

    def test_same_id_on_both_sides_merges_instead_of_duplicating(self):
        disk = [_meeting("m1", "2026-08-02T09:00:00", title="From disk")]
        memory = [_meeting("m1", "2026-08-01T09:00:00", title="From memory")]
        merged = storage.merge_meeting_lists(disk, memory)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].title, "From disk")


if __name__ == "__main__":
    unittest.main()
