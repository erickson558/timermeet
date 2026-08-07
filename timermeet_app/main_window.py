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
import tkinter.messagebox as messagebox
import webbrowser
from dataclasses import dataclass
from datetime import date
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
    helper the list view's cards use), so this module stays display-only."""

    meeting_id: str
    time_text: str
    title: str
    color: str


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


@dataclass
class _HeaderWidgets:
    """Widget handles for one instance of the shared header (see
    `_build_header`) -- `full_view` and `calendar_view` each get their own
    instance, so `apply_translations`/`update_storage_status` must loop over
    every entry in `MainWindow._headers` instead of assuming a single set of
    header widgets exists."""

    title_label: tk.Label
    subtitle_label: tk.Label
    version_chip: tk.Label
    storage_chip: tk.Label
    notify_button: tk.Button
    language_button: tk.Button
    calendar_toggle_button: tk.Button
    calendar_toggle_key: str
    gadget_button: tk.Button
    tray_button: tk.Button
    donate_button: tk.Button
    exit_button: tk.Button


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
    on_toggle_calendar_view: Callable[[], None]
    on_calendar_prev_month: Callable[[], None]
    on_calendar_next_month: Callable[[], None]
    on_calendar_today: Callable[[], None]
    on_calendar_day_click: Callable[[date], None]


def _button(parent, text: str, command, bg: str, fg: str, hover: Optional[str] = None, **extra) -> tk.Button:
    hover = hover or bg
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
        relief="flat", borderwidth=0, padx=12, pady=6, cursor="hand2", font=(FONT_FAMILY, 11), **extra,
    )
    btn.bind("<Enter>", lambda _e: btn.configure(bg=hover))
    btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
    return btn


def _entry(parent, **extra) -> tk.Entry:
    return tk.Entry(
        parent, bg=FIELD_BG, fg=TEXT, insertbackground=TEXT, relief="flat",
        highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
        font=(FONT_FAMILY, 11), **extra,
    )


