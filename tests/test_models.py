"""Tests for Meeting normalization and validation -- in particular the Teams
URL scheme allow-list, since that's also the app's main security boundary
(see timermeet_app/security.py::is_http_url)."""

import unittest

from timermeet_app import models, security


class NormalizeMeetingTests(unittest.TestCase):
    def test_defaults_are_applied_to_a_missing_field(self):
        meeting = models.normalize_meeting({})
        self.assertEqual(meeting.reminderMinutes, 15)
        self.assertEqual(meeting.soundProfile, "soft")
        self.assertEqual(meeting.recurrenceType, "none")
        self.assertTrue(meeting.id)

    def test_unknown_sound_profile_falls_back_to_soft(self):
        meeting = models.normalize_meeting({"soundProfile": "not-a-real-profile"})
        self.assertEqual(meeting.soundProfile, "soft")

    def test_unknown_recurrence_type_falls_back_to_none(self):
        meeting = models.normalize_meeting({"recurrenceType": "yearly"})
        self.assertEqual(meeting.recurrenceType, "none")

    def test_oversized_fields_are_clamped(self):
        meeting = models.normalize_meeting({"workName": "x" * 500, "notes": "y" * 500})
        self.assertEqual(len(meeting.workName), security.MAX_WORK_NAME_LENGTH)
        self.assertEqual(len(meeting.notes), security.MAX_NOTES_LENGTH)


class ValidateMeetingTests(unittest.TestCase):
    def _valid_payload(self, **overrides):
        payload = {
            "workName": "Acme",
            "title": "Daily",
            "date": "2026-08-10",  # a Monday
            "time": "09:00",
            "reminderMinutes": "15",
            "recurrenceType": "none",
            "occurrenceCount": "1",
            "teamsUrl": "",
        }
        payload.update(overrides)
        return payload

    def test_valid_payload_passes(self):
        self.assertIsNone(models.validate_meeting(self._valid_payload()))

    def test_missing_work_name_fails_first(self):
        self.assertEqual(models.validate_meeting(self._valid_payload(workName="")), "validationWork")

    def test_weekday_recurrence_rejects_a_saturday_start(self):
        payload = self._valid_payload(date="2026-08-08", recurrenceType="weekdays")  # a Saturday
        self.assertEqual(models.validate_meeting(payload), "validationWeekdayStart")

    def test_weekday_recurrence_accepts_a_monday_start(self):
        payload = self._valid_payload(date="2026-08-10", recurrenceType="weekdays")  # a Monday
        self.assertIsNone(models.validate_meeting(payload))

    def test_occurrence_count_out_of_range_fails(self):
        payload = self._valid_payload(recurrenceType="weekly", occurrenceCount="53")
        self.assertEqual(models.validate_meeting(payload), "validationOccurrences")

    def test_non_http_teams_url_is_rejected(self):
        payload = self._valid_payload(teamsUrl="msteams://meeting/123")
        self.assertEqual(models.validate_meeting(payload), "validationTeamsUrl")

    def test_http_and_https_teams_urls_are_accepted(self):
        for scheme in ("http://", "https://"):
            payload = self._valid_payload(teamsUrl=f"{scheme}teams.microsoft.com/meeting")
            self.assertIsNone(models.validate_meeting(payload))


class IsHttpUrlTests(unittest.TestCase):
    def test_rejects_non_http_schemes(self):
        for url in ("javascript:alert(1)", "file:///etc/passwd", "ftp://example.com", ""):
            self.assertFalse(security.is_http_url(url))

    def test_accepts_http_and_https(self):
        self.assertTrue(security.is_http_url("http://example.com"))
        self.assertTrue(security.is_http_url("https://example.com"))

    def test_accepts_ordinary_leading_and_trailing_whitespace(self):
        self.assertTrue(security.is_http_url(" https://example.com "))

    def test_rejects_control_character_that_strip_would_otherwise_remove(self):
        # \x1f is treated as whitespace by str.strip() (a CPython/Unicode
        # quirk covering the ASCII "information separator" range
        # \x1c-\x1f), so it used to vanish before the unsafe-character check
        # ever saw it -- confirming the check now runs on the raw value.
        self.assertFalse(security.is_http_url("https://example.com/path\x1f"))
        self.assertFalse(security.is_http_url("\x1fhttps://example.com/path"))


if __name__ == "__main__":
    unittest.main()
