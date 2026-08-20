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
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional

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
        try:
            handle = open(lock_path, "a+b")
        except Exception:  # noqa: BLE001 - e.g. lock_path was pre-created as a
            # directory (or is otherwise unopenable); treat exactly like a
            # failure to acquire the lock further below rather than letting
            # this propagate and permanently blocking every future save --
            # real corruption protection comes from atomic_write_text's
            # os.replace(), not from this advisory lock.
            handle = None
        if handle is not None:
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


@dataclass(frozen=True)
class MeetingLoadReport:
    """Everything a single ``load_meetings_report()`` read found, including
    whether anything was dropped getting there.

    ``load_meetings()`` (below) stays a bare ``List[models.Meeting]`` for
    every existing caller -- most of them (``save_meetings``'s
    read-before-merge, ``TimerMeetApp._resync_from_disk``) only ever want
    the meetings and would gain nothing from this signal. ``TimerMeetApp``'s
    *startup* path is the one exception: before this report existed, a
    quarantined file or a skipped record only ever reached
    ``logger.warning(...)`` -- durably written to ``data/timermeet.log``,
    but invisible to a user who will likely never open it. For an app whose
    whole purpose is "never let the user miss a meeting", losing meetings
    without telling the user is a trust problem regardless of whether the
    cause was bad data (the thing this broad exception handling is deliberately
    resilient against) or a future code bug in ``normalize_meeting()`` that
    happens to raise on every record -- both look identical from here, and
    both deserve a visible toast, not just a log line."""

    meetings: List[models.Meeting]
    quarantined: bool = False
    skipped_records: int = 0


def load_meetings_report() -> MeetingLoadReport:
    """Read and normalize every meeting on disk, same as ``load_meetings()``,
    but also report whether the whole file was quarantined (unreadable/
    corrupt) or individual records were skipped (bad field data) along the
    way. Never raises, for the same reasons ``load_meetings()``'s docstring
    describes below."""
    path = meetings_path()
    if not path.exists():
        return MeetingLoadReport(meetings=[])

    try:
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return MeetingLoadReport(meetings=[])
        decoded = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see below
        # Deliberately catches everything, not just OSError (read_text) and
        # json.JSONDecodeError (json.loads) as this used to. A file can be
        # syntactically-valid-but-extreme in ways that raise neither of
        # those: an invalid UTF-8 byte raises UnicodeDecodeError (not an
        # OSError subclass), and ~100k levels of nested "[" raises
        # RecursionError from deep inside json.loads() itself (not a
        # JSONDecodeError subclass). Every one of those must degrade the
        # same way this function's docstring promises -- quarantine the file
        # so the identical crash can't reproduce on the next launch, and
        # start empty instead of propagating. There's no way to know how
        # many meetings were in a file that never even parsed, so this is
        # reported as `quarantined=True` rather than a fabricated count --
        # see MeetingLoadReport's docstring for why the caller still surfaces
        # this to the user.
        logger.warning("Could not read/parse %s: %s", path, exc)
        _quarantine_corrupt_file(path)
        return MeetingLoadReport(meetings=[], quarantined=True)

    if not isinstance(decoded, list):
        return MeetingLoadReport(meetings=[])

    meetings: List[models.Meeting] = []
    skipped_records = 0
    for item in decoded:
        if not isinstance(item, dict):
            continue
        try:
            meetings.append(models.normalize_meeting(item))
        except Exception as exc:  # noqa: BLE001 - one bad record must not
            # sink the whole file's data. E.g. {"reminderMinutes": 1e400}
            # decodes cleanly to float("inf") (json.loads never raises for
            # this), but int(float("inf")) inside models._as_int() raises
            # OverflowError -- a type _as_int's own except clause doesn't
            # catch. Skip only this record; every other valid record in the
            # same file still loads.
            logger.warning("Skipping unparseable meeting record in %s: %s", path, exc)
            skipped_records += 1
    return MeetingLoadReport(meetings=meetings, skipped_records=skipped_records)


def load_meetings() -> List[models.Meeting]:
    """Read and normalize every meeting on disk. Never raises: a missing
    file yields an empty list, and an unreadable/corrupt file is quarantined
    (not deleted) and also yields an empty list rather than crashing the app.

    Thin wrapper around ``load_meetings_report()`` for the common case where
    the caller only wants the meetings, not whether anything was dropped
    getting there -- see that function (and ``MeetingLoadReport``) for
    callers that do care."""
    return load_meetings_report().meetings


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
    deleted_ids: Optional[FrozenSet[str]] = None,
) -> List[models.Meeting]:
    """Combine what's currently on disk (possibly edited on another machine
    since this process last loaded) with what's in memory. A meeting that
    exists only in memory survives the merge if it was created in the last
    ``SYNC_MERGE_GRACE`` seconds (it just hasn't reached disk yet); anything
    older that the disk no longer has is treated as a legitimate deletion
    from another session.

    ``deleted_ids`` names meetings *this process* just removed on purpose
    (a delete button, the "clear past events" button, or the automatic
    retention purge). Without it, a disk-only meeting and a
    just-deleted-locally meeting look identical (present on disk, absent
    from memory) and the merge can't tell them apart -- it would otherwise
    silently resurrect every deletion from the disk copy read just before
    the write. Callers that remove meetings must pass the ids they removed;
    see ``TimerMeetApp._persist`` for the single place that tracks this."""
    now = now or datetime.now()
    deleted_ids = deleted_ids or frozenset()
    memory_by_id: Dict[str, models.Meeting] = {m.id: m for m in memory_meetings}
    seen_ids = set()
    merged: List[models.Meeting] = []

    for disk_meeting in disk_meetings:
        if disk_meeting.id in deleted_ids:
            continue
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


