"""Application wiring: owns the in-memory state, the 1-second heartbeat, alert
firing, the renewal engine, and persistence.

This is the "controller" that connects ``storage.py`` / ``recurrence.py`` /
``audio.py`` / ``alarm_ui.py`` to the ``MainWindow`` view (``main_window.py``).
Business logic (validation, stats, filtering, alert gating) lives here, not in
the view, mirroring the ``processAlerts``/``renderStats``/``runHeartbeat``
functions in ``legacy-php/assets/app.js``.
"""

from __future__ import annotations

import colorsys
import logging
import math
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from . import i18n, main_window, models, notifications, recurrence, retention, security, storage
from .alarm_ui import AlarmController
from .main_window import (
    CALENDAR_MAX_ENTRIES_PER_CELL,
    WEEK_MAX_CONCURRENT_SPLIT,
    WEEK_MAX_DURATION_BLOCKS_PER_DAY,
    WEEK_MAX_ENTRIES_PER_CELL,
    Callbacks,
    CalendarCellData,
    CalendarEntry,
    MainWindow,
    MeetingCardData,
    WeekCellData,
    WeekMeetingBlock,
)
from .tray_icon import TrayIcon

logger = logging.getLogger(__name__)

HEARTBEAT_MS = 1000
RESYNC_MS = 60_000  # periodic reload-from-disk, the desktop equivalent of the
# web app's 45s server poll -- picks up edits made on another OneDrive-synced PC
PURGE_MS = 3_600_000  # once an hour is plenty for a retention window measured in days
MEETING_LIVE_WINDOW = timedelta(minutes=60)
START_ALERT_WINDOW = timedelta(minutes=10)


def _meeting_sort_key(meeting: models.Meeting):
    parsed = meeting.local_datetime()
    return parsed if parsed is not None else datetime.min


def _group_meetings_by_date(meetings: List[models.Meeting]) -> Dict[date, List[models.Meeting]]:
    """Group meetings by their local calendar date, for the monthly
    calendar view (see `_refresh_calendar`). A meeting with an empty or
    unparseable `datetime` (`local_datetime() is None`) has no calendar
    cell to belong to and is silently dropped here -- it must never appear
    in the grid (see SDD.md's acceptance criteria for v2.7.0), the same way
    it's already excluded from the list view's countdown/status rendering."""
    groups: Dict[date, List[models.Meeting]] = {}
    for meeting in meetings:
        when = meeting.local_datetime()
        if when is None:
            continue
        groups.setdefault(when.date(), []).append(meeting)
    return groups


def _cluster_meetings_by_overlap(ordered: List[models.Meeting]) -> List[List[models.Meeting]]:
    """Groups an already start-time-sorted day's meetings into connected
    components of overlap (SDD.md v2.16.0 decision #1) -- the standard
    calendar-layout clustering Google Calendar/Outlook both use, not an
    invention of this codebase. A cluster keeps accumulating meetings while
    the next one (by start time) begins BEFORE the latest end time seen so
    far anywhere in the cluster (`start < cluster_end`, strictly less-than);
    the moment a meeting starts at or after that running maximum, it can
    share no widget geometry with anything already in the cluster (even
    transitively), so it closes the current cluster and opens a new one.

    `start >= cluster_end` (not `>`) is deliberate, not an off-by-one: a
    meeting that starts exactly when the busiest-so-far meeting in the
    cluster ends must NOT be treated as overlapping it (an explicit
    acceptance criterion) -- back-to-back meetings read as sequential, not
    concurrent, to a human looking at the grid, and Teams/Outlook agree."""
    clusters: List[List[models.Meeting]] = []
    cluster_end: Optional[float] = None
    for meeting in ordered:
        when = meeting.local_datetime()
        start = when.hour + when.minute / 60
        end = start + meeting.durationMinutes / 60
        if cluster_end is None or start >= cluster_end:
            clusters.append([meeting])
            cluster_end = end
        else:
            clusters[-1].append(meeting)
            cluster_end = max(cluster_end, end)
    return clusters


def _assign_cluster_blocks(
    day_index: int, cluster: List[models.Meeting], series_sizes: Dict[str, int],
    work_colors: Optional[Dict[str, str]] = None,
) -> List[Tuple[WeekMeetingBlock, List[str]]]:
    """Lane-assigns ONE overlap cluster (see `_cluster_meetings_by_overlap`)
    and turns it into its final `WeekMeetingBlock`s, per SDD.md v2.16.0
    decisions #1-#3. Returns `(block, meeting_ids_it_represents)` pairs --
    the id list is `[meeting.id]` for a normal block and every absorbed
    meeting's id for the shared "+N más" aggregate -- so the caller can
    build the "which meetings already have SOME visual representation"
    set `_refresh_week` needs to stop listing them a second time in their
    hour-cell's plain text (SDD.md decision #7).

    Lane assignment itself is the same *greedy* "lowest free lane whose
    previous occupant already ended" algorithm `v2.15.0` used for its own
    thin bars -- proven (not just asserted) to use exactly as many lanes as
    the cluster's real peak concurrency, never more: because it always
    fills the LOWEST available index first, the set of lanes "open" at the
    cluster's busiest moment is always exactly `{0, ..., peak-1}`, so
    `len(lane_end_hour)` after processing the whole cluster IS that peak
    concurrency count, with no separate max-tracking needed."""
    ordered = sorted(cluster, key=_meeting_sort_key)
    lane_end_hour: List[float] = []
    lane_of: Dict[str, int] = {}
    for meeting in ordered:
        when = meeting.local_datetime()
        start = when.hour + when.minute / 60
        assigned_lane = next(
            (lane for lane, end_hour in enumerate(lane_end_hour) if end_hour <= start), None
        )
        if assigned_lane is None:
            assigned_lane = len(lane_end_hour)
            lane_end_hour.append(0.0)
        lane_end_hour[assigned_lane] = start + meeting.durationMinutes / 60
        lane_of[meeting.id] = assigned_lane

    def _series_count(meeting: models.Meeting) -> int:
        if meeting.recurrenceType != "none" and meeting.seriesId:
            return series_sizes.get(meeting.seriesId, 0)
        return 0

    def _real_block(meeting: models.Meeting, column_index: int, column_count: int) -> WeekMeetingBlock:
        when = meeting.local_datetime()
        start = when.hour + when.minute / 60
        return WeekMeetingBlock(
            day_index=day_index,
            column_index=column_index,
            column_count=column_count,
            start_hour_float=start,
            duration_minutes=meeting.durationMinutes,
            color=_work_block_color(meeting.workName, work_colors),
            title=meeting.title,
            time_text=when.strftime("%H:%M"),
            series_occurrence_count=_series_count(meeting),
            meeting_id=meeting.id,
            # Full start/end (SDD.md v2.17.2) for the block's hover tooltip
            # -- `time_text` above is only "HH:MM", not enough to show the
            # exact date the tooltip needs, and `main_window.py` has no
            # other way to recover it (`day_index` alone doesn't carry
            # which real calendar date it refers to).
            start_dt=when,
            end_dt=when + timedelta(minutes=meeting.durationMinutes),
        )

    real_concurrency = len(lane_end_hour)
    if real_concurrency <= WEEK_MAX_CONCURRENT_SPLIT:
        # Common case: this cluster's peak overlap already fits the
        # structural cap -- every meeting gets its own real, titled block,
        # `column_count` is just the cluster's real peak concurrency (a
        # lone meeting still gets `column_count=1`, i.e. the full column
        # width), never artificially padded up to the cap.
        column_count = max(real_concurrency, 1)
        return [
            (_real_block(meeting, lane_of[meeting.id], column_count), [meeting.id]) for meeting in ordered
        ]

    # Peak concurrency exceeds the cap (SDD.md decision #3): reserve the
    # LAST lane as one shared, non-interactive aggregate chip instead of
    # silently dropping the excess meetings the way v2.15.0's thin bars
    # did (their 4th+ concurrent meeting had no bar at all, only the
    # hour-cell text). `column_count` itself becomes the cap, not the real
    # (larger) concurrency, so the excess meetings' own lane indices
    # (>= column_count - 1) all collapse onto that one reserved slot.
    column_count = WEEK_MAX_CONCURRENT_SPLIT
    real_lane_ceiling = column_count - 1
    results: List[Tuple[WeekMeetingBlock, List[str]]] = []
    overflow_meetings: List[models.Meeting] = []
    for meeting in ordered:
        lane = lane_of[meeting.id]
        if lane < real_lane_ceiling:
            results.append((_real_block(meeting, lane, column_count), [meeting.id]))
        else:
            overflow_meetings.append(meeting)

    if overflow_meetings:
        starts = [m.local_datetime().hour + m.local_datetime().minute / 60 for m in overflow_meetings]
        ends = [s + m.durationMinutes / 60 for s, m in zip(starts, overflow_meetings)]
        aggregate = WeekMeetingBlock(
            day_index=day_index,
            column_index=real_lane_ceiling,
            column_count=column_count,
            start_hour_float=min(starts),
            duration_minutes=(max(ends) - min(starts)) * 60,
            color="",
            title="",
            time_text="",
            meeting_id=None,
            is_overflow=True,
            overflow_count=len(overflow_meetings),
        )
        results.append((aggregate, [m.id for m in overflow_meetings]))
    return results


