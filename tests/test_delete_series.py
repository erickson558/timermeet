"""Tests for "Eliminar serie completa" (SDD.md v2.11.0): deleting every
occurrence sharing a `seriesId`, past and future, with no anchor kept --
distinct from (and more aggressive than) `retention.py`'s automatic/manual
purges, which always keep a series' latest occurrence.

Three layers, mirroring the feature's own design:

- `DeleteSeriesMergeTombstoneTests` (no Tk needed): a pure `storage.py`-level
  regression test, styled exactly like `tests/test_merge.py`'s own
  "another machine hasn't seen the delete yet" case, proving the deletion
  survives a stale disk merge instead of being silently resurrected (the
  v2.3.0 bug class).
- `DeleteSeriesAppTests` (real `TimerMeetApp` against an isolated scratch
  data directory, never `data/meetings.json` -- see MEMORY's "never test
  against live data" note): the real `handle_delete_series` wiring, at a
  realistic standalone-meeting volume -- its only two no-op guards (an
  empty `seriesId` target, which must never fall through to wiping out
  every standalone meeting in the app; and a nonexistent meeting id).
  There is no separate "no live siblings" guard *in this method* to test
  here -- that check is the UI's own enablement condition for showing the
  menu item at all (see `SeriesOccurrenceCountRefreshTests` below), not a
  guard `handle_delete_series` itself performs. Also covered: isolation
  between two distinct live series plus standalones, the real
  `_pending_deleted_ids`/`storage.save_meetings` plumbing (both a
  mocked-argument capture and a full real end-to-end disk round trip
  against a seeded stale on-disk snapshot, proving no resurrection
  without mocking storage at all), and the toast.
- `SeriesOccurrenceCountRefreshTests` (same real-app harness): proves
  `_refresh_calendar`/`_refresh_week` compute `CalendarEntry.series_occurrence_count`
  from `recurrence.group_meetings_by_series` (a live count), never from the
  stale/inflatable `meeting.seriesSize` field.
"""

import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from timermeet_app import models, storage

try:
    import tkinter as tk

    from timermeet_app.app import TimerMeetApp
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    TimerMeetApp = None


def _meeting(id_, **overrides):
    data = {
        "id": id_,
        "workName": "Acme",
        "title": "Daily",
        "datetime": "2026-08-10T09:00",
    }
    data.update(overrides)
    return models.normalize_meeting(data)


