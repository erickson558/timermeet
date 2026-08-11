"""Main window: header (title/version/storage/donation/language), the
meeting form, and the summary panel (stats + filter + meeting list).

This module is a view layer only -- all business logic (validation,
persistence, filtering, stats, alarm firing) lives in ``app.py``; here we just
build widgets, expose update/render methods, and forward user actions through
a `Callbacks` bundle. Field layout, labels, and actions mirror
``legacy-php/index.php``.

Built entirely with plain ``tkinter``/``ttk`` widgets, not CustomTkinter.
CustomTkinter's rounded-corner widgets each defer a PIL-based image render
until Tk's idle queue is flushed -- for this window's ~80-100 widgets
(header + form + summary panel + every meeting card), that first flush
measured 10-25+ seconds on ordinary hardware, during which the window looked
completely blank/frozen. Plain widgets pay none of that cost. The dark color
palette below is hand-picked to keep a similar look to the original
CustomTkinter design; see MEMORY/SDD for the tradeoff this was worth making.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import tkinter.messagebox as messagebox
import webbrowser
from dataclasses import dataclass, field
from datetime import date, datetime
from tkinter import ttk
from typing import Callable, Dict, List, Optional, Tuple

from . import __version__, i18n, models, security

DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=ZABFRXC2P3JQN"

WINDOW_BG = "#15171c"
PANEL_BG = "#1c1f26"
FIELD_BG = "#252a33"
BORDER = "#333844"
TEXT = "#f2f3f5"
MUTED = "#9aa1ac"
SUBTLE = "#767d88"
ACCENT = "#3b82f6"
ACCENT_HOVER = "#2563eb"
ACCENT_FG = "#ffffff"
GHOST_BG = "#2a2e37"
GHOST_HOVER = "#343a45"
GHOST_FG = "#f2f3f5"
DANGER = "#b91c1c"
DANGER_HOVER = "#991b1b"
CHIP_BG = "#2a2e37"
GOLD_BG = "#f2c14e"
GOLD_HOVER = "#e0ad33"
GOLD_FG = "#402d00"

FONT_FAMILY = "Segoe UI"

# Gadget/skin mode: a small borderless always-on-top panel (see
# `set_gadget_mode`), sized to fit a clock + one status line with a comfortable
# margin above the Windows taskbar (winfo_screenheight() doesn't exclude it).
GADGET_WIDTH = 280
GADGET_HEIGHT = 130
GADGET_MARGIN_X = 24
GADGET_MARGIN_BOTTOM = 60

_CARD_PALETTE = {
    "card_bg": "#20242c",
    "chip_bg": CHIP_BG,
    "status_bg": "#2f3440",
    "title_fg": TEXT,
    "muted_fg": MUTED,
    "recurrence_fg": SUBTLE,
    "button_bg": ACCENT,
    "button_hover": ACCENT_HOVER,
    "button_fg": ACCENT_FG,
    "ghost_bg": GHOST_BG,
    "ghost_hover": GHOST_HOVER,
    "ghost_fg": GHOST_FG,
    "danger_bg": DANGER,
    "danger_hover": DANGER_HOVER,
    "danger_fg": "#ffffff",
}

# A meeting card's actual content (color chip + title + one countdown/
# recurrence line + 3 action buttons) never needs more than ~400-500px --
# measured growing unbounded from a reasonable 308px at the app's 960px
# minsize floor up to 1084px on a 1920px-wide monitor, which reads as
# sparse/broken rather than adapting well. Passed as `_ScrollablePanel`'s
# `max_content_width` for the meeting-list panel only (see `_build_summary`)
# -- the meeting-form panel's own `_ScrollablePanel` is intentionally left
# uncapped, it was never part of this bug. Left-aligned rather than
# centered: simplest change that satisfies the requirement (no need to also
# reposition the canvas window's x-coordinate), and it keeps the list's left
# edge lined up with the panel's other left-aligned content (stats cards,
# filter row) above it.
MEETING_CARD_MAX_WIDTH_PX = 760

# `title_label`'s own `.grid(padx=...)` inside a meeting card (see
# `_create_card`) -- pulled out as a named constant because
# `_on_meeting_list_width_change` needs the exact same number to compute
# how much of the card's width is actually available to the title text
# itself once this padding is subtracted. A second-round adversarial review
# found that capping the card's width above (`MEETING_CARD_MAX_WIDTH_PX`)
# shrank a title's available room from as much as ~1060px (old, uncapped,
# on a 1920px monitor) down to ~736px (760 minus this padding twice) with
# no wrap/truncation to match -- a 90-character title (well under
# `security.MAX_TITLE_LENGTH=120`) that used to always fit now silently
# clipped mid-character. See `_on_meeting_list_width_change` for the fix.
_CARD_TITLE_PADX = 12

_SOUND_LABEL_KEYS = [
    ("soft", "soundSoft"),
    ("urgent", "soundUrgent"),
    ("alarm", "soundAlarm"),
    ("siren", "soundSiren"),
    ("fire", "soundFireSiren"),
]

# The gadget's next-alert label wraps but never scrolls in its fixed 130px
# height; the strip+clock above already claim most of that, leaving room for
# only ~2 short lines before text would clip against the window's bottom edge.
_GADGET_ALERT_MAX_CHARS = 72


def _truncate_for_gadget(text: str) -> str:
    if len(text) <= _GADGET_ALERT_MAX_CHARS:
        return text
    return text[: _GADGET_ALERT_MAX_CHARS - 1].rstrip() + "…"


# Monthly calendar view (v2.7.0): a day cell shows at most this many meeting
# rows before the rest collapse into a non-interactive "+N más"/"+N more"
# label (see SDD.md's calendar view requirements) -- 3 is the count the spec
# settled on, and this constant is the single source of truth for both the
# eager cell construction below and app.py's `_refresh_calendar`, which must
# slice `day_meetings[:3]` the same way.
CALENDAR_MAX_ENTRIES_PER_CELL = 3
CALENDAR_ROWS = 6
CALENDAR_COLS = 7

# A calendar cell is much narrower than a full meeting card, so its "HH:MM
# Title" entry line needs its own, tighter truncation budget. Empirically
# measured (see the v2.7.0 fix in SDD.md) against the app's own declared
# floor -- root.minsize(960, 640) -- with every one of the 42 cells holding
# realistic titles: 24 clipped (a "Weekly Team Standup" entry rendered at
# 149px inside a 130px column), 20 did not, across repeated measurements.
# This constant is NOT re-derived per window size (deliberately -- see the
# fix's rationale for staying a fixed count instead of a dynamic
# width-measurement system), so it must keep fitting at that same 960px
# floor even though most launches default to the wider 1180px window.
_CALENDAR_ENTRY_MAX_CHARS = 20


def _truncate_calendar_entry(text: str) -> str:
    if len(text) <= _CALENDAR_ENTRY_MAX_CHARS:
        return text
    return text[: _CALENDAR_ENTRY_MAX_CHARS - 1].rstrip() + "…"


# Weekly calendar view (v2.9.0): 24 hour-rows x 7 day-columns, reusing
# `CalendarEntry` for each hour-cell's up-to-2 meeting rows -- see SDD.md's
# v2.9.0 section for the full design (the hour-axis-scrolls-with-the-grid
# decision, the Nivel A/Nivel B split for the live time-line, etc.).
WEEK_ROWS = 24
WEEK_COLS = 7
# 0-based column index within WEEK_COLS (Monday=0, per `week_dates`'s own
# `firstweekday=0` convention) -- the two columns "work-week" mode (v2.10.0)
# hides. Named rather than inlined so `set_week_column_mode` and any future
# reader don't have to re-derive "5 and 6 mean Saturday/Sunday" from bare
# integers.
_WEEKEND_COLUMN_INDICES = (5, 6)
# 2, not the month view's 3: an hour-row is much shorter than a full day
# cell (see SDD.md decision #7) -- deliberately lower, not a copy-paste of
# CALENDAR_MAX_ENTRIES_PER_CELL.
WEEK_MAX_ENTRIES_PER_CELL = 2
# SDD.md's starting point was 48px ("comfortable for 2 lines of text"), but
# a cell can show 3 lines at once -- 2 entries (WEEK_MAX_ENTRIES_PER_CELL)
# PLUS the "+N más" overflow row underneath them, all three simultaneously
# whenever an hour has more meetings than fit. Measured empirically against
# a real widget tree: 3 stacked 8pt entry/overflow labels need ~65px, so
# 48px would silently clip the overflow row in a busy hour. This matters
# more here than it would elsewhere in the app: `grid_rowconfigure(...,
# minsize=...)` is only a MINIMUM -- Tk's grid never shrinks a row below
# its widest/tallest current content -- so an under-sized constant wouldn't
# just clip text, it would silently grow THAT row taller than every other
# row, breaking the live time-line's pure-arithmetic Y math (SDD.md
# decision #3), which assumes every row is exactly this many pixels tall.
# 70px keeps a small margin above the measured 67px true minimum (content
# height + this cell's own `pady`) for minor cross-environment font-metric
# variance (ClearType/DPI settings).
WEEK_ROW_HEIGHT_PX = 70
# Wide enough for "23:00" at 9pt plus the small trailing padx this column
# already gets in `_build_week_view` -- measured against the app's declared
# floor (root.minsize(960, 640), same floor `_CALENDAR_ENTRY_MAX_CHARS` was
# measured against) so the axis never clips even at that minimum width.
HOUR_AXIS_WIDTH_PX = 56
# `tk.Scrollbar`'s own default width on Windows -- reserved as a spacer in
# the day-header row (built OUTSIDE the `_ScrollablePanel`, per SDD.md
# decision #2) so its 7 day columns keep lining up with the scrollable
# grid's day columns underneath, which lose this same width to their own
# vertical scrollbar.
_WEEK_SCROLLBAR_SPACER_PX = 17
# A week's day column is narrower than a month cell's (the day column here
# also gives up room to the hour axis + scrollbar spacer, see above), so the
# month view's 20-char budget does not transfer without remeasuring -- and
# this grid has a sharper failure mode than the month view's if it's picked
# wrong: all 24 hour-rows share the SAME 7 day-columns, and Tk's grid only
# distributes *extra* space via `weight=1` -- it never shrinks a column
# below the widest content currently inside it. One single un-truncated
# long title in any ONE of the 168 cells would widen that whole column
# (every other hour in that day, not just that one cell), silently
# distorting all 7 columns' proportions. Measured empirically at this app's
# 960px minsize floor (same floor `_CALENDAR_ENTRY_MAX_CHARS` was measured
# against) with every cell otherwise blank: each day column's "fair share"
# width was ~120px, and font.measure() against that budget (minus the
# label's own padx margins) found 19 characters as the true fit limit for a
# representative long title. 16 keeps a deliberate margin below that
# measured limit -- smaller than the month view's own margin (24 clipped,
# 20 fits), on purpose, given the column-wide-distortion risk above.
_WEEK_ENTRY_MAX_CHARS = 16
# Distinct from every other color in the palette on purpose (see SDD.md
# decision #3): not ACCENT (already means "today"/primary action) and not
# DANGER (already means "destructive"), so the live time-line reads as its
# own, unambiguous "this is where 'now' is" signal.
NOW_LINE_COLOR = "#22c55e"
# A user confirmed (screenshot + follow-up, v2.11.2) that the line alone --
# at its original 2px height -- read as a stray/misaligned grid line rather
# than a deliberate "current time" marker, even though a pixel-measurement
# investigation proved the grid itself has zero misalignment. Two purely
# visual (no geometry/logic) fixes, matching how Outlook/Teams/Google
# Calendar all mark "now": a thicker line, and a small filled dot at the
# line's left end (see `_week_now_dot` below) so the combination reads
# unambiguously as a marker, not a grid artifact.
NOW_LINE_HEIGHT_PX = 3
# Diameter of the small circular "now" marker placed at the live line's left
# edge (`_week_now_dot`, built once in `_build_week_view`, alongside the line
# it accompanies). Deliberately small -- just enough to read as a dot next to
# the hour axis without crowding it or overlapping into the next row.
NOW_LINE_DOT_DIAMETER_PX = 10
# See `MainWindow._apply_week_now_line`'s docstring: a real day column can
# never legitimately be narrower than ~120px at this app's 960px minsize
# floor, but a just-`.grid()`ed cell's pre-layout width measured as low as
# ~18px before Tk finished a real geometry pass -- this sits with margin
# between the two, used to detect "not really laid out yet" without
# assuming the stale value is always exactly the same number.
_WEEK_LINE_MIN_PLAUSIBLE_WIDTH_PX = 80
# Defense-in-depth cap on `_apply_week_now_line`'s self-reschedule (see its
# docstring): the cold-start width delay it works around resolves within
# ~1.5s in every empirical measurement, so 20 retries at the 300ms interval
# below (6s total) is a >3x margin above that -- generous enough to never
# fire under real conditions, but a hard ceiling so a future window state
# that genuinely never resolves can't retry unconditionally forever even if
# the active-view checks elsewhere in this method somehow have a gap.
_WEEK_LINE_MAX_RETRIES = 20


def _truncate_week_entry(text: str) -> str:
    if len(text) <= _WEEK_ENTRY_MAX_CHARS:
        return text
    return text[: _WEEK_ENTRY_MAX_CHARS - 1].rstrip() + "…"


def _truncate_text_to_pixel_width(text: str, font: "tkfont.Font", max_width_px: int) -> str:
    """Ellipsis truncation measured in real pixels via `font.measure()` --
    the same metric Tk itself uses to lay out a Label -- rather than a
    fixed character-count budget like `_truncate_calendar_entry`/
    `_truncate_week_entry` above. Those two can get away with a static
    character count because their available width is a fixed pixel column
    that never changes at runtime; the header subtitle's available width
    (see `MainWindow._update_header_subtitle`) changes on every window
    resize, so a single hardcoded character count can't stay correct across
    this app's whole 960px-1920px supported range. Binary search over
    `text`'s length rather than a linear scan: this runs on every header
    resize (debounced, but still potentially every live-drag frame), and
    `font.measure()` is a real Tcl round-trip, not free.

    Returns `""` (never a bare, unindicated `"…"` or worse) if not even the
    ellipsis itself fits `max_width_px` -- callers treat an empty result as
    "hide the subtitle at this width" per this app's own acceptance
    criterion (show fully, show truncated-with-ellipsis, or hide -- never a
    silent raw clip)."""
    if max_width_px <= 0:
        return ""
    if font.measure(text) <= max_width_px:
        return text
    ellipsis = "…"
    if font.measure(ellipsis) > max_width_px:
        return ""
    low, high, best = 0, len(text), ""
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid].rstrip() + ellipsis
        if font.measure(candidate) <= max_width_px:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best


# Header action-row spacing (see `_build_header`): measured empirically
# against a real widget tree (960px through 1920px, all three header
# instances) that the *default* `_button` padding (12px internal + 4px pack
# gap) made this row's 8 buttons (Notificar/Idioma/up to 2 view-switch/
# Gadget/Bandeja/Donar/Salir) require ~1040-1065px total -- more than the
# app's own declared floor, `root.minsize(960, 640)` (v2.4.0), which a
# completely ordinary action (Windows' Win+Left/Right half-screen Snap on any
# 1920px-wide monitor) lands on directly. Because `header`'s grid gives
# column 0 (title/subtitle/chips) the only nonzero weight and leaves this
# actions column at weight 0, Tk's grid always honors a 0-weight column's
# full requested size first and shrinks the weighted column to absorb any
# deficit (down to 0 if needed) -- so at 960px the *buttons* never actually
# shrink; they get laid out at their full width starting from wherever
# column 0 was compressed to, which pushes the rightmost ones (Donar, Salir)
# past the window's real right edge, off-screen and unclickable.
#
# SECOND ROUND (see `_header_title_column_minsize`): a follow-up adversarial
# review found that the first-round fix above -- correct on its own terms --
# left column 0 with no *floor*, so at that same 960px width Tk was free to
# compress it all the way down to ~1px, taking the app's own name
# ("TimerMeet", `title_label`) down with it. Giving column 0 a real
# `grid_columnconfigure(minsize=...)` floor fixes that (see
# `_build_header`), but empirically (real `tk.Tk()`, no mocks, this row's
# actual widgets) a hard floor for the title and this row's *first-round*
# footprint do not both fit inside the ~928px a 960px window actually gives
# `header` (960 minus `full_view`'s own 16px outer padding on each side):
# even shaved to the bone (2px button padding, 0px gaps) this row measured
# ~777-799px, and `title_label` alone needs ~198px (170px text at its real
# 24pt bold font + `title_box`'s own 28px padding) on top of that -- ~50-70px
# more than the ~928px available, regardless of how tight the padding gets.
# This isn't a padding problem: it's this row's Spanish button *text* itself
# (`i18n.DEFAULT_LANGUAGE`) -- "Probar notificación nativa" + up to 2
# view-switch labels + "Modo gadget" + "Bandeja" + "Cómprame una cerveza" +
# "Salir", the worst case being the list/week headers' 8-button row --
# already measuring ~695-717px on its own, un-padded.
#
# Closing that remaining gap needed one more lever: `_HEADER_BUTTON_FONT_SIZE`
# below drops this row's own font from `_button`'s app-wide default (11pt)
# to 9pt -- still comfortably legible, and matching this app's own existing
# precedent for secondary UI text at a similarly small size (the version/
# storage chips at 10pt, calendar/week entry labels at 8pt, see
# `_CALENDAR_ENTRY_MAX_CHARS`'s neighborhood above) -- scoped to *only* this
# row via `_button`'s new `font_size` parameter, so every other `_button()`
# call site in this file (meeting cards, month/week nav, the form) stays at
# 11pt, unaffected. That plus the tighter spacing constants below measured
# the worst case (`es`, list header) down to ~691px, leaving a verified
# ~237px for column 0 at the 960px floor -- comfortably more than
# `title_label`'s ~198px full-fidelity need, with real margin left over for
# cross-environment font-metric variance (ClearType/DPI settings).
_HEADER_BUTTON_PADX = 4
_HEADER_BUTTON_GAP_PX = 1
_HEADER_ACTIONS_OUTER_PADX = 4
_HEADER_EXIT_SPACER_PX = 4
_HEADER_BUTTON_FONT_SIZE = 9

# `title_box`'s own external padding (see `_build_header`'s `.grid(padx=...)`
# call) -- pulled out as a named constant because `_header_title_column_minsize`
# below needs the exact same number to compute column 0's floor (title's own
# natural text width alone isn't enough; this padding is real space Tk
# reserves around it inside the column).
_HEADER_TITLE_BOX_PADX = 14
# Safety margin added on top of `title_label`'s measured natural width when
# computing column 0's `minsize` (see `_header_title_column_minsize`) --
# covers small cross-machine font-metric rounding (ClearType/DPI) without
# eating meaningfully into the ~27px of slack the header-row changes above
# leave at the 960px floor (see that comment block for the real numbers).
_HEADER_TITLE_MIN_MARGIN_PX = 12
# Trimmed off the *end* of the available width when truncating the header
# subtitle (see `MainWindow._update_header_subtitle`) so the ellipsis never
# sits flush against the header's own edge -- small and purely cosmetic,
# unlike `_HEADER_TITLE_MIN_MARGIN_PX` above, which protects a hard
# never-clip guarantee.
_HEADER_SUBTITLE_SAFETY_MARGIN_PX = 4
# `_update_header_subtitle`'s guard against measuring against a header that
# hasn't had a real layout pass yet (either pre-`mainloop()`, or because it
# belongs to a primary view that isn't the active one -- see that method's
# docstring). A real header can never legitimately be narrower than this at
# the app's own 960px `minsize` floor; a header that hasn't been through a
# real layout pass yet reports Tk's pre-layout default instead (effectively
# 1px), well below it -- mirrors `_WEEK_LINE_MIN_PLAUSIBLE_WIDTH_PX`'s
# identical reasoning for the week view's own cold-start delay.
_HEADER_SUBTITLE_MIN_PLAUSIBLE_WIDTH_PX = 100

_RECURRENCE_LABEL_KEYS = [
    ("none", "recurrenceNone"),
    ("daily", "recurrenceDaily"),
    ("weekdays", "recurrenceWeekdays"),
    ("weekly", "recurrenceWeekly"),
    ("biweekly", "recurrenceBiweekly"),
    ("monthly", "recurrenceMonthly"),
]


@dataclass
class MeetingCardData:
    meeting: models.Meeting
    status_key: str
    countdown_text: str
    recurrence_text: str
    color: str


@dataclass
class _CardWidgets:
    frame: tk.Frame
    work_label: tk.Label
    status_label: tk.Label
    title_label: tk.Label
    detail_label: tk.Label


@dataclass
class CalendarEntry:
    """One meeting row inside a calendar day-cell -- already formatted/
    pre-colored by app.py (the color reuses `_color_for_work_name`, the same
    helper the list view's cards use), so this module stays display-only.

    `series_occurrence_count` (SDD.md v2.11.0): `0` if this entry isn't (or
    is no longer, see the `recurrenceType`-edited-to-"none" edge case in
    SDD.md) part of an active recurring series; otherwise the real number of
    live siblings sharing its `seriesId` this same refresh, computed once
    per refresh in `app.py` via `recurrence.group_meetings_by_series` --
    deliberately NOT `meeting.seriesSize`, which `retention.py` never
    decrements on a partial purge and so can be stale/inflated. `>= 2`
    enables "Eliminar serie completa" in the context menu; `0` or `1`
    doesn't. Never persisted -- presentation data only, recomputed every
    refresh."""

    meeting_id: str
    time_text: str
    title: str
    color: str
    series_occurrence_count: int = 0


@dataclass
class CalendarCellData:
    day: date
    in_current_month: bool
    is_today: bool
    entries: List[CalendarEntry]
    overflow_count: int


@dataclass
class _CalendarCellWidgets:
    frame: tk.Frame
    day_label: tk.Label
    entry_labels: List[tk.Label]
    overflow_label: tk.Label
    # Tracks the funcid the most recent `.bind()` call returned for each
    # rebound widget+sequence pair on this cell, so the NEXT real re-render
    # can release the PREVIOUS Tcl command first via `_rebind()` (see that
    # function's docstring, and module-map.md's "Recurring footgun" note --
    # this cell's `day_label`/`frame`/`entry_labels` are long-lived widgets
    # tied to a fixed grid *position*, rebound with a fresh closure every
    # real render). Keys are short, stable labels ("day_left", "day_right",
    # "frame_left", "frame_right", "entry_left_0", "entry_right_0", ...)
    # rather than one dataclass field per widget+sequence pair.
    bind_funcids: Dict[str, Optional[str]] = field(default_factory=dict)


@dataclass
class WeekCellData:
    """One hour-cell's worth of display data for the weekly calendar view
    (see SDD.md v2.9.0) -- reuses `CalendarEntry` unchanged (same
    `time_text`/`title`/`color`/`meeting_id` shape the month view already
    uses), just grouped by (day, hour) instead of by day alone."""

    day: date
    hour: int
    entries: List[CalendarEntry]
    overflow_count: int


@dataclass
class _WeekCellWidgets:
    """No `day_label` here (unlike `_CalendarCellWidgets`) -- a week cell's
    day identity lives in the one fixed day-header row above the scrollable
    grid, not repeated in each of that column's 24 hour-cells."""

    frame: tk.Frame
    entry_labels: List[tk.Label]
    overflow_label: tk.Label
    # Same funcid-tracking purpose as `_CalendarCellWidgets.bind_funcids`
    # above -- see `_rebind()`'s docstring.
    bind_funcids: Dict[str, Optional[str]] = field(default_factory=dict)
    # Parallel to `entry_labels` (SDD.md v2.11.0): which `meeting_id`, if
    # any, each entry slot is currently showing -- `None` for an unused
    # slot. Needed because the week-view selection highlight is applied
    # through two independent paths (the immediate click handler and
    # `_update_week_cell`'s render-time fallback, see
    # `_apply_week_selection_highlight`) that must agree on which widget
    # currently represents which meeting.
    entry_meeting_ids: List[Optional[str]] = field(default_factory=list)


