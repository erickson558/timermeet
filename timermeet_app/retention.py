"""Retention: drop meetings that are no longer actionable so the saved list
(and therefore every render/scan of it) doesn't grow forever.

A meeting is purge-eligible once it's in the past *and* both its alerts have
already fired (``reminderSent`` and ``startSent``) *and* it has sat that way
for at least ``RETENTION`` -- the short grace window means a meeting that
just ended this morning is still visible for a few days, not erased the
instant its second alert fires.

The one exception: the chronologically latest occurrence of each recurring
series is always kept, even if it's past and done, because
``recurrence.run_weekly_series_renewal`` needs at least one occurrence per
series to know where to extend from next.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple

from . import models

RETENTION = timedelta(days=7)


def _meeting_time(meeting: models.Meeting) -> datetime:
    parsed = meeting.local_datetime()
    return parsed if parsed is not None else datetime.max


def _latest_occurrence_ids(meetings: List[models.Meeting]) -> set:
    latest_by_series = {}
    for meeting in meetings:
        if not meeting.seriesId:
            continue
        current = latest_by_series.get(meeting.seriesId)
        if current is None or _meeting_time(meeting) > _meeting_time(current):
            latest_by_series[meeting.seriesId] = meeting
    return {meeting.id for meeting in latest_by_series.values()}


def purge_stale_meetings(
    meetings: List[models.Meeting], now: datetime = None
) -> Tuple[List[models.Meeting], int]:
    """Return ``(kept, purged_count)``. Never mutates the input list."""
    now = now or datetime.now()
    cutoff = now - RETENTION
    keep_ids = _latest_occurrence_ids(meetings)

    kept: List[models.Meeting] = []
    purged = 0
    for meeting in meetings:
        when = meeting.local_datetime()
        is_stale = (
            when is not None
            and when < cutoff
            and meeting.reminderSent
            and meeting.startSent
            and meeting.id not in keep_ids
        )
        if is_stale:
            purged += 1
        else:
            kept.append(meeting)

    return kept, purged


def clear_past_meetings(
    meetings: List[models.Meeting], now: datetime = None
) -> Tuple[List[models.Meeting], int]:
    """Explicit, immediate "delete all past events" for the manual button --
    unlike ``purge_stale_meetings`` this has no grace period and doesn't
    require both alerts to have fired (a past meeting's alerts are moot
    either way; the user asked for this one, on purpose, right now). Still
    keeps each recurring series' latest occurrence so an existing series
    doesn't lose its renewal anchor and quietly stop reminding the user.
    Return ``(kept, removed_count)``. Never mutates the input list."""
    now = now or datetime.now()
    keep_ids = _latest_occurrence_ids(meetings)

    kept: List[models.Meeting] = []
    removed = 0
    for meeting in meetings:
        when = meeting.local_datetime()
        is_past = when is not None and when < now and meeting.id not in keep_ids
        if is_past:
            removed += 1
        else:
            kept.append(meeting)

    return kept, removed
