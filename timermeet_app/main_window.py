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

        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

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
        # root has exactly one grid cell, holding whichever of these two
        # sibling frames is currently gridded -- full_view (today's whole
        # header+form+summary layout, unchanged) or gadget_view (the
        # borderless mini skin, see `_build_gadget_view`/`set_gadget_mode`).
        # Only one is ever gridded at a time; the other sits ungridded.
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.full_view = tk.Frame(self.root, bg=WINDOW_BG)
        self.full_view.grid(row=0, column=0, sticky="nsew")
        self.full_view.grid_columnconfigure(0, weight=1)
        self.full_view.grid_rowconfigure(1, weight=1)

        self._build_header(self.full_view)

        body = tk.Frame(self.full_view, bg=WINDOW_BG)
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1, minsize=340)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        self._build_form(body)
        self._build_summary(body)

        self._build_gadget_view()

    def _build_header(self, parent) -> None:
        header = tk.Frame(parent, bg=PANEL_BG)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        header.grid_columnconfigure(0, weight=1)

        title_box = tk.Frame(header, bg=PANEL_BG)
        title_box.grid(row=0, column=0, sticky="w", padx=14, pady=14)
        self.title_label = tk.Label(
            title_box, text="TimerMeet", font=(FONT_FAMILY, 24, "bold"), bg=PANEL_BG, fg=TEXT,
        )
        self.title_label.pack(anchor="w")
        self.subtitle_label = tk.Label(
            title_box, text="", font=(FONT_FAMILY, 12), bg=PANEL_BG, fg=MUTED,
        )
        self.subtitle_label.pack(anchor="w", pady=(2, 0))

        chips = tk.Frame(title_box, bg=PANEL_BG)
        chips.pack(anchor="w", pady=(10, 0))
        self.version_chip = tk.Label(
            chips, text="", bg=CHIP_BG, fg=MUTED, padx=10, pady=4, font=(FONT_FAMILY, 10),
        )
        self.version_chip.pack(side="left", padx=(0, 8))
        self.storage_chip = tk.Label(
            chips, text="", bg=CHIP_BG, fg=MUTED, padx=10, pady=4, font=(FONT_FAMILY, 10),
        )
        self.storage_chip.pack(side="left")

        actions = tk.Frame(header, bg=PANEL_BG)
        actions.grid(row=0, column=1, sticky="e", padx=14, pady=14)
        self.notify_button = _button(actions, "", self.callbacks.on_test_notification, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.notify_button.pack(side="left", padx=4)
        self.language_button = _button(actions, "EN", self.callbacks.on_toggle_language, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.language_button.pack(side="left", padx=4)
        self.gadget_button = _button(actions, "", self.callbacks.on_toggle_gadget_mode, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.gadget_button.pack(side="left", padx=4)
        self.tray_button = _button(actions, "", self.callbacks.on_enter_tray_mode, GHOST_BG, GHOST_FG, GHOST_HOVER)
        self.tray_button.pack(side="left", padx=4)
        self.donate_button = _button(actions, "", self._open_donate, GOLD_BG, GOLD_FG, GOLD_HOVER)
        self.donate_button.pack(side="left", padx=4)
        # A thin visual gap sets "Salir" apart from the utility buttons --
        # it's the one action in this row that ends the whole app, not just
        # toggles a setting or opens a link, so it shouldn't blend in.
        tk.Frame(actions, bg=PANEL_BG, width=12).pack(side="left")
        self.exit_button = _button(actions, "", self.callbacks.on_exit, DANGER, "#ffffff", DANGER_HOVER)
        self.exit_button.pack(side="left", padx=4)

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
        synchronous call. AlarmController's overlay/dialog need no special
        handling here: they're independent, non-transient Toplevels (see
        alarm_ui.py) whose own visibility never depended on root's mapped
        state, size, or decoration -- only on their own attributes."""
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
            self.full_view.grid_remove()
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
            self.full_view.grid(row=0, column=0, sticky="nsew")
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
        self.storage_chip.configure(text=text)

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
        self.title_label.configure(text=tr("appTitle"))
        self.subtitle_label.configure(text=tr("appSubtitle"))
        self.version_chip.configure(text=f"{tr('versionLabel')}: v{__version__}")

        self.notify_button.configure(text=tr("enableNotifications"))
        self.language_button.configure(text="EN" if language == "es" else "ES")
        self.gadget_button.configure(text=tr("gadgetModeButton"))
        self.tray_button.configure(text=tr("trayModeButton"))
        self.donate_button.configure(text=tr("buyBeer"))
        self.exit_button.configure(text=tr("exitButton"))

        self.gadget_title_label.configure(text=tr("appTitle"))
        self.gadget_restore_button.configure(text=tr("gadgetRestoreButton"))
        self.gadget_close_button.configure(text=tr("gadgetCloseButton"))

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