@dataclass
class _HeaderWidgets:
    """Widget handles for one instance of the shared header (see
    `_build_header`) -- `full_view`, `calendar_view`, and `week_view` each
    get their own instance, so `apply_translations`/`update_storage_status`
    must loop over every entry in `MainWindow._headers` instead of assuming
    a single set of header widgets exists.

    `view_switch_buttons` replaces what used to be a single
    `calendar_toggle_button`/`calendar_toggle_key` pair now that List/Month/
    Week are three mutually exclusive named views instead of a 2-way toggle
    (SDD.md v2.9.0) -- each header gets up to 2 "go to view X" buttons
    (never a 1-button cycle, which can't unambiguously represent 3
    destinations), so this is a list of (button, i18n key) pairs instead of
    one of each.

    `header_frame`/`actions_frame` and `subtitle_truncate_job` exist purely
    for `MainWindow._update_header_subtitle`'s dynamic ellipsis truncation
    (see that method and `_schedule_subtitle_update`) -- `header_frame` is
    read for its real current width, `actions_frame` for its (effectively
    fixed, 0-weight) footprint, and `subtitle_truncate_job` is this specific
    header instance's own `after_idle` debounce handle, mirroring
    `_ScrollablePanel`'s `_canvas_width_job` pattern. Kept per-instance
    (not a single `MainWindow`-level attribute) for the same reason
    everything else here is: three header instances exist, each resizing
    independently.
    """

    title_label: tk.Label
    subtitle_label: tk.Label
    version_chip: tk.Label
    storage_chip: tk.Label
    notify_button: tk.Button
    language_button: tk.Button
    view_switch_buttons: List[Tuple[tk.Button, str]]
    gadget_button: tk.Button
    tray_button: tk.Button
    donate_button: tk.Button
    exit_button: tk.Button
    header_frame: tk.Frame
    actions_frame: tk.Frame
    subtitle_truncate_job: Optional[str] = None


@dataclass
class Callbacks:
    on_save: Callable[[dict], None]
    on_clear: Callable[[], None]
    on_edit: Callable[[str], None]
    on_delete: Callable[[str], None]
    on_open_link: Callable[[str], None]
    on_test_sound: Callable[[str], None]
    on_set_now: Callable[[], None]
    on_toggle_language: Callable[[], None]
    on_test_notification: Callable[[], None]
    on_filter_change: Callable[[str], None]
    on_clear_past: Callable[[], None]
    on_exit: Callable[[], None]
    on_add_company: Callable[[str], None]
    on_remove_company: Callable[[str], None]
    on_toggle_gadget_mode: Callable[[], None]
    on_enter_tray_mode: Callable[[], None]
    on_set_active_view: Callable[[str], None]
    on_calendar_prev_month: Callable[[], None]
    on_calendar_next_month: Callable[[], None]
    on_calendar_today: Callable[[], None]
    on_calendar_day_click: Callable[[date], None]
    on_week_prev: Callable[[], None]
    on_week_next: Callable[[], None]
    on_week_today: Callable[[], None]
    on_week_slot_click: Callable[[date, int], None]
    on_toggle_week_column_mode: Callable[[], None]
    on_delete_series: Callable[[str], None]


def _button(
    parent, text: str, command, bg: str, fg: str, hover: Optional[str] = None,
    padx: int = 12, pady: int = 6, font_size: int = 11, **extra,
) -> tk.Button:
    hover = hover or bg
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
        relief="flat", borderwidth=0, padx=padx, pady=pady, cursor="hand2", font=(FONT_FAMILY, font_size), **extra,
    )
    # `str(btn["state"])` check (SDD.md v2.11.0): the week-view toolbar's
    # "Editar"/"Eliminar" buttons are this file's first use of
    # `state="disabled"` on a `tk.Button` (see
    # `_update_week_toolbar_button_states`) -- without this guard, a
    # disabled button still lit up on hover even though its `command`
    # can't fire, a visual inconsistency nobody had reason to hit before
    # now. `<Leave>` needs no matching check: always restoring the base
    # color is correct regardless of state.
    btn.bind("<Enter>", lambda _e: btn.configure(bg=hover) if str(btn["state"]) != "disabled" else None)
    btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
    return btn


def _entry(parent, **extra) -> tk.Entry:
    return tk.Entry(
        parent, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
        font=(FONT_FAMILY, 11), **extra,
    )


def _rebind(widget: tk.Widget, sequence: str, handler: Callable, previous_funcid: Optional[str]) -> str:
    """Rebinds `sequence` on `widget` to a fresh `handler`, releasing the
    Tcl command a PREVIOUS `.bind()` call on this same widget+sequence
    registered first -- see module-map.md's "Recurring footgun" note.

    This is the fix for a real, confirmed leak in `_update_calendar_cell`/
    `_update_week_cell`: those two functions rebind a fresh closure onto
    long-lived cell widgets on every real re-render (a month/week
    navigation, an edit, a language toggle -- gated behind app.py's own
    dirty-check signature, so this never runs on an unchanged heartbeat
    tick). Being *gated* only stops WASTED rebinds when nothing changed;
    it does nothing about the Tcl command a real, correctly-triggered
    rebind leaves behind. On this Tk/Python version, calling `.bind()`
    again on the same widget+sequence replaces which callback *fires* but
    never releases the previous callback's underlying Tcl command --
    confirmed empirically (500 rebinds via plain `.bind()`, no release: the
    real interpreter-wide command count, `info commands`, grew by 500; the
    same 500 rebinds through this helper grew it by exactly 1, the one
    still live).

    Which widget to call `deletecommand` on matters and is NOT the same
    for every kind of bind: `_ScrollablePanel._unbind_wheel` already
    documents that `bind_all`'s funcid is tracked against the ROOT widget
    (`self._root()._bind(('bind', 'all'), ...)`), never the widget
    `bind_all()` was called on. A plain, non-"all" `.bind()` (this
    function's only use) is different -- confirmed empirically, not
    assumed: it registers its funcid via `self._register()` on the WIDGET
    ITSELF, so release must go through `widget.deletecommand(...)`, never
    `widget._root().deletecommand(...)`.

    The wrong target does NOT silently fail to release the Tcl command --
    `Misc.deletecommand()` calls `self.tk.deletecommand(name)` against the
    one Tcl interpreter shared by every widget under this `Tk()` root, so
    the underlying command is genuinely deleted no matter which widget
    object you call it through. What actually goes wrong, confirmed
    directly against CPython's own `tkinter.Misc.deletecommand`/`destroy`
    source (not assumed): that same method ALSO does its Python-side
    bookkeeping (`self._tclCommands.remove(name)`) against whichever
    object you called it on. A plain `.bind()`'s funcid lives in the
    WIDGET's own `_tclCommands` list (only `bind_all` routes that
    bookkeeping through `_root()`), so calling `deletecommand()` via the
    wrong (`_root()`) target tries to remove it from ROOT's list instead --
    a harmless no-op there (caught by that method's own `except
    ValueError`) -- while leaving the now-stale funcid behind in the
    WIDGET's own list. `Misc.destroy()` later iterates that same list and
    calls `self.tk.deletecommand(name)` on every entry unconditionally, so
    that stale, already-deleted funcid raises an uncaught `TclError: can't
    delete Tcl command` the moment this widget is ever `.destroy()`ed --
    e.g. cascading from `root.destroy()` at app shutdown. A double-delete
    crash at teardown, not a silent leak.

    Also the reason `root._tclCommands` (the metric `tests/
    test_scrollable_panel.py` uses, correctly, for the `bind_all` case)
    must NOT be trusted as the sole leak signal for a plain `.bind()` on a
    non-root widget -- confirmed empirically: 500 leaked plain-`.bind()`
    commands moved `root._tclCommands`'s count by exactly 0. Tests for
    this class of bug use `tests/testutils.py::count_tcl_commands`
    (`info commands`, the real interpreter-wide count) instead."""
    if previous_funcid is not None:
        try:
            widget.deletecommand(previous_funcid)
        except tk.TclError:
            # Already released is harmless -- bandit's B110 check only
            # flags a bare/`Exception`-typed try/except/pass by default
            # (see `try_except_pass.py`'s `check_typed_exception` config),
            # so this specific, narrow exception type needs no `# nosec`.
            pass
    return widget.bind(sequence, handler)


class _ScrollablePanel(tk.Frame):
    """A vertically scrollable container. Children are added to `.body`, not
    to this frame directly; `winfo_children()` is intentionally left
    un-overridden (callers that need to clear rendered content use
    `.body.winfo_children()`)."""

    def __init__(
        self, parent, bg: str, max_content_width: Optional[int] = None,
        on_content_width_change: Optional[Callable[[int], None]] = None,
    ):
        """`max_content_width` caps how wide `.body` (and therefore anything
        gridded into it with `sticky="ew"`, e.g. a meeting card) is ever
        allowed to stretch -- `None` (the default, used by the meeting-form
        panel) preserves the original unbounded behavior. Left `None` unless
        a caller opts in; see the meeting-list panel in `_build_summary` for
        the one caller that does.

        `on_content_width_change`, if given, is called from
        `_update_canvas_width` with the resolved width actually applied to
        `.body` (post-`max_content_width` clamp) every time it changes --
        added so a caller whose children stretch to fill `.body` (e.g. a
        meeting card's title label) can keep something width-dependent
        (wraplength) in sync without re-deriving this same clamped-width
        logic a second time or adding its own separate `<Configure>` binding
        on `.body` (which would silently clobber this class's own existing
        `body.bind("<Configure>", ...)` scrollregion binding below unless it
        also remembered to pass `add="+"`). `None` (the default) preserves
        the original behavior for every other caller (the meeting-form
        panel, and the meeting-list panel before this parameter existed)."""
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self._max_content_width = max_content_width
        self._on_content_width_change = on_content_width_change
        self._last_content_width: Optional[int] = None
        self._scrollregion_job = None
        self._canvas_width_job = None
        self._pending_canvas_width = None
        self._wheel_funcid = None

        # Debounced via after_idle rather than recalculating on every single
        # <Configure> event: inserting N sibling widgets (e.g. one meeting
        # card at a time) fires N of these in a row, and recomputing
        # scrollregion on every single one measured as a multi-second stall
        # once N was ~40 real meetings x ~8 widgets each.
        self.body.bind("<Configure>", self._schedule_scrollregion_update)
        # Same debounce applied to the canvas's own width sync: dragging a
        # window border (or maximizing) fires a rapid burst of <Configure>
        # events on the canvas -- collapsing that burst down to one
        # itemconfig() call via after_idle keeps a live resize/move smooth
        # instead of doing that call once per intermediate frame.
        self.canvas.bind("<Configure>", self._schedule_canvas_width_update)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _schedule_scrollregion_update(self, _event=None) -> None:
        if self._scrollregion_job is not None:
            return
        self._scrollregion_job = self.after_idle(self._update_scrollregion)

    def _update_scrollregion(self) -> None:
        self._scrollregion_job = None
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _schedule_canvas_width_update(self, event) -> None:
        self._pending_canvas_width = event.width
        if self._canvas_width_job is not None:
            return
        self._canvas_width_job = self.after_idle(self._update_canvas_width)

    def _update_canvas_width(self) -> None:
        self._canvas_width_job = None
        if self._pending_canvas_width is not None:
            width = self._pending_canvas_width
            if self._max_content_width is not None:
                # min(), not a hard override: below the cap this behaves
                # exactly like the uncapped panel (content still stretches
                # to fill a narrow window), and only clamps once the canvas
                # is wider than the cap -- the extra width past that point
                # is simply left as canvas background (already the same
                # color as `.body`, so it reads as deliberate margin, not a
                # gap) rather than stretching a meeting card to it.
                width = min(width, self._max_content_width)
            self.canvas.itemconfig(self._window, width=width)
            if self._on_content_width_change is not None and width != self._last_content_width:
                self._last_content_width = width
                self._on_content_width_change(width)

    def _on_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind_wheel(self, _event=None) -> None:
        # Guarded so a stray double-<Enter> (Tk can fire it without a
        # matching <Leave> in between, e.g. moving the mouse across a nested
        # child widget boundary) never registers a second global binding on
        # top of one already active -- that second `bind_all` would itself
        # be an orphaned Tcl command the moment `_unbind_wheel` only releases
        # the last one it captured.
        if self._wheel_funcid is None:
            self._wheel_funcid = self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _unbind_wheel(self, _event=None) -> None:
        # `unbind_all` alone only removes the Tk *binding* for the sequence;
        # it does NOT release the underlying Tcl command `bind_all` created
        # (confirmed empirically: 100,000 Enter/Leave cycles across this
        # panel and the meeting-form panel leaked 101,253 orphaned Tcl
        # commands and +79MB RSS in a long-running session). Explicitly
        # calling `deletecommand` on the funcid `bind_all` returned is what
        # actually frees it. Guarded with `is None` so a stray <Leave>
        # without a preceding <Enter> (or a second one) is a no-op instead
        # of double-deleting an already-released command.
        if self._wheel_funcid is not None:
            self.canvas.unbind_all("<MouseWheel>")
            # Deleting the command must go through `self.canvas._root()`,
            # NOT `self.canvas` itself: CPython's `Misc.bind_all` implements
            # a global binding as `self._root()._bind(('bind', 'all'), ...)`
            # -- it registers the Tcl command against the *toplevel root*'s
            # own bookkeeping list (`_tclCommands`), never the widget
            # `bind_all` was called on. Calling `deletecommand` on `canvas`
            # instead still deletes the real Tcl command (they share one
            # interpreter) but silently fails to remove it from the root's
            # list (a caught `ValueError`, since it's not in canvas's own
            # list). That stale, already-deleted name then blows up
            # `root.destroy()` at real app shutdown with `_tkinter.TclError:
            # can't delete Tcl command` the moment `destroy()` tries to
            # clean it up a second time -- confirmed empirically both ways
            # before settling on this.
            self.canvas._root().deletecommand(self._wheel_funcid)
            self._wheel_funcid = None


