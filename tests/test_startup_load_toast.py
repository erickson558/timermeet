"""Tests for the startup "N meetings could not be loaded" toast.

Security-hardening follow-up: ``storage.load_meetings_report()`` reports
whether the whole ``meetings.json`` was quarantined (unreadable/corrupt) or
individual records were skipped (bad field data) on the way in, and
``TimerMeetApp``'s startup path (``_maybe_show_startup_load_toast``) must
turn that into a visible toast -- before this fix, both cases only ever
reached ``logger.warning(...)``, durably written to ``data/timermeet.log``
but invisible to a user who will likely never open it. For an app whose
whole purpose is "never let the user miss a meeting", losing meetings
without telling the user is a trust problem, whether the cause is bad data
or a future code bug in ``normalize_meeting()``.

Each test builds a full, real ``TimerMeetApp()`` against an isolated
scratch data directory (never ``data/meetings.json`` -- see MEMORY's "never
test against live data" note), with the ``meetings.json`` content pre-seeded
before construction so the exact startup path under test runs for real,
same setup style as ``tests/test_week_view.py``'s ``WeekViewGatingTests``.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from timermeet_app import i18n

try:
    import tkinter as tk

    from timermeet_app.app import TimerMeetApp
except ImportError:  # pragma: no cover - non-Windows/no-Tk dev environments
    tk = None
    TimerMeetApp = None


@unittest.skipUnless(tk is not None, "Tkinter is not importable in this environment")
class StartupLoadToastTests(unittest.TestCase):
    def _build_app(self, meetings_json_bytes: bytes = None) -> "TimerMeetApp":
        scratch_dir = tempfile.mkdtemp(prefix="timermeet_startup_toast_test_")
        base_dir_patcher = patch("timermeet_app.storage.base_dir", return_value=Path(scratch_dir))
        base_dir_patcher.start()
        if meetings_json_bytes is not None:
            data_dir = Path(scratch_dir) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / "meetings.json").write_bytes(meetings_json_bytes)
        try:
            app = TimerMeetApp()
        except tk.TclError as exc:  # e.g. a headless CI runner with no display
            base_dir_patcher.stop()
            shutil.rmtree(scratch_dir, ignore_errors=True)
            raise unittest.SkipTest(f"No display available for Tk: {exc}")
        self.addCleanup(base_dir_patcher.stop)
        self.addCleanup(shutil.rmtree, scratch_dir, ignore_errors=True)
        self.addCleanup(self._destroy_root, app)
        return app

    @staticmethod
    def _destroy_root(app: "TimerMeetApp") -> None:
        try:
            app.root.destroy()
        except tk.TclError:  # nosec B110 - already gone, nothing to clean up
            pass

    @staticmethod
    def _toast_text(app: "TimerMeetApp"):
        toast = app.view._toast_window
        return toast.cget("text") if toast is not None else None

    def test_ordinary_clean_load_does_not_show_a_toast(self):
        payload = json.dumps(
            [{"id": "good", "workName": "A", "title": "T", "datetime": "2026-08-10T09:00"}]
        ).encode("utf-8")

        app = self._build_app(payload)

        self.assertIsNone(self._toast_text(app))

    def test_missing_meetings_file_does_not_show_a_toast(self):
        app = self._build_app()

        self.assertIsNone(self._toast_text(app))

    def test_per_record_skip_shows_a_toast_with_the_right_count(self):
        # {"reminderMinutes": 1e400} decodes cleanly (json.loads never
        # raises for this) but crashes int(float("inf")) one step later
        # inside models._as_int() -- a per-record drop, not a whole-file
        # quarantine (see tests/test_storage.py for the storage-level
        # coverage of this exact case).
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

        app = self._build_app(payload)

        expected = i18n.format_text("meetingsSkippedToast", app.language, count=1)
        self.assertEqual(self._toast_text(app), expected)
        # The good record must still have loaded -- one bad record must
        # never sink the whole file's data.
        self.assertEqual({m.id for m in app.meetings}, {"good"})

    def test_whole_file_quarantine_shows_the_corrupt_file_toast(self):
        # json.loads() itself raises RecursionError for this (not a
        # json.JSONDecodeError subclass), routing to the whole-file
        # quarantine path rather than the per-record one.
        nested = ("[" * 100_000) + ("]" * 100_000)

        app = self._build_app(nested.encode("utf-8"))

        expected = i18n.t("meetingsFileCorruptToast", app.language)
        self.assertEqual(self._toast_text(app), expected)
        self.assertEqual(app.meetings, [])


if __name__ == "__main__":
    unittest.main()
