"""Tests for storage.py's load-time crash safety and the same-machine
advisory lock's self-healing.

``load_meetings()``'s own docstring promises it never raises -- an
unreadable/corrupt file is quarantined (renamed aside, never deleted) and
the app starts with an empty list instead of crashing. This suite
reproduces the three concrete ways a syntactically-valid-but-extreme file
used to defeat that promise (see the security audit that prompted this
file), plus the same-class problem one step later, inside the per-record
``models.normalize_meeting()`` call. Every test below points
``storage.base_dir()`` at an isolated scratch directory -- never the real
``data/meetings.json`` (see feedback_never_test_against_live_data)."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from timermeet_app import models, storage


class _IsolatedDataDirTestCase(unittest.TestCase):
    def setUp(self):
        self._scratch_dir = tempfile.mkdtemp(prefix="timermeet_storage_test_")
        self._base_dir_patcher = patch(
            "timermeet_app.storage.base_dir", return_value=Path(self._scratch_dir)
        )
        self._base_dir_patcher.start()

    def tearDown(self):
        self._base_dir_patcher.stop()
        shutil.rmtree(self._scratch_dir, ignore_errors=True)

    def _write_raw(self, content: bytes) -> Path:
        path = storage.meetings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def _quarantined_siblings(self, path: Path):
        return list(path.parent.glob(f"{path.name}.corrupt-*"))


class LoadMeetingsCrashSafetyTests(_IsolatedDataDirTestCase):
    def test_extreme_numeric_field_does_not_crash_and_drops_only_that_record(self):
        # {"reminderMinutes": 1e400} decodes cleanly to float("inf")
        # (json.loads never raises for this) -- the crash used to happen
        # one step later, inside models._as_int()'s int(float(value)),
        # which raises OverflowError, a type _as_int's own except clause
        # doesn't catch. One bad record must not sink the whole file.
        payload = json.dumps(
            [
                {
                    "id": "bad",
                    "workName": "A",
                    "title": "T",
                    "datetime": "2026-08-10T09:00",
                    "reminderMinutes": 1e400,
                },
                {
                    "id": "good",
                    "workName": "B",
                    "title": "T2",
                    "datetime": "2026-08-11T09:00",
                },
            ]
        ).encode("utf-8")
        path = self._write_raw(payload)

        meetings = storage.load_meetings()

        self.assertEqual({m.id for m in meetings}, {"good"})
        # This is a per-record failure, not a whole-file parse failure --
        # the file itself is left alone, not quarantined.
        self.assertTrue(path.exists())

    def test_deeply_nested_json_does_not_crash_and_is_quarantined(self):
        # json.loads() itself raises RecursionError for this, which is not
        # a json.JSONDecodeError subclass -- the original except clause
        # missed it entirely.
        nested = ("[" * 100_000) + ("]" * 100_000)
        path = self._write_raw(nested.encode("utf-8"))

        meetings = storage.load_meetings()

        self.assertEqual(meetings, [])
        self.assertFalse(path.exists())
        self.assertEqual(len(self._quarantined_siblings(path)), 1)

    def test_invalid_utf8_byte_does_not_crash_and_is_quarantined(self):
        # path.read_text(encoding="utf-8") raises UnicodeDecodeError for
        # this, which is NOT an OSError subclass -- the original except
        # clause missed it entirely.
        path = self._write_raw(b'[{"id": "x", "workName": "A"}]\xff')

        meetings = storage.load_meetings()

        self.assertEqual(meetings, [])
        self.assertFalse(path.exists())
        self.assertEqual(len(self._quarantined_siblings(path)), 1)

    def test_second_launch_after_quarantine_starts_clean_instead_of_recrashing(self):
        # Regression: before this fix, quarantine was only wired to the
        # json.JSONDecodeError branch, so the identical crash reproduced on
        # every subsequent launch until a human manually removed the file.
        path = self._write_raw(b"\xff\xfe not valid utf-8 at all")

        first = storage.load_meetings()
        second = storage.load_meetings()

        self.assertEqual(first, [])
        self.assertEqual(second, [])
        self.assertFalse(path.exists())
        self.assertEqual(len(self._quarantined_siblings(path)), 1)


class LoadMeetingsReportTests(_IsolatedDataDirTestCase):
    """``load_meetings_report()`` is the signal ``TimerMeetApp``'s startup
    path uses to decide whether to surface a toast (see app.py's
    ``_maybe_show_startup_load_toast``) -- these tests cover the report
    itself in isolation from any Tk/toast plumbing; see
    ``tests/test_startup_load_toast.py`` for the end-to-end toast behavior."""

    def test_clean_load_reports_nothing_dropped(self):
        payload = json.dumps(
            [{"id": "good", "workName": "A", "title": "T", "datetime": "2026-08-10T09:00"}]
        ).encode("utf-8")
        self._write_raw(payload)

        report = storage.load_meetings_report()

        self.assertEqual({m.id for m in report.meetings}, {"good"})
        self.assertFalse(report.quarantined)
        self.assertEqual(report.skipped_records, 0)

    def test_missing_file_reports_nothing_dropped(self):
        report = storage.load_meetings_report()

        self.assertEqual(report.meetings, [])
        self.assertFalse(report.quarantined)
        self.assertEqual(report.skipped_records, 0)

    def test_per_record_skip_is_counted_and_not_reported_as_quarantine(self):
        payload = json.dumps(
            [
                {
                    "id": "bad",
                    "workName": "A",
                    "title": "T",
                    "datetime": "2026-08-10T09:00",
                    "reminderMinutes": 1e400,
                },
                {"id": "good", "workName": "B", "title": "T2", "datetime": "2026-08-11T09:00"},
            ]
        ).encode("utf-8")
        self._write_raw(payload)

        report = storage.load_meetings_report()

        self.assertEqual({m.id for m in report.meetings}, {"good"})
        self.assertFalse(report.quarantined)
        self.assertEqual(report.skipped_records, 1)

    def test_whole_file_quarantine_is_reported_distinctly_from_a_per_record_skip(self):
        nested = ("[" * 100_000) + ("]" * 100_000)
        self._write_raw(nested.encode("utf-8"))

        report = storage.load_meetings_report()

        self.assertEqual(report.meetings, [])
        self.assertTrue(report.quarantined)
        self.assertEqual(report.skipped_records, 0)

    def test_load_meetings_still_returns_a_bare_list(self):
        # The common-case wrapper must keep its existing return type for
        # every caller/test that doesn't care about the drop signal.
        payload = json.dumps(
            [{"id": "good", "workName": "A", "title": "T", "datetime": "2026-08-10T09:00"}]
        ).encode("utf-8")
        self._write_raw(payload)

        meetings = storage.load_meetings()

        self.assertIsInstance(meetings, list)
        self.assertEqual({m.id for m in meetings}, {"good"})


class SameMachineLockSelfHealingTests(_IsolatedDataDirTestCase):
    def test_save_succeeds_even_if_lock_path_is_pre_created_as_a_directory(self):
        # A pre-existing directory at meetings.lock makes open(lock_path,
        # "a+b") raise PermissionError, which used to be uncaught (only the
        # later msvcrt.locking() call was wrapped), permanently blocking
        # every future save. This lock is documented best-effort/advisory --
        # a failure to even open it must behave like a failure to acquire
        # it (proceed without the lock), not abort the save forever.
        lock_path = storage.data_dir() / storage.LOCK_FILENAME
        lock_path.mkdir(parents=True, exist_ok=True)

        meeting = models.normalize_meeting(
            {"workName": "Acme", "title": "Daily", "datetime": "2026-08-10T09:00"}
        )

        saved = storage.save_meetings([meeting])

        self.assertEqual({m.id for m in saved}, {meeting.id})
        self.assertTrue(storage.meetings_path().exists())
        # The pre-created directory itself is left alone -- no attempt to
        # delete/replace it, just don't let it block the save.
        self.assertTrue(lock_path.is_dir())


if __name__ == "__main__":
    unittest.main()