class MainWindow:
    def __init__(self, root: tk.Tk, callbacks: Callbacks):
        self.root = root
        self.callbacks = callbacks
        self.language = i18n.DEFAULT_LANGUAGE

        self._sound_profile_var = tk.StringVar()
        self._recurrence_var = tk.StringVar()
        self._work_filter_var = tk.StringVar()
        self._filter_display_to_value: Dict[str, str] = {"": "all"}
        self._sound_id_to_label: Dict[str, str] = {}
        self._sound_label_to_id: Dict[str, str] = {}
        self._recurrence_id_to_label: Dict[str, str] = {}
        self._recurrence_label_to_id: Dict[str, str] = {}
        self._toast_window = None
        self._companies: List[str] = []
        self._company_dialog = None
        self._company_listbox: Optional[tk.Listbox] = None
        self._gadget_active = False
        self._pre_gadget_geometry: Optional[str] = None
        self._gadget_drag_offset_x = 0
        self._gadget_drag_offset_y = 0
        self._card_widgets: Dict[str, _CardWidgets] = {}
        self._card_language: Optional[str] = None
        self._empty_state_frame: Optional[tk.Frame] = None
        # Which of the three *primary* (non-gadget) sibling frames is the
        # logical "current view" -- read by `set_gadget_mode` on exit so
        # leaving gadget mode restores whichever of list/calendar/week was
        # active beforehand instead of always jumping back to the list (the
        # bug documented in SDD.md's v2.7.0 section, now extended to a third
        # view in v2.9.0). Only `set_active_view` and `set_gadget_mode` ever
        # change this.
        self._primary_view = "list"
        self._headers: List[_HeaderWidgets] = []
        self._calendar_weekday_labels: List[tk.Label] = []
        self._calendar_cells: List[_CalendarCellWidgets] = []
        self._week_day_header_labels: List[tk.Label] = []
        self._week_cells: List[_WeekCellWidgets] = []
        self._week_now_line: Optional[tk.Frame] = None
        # Small filled-circle "now" marker shown at the live line's left end
        # (see `NOW_LINE_DOT_DIAMETER_PX`) -- built once in `_build_week_view`
        # right alongside `_week_now_line`, and, like that line, only ever
        # `.place()`d/`.place_forget()`'d together with it from
        # `_apply_week_now_line`, never destroyed/recreated.
        self._week_now_dot: Optional[tk.Canvas] = None
        self._week_live_state: Tuple[Optional[int], int, int] = (None, 0, 0)
        self._week_live_retry_job: Optional[str] = None
        self._week_live_retry_count = 0
        # Debounce handle for `_schedule_week_now_line_update` (see that
        # method) -- the same `after_idle`-coalescing pattern
        # `_ScrollablePanel._canvas_width_job` already uses for its own
        # `<Configure>` burst during a live window-resize drag.
        self._week_now_line_configure_job: Optional[str] = None
        # "last click selected" state for the week view only (SDD.md
        # v2.11.0) -- lives here, not in app.py, per that section's explicit
        # decision: it's purely presentational (which entry has an accent
        # border, which toolbar buttons are enabled), never a business
        # decision, so it doesn't need to cross the view/controller
        # boundary. See `clear_week_selection`/`_handle_week_entry_select`/
        # `_apply_week_selection_highlight`.
        self._week_selected_meeting_id: Optional[str] = None
        # "full" (Mon-Sun, 7 columns) or "work" (Mon-Fri, 2 columns
        # collapsed) -- see `set_week_column_mode`. app.py sets the real
        # persisted value right after construction; "full" here is only
        # this attribute's pre-persistence default, matching
        # `settings.json`'s own default for `weekColumnMode`.
        self._week_column_mode = "full"
        # Set by `_build_week_view` (today local variables `day_header_row`/
        # `grid_frame`) -- `set_week_column_mode` needs both afterwards to
        # collapse/restore the weekend columns' `grid_columnconfigure`
        # weight in both frames that declare those columns.
        self._week_day_header_row: Optional[tk.Frame] = None
        self._week_grid_frame: Optional[tk.Frame] = None
        # Lazily created/cached on first use (both need a live `tk.Tk()` to
        # query font metrics, which doesn't exist yet at this point in
        # `__init__`) -- see `_header_title_column_minsize`/`_subtitle_font`.
        # `title_label`'s text/font never change (see the property below),
        # so this is computed once and reused across all 3 header instances
        # instead of re-measuring the same string 3 times.
        self._title_natural_width_px: Optional[int] = None
        self._subtitle_font_cache: Optional["tkfont.Font"] = None
        # Set from `_ScrollablePanel`'s `on_content_width_change` hook (see
        # `_build_summary`/`_on_meeting_list_width_change`) -- `None` until
        # the meeting-list panel's first real `<Configure>` fires, at which
        # point every meeting card built afterwards picks it up immediately
        # (see `_create_card`) instead of waiting for its own resize event.
        self._card_title_wraplength_px: Optional[int] = None

        self.root.configure(bg=WINDOW_BG)
        # A single, long-lived context menu (SDD.md v2.10.0), reused for
        # every right-click on month/week cells -- never rebuilt per cell or
        # per click. Its contents are cleared and re-added just before each
        # `tk_popup()` call (see `_show_context_menu`); `tkinter.Menu.delete`
        # itself calls `deletecommand()` for every entry with a `command=`
        # it removes (verified against the stdlib source), so rebuilding its
        # contents on every right-click does not accumulate orphaned Tcl
        # commands the way a repeated plain `.bind()` would (see `_rebind`'s
        # docstring) -- this widget is deliberately never destroyed/recreated.
        self._context_menu = tk.Menu(self.root, tearoff=0)
        self._configure_ttk_style()
        self._build_layout()
        self.apply_translations(i18n.DEFAULT_LANGUAGE)
        self.clear_form()

    def _configure_ttk_style(self) -> None:
        """The work-field combobox (see `_build_form`) is the only ttk widget
        in this app -- everything else is plain tkinter (see module
        docstring for why). ttk.Combobox is the only stock widget that gives
        both a type-anything entry and a click-to-pick dropdown list, and
        unlike CustomTkinter it isn't PIL-image-based, so it doesn't carry
        the same per-widget render cost that ruled CustomTkinter out. `clam`
        is the only built-in theme where `.map()` actually lets us override
        fieldbackground/foreground on Windows (the default `vista` theme
        ignores most of it)."""
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "TimerMeet.TCombobox",
            fieldbackground=FIELD_BG, background=FIELD_BG, foreground=TEXT,
            arrowcolor=TEXT, bordercolor=BORDER, lightcolor=FIELD_BG, darkcolor=FIELD_BG,
            padding=6,
        )
        style.map(
            "TimerMeet.TCombobox",
            fieldbackground=[("readonly", FIELD_BG), ("disabled", FIELD_BG)],
            foreground=[("disabled", MUTED)],
        )
        # The dropdown popup is a plain Tk listbox under the hood and reads
        # its colors from the option database, not from the ttk style above.
        self.root.option_add("*TCombobox*Listbox.background", FIELD_BG)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", ACCENT_FG)

    # -- layout ---------------------------------------------------------------

    def _build_layout(self) -> None:
        # root has exactly one grid cell, holding whichever of these four
        # sibling frames is currently gridded -- full_view (the list view:
        # header+form+summary, unchanged), calendar_view (the monthly grid,
        # see `_build_calendar_view`/`set_active_view`), week_view (the
        # weekly grid, see `_build_week_view`/`set_active_view`), or
        # gadget_view (the borderless mini skin, see
        # `_build_gadget_view`/`set_gadget_mode`). Only one is ever gridded
        # at a time; the other three sit ungridded.
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.full_view = tk.Frame(self.root, bg=WINDOW_BG)
        self.full_view.grid(row=0, column=0, sticky="nsew")
        self.full_view.grid_columnconfigure(0, weight=1)
        self.full_view.grid_rowconfigure(1, weight=1)

        # "week" listed before "calendar" (SDD.md v2.10.0 discoverability
        # fix): on this, the launch screen where the user actually decides
        # which view to try, the hour-axis week view previously read second
        # with identical visual weight to the monthly calendar and went
        # unnoticed. Zero behavior change -- both buttons already existed
        # and already did the same thing; only construction order (and, see
        # `_build_header`, this one button's color) changes.
        self.full_header = self._build_header(
            self.full_view, [("week", "weekViewButton"), ("calendar", "calendarViewButton")]
        )
        self._headers.append(self.full_header)

        body = tk.Frame(self.full_view, bg=WINDOW_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1, minsize=340)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        self._build_form(body)
        self._build_summary(body)

        self._build_gadget_view()
        self._build_calendar_view()
        self._build_week_view()

    def _build_header(self, parent, view_buttons: List[Tuple[str, str]]) -> _HeaderWidgets:
        """Builds one full copy of the header (title/version/storage chips +
        the Notify/Language/view-switch/Gadget/Tray/Donate/Exit action row)
        into `parent`, and returns handles to every widget it created
        instead of stashing them on `self` directly -- this is called once
        per primary view (`full_view`, `calendar_view`, `week_view`), and a
        plain `self.title_label = ...` would have each later call silently
        overwrite the previous view's widget reference, leaving that view's
        header never updated again by `apply_translations`/
        `update_storage_status`. Every call site keeps its returned instance
        in `self._headers` and loops over it instead.

        `view_buttons` is a list of (target-view-name, i18n-key) pairs --
        up to 2 per header, one "go to view X" button each (never a single
        button cycling through all views: with three mutually exclusive
        views, a 1-button cycle can't unambiguously say which of the other
        two clicking it leads to, and it would also silently change the
        already-shipped behavior of the month view's "Vista de lista"
        button, see SDD.md's v2.9.0 section). Each button calls
        `on_set_active_view(target)` directly.
        """
        header = tk.Frame(parent, bg=PANEL_BG)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        # `minsize` is column 0's hard floor -- see `_header_title_column_minsize`
        # and the big comment block above `_HEADER_BUTTON_PADX` for why a bare
        # `weight=1` (the pre-fix state) let Tk compress this column, and
        # `title_label` along with it, all the way down to ~1px whenever this
        # row's `weight=0` actions column needed the deficit absorbed.
        header.grid_columnconfigure(0, weight=1, minsize=self._header_title_column_minsize())

        title_box = tk.Frame(header, bg=PANEL_BG)
        title_box.grid(row=0, column=0, sticky="w", padx=_HEADER_TITLE_BOX_PADX, pady=14)
        title_label = tk.Label(
            title_box, text="TimerMeet", font=(FONT_FAMILY, 24, "bold"), bg=PANEL_BG, fg=TEXT,
        )
        title_label.pack(anchor="w")
        subtitle_label = tk.Label(
            title_box, text="", font=(FONT_FAMILY, 12), bg=PANEL_BG, fg=MUTED,
        )
        subtitle_label.pack(anchor="w", pady=(2, 0))

        chips = tk.Frame(title_box, bg=PANEL_BG)
        chips.pack(anchor="w", pady=(10, 0))
        version_chip = tk.Label(
            chips, text="", bg=CHIP_BG, fg=MUTED, padx=10, pady=4, font=(FONT_FAMILY, 10),
        )
        version_chip.pack(side="left", padx=(0, 8))
        storage_chip = tk.Label(
            chips, text="", bg=CHIP_BG, fg=MUTED, padx=10, pady=4, font=(FONT_FAMILY, 10),
        )
        storage_chip.pack(side="left")

        actions = tk.Frame(header, bg=PANEL_BG)
        actions.grid(row=0, column=1, sticky="e", padx=_HEADER_ACTIONS_OUTER_PADX, pady=14)
        notify_button = _button(
            actions, "", self.callbacks.on_test_notification, GHOST_BG, GHOST_FG, GHOST_HOVER,
            padx=_HEADER_BUTTON_PADX, font_size=_HEADER_BUTTON_FONT_SIZE,
        )
        notify_button.pack(side="left", padx=_HEADER_BUTTON_GAP_PX)
        language_button = _button(
            actions, "EN", self.callbacks.on_toggle_language, GHOST_BG, GHOST_FG, GHOST_HOVER,
            padx=_HEADER_BUTTON_PADX, font_size=_HEADER_BUTTON_FONT_SIZE,
        )
        language_button.pack(side="left", padx=_HEADER_BUTTON_GAP_PX)
        view_switch_buttons: List[Tuple[tk.Button, str]] = []
        for target_view, key in view_buttons:
            # Discoverability fix (SDD.md v2.10.0): the button that jumps to
            # the hour-axis week view gets the app's accent palette instead
            # of the same GHOST_BG every other action-row button uses --
            # same precedent as `donate_button`'s own distinct GOLD_*
            # palette below. Applies to this button wherever it appears
            # (full_view and calendar_view); week_view itself never has a
            # "week" target in its own `view_buttons` (you're already
            # there), so this never fires out of place.
            if target_view == "week":
                btn_bg, btn_fg, btn_hover = ACCENT, ACCENT_FG, ACCENT_HOVER
            else:
                btn_bg, btn_fg, btn_hover = GHOST_BG, GHOST_FG, GHOST_HOVER
            view_button = _button(
                actions, "", lambda target=target_view: self.callbacks.on_set_active_view(target),
                btn_bg, btn_fg, btn_hover, padx=_HEADER_BUTTON_PADX, font_size=_HEADER_BUTTON_FONT_SIZE,
            )
            view_button.pack(side="left", padx=_HEADER_BUTTON_GAP_PX)
            view_switch_buttons.append((view_button, key))
        gadget_button = _button(
            actions, "", self.callbacks.on_toggle_gadget_mode, GHOST_BG, GHOST_FG, GHOST_HOVER,
            padx=_HEADER_BUTTON_PADX, font_size=_HEADER_BUTTON_FONT_SIZE,
        )
        gadget_button.pack(side="left", padx=_HEADER_BUTTON_GAP_PX)
        tray_button = _button(
            actions, "", self.callbacks.on_enter_tray_mode, GHOST_BG, GHOST_FG, GHOST_HOVER,
            padx=_HEADER_BUTTON_PADX, font_size=_HEADER_BUTTON_FONT_SIZE,
        )
        tray_button.pack(side="left", padx=_HEADER_BUTTON_GAP_PX)
        donate_button = _button(
            actions, "", self._open_donate, GOLD_BG, GOLD_FG, GOLD_HOVER,
            padx=_HEADER_BUTTON_PADX, font_size=_HEADER_BUTTON_FONT_SIZE,
        )
        donate_button.pack(side="left", padx=_HEADER_BUTTON_GAP_PX)
        # A thin visual gap sets "Salir" apart from the utility buttons --
        # it's the one action in this row that ends the whole app, not just
        # toggles a setting or opens a link, so it shouldn't blend in.
        tk.Frame(actions, bg=PANEL_BG, width=_HEADER_EXIT_SPACER_PX).pack(side="left")
        exit_button = _button(
            actions, "", self.callbacks.on_exit, DANGER, "#ffffff", DANGER_HOVER,
            padx=_HEADER_BUTTON_PADX, font_size=_HEADER_BUTTON_FONT_SIZE,
        )
        exit_button.pack(side="left", padx=_HEADER_BUTTON_GAP_PX)

        header_widgets = _HeaderWidgets(
            title_label=title_label, subtitle_label=subtitle_label, version_chip=version_chip,
            storage_chip=storage_chip, notify_button=notify_button, language_button=language_button,
            view_switch_buttons=view_switch_buttons,
            gadget_button=gadget_button, tray_button=tray_button, donate_button=donate_button,
            exit_button=exit_button, header_frame=header, actions_frame=actions,
        )
        # Recomputes the subtitle's ellipsis truncation whenever this specific
        # header actually resizes (see `_schedule_subtitle_update`/
        # `_update_header_subtitle`) -- `header`'s own width changes 1:1 with
        # the window's width (it's the only weighted column's parent-of-parent,
        # see `full_view.grid_columnconfigure(0, weight=1)` in `_build_layout`),
        # so this is the one `<Configure>` this class needs to react to, not
        # `title_box`'s own (which would be circular: shrinking the subtitle
        # text shrinks `title_box`'s natural request, which would change
        # `title_box`'s own `<Configure>` again).
        header.bind("<Configure>", lambda _e, hw=header_widgets: self._schedule_subtitle_update(hw))
        return header_widgets

    def _header_title_column_minsize(self) -> int:
        """Column 0's `grid_columnconfigure(minsize=...)` floor (see
        `_build_header`) -- measured via `tkinter.font.Font.measure()`
        against `title_label`'s own real font/text rather than a guessed
        constant, so this stays correct if either ever changes. Cached after
        the first call: `title_label`'s text ("TimerMeet") and font
        (`FONT_FAMILY`, 24, bold) are the same in every header instance and
        never change at runtime (unlike the subtitle, which is re-measured
        per resize -- see `_update_header_subtitle`), so there's nothing to
        gain from re-querying the same font metrics 3 times over.
        """
        if self._title_natural_width_px is None:
            title_font = tkfont.Font(root=self.root, family=FONT_FAMILY, size=24, weight="bold")
            self._title_natural_width_px = title_font.measure("TimerMeet")
        # `title_box`'s own padding (see its `.grid(padx=_HEADER_TITLE_BOX_PADX)`
        # call) is real space Tk reserves around the title inside this column
        # -- omitting it here would let the column's floor be satisfied while
        # `title_box` itself still gets squeezed by that missing padding.
        return self._title_natural_width_px + (_HEADER_TITLE_BOX_PADX * 2) + _HEADER_TITLE_MIN_MARGIN_PX

    def _get_subtitle_font(self) -> "tkfont.Font":
        if self._subtitle_font_cache is None:
            self._subtitle_font_cache = tkfont.Font(root=self.root, family=FONT_FAMILY, size=12)
        return self._subtitle_font_cache

    def _schedule_subtitle_update(self, header: _HeaderWidgets) -> None:
        """Debounced the same way `_ScrollablePanel._schedule_canvas_width_update`
        already is: a live window-resize drag fires a burst of `<Configure>`
        events on `header` in a row, and re-measuring/re-truncating the
        subtitle text on every single one of them is real (if small) work
        this doesn't need to repeat for every intermediate frame."""
        if header.subtitle_truncate_job is not None:
            return
        header.subtitle_truncate_job = self.root.after_idle(lambda: self._apply_subtitle_update(header))

    def _apply_subtitle_update(self, header: _HeaderWidgets) -> None:
        header.subtitle_truncate_job = None
        self._update_header_subtitle(header)

    def _update_header_subtitle(self, header: _HeaderWidgets) -> None:
        """Recomputes `header.subtitle_label`'s displayed text to fit
        whatever width column 0 actually has *right now* -- full text,
        ellipsis-truncated (`_truncate_text_to_pixel_width`), or empty (this
        app's stand-in for "hidden": an empty `tk.Label` occupies no visible
        space) if even the ellipsis doesn't fit. Called from both
        `_schedule_subtitle_update` (on resize) and `apply_translations` (on
        a language toggle, which changes the full untruncated text) so the
        two triggers never fall out of sync with two separate copies of this
        arithmetic.

        `header.header_frame.winfo_width()` can legitimately be tiny (Tk's
        pre-layout default, effectively 1px) in two real situations: before
        `mainloop()`'s first real layout pass (this runs once already, from
        `MainWindow.__init__` -> `apply_translations`, before the window has
        ever been mapped), and for the two header instances that belong to
        whichever primary view *isn't* currently active (an ungridded frame
        has no real allocated screen width -- see `set_active_view`). Bailing
        out on an implausibly small width rather than truncating against it
        avoids a visible flash to "" that would otherwise self-correct one
        frame later anyway once a real `<Configure>` fires (on first paint,
        or the moment this header's view becomes active) -- same reasoning
        `_WEEK_LINE_MIN_PLAUSIBLE_WIDTH_PX` already documents for the
        week view's own cold-start width delay.
        """
        full_text = i18n.t("appSubtitle", self.language)
        header_width = header.header_frame.winfo_width()
        if header_width <= _HEADER_SUBTITLE_MIN_PLAUSIBLE_WIDTH_PX:
            return
        # Column 1 (actions) never shrinks (see the `_HEADER_BUTTON_PADX`
        # comment block) -- its own reqwidth plus its `.grid(padx=...)` is a
        # reliable stand-in for "how much of `header_width` it's already
        # claimed", leaving the rest for column 0 without needing to read
        # column 0's own (possibly stale, see the docstring above) geometry.
        actions_width = header.actions_frame.winfo_reqwidth() + (_HEADER_ACTIONS_OUTER_PADX * 2)
        column0_width = max(header_width - actions_width, self._header_title_column_minsize())
        available_for_subtitle = (
            column0_width - (_HEADER_TITLE_BOX_PADX * 2) - _HEADER_SUBTITLE_SAFETY_MARGIN_PX
        )
        truncated = _truncate_text_to_pixel_width(full_text, self._get_subtitle_font(), available_for_subtitle)
        header.subtitle_label.configure(text=truncated)

    def _open_donate(self) -> None:
        if security.is_http_url(DONATE_URL):
            webbrowser.open(DONATE_URL)

    def _add_label(self, parent, bg: str = PANEL_BG) -> tk.Label:
        label = tk.Label(parent, text="", font=(FONT_FAMILY, 11, "bold"), anchor="w", bg=bg, fg=TEXT)
        label.pack(anchor="w", pady=(0, 2))
        return label

    def _build_form(self, parent) -> None:
        outer = _ScrollablePanel(parent, bg=PANEL_BG)
        outer.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        panel = outer.body

        self.form_eyebrow = tk.Label(panel, text="", font=(FONT_FAMILY, 10), bg=PANEL_BG, fg=MUTED)
        self.form_eyebrow.pack(anchor="w", pady=(10, 0), padx=10)
        self.form_title_label = tk.Label(panel, text="", font=(FONT_FAMILY, 17, "bold"), bg=PANEL_BG, fg=TEXT)
        self.form_title_label.pack(anchor="w", pady=(0, 4), padx=10)
        self.form_hint_label = tk.Label(
            panel, text="", font=(FONT_FAMILY, 10), bg=PANEL_BG, fg=MUTED, wraplength=300, justify="left"
        )
        self.form_hint_label.pack(anchor="w", pady=(0, 12), padx=10)

        self.meeting_id_var = tk.StringVar(value="")

        work_header = tk.Frame(panel, bg=PANEL_BG)
        work_header.pack(fill="x", padx=10)
        self.work_label = tk.Label(
            work_header, text="", font=(FONT_FAMILY, 11, "bold"), anchor="w", bg=PANEL_BG, fg=TEXT
        )
        self.work_label.pack(side="left")
        self.manage_companies_button = tk.Button(
            work_header, text="", command=self._open_manage_companies, bg=PANEL_BG, fg=MUTED,
            activebackground=PANEL_BG, activeforeground=ACCENT, relief="flat", borderwidth=0,
            cursor="hand2", font=(FONT_FAMILY, 9, "underline"), padx=0, pady=0,
        )
        self.manage_companies_button.pack(side="right")
        self.work_entry = ttk.Combobox(panel, style="TimerMeet.TCombobox", font=(FONT_FAMILY, 11))
        self.work_entry.pack(fill="x", padx=10, pady=(0, 10))

        self.title_label_field = self._add_label(panel)
        self.title_label_field.pack(anchor="w", padx=10)
        self.title_entry = _entry(panel)
        self.title_entry.pack(fill="x", padx=10, pady=(0, 10))

        date_row = tk.Frame(panel, bg=PANEL_BG)
        date_row.pack(fill="x", padx=10, pady=(0, 4))
        date_row.grid_columnconfigure((0, 1), weight=1)
        date_col = tk.Frame(date_row, bg=PANEL_BG)
        date_col.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.date_label = self._add_label(date_col)
        self.date_entry = _entry(date_col)
        self.date_entry.pack(fill="x")
        time_col = tk.Frame(date_row, bg=PANEL_BG)
        time_col.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.time_label = self._add_label(time_col)
        self.time_entry = _entry(time_col)
        self.time_entry.pack(fill="x")

        self.set_now_button = _button(panel, "", self.callbacks.on_set_now, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.set_now_button.pack(anchor="w", padx=10, pady=(8, 10))

        reminder_row = tk.Frame(panel, bg=PANEL_BG)
        reminder_row.pack(fill="x", padx=10, pady=(0, 4))
        reminder_row.grid_columnconfigure((0, 1), weight=1)
        reminder_col = tk.Frame(reminder_row, bg=PANEL_BG)
        reminder_col.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.reminder_label = self._add_label(reminder_col)
        self.reminder_entry = _entry(reminder_col)
        self.reminder_entry.insert(0, "15")
        self.reminder_entry.pack(fill="x")
        sound_col = tk.Frame(reminder_row, bg=PANEL_BG)
        sound_col.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.sound_label = self._add_label(sound_col)
        self.sound_menu, self._sound_menu_widget = self._make_option_menu(sound_col, self._sound_profile_var)
        self.sound_menu.pack(fill="x")

        self.test_sound_button = _button(panel, "", self._handle_test_sound, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.test_sound_button.pack(anchor="w", padx=10, pady=(8, 10))

        recur_row = tk.Frame(panel, bg=PANEL_BG)
        recur_row.pack(fill="x", padx=10, pady=(0, 4))
        recur_row.grid_columnconfigure((0, 1), weight=1)
        recur_col = tk.Frame(recur_row, bg=PANEL_BG)
        recur_col.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.recurrence_label = self._add_label(recur_col)
        self.recurrence_menu, self._recurrence_menu_widget = self._make_option_menu(
            recur_col, self._recurrence_var, command=self._handle_recurrence_change
        )
        self.recurrence_menu.pack(fill="x")
        occ_col = tk.Frame(recur_row, bg=PANEL_BG)
        occ_col.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.occurrence_label = self._add_label(occ_col)
        self.occurrence_entry = _entry(occ_col)
        self.occurrence_entry.insert(0, "1")
        self.occurrence_entry.pack(fill="x")

        self.recurrence_hint_label = tk.Label(
            panel, text="", font=(FONT_FAMILY, 9), bg=PANEL_BG, fg=MUTED, wraplength=300, justify="left"
        )
        self.recurrence_hint_label.pack(anchor="w", padx=10, pady=(4, 10))

        self.url_label = self._add_label(panel)
        self.url_label.pack(anchor="w", padx=10)
        self.url_entry = _entry(panel)
        self.url_entry.pack(fill="x", padx=10, pady=(0, 10))

        self.notes_label = self._add_label(panel)
        self.notes_label.pack(anchor="w", padx=10)
        self.notes_text = tk.Text(
            panel, height=4, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT, font=(FONT_FAMILY, 11),
        )
        self.notes_text.pack(fill="x", padx=10, pady=(0, 10))

        actions_row = tk.Frame(panel, bg=PANEL_BG)
        actions_row.pack(fill="x", padx=10, pady=(4, 4))
        self.save_button = _button(actions_row, "", self._handle_save, ACCENT, ACCENT_FG, ACCENT_HOVER)
        self.save_button.pack(side="left", padx=(0, 8))
        self.clear_button = _button(actions_row, "", self._handle_clear, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.clear_button.pack(side="left")

        self.form_feedback_label = tk.Label(
            panel, text="", wraplength=300, justify="left", bg=PANEL_BG, fg=MUTED, font=(FONT_FAMILY, 10)
        )
        self.form_feedback_label.pack(anchor="w", padx=10, pady=(8, 14))

    def _make_option_menu(self, parent, variable: tk.StringVar, command=None):
        menu_button = tk.OptionMenu(parent, variable, "")
        menu_button.configure(
            bg=FIELD_BG, fg=TEXT, activebackground=ACCENT, activeforeground=ACCENT_FG,
            highlightthickness=1, highlightbackground=BORDER, relief="flat", anchor="w",
            font=(FONT_FAMILY, 11), padx=8, pady=4, cursor="hand2",
        )
        menu_button["menu"].configure(bg=FIELD_BG, fg=TEXT, activebackground=ACCENT, activeforeground=ACCENT_FG)
        self._set_option_menu_values(menu_button, variable, [], command)
        return menu_button, menu_button

    @staticmethod
    def _set_option_menu_values(menu_button: tk.OptionMenu, variable: tk.StringVar, values: List[str], command=None) -> None:
        menu = menu_button["menu"]
        menu.delete(0, "end")

        def _select(value: str) -> None:
            variable.set(value)
            if command:
                command(value)

        for value in values:
            menu.add_command(label=value, command=lambda v=value: _select(v))

    def _build_summary(self, parent) -> None:
        panel = tk.Frame(parent, bg=PANEL_BG)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_rowconfigure(5, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = tk.Frame(panel, bg=PANEL_BG)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 4))
        self.stats_eyebrow = tk.Label(header, text="", font=(FONT_FAMILY, 10), bg=PANEL_BG, fg=MUTED)
        self.stats_eyebrow.pack(anchor="w")
        self.stats_title_label = tk.Label(header, text="", font=(FONT_FAMILY, 17, "bold"), bg=PANEL_BG, fg=TEXT)
        self.stats_title_label.pack(anchor="w")
        self.notification_hint_label = tk.Label(
            header, text="", font=(FONT_FAMILY, 10), bg=PANEL_BG, fg=MUTED, wraplength=380, justify="left"
        )
        self.notification_hint_label.pack(anchor="w", pady=(2, 0))

        status_grid = tk.Frame(panel, bg=PANEL_BG)
        status_grid.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        status_grid.grid_columnconfigure((0, 1), weight=1)
        self.current_time_card = self._stat_card(status_grid, 0)
        self.next_alert_card = self._stat_card(status_grid, 1)

        stats_grid = tk.Frame(panel, bg=PANEL_BG)
        stats_grid.grid(row=2, column=0, sticky="ew", padx=14, pady=4)
        stats_grid.grid_columnconfigure((0, 1, 2), weight=1)
        self.total_card = self._stat_card(stats_grid, 0)
        self.today_card = self._stat_card(stats_grid, 1)
        self.next_meeting_card = self._stat_card(stats_grid, 2)

        toolbar = tk.Frame(panel, bg=PANEL_BG)
        toolbar.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 4))
        self.filter_label = tk.Label(toolbar, text="", font=(FONT_FAMILY, 10, "bold"), bg=PANEL_BG, fg=TEXT)
        self.filter_label.pack(anchor="w")
        self.filter_menu, self._filter_menu_widget = self._make_option_menu(
            toolbar, self._work_filter_var, command=self._handle_filter_change
        )
        self.filter_menu.pack(fill="x", pady=(2, 0))

        self.clear_past_button = _button(
            toolbar, "", self._confirm_clear_past, GHOST_BG, GHOST_FG, GHOST_HOVER,
        )
        self.clear_past_button.pack(anchor="w", pady=(8, 0))

        list_header = tk.Frame(panel, bg=PANEL_BG)
        list_header.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 4))
        self.list_title_label = tk.Label(list_header, text="", font=(FONT_FAMILY, 13, "bold"), bg=PANEL_BG, fg=TEXT)
        self.list_title_label.pack(side="left")
        self.meeting_count_label = tk.Label(
            list_header, text="0", font=(FONT_FAMILY, 11), bg=PANEL_BG, fg=MUTED
        )
        self.meeting_count_label.pack(side="left", padx=(8, 0))

        list_container = _ScrollablePanel(
            panel, bg=PANEL_BG, max_content_width=MEETING_CARD_MAX_WIDTH_PX,
            on_content_width_change=self._on_meeting_list_width_change,
        )
        list_container.grid(row=5, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.meeting_list_frame = list_container.body
        self.meeting_list_frame.grid_columnconfigure(0, weight=1)

    def _on_meeting_list_width_change(self, width: int) -> None:
        """Keeps every meeting card's title label wrapping at the card's
        *actual current* width instead of a fixed guess -- needed because
        `MEETING_CARD_MAX_WIDTH_PX` means that width isn't constant (it
        scales with the window up to the cap, see `_ScrollablePanel`'s own
        docstring). A card's title stretches to fill the card via its own
        `sticky="ew"` (see `_create_card`), so `width` here -- the same
        already-`min()`-clamped value `_ScrollablePanel` just applied to
        `.body` -- minus the title label's own `padx` on each side is
        exactly the pixel budget Tk will actually give the title to render
        into. Wrapping (not truncating) was the choice for a card that
        doesn't fit: unlike a calendar/week cell, a meeting card has no
        fixed-height assumption elsewhere in this file that a taller,
        2-line title would break (`_ScrollablePanel`'s own scrollregion
        already recomputes from real content height on every change, see
        its `_schedule_scrollregion_update`), so wrapping preserves the
        full title instead of silently discarding part of it."""
        wraplength = max(width - (_CARD_TITLE_PADX * 2), 1)
        self._card_title_wraplength_px = wraplength
        for widgets in self._card_widgets.values():
            widgets.title_label.configure(wraplength=wraplength)

    def _stat_card(self, parent, column: int) -> Dict[str, tk.Label]:
        card = tk.Frame(parent, bg=CHIP_BG)
        card.grid(row=0, column=column, sticky="ew", padx=4, pady=4)
        label = tk.Label(card, text="", font=(FONT_FAMILY, 9), bg=CHIP_BG, fg=MUTED)
        label.pack(anchor="w", padx=10, pady=(8, 0))
        value = tk.Label(card, text="--", font=(FONT_FAMILY, 14, "bold"), bg=CHIP_BG, fg=TEXT)
        value.pack(anchor="w", padx=10, pady=(0, 8))
        return {"label": label, "value": value}

    # -- gadget mode --------------------------------------------------------------

    def _build_gadget_view(self) -> None:
        """The borderless mini skin (WMP "skin mode" style): built once,
        eagerly, alongside full_view, but never gridded here -- `set_gadget_mode`
        grids it in and `full_view` out (and back) on demand. Kept as a sibling
        of full_view in the same root grid cell rather than a second Toplevel,
        so the app never has more than one real top-level window (see
        `set_gadget_mode`'s docstring for why that matters for the alarm)."""
        self.gadget_view = tk.Frame(self.root, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER)

        strip = tk.Frame(self.gadget_view, bg=PANEL_BG)
        strip.pack(fill="x", padx=8, pady=(8, 0))
        self.gadget_title_label = tk.Label(strip, text="", font=(FONT_FAMILY, 9, "bold"), bg=PANEL_BG, fg=MUTED)
        self.gadget_title_label.pack(side="left")
        self.gadget_close_button = tk.Button(
            strip, text="", command=self.callbacks.on_exit, bg=PANEL_BG, fg=MUTED,
            activebackground=DANGER, activeforeground="#ffffff", relief="flat", borderwidth=0,
            cursor="hand2", font=(FONT_FAMILY, 12, "bold"), padx=6, pady=0,
        )
        self.gadget_close_button.pack(side="right")
        self.gadget_restore_button = tk.Button(
            strip, text="", command=self.callbacks.on_toggle_gadget_mode, bg=PANEL_BG, fg=MUTED,
            activebackground=PANEL_BG, activeforeground=ACCENT, relief="flat", borderwidth=0,
            cursor="hand2", font=(FONT_FAMILY, 9, "underline"), padx=0, pady=0,
        )
        self.gadget_restore_button.pack(side="right", padx=(0, 10))

        self.gadget_clock_label = tk.Label(
            self.gadget_view, text="--:--:--", font=(FONT_FAMILY, 22, "bold"), bg=PANEL_BG, fg=TEXT
        )
        self.gadget_clock_label.pack(anchor="w", padx=10, pady=(6, 0))

        self.gadget_next_alert_label = tk.Label(
            self.gadget_view, text="", font=(FONT_FAMILY, 9), bg=PANEL_BG, fg=MUTED,
            wraplength=GADGET_WIDTH - 20, justify="left",
        )
        self.gadget_next_alert_label.pack(anchor="w", padx=10, pady=(2, 8), fill="x")

        # Drag-from-anywhere: bound on every widget except the two buttons,
        # so a click on Restore/close still fires its own command instead of
        # being swallowed by a drag-start. Tk bindings don't propagate from a
        # parent to its children, hence binding the same handlers repeatedly.
        for widget in (self.gadget_view, strip, self.gadget_title_label, self.gadget_clock_label, self.gadget_next_alert_label):
            widget.bind("<ButtonPress-1>", self._start_gadget_drag)
            widget.bind("<B1-Motion>", self._do_gadget_drag)
            widget.bind("<Double-Button-1>", lambda _e: self.callbacks.on_toggle_gadget_mode())

    # -- monthly calendar view ----------------------------------------------------

    def _build_calendar_view(self) -> None:
        """The third sibling of `full_view`/`gadget_view` in root's one grid
        cell (see `_build_gadget_view`'s docstring for why a sibling frame,
        never a second Toplevel/Tk()). Built once, eagerly, right alongside
        the other two -- per SDD.md's v2.7.0 decision, this is measured
        against the .exe's 5s startup budget rather than assumed safe; if a
        real regression ever shows up, this is the one call to make lazy
        (build on first toggle instead of here), not the default.
        `set_active_view` grids it in/out; it starts ungridded because the
        default primary view is the list."""
        self.calendar_view = tk.Frame(self.root, bg=WINDOW_BG)
        self.calendar_view.grid_columnconfigure(0, weight=1)
        self.calendar_view.grid_rowconfigure(3, weight=1)

        self.calendar_header = self._build_header(
            self.calendar_view, [("list", "listViewButton"), ("week", "weekViewButton")]
        )
        self._headers.append(self.calendar_header)

        nav = tk.Frame(self.calendar_view, bg=PANEL_BG)
        nav.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.calendar_prev_button = _button(
            nav, "", self.callbacks.on_calendar_prev_month, GHOST_BG, GHOST_FG, GHOST_HOVER
        )
        self.calendar_prev_button.pack(side="left", padx=(0, 4))
        self.calendar_month_label = tk.Label(
            nav, text="", font=(FONT_FAMILY, 15, "bold"), bg=PANEL_BG, fg=TEXT, width=18, anchor="center",
        )
        self.calendar_month_label.pack(side="left", padx=4)
        self.calendar_next_button = _button(
            nav, "", self.callbacks.on_calendar_next_month, GHOST_BG, GHOST_FG, GHOST_HOVER
        )
        self.calendar_next_button.pack(side="left", padx=(4, 12))
        self.calendar_today_button = _button(nav, "", self.callbacks.on_calendar_today, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.calendar_today_button.pack(side="left")

        weekday_row = tk.Frame(self.calendar_view, bg=WINDOW_BG)
        weekday_row.grid(row=2, column=0, sticky="ew", padx=16)
        for col in range(CALENDAR_COLS):
            weekday_row.grid_columnconfigure(col, weight=1)
            label = tk.Label(weekday_row, text="", font=(FONT_FAMILY, 10, "bold"), bg=WINDOW_BG, fg=MUTED)
            label.grid(row=0, column=col, sticky="ew", pady=(0, 4))
            self._calendar_weekday_labels.append(label)

        grid_frame = tk.Frame(self.calendar_view, bg=WINDOW_BG)
        grid_frame.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))
        for row in range(CALENDAR_ROWS):
            grid_frame.grid_rowconfigure(row, weight=1)
        for col in range(CALENDAR_COLS):
            grid_frame.grid_columnconfigure(col, weight=1)

        # Built once, eagerly, exactly like the meeting list's cards --
        # `render_calendar` only ever `.configure()`/`.grid()`/`.grid_remove()`s
        # these 42 cells afterwards, it never destroys/recreates them.
        for row in range(CALENDAR_ROWS):
            for col in range(CALENDAR_COLS):
                self._calendar_cells.append(self._build_calendar_cell(grid_frame, row, col))

    def _build_calendar_cell(self, parent, row: int, col: int) -> _CalendarCellWidgets:
        # cursor="hand2" on both the frame's empty background and the day
        # number is the only discoverability signal that this cell is
        # clickable-to-create (see SDD.md v2.8.0 -- no new "+" widget, no
        # hover color) -- matches the treatment `entry_label` already had.
        cell = tk.Frame(
            parent, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER, cursor="hand2",
        )
        cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
        cell.grid_columnconfigure(0, weight=1)

        day_label = tk.Label(
            cell, text="", font=(FONT_FAMILY, 10, "bold"), bg=PANEL_BG, fg=TEXT, anchor="w", cursor="hand2",
        )
        day_label.grid(row=0, column=0, sticky="w", padx=4, pady=(2, 0))

        entry_labels: List[tk.Label] = []
        for slot in range(CALENDAR_MAX_ENTRIES_PER_CELL):
            entry_label = tk.Label(
                cell, text="", font=(FONT_FAMILY, 8), anchor="w", cursor="hand2", padx=3,
            )
            entry_label.grid(row=1 + slot, column=0, sticky="ew", padx=3, pady=1)
            entry_labels.append(entry_label)

        overflow_label = tk.Label(cell, text="", font=(FONT_FAMILY, 8), bg=PANEL_BG, fg=MUTED, anchor="w")
        overflow_label.grid(row=1 + CALENDAR_MAX_ENTRIES_PER_CELL, column=0, sticky="ew", padx=4, pady=1)

        return _CalendarCellWidgets(
            frame=cell, day_label=day_label, entry_labels=entry_labels, overflow_label=overflow_label,
        )

    # -- weekly calendar view -----------------------------------------------------

    def _build_week_view(self) -> None:
        """The fourth sibling of `full_view`/`calendar_view`/`gadget_view` in
        root's one grid cell (see `_build_gadget_view`'s docstring for why a
        sibling frame, never a second Toplevel/Tk()). Built once, eagerly,
        right alongside the other three -- per SDD.md's v2.9.0 decision #8,
        this is the biggest fixed widget-count jump yet (~718 widgets) and
        is measured against the .exe's 5s startup budget rather than assumed
        safe; if a real regression ever shows up, this is the one call to
        make lazy (build on first toggle instead of here), not
        `full_view`/`calendar_view`. `set_active_view` grids it in/out; it
        starts ungridded because the default primary view is the list.

        Layout, top to bottom: its own header copy (Exit/Language/Donate/
        Gadget/Tray stay reachable, same precedent as `calendar_view`), a
        nav bar (Prev/Next/This-week + the date-range label), a day-header
        row OUTSIDE the scrollable area (so the user never loses track of
        which column is which day while scrolling vertically -- see SDD.md
        decision #2), and a `_ScrollablePanel` holding the 24x7 hour/day
        grid plus the always-on-top-of-it-but-never-`.grid()`ed live time
        line (see `update_week_live_indicators`). The hour axis is column 0
        of that SAME grid (scrolls with it, not pinned) -- SDD.md decision
        #1 explains why a synced-scroll dual-canvas (the only way to pin it)
        was deliberately rejected as a new surface for the exact class of
        Tcl-command-leak bug this codebase has already hit twice.
        """
        self.week_view = tk.Frame(self.root, bg=WINDOW_BG)
        self.week_view.grid_columnconfigure(0, weight=1)
        self.week_view.grid_rowconfigure(3, weight=1)

        self.week_header = self._build_header(
            self.week_view, [("list", "listViewButton"), ("calendar", "calendarViewButton")]
        )
        self._headers.append(self.week_header)

        nav = tk.Frame(self.week_view, bg=PANEL_BG)
        nav.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        # Prev/Next/Today route through small wrapper methods rather than
        # straight to the callbacks (SDD.md v2.11.0): each wrapper clears
        # the week-view selection before forwarding to the real callback,
        # so navigating away from a selected entry can never leave the
        # toolbar's Editar/Eliminar buttons enabled over a now-different
        # week's data. See `clear_week_selection`.
        self.week_prev_button = _button(nav, "", self._handle_week_prev_click, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.week_prev_button.pack(side="left", padx=(0, 4))
        self.week_range_label = tk.Label(
            nav, text="", font=(FONT_FAMILY, 15, "bold"), bg=PANEL_BG, fg=TEXT, width=22, anchor="center",
        )
        self.week_range_label.pack(side="left", padx=4)
        self.week_next_button = _button(nav, "", self._handle_week_next_click, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.week_next_button.pack(side="left", padx=(4, 12))
        self.week_today_button = _button(nav, "", self._handle_week_today_click, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.week_today_button.pack(side="left")
        # Work-week/full-week toggle (SDD.md v2.10.0): lives in this nav bar,
        # not the header's action row, which is already at its width budget
        # at the app's 960px floor (see `_HEADER_BUTTON_PADX`'s comment
        # block) -- this nav bar has room to spare. One button whose own
        # text announces the state a click switches TO, same pattern
        # `language_button` already uses (its text is the *other*
        # language's code, not the current one).
        self.week_column_toggle_button = _button(
            nav, "", self.callbacks.on_toggle_week_column_mode, GHOST_BG, GHOST_FG, GHOST_HOVER,
        )
        self.week_column_toggle_button.pack(side="left", padx=(12, 0))

        # Action toolbar (SDD.md v2.11.0): Agregar/Editar/Eliminar operating
        # on `self._week_selected_meeting_id`. Lives in this nav bar, not
        # the header's action row -- same precedent as the work-week toggle
        # above. Built once here, for the app's whole life (like every
        # other button in this nav bar); never rebuilt or `.bind()`-rebound
        # per render, so none of this needs `_rebind()`. "Agregar" reuses
        # `_handle_week_slot_click` (the exact method an empty-cell click
        # already calls) with today's date/current hour -- zero new
        # callback. "Editar"/"Eliminar" start disabled (no selection yet at
        # construction) and `_update_week_toolbar_button_states` keeps them
        # in sync afterwards.
        self.week_add_button = _button(
            nav, "", lambda: self._handle_week_slot_click(date.today(), datetime.now().hour),
            GHOST_BG, GHOST_FG, GHOST_HOVER,
        )
        self.week_add_button.pack(side="left", padx=(12, 4))
        self.week_edit_button = _button(
            nav, "", lambda: self._handle_week_entry_click(self._week_selected_meeting_id),
            GHOST_BG, GHOST_FG, GHOST_HOVER,
        )
        self.week_edit_button.pack(side="left", padx=4)
        self.week_delete_button = _button(
            nav, "", lambda: self._confirm_delete(self._week_selected_meeting_id),
            GHOST_BG, GHOST_FG, GHOST_HOVER,
        )
        self.week_delete_button.pack(side="left", padx=4)
        self.week_edit_button.configure(state="disabled")
        self.week_delete_button.configure(state="disabled")

        day_header_row = tk.Frame(self.week_view, bg=WINDOW_BG)
        # Stashed on `self` (used to be a bare local) so `set_week_column_mode`
        # can reach this frame's `grid_columnconfigure` later, for the
        # work-week toggle (SDD.md v2.10.0) -- see that method.
        self._week_day_header_row = day_header_row
        day_header_row.grid(row=2, column=0, sticky="ew", padx=16)
        day_header_row.grid_columnconfigure(0, minsize=HOUR_AXIS_WIDTH_PX)
        for col in range(WEEK_COLS):
            day_header_row.grid_columnconfigure(col + 1, weight=1)
            # Same visible-chip convention as the month view's day-number
            # badges (`_update_calendar_cell`): every header gets a real,
            # non-window-color background so "today" (ACCENT fill, applied
            # in `update_week_live_indicators`) reads as a color swap on an
            # already-consistent shape, not the only header with a box at
            # all. Using WINDOW_BG here (this row's own parent background)
            # made the other 6 headers render as bare floating text with no
            # visible box whatsoever -- reported from a real screenshot and
            # confirmed by measurement to be a color issue, not a geometry
            # one (see SDD.md).
            label = tk.Label(
                day_header_row, text="", font=(FONT_FAMILY, 10, "bold"), bg=PANEL_BG, fg=TEXT, anchor="center",
            )
            label.grid(row=0, column=col + 1, sticky="ew", pady=(0, 4))
            self._week_day_header_labels.append(label)
        # Spacer matching the scrollable grid's own vertical scrollbar width
        # (see `_WEEK_SCROLLBAR_SPACER_PX`) so this fixed header row's 7 day
        # columns keep lining up with the day columns of the scrollable grid
        # below it, which give up that same width to their scrollbar.
        tk.Frame(day_header_row, bg=WINDOW_BG, width=_WEEK_SCROLLBAR_SPACER_PX).grid(row=0, column=WEEK_COLS + 1)

        scroll_panel = _ScrollablePanel(self.week_view, bg=WINDOW_BG)
        scroll_panel.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 16))
        # `scroll_panel.body` doubles as the "grid_frame" SDD.md describes --
        # column 0 is the hour axis, columns 1-7 are the 7 day columns, and
        # it scrolls as one unit (the hour axis is NOT pinned, see decision
        # #1 above). Using `body` directly instead of adding one more nested
        # Frame keeps the widget count down (see design-notes.md's "think
        # twice before adding a widget" guidance for this exact fixed panel).
        grid_frame = scroll_panel.body
        # Same reason as `self._week_day_header_row` above -- `set_week_column_mode`
        # needs this frame's `grid_columnconfigure` too (the weekend
        # columns' widget rows AND their column weight both live here).
        self._week_grid_frame = grid_frame
        grid_frame.grid_columnconfigure(0, minsize=HOUR_AXIS_WIDTH_PX)
        for col in range(1, WEEK_COLS + 1):
            grid_frame.grid_columnconfigure(col, weight=1)

        for row in range(WEEK_ROWS):
            grid_frame.grid_rowconfigure(row, minsize=WEEK_ROW_HEIGHT_PX)
            # The hour axis is static (never translated, never re-configured
            # after construction -- "00:00".."23:00" reads identically in
            # both languages) so it needs no rebind/re-render bookkeeping at
            # all, unlike every other label in this view.
            hour_label = tk.Label(
                grid_frame, text=f"{row:02d}:00", font=(FONT_FAMILY, 9), bg=WINDOW_BG, fg=MUTED, anchor="ne",
            )
            hour_label.grid(row=row, column=0, sticky="nsew", padx=(0, 4))
            for col in range(WEEK_COLS):
                self._week_cells.append(self._build_week_cell(grid_frame, row, col))

        # A single thin Frame, built once and reused for the app's whole
        # life: `update_week_live_indicators` only ever `.place()`s or
        # `.place_forget()`s it (see SDD.md decision #3) -- it's a real
        # pixel coordinate, not a grid cell, so `.grid()` is never used on
        # it at all, and it's never destroyed/recreated.
        self._week_now_line = tk.Frame(grid_frame, bg=NOW_LINE_COLOR, height=NOW_LINE_HEIGHT_PX)

        # The "now" dot: same lifecycle as the line above (built once here,
        # only ever `.place()`d/`.place_forget()`'d afterwards -- see that
        # attribute's docstring). A `tk.Canvas` with a single `create_oval`
        # item is the smallest way to get a filled circle in plain tkinter
        # (no themed-widget shortcut exists for this); the oval is drawn
        # exactly once here since it never needs to change color, size, or
        # be redrawn -- only the canvas's on-screen position toggles.
        # `highlightthickness=0` avoids an unwanted default 1px border/focus
        # ring around the tiny canvas that would otherwise read as its own
        # stray square. `bg` matches `grid_frame`'s own background so only
        # the circle itself (not the canvas's bounding box) is visible.
        dot_d = NOW_LINE_DOT_DIAMETER_PX
        self._week_now_dot = tk.Canvas(
            grid_frame, width=dot_d, height=dot_d, bg=WINDOW_BG, highlightthickness=0,
        )
        self._week_now_dot.create_oval(0, 0, dot_d, dot_d, fill=NOW_LINE_COLOR, outline=NOW_LINE_COLOR)

        # `_apply_week_now_line` only ever measures ROW 0's cell for a given
        # day column (every row in that column shares its width, see that
        # method's docstring) -- row 0's cells are exactly
        # `self._week_cells[0:WEEK_COLS]` (row-major order, row 0 * WEEK_COLS
        # + col == col). Binding `<Configure>` on these 7 long-lived cells
        # here, once, at construction is what lets the live line self-correct
        # the instant Tk finishes an actual column-width recompute (a window
        # resize, or `set_week_column_mode`'s weight/`.grid_remove()`
        # changes) instead of staying rendered at a stale pixel width/x until
        # the next per-minute heartbeat tick happens to re-invoke
        # `update_week_live_indicators` on its own (SDD.md v2.10.0) -- see
        # `_schedule_week_now_line_update`'s docstring for why a real
        # `<Configure>` listener, not a fixed delay or `update_idletasks()`,
        # is the correct fix. A one-time bind on 7 permanent widgets, never
        # repeated per-toggle or per-render, so this adds none of the
        # unbounded-rebind leak risk `_rebind()` exists to guard against
        # elsewhere in this file.
        for col in range(WEEK_COLS):
            self._week_cells[col].frame.bind("<Configure>", self._schedule_week_now_line_update)

    def _build_week_cell(self, parent, row: int, col: int) -> _WeekCellWidgets:
        cell = tk.Frame(
            parent, bg=PANEL_BG, highlightthickness=1, highlightbackground=BORDER, cursor="hand2",
        )
        cell.grid(row=row, column=col + 1, sticky="nsew", padx=1, pady=1)
        cell.grid_columnconfigure(0, weight=1)

        entry_labels: List[tk.Label] = []
        for slot in range(WEEK_MAX_ENTRIES_PER_CELL):
            entry_label = tk.Label(
                cell, text="", font=(FONT_FAMILY, 8), anchor="w", cursor="hand2", padx=3,
            )
            entry_label.grid(row=slot, column=0, sticky="ew", padx=3, pady=1)
            entry_labels.append(entry_label)

        overflow_label = tk.Label(cell, text="", font=(FONT_FAMILY, 8), bg=PANEL_BG, fg=MUTED, anchor="w")
        overflow_label.grid(row=WEEK_MAX_ENTRIES_PER_CELL, column=0, sticky="ew", padx=4, pady=1)

        return _WeekCellWidgets(
            frame=cell, entry_labels=entry_labels, overflow_label=overflow_label,
            entry_meeting_ids=[None] * WEEK_MAX_ENTRIES_PER_CELL,
        )

    def set_week_column_mode(self, mode: str) -> None:
        """Toggles between "full" (Mon-Sun, all 7 day columns visible) and
        "work" (Mon-Fri, the Saturday/Sunday columns collapsed) -- SDD.md
        v2.10.0. Purely visual: `recurrence.week_dates` always returns the
        same 7 real dates either way, and `_update_week_cell`'s `.bind()`
        rebinding (and its own dirty-check gate) is completely unaffected --
        this only ever touches `.grid()`/`.grid_remove()`/
        `grid_columnconfigure`, never `.bind()`.

        `grid_remove()` alone does NOT collapse a `weight=1` column to 0px
        -- confirmed against real Tk behavior, not assumed: an empty
        weighted column still claims its proportional share of the grid's
        extra space. Both halves are required together: `.grid_remove()`
        the weekend widgets (so they stop reserving a spot for the geometry
        manager to distribute space around) AND zero that column's own
        `weight` in BOTH frames that declare it (`_week_day_header_row` and
        `_week_grid_frame` -- the fixed day-header row and the scrollable
        grid are two separate frames, each with their own
        `grid_columnconfigure` for the same 7 day columns). Restoring
        "full" mode re-applies `weight=1` and calls a bare `.grid()` (no
        arguments -- Tk remembers each widget's last row/column/sticky) on
        the exact same widgets; nothing is ever destroyed or rebuilt here.

        The trailing `_apply_week_now_line()` call below is a real bug fix
        (SDD.md v2.10.0), not a no-op: the live "now" line is a separately
        `.place()`d widget with absolute pixel geometry (see that method's
        docstring), which Tk does NOT retroactively recompute just because a
        sibling column's grid weight changed -- without this call, toggling
        this mode left the line rendered at its pre-toggle width/x for as
        long as ~60 seconds, until the next per-minute heartbeat tick
        happened to re-invoke `update_week_live_indicators` on its own. This
        call alone is only a best-effort immediate attempt, since Tk's own
        column-width recompute for the `grid_columnconfigure`/
        `.grid_remove()` calls above is itself deferred (confirmed
        empirically, not assumed -- see `_schedule_week_now_line_update`'s
        docstring); the `<Configure>` listener bound on each day column in
        `_build_week_view` is what reliably catches the moment Tk's real
        recompute actually finishes and re-applies then, race-free.
        """
        # SDD.md v2.11.0: an entry selected in a weekend column would keep
        # the toolbar's Editar/Eliminar buttons enabled over something
        # `.grid_remove()`'d below the instant "work week" mode is toggled
        # on -- clear first, unconditionally, rather than only when the
        # selected entry actually happens to be in Sat/Sun.
        self.clear_week_selection()
        self._week_column_mode = mode
        show_weekend = mode != "work"
        for offset in _WEEKEND_COLUMN_INDICES:
            # Day-header row: columns are offset by 1 there (column 0 is the
            # hour-axis spacer -- see `_build_week_view`).
            self._week_day_header_row.grid_columnconfigure(offset + 1, weight=1 if show_weekend else 0)
            self._week_grid_frame.grid_columnconfigure(offset + 1, weight=1 if show_weekend else 0)
            if show_weekend:
                self._week_day_header_labels[offset].grid()
            else:
                self._week_day_header_labels[offset].grid_remove()
            for row in range(WEEK_ROWS):
                cell = self._week_cells[row * WEEK_COLS + offset]
                if show_weekend:
                    cell.frame.grid()
                else:
                    cell.frame.grid_remove()
        if hasattr(self, "week_column_toggle_button"):
            # Guarded with `hasattr`: `app.py` calls this once at startup
            # with the persisted setting, right after `MainWindow(...)` is
            # constructed -- by then the button already exists (it's built
            # eagerly in `_build_week_view`, part of the same `__init__` call
            # that runs this), but keeping this defensive costs nothing and
            # protects any future caller that might run this earlier.
            self.week_column_toggle_button.configure(
                text=i18n.t(
                    "weekViewFullWeekButton" if mode == "work" else "weekViewWorkWeekButton", self.language
                )
            )
        # See this method's docstring: best-effort immediate re-placement:
        # the `<Configure>`-triggered `_schedule_week_now_line_update` is
        # what actually catches the real, post-recompute geometry.
        self._apply_week_now_line()

    def _primary_view_frame(self) -> tk.Frame:
        if self._primary_view == "calendar":
            return self.calendar_view
        if self._primary_view == "week":
            return self.week_view
        return self.full_view

    def set_active_view(self, view: str) -> None:
        """Swap which of `full_view` ("list") / `calendar_view` ("calendar")
        / `week_view` ("week") is gridded into root's cell -- the same swap
        mechanism `set_gadget_mode` already uses, just between the three
        non-gadget frames. Also records `_primary_view`, which
        `set_gadget_mode` reads on exit so leaving gadget mode returns to
        whichever of these three was active beforehand instead of
        unconditionally landing on the list (see that method's docstring)."""
        if self._gadget_active:
            # Defensive only: the view-switch buttons that call this live in
            # full_view's/calendar_view's/week_view's own headers, none of
            # which is reachable while gadget_view is the one gridded frame
            # -- this should never actually fire from the real UI.
            return
        if self._primary_view == "week" and view != "week":
            # See SDD.md's v2.9.0 "Resultado real vs. diseño" section (second
            # bug write-up) / `_apply_week_now_line`'s
            # docstring: that method reschedules itself via `root.after(...)`
            # while it's waiting out the cold-start width delay, entirely
            # independent of app.py's own heartbeat gating. Leaving week view
            # before that width resolves must stop the chain here -- without
            # this, the retry keeps firing every 300ms for the rest of the
            # session even though week view is no longer on screen.
            self._cancel_week_live_retry()
            # SDD.md v2.11.0: clear on LEAVING week view (not on entering
            # it) -- by the time the user comes back, it's already empty,
            # so no second clear-on-entry call site is needed. Deliberately
            # NOT paired with the `set_gadget_mode` round trip below (that
            # path never reaches this method at all -- see its own
            # docstring -- which is exactly why a gadget round trip
            # preserves the selection, per SDD.md's explicit decision).
            self.clear_week_selection()
        self._primary_view_frame().grid_remove()
        self._primary_view = view
        self._primary_view_frame().grid(row=0, column=0, sticky="nsew")

    def render_calendar(self, month_label: str, weekday_labels: List[str], cells: List[CalendarCellData]) -> None:
        """Incremental, like `render_meeting_list`: reuses the 42 pre-built
        cell widgets (and their up-to-3 pre-built entry-row labels) via
        `.configure()`/`.grid()`/`.grid_remove()` every call -- never
        destroys/recreates a cell. Called from app.py only while the
        calendar is the active view (see `_refresh_calendar`), so a month
        navigation click or a heartbeat tick while some other view is
        showing never reaches here at all."""
        self.calendar_month_label.configure(text=month_label)
        for label_widget, text in zip(self._calendar_weekday_labels, weekday_labels):
            label_widget.configure(text=text)
        for widgets, cell_data in zip(self._calendar_cells, cells):
            self._update_calendar_cell(widgets, cell_data)

    def _update_calendar_cell(self, widgets: _CalendarCellWidgets, cell_data: CalendarCellData) -> None:
        if cell_data.is_today:
            day_bg, day_fg = ACCENT, ACCENT_FG
        elif cell_data.in_current_month:
            day_bg, day_fg = PANEL_BG, TEXT
        else:
            # Outside the visible month, but still real, clickable meetings
            # underneath (see SDD.md) -- only the day number itself dims.
            day_bg, day_fg = PANEL_BG, SUBTLE
        widgets.day_label.configure(text=str(cell_data.day.day), bg=day_bg, fg=day_fg)

        # Same "rebind a fresh closure on every render, never once at
        # construction" reasoning as `entry_label` below: `day_label`/`frame`
        # are long-lived widgets tied to a fixed grid *position*, not to a
        # fixed date, so the date this closure should create a meeting for
        # changes every time the user navigates months. This is safe from
        # WASTED rebinds (gated behind `render_calendar`'s own dirty-check in
        # app.py, whose signature already keys on `cell.day` first, so an
        # unchanged heartbeat tick never reaches this line at all) -- but
        # gating alone does not stop a real, correctly-triggered rebind from
        # leaking: on this Tk/Python version, `.bind()` on the same
        # widget+sequence again does NOT release the previous call's Tcl
        # command, only replaces which one fires (confirmed empirically --
        # see `_rebind`'s docstring for the exact numbers). `_rebind()`
        # captures and releases that previous command every time, so a
        # month navigation, an edit, or a language toggle -- all real,
        # legitimate rebinds -- no longer leave anything behind.
        day_click = lambda _e, d=cell_data.day: self._handle_calendar_day_click(d)
        widgets.bind_funcids["day_left"] = _rebind(
            widgets.day_label, "<Button-1>", day_click, widgets.bind_funcids.get("day_left")
        )
        widgets.bind_funcids["frame_left"] = _rebind(
            widgets.frame, "<Button-1>", day_click, widgets.bind_funcids.get("frame_left")
        )
        # Right-click context menu (SDD.md v2.10.0): "Nueva reunión" on the
        # cell's own empty background/day number -- same rebind discipline,
        # same gate, as the left-click above.
        day_context = lambda e, d=cell_data.day: self._show_calendar_day_context_menu(e, d)
        widgets.bind_funcids["day_right"] = _rebind(
            widgets.day_label, "<Button-3>", day_context, widgets.bind_funcids.get("day_right")
        )
        widgets.bind_funcids["frame_right"] = _rebind(
            widgets.frame, "<Button-3>", day_context, widgets.bind_funcids.get("frame_right")
        )

        for index, entry_label in enumerate(widgets.entry_labels):
            if index < len(cell_data.entries):
                entry = cell_data.entries[index]
                entry_label.configure(
                    text=_truncate_calendar_entry(f"{entry.time_text} {entry.title}"),
                    bg=entry.color, fg="black",
                )
                # Rebinding a fresh closure each render (instead of a
                # per-widget click handler set up once at construction, the
                # way `_create_card`'s buttons do) is required here: unlike a
                # meeting card -- one card per meeting, built once for that
                # meeting's whole lifetime in the list -- a calendar cell is
                # a fixed *position* in the grid whose displayed meeting
                # changes every time the user navigates months. See the
                # `day_click`/`day_context` comment above for why `_rebind`
                # (not a plain `.bind()`) is required here, not just the
                # dirty-check gate.
                left_key, right_key = f"entry_left_{index}", f"entry_right_{index}"
                widgets.bind_funcids[left_key] = _rebind(
                    entry_label, "<Button-1>",
                    lambda _e, mid=entry.meeting_id: self._handle_calendar_entry_click(mid),
                    widgets.bind_funcids.get(left_key),
                )
                widgets.bind_funcids[right_key] = _rebind(
                    entry_label, "<Button-3>",
                    lambda e, mid=entry.meeting_id, n=entry.series_occurrence_count: (
                        self._show_calendar_entry_context_menu(e, mid, n)
                    ),
                    widgets.bind_funcids.get(right_key),
                )
                entry_label.grid()
            else:
                entry_label.grid_remove()

        if cell_data.overflow_count > 0:
            widgets.overflow_label.configure(
                text=i18n.format_text("calendarMoreLabel", self.language, count=cell_data.overflow_count)
            )
            widgets.overflow_label.grid()
        else:
            widgets.overflow_label.grid_remove()

    def _handle_calendar_entry_click(self, meeting_id: str) -> None:
        # Same edit flow as the list view's "Editar" button, then hand the
        # view-switch back to app.py so its `active_view` bookkeeping (used
        # to skip calendar recompute while the list is showing, see
        # `_refresh_calendar`) stays correct.
        self.callbacks.on_edit(meeting_id)
        self.callbacks.on_set_active_view("list")

    def _handle_calendar_day_click(self, day: date) -> None:
        # Mirrors `_handle_calendar_entry_click`'s two-step pattern (data
        # action first, then hand the view-switch to app.py) -- here the
        # "data action" is preparing a blank form for `day` instead of
        # populating one from an existing meeting. Tkinter doesn't propagate
        # a child widget's click up to its parent, so this only ever fires
        # from a click on the day number or the cell's own empty background,
        # never as a duplicate of an `entry_label` click (see SDD.md v2.8.0).
        self.callbacks.on_calendar_day_click(day)
        self.callbacks.on_set_active_view("list")

    def render_week_grid(self, week_range_label: str, day_header_texts: List[str], cells: List[WeekCellData]) -> None:
        """Nivel A (see SDD.md v2.9.0 decision #4): incremental, like
        `render_calendar` -- reuses the 168 pre-built cell widgets via
        `.configure()`/`.grid()`/`.grid_remove()` every call, never
        destroys/recreates one. Called from app.py only while the week view
        is active AND only when its own dirty-check signature changed (see
        `_refresh_week`) -- that signature deliberately excludes hour/minute,
        so a bare heartbeat tick with unchanged data never reaches the
        `.bind()` calls in `_update_week_cell` below. The live time-line's
        per-minute movement is handled entirely by `update_week_live_indicators`
        instead (Nivel B) -- mixing the two would reintroduce the exact
        Tcl-command-leak class already found and fixed twice in this
        codebase (see module-map.md)."""
        self.week_range_label.configure(text=week_range_label)
        for label_widget, text in zip(self._week_day_header_labels, day_header_texts):
            label_widget.configure(text=text)
        for widgets, cell_data in zip(self._week_cells, cells):
            self._update_week_cell(widgets, cell_data)

        # SDD.md v2.11.0: the guaranteed-correct backstop for a selection
        # that no longer refers to anything visible -- covers every deletion
        # route (the toolbar's own "Eliminar", the context menu, "Eliminar
        # eventos pasados", the automatic retention purge) with a single
        # check instead of one per route, because all of them end up back
        # here via `_refresh_all` -> `_refresh_week` -> `render_week_grid`.
        # Known, accepted limit (documented, not fixed): this only sees
        # `cell.entries` (already capped at WEEK_MAX_ENTRIES_PER_CELL), so a
        # selected entry pushed into "+N más" by a new arrival reads as
        # "gone" here too, same as if it had actually been deleted.
        visible_meeting_ids = {
            entry.meeting_id for cell_data in cells for entry in cell_data.entries
        }
        if self._week_selected_meeting_id is not None and self._week_selected_meeting_id not in visible_meeting_ids:
            self._week_selected_meeting_id = None
        self._update_week_toolbar_button_states()

    def _update_week_cell(self, widgets: _WeekCellWidgets, cell_data: WeekCellData) -> None:
        # Same "rebind a fresh closure on every render, never once at
        # construction" reasoning `_update_calendar_cell` already documents
        # for `day_label`/`frame`: this cell is a fixed grid *position*
        # (one hour of one weekday column), not a fixed date -- which real
        # date/hour it represents changes every time the user navigates
        # weeks. Gated behind `render_week_grid`'s own dirty-check in app.py
        # so this only runs on a real re-render, but (same as
        # `_update_calendar_cell`) that gate alone doesn't stop a real
        # rebind from leaking a Tcl command -- `_rebind()` captures and
        # releases the previous one every time (see its docstring).
        slot_click = lambda _e, d=cell_data.day, h=cell_data.hour: self._handle_week_slot_click(d, h)
        widgets.bind_funcids["frame_left"] = _rebind(
            widgets.frame, "<Button-1>", slot_click, widgets.bind_funcids.get("frame_left")
        )
        # Right-click context menu (SDD.md v2.10.0): "Nueva reunión" on the
        # cell's own empty background -- same rebind discipline, same gate.
        slot_context = lambda e, d=cell_data.day, h=cell_data.hour: self._show_week_slot_context_menu(e, d, h)
        widgets.bind_funcids["frame_right"] = _rebind(
            widgets.frame, "<Button-3>", slot_context, widgets.bind_funcids.get("frame_right")
        )

        for index, entry_label in enumerate(widgets.entry_labels):
            if index < len(cell_data.entries):
                entry = cell_data.entries[index]
                widgets.entry_meeting_ids[index] = entry.meeting_id
                # Render-time fallback for the selection highlight (SDD.md
                # v2.11.0, camino 2 of 2 -- see `_apply_week_selection_highlight`
                # for camino 1, the immediate click path): derived fresh from
                # `self._week_selected_meeting_id` on every real render, so
                # this cell's border can never drift out of sync with the
                # real selection state even if the immediate path was somehow
                # skipped (a resync from disk, an edit made elsewhere).
                is_selected = entry.meeting_id == self._week_selected_meeting_id
                entry_label.configure(
                    text=_truncate_week_entry(f"{entry.time_text} {entry.title}"),
                    bg=entry.color, fg="black",
                    highlightthickness=2 if is_selected else 0,
                    highlightbackground=ACCENT,
                )
                left_key, right_key = f"entry_left_{index}", f"entry_right_{index}"
                # Left-click now SELECTS instead of editing directly (SDD.md
                # v2.11.0) -- week-view-only behavior change; the month
                # view's `_handle_calendar_entry_click` above is untouched.
                # `_handle_week_entry_click` itself is unchanged and still
                # used by "Editar" (context menu + toolbar).
                widgets.bind_funcids[left_key] = _rebind(
                    entry_label, "<Button-1>",
                    lambda _e, mid=entry.meeting_id: self._handle_week_entry_select(mid),
                    widgets.bind_funcids.get(left_key),
                )
                widgets.bind_funcids[right_key] = _rebind(
                    entry_label, "<Button-3>",
                    lambda e, mid=entry.meeting_id, n=entry.series_occurrence_count: (
                        self._show_week_entry_context_menu(e, mid, n)
                    ),
                    widgets.bind_funcids.get(right_key),
                )
                entry_label.grid()
            else:
                widgets.entry_meeting_ids[index] = None
                entry_label.grid_remove()

        if cell_data.overflow_count > 0:
            widgets.overflow_label.configure(
                text=i18n.format_text("calendarMoreLabel", self.language, count=cell_data.overflow_count)
            )
            widgets.overflow_label.grid()
        else:
            widgets.overflow_label.grid_remove()

    def update_week_live_indicators(self, today_index: Optional[int], hour: int, minute: int) -> None:
        """Nivel B (see SDD.md v2.9.0 decision #4): the ONLY two things this
        touches are the 7 day-header labels' colors (highlighting "today")
        and the live time-line's `.place()`/`.place_forget()` -- NEVER
        `.bind()`. That split is what makes it safe to call this as often as
        app.py's own gate allows (at most once a real minute while the shown
        week is the current one, see `_refresh_week`) for as long as the app
        stays open, with none of the unbounded-Tcl-command-leak risk
        `render_week_grid`/`_update_week_cell` have to guard against above.
        `today_index` is `None` whenever the visible week is not the real
        current week (see SDD.md decision #5) -- the line is hidden and no
        day header is highlighted in that case.
        """
        for index, label in enumerate(self._week_day_header_labels):
            if index == today_index:
                label.configure(bg=ACCENT, fg=ACCENT_FG)
            else:
                # Same PANEL_BG/TEXT chip as this label's own construction
                # default (see `_build_week_view`) -- restores the
                # always-visible chip after a previous tick highlighted this
                # header as "today" and a later tick un-highlights it (e.g.
                # week navigation, or midnight rollover).
                label.configure(bg=PANEL_BG, fg=TEXT)

        self._week_live_state = (today_index, hour, minute)
        # A fresh state to place is a fresh attempt at resolving real
        # geometry -- reset the retry counter so a legitimate later call
        # (e.g. the user left and re-entered week view) isn't penalized by
        # retries an earlier, unrelated call already spent.
        self._week_live_retry_count = 0
        self._cancel_week_live_retry()
        self._apply_week_now_line()

    def _cancel_week_live_retry(self) -> None:
        """Best-effort cancellation of a pending `_apply_week_now_line`
        self-reschedule (see that method's docstring for what it's retrying
        and why). Wrapped in the same defensive try/except
        `alarm_ui.py::AlarmController.dismiss()` already uses for its own
        job cancellation: `after_cancel` on an id whose callback already ran
        raises in some Tk states, and failing to cancel a stale job is far
        cheaper than raising out of a view switch."""
        if self._week_live_retry_job is not None:
            try:
                self.root.after_cancel(self._week_live_retry_job)
            except Exception:  # nosec B110
                pass
            self._week_live_retry_job = None

    def _schedule_week_now_line_update(self, _event=None) -> None:
        """Bound (once, at construction -- see `_build_week_view`) to
        `<Configure>` on each of the 7 row-0 week cells. Fixes a real,
        empirically-confirmed bug (SDD.md v2.10.0): `_apply_week_now_line`
        `.place()`s the live line at an ABSOLUTE pixel x/width read from
        `winfo_width()`/`winfo_x()` at the moment it runs -- Tk's grid
        geometry manager does NOT retroactively move an already-`.place()`d
        sibling when a column's real width changes afterwards (confirmed
        directly: toggling `set_week_column_mode` alone, with no listener,
        left the line rendered at its pre-toggle width/x indefinitely, until
        the next per-minute heartbeat tick happened to re-invoke
        `update_week_live_indicators` on its own -- up to ~60 real seconds
        later). The same gap existed for a plain window resize, with no
        toggle involved at all.

        A real `<Configure>` is the correct, race-free signal to react to
        here instead of a fixed delay or `update_idletasks()` (forbidden by
        this project's hard rule): confirmed directly (not assumed) that Tk
        does NOT recompute a grid column's real width synchronously inside
        the same call that changes `grid_columnconfigure`/`.grid_remove()`
        -- `winfo_width()` read immediately after, or even after several
        chained `after_idle`/`after(0, ...)` callbacks queued from within
        that same call, still reports the OLD width; only a genuine
        `<Configure>` notification (fired once Tk actually finishes the
        real recompute) reflects the new one. Reacting to that event is
        therefore the only race-free way to catch the right moment, short
        of the forbidden synchronous `update_idletasks()` call.

        Debounced the same way `_ScrollablePanel._schedule_canvas_width_update`
        already is: a live window-resize drag fires a burst of `<Configure>`
        events across all 7 watched cells in quick succession, and
        `set_week_column_mode` itself touches 2 of them at once -- collapsing
        that burst into a single `_apply_week_now_line()` call is strictly
        cheaper and avoids placing at an intermediate, still-settling width.
        """
        if self._week_now_line_configure_job is not None:
            return
        self._week_now_line_configure_job = self.root.after_idle(self._run_week_now_line_configure_update)

    def _run_week_now_line_configure_update(self) -> None:
        self._week_now_line_configure_job = None
        self._apply_week_now_line()

    def _apply_week_now_line(self) -> None:
        """Places (or hides) the live time-line from `self._week_live_state`
        (the last values `update_week_live_indicators` recorded). Split out
        from `update_week_live_indicators` so it can also be re-invoked by
        `self.root.after(...)` retries below, without re-doing the
        day-header color pass or re-recording state each retry tick.

        Y is pure arithmetic against the declared row-height constant
        (never derived from `winfo_y()` of a real row -- see SDD.md decision
        #3). X/width DO need a live query because column width is
        proportional to the window's (resizable) actual width, taken from
        the row-0 cell of the "today" column (`self._week_cells[today_index]`,
        since row 0's cells are the first `WEEK_COLS` entries in that
        row-major list).

        The `width < _WEEK_LINE_MIN_PLAUSIBLE_WIDTH_PX` guard and retry
        below exist because of a real, empirically-confirmed one-time
        cold-start delay: the very first time the week view is ever
        activated in a session, `winfo_width()` on a just-`.grid()`ed hour
        cell does NOT reliably read as an obvious "not mapped" sentinel
        (`<=1`) -- it measured a small, real-looking but WRONG ~18px
        (this widget's own pre-layout natural size) for up to ~1.5s before
        Tk finished propagating the newly-mapped grid's real column widths,
        confirmed directly with a live widget tree, not assumed. A day
        column can never legitimately be that narrow: at this app's
        `root.minsize(960, 640)` floor, 7 columns of the available width
        (minus the fixed hour axis + scrollbar) works out to ~120px each --
        so `_WEEK_LINE_MIN_PLAUSIBLE_WIDTH_PX` sits well below that real
        floor and well above the observed stale value, with margin on both
        sides. Retrying on a real timer (never `update()`/`update_idletasks()`,
        per this project's hard rule) self-heals within about a second and
        never recurs for the rest of the session once real geometry has
        resolved once -- confirmed empirically that a later switch away and
        back reuses the already-correct cached geometry immediately.

        Two termination guards, both required (fixed together after a real
        bug: this used to reschedule itself unconditionally forever if the
        user switched away from week view before the width resolved): the
        active-view check right below bails out -- doing no work and,
        critically, NOT rescheduling -- the moment week view is no longer
        the visible primary frame (covers both a plain List/Month switch via
        `set_active_view`, which also proactively cancels any pending job
        itself, and a gadget-mode toggle, which doesn't call
        `set_active_view` at all but is still caught here); and
        `_WEEK_LINE_MAX_RETRIES` caps the retry count as defense-in-depth for
        a window state that hypothetically never resolves, so a gap in the
        active-view check can never again turn into an unconditional
        forever-loop."""
        if self._primary_view != "week" or self._gadget_active:
            # Week view isn't the visible primary frame anymore -- either a
            # plain view switch (which already cancelled any pending retry
            # job before getting here, see `set_active_view`) or a
            # gadget-mode toggle (which doesn't go through `set_active_view`
            # at all, so this is the only place that catches it). Either
            # way: no widget to place a line onto, and no reschedule.
            return
        today_index, hour, minute = self._week_live_state
        if today_index is None:
            # `_week_now_dot` always follows `_week_now_line`'s own
            # show/hide state -- they're one visual unit (see both widgets'
            # docstrings) -- so every `place_forget()`/`place()` call on the
            # line below has a matching one on the dot right next to it.
            self._week_now_line.place_forget()
            self._week_now_dot.place_forget()
            return
        reference_cell = self._week_cells[today_index].frame
        width = reference_cell.winfo_width()
        if width < _WEEK_LINE_MIN_PLAUSIBLE_WIDTH_PX:
            self._week_now_line.place_forget()
            self._week_now_dot.place_forget()
            self._week_live_retry_count += 1
            if self._week_live_retry_count > _WEEK_LINE_MAX_RETRIES:
                # Give up -- see the cap's own comment for why this margin
                # is generous. Leaves the line hidden rather than placed
                # with implausible geometry; a later `update_week_live_indicators`
                # call (next heartbeat tick, still gated to once a minute)
                # resets the counter and gets a fresh set of attempts.
                self._week_live_retry_job = None
                return
            self._week_live_retry_job = self.root.after(300, self._apply_week_now_line)
            return
        x = reference_cell.winfo_x()
        y = WEEK_ROW_HEIGHT_PX * (hour + minute / 60)
        self._week_now_line.place(x=x, y=y, width=width, height=NOW_LINE_HEIGHT_PX)
        # The dot sits centered on the line's own left end -- half hanging
        # over the hour-axis gutter, half over the line's start -- exactly
        # the "dot + line" combination Outlook/Teams/Google Calendar all use
        # for a "this is now" marker. Vertically centered on the line's own
        # thickness so it reads as one shape, not two misaligned ones.
        dot_radius = NOW_LINE_DOT_DIAMETER_PX / 2
        self._week_now_dot.place(
            x=x - dot_radius, y=y + (NOW_LINE_HEIGHT_PX / 2) - dot_radius,
        )

    def _handle_week_entry_click(self, meeting_id: str) -> None:
        self.callbacks.on_edit(meeting_id)
        self.callbacks.on_set_active_view("list")

    def _handle_week_slot_click(self, day: date, hour: int) -> None:
        self.callbacks.on_week_slot_click(day, hour)
        self.callbacks.on_set_active_view("list")

    # -- week-view "last click" selection + action toolbar (SDD.md v2.11.0) ----

    def _handle_week_entry_select(self, meeting_id: str) -> None:
        """What left-click on a week-view entry does now, instead of
        `_handle_week_entry_click` (edit). Deliberately does NOT call
        `on_edit`/`on_set_active_view` -- selecting stays in week view. A
        second click on the already-selected entry re-selects the same id
        (idempotent no-op), and clicking a different entry simply moves the
        selection (no multi-select, per SDD.md's explicit non-goal)."""
        self._week_selected_meeting_id = meeting_id
        self._apply_week_selection_highlight()
        self._update_week_toolbar_button_states()

    def clear_week_selection(self) -> None:
        """Called from the specific set of places SDD.md v2.11.0 names
        explicitly (week nav Prev/Next/Today, the work-week/full-week
        toggle, leaving week view for another primary view, and
        `render_week_grid`'s own render-time backstop for a
        deleted/no-longer-visible selection) -- deliberately NOT called on a
        gadget-mode round trip (see `set_gadget_mode`'s docstring/SDD.md for
        why that case is excluded on purpose)."""
        if self._week_selected_meeting_id is None:
            return
        self._week_selected_meeting_id = None
        self._apply_week_selection_highlight()
        self._update_week_toolbar_button_states()

    def _apply_week_selection_highlight(self) -> None:
        """Camino 1 of 2 (SDD.md v2.11.0): the immediate, same-click path --
        walks the already-built entry labels comparing against
        `entry_meeting_ids` and flips `highlightthickness`/
        `highlightbackground` on whichever ones changed. Purely
        `.configure()`, same category as `update_week_live_indicators`
        (Nivel B) -- never `.bind()`, so this is not a new Tcl-command-leak
        surface. `_update_week_cell` (camino 2, the render-time fallback)
        re-derives the same styling independently on every real render, so
        this path being imperfect could never leave a stale border
        permanently -- but responding on the same click, without waiting for
        the next heartbeat, is the whole point of having it."""
        for widgets in self._week_cells:
            for index, label in enumerate(widgets.entry_labels):
                is_selected = (
                    widgets.entry_meeting_ids[index] is not None
                    and widgets.entry_meeting_ids[index] == self._week_selected_meeting_id
                )
                label.configure(highlightthickness=2 if is_selected else 0, highlightbackground=ACCENT)

    def _update_week_toolbar_button_states(self) -> None:
        """Centralizes SDD.md v2.11.0's `state="disabled"`/`"normal"` toggle
        for "Editar"/"Eliminar" -- called from every place the selection can
        change (`_handle_week_entry_select`, `clear_week_selection`, and
        `render_week_grid`'s own backstop) so these two buttons can never
        drift out of sync with whether a selection actually exists."""
        state = "normal" if self._week_selected_meeting_id is not None else "disabled"
        self.week_edit_button.configure(state=state)
        self.week_delete_button.configure(state=state)

    def _handle_week_prev_click(self) -> None:
        self.clear_week_selection()
        self.callbacks.on_week_prev()

    def _handle_week_next_click(self) -> None:
        self.clear_week_selection()
        self.callbacks.on_week_next()

    def _handle_week_today_click(self) -> None:
        self.clear_week_selection()
        self.callbacks.on_week_today()

    # -- right-click context menu (month/week only, SDD.md v2.10.0) -------------

    def _show_context_menu(self, event) -> None:
        """Shared `tk_popup` call for all four context-menu entry points
        below. `self._context_menu` is the single, long-lived `tk.Menu`
        built once in `__init__` -- never rebuilt here, never `.destroy()`ed
        after use: `tk_popup` positions the menu and returns immediately
        (it does not block until the menu closes), so destroying it in this
        same call would close it before the user could ever see or click
        it. `grab_release()` in `finally` mirrors Tk's own documented
        `tk_popup` idiom -- releases the temporary grab `tk_popup` sets even
        if the menu is dismissed by a click outside it rather than a real
        selection."""
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _show_calendar_day_context_menu(self, event, day: date) -> None:
        self._context_menu.delete(0, "end")
        self._context_menu.add_command(
            label=i18n.t("contextMenuNewMeeting", self.language),
            command=lambda d=day: self._handle_calendar_day_click(d),
        )
        self._show_context_menu(event)

    def _show_calendar_entry_context_menu(self, event, meeting_id: str, series_occurrence_count: int = 0) -> None:
        self._context_menu.delete(0, "end")
        self._context_menu.add_command(
            label=i18n.t("edit", self.language), command=lambda mid=meeting_id: self._handle_calendar_entry_click(mid)
        )
        # Deliberately does NOT call `on_set_active_view("list")` (unlike
        # "Editar" above) -- matches the list view's own "Eliminar" button,
        # which never forces a view switch either; `handle_delete` in
        # app.py already calls `_refresh_all()` on its own, so the deleted
        # entry disappears from this cell on the next heartbeat without
        # needing to leave month/week view first (SDD.md v2.10.0).
        self._context_menu.add_command(
            label=i18n.t("delete", self.language), command=lambda mid=meeting_id: self._confirm_delete(mid)
        )
        # "Eliminar serie completa" (SDD.md v2.11.0): only offered when
        # there are 2+ LIVE siblings sharing this entry's `seriesId` this
        # same refresh (computed in app.py via
        # `recurrence.group_meetings_by_series`, never `meeting.seriesSize`
        # -- see `CalendarEntry.series_occurrence_count`'s docstring for why
        # that field can be stale). `1` means "recurring but only one
        # occurrence exists right now" -- not enough to offer this.
        if series_occurrence_count > 1:
            self._context_menu.add_command(
                label=i18n.t("deleteSeries", self.language),
                command=lambda mid=meeting_id, n=series_occurrence_count: self._confirm_delete_series(mid, n),
            )
        self._show_context_menu(event)

    def _show_week_slot_context_menu(self, event, day: date, hour: int) -> None:
        self._context_menu.delete(0, "end")
        self._context_menu.add_command(
            label=i18n.t("contextMenuNewMeeting", self.language),
            command=lambda d=day, h=hour: self._handle_week_slot_click(d, h),
        )
        self._show_context_menu(event)

    def _show_week_entry_context_menu(self, event, meeting_id: str, series_occurrence_count: int = 0) -> None:
        # SDD.md v2.11.0: right-click also selects, as a deliberate side
        # effect -- matches Windows' own precedent (right-click on an
        # unselected item selects it first) and avoids the confusing state
        # of "right-clicked A to delete it, but the toolbar still shows B as
        # selected". Right-click on empty slot background
        # (`_show_week_slot_context_menu`) never touches selection -- no
        # entry under the cursor to select.
        self._handle_week_entry_select(meeting_id)
        self._context_menu.delete(0, "end")
        self._context_menu.add_command(
            label=i18n.t("edit", self.language), command=lambda mid=meeting_id: self._handle_week_entry_click(mid)
        )
        # Same no-view-switch reasoning as `_show_calendar_entry_context_menu`.
        self._context_menu.add_command(
            label=i18n.t("delete", self.language), command=lambda mid=meeting_id: self._confirm_delete(mid)
        )
        # Same enablement rule as the month view's menu above.
        if series_occurrence_count > 1:
            self._context_menu.add_command(
                label=i18n.t("deleteSeries", self.language),
                command=lambda mid=meeting_id, n=series_occurrence_count: self._confirm_delete_series(mid, n),
            )
        self._show_context_menu(event)

    def _start_gadget_drag(self, event) -> None:
        # Guards against a real, reproduced bug: double-clicking the gadget
        # to restore the full window fires this a second time (Tk delivers
        # the plain ButtonPress-1 before resolving Double-Button-1), and if
        # the mouse moves at all before release -- ordinary click jitter --
        # a stray <B1-Motion> would otherwise still land on this (now
        # grid_remove()'d) widget and drag the just-restored, much larger
        # full window using a stale gadget-sized offset. Bailing out here
        # whenever gadget mode isn't (or is no longer) active makes any
        # drag event that arrives mid-mode-switch a no-op.
        if not self._gadget_active:
            return
        self._gadget_drag_offset_x = event.x_root - self.root.winfo_x()
        self._gadget_drag_offset_y = event.y_root - self.root.winfo_y()

    def _do_gadget_drag(self, event) -> None:
        if not self._gadget_active:
            return
        new_x = event.x_root - self._gadget_drag_offset_x
        new_y = event.y_root - self._gadget_drag_offset_y
        # Clamp every motion event, not just at mode-entry: this is an
        # overrideredirect + topmost window with no taskbar/Alt-Tab entry,
        # so an unclamped fast drag past a screen edge could otherwise
        # strand it fully off-screen with its own Restore/Close controls
        # unreachable for the rest of the session.
        new_x, new_y = self._resolve_gadget_position(new_x, new_y)
        self.root.geometry(f"+{new_x}+{new_y}")

    def _virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """(left, top, width, height) of the full virtual desktop spanning
        every connected monitor. `winfo_screenwidth()`/`winfo_screenheight()`
        only report the PRIMARY monitor on Windows -- clamping the gadget
        against just that would silently snap it back from a legitimate
        position on a secondary monitor every time gadget mode is
        (re-)entered. `GetSystemMetrics` gives the real bounds (the origin
        can be negative for a monitor placed left of/above the primary);
        fall back to Tk's primary-only metrics if that call ever fails for
        any reason (e.g. a non-Windows dev environment)."""
        try:
            import ctypes

            user32 = ctypes.windll.user32
            SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
            SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
            left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            if width > 0 and height > 0:
                return left, top, width, height
        except Exception:  # nosec B110 - best-effort; Tk's own metrics are a safe fallback
            pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _resolve_gadget_position(self, x: Optional[int], y: Optional[int]) -> Tuple[int, int]:
        left, top, width, height = self._virtual_screen_bounds()
        if x is None or y is None:
            # The default position is always the primary monitor's own
            # bottom-right corner (not the whole virtual desktop's) --
            # where a new gadget is expected to first appear.
            x = self.root.winfo_screenwidth() - GADGET_WIDTH - GADGET_MARGIN_X
            y = self.root.winfo_screenheight() - GADGET_HEIGHT - GADGET_MARGIN_BOTTOM
        x = max(left, min(int(x), max(left, left + width - GADGET_WIDTH)))
        y = max(top, min(int(y), max(top, top + height - GADGET_HEIGHT)))
        return x, y

    def current_gadget_position(self) -> Tuple[int, int]:
        return self.root.winfo_x(), self.root.winfo_y()

    def set_gadget_mode(self, is_gadget: bool, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Reskin the SAME root window instead of swapping in a second
        Toplevel -- this is the one existing Tk() instance and heartbeat for
        the app's whole life either way. Every `overrideredirect()` toggle is
        wrapped in an immediate withdraw()-just-before/deiconify()-just-after
        pair on both directions: this sidesteps a documented Windows/Tk quirk
        where toggling overrideredirect on an already-mapped window doesn't
        reliably stick, and because Tk's event loop is single-threaded, the
        brief "root not mapped" window is invisible to the rest of the app --
        no heartbeat tick, alert, or toast can run in the middle of this one
        synchronous call. AlarmController's overlay needs no special
        handling here: it's an independent, non-transient Toplevel (see
        alarm_ui.py) whose own visibility never depended on root's mapped
        state, size, or decoration -- only on its own attributes.

        Which of `full_view`/`calendar_view`/`week_view` gets grid_remove()d
        on entry and grid()ed back on exit is resolved through
        `_primary_view_frame()` (backed by `_primary_view`), not hardcoded
        to `full_view` -- with a third primary view added in v2.7.0 (and a
        fourth in v2.9.0), hardcoding it here was a real bug: entering
        gadget mode from the calendar and leaving it again used to always
        land back on the list instead of the calendar. Only
        `set_active_view` ever changes `_primary_view`, so whichever primary
        view was showing before this call is exactly what reappears after
        it, regardless of how many times gadget mode is toggled in between.
        """
        if is_gadget:
            self._pre_gadget_geometry = self.root.geometry()
            target_x, target_y = self._resolve_gadget_position(x, y)
            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.resizable(False, False)
            # TimerMeetApp.__init__ sets a 960x640 minsize for the full
            # window; left in place it silently clamps the geometry() call
            # below back up to 960x640 even with resizable(False, False).
            self.root.minsize(1, 1)
            self._primary_view_frame().grid_remove()
            self.gadget_view.grid(row=0, column=0, sticky="nsew")
            self.root.geometry(f"{GADGET_WIDTH}x{GADGET_HEIGHT}+{target_x}+{target_y}")
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self._gadget_active = True
        else:
            self.root.withdraw()
            self.root.overrideredirect(False)
            self.root.attributes("-topmost", False)
            self.root.resizable(True, True)
            self.gadget_view.grid_remove()
            self._primary_view_frame().grid(row=0, column=0, sticky="nsew")
            self.root.geometry(self._pre_gadget_geometry or "1180x760")
            self.root.minsize(960, 640)
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self._gadget_active = False

    def keep_gadget_on_top(self, is_alarm_active: bool) -> None:
        """Called every heartbeat tick from app.py; a near-zero-cost no-op
        unless gadget mode is active. Piggybacks on the existing 1s heartbeat
        instead of a separate self-rescheduling job -- one less job to track
        starting/cancelling correctly. Skips re-asserting topmost while an
        alarm is showing so AlarmController's own independent relift loop
        always wins the top z-order contest (see alarm_ui.py's `_relift`)."""
        if not self._gadget_active or is_alarm_active:
            return
        try:
            self.root.lift()
            self.root.attributes("-topmost", True)
        except Exception:  # nosec B110 - best-effort, mirrors AlarmController's own defensive teardown style
            pass

    # -- form actions -----------------------------------------------------------

    def _handle_save(self) -> None:
        payload = {
            "meetingId": self.meeting_id_var.get(),
            "workName": self.work_entry.get(),
            "title": self.title_entry.get(),
            "date": self.date_entry.get().strip(),
            "time": self.time_entry.get().strip(),
            "reminderMinutes": self.reminder_entry.get().strip(),
            "soundProfile": self._sound_label_to_id.get(self._sound_profile_var.get(), "soft"),
            "recurrenceType": self._recurrence_label_to_id.get(self._recurrence_var.get(), "none"),
            "occurrenceCount": self.occurrence_entry.get().strip(),
            "teamsUrl": self.url_entry.get().strip(),
            "notes": self.notes_text.get("1.0", "end").strip(),
        }
        self.callbacks.on_save(payload)

    def _handle_clear(self) -> None:
        self.callbacks.on_clear()

    def _handle_test_sound(self) -> None:
        profile_id = self._sound_label_to_id.get(self._sound_profile_var.get(), "soft")
        self.callbacks.on_test_sound(profile_id)

    def _handle_recurrence_change(self, _value: str) -> None:
        """Port of `updateRecurrenceState()`: "no repetir" always creates
        exactly 1 occurrence (field locked), and picking a recurring type
        seeds a sensible default occurrence count the first time (5 for
        weekdays-only series, 8 for everything else) without clobbering a
        count the user already typed."""
        recurrence_id = self._recurrence_label_to_id.get(self._recurrence_var.get(), "none")
        try:
            current_count = int(self.occurrence_entry.get().strip())
        except ValueError:
            current_count = 0

        if recurrence_id == "none":
            self._set_entry(self.occurrence_entry, "1")
            self.occurrence_entry.configure(state="disabled")
        else:
            self.occurrence_entry.configure(state="normal")
            if current_count < 2:
                default_count = 5 if recurrence_id == "weekdays" else 8
                self._set_entry(self.occurrence_entry, str(default_count))

    def _handle_filter_change(self, display_value: str) -> None:
        actual = self._filter_display_to_value.get(display_value, "all")
        self.callbacks.on_filter_change(actual)

    def _confirm_delete(self, meeting_id: str) -> None:
        if messagebox.askyesno(i18n.t("delete", self.language), i18n.t("deleteConfirm", self.language)):
            self.callbacks.on_delete(meeting_id)

    def _confirm_delete_series(self, meeting_id: str, occurrence_count: int) -> None:
        """Same `messagebox.askyesno` pattern as `_confirm_delete`, deliberate
        different wording (SDD.md v2.11.0): must be unmistakable that this
        removes ALL `occurrence_count` occurrences of the series, past and
        future, not just the one that was right-clicked. `occurrence_count`
        arrives already computed from app.py (via
        `recurrence.group_meetings_by_series`) -- this view never touches
        `self.meetings` to recompute it."""
        title = i18n.t("deleteSeries", self.language)
        message = i18n.format_text("deleteSeriesConfirm", self.language, count=occurrence_count)
        if messagebox.askyesno(title, message):
            self.callbacks.on_delete_series(meeting_id)

    def _confirm_clear_past(self) -> None:
        if messagebox.askyesno(
            i18n.t("clearPastButton", self.language), i18n.t("clearPastConfirm", self.language)
        ):
            self.callbacks.on_clear_past()

    # -- company management -----------------------------------------------------

    def update_company_options(self, names: List[str]) -> None:
        self._companies = list(names)
        self.work_entry["values"] = self._companies
        self._refresh_company_listbox()

    def _open_manage_companies(self) -> None:
        if self._company_dialog is not None:
            self._company_dialog.lift()
            self._company_dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        dialog.title(i18n.t("manageCompaniesTitle", self.language))
        dialog.configure(bg=PANEL_BG)
        dialog.geometry("360x420")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.protocol("WM_DELETE_WINDOW", self._close_manage_companies)
        self._company_dialog = dialog

        tk.Label(
            dialog, text=i18n.t("manageCompaniesHint", self.language), wraplength=320, justify="left",
            bg=PANEL_BG, fg=MUTED, font=(FONT_FAMILY, 10),
        ).pack(anchor="w", padx=14, pady=(14, 8))

        add_row = tk.Frame(dialog, bg=PANEL_BG)
        add_row.pack(fill="x", padx=14)
        new_company_entry = _entry(add_row)
        new_company_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def _add(_event=None) -> None:
            self.callbacks.on_add_company(new_company_entry.get())
            new_company_entry.delete(0, "end")

        new_company_entry.bind("<Return>", _add)
        _button(add_row, i18n.t("addCompanyButton", self.language), _add, ACCENT, ACCENT_FG, ACCENT_HOVER).pack(side="left")

        list_frame = tk.Frame(dialog, bg=PANEL_BG)
        list_frame.pack(fill="both", expand=True, padx=14, pady=10)
        listbox = tk.Listbox(
            list_frame, bg=FIELD_BG, fg=TEXT, selectbackground=ACCENT, selectforeground=ACCENT_FG,
            relief="flat", highlightthickness=1, highlightbackground=BORDER, font=(FONT_FAMILY, 11),
            activestyle="none", disabledforeground=MUTED,
        )
        listbox.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        scrollbar.pack(side="right", fill="y")
        listbox.configure(yscrollcommand=scrollbar.set)
        self._company_listbox = listbox

        def _remove_selected() -> None:
            if not self._companies:
                return
            selection = listbox.curselection()
            if not selection:
                return
            name = listbox.get(selection[0])
            if messagebox.askyesno(
                i18n.t("removeCompanyButton", self.language), i18n.t("removeCompanyConfirm", self.language)
            ):
                self.callbacks.on_remove_company(name)

        bottom_row = tk.Frame(dialog, bg=PANEL_BG)
        bottom_row.pack(fill="x", padx=14, pady=(0, 14))
        _button(
            bottom_row, i18n.t("removeCompanyButton", self.language), _remove_selected, DANGER, "#ffffff", DANGER_HOVER
        ).pack(side="left")
        _button(
            bottom_row, i18n.t("closeButton", self.language), self._close_manage_companies, GHOST_BG, GHOST_FG, GHOST_HOVER
        ).pack(side="right")

        self._refresh_company_listbox()

    def _close_manage_companies(self) -> None:
        if self._company_dialog is not None:
            self._company_dialog.destroy()
            self._company_dialog = None
            self._company_listbox = None

    def _refresh_company_listbox(self) -> None:
        listbox = self._company_listbox
        if listbox is None:
            return
        listbox.configure(state="normal")
        listbox.delete(0, "end")
        if self._companies:
            for name in self._companies:
                listbox.insert("end", name)
        else:
            listbox.insert("end", i18n.t("noCompaniesYet", self.language))
            listbox.configure(state="disabled")

    @staticmethod
    def _set_entry(entry: tk.Entry, value: str) -> None:
        previous_state = entry.cget("state")
        if previous_state == "disabled":
            entry.configure(state="normal")
        entry.delete(0, "end")
        entry.insert(0, value or "")
        if previous_state == "disabled":
            entry.configure(state="disabled")

    def _sound_label_for(self, profile_id: str) -> str:
        return self._sound_id_to_label.get(profile_id, self._sound_id_to_label.get("soft", ""))

    def _recurrence_label_for(self, recurrence_id: str) -> str:
        return self._recurrence_id_to_label.get(recurrence_id, self._recurrence_id_to_label.get("none", ""))

    def populate_form(self, meeting: models.Meeting) -> None:
        self.meeting_id_var.set(meeting.id)
        self._set_entry(self.work_entry, meeting.workName)
        self._set_entry(self.title_entry, meeting.title)
        date_part, _, time_part = meeting.datetime.partition("T")
        self._set_entry(self.date_entry, date_part)
        self._set_entry(self.time_entry, time_part)
        self._set_entry(self.reminder_entry, str(meeting.reminderMinutes))
        self._sound_profile_var.set(self._sound_label_for(meeting.soundProfile))
        self._recurrence_var.set(self._recurrence_label_for(meeting.recurrenceType))
        self._set_entry(self.occurrence_entry, "1")
        self._set_entry(self.url_entry, meeting.teamsUrl)
        self.notes_text.delete("1.0", "end")
        self.notes_text.insert("1.0", meeting.notes)
        self.save_button.configure(text=i18n.t("updateButton", self.language))
        self._handle_recurrence_change(self._recurrence_var.get())

    def clear_form(self) -> None:
        self.meeting_id_var.set("")
        for entry in (self.work_entry, self.title_entry, self.date_entry, self.time_entry, self.url_entry):
            self._set_entry(entry, "")
        self._set_entry(self.reminder_entry, "15")
        self._set_entry(self.occurrence_entry, "1")
        self.notes_text.delete("1.0", "end")
        self._sound_profile_var.set(self._sound_label_for("soft"))
        self._recurrence_var.set(self._recurrence_label_for("none"))
        self.save_button.configure(text=i18n.t("saveButton", self.language))
        self.form_feedback_label.configure(text="")
        self._handle_recurrence_change(self._recurrence_var.get())

    def prefill_new_meeting(self, target_date: date, hour: Optional[int] = None) -> None:
        """Calendar-day-click entry point (SDD.md v2.8.0), extended in
        v2.9.0 for the week view's empty-hour-cell click: reset the form to
        the exact same blank state the "Limpiar" button produces, then set
        the date field -- and, when `hour` is given, the time field to
        `HH:00` -- workName/reminder/sound/recurrence all stay at
        `clear_form`'s defaults either way, no inference beyond date/hour
        from the calendar/week context. `hour` defaults to `None` so the
        month calendar's existing day-click call site (which never has an
        hour to offer) keeps its exact previously-shipped behavior."""
        self.clear_form()
        self._set_entry(self.date_entry, target_date.isoformat())
        if hour is not None:
            self._set_entry(self.time_entry, f"{hour:02d}:00")

    def set_now_values(self, date_str: str, time_str: str) -> None:
        self._set_entry(self.date_entry, date_str)
        self._set_entry(self.time_entry, time_str)
        self.show_form_feedback(i18n.t("formReady", self.language), is_error=False)

    def show_form_feedback(self, message: str, is_error: bool = False) -> None:
        self.form_feedback_label.configure(text=message, fg=("#f87171" if is_error else "#4ade80"))

    def show_toast(self, message: str) -> None:
        if self._toast_window is not None:
            try:
                self._toast_window.destroy()
            except Exception:  # nosec B110 - toast may already be gone; destroying it is best-effort
                pass
        # A background-fired toast (e.g. renewalToast) can land while gadget
        # mode is active; the default full-window sizing/font is wide enough
        # to overflow both edges of the tiny 280px gadget skin, so it shrinks
        # and wraps to fit there instead.
        if self._gadget_active:
            toast = tk.Label(
                self.root, text=message, bg="#2a2e37", fg=TEXT, padx=8, pady=4, font=(FONT_FAMILY, 8),
                wraplength=GADGET_WIDTH - 16, justify="left",
            )
        else:
            toast = tk.Label(
                self.root, text=message, bg="#2a2e37", fg=TEXT, padx=16, pady=8, font=(FONT_FAMILY, 10)
            )
        toast.place(relx=0.5, rely=0.96, anchor="s")
        self._toast_window = toast
        self.root.after(3200, self._hide_toast)

    def _hide_toast(self) -> None:
        if self._toast_window is not None:
            try:
                self._toast_window.destroy()
            except Exception:  # nosec B110 - toast may already be gone; destroying it is best-effort
                pass
            self._toast_window = None

    # -- rendering --------------------------------------------------------------

    def update_clock(self, text: str) -> None:
        self.current_time_card["value"].configure(text=text)
        self.gadget_clock_label.configure(text=text)

    def update_next_alert(self, text: str) -> None:
        self.next_alert_card["value"].configure(text=text)
        self.gadget_next_alert_label.configure(text=_truncate_for_gadget(text))

    def update_stats(self, total: int, today: int, next_meeting_text: str) -> None:
        self.total_card["value"].configure(text=str(total))
        self.today_card["value"].configure(text=str(today))
        self.next_meeting_card["value"].configure(text=next_meeting_text)

    def update_storage_status(self, text: str) -> None:
        for header in self._headers:
            header.storage_chip.configure(text=text)

    def update_filter_options(self, work_names: List[str], selected: str) -> None:
        all_label = i18n.t("allWorks", self.language)
        display_values = [all_label] + list(work_names)
        self._filter_display_to_value = {all_label: "all"}
        for name in work_names:
            self._filter_display_to_value[name] = name
        self._set_option_menu_values(self._filter_menu_widget, self._work_filter_var, display_values, self._handle_filter_change)
        selected_display = selected if selected in work_names else all_label
        self._work_filter_var.set(selected_display)

    def render_meeting_list(self, cards: List[MeetingCardData]) -> None:
        """Incremental: reuses each meeting's existing card widgets across
        calls (keyed by meeting id) instead of destroying and rebuilding the
        whole list every time this runs. Destroying a card with 3 bound
        buttons is not free -- profiled at ~1.5s total for 24 real meetings
        (each `tkinter.Widget.destroy()` deregisters every Tcl command the
        widget's bindings created) -- and this ran synchronously on the UI
        thread every time the heartbeat's skip-if-unchanged check let a
        render through (at least once a minute, since countdown text changes
        on the minute boundary), which was long enough to visibly stall the
        window and make an in-progress resize/move look like it "snapped"
        once Tk finally caught up. Only meetings that appear/disappear (a
        save, delete, or filter change) still pay for real widget churn."""
        if self._card_language != self.language:
            # A language toggle is the one case a per-field .configure()
            # can't reach cleanly (every label and all 3 button texts would
            # need updating) -- rare enough (a deliberate user action, never
            # a per-tick event) that a one-time full rebuild is simpler and
            # cheap relative to how infrequently it happens.
            for widgets in self._card_widgets.values():
                widgets.frame.destroy()
            self._card_widgets.clear()
            self._card_language = self.language

        new_ids = {card_data.meeting.id for card_data in cards}
        for meeting_id in list(self._card_widgets.keys()):
            if meeting_id not in new_ids:
                self._card_widgets.pop(meeting_id).frame.destroy()

        self.meeting_count_label.configure(text=str(len(cards)))

        if not cards:
            if self._empty_state_frame is None:
                empty = tk.Frame(self.meeting_list_frame, bg=PANEL_BG)
                empty.grid(row=0, column=0, sticky="ew", pady=24)
                tk.Label(
                    empty, text=i18n.t("emptyTitle", self.language), font=(FONT_FAMILY, 13, "bold"),
                    bg=PANEL_BG, fg=TEXT,
                ).pack()
                tk.Label(
                    empty, text=i18n.t("emptyBody", self.language), wraplength=320, justify="center",
                    bg=PANEL_BG, fg=MUTED, font=(FONT_FAMILY, 10),
                ).pack(pady=(4, 0))
                self._empty_state_frame = empty
            return

        if self._empty_state_frame is not None:
            self._empty_state_frame.destroy()
            self._empty_state_frame = None

        for row_index, card_data in enumerate(cards):
            widgets = self._card_widgets.get(card_data.meeting.id)
            if widgets is None:
                widgets = self._create_card(card_data.meeting.id, _CARD_PALETTE)
                self._card_widgets[card_data.meeting.id] = widgets
            self._update_card(widgets, row_index, card_data, _CARD_PALETTE)

    def _create_card(self, meeting_id: str, palette: dict) -> _CardWidgets:
        """Widget construction only -- runs once per meeting's lifetime in
        the visible list, not on every refresh. Button commands close over
        `meeting_id`, which never changes for a given card, so they never
        need rebuilding either."""
        card = tk.Frame(self.meeting_list_frame, bg=palette["card_bg"])
        card.grid_columnconfigure(0, weight=1)

        top = tk.Frame(card, bg=palette["card_bg"])
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        top.grid_columnconfigure(1, weight=1)
        work_label = tk.Label(top, fg="black", font=(FONT_FAMILY, 10))
        work_label.grid(row=0, column=0, sticky="w")
        status_label = tk.Label(top, bg=palette["status_bg"], fg=palette["muted_fg"], font=(FONT_FAMILY, 10))
        status_label.grid(row=0, column=1, sticky="e")

        title_label = tk.Label(
            card, font=(FONT_FAMILY, 14, "bold"), anchor="w", justify="left",
            bg=palette["card_bg"], fg=palette["title_fg"],
            # Seeded from the last width `_on_meeting_list_width_change`
            # observed, if any, so a card created mid-session (after the
            # panel's first resize already fired) wraps correctly from its
            # very first render instead of showing one un-wrapped frame at
            # Tk's default (no-wrap) width until the next resize event.
            # `0` (Tk's own "no wraplength configured" default) only when
            # this is the first card ever built, before any real
            # `<Configure>` on the meeting-list panel has fired yet.
            wraplength=self._card_title_wraplength_px or 0,
        )
        title_label.grid(row=1, column=0, sticky="ew", padx=_CARD_TITLE_PADX)

        # Countdown + recurrence share one line (instead of two separate
        # labels) -- one less widget per card and a less cluttered card.
        detail_label = tk.Label(
            card, anchor="w", bg=palette["card_bg"], fg=palette["muted_fg"], font=(FONT_FAMILY, 10),
        )
        detail_label.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 0))

        actions = tk.Frame(card, bg=palette["card_bg"])
        actions.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 10))
        _button(
            actions, i18n.t("openTeams", self.language), lambda mid=meeting_id: self.callbacks.on_open_link(mid),
            palette["button_bg"], palette["button_fg"], palette["button_hover"],
        ).pack(side="left", padx=(0, 6))
        _button(
            actions, i18n.t("edit", self.language), lambda mid=meeting_id: self.callbacks.on_edit(mid),
            palette["ghost_bg"], palette["ghost_fg"], palette["ghost_hover"],
        ).pack(side="left", padx=(0, 6))
        _button(
            actions, i18n.t("delete", self.language), lambda mid=meeting_id: self._confirm_delete(mid),
            palette["danger_bg"], palette["danger_fg"], palette["danger_hover"],
        ).pack(side="left")

        return _CardWidgets(
            frame=card, work_label=work_label, status_label=status_label,
            title_label=title_label, detail_label=detail_label,
        )

    def _update_card(self, widgets: _CardWidgets, row_index: int, card_data: MeetingCardData, palette: dict) -> None:
        """Per-refresh: only re-configures text/color and the grid row --
        no widget creation/destruction, so this is cheap even every second."""
        meeting = card_data.meeting
        widgets.frame.grid(row=row_index, column=0, sticky="ew", pady=6)
        widgets.work_label.configure(text=f" {meeting.workName or '-'} ", bg=card_data.color)
        widgets.status_label.configure(text=f" {i18n.t(card_data.status_key, self.language)} ")
        widgets.title_label.configure(text=meeting.title or "-")
        detail_text = card_data.countdown_text
        if card_data.recurrence_text:
            detail_text = f"{detail_text}  ·  {card_data.recurrence_text}"
        widgets.detail_label.configure(text=detail_text)

    # -- translations -------------------------------------------------------------

    def apply_translations(self, language: str) -> None:
        self.language = language

        def tr(key: str) -> str:
            return i18n.t(key, language)

        self.root.title(tr("appTitle"))
        # All three header instances (full_view's, calendar_view's,
        # week_view's) share this loop -- see `_HeaderWidgets`/`_build_header`
        # for why there are three.
        for header in self._headers:
            header.title_label.configure(text=tr("appTitle"))
            # Not a plain `.configure(text=tr("appSubtitle"))`: the subtitle
            # must stay truncated-to-fit after a language toggle too (the
            # two languages' subtitle strings are different lengths -- see
            # `_HEADER_BUTTON_PADX`'s comment block), so this goes through
            # the same width-aware logic `_schedule_subtitle_update` uses on
            # resize instead of duplicating it here with the untruncated text.
            self._update_header_subtitle(header)
            header.version_chip.configure(text=f"{tr('versionLabel')}: v{__version__}")
            header.notify_button.configure(text=tr("enableNotifications"))
            header.language_button.configure(text="EN" if language == "es" else "ES")
            for button, key in header.view_switch_buttons:
                button.configure(text=tr(key))
            header.gadget_button.configure(text=tr("gadgetModeButton"))
            header.tray_button.configure(text=tr("trayModeButton"))
            header.donate_button.configure(text=tr("buyBeer"))
            header.exit_button.configure(text=tr("exitButton"))

        self.gadget_title_label.configure(text=tr("appTitle"))
        self.gadget_restore_button.configure(text=tr("gadgetRestoreButton"))
        self.gadget_close_button.configure(text=tr("gadgetCloseButton"))

        self.calendar_prev_button.configure(text=tr("calendarPrevMonthButton"))
        self.calendar_next_button.configure(text=tr("calendarNextMonthButton"))
        self.calendar_today_button.configure(text=tr("calendarTodayButton"))

        self.week_prev_button.configure(text=tr("weekPrevButton"))
        self.week_next_button.configure(text=tr("weekNextButton"))
        self.week_today_button.configure(text=tr("weekTodayButton"))
        # Re-derives its own label from the *current* mode rather than a
        # bare fixed key, same reason `language_button` above isn't a plain
        # `tr("...")` either -- its text announces the state a click leads
        # to, and that depends on `self._week_column_mode`, not just which
        # language is active.
        self.week_column_toggle_button.configure(
            text=tr("weekViewFullWeekButton" if self._week_column_mode == "work" else "weekViewWorkWeekButton")
        )
        # Action toolbar (SDD.md v2.11.0) -- "Editar"/"Eliminar" reuse the
        # same `edit`/`delete` keys the meeting cards and context menu
        # already use (no semantic divergence to protect, see SDD.md); only
        # "Agregar" gets its own key since `addCompanyButton` means
        # something semantically different despite matching text today.
        self.week_add_button.configure(text=tr("weekToolbarAddButton"))
        self.week_edit_button.configure(text=tr("edit"))
        self.week_delete_button.configure(text=tr("delete"))

        self.form_eyebrow.configure(text=tr("formEyebrow"))
        self.form_title_label.configure(text=tr("formTitle"))
        self.form_hint_label.configure(text=tr("formHint"))

        self.work_label.configure(text=tr("workLabel"))
        self.manage_companies_button.configure(text=tr("manageCompaniesButton"))
        if self._company_dialog is not None:
            self._company_dialog.title(tr("manageCompaniesTitle"))
        self.title_label_field.configure(text=tr("titleLabel"))
        self.date_label.configure(text=tr("dateOnlyLabel"))
        self.time_label.configure(text=tr("timeOnlyLabel"))
        self.set_now_button.configure(text=tr("setNowButton"))

        self.reminder_label.configure(text=f"{tr('reminderLabel')} ({tr('minutesSuffix')})")
        self.sound_label.configure(text=tr("soundLabel"))
        self.test_sound_button.configure(text=tr("testSoundButton"))

        self.recurrence_label.configure(text=tr("repeatLabel"))
        self.occurrence_label.configure(text=f"{tr('occurrenceCountLabel')} ({tr('occurrenceCountSuffix')})")
        self.recurrence_hint_label.configure(text=tr("recurrenceHint"))

        self.url_label.configure(text=tr("urlLabel"))
        self.notes_label.configure(text=tr("notesLabel"))

        is_editing = bool(self.meeting_id_var.get())
        self.save_button.configure(text=tr("updateButton") if is_editing else tr("saveButton"))
        self.clear_button.configure(text=tr("clearButton"))

        self.stats_eyebrow.configure(text=tr("statsEyebrow"))
        self.stats_title_label.configure(text=tr("statsTitle"))
        self.notification_hint_label.configure(text=tr("notificationHint"))

        self.current_time_card["label"].configure(text=tr("currentTimeLabel"))
        self.next_alert_card["label"].configure(text=tr("nextAlertLabel"))
        self.total_card["label"].configure(text=tr("totalMeetings"))
        self.today_card["label"].configure(text=tr("todayMeetings"))
        self.next_meeting_card["label"].configure(text=tr("activeMeetings"))

        self.filter_label.configure(text=tr("filterLabel"))
        self.clear_past_button.configure(text=tr("clearPastButton"))
        self.list_title_label.configure(text=tr("listTitle"))

        self._rebuild_sound_options(language)
        self._rebuild_recurrence_options(language)

    def _rebuild_sound_options(self, language: str) -> None:
        previous_id = self._sound_label_to_id.get(self._sound_profile_var.get(), "soft")
        self._sound_id_to_label = {pid: i18n.t(key, language) for pid, key in _SOUND_LABEL_KEYS}
        self._sound_label_to_id = {label: pid for pid, label in self._sound_id_to_label.items()}
        self._set_option_menu_values(self._sound_menu_widget, self._sound_profile_var, list(self._sound_id_to_label.values()))
        self._sound_profile_var.set(self._sound_label_for(previous_id))

    def _rebuild_recurrence_options(self, language: str) -> None:
        previous_id = self._recurrence_label_to_id.get(self._recurrence_var.get(), "none")
        self._recurrence_id_to_label = {rid: i18n.t(key, language) for rid, key in _RECURRENCE_LABEL_KEYS}
        self._recurrence_label_to_id = {label: rid for rid, label in self._recurrence_id_to_label.items()}
        self._set_option_menu_values(
            self._recurrence_menu_widget, self._recurrence_var, list(self._recurrence_id_to_label.values()),
            self._handle_recurrence_change,
        )
        self._recurrence_var.set(self._recurrence_label_for(previous_id))
