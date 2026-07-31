"""Recurrence generation and the weekly series auto-renewal engine.

Ported from ``legacy-php/assets/app.js`` (`addRecurrenceToDate`,
`addWeekdayRecurrenceToDate`, `runWeeklySeriesRenewal`, `extendSeriesIfNeeded`).
This is the mechanism that used to silently stop reminding the user once a
recurring series ran out of pre-generated occurrences (fixed in the web app's
v1.3.0, see the root README's "Por qué antes fallaban algunos recordatorios"
section) — it must behave identically here.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from . import models

RENEWAL_TRIGGER_HOUR = 18  # Friday, local time
RENEWAL_LOOKAHEAD = timedelta(days=9)
RENEWAL_MAX_STEPS_PER_SERIES = 60  # safety cap so a bad record can't loop forever


def _is_weekend(value: datetime) -> bool:
    return value.weekday() >= 5  # Python: Mon=0 ... Sat=5, Sun=6


def _add_months(value: datetime, months: int) -> datetime:
    """Mimic JS ``date.setMonth(date.getMonth() + months)``.

    JS lets the day-of-month overflow into the following month(s) instead of
    clamping it (e.g. Jan 31 + 1 month -> Mar 3 in a non-leap year, not Feb
    28), so a "cada mes" series anchored on the 31st keeps landing on
    believable, monotonically-increasing dates instead of silently sliding
    backwards every time a short month is involved.
    """
    total_month_index = value.month - 1 + months
    year = value.year + total_month_index // 12
    month = total_month_index % 12 + 1
    days_in_target_month = calendar.monthrange(year, month)[1]
    if value.day <= days_in_target_month:
        return value.replace(year=year, month=month)
    overflow_days = value.day - days_in_target_month
    base = value.replace(year=year, month=month, day=days_in_target_month)
    return base + timedelta(days=overflow_days)


def add_weekday_recurrence_to_date(base: datetime, step_index: int) -> datetime:
    """Step forward one calendar day at a time, only counting weekdays,
    until ``step_index`` weekday-steps have been consumed. Used exclusively
    for ``recurrenceType == "weekdays"``."""
    current = base
    remaining = step_index
    while remaining > 0:
        current = current + timedelta(days=1)
        if not _is_weekend(current):
            remaining -= 1
    return current


def add_recurrence_to_date(base: datetime, recurrence_type: str, step_index: int) -> datetime:
    """Port of ``addRecurrenceToDate()`` — advance ``base`` by ``step_index``
    units of ``recurrence_type``."""
    if recurrence_type == "weekdays":
        return add_weekday_recurrence_to_date(base, step_index)
    if step_index == 0 or recurrence_type == "none":
        return base
    if recurrence_type == "daily":
        return base + timedelta(days=step_index)
    if recurrence_type == "weekly":
        return base + timedelta(days=step_index * 7)
    if recurrence_type == "biweekly":
        return base + timedelta(days=step_index * 14)
    if recurrence_type == "monthly":
        return _add_months(base, step_index)
    return base


def _meeting_time(meeting: models.Meeting) -> datetime:
    parsed = meeting.local_datetime()
    return parsed if parsed is not None else datetime.min


def most_recent_friday_eod(now: datetime) -> datetime:
    """Return the most recent Friday-18:00-local instant that has already
    happened relative to ``now`` (never in the future).

    This is the sole "clock" the renewal engine reads: it is what makes a
    second run in the same week a no-op (see ``extend_series_if_needed``)
    without needing any separate "last run at" bookkeeping on disk.
    """
    days_since_monday = now.weekday()  # Mon=0 ... Sun=6
    monday = (now - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    friday = (monday + timedelta(days=4)).replace(
        hour=RENEWAL_TRIGGER_HOUR, minute=0, second=0, microsecond=0
    )
    if friday > now:
        friday -= timedelta(days=7)
    return friday


def group_meetings_by_series(meetings: List[models.Meeting]) -> Dict[str, List[models.Meeting]]:
    """A series is "active" simply by having >=1 occurrence on record with a
    non-"none" recurrenceType and a seriesId — there's no separate "still
    wanted" flag. Deleting *every* occurrence of a series is the only way to
    stop its renewal."""
    groups: Dict[str, List[models.Meeting]] = {}
    for meeting in meetings:
        if meeting.recurrenceType == "none" or not meeting.seriesId:
            continue
        groups.setdefault(meeting.seriesId, []).append(meeting)
    return groups


def extend_series_if_needed(
    series_meetings: List[models.Meeting], now: datetime, lookahead_target: datetime
) -> int:
    """Top up one recurring series so its latest occurrence reaches at least
    ``lookahead_target``. Mutates ``series_meetings`` in place (appends any
    newly created occurrences) and returns how many were created.

    Idempotency: the loop starts from whatever is *currently* the latest
    occurrence and stops as soon as that is already >= ``lookahead_target``.
    Since ``lookahead_target`` itself only advances once a week (see
    ``most_recent_friday_eod``), calling this again before the next Friday
    18:00 immediately returns 0 — no duplicate occurrences are ever created.
    """
    if not series_meetings:
        return 0

    latest = max(series_meetings, key=_meeting_time)
    cursor_time = _meeting_time(latest)
    if cursor_time >= lookahead_target:
        return 0

    created_total = 0
    last_created = latest
    safety = 0
    while cursor_time < lookahead_target and safety < RENEWAL_MAX_STEPS_PER_SERIES:
        safety += 1
        cursor_time = add_recurrence_to_date(cursor_time, latest.recurrenceType, 1)

        # Only materialize occurrences that land today or later — the cursor
        # still advances through any already-past steps so weekday/monthly
        # alignment stays correct, it just doesn't backfill dead reminders.
        if cursor_time >= now:
            new_meeting = models.normalize_meeting(
                {
                    "workName": latest.workName,
                    "title": latest.title,
                    "datetime": cursor_time.strftime("%Y-%m-%dT%H:%M"),
                    "reminderMinutes": latest.reminderMinutes,
                    "soundProfile": latest.soundProfile,
                    "teamsUrl": latest.teamsUrl,
                    "notes": latest.notes,
                    "recurrenceType": latest.recurrenceType,
                    "seriesId": latest.seriesId,
                    "occurrenceIndex": last_created.occurrenceIndex + 1,
                    "seriesSize": last_created.seriesSize + 1,
                    "reminderSent": False,
                    "startSent": False,
                }
            )
            series_meetings.append(new_meeting)
            last_created = new_meeting
            created_total += 1

    if created_total:
        final_size = last_created.seriesSize
        for meeting in series_meetings:
            meeting.seriesSize = final_size

    return created_total


def run_weekly_series_renewal(meetings: List[models.Meeting], now: Optional[datetime] = None) -> int:
    """Extend every active recurring series so it stays populated roughly a
    week into the future, refreshed starting each Friday 18:00 local time (or
    immediately on the next run after that point if the app was closed).
    Appends any newly created occurrences directly into ``meetings`` and
    returns the total number created (0 most of the time)."""
    now = now or datetime.now()
    lookahead_target = most_recent_friday_eod(now) + RENEWAL_LOOKAHEAD

    created_total = 0
    for series_meetings in group_meetings_by_series(meetings).values():
        existing_ids = {meeting.id for meeting in series_meetings}
        created = extend_series_if_needed(series_meetings, now, lookahead_target)
        if created:
            for meeting in series_meetings:
                if meeting.id not in existing_ids:
                    meetings.append(meeting)
            created_total += created

    return created_total
