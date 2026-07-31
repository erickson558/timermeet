"""Persistence layer: a single shared ``data/meetings.json`` file.

Replaces the old PHP-endpoint + localStorage + 45s-polling stack (see
``legacy-php/assets/app.js``) now that there's no browser and no server. This
project folder lives inside OneDrive and may run on more than one PC, so every
save re-reads the file, merges it with the in-memory state using the same
conflict rules the web app used for its multi-tab sync, and writes the result
back atomically. There is no distributed lock across machines (OneDrive
doesn't provide one, and syncing is not instant) — cross-machine safety comes
from the merge, not from file locking; a same-machine advisory lock only
guards against two TimerMeet processes racing on this one PC.
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from . import models, security

logger = logging.getLogger(__name__)

MEETINGS_FILENAME = "meetings.json"
SETTINGS_FILENAME = "settings.json"
LOCK_FILENAME = "meetings.lock"

SYNC_MERGE_GRACE = timedelta(seconds=15)


def base_dir() -> Path:
    """Directory the app should treat as "next to the executable" — the
    frozen .exe's own folder when packaged, or the repository root when run
    as a script (this module lives one level down, in ``timermeet_app/``)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return base_dir() / "data"


def meetings_path() -> Path:
    return data_dir() / MEETINGS_FILENAME


def settings_path() -> Path:
    return data_dir() / SETTINGS_FILENAME


@contextmanager
def _same_machine_lock(directory: Path):
    """Best-effort advisory lock so two TimerMeet processes on the *same* PC
    don't interleave a read-merge-write cycle. Never raises — if locking
    isn't available for any reason, saving still proceeds (atomic replace is
    what actually prevents on-disk corruption; this just narrows a race)."""
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / LOCK_FILENAME
    handle = None
    locked = False
    try:
        handle = open(lock_path, "a+b")
        try:
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            locked = True
        except Exception:  # noqa: BLE001 - locking is best-effort, never fatal
            locked = False
        yield
    finally:
        if handle is not None:
            if locked:
                try:
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except Exception:  # nosec B110 - this lock is advisory/best-effort (see class docstring)
                    pass
            handle.close()


def _quarantine_corrupt_file(path: Path) -> None:
    """Never delete data the user might need: rename an unreadable file
    aside instead of overwriting it, so a corrupted meetings.json can still
    be recovered by hand."""
    backup = path.with_name(f"{path.name}.corrupt-{int(datetime.now().timestamp())}")
    try:
        path.replace(backup)
        logger.warning("Quarantined corrupt data file to %s", backup)
    except OSError as exc:
        logger.warning("Could not quarantine corrupt data file %s: %s", path, exc)


def load_meetings() -> List[models.Meeting]:
    """Read and normalize every meeting on disk. Never raises: a missing
    file yields an empty list, and an unreadable/corrupt file is quarantined
    (not deleted) and also yields an empty list rather than crashing the app."""
    path = meetings_path()
    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return []

    if not raw.strip():
        return []

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Corrupt data file %s (%s)", path, exc)
        _quarantine_corrupt_file(path)
        return []

    if not isinstance(decoded, list):
        return []

    return [models.normalize_meeting(item) for item in decoded if isinstance(item, dict)]


def _parse_iso(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return datetime.min


def merge_meeting_pair(disk_meeting: models.Meeting, memory_meeting: models.Meeting) -> models.Meeting:
    """Port of ``mergeMeetingPair()``: the record with the newer
    ``updatedAt`` wins on content, but ``reminderSent``/``startSent`` are
    always OR'd across both copies regardless of which one "wins" — this is
    what stops an alarm already dismissed on one machine from replaying after
    a merge pulls in an older copy from another machine that hadn't recorded
    the flag yet."""
    disk_updated = _parse_iso(disk_meeting.updatedAt)
    memory_updated = _parse_iso(memory_meeting.updatedAt)
    base = disk_meeting if disk_updated > memory_updated else memory_meeting

    merged = models.normalize_meeting(base.to_dict())
    merged.reminderSent = bool(disk_meeting.reminderSent or memory_meeting.reminderSent)
    merged.startSent = bool(disk_meeting.startSent or memory_meeting.startSent)
    return merged


def merge_meeting_lists(
    disk_meetings: List[models.Meeting],
    memory_meetings: List[models.Meeting],
    now: Optional[datetime] = None,
) -> List[models.Meeting]:
    """Combine what's currently on disk (possibly edited on another machine
    since this process last loaded) with what's in memory. A meeting that
    exists only in memory survives the merge if it was created in the last
    ``SYNC_MERGE_GRACE`` seconds (it just hasn't reached disk yet); anything
    older that the disk no longer has is treated as a legitimate deletion
    from another session."""
    now = now or datetime.now()
    memory_by_id: Dict[str, models.Meeting] = {m.id: m for m in memory_meetings}
    seen_ids = set()
    merged: List[models.Meeting] = []

    for disk_meeting in disk_meetings:
        seen_ids.add(disk_meeting.id)
        memory_meeting = memory_by_id.get(disk_meeting.id)
        merged.append(
            merge_meeting_pair(disk_meeting, memory_meeting) if memory_meeting else disk_meeting
        )

    for memory_meeting in memory_meetings:
        if memory_meeting.id in seen_ids:
            continue
        if now - _parse_iso(memory_meeting.createdAt) < SYNC_MERGE_GRACE:
            merged.append(memory_meeting)

    return merged


def _sort_key(meeting: models.Meeting):
    parsed = meeting.local_datetime()
    return parsed if parsed is not None else datetime.min


def save_meetings(meetings: List[models.Meeting], now: Optional[datetime] = None) -> List[models.Meeting]:
    """Merge the in-memory list with whatever is currently on disk and
    atomically write the result — the merge becomes the new source of truth,
    so the caller should replace its in-memory state with the returned list.
    Raises only on a genuine disk-write failure (permissions, disk full);
    callers are expected to catch that and retry later, exactly like the
    original app's "saved locally, will retry" fallback."""
    with _same_machine_lock(data_dir()):
        disk_meetings = load_meetings()
        merged = sorted(merge_meeting_lists(disk_meetings, meetings, now), key=_sort_key)
        payload = json.dumps([m.to_dict() for m in merged], indent=2, ensure_ascii=False)
        security.atomic_write_text(meetings_path(), payload + "\n")
    return merged


def load_settings() -> dict:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def save_settings(settings: dict) -> None:
    security.atomic_write_text(settings_path(), json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