def _assign_week_meeting_blocks(
    day_index: int, day_meetings: List[models.Meeting], series_sizes: Optional[Dict[str, int]] = None,
    work_colors: Optional[Dict[str, str]] = None,
) -> Tuple[List[WeekMeetingBlock], Set[str]]:
    """Full-width/split-width "Teams-style" block layout for one day's worth
    of meetings (SDD.md v2.16.0, replaces `v2.15.0`'s thin-bar
    `_assign_week_duration_blocks`), called once per visible day from
    `_refresh_week`. Pure/testable on its own -- no Tk widgets involved,
    only arithmetic and sorting -- exactly like its predecessor.

    Returns `(blocks, covered_meeting_ids)`: the second element is every
    meeting id that now has SOME visual representation in this layer (its
    own real block, or folded into an aggregate "+N más" chip) -- `_refresh_week`
    needs this set to stop listing those same meetings a second time in
    their hour-cell's plain text (SDD.md decision #7); a meeting NOT in this
    set got no representation at all here (only the day-level
    `WEEK_MAX_DURATION_BLOCKS_PER_DAY` cap below can cause that) and must
    keep showing in its hour-cell text exactly as it always has.

    Single remaining cap, independent of concurrency, unchanged from
    `v2.15.0`: `WEEK_MAX_DURATION_BLOCKS_PER_DAY`, a ceiling on the day's
    TOTAL block count (real + aggregate combined), since the week grid shows
    all 24 hours in one continuously-scrollable panel -- every meeting that
    day is on screen at once even when nothing overlaps. Clusters are
    processed in start-time order and a cluster that would push the running
    total past the cap has its OWN blocks truncated to whatever budget is
    left (including, in the rare case that truncation lands exactly on an
    aggregate chip, silently dropping that chip along with the "coverage"
    it would have given its absorbed meetings) -- an accepted, documented
    limitation for an already-extreme compound case (12+ meetings a day AND
    heavy overlap), not a regression against `v2.15.0`, which had the exact
    same class of limit for its own 4th+ concurrent meeting."""
    series_sizes = series_sizes or {}
    ordered = [m for m in sorted(day_meetings, key=_meeting_sort_key) if m.local_datetime() is not None]
    clusters = _cluster_meetings_by_overlap(ordered)

    all_blocks: List[WeekMeetingBlock] = []
    covered_ids: Set[str] = set()
    for cluster in clusters:
        if len(all_blocks) >= WEEK_MAX_DURATION_BLOCKS_PER_DAY:
            break
        cluster_blocks = _assign_cluster_blocks(day_index, cluster, series_sizes, work_colors)
        remaining_budget = WEEK_MAX_DURATION_BLOCKS_PER_DAY - len(all_blocks)
        if len(cluster_blocks) > remaining_budget:
            cluster_blocks = cluster_blocks[:remaining_budget]
        for block, meeting_ids in cluster_blocks:
            all_blocks.append(block)
            covered_ids.update(meeting_ids)
    return all_blocks, covered_ids


def _shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    """Advance/rewind a (year, month) pair by `delta` months, wrapping the
    year boundary in both directions (Dec + 1 -> next Jan; Jan - 1 ->
    previous Dec). The calendar view's Prev/Next buttons are the only
    callers, each passing delta=-1/+1 -- Python's floor division/modulo
    already do the right thing here without needing day-of-month overflow
    handling like `recurrence._add_months` (there's no day component)."""
    index = (month - 1) + delta
    return year + index // 12, index % 12 + 1


def _coerce_gadget_coordinate(value) -> Optional[int]:
    """A hand-edited or corrupted settings.json could put anything under
    gadgetX/gadgetY (a string, a list, ...); only trust it if it's actually
    numeric, otherwise fall back to the same "use the default position" path
    an absent value already takes, the same way saved_language is validated
    against i18n.translations before being trusted below.

    ``isinstance(value, (int, float))`` alone isn't enough: Python's
    ``json`` module accepts the non-standard ``NaN``/``Infinity``/
    ``-Infinity`` literals on load (so a hand-edited settings.json with
    ``"gadgetX": NaN`` parses without error into ``float("nan")``), and
    ``int()`` on either raises (``ValueError`` for NaN, ``OverflowError``
    for +/-Infinity) rather than returning a value -- which would crash
    the app on startup before a single window is ever shown. Reject those
    the same way a non-numeric value already is."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return int(value)
    return None


def _coerce_gadget_size(value, default: int) -> int:
    """Same defensive style as `_coerce_gadget_coordinate`, for
    gadgetWidth/gadgetHeight: only trust a plain numeric value. Unlike the
    coordinate coercion, there's no "use None and let the caller pick a
    default" path here -- `MainWindow._resolve_gadget_size` already clamps
    whatever int it's handed to the min/max bounds, so this only needs to
    guard against a non-numeric settings.json value crashing that clamp
    (e.g. `int("banana")`), not against an out-of-range one.

    ``math.isfinite()`` guard mirrors `_coerce_gadget_coordinate`'s: a
    hand-edited ``"gadgetWidth": NaN``/``Infinity`` parses cleanly via
    ``json.loads`` (it's a Python-accepted, if non-standard, JSON
    extension) but ``int(float("nan"))``/``int(float("inf"))`` raise
    rather than clamp, which `_resolve_gadget_size`'s own min/max clamp
    downstream never gets a chance to catch."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and math.isfinite(value):
        return int(value)
    return default


def _coerce_app_theme(value) -> str:
    """A hand-edited or stale settings.json could name a theme that no
    longer exists (or never did); only trust `value` if it's a real key in
    the current `APP_THEMES` registry, otherwise fall back to the default
    theme -- the same "absent/corrupted value takes the default path" style
    `saved_language`/`_coerce_gadget_coordinate` already use above.

    Renamed from `_coerce_gadget_skin` in v2.14.0 when the gadget-only skin
    picker grew into a whole-app theme picker (SDD.md v2.14.0) -- a clean
    rename, not a second helper, since there's exactly one setting
    (`appTheme`) now, not two that could drift."""
    if isinstance(value, str) and value in main_window.APP_THEMES:
        return value
    return main_window.APP_DEFAULT_THEME


def _meeting_status(meeting: models.Meeting, now: datetime) -> str:
    when = meeting.local_datetime()
    if when is None:
        return "past"
    reminder_time = when - timedelta(minutes=meeting.reminderMinutes)
    if when <= now < when + MEETING_LIVE_WINDOW:
        return "live"
    if reminder_time <= now < when:
        return "dueSoon"
    if now < reminder_time:
        return "upcoming"
    return "past"


