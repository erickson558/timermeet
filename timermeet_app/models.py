"""Meeting data model.

Mirrors the JSON schema from the original PHP/JS app (see
``legacy-php/api/meetings.php::normalizeMeeting`` and
``legacy-php/assets/app.js``) field-for-field, so any existing
``data/meetings.json`` written by the web version keeps working unchanged.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from . import security

RECURRENCE_TYPES = ("none", "daily", "weekdays", "weekly", "biweekly", "monthly")
SOUND_PROFILES = ("soft", "urgent", "alarm", "siren", "fire")

DEFAULT_REMINDER_MINUTES = 15
DEFAULT_SOUND_PROFILE = "soft"
DEFAULT_RECURRENCE_TYPE = "none"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


def new_id() -> str:
    return uuid.uuid4().hex


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Meeting:
    id: str = field(default_factory=new_id)
    workName: str = ""
    title: str = ""
    datetime: str = ""  # naive local "YYYY-MM-DDTHH:MM", no seconds/timezone
    reminderMinutes: int = DEFAULT_REMINDER_MINUTES
    soundProfile: str = DEFAULT_SOUND_PROFILE
    teamsUrl: str = ""
    notes: str = ""
    recurrenceType: str = DEFAULT_RECURRENCE_TYPE
    seriesId: str = ""
    occurrenceIndex: int = 1
    seriesSize: int = 1
    reminderSent: bool = False
    startSent: bool = False
    createdAt: str = field(default_factory=now_iso)
    updatedAt: str = field(default_factory=now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    def local_datetime(self) -> Optional[datetime]:
        """Parse ``datetime`` as a naive local datetime, or None if empty/invalid."""
        if not self.datetime:
            return None
        try:
            return datetime.strptime(self.datetime, "%Y-%m-%dT%H:%M")
        except ValueError:
            return None


def normalize_sound_profile(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in SOUND_PROFILES else DEFAULT_SOUND_PROFILE


def normalize_recurrence_type(value) -> str:
    text = str(value or "").strip().lower()
    return text if text in RECURRENCE_TYPES else DEFAULT_RECURRENCE_TYPE


def _as_int(value, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return number if number else default


def normalize_meeting(data: dict) -> Meeting:
    """Port of ``normalizeMeeting()``: every field gets a safe default and
    passes through the same allow-lists, so a malformed or partial record on
    disk never crashes the app — it just gets coerced into something valid."""
    data = data or {}
    meeting_id = str(data.get("id") or "").strip() or new_id()
    created_at = str(data.get("createdAt") or "").strip() or now_iso()
    updated_at = str(data.get("updatedAt") or "").strip() or created_at
    return Meeting(
        id=meeting_id,
        workName=security.clamp_text(data.get("workName"), security.MAX_WORK_NAME_LENGTH),
        title=security.clamp_text(data.get("title"), security.MAX_TITLE_LENGTH),
        datetime=str(data.get("datetime") or "").strip(),
        reminderMinutes=max(1, _as_int(data.get("reminderMinutes"), DEFAULT_REMINDER_MINUTES)),
        soundProfile=normalize_sound_profile(data.get("soundProfile")),
        teamsUrl=security.clamp_text(data.get("teamsUrl"), security.MAX_TEAMS_URL_LENGTH),
        notes=security.clamp_text(data.get("notes"), security.MAX_NOTES_LENGTH),
        recurrenceType=normalize_recurrence_type(data.get("recurrenceType")),
        seriesId=str(data.get("seriesId") or "").strip(),
        occurrenceIndex=max(1, _as_int(data.get("occurrenceIndex"), 1)),
        seriesSize=max(1, _as_int(data.get("seriesSize"), 1)),
        reminderSent=bool(data.get("reminderSent")),
        startSent=bool(data.get("startSent")),
        createdAt=created_at,
        updatedAt=updated_at,
    )


def _normalize_time_value(value) -> str:
    """Accept "HH:MM" or "HH:MM:SS" (drop seconds), like a browser time input."""
    text = str(value or "").strip()
    return text[:5] if len(text) >= 5 else text


def validate_meeting(payload: dict) -> Optional[str]:
    """Port of ``validateMeeting()``. Returns an i18n key naming the first
    failing rule, or ``None`` if the payload is valid. Order matters — it
    mirrors the original check sequence exactly so error precedence matches."""
    work_name = str(payload.get("workName") or "").strip()
    if not work_name:
        return "validationWork"

    title = str(payload.get("title") or "").strip()
    if not title:
        return "validationTitle"

    date_value = str(payload.get("date") or "").strip()
    if not _DATE_RE.match(date_value):
        return "validationDate"

    time_value = _normalize_time_value(payload.get("time"))
    if not _TIME_RE.match(time_value):
        return "validationTime"

    try:
        parsed = datetime.strptime(f"{date_value}T{time_value}", "%Y-%m-%dT%H:%M")
    except ValueError:
        return "validationDate"

    recurrence_type = normalize_recurrence_type(payload.get("recurrenceType"))
    if recurrence_type == "weekdays" and parsed.weekday() >= 5:  # Mon=0 ... Sat=5, Sun=6
        return "validationWeekdayStart"

    try:
        reminder_minutes = float(payload.get("reminderMinutes"))
    except (TypeError, ValueError):
        return "validationReminder"
    if not reminder_minutes >= 1:
        return "validationReminder"

    try:
        occurrence_count = float(payload.get("occurrenceCount"))
    except (TypeError, ValueError):
        return "validationOccurrences"
    if not (1 <= occurrence_count <= 52):
        return "validationOccurrences"

    teams_url = str(payload.get("teamsUrl") or "").strip()
    if teams_url and not security.is_http_url(teams_url):
        return "validationTeamsUrl"

    return None