class _ScrollablePanel(tk.Frame):
    """A vertically scrollable container. Children are added to `.body`, not
    to this frame directly; `winfo_children()` is intentionally left
    un-overridden (callers that need to clear rendered content use
    `.body.winfo_children()`)."""

    def __init__(self, parent, bg: str):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
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
            self.canvas.itemconfig(self._window, width=self._pending_canvas_width)

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
        # Which of the two *primary* (non-gadget) sibling frames is the
        # logical "current view" -- read by `set_gadget_mode` on exit so
        # leaving gadget mode restores whichever of list/calendar was active
        # beforehand instead of always jumping back to the list (the bug
        # documented in SDD.md's v2.7.0 section). Only `set_active_view` and
        # `set_gadget_mode` ever change this.
        self._primary_view = "list"
        self._headers: List[_HeaderWidgets] = []
        self._calendar_weekday_labels: List[tk.Label] = []
        self._calendar_cells: List[_CalendarCellWidgets] = []

        self.root.configure(bg=WINDOW_BG)
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
        # root has exactly one grid cell, holding whichever of these three
        # sibling frames is currently gridded -- full_view (the list view:
        # header+form+summary, unchanged), calendar_view (the monthly grid,
        # see `_build_calendar_view`/`set_active_view`), or gadget_view (the
        # borderless mini skin, see `_build_gadget_view`/`set_gadget_mode`).
        # Only one is ever gridded at a time; the other two sit ungridded.
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.full_view = tk.Frame(self.root, bg=WINDOW_BG)
        self.full_view.grid(row=0, column=0, sticky="nsew")
        self.full_view.grid_columnconfigure(0, weight=1)
        self.full_view.grid_rowconfigure(1, weight=1)

        self.full_header = self._build_header(self.full_view, "calendarViewButton")
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

    def _build_header(self, parent, calendar_toggle_key: str) -> _HeaderWidgets:
        """Builds one full copy of the header (title/version/storage chips +
        the Notify/Language/Calendar-toggle/Gadget/Tray/Donate/Exit action
        row) into `parent`, and returns handles to every widget it created
        instead of stashing them on `self` directly -- this is called twice
        (once for `full_view`, once for `calendar_view`, see
        `_build_calendar_view`), and a plain `self.title_label = ...` would
        have the second call silently overwrite the first view's widget
        reference, leaving `full_view`'s header never updated again by
        `apply_translations`/`update_storage_status`. Both call sites keep
        every returned instance in `self._headers` and loop over it instead.
        `calendar_toggle_key` is the only thing that differs between the two
        headers' otherwise-identical action rows: "Vista calendario" on
        `full_view`'s copy, "Vista de lista" on `calendar_view`'s -- both
        buttons share the same `on_toggle_calendar_view` callback (it's a
        toggle), exactly like "Modo gadget"/"Completo" already share
        `on_toggle_gadget_mode`.
        """
        header = tk.Frame(parent, bg=PANEL_BG)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        header.grid_columnconfigure(0, weight=1)

        title_box = tk.Frame(header, bg=PANEL_BG)
        title_box.grid(row=0, column=0, sticky="w", padx=14, pady=14)
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
        actions.grid(row=0, column=1, sticky="e", padx=14, pady=14)
        notify_button = _button(actions, "", self.callbacks.on_test_notification, GHOST_BG, GHOST_FG, GHOST_HOVER)
        notify_button.pack(side="left", padx=4)
        language_button = _button(actions, "EN", self.callbacks.on_toggle_language, GHOST_BG, GHOST_FG, GHOST_HOVER)
        language_button.pack(side="left", padx=4)
        calendar_toggle_button = _button(
            actions, "", self.callbacks.on_toggle_calendar_view, GHOST_BG, GHOST_FG, GHOST_HOVER
        )
        calendar_toggle_button.pack(side="left", padx=4)
        gadget_button = _button(actions, "", self.callbacks.on_toggle_gadget_mode, GHOST_BG, GHOST_FG, GHOST_HOVER)
        gadget_button.pack(side="left", padx=4)
        tray_button = _button(actions, "", self.callbacks.on_enter_tray_mode, GHOST_BG, GHOST_FG, GHOST_HOVER)
        tray_button.pack(side="left", padx=4)
        donate_button = _button(actions, "", self._open_donate, GOLD_BG, GOLD_FG, GOLD_HOVER)
        donate_button.pack(side="left", padx=4)
        # A thin visual gap sets "Salir" apart from the utility buttons --
        # it's the one action in this row that ends the whole app, not just
        # toggles a setting or opens a link, so it shouldn't blend in.
        tk.Frame(actions, bg=PANEL_BG, width=12).pack(side="left")
        exit_button = _button(actions, "", self.callbacks.on_exit, DANGER, "#ffffff", DANGER_HOVER)
        exit_button.pack(side="left", padx=4)

        return _HeaderWidgets(
            title_label=title_label, subtitle_label=subtitle_label, version_chip=version_chip,
            storage_chip=storage_chip, notify_button=notify_button, language_button=language_button,
            calendar_toggle_button=calendar_toggle_button, calendar_toggle_key=calendar_toggle_key,
            gadget_button=gadget_button, tray_button=tray_button, donate_button=donate_button,
            exit_button=exit_button,
        )

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

        list_container = _ScrollablePanel(panel, bg=PANEL_BG)
        list_container.grid(row=5, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.meeting_list_frame = list_container.body
        self.meeting_list_frame.grid_columnconfigure(0, weight=1)

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

        self.calendar_header = self._build_header(self.calendar_view, "listViewButton")
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

    def _primary_view_frame(self) -> tk.Frame:
        return self.calendar_view if self._primary_view == "calendar" else self.full_view

    def set_active_view(self, view: str) -> None:
        """Swap which of `full_view` ("list") / `calendar_view` ("calendar")
        is gridded into root's cell -- the same swap mechanism
        `set_gadget_mode` already uses, just between the two non-gadget
        frames. Also records `_primary_view`, which `set_gadget_mode` reads
        on exit so leaving gadget mode returns to whichever of these two was
        active beforehand instead of unconditionally landing on the list
        (see that method's docstring)."""
        if self._gadget_active:
            # Defensive only: the toggle buttons that call this live in
            # full_view's/calendar_view's own headers, neither of which is
            # reachable while gadget_view is the one gridded frame -- this
            # should never actually fire from the real UI.
            return
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
        # changes every time the user navigates months. Safe from leaking
        # Tcl commands for the identical reason -- gated behind
        # `render_calendar`'s own dirty-check in app.py, whose signature
        # already keys on `cell.day` first, so an unchanged heartbeat tick
        # never reaches this line at all.
        day_click = lambda _e, d=cell_data.day: self._handle_calendar_day_click(d)
        widgets.day_label.bind("<Button-1>", day_click)
        widgets.frame.bind("<Button-1>", day_click)

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
                # changes every time the user navigates months.
                #
                # This is safe from leaking Tcl commands ONLY because
                # `render_calendar` is now gated by app.py's own dirty-check
                # (`_last_rendered_calendar_signature`): repeated `.bind()`
                # calls on the same widget+sequence do NOT release the
                # previous Tcl command on this Tk/Python version -- verified
                # directly, 2000 rebinds left 2000 orphaned entries in
                # `widget._tclCommands`, growing unbounded for as long as the
                # calendar stayed open. Rebinding only happens here when this
                # slot's actual displayed meeting changed (a month
                # navigation, an edit, etc.), not on every idle heartbeat
                # tick with unchanged data -- see app.py's `_refresh_calendar`.
                entry_label.bind(
                    "<Button-1>", lambda _e, mid=entry.meeting_id: self._handle_calendar_entry_click(mid)
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
        # view-toggle back to app.py so its `active_view` bookkeeping (used
        # to skip calendar recompute while the list is showing, see
        # `_refresh_calendar`) stays correct -- reusing the toggle callback
        # is safe here specifically because this can only ever fire while
        # the calendar is already the active view.
        self.callbacks.on_edit(meeting_id)
        self.callbacks.on_toggle_calendar_view()

    def _handle_calendar_day_click(self, day: date) -> None:
        # Mirrors `_handle_calendar_entry_click`'s two-step pattern (data
        # action first, then hand the view-toggle to app.py) -- here the
        # "data action" is preparing a blank form for `day` instead of
        # populating one from an existing meeting. Tkinter doesn't propagate
        # a child widget's click up to its parent, so this only ever fires
        # from a click on the day number or the cell's own empty background,
        # never as a duplicate of an `entry_label` click (see SDD.md v2.8.0).
        self.callbacks.on_calendar_day_click(day)
        self.callbacks.on_toggle_calendar_view()

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

        Which of `full_view`/`calendar_view` gets grid_remove()d on entry and
        grid()ed back on exit is resolved through `_primary_view_frame()`
        (backed by `_primary_view`), not hardcoded to `full_view` -- with a
        third primary view added in v2.7.0, hardcoding it here was a real
        bug: entering gadget mode from the calendar and leaving it again
        used to always land back on the list instead of the calendar. Only
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

    def prefill_new_meeting(self, target_date: date) -> None:
        """Calendar-day-click entry point (SDD.md v2.8.0): reset the form to
        the exact same blank state the "Limpiar" button produces, then set
        only the date field -- workName/time/reminder/sound/recurrence all
        stay at `clear_form`'s defaults, no inference from calendar context."""
        self.clear_form()
        self._set_entry(self.date_entry, target_date.isoformat())

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
            card, font=(FONT_FAMILY, 14, "bold"), anchor="w", bg=palette["card_bg"], fg=palette["title_fg"],
        )
        title_label.grid(row=1, column=0, sticky="ew", padx=12)

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
        # Both header instances (full_view's and calendar_view's) share this
        # loop -- see `_HeaderWidgets`/`_build_header` for why there are two.
        for header in self._headers:
            header.title_label.configure(text=tr("appTitle"))
            header.subtitle_label.configure(text=tr("appSubtitle"))
            header.version_chip.configure(text=f"{tr('versionLabel')}: v{__version__}")
            header.notify_button.configure(text=tr("enableNotifications"))
            header.language_button.configure(text="EN" if language == "es" else "ES")
            header.calendar_toggle_button.configure(text=tr(header.calendar_toggle_key))
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