class DeleteSeriesMergeTombstoneTests(unittest.TestCase):
    """Mirrors `tests/test_merge.py::MergeMeetingListsTests
    .test_deleted_id_is_not_resurrected_from_a_stale_disk_read`, but for a
    multi-id series delete -- proving `_apply_meetings`'s set-based diff (the
    same path a single delete already uses) protects a multi-record delete
    exactly the same way, with no special-casing needed."""

    def test_deleted_series_survives_a_stale_disk_read_standalone_meeting_untouched(self):
        series = [
            _meeting(f"series-{i}", seriesId="s1", recurrenceType="weekly", seriesSize=1)
            for i in range(3)
        ]
        standalone = _meeting("standalone", seriesId="", recurrenceType="none")
        before = series + [standalone]
        target = series[0]

        # Exactly `handle_delete_series`'s own filter -- kept in the test as
        # a hand-written line (not imported) so this proves the FILTER
        # LOGIC is safe in combination with the merge, not just that the
        # app method happens to call the right things.
        after = [m for m in before if m.seriesId != target.seriesId]
        deleted_ids = {m.id for m in series}
        self.assertEqual(after, [standalone])

        # "Another machine" wrote a snapshot before it ever saw this delete
        # -- still has all 3 series occurrences on disk.
        stale_disk = before
        merged = storage.merge_meeting_lists(stale_disk, after, deleted_ids=deleted_ids)

        self.assertEqual({m.id for m in merged}, {"standalone"})

    def test_deleted_ids_do_not_affect_an_unrelated_second_series(self):
        series_a = [_meeting(f"a{i}", seriesId="sA", recurrenceType="weekly") for i in range(2)]
        series_b = [_meeting(f"b{i}", seriesId="sB", recurrenceType="weekly") for i in range(2)]
        before = series_a + series_b
        target = series_a[0]
        after = [m for m in before if m.seriesId != target.seriesId]
        deleted_ids = {m.id for m in series_a}

        merged = storage.merge_meeting_lists(before, after, deleted_ids=deleted_ids)

        self.assertEqual({m.id for m in merged}, {m.id for m in series_b})


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class DeleteSeriesAppTests(unittest.TestCase):
    def setUp(self):
        self._scratch_dir = tempfile.mkdtemp(prefix="timermeet_delete_series_test_")
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

    def _four_meetings(self):
        """3 series occurrences sharing `seriesId="s1"` (deliberately with a
        misleading/stale `seriesSize=8`, per SDD.md's own documented
        finding that `retention.py` never decrements it) plus 1 standalone
        meeting (`seriesId == ""`, `recurrenceType == "none"`, exactly how
        `_save_new` leaves a non-recurring meeting)."""
        series = [
            _meeting(
                f"series-{i}", seriesId="s1", recurrenceType="weekly", seriesSize=8, occurrenceIndex=i + 1,
                datetime=f"2026-08-{10 + i:02d}T09:00",
            )
            for i in range(3)
        ]
        standalone = _meeting("standalone", seriesId="", recurrenceType="none", datetime="2026-08-20T10:00")
        return series, standalone

    def test_deletes_every_series_occurrence_and_leaves_standalone_meeting_untouched(self):
        app = self._build_app()
        series, standalone = self._four_meetings()
        app.meetings = series + [standalone]
        app._persist(silent=True)  # establish an "already synced to disk" baseline

        toast_mock = MagicMock()
        with patch.object(app.view, "show_toast", toast_mock):
            app.handle_delete_series(series[0].id)

        self.assertEqual({m.id for m in app.meetings}, {"standalone"})
        # And actually persisted, not just mutated in memory.
        on_disk = storage.load_meetings()
        self.assertEqual({m.id for m in on_disk}, {"standalone"})
        toast_mock.assert_called_once()
        self.assertIn("3", toast_mock.call_args[0][0])  # deletedSeriesToast formatted with count=3

    def test_target_with_empty_series_id_is_a_no_op_and_never_touches_standalone_meetings(self):
        """The exact worst-case bug SDD.md documents by name: filtering by
        `m.seriesId != target.seriesId` with an empty `target.seriesId`
        would keep only NON-empty-`seriesId` meetings -- i.e. delete every
        standalone meeting in the app in one call. The guard
        (`not target.seriesId: return`) must run BEFORE that filter.

        Strengthened to a realistic volume (18 standalone meetings, an
        adversarial-review follow-up) rather than just 2 -- a slice/off-by-one
        regression in the filter (e.g. an accidental `[1:]`) could easily
        leave 16-17 of 18 survivors looking "close enough" to pass a 2-item
        test by coincidence while still being wrong."""
        app = self._build_app()
        series, _unused_single_standalone = self._four_meetings()
        base_date = date(2026, 8, 21)
        standalones = [
            _meeting(
                f"standalone-{i}", seriesId="", recurrenceType="none",
                datetime=(base_date + timedelta(days=i)).isoformat() + "T10:00",
            )
            for i in range(18)
        ]
        app.meetings = series + standalones
        before_ids = {m.id for m in app.meetings}
        self.assertEqual(len(before_ids), 21, "sanity check: 3 series occurrences + 18 standalones, no id collision")

        app.handle_delete_series(standalones[0].id)  # seriesId == ""

        self.assertEqual({m.id for m in app.meetings}, before_ids, "an empty seriesId target must delete nothing")

    def test_nonexistent_meeting_id_is_a_no_op(self):
        app = self._build_app()
        series, standalone = self._four_meetings()
        app.meetings = series + [standalone]
        before_ids = {m.id for m in app.meetings}

        app.handle_delete_series("does-not-exist")

        self.assertEqual({m.id for m in app.meetings}, before_ids)

    def test_persist_is_called_with_every_removed_id_for_tombstone_safe_merge(self):
        """Direct proof of the real `_apply_meetings` -> `storage.save_meetings`
        wiring (not a hand-replicated filter, unlike the pure merge tests
        above): `handle_delete_series` must record ALL 3 series ids in
        `_pending_deleted_ids` and pass them through as `deleted_ids`,
        exactly like `handle_delete` already does for a single id."""
        app = self._build_app()
        series, standalone = self._four_meetings()
        app.meetings = series + [standalone]

        save_mock = MagicMock(return_value=[standalone])
        with patch("timermeet_app.app.storage.save_meetings", save_mock):
            app.handle_delete_series(series[1].id)

        save_mock.assert_called_once()
        _args, kwargs = save_mock.call_args
        self.assertEqual(kwargs["deleted_ids"], frozenset(m.id for m in series))

    def test_deleting_one_of_two_distinct_series_leaves_the_other_series_and_standalones_untouched(self):
        """The real `app.handle_delete_series` (not a hand-copied filter
        expression against `storage.merge_meeting_lists` directly, unlike
        `DeleteSeriesMergeTombstoneTests.test_deleted_ids_do_not_affect_an_unrelated_second_series`
        above) with TWO distinct live series plus standalones present --
        deleting one must leave the other series and every standalone
        completely untouched, both in memory and after a real disk
        round trip."""
        app = self._build_app()
        series_a = [
            _meeting(f"a{i}", seriesId="sA", recurrenceType="weekly", datetime=f"2026-08-{10 + i:02d}T09:00")
            for i in range(3)
        ]
        series_b = [
            _meeting(f"b{i}", seriesId="sB", recurrenceType="weekly", datetime=f"2026-09-{10 + i:02d}T09:00")
            for i in range(2)
        ]
        standalones = [
            _meeting(f"solo-{i}", seriesId="", recurrenceType="none", datetime=f"2026-10-{10 + i:02d}T09:00")
            for i in range(4)
        ]
        app.meetings = series_a + series_b + standalones
        app._persist(silent=True)  # establish an "already synced to disk" baseline for all 9 records
        untouched_ids = {m.id for m in series_b + standalones}

        with patch.object(app.view, "show_toast"):
            app.handle_delete_series(series_a[0].id)

        self.assertEqual({m.id for m in app.meetings}, untouched_ids)
        on_disk = storage.load_meetings()
        self.assertEqual(
            {m.id for m in on_disk}, untouched_ids,
            "series B and every standalone meeting must be completely untouched, on disk too",
        )

    def test_real_end_to_end_persist_and_merge_do_not_resurrect_a_deleted_series_from_a_stale_disk_snapshot(self):
        """Unlike `test_persist_is_called_with_every_removed_id_for_tombstone_safe_merge`
        just above (which mocks `storage.save_meetings` to inspect its call
        arguments) and `DeleteSeriesMergeTombstoneTests` at the top of this
        file (which calls `storage.merge_meeting_lists` directly, no app
        involved), this test mocks nothing storage-related: it seeds a real
        on-disk snapshot via a real `storage.save_meetings` call -- standing
        in for "whatever this machine last synced to OneDrive" -- BEFORE
        `TimerMeetApp()` is even constructed, so the app's own real startup
        load (`storage.load_meetings_report()` in `__init__`) is what
        populates `app.meetings`, not a test shortcut. It then runs the real
        `handle_delete_series` -> real `_persist` -> real
        `storage.save_meetings` -> real `storage.merge_meeting_lists` chain
        end to end for a 3-record series delete, and re-reads the same real
        file afterwards -- proving none of the 3 deleted records survive the
        merge against that seeded stale snapshot."""
        series, standalone = self._four_meetings()
        storage.save_meetings(series + [standalone])  # the seeded "stale" snapshot, written before the app exists

        app = self._build_app()
        self.assertEqual(
            {m.id for m in app.meetings}, {m.id for m in series} | {standalone.id},
            "sanity check: the app's real startup load must have picked up the seeded snapshot",
        )

        with patch.object(app.view, "show_toast"):
            app.handle_delete_series(series[2].id)

        self.assertEqual({m.id for m in app.meetings}, {"standalone"})
        on_disk = storage.load_meetings()
        self.assertEqual(
            {m.id for m in on_disk}, {"standalone"},
            "none of the 3 deleted series records may be resurrected by the real merge",
        )


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class SeriesOccurrenceCountRefreshTests(unittest.TestCase):
    """Proves `_refresh_calendar`/`_refresh_week` derive
    `CalendarEntry.series_occurrence_count` from a live recount
    (`recurrence.group_meetings_by_series`), never from `meeting.seriesSize`
    -- built with a deliberately WRONG `seriesSize` on every meeting so a
    bug that read that field instead would fail loudly."""

    @classmethod
    def setUpClass(cls):
        cls._scratch_dir = tempfile.mkdtemp(prefix="timermeet_series_count_test_")
        cls._base_dir_patcher = patch(
            "timermeet_app.storage.base_dir", return_value=Path(cls._scratch_dir)
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

    def _all_entries(self, cells):
        return [entry for cell in cells for entry in cell.entries]

    def test_refresh_calendar_counts_live_siblings_ignoring_misleading_series_size(self):
        self.app.meetings = [
            _meeting(
                "cal-a", seriesId="s1", recurrenceType="weekly", seriesSize=1,  # misleadingly says "1"
                datetime="2026-08-10T09:00",
            ),
            _meeting(
                "cal-b", seriesId="s1", recurrenceType="weekly", seriesSize=99,  # misleadingly says "99"
                datetime="2026-08-17T09:00",
            ),
        ]
        self.app.active_view = "calendar"
        self.app._calendar_year, self.app._calendar_month = 2026, 8
        self.app._last_rendered_calendar_signature = None
        render_mock = MagicMock()
        with patch.object(self.app.view, "render_calendar", render_mock):
            self.app._refresh_calendar(datetime(2026, 8, 10, 8, 0))

        cells = render_mock.call_args[0][2]
        counts = {entry.meeting_id: entry.series_occurrence_count for entry in self._all_entries(cells)}
        self.assertEqual(counts, {"cal-a": 2, "cal-b": 2})

    def test_refresh_calendar_is_zero_for_standalone_and_for_recurrence_type_none_despite_nonempty_series_id(self):
        self.app.meetings = [
            _meeting("standalone", seriesId="", recurrenceType="none", datetime="2026-08-11T09:00"),
            # The documented `_save_edit` edge case: seriesId survives an
            # edit that reset recurrenceType to "none" -- must read as "not
            # part of an active series" here too, matching
            # `recurrence.group_meetings_by_series`'s own definition.
            _meeting("lagging", seriesId="s2", recurrenceType="none", seriesSize=5, datetime="2026-08-12T09:00"),
        ]
        self.app.active_view = "calendar"
        self.app._calendar_year, self.app._calendar_month = 2026, 8
        self.app._last_rendered_calendar_signature = None
        render_mock = MagicMock()
        with patch.object(self.app.view, "render_calendar", render_mock):
            self.app._refresh_calendar(datetime(2026, 8, 11, 8, 0))

        cells = render_mock.call_args[0][2]
        counts = {entry.meeting_id: entry.series_occurrence_count for entry in self._all_entries(cells)}
        self.assertEqual(counts, {"standalone": 0, "lagging": 0})

    def test_refresh_week_counts_live_siblings_ignoring_misleading_series_size(self):
        self.app.meetings = [
            _meeting(
                "week-a", seriesId="s3", recurrenceType="weekly", seriesSize=1,
                datetime="2026-08-10T09:00",
            ),
            _meeting(
                "week-b", seriesId="s3", recurrenceType="weekly", seriesSize=1,
                datetime="2026-08-11T09:00",
            ),
            _meeting(
                "week-c", seriesId="s3", recurrenceType="weekly", seriesSize=1,
                datetime="2026-08-12T09:00",
            ),
        ]
        self.app.active_view = "week"
        self.app._week_anchor = datetime(2026, 8, 12).date()
        self.app._last_rendered_week_signature = None
        render_mock = MagicMock()
        live_mock = MagicMock()
        with patch.object(self.app.view, "render_week_grid", render_mock), patch.object(
            self.app.view, "update_week_live_indicators", live_mock
        ):
            self.app._refresh_week(datetime(2026, 8, 12, 8, 0))

        cells = render_mock.call_args[0][2]
        counts = {entry.meeting_id: entry.series_occurrence_count for entry in self._all_entries(cells)}
        self.assertEqual(counts, {"week-a": 3, "week-b": 3, "week-c": 3})


if __name__ == "__main__":
    unittest.main()