def save_meetings(
    meetings: List[models.Meeting],
    now: Optional[datetime] = None,
    deleted_ids: Optional[FrozenSet[str]] = None,
) -> List[models.Meeting]:
    """Merge the in-memory list with whatever is currently on disk and
    atomically write the result — the merge becomes the new source of truth,
    so the caller should replace its in-memory state with the returned list.
    Raises only on a genuine disk-write failure (permissions, disk full);
    callers are expected to catch that and retry later, exactly like the
    original app's "saved locally, will retry" fallback.

    Pass ``deleted_ids`` (the ids of any meetings just removed from
    ``meetings`` on purpose) so the merge doesn't resurrect them from the
    disk read below -- see ``merge_meeting_lists`` for why this is needed."""
    with _same_machine_lock(data_dir()):
        disk_meetings = load_meetings()
        merged = sorted(merge_meeting_lists(disk_meetings, meetings, now, deleted_ids), key=_sort_key)
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


def load_companies() -> List[str]:
    """The user-managed company/job list backing the work-field combobox.

    Lives in ``settings.json`` (this machine only, like the language
    preference) rather than in ``meetings.json`` -- it's a UI convenience
    list, not shared/synced data, so it deliberately doesn't go through the
    OneDrive merge logic above."""
    raw = load_settings().get("companies")
    if not isinstance(raw, list):
        return []
    seen_lower = set()
    companies: List[str] = []
    for item in raw:
        name = item.strip() if isinstance(item, str) else ""
        if name and name.lower() not in seen_lower:
            seen_lower.add(name.lower())
            companies.append(name)
    return companies


def save_companies(companies: List[str]) -> None:
    """Persist the company list, merging into whatever else is already in
    settings.json (never overwrite sibling keys like "language")."""
    settings = load_settings()
    settings["companies"] = list(companies)
    save_settings(settings)


_HEX_COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


def _is_hex_color(value: object) -> bool:
    # fullmatch, not match() with a "^...$" pattern: "$" matches just before
    # a trailing "\n" as well as true end-of-string, so a value like
    # "#ffffff\n" used to pass this check and then raise deep inside Tk when
    # actually applied as a color (Tk's own color parser has no such
    # leniency) -- exactly the crash this validation exists to prevent (see
    # load_now_line_color's docstring). fullmatch() requires the whole
    # string to match, trailing newline included, with no anchor-escaping
    # footgun.
    return isinstance(value, str) and bool(_HEX_COLOR_RE.fullmatch(value))


def load_now_line_color(default: str) -> str:
    """The user-configurable color of the week view's live "now" line/dot
    (``main_window.NOW_LINE_COLOR`` is the shipped default). Same
    machine-local, UI-preference rationale as ``load_companies`` -- lives in
    settings.json, not synced/merged meeting data. Falls back to ``default``
    for a missing key or a value that isn't a well-formed ``#rrggbb`` string
    (e.g. hand-edited settings.json, or a future format change) rather than
    handing a bad color straight to Tk, which would raise deep inside a
    render call."""
    raw = load_settings().get("nowLineColor")
    return raw if _is_hex_color(raw) else default


def save_now_line_color(color: str) -> None:
    """Persist the "now" line color, merging into whatever else is already
    in settings.json (see ``save_companies``'s docstring for why this must
    never be a whole-file overwrite)."""
    settings = load_settings()
    settings["nowLineColor"] = color
    save_settings(settings)


def load_company_colors() -> Dict[str, str]:
    """User-chosen overrides for individual companies' block colors (see
    ``app.py::_build_work_color_map``), keyed by exact company name. Same
    machine-local settings.json home as ``load_companies``. Anything that
    doesn't validate -- a blank/non-string key, or a value that isn't a
    well-formed ``#rrggbb`` string -- is silently dropped rather than
    raised, so a hand-edited or partially-corrupt settings.json degrades to
    "that one company keeps its auto-assigned color" instead of crashing
    startup."""
    raw = load_settings().get("companyColors")
    if not isinstance(raw, dict):
        return {}
    colors: Dict[str, str] = {}
    for name, value in raw.items():
        if isinstance(name, str) and name.strip() and _is_hex_color(value):
            colors[name] = value
    return colors


def save_company_colors(colors: Dict[str, str]) -> None:
    """Persist company color overrides, merging into whatever else is
    already in settings.json (see ``save_companies``'s docstring)."""
    settings = load_settings()
    settings["companyColors"] = dict(colors)
    save_settings(settings)