def _format_relative(delta: timedelta, language: str) -> str:
    """Port of `formatRelativeTime()`: floor to minutes, split into
    days/hours/minutes, then join only the first two non-zero chunks."""
    total_seconds = delta.total_seconds()
    if total_seconds <= 0:
        return i18n.t("startsNow", language)
    total_minutes = int(total_seconds // 60)
    days, remainder = divmod(total_minutes, 60 * 24)
    hours, minutes = divmod(remainder, 60)
    chunks = []
    if days:
        chunks.append(f"{days} d")
    if hours:
        chunks.append(f"{hours} h")
    if minutes or not chunks:
        chunks.append(f"{minutes} min")
    return " ".join(chunks[:2])


def _countdown_text(meeting: models.Meeting, now: datetime, language: str) -> str:
    when = meeting.local_datetime()
    if when is None:
        return ""
    if when <= now:
        return f"{i18n.t('startedAgo', language)} {_format_relative(now - when, language)}"
    return f"{i18n.t('startsIn', language)} {_format_relative(when - now, language)}"


_CALENDAR_WEEKDAY_KEYS = [
    "calendarWeekdayMon", "calendarWeekdayTue", "calendarWeekdayWed",
    "calendarWeekdayThu", "calendarWeekdayFri", "calendarWeekdaySat", "calendarWeekdaySun",
]

_RECURRENCE_TEXT_KEYS = {
    "daily": "recurrenceDaily",
    "weekdays": "recurrenceWeekdays",
    "weekly": "recurrenceWeekly",
    "biweekly": "recurrenceBiweekly",
    "monthly": "recurrenceMonthly",
}


def _recurrence_text(meeting: models.Meeting, language: str) -> str:
    if meeting.recurrenceType == "none":
        return ""
    label_key = _RECURRENCE_TEXT_KEYS.get(meeting.recurrenceType)
    text = i18n.t(label_key, language) if label_key else ""
    if meeting.seriesSize > 1:
        occurrence = i18n.format_text(
            "repeatOccurrenceLabel", language, index=meeting.occurrenceIndex, total=meeting.seriesSize
        )
        text = f"{text} · {occurrence}" if text else occurrence
    return text


def _to_signed_32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value >= 0x80000000 else value


def _color_for_work_name(name: str) -> str:
    """Deterministic per-name color chip, in the spirit of the original's
    `stringToColor()` string hash -- not a byte-exact port (purely cosmetic),
    just guaranteed stable for a given work name.

    Kept as the fallback `_work_block_color` uses when no `work_colors` map
    is available (direct/unit-test callers) -- real render paths build a map
    via `_build_work_color_map` instead, see that function's docstring for
    why a raw hash alone isn't enough."""
    if not name:
        return "#d4d4d8"
    hash_value = 0
    for char in name:
        hash_value = ord(char) + ((hash_value << 5) - hash_value)
        hash_value &= 0xFFFFFFFF
    hue = abs(_to_signed_32(hash_value)) % 360
    red, green, blue = colorsys.hls_to_rgb(hue / 360, 0.74, 0.70)
    return "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))


# 360 / phi^2: the golden-angle hue increment. Assigning each company a hue
# this far from the previous one (walking the CURRENT, sorted set of company
# names in order) spreads any number of colors around the wheel with maximal
# separation between neighbors -- unlike `_color_for_work_name`'s raw string
# hash above, which has no such guarantee. Real-data proof this matters
# (v2.17.1): two actual saved companies, "SRS" and "Direct English", hashed
# to #eb8ede/#eb8ee6 -- two hex digits apart, indistinguishable by eye in the
# week/month/list views, even though the hash itself never collided (it's
# the same problem a birthday-paradox-style near-collision always risks with
# an unconstrained hash-to-hue mapping over a small set of buckets).
_GOLDEN_ANGLE_DEGREES = 137.508


def _build_work_color_map(work_names) -> Dict[str, str]:
    """Assigns every distinct, non-blank name in `work_names` its own color,
    spaced by `_GOLDEN_ANGLE_DEGREES` around the hue wheel in sorted-name
    order -- guarantees every company CURRENTLY present in the data reads as
    visually distinct from every other one, which a per-name hash cannot
    promise (see `_color_for_work_name`'s docstring). Trade-off, accepted:
    unlike a pure hash, a company's color can shift if the overall set of
    saved company names changes (one added/removed/renamed) -- acceptable
    here since every render path rebuilds this map fresh from the current
    `self.meetings` on every heartbeat tick anyway, so it's never stale."""
    ordered = sorted({name for name in work_names if name})
    colors: Dict[str, str] = {}
    for index, name in enumerate(ordered):
        hue = (index * _GOLDEN_ANGLE_DEGREES) % 360
        red, green, blue = colorsys.hls_to_rgb(hue / 360, 0.74, 0.70)
        colors[name] = "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))
    return colors


def _work_block_color(name: str, work_colors: Optional[Dict[str, str]]) -> str:
    """Look up `name`'s color in a precomputed `_build_work_color_map` result
    when one is available, falling back to the plain per-name hash otherwise
    (direct/unit-test calls that don't build a map, e.g.
    `tests/test_app_helpers.py`'s direct `_assign_week_meeting_blocks` calls)
    -- never raises on a missing/blank name either way."""
    if work_colors is not None:
        color = work_colors.get(name)
        if color:
            return color
    return _color_for_work_name(name)


class TimerMeetApp:
    def __init__(self) -> None:
        self.root = tk.Tk()

        # Read settings before deciding what to show first: if the user was
        # last in gadget mode, the full-size 1180x760 splash below must never
        # be shown even briefly, or every resumed launch would flash exactly
        # the large window this feature exists to avoid before shrinking
        # back down (there's no update()/update_idletasks() call between here
        # and mainloop() starting, so whatever geometry is set first is what
        # actually gets painted).
        settings = storage.load_settings()
        saved_language = settings.get("language")
        self.language = saved_language if saved_language in i18n.translations else i18n.DEFAULT_LANGUAGE
        self.gadget_mode = bool(settings.get("gadgetMode", False))
        self._gadget_x = _coerce_gadget_coordinate(settings.get("gadgetX"))
        self._gadget_y = _coerce_gadget_coordinate(settings.get("gadgetY"))
        # `settings.get("appTheme", settings.get("gadgetSkin"))` (v2.14.0):
        # a one-time migration read, not a second persisted setting -- a
        # user who already picked a gadget skin under v2.13.0 (before the
        # whole-app theme picker existed) had that choice saved under the
        # old `gadgetSkin` key; without this fallback, upgrading to v2.14.0
        # would silently reset their preference back to "classic" the
        # moment `appTheme` is absent, which is exactly the kind of silent
        # preference loss this project's own settings-merge discipline
        # exists to avoid (see `_save_theme_and_gadget_settings` below,
        # which only ever writes `appTheme` going forward -- the old key is
        # simply never read again once this session's first save happens).
        self._app_theme = _coerce_app_theme(settings.get("appTheme", settings.get("gadgetSkin")))
        self._gadget_width = _coerce_gadget_size(settings.get("gadgetWidth"), main_window.GADGET_WIDTH)
        self._gadget_height = _coerce_gadget_size(settings.get("gadgetHeight"), main_window.GADGET_HEIGHT)
        # Persisted the same way `gadgetMode` is (a stable per-machine UI
        # preference, unlike `active_view`/`_week_anchor`, which are
        # deliberately reset every launch -- see SDD.md v2.10.0). Only
        # trusted if it's exactly one of the two real values; anything else
        # (absent, corrupted, hand-edited) falls back to "full", same
        # defensive style already used for `saved_language` above.
        saved_week_column_mode = settings.get("weekColumnMode")
        self.week_column_mode = saved_week_column_mode if saved_week_column_mode in ("work", "full") else "full"

        # Belt-and-suspenders against a packaged build ever ending up with a
        # window that exists but never gets shown (observed once under
        # PyInstaller --windowed, root-caused to sys.stdout/stderr being
        # None -- see timermeet.py). Harmless either way it resolves below:
        # deiconify/state/lift/focus_force never touch geometry/overrideredirect,
        # so it just re-affirms whichever surface set_gadget_mode already made
        # visible if the app is resuming into gadget mode.
        self.root.after(0, self._force_show_window)

        if self.gadget_mode:
            # Skip the full-size splash entirely -- MainWindow builds
            # full_view gridded by default, so leaving root withdrawn until
            # set_gadget_mode(True, ...) runs (further down, once the view
            # exists) means the large window is never mapped/painted at all.
            self.root.withdraw()
            loading_label = None
        else:
            self.root.geometry("1180x760")
            self.root.minsize(960, 640)
            # Cheap, immediate feedback while the real UI builds underneath.
            loading_label = tk.Label(
                self.root, text="Cargando TimerMeet…", font=("Segoe UI", 14), bg="#1a1a1a", fg="#f5f5f5"
            )
            loading_label.place(relx=0.5, rely=0.5, anchor="center")
            # update_idletasks(), not update(): only the loading label exists
            # at this point, so there's nothing but its own geometry/paint to
            # flush -- cheap by construction (unlike the v2.1.0 bug, which
            # called this *after* the whole widget tree existed). update()
            # would additionally process the `after(0, self._force_show_window)`
            # queued above, whose deiconify/lift/focus_force calls measured
            # ~0.5s alone; deferring that to mainloop()'s own event processing
            # keeps this paint-only flush cheap.
            self.root.update_idletasks()

        self.work_filter = "all"
        # Which primary view is showing ("list"/"calendar") -- mirrors
        # MainWindow's own `_primary_view`, but this copy is what
        # `_refresh_all` reads to decide whether the calendar's per-heartbeat
        # recompute (grouping meetings by date, rebuilding 42 cells' worth of
        # display data) is worth doing at all; see `_refresh_calendar`. Not
        # persisted between launches -- unlike gadgetMode, nothing in
        # SDD.md's acceptance criteria asks for that, and the app always
        # starts in list view.
        self.active_view = "list"
        now = datetime.now()
        self._calendar_year = now.year
        self._calendar_month = now.month
        # Any date inside the shown week -- `recurrence.week_dates` derives
        # the real 7 dates from this on every render (never cached as "today
        # was X when the view opened"), same spirit as `_calendar_year`/
        # `_calendar_month` above.
        self._week_anchor: date = now.date()
        # Captured as a report (not a bare list) purely so the startup toast
        # below can tell the user something was actually dropped -- see
        # `_maybe_show_startup_load_toast` and `storage.MeetingLoadReport`.
        startup_load = storage.load_meetings_report()
        self.meetings: List[models.Meeting] = startup_load.meetings
        self._pending_deleted_ids: set = set()

        # First run under this feature (no "companies" key at all yet): seed
        # the list from whatever work names already exist in meetings.json,
        # so upgrading users don't see an empty dropdown. After that, the
        # persisted list is authoritative -- it deliberately does NOT get
        # re-derived from meetings.json on later launches, or an explicit
        # removal would silently come back the next time that name is still
        # used by an existing meeting.
        if "companies" in settings:
            self.companies: List[str] = storage.load_companies()
        else:
            self.companies = sorted({m.workName for m in self.meetings if m.workName}, key=str.lower)
            storage.save_companies(self.companies)
        purged_at_startup = self._apply_meetings(retention.purge_stale_meetings(self.meetings)[0])
        self.storage_ok = True
        self._dirty = bool(purged_at_startup)
        self._resync_accumulator_ms = 0
        self._purge_accumulator_ms = 0
        self._last_rendered_signature = None
        self._last_rendered_calendar_signature = None
        self._last_rendered_week_signature = None  # Nivel A, see `_refresh_week`
        self._last_rendered_week_live_state = None  # Nivel B, see `_refresh_week`
        # One-shot request for the week view's auto-scroll-to-now (v2.14.1):
        # set True by `handle_set_active_view` (entering week view from
        # another view) and `handle_week_today`, consumed by the very next
        # `_refresh_all` -> `_refresh_week` call regardless of which of
        # those two set it. Never set True by the heartbeat itself, which is
        # exactly what keeps a per-minute re-render from ever re-centering
        # the scroll out from under a user who scrolled elsewhere manually.
        self._week_scroll_to_now_requested = False

        callbacks = Callbacks(
            on_save=self.handle_save,
            on_clear=self.handle_clear,
            on_edit=self.handle_edit,
            on_delete=self.handle_delete,
            on_open_link=self.handle_open_link,
            on_test_sound=self.handle_test_sound,
            on_set_now=self.handle_set_now,
            on_toggle_language=self.handle_toggle_language,
            on_test_notification=self.handle_test_notification,
            on_filter_change=self.handle_filter_change,
            on_clear_past=self.handle_clear_past,
            on_exit=self._on_close,
            on_add_company=self.handle_add_company,
            on_remove_company=self.handle_remove_company,
            on_toggle_gadget_mode=self.handle_toggle_gadget_mode,
            on_enter_tray_mode=self.handle_enter_tray_mode,
            on_set_active_view=self.handle_set_active_view,
            on_calendar_prev_month=self.handle_calendar_prev_month,
            on_calendar_next_month=self.handle_calendar_next_month,
            on_calendar_today=self.handle_calendar_today,
            on_calendar_day_click=self.handle_calendar_day_click,
            on_week_prev=self.handle_week_prev,
            on_week_next=self.handle_week_next,
            on_week_today=self.handle_week_today,
            on_week_slot_click=self.handle_week_slot_click,
            on_toggle_week_column_mode=self.handle_toggle_week_column_mode,
            on_delete_series=self.handle_delete_series,
            on_set_app_theme=self.handle_set_app_theme,
            on_gadget_resize=self.handle_gadget_resize,
        )
        self.view = MainWindow(self.root, callbacks)
        self.view.apply_translations(self.language)
        self.view.update_company_options(self.companies)
        self.view.set_week_column_mode(self.week_column_mode)
        # Applied BEFORE `set_gadget_mode` below (v2.14.0) so gadget mode's
        # own initial entry -- which internally calls `apply_gadget_skin`
        # again with whatever `self._app_theme` already is -- is consistent
        # with whatever this call just set, not fighting it.
        self.view.apply_theme(self._app_theme)
        if self.gadget_mode:
            self.view.set_gadget_mode(
                True, self._gadget_x, self._gadget_y, self._gadget_width, self._gadget_height, self._app_theme,
            )
        self._maybe_show_startup_load_toast(startup_load)

        self.alarms = AlarmController(self.root, get_language=lambda: self.language)
        self.alarms.set_base_title(i18n.t("appTitle", self.language))

        # Cheap to construct (no pystray/Pillow import happens until the
        # first real show() call, see tray_icon.py) -- callbacks are wrapped
        # in root.after(0, ...) here, not inside TrayIcon itself, since they
        # fire from pystray's own background thread and Tkinter widgets may
        # only ever be touched from the main thread.
        self.tray_mode = False
        self.tray = TrayIcon(
            icon_path=storage.base_dir() / "computer_pc_10894.ico",
            tooltip=i18n.t("trayModeToast", self.language),
            on_restore=lambda: self.root.after(0, self.handle_restore_from_tray),
            on_exit=lambda: self.root.after(0, self._on_close),
        )

        self.root.bind("<FocusIn>", self._on_focus_in)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._refresh_all()
        self.root.after(HEARTBEAT_MS, self._heartbeat)
        # Do NOT add a synchronous root.update()/update_idletasks() call here.
        # It was here in an earlier version to force CustomTkinter's deferred
        # widget rendering to finish before showing the real UI -- but
        # forcing the *entire* pending idle/geometry queue to drain in one
        # blocking call is exactly what made the window freeze on launch
        # with a real-sized meeting list (10+ seconds, confirmed by timing).
        # Removing it fixed the freeze completely: letting mainloop() work
        # through the same queue incrementally, interleaved with normal
        # event processing, is what keeps Windows from flagging the window
        # "Not Responding" during startup.
        if loading_label is not None:
            loading_label.destroy()

        # Run on a background thread rather than blocking startup on it:
        # warm_cache() only touches the filesystem/MCI, never a Tkinter
        # widget, so it's safe to run concurrently with the UI thread. The
        # alarm system works fine in the meantime either way -- it opens the
        # MP3 (or falls back to a synth tone) on demand the moment an alarm
        # actually needs to play (see audio.py).
        threading.Thread(target=self.alarms.warm_cache, daemon=True).start()

    def run(self) -> None:
        self.root.mainloop()

    def _force_show_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
        except Exception as exc:  # nosec B110 - defensive nicety, must never block startup
            logger.warning("Could not force-show the main window: %s", exc)

    def _maybe_show_startup_load_toast(self, report: "storage.MeetingLoadReport") -> None:
        """Surface the one-time startup load report as a toast instead of
        letting it live only in ``data/timermeet.log`` (see
        ``storage.MeetingLoadReport``'s docstring for why this matters: bad
        data and a future code bug in ``normalize_meeting()`` degrade
        identically here, and both must be visible, not just logged). Quiet
        no-op on the ordinary clean-load path (``quarantined=False`` and
        ``skipped_records=0``), which is every launch except the two failure
        cases this exists for."""
        if report.quarantined:
            # The file never even parsed, so there's no way to know how many
            # meetings were in it -- a fabricated count would be worse than
            # none, so this case gets its own count-free message instead of
            # reusing meetingsSkippedToast with a made-up number.
            self.view.show_toast(i18n.t("meetingsFileCorruptToast", self.language))
        elif report.skipped_records:
            self.view.show_toast(
                i18n.format_text("meetingsSkippedToast", self.language, count=report.skipped_records)
            )

    # -- persistence ----------------------------------------------------------

    def _apply_meetings(self, new_meetings: List[models.Meeting]) -> int:
        """Replace ``self.meetings`` and record the ids of anything removed
        so the next ``_persist()`` doesn't let a stale disk read resurrect
        them (a disk-only meeting and a just-deleted-locally meeting are
        otherwise indistinguishable -- see
        ``storage.merge_meeting_lists``). Every deletion path (single
        delete, "clear past events", the automatic retention purge) must go
        through this instead of assigning ``self.meetings`` directly.
        Returns how many meetings were removed."""
        before_ids = {m.id for m in self.meetings}
        self.meetings = new_meetings
        removed_ids = before_ids - {m.id for m in new_meetings}
        self._pending_deleted_ids |= removed_ids
        return len(removed_ids)

    def _persist(self, silent: bool = True) -> None:
        try:
            merged = storage.save_meetings(self.meetings, deleted_ids=frozenset(self._pending_deleted_ids))
        except OSError as exc:
            logger.warning("Could not save meetings: %s", exc)
            self.storage_ok = False
            self._dirty = True
            if not silent:
                self.view.show_toast(i18n.t("storageFallbackToast", self.language))
            return
        self.meetings = merged
        self._pending_deleted_ids.clear()
        self.storage_ok = True
        self._dirty = False

    def _resync_from_disk(self) -> None:
        try:
            disk_meetings = storage.load_meetings()
        except OSError:
            return
        merged = storage.merge_meeting_lists(
            disk_meetings, self.meetings, deleted_ids=frozenset(self._pending_deleted_ids)
        )
        before = sorted((m.to_dict() for m in self.meetings), key=lambda d: d["id"])
        after = sorted((m.to_dict() for m in merged), key=lambda d: d["id"])
        if before != after:
            self.meetings = sorted(merged, key=_meeting_sort_key)
            self._persist(silent=True)
            self._refresh_all()

    def _on_focus_in(self, _event=None) -> None:
        self._resync_from_disk()

    def _on_close(self) -> None:
        # advance_queue=False: the app is shutting down, so any other alert
        # still waiting in the queue must be dropped, not popped and shown
        # in a brand-new Toplevel parented to a root that's about to be
        # destroyed (see AlarmController.dismiss's docstring/comment).
        self.alarms.dismiss(run_callback=False, advance_queue=False)
        if self.gadget_mode:
            # Otherwise quitting directly from the gadget's own close button
            # would lose whatever spot the user last dragged it to -- normal
            # toggling back to the full window already flushes this, but a
            # direct quit from gadget mode skips that path entirely.
            self._gadget_x, self._gadget_y = self.view.current_gadget_position()
            self._save_theme_and_gadget_settings()
        # Removes the tray icon immediately (NIM_DELETE) instead of leaving
        # it for the OS to eventually notice the owning process died.
        self.tray.stop()
        self.root.destroy()

    # -- heartbeat / alerts -----------------------------------------------------

    def _heartbeat(self) -> None:
        now = datetime.now()
        created = recurrence.run_weekly_series_renewal(self.meetings, now)
        fired_any = self._process_alerts(now)

        self._purge_accumulator_ms += HEARTBEAT_MS
        purged = 0
        if self._purge_accumulator_ms >= PURGE_MS:
            self._purge_accumulator_ms = 0
            purged = self._apply_meetings(retention.purge_stale_meetings(self.meetings, now)[0])

        if created or purged or fired_any or self._dirty:
            self._persist(silent=True)
            if created:
                self.view.show_toast(i18n.format_text("renewalToast", self.language, count=created))

        self._resync_accumulator_ms += HEARTBEAT_MS
        if self._resync_accumulator_ms >= RESYNC_MS:
            self._resync_accumulator_ms = 0
            self._resync_from_disk()

        self._refresh_all()
        self.root.after(HEARTBEAT_MS, self._heartbeat)

    def _process_alerts(self, now: datetime) -> bool:
        """Port of `processAlerts()`: fires a reminder alert once when the
        reminder window opens, and a start alert once within 10 minutes of
        the scheduled time -- both silently marked "sent" without notifying
        if that window was already missed (e.g. the app was closed through
        it), so a stale record can never suddenly alarm hours later."""
        changed = False
        for meeting in self.meetings:
            when = meeting.local_datetime()
            if when is None:
                continue
            reminder_time = when - timedelta(minutes=meeting.reminderMinutes)
            start_window_end = when + START_ALERT_WINDOW

            if not meeting.reminderSent and reminder_time <= now < when:
                self._notify_meeting(meeting, "reminder")
                meeting.reminderSent = True
                changed = True
            elif not meeting.reminderSent and now >= when:
                meeting.reminderSent = True
                changed = True

            if not meeting.startSent and when <= now <= start_window_end:
                self._notify_meeting(meeting, "start")
                meeting.startSent = True
                changed = True
            elif not meeting.startSent and now > start_window_end:
                meeting.startSent = True
                changed = True
        return changed

    def _notify_meeting(self, meeting: models.Meeting, mode: str) -> None:
        self.alarms.notify(meeting, mode, on_dismiss=self._refresh_all)

    # -- derived view state -----------------------------------------------------

    def _visible_meetings(self) -> List[models.Meeting]:
        if self.work_filter == "all":
            return list(self.meetings)
        target = self.work_filter.lower()
        return [m for m in self.meetings if m.workName.lower() == target]

    def _work_names(self) -> List[str]:
        return sorted({m.workName for m in self.meetings if m.workName})

    def _compute_stats(self, now: datetime):
        total = len(self.meetings)
        today = sum(1 for m in self.meetings if (m.local_datetime() or datetime.min).date() == now.date())
        upcoming = sorted(
            (m for m in self.meetings if _meeting_sort_key(m) >= now), key=_meeting_sort_key
        )
        if upcoming:
            next_meeting = upcoming[0]
            next_text = f"{next_meeting.title} · {_format_relative(next_meeting.local_datetime() - now, self.language)}"
        else:
            next_text = i18n.t("nextMeetingNone", self.language)
        return total, today, next_text

    def _compute_next_alert(self, now: datetime) -> str:
        candidates = []
        for meeting in self.meetings:
            when = meeting.local_datetime()
            if when is None:
                continue
            reminder_time = when - timedelta(minutes=meeting.reminderMinutes)
            if not meeting.reminderSent and reminder_time > now:
                candidates.append((reminder_time, "alertReminderTitle", meeting))
            if not meeting.startSent and when > now:
                candidates.append((when, "alertStartTitle", meeting))
        if not candidates:
            return i18n.t("nextAlertNone", self.language)
        candidates.sort(key=lambda item: item[0])
        timestamp, label_key, meeting = candidates[0]
        relative = _format_relative(timestamp - now, self.language)
        return f"{i18n.t(label_key, self.language)}: {meeting.title} · {relative}"

    def _refresh_all(self) -> None:
        now = datetime.now()
        self.view.update_clock(now.strftime("%H:%M:%S"))
        self.view.update_next_alert(self._compute_next_alert(now))

        total, today, next_text = self._compute_stats(now)
        self.view.update_stats(total, today, next_text)

        storage_key = "storageServer" if self.storage_ok else "storageLocal"
        self.view.update_storage_status(i18n.t(storage_key, self.language))
        work_names = self._work_names()
        self.view.update_filter_options(work_names, self.work_filter)
        # Built fresh from the full, current meeting list on every tick (same
        # redundant-but-cheap precedent `series_sizes` already sets in
        # `_refresh_calendar`/`_refresh_week` below, rather than threading a
        # shared value through) -- see `_build_work_color_map`'s docstring
        # for why this guarantees distinct colors instead of a raw hash.
        work_colors = _build_work_color_map(work_names)

        cards = [
            MeetingCardData(
                meeting=meeting,
                status_key=_meeting_status(meeting, now),
                countdown_text=_countdown_text(meeting, now, self.language),
                recurrence_text=_recurrence_text(meeting, self.language),
                color=_work_block_color(meeting.workName, work_colors),
            )
            for meeting in sorted(self._visible_meetings(), key=_meeting_sort_key)
        ]

        # Rebuilding every CustomTkinter card widget from scratch is
        # expensive (each card is ~8 canvas-based widgets), and _refresh_all
        # runs every second from the heartbeat. Skip the rebuild whenever
        # nothing a card actually displays has changed -- countdown text
        # only changes once a minute (see _format_relative's minute
        # flooring), so with a real-sized meeting list this is what keeps
        # the UI thread from falling behind and the window from appearing
        # to hang. Mirrors the original web app's own "skip re-render if
        # nothing changed" optimization in its merge path.
        signature = (
            self.language,
            tuple(
                # `c.color` included so a card whose OWN fields didn't change
                # still re-renders if the color map itself shifted (e.g. a
                # company was added/removed elsewhere, reflowing every other
                # company's golden-angle-indexed hue) -- see
                # `_build_work_color_map`'s docstring for why colors aren't
                # permanently fixed per name anymore.
                (c.meeting.id, c.status_key, c.countdown_text, c.recurrence_text, c.meeting.updatedAt, c.color)
                for c in cards
            ),
        )
        if signature != self._last_rendered_signature:
            self.view.render_meeting_list(cards)
            self._last_rendered_signature = signature

        # Building the 6x7 grid's display data (grouping every meeting by
        # date, formatting up to 3 entries per cell x 42 cells) only to throw
        # it away unseen would be pure waste on every single heartbeat tick
        # while the user is looking at the list or the gadget -- skip it
        # entirely unless the calendar is the view actually on screen, same
        # spirit as `keep_gadget_on_top` being a no-op outside gadget mode.
        # `active_view` alone isn't enough: entering gadget mode doesn't
        # change it (gadget mode is an orthogonal reskin of the SAME root
        # window, see MainWindow.set_gadget_mode), so a user who was in
        # calendar view before toggling into the gadget would otherwise keep
        # paying this cost every tick for a frame that's `grid_remove()`d
        # and physically invisible.
        if self.active_view == "calendar" and not self.gadget_mode:
            self._refresh_calendar(now)
        elif self.active_view == "week" and not self.gadget_mode:
            # `_week_scroll_to_now_requested` is consumed here, unconditionally,
            # the moment it's actually handed to `_refresh_week` -- a one-shot
            # flag, not a standing state, so a later heartbeat tick (this
            # same `elif` branch, ~1s later) never re-sends `True` on its own.
            self._refresh_week(now, scroll_to_now=self._week_scroll_to_now_requested)
            self._week_scroll_to_now_requested = False

        # A near-zero-cost no-op unless gadget mode is active; piggybacks on
        # this existing 1s heartbeat instead of a separate self-rescheduling
        # relift job (one less job lifecycle to start/cancel correctly).
        self.view.keep_gadget_on_top(self.alarms.is_active())

    def _refresh_calendar(self, now: datetime) -> None:
        """Build this heartbeat's display data for the monthly calendar
        view and hand it to `MainWindow.render_calendar`, which only ever
        `.configure()`/`.grid()`/`.grid_remove()`s the 42 pre-built cells --
        see that method's docstring. Only called while `active_view ==
        "calendar"` (see `_refresh_all`)."""
        weeks = recurrence.month_grid(self._calendar_year, self._calendar_month)
        grouped = _group_meetings_by_date(self.meetings)
        # Real, live sibling counts per series (SDD.md v2.11.0) -- computed
        # once per refresh, never read from `meeting.seriesSize`, which
        # `retention.py` never decrements on a partial purge and so can be
        # stale/inflated (a series that was once 8 occurrences can survive
        # with just 1 real record still claiming `seriesSize == 8`). Feeds
        # `CalendarEntry.series_occurrence_count` below, which is what the
        # right-click menu's "Eliminar serie completa" enablement actually
        # checks -- see that field's own docstring in main_window.py.
        series_sizes = {sid: len(group) for sid, group in recurrence.group_meetings_by_series(self.meetings).items()}
        # Same redundant-but-cheap "compute fresh from self.meetings" pattern
        # `series_sizes` above already uses, applied to colors -- see
        # `_build_work_color_map`'s docstring.
        work_colors = _build_work_color_map(self._work_names())
        # "Today" is only highlighted while the *visible* month is the real
        # current month (see SDD.md) -- comparing bare dates would wrongly
        # highlight a leading/trailing padding cell that happens to literally
        # be today's date while browsing a neighboring month.
        showing_current_month = (self._calendar_year, self._calendar_month) == (now.year, now.month)
        today_date = now.date()

        cells: List[CalendarCellData] = []
        for week in weeks:
            for day in week:
                # `grouped` only ever holds meetings whose `local_datetime()`
                # parsed successfully (see `_group_meetings_by_date`), so
                # every meeting reaching this loop already has one -- no
                # `datetime.min` fallback needed the way `_meeting_sort_key`
                # needs one for the *unfiltered* full meeting list.
                day_meetings = sorted(grouped.get(day, []), key=_meeting_sort_key)
                entries = [
                    CalendarEntry(
                        meeting_id=meeting.id,
                        # "HH:MM-HH:MM" (Teams-style start-end range, SDD.md
                        # v2.15.0), plain ASCII hyphen -- same separator
                        # convention `i18n.format_week_range` already uses
                        # for its own ranges. `_last_rendered_calendar_
                        # signature` already treats `time_text` as an opaque
                        # string, so a duration-only edit is detected for
                        # free without touching that tuple.
                        time_text=(
                            f"{meeting.local_datetime().strftime('%H:%M')}-"
                            f"{(meeting.local_datetime() + timedelta(minutes=meeting.durationMinutes)).strftime('%H:%M')}"
                        ),
                        title=meeting.title,
                        color=_work_block_color(meeting.workName, work_colors),
                        series_occurrence_count=(
                            series_sizes.get(meeting.seriesId, 0)
                            if meeting.recurrenceType != "none" and meeting.seriesId
                            else 0
                        ),
                    )
                    for meeting in day_meetings[:CALENDAR_MAX_ENTRIES_PER_CELL]
                ]
                cells.append(
                    CalendarCellData(
                        day=day,
                        in_current_month=(day.year, day.month) == (self._calendar_year, self._calendar_month),
                        is_today=showing_current_month and day == today_date,
                        entries=entries,
                        overflow_count=max(0, len(day_meetings) - CALENDAR_MAX_ENTRIES_PER_CELL),
                    )
                )

        month_label = i18n.format_month_year(self._calendar_year, self._calendar_month, self.language)
        weekday_labels = [i18n.t(key, self.language) for key in _CALENDAR_WEEKDAY_KEYS]

        # Same "skip re-render if nothing changed" dirty-check `_refresh_all`
        # already applies to the list view, and for the same reason: this
        # runs every second from the heartbeat while the calendar is on
        # screen, and `render_calendar` rebinds a fresh click-handler closure
        # onto every visible entry label each time it's called (see
        # `MainWindow._update_calendar_cell`). Repeated `.bind()` calls on
        # the same widget+sequence do NOT release the previous Tcl command
        # in this Tk/Python version -- verified directly, every prior
        # binding stays registered forever since these cell widgets are
        # never destroyed -- so calling `render_calendar` unconditionally on
        # every tick was an unbounded, per-second memory leak for as long as
        # the calendar view stayed open. The signature captures everything a
        # cell can visibly show (day/month membership/today-highlight/each
        # entry's id+time+title+color/overflow count) plus the month label
        # and language (weekday names and the "+N more" label are
        # translated), so any real display change still re-renders.
        signature = (
            self.language,
            month_label,
            tuple(
                (
                    cell.day,
                    cell.in_current_month,
                    cell.is_today,
                    tuple(
                        (e.meeting_id, e.time_text, e.title, e.color, e.series_occurrence_count)
                        for e in cell.entries
                    ),
                    cell.overflow_count,
                )
                for cell in cells
            ),
        )
        if signature != self._last_rendered_calendar_signature:
            self.view.render_calendar(month_label, weekday_labels, cells)
            self._last_rendered_calendar_signature = signature

    def _refresh_week(self, now: datetime, scroll_to_now: bool = False) -> None:
        """Build this heartbeat's display data for the weekly calendar view.
        Split into two independent dirty-checks, per SDD.md v2.9.0 decision
        #4 -- this is the load-bearing part of this whole feature, not a
        stylistic choice:

        `scroll_to_now` (v2.14.1) is a one-shot request, forwarded from
        `_refresh_all`, asking the view to re-center its scroll on "now" --
        see Nivel B's dirty-check below for why it must bypass that gate
        rather than just being an extra tuple element inside it.

        - Nivel A (`render_week_grid`): rebinds `.bind()` click handlers on
          all 168 cells, gated by `_last_rendered_week_signature`, which
          deliberately has NO hour/minute component. If the live time-line's
          per-minute movement were folded into this same signature, every
          minute would force a full `.bind()` rebind pass over 168 cells
          forever -- reintroducing, just 60x less often, the exact
          Tcl-command-leak class this codebase already found and fixed
          twice (`render_calendar`'s entry labels in v2.7.0,
          `_ScrollablePanel`'s `bind_all` in v2.8.0; see module-map.md).
        - Nivel B (`update_week_live_indicators`): only `.configure()`s the
          day-header colors and `.place()`s the time-line -- never
          `.bind()` -- so it's safe to re-apply up to once a real minute
          without any of that risk. Only called while `active_view ==
          "week"` (see `_refresh_all`), same guard `_refresh_calendar` uses.
        """
        days = recurrence.week_dates(self._week_anchor)
        grouped = _group_meetings_by_date(self.meetings)
        # Same live-sibling-count computation as `_refresh_calendar` -- see
        # that method's comment for why `meeting.seriesSize` itself isn't
        # trustworthy here (SDD.md v2.11.0). Deliberately not factored into
        # a shared helper (see the "no new public helper" note just below
        # for the per-hour grouping, same reasoning applies here).
        series_sizes = {sid: len(group) for sid, group in recurrence.group_meetings_by_series(self.meetings).items()}
        # Same redundant-but-cheap "compute fresh from self.meetings" pattern
        # `series_sizes` above already uses, applied to colors -- see
        # `_build_work_color_map`'s docstring.
        work_colors = _build_work_color_map(self._work_names())

        # Full-color meeting-block layer (SDD.md v2.16.0, replaces v2.15.0's
        # thin decorative bar): computed per VISIBLE day from ALL of that
        # day's meetings (`grouped`, never the hour-capped `hour_meetings`
        # below, which would silently under-count blocks for a busy day) --
        # cluster/lane/aggregate-chip logic is `_assign_week_meeting_blocks`'s
        # own responsibility, not a side effect of hour-cell text truncation.
        # Computed BEFORE the per-hour `cells` loop below (unlike v2.15.0's
        # ordering) for two reasons: (1) `covered_ids_by_day` lets that loop
        # filter out any meeting that already has its own block/aggregate
        # representation here -- SDD.md decision #7, the old per-hour text
        # list stops being this view's "source of truth for what meetings
        # exist" and becomes a rare fallback for the 13th+ meeting of an
        # already-extreme day; (2) `self.view.render_week_meeting_blocks(...)`
        # is called before `self.view.render_week_grid(...)` below so that,
        # by the time `render_week_grid` builds its own
        # "selection still visible?" backstop, `MainWindow` already has this
        # render's block data recorded and can fold block meeting ids into
        # that same check (see `render_week_grid`'s own docstring for why a
        # block-only selection would otherwise be wiped every render).
        meeting_blocks: List[WeekMeetingBlock] = []
        covered_ids_by_day: Dict[date, Set[str]] = {}
        for day_index, day in enumerate(days):
            day_blocks, covered_ids = _assign_week_meeting_blocks(
                day_index, grouped.get(day, []), series_sizes, work_colors
            )
            meeting_blocks.extend(day_blocks)
            covered_ids_by_day[day] = covered_ids

        # First level of grouping reuses `_group_meetings_by_date` (by
        # calendar date, across the whole app); the second level -- by hour
        # within that date -- is local to this view, per SDD.md (no new
        # public helper for it, same as `_refresh_calendar` doesn't factor
        # out its own per-day slicing/ordering/overflow counting either).
        meetings_by_day_and_hour: Dict[date, Dict[int, List[models.Meeting]]] = {}
        for day in days:
            by_hour: Dict[int, List[models.Meeting]] = {}
            for meeting in grouped.get(day, []):
                by_hour.setdefault(meeting.local_datetime().hour, []).append(meeting)
            meetings_by_day_and_hour[day] = by_hour

        cells: List[WeekCellData] = []
        for hour in range(24):
            for day in days:
                covered_ids = covered_ids_by_day.get(day, set())
                # SDD.md v2.16.0 decision #7: a meeting that already has a
                # real block or is folded into this day's aggregate "+N más"
                # chip is dropped from the plain hour-cell text entirely --
                # its own block/chip IS its visual representation now, and
                # showing it a second time here would just repeat the same
                # title (worse, at a stale start-time-only format) right
                # next to its own colored block. Only a meeting that got NO
                # representation at all above (only possible via the
                # independent `WEEK_MAX_DURATION_BLOCKS_PER_DAY` cap, an
                # already-extreme "12+ meetings this day" case) still
                # reaches this text list, exactly as it always has.
                hour_meetings = sorted(
                    (
                        m for m in meetings_by_day_and_hour[day].get(hour, [])
                        if m.id not in covered_ids
                    ),
                    key=_meeting_sort_key,
                )
                entries = [
                    CalendarEntry(
                        meeting_id=meeting.id,
                        # Start-time only -- deliberately NOT the month
                        # view's "HH:MM-HH:MM" range (SDD.md v2.15.0 decision
                        # #5, still true post-v2.16.0): this rarely-reached
                        # fallback text stays exactly as it always has.
                        time_text=meeting.local_datetime().strftime("%H:%M"),
                        title=meeting.title,
                        color=_work_block_color(meeting.workName, work_colors),
                        series_occurrence_count=(
                            series_sizes.get(meeting.seriesId, 0)
                            if meeting.recurrenceType != "none" and meeting.seriesId
                            else 0
                        ),
                        # Only real effect: keeps the Nivel A signature below
                        # honest -- `time_text` here never changes when only
                        # duration changes, unlike the month view's own
                        # range-text (see `CalendarEntry.duration_minutes`'s
                        # own docstring for why the two views differ).
                        duration_minutes=meeting.durationMinutes,
                    )
                    for meeting in hour_meetings[:WEEK_MAX_ENTRIES_PER_CELL]
                ]
                cells.append(
                    WeekCellData(
                        day=day,
                        hour=hour,
                        entries=entries,
                        overflow_count=max(0, len(hour_meetings) - WEEK_MAX_ENTRIES_PER_CELL),
                    )
                )

        week_range_label = i18n.format_week_range(days[0], days[-1], self.language)
        day_header_texts = [
            f"{i18n.t(key, self.language)} {day.day}" for key, day in zip(_CALENDAR_WEEKDAY_KEYS, days)
        ]

        # Nivel A's dirty-check -- see this method's docstring for why
        # hour/minute must never be part of this tuple. `meeting_blocks`'s
        # own tuple form is folded in here (not just `duration_minutes` on
        # each cell entry above) so a cluster/column re-assignment -- possible
        # even when no single meeting's own fields changed, e.g. an
        # overlapping sibling was deleted -- also triggers a fresh render.
        # Every field of `WeekMeetingBlock` is listed explicitly (SDD.md
        # v2.16.0 decision #11): a title-only edit (no time/duration change)
        # must still re-render that meeting's own block text.
        signature = (
            self.language,
            week_range_label,
            tuple(day_header_texts),
            tuple(
                (
                    cell.day,
                    cell.hour,
                    tuple(
                        (e.meeting_id, e.time_text, e.title, e.color, e.series_occurrence_count, e.duration_minutes)
                        for e in cell.entries
                    ),
                    cell.overflow_count,
                )
                for cell in cells
            ),
            tuple(
                (
                    b.day_index, b.column_index, b.column_count, b.start_hour_float, b.duration_minutes,
                    b.color, b.meeting_id, b.title, b.time_text, b.series_occurrence_count,
                    b.is_overflow, b.overflow_count, b.start_dt, b.end_dt,
                )
                for b in meeting_blocks
            ),
        )
        if signature != self._last_rendered_week_signature:
            # Block data recorded first -- see the comment above
            # `meeting_blocks`'s own computation for why `render_week_grid`
            # needs it already in place before it builds its own
            # selection-still-visible backstop.
            self.view.render_week_meeting_blocks(meeting_blocks)
            self.view.render_week_grid(week_range_label, day_header_texts, cells)
            self._last_rendered_week_signature = signature

        # Nivel B's dirty-check -- cheap to recompute every heartbeat (plain
        # date/int comparisons), but only actually touches widgets when this
        # tuple changes, which happens at most once a real minute while the
        # shown week is the current one. `today_index` is `None` whenever
        # the visible week is any week other than the real current one (see
        # SDD.md decision #5) -- unlike the month view, no separate
        # "showing_current_month"-style flag is needed here, because a
        # week's 7 days are never padded with days from a neighboring week,
        # so `now.date() in days` alone is already 100% correct.
        today_date = now.date()
        today_index = days.index(today_date) if today_date in days else None
        # Edge case found while designing the work-week toggle (SDD.md
        # v2.10.0): if today is a Saturday/Sunday AND the active mode is
        # "work" (those two columns collapsed to 0px), `today_index` would
        # otherwise still point at a real column index that just happens to
        # have no width -- `_apply_week_now_line` would then measure an
        # implausible width against a column that's *permanently* collapsed
        # (not the one-time cold-start delay its retry mechanism exists
        # for) and burn through all of its retries every time this fires,
        # never actually showing the line. Folding this into the same
        # `today_index = None` branch the "not the current week" case
        # already uses (SDD.md v2.9.0 decision #5) reuses that already-
        # proven "hide cleanly" path instead of adding a second one.
        if self.week_column_mode == "work" and today_date.weekday() >= 5:
            today_index = None
        live_state = (today_index, now.hour, now.minute)
        # `or scroll_to_now`: a real scroll-to-now request must always reach
        # `MainWindow.update_week_live_indicators` -- even on the (rare but
        # real) tick where `live_state` happens to already equal the last
        # one recorded, e.g. the user leaves and re-enters week view within
        # the same real minute. Without this, that request would be
        # silently swallowed by a dirty-check that exists to skip redundant
        # `.configure()`/`.place()` calls, not to gate a fresh user-intent
        # signal that carries no footprint of its own in `live_state`.
        if live_state != self._last_rendered_week_live_state or scroll_to_now:
            self.view.update_week_live_indicators(today_index, now.hour, now.minute, scroll_to_now=scroll_to_now)
            self._last_rendered_week_live_state = live_state

    def _find_meeting(self, meeting_id: str) -> Optional[models.Meeting]:
        return next((m for m in self.meetings if m.id == meeting_id), None)

    # -- user actions -------------------------------------------------------------

    def handle_save(self, payload: dict) -> None:
        error_key = models.validate_meeting(payload)
        if error_key:
            self.view.show_form_feedback(i18n.t(error_key, self.language), is_error=True)
            self.view.show_toast(i18n.t(error_key, self.language))
            return

        recurrence_type = models.normalize_recurrence_type(payload.get("recurrenceType"))
        time_value = str(payload.get("time") or "").strip()[:5]
        composed_datetime = f"{payload['date']}T{time_value}"
        meeting_id = str(payload.get("meetingId") or "").strip()

        # A work name typed directly into the combobox (not picked from the
        # list) becomes available for next time automatically -- the
        # explicit "Manage companies" dialog is for removing one, or adding
        # one without saving a meeting first.
        self._register_company(payload.get("workName", ""))

        if meeting_id:
            self._save_edit(meeting_id, payload, recurrence_type, composed_datetime)
        else:
            self._save_new(payload, recurrence_type, composed_datetime)

        self._refresh_all()

    def _save_edit(self, meeting_id: str, payload: dict, recurrence_type: str, composed_datetime: str) -> None:
        existing = self._find_meeting(meeting_id)
        if existing is None:
            self.view.show_form_feedback(i18n.t("saveError", self.language), is_error=True)
            return

        # Only the single occurrence being edited changes -- seriesId/
        # occurrenceIndex/seriesSize are left untouched, and both alert
        # flags reset so the edited timer fires its alerts again.
        existing.workName = security.clamp_text(payload.get("workName"), security.MAX_WORK_NAME_LENGTH)
        existing.title = security.clamp_text(payload.get("title"), security.MAX_TITLE_LENGTH)
        existing.datetime = composed_datetime
        existing.reminderMinutes = max(1, int(float(payload.get("reminderMinutes"))))
        existing.durationMinutes = min(
            models.MAX_DURATION_MINUTES,
            max(models.MIN_DURATION_MINUTES, int(float(payload.get("durationMinutes")))),
        )
        existing.soundProfile = models.normalize_sound_profile(payload.get("soundProfile"))
        existing.teamsUrl = security.clamp_text(payload.get("teamsUrl"), security.MAX_TEAMS_URL_LENGTH)
        existing.notes = security.clamp_text(payload.get("notes"), security.MAX_NOTES_LENGTH)
        existing.recurrenceType = recurrence_type
        existing.reminderSent = False
        existing.startSent = False
        existing.updatedAt = models.now_iso()

        self._persist(silent=False)
        self.view.clear_form()
        self.view.show_form_feedback(i18n.t("formUpdatedSingle", self.language))
        self.view.show_toast(i18n.t("updated", self.language))

    def _save_new(self, payload: dict, recurrence_type: str, composed_datetime: str) -> None:
        if recurrence_type == "none":
            occurrence_count = 1
        else:
            occurrence_count = max(1, min(52, int(float(payload.get("occurrenceCount") or 1))))
        series_id = models.new_id() if recurrence_type != "none" else ""
        base_date = datetime.strptime(composed_datetime, "%Y-%m-%dT%H:%M")

        created = []
        for index in range(occurrence_count):
            occurrence_date = recurrence.add_recurrence_to_date(base_date, recurrence_type, index)
            created.append(
                models.normalize_meeting(
                    {
                        "workName": payload.get("workName"),
                        "title": payload.get("title"),
                        "datetime": occurrence_date.strftime("%Y-%m-%dT%H:%M"),
                        "reminderMinutes": payload.get("reminderMinutes"),
                        "durationMinutes": payload.get("durationMinutes"),
                        "soundProfile": payload.get("soundProfile"),
                        "teamsUrl": payload.get("teamsUrl"),
                        "notes": payload.get("notes"),
                        "recurrenceType": recurrence_type,
                        "seriesId": series_id,
                        "occurrenceIndex": index + 1,
                        "seriesSize": occurrence_count,
                    }
                )
            )

        self.meetings.extend(created)
        self._persist(silent=False)
        self.view.clear_form()
        if occurrence_count > 1:
            message = i18n.format_text("formSavedSeries", self.language, count=occurrence_count)
        else:
            message = i18n.t("formSavedSingle", self.language)
        self.view.show_form_feedback(message)
        self.view.show_toast(i18n.t("saved", self.language) if occurrence_count == 1 else message)

    def handle_clear(self) -> None:
        self.view.clear_form()

    def handle_edit(self, meeting_id: str) -> None:
        meeting = self._find_meeting(meeting_id)
        if meeting is not None:
            self.view.populate_form(meeting)

    def handle_delete(self, meeting_id: str) -> None:
        removed = self._apply_meetings([m for m in self.meetings if m.id != meeting_id])
        if removed:
            self._persist(silent=False)
            self.view.show_toast(i18n.t("deleted", self.language))
            self._refresh_all()

    def handle_delete_series(self, meeting_id: str) -> None:
        """Removes EVERY occurrence sharing this meeting's `seriesId` --
        past and future, no anchor kept (SDD.md v2.11.0) -- unlike
        `retention.purge_stale_meetings`/`clear_past_meetings`, which always
        keep a series' latest occurrence so it doesn't silently stop
        reminding. This is the opposite: an explicit, one-shot user action
        to end the series entirely, so nothing is preserved on purpose.

        Goes through `_apply_meetings` exactly like `handle_delete` --
        removing 1 id or 8 ids in the same call is the same set-based diff
        either way, so there is no special-casing for a multi-record
        delete. This is also what makes the deletion tombstone-safe: without
        routing through `_apply_meetings`'s `_pending_deleted_ids`
        bookkeeping, a still-pending disk read from another OneDrive-synced
        machine would look identical to "that machine added these and we
        haven't seen them yet" and silently resurrect them on the next
        merge (the exact v2.3.0 bug this path exists to prevent).

        `not target.seriesId` is checked BEFORE the filter runs, not after
        -- this is the one guard that actually matters here, not a
        cosmetic nicety: every standalone (non-recurring) meeting has
        `seriesId == ""` by construction (see `_save_new`), so
        `m.seriesId != target.seriesId` with an empty `target.seriesId`
        would keep only the non-empty-`seriesId` meetings -- i.e. delete
        every standalone meeting in the app in one call. The menu that
        calls this already only offers "Eliminar serie completa" when
        `series_occurrence_count > 1` (which itself requires a non-empty,
        actively-recurring `seriesId`), so this is a second, defensive
        check, not the first line of defense.

        Deliberately filters by bare `seriesId` alone here, NOT also
        requiring `recurrenceType != "none"` the way the menu's own
        enablement check does -- see SDD.md's v2.11.0 section for the
        documented edge case this causes (a lagging occurrence whose own
        `recurrenceType` was individually edited to "none" via `_save_edit`
        stays deletable as part of the series from any OTHER sibling's
        menu, just not offered as a target to right-click itself): "sin
        rastro histórico" means a materialized occurrence of that series
        must not survive just because its own `recurrenceType` field was
        edited afterwards.
        """
        target = self._find_meeting(meeting_id)
        if target is None or not target.seriesId:
            return
        removed = self._apply_meetings([m for m in self.meetings if m.seriesId != target.seriesId])
        if removed:
            self._persist(silent=False)
            self.view.show_toast(i18n.format_text("deletedSeriesToast", self.language, count=removed))
            self._refresh_all()

    def handle_clear_past(self) -> None:
        """Manual "delete past events" button -- removes every past meeting
        across all work names right now (ignores the current filter and the
        automatic purge's grace period), but still keeps each recurring
        series' latest occurrence so it doesn't silently stop reminding."""
        removed = self._apply_meetings(retention.clear_past_meetings(self.meetings)[0])
        if removed:
            self._persist(silent=False)
            self.view.show_toast(i18n.format_text("clearPastToast", self.language, count=removed))
            self._refresh_all()
        else:
            self.view.show_toast(i18n.t("clearPastNone", self.language))

    def handle_open_link(self, meeting_id: str) -> None:
        meeting = self._find_meeting(meeting_id)
        if meeting is not None and security.is_http_url(meeting.teamsUrl):
            webbrowser.open(meeting.teamsUrl)
        else:
            self.view.show_toast(i18n.t("openTeamsUnavailable", self.language))

    def handle_test_sound(self, profile_id: str) -> None:
        self.alarms.test_play(profile_id)
        self.view.show_toast(i18n.t("soundPreviewReady", self.language))

    def handle_set_now(self) -> None:
        now = datetime.now()
        self.view.set_now_values(now.strftime("%Y-%m-%d"), now.strftime("%H:%M"))

    def handle_toggle_language(self) -> None:
        self.language = "en" if self.language == "es" else "es"
        # Merge into existing settings rather than overwrite: settings.json
        # also holds the company list (see storage.save_companies), and a
        # bare save_settings({"language": ...}) would silently wipe it out.
        settings = storage.load_settings()
        settings["language"] = self.language
        storage.save_settings(settings)
        self.view.apply_translations(self.language)
        self.alarms.set_base_title(i18n.t("appTitle", self.language))
        self.tray.set_tooltip(i18n.t("trayModeToast", self.language))
        self._refresh_all()

    def handle_test_notification(self) -> None:
        ok = notifications.notify(i18n.t("appTitle", self.language), i18n.t("soundPreviewReady", self.language))
        key = "notificationsGrantedToast" if ok else "notificationsDeniedToast"
        self.view.show_toast(i18n.t(key, self.language))

    def handle_filter_change(self, value: str) -> None:
        self.work_filter = value
        self._refresh_all()

    # -- company list ---------------------------------------------------------

    def _register_company(self, name: str) -> None:
        name = name.strip()
        if not name or any(c.lower() == name.lower() for c in self.companies):
            return
        self.companies.append(name)
        self.companies.sort(key=str.lower)
        storage.save_companies(self.companies)
        self.view.update_company_options(self.companies)

    def handle_add_company(self, name: str) -> None:
        name = security.clamp_text(name, security.MAX_WORK_NAME_LENGTH)
        if not name:
            self.view.show_toast(i18n.t("companyEmptyError", self.language))
            return
        if any(c.lower() == name.lower() for c in self.companies):
            self.view.show_toast(i18n.t("companyExistsError", self.language))
            return
        self.companies.append(name)
        self.companies.sort(key=str.lower)
        storage.save_companies(self.companies)
        self.view.update_company_options(self.companies)
        self.view.show_toast(i18n.t("companyAddedToast", self.language))

    def handle_remove_company(self, name: str) -> None:
        before = len(self.companies)
        self.companies = [c for c in self.companies if c.lower() != name.lower()]
        if len(self.companies) != before:
            storage.save_companies(self.companies)
            self.view.update_company_options(self.companies)
            self.view.show_toast(i18n.t("companyRemovedToast", self.language))

    # -- gadget mode ------------------------------------------------------------

    def handle_toggle_gadget_mode(self) -> None:
        # Refused while an alert is showing: not just belt-and-suspenders --
        # switching modes reskins the one real window (see
        # MainWindow.set_gadget_mode), and this guarantees that never happens
        # while an AlarmController Toplevel is up, rather than relying only on
        # its own grab_set() making the button physically unclickable.
        if self.alarms.is_active():
            self.view.show_toast(i18n.t("gadgetModeBlockedToast", self.language))
            return
        self.gadget_mode = not self.gadget_mode
        if self.gadget_mode:
            # Pass the last known width/height/theme too, not just position
            # -- otherwise toggling out of gadget mode (e.g. to edit a
            # meeting) and back in within the same session would silently
            # reset a resize/theme choice back to the hardcoded default,
            # even though `self._gadget_width`/`_height`/`_app_theme`
            # already remember it.
            self.view.set_gadget_mode(
                True, self._gadget_x, self._gadget_y, self._gadget_width, self._gadget_height, self._app_theme,
            )
        else:
            self._gadget_x, self._gadget_y = self.view.current_gadget_position()
            self.view.set_gadget_mode(False)
        self._save_theme_and_gadget_settings()
        self._refresh_all()

    def handle_set_app_theme(self, theme_key: str) -> None:
        """Renamed from `handle_set_gadget_skin` in v2.14.0 -- ONE handler
        now backs both theme-picker entry points (the gadget's own picker
        and the full window's header button, see `main_window.Callbacks`'s
        own `on_set_app_theme` comment), since choosing either sets the
        same underlying `appTheme` setting and re-themes the same one root
        window either way."""
        # Same guard/reasoning as `handle_toggle_gadget_mode`: the theme
        # button/menu stay visible (on the gadget, and now on the full
        # window's header too) while an alarm overlay is up, but must not
        # repaint the one shared root window out from under that overlay
        # mid-alert.
        if self.alarms.is_active():
            self.view.show_toast(i18n.t("gadgetModeBlockedToast", self.language))
            return
        self._app_theme = theme_key
        self.view.apply_theme(theme_key)
        # Forces the calendar/week views' own "skip re-render if nothing
        # changed" signatures (see `_refresh_calendar`/`_refresh_week`) --
        # and the meeting-list's equivalent, `_last_rendered_signature` --
        # to miss on the very next heartbeat tick, since none of those
        # signatures include the active theme. Without this, a theme
        # switch would recolor everything `MainWindow.apply_theme` reaches
        # directly, but the calendar/week grids' own per-cell colors
        # (`_update_calendar_cell`/`_update_week_cell`, which read the
        # module constants `apply_theme` just reassigned) and the meeting
        # cards (gated behind this same list signature) would keep
        # rendering with the OLD colors until something else unrelated
        # happened to change first. Resetting to `None` (not recomputing a
        # real one) is deliberate: it's a guaranteed one-time miss against
        # whatever the signature comparison is, cheaper than duplicating
        # each signature's own real construction here just to invalidate it.
        self._last_rendered_signature = None
        self._last_rendered_calendar_signature = None
        self._last_rendered_week_signature = None
        self._last_rendered_week_live_state = None
        self._refresh_all()
        self._save_theme_and_gadget_settings()

    def handle_gadget_resize(self, width: int, height: int) -> None:
        # No toast here, unlike the theme/mode-toggle guards above: a resize
        # is driven by the user's mouse on the grip, and an alarm overlay
        # taking over the root window mid-drag would already steal focus/
        # grab -- there's nothing useful to interrupt, so this just skips
        # persisting the in-progress size rather than nagging on every
        # release event.
        if self.alarms.is_active():
            return
        self._gadget_width, self._gadget_height = width, height
        self._save_theme_and_gadget_settings()

    def _save_theme_and_gadget_settings(self) -> None:
        """Renamed from `_save_gadget_settings` in v2.14.0 -- covers the
        broader `appTheme` concept now, not just gadget-specific settings;
        same load-full-dict/mutate-known-keys/save-full-dict merge
        discipline as before (see this project's own settings-merge
        guidance -- `save_settings` overwrites the whole file, so this must
        never be called with a partial dict)."""
        settings = storage.load_settings()
        settings["gadgetMode"] = self.gadget_mode
        if self._gadget_x is not None and self._gadget_y is not None:
            settings["gadgetX"] = self._gadget_x
            settings["gadgetY"] = self._gadget_y
        settings["appTheme"] = self._app_theme
        settings["gadgetWidth"] = self._gadget_width
        settings["gadgetHeight"] = self._gadget_height
        storage.save_settings(settings)

    # -- tray mode --------------------------------------------------------------

    def handle_enter_tray_mode(self) -> None:
        # Same guard as gadget mode, and for the same reason: this hides the
        # one real window entirely, which must never happen while an
        # AlarmController Toplevel is up.
        if self.alarms.is_active():
            self.view.show_toast(i18n.t("gadgetModeBlockedToast", self.language))
            return
        shown = self.tray.show(
            restore_label=i18n.t("trayShowMenuItem", self.language),
            exit_label=i18n.t("exitButton", self.language),
        )
        if not shown:
            # Never hide the window if the tray icon couldn't actually be
            # created -- that would strand the user with no visible UI and
            # no way back.
            self.view.show_toast(i18n.t("trayModeUnavailableToast", self.language))
            return
        self.tray_mode = True
        self.root.withdraw()

    def handle_restore_from_tray(self) -> None:
        if not self.tray_mode:
            return
        self.tray_mode = False
        self.tray.hide()
        self._force_show_window()

    # -- view switching (list / month / week) ------------------------------------

    def handle_set_active_view(self, view: str) -> None:
        # Replaces the old 2-way `handle_toggle_calendar_view` now that
        # List/Month/Week are three mutually exclusive named views (SDD.md
        # v2.9.0) -- every view-switch button in every header (see
        # `_build_header` in main_window.py) calls this directly with its
        # own target name instead of sharing one ambiguous toggle. Unlike
        # gadget/tray mode, this isn't blocked while an alarm is active: all
        # three views live inside the same normal, decorated root window, so
        # switching between them can never interfere with AlarmController's
        # independent Toplevel overlay.
        # Auto-scroll-to-now (v2.14.1): only a real transition INTO week view
        # from somewhere else counts -- checked against the OLD value,
        # before it's overwritten below. Week view's own header never
        # offers "week" as a target (see `_build_week_view`), so in
        # practice `self.active_view` is never already "week" here, but the
        # explicit check keeps this correct even if that ever changes,
        # instead of quietly re-centering the scroll on every redundant
        # same-view call.
        entering_week = view == "week" and self.active_view != "week"
        self.active_view = view
        self.view.set_active_view(view)
        if entering_week:
            self._week_scroll_to_now_requested = True
        self._refresh_all()

    # -- calendar view ----------------------------------------------------------

    def handle_calendar_prev_month(self) -> None:
        self._calendar_year, self._calendar_month = _shift_month(self._calendar_year, self._calendar_month, -1)
        self._refresh_all()

    def handle_calendar_next_month(self) -> None:
        self._calendar_year, self._calendar_month = _shift_month(self._calendar_year, self._calendar_month, 1)
        self._refresh_all()

    def handle_calendar_today(self) -> None:
        now = datetime.now()
        self._calendar_year, self._calendar_month = now.year, now.month
        self._refresh_all()

    def handle_calendar_day_click(self, day: date) -> None:
        # Thin by design (SDD.md v2.8.0): no business logic here, no
        # `self.meetings` mutation -- the real creation still happens only
        # when the user submits the normal form via `handle_save`/`_save_new`.
        self.view.prefill_new_meeting(day)

    # -- weekly calendar view -----------------------------------------------------

    def handle_week_prev(self) -> None:
        self._week_anchor -= timedelta(weeks=1)
        self._refresh_all()

    def handle_week_next(self) -> None:
        self._week_anchor += timedelta(weeks=1)
        self._refresh_all()

    def handle_week_today(self) -> None:
        self._week_anchor = datetime.now().date()
        # Auto-scroll-to-now (v2.14.1): the user explicitly asked to see
        # "now" again, same intent as a fresh entry into week view -- see
        # `handle_set_active_view`'s own comment for why this is a one-shot
        # request flag, not a standing state.
        self._week_scroll_to_now_requested = True
        self._refresh_all()

    def handle_week_slot_click(self, day: date, hour: int) -> None:
        # Thin by design, same as `handle_calendar_day_click`: no business
        # logic here, no `self.meetings` mutation.
        self.view.prefill_new_meeting(day, hour)

    def handle_toggle_week_column_mode(self) -> None:
        """Work-week (Mon-Fri) / full-week (Mon-Sun) toggle for the week
        view (SDD.md v2.10.0) -- purely a display preference, persisted the
        same read-merge-write way `language`/`gadgetMode` already are
        (never a partial `save_settings()` call, which would silently wipe
        out the other keys in `settings.json`)."""
        self.week_column_mode = "full" if self.week_column_mode == "work" else "work"
        settings = storage.load_settings()
        settings["weekColumnMode"] = self.week_column_mode
        storage.save_settings(settings)
        self.view.set_week_column_mode(self.week_column_mode)
        self._refresh_all()
