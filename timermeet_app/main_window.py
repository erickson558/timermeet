"""Main window: header (title/version/storage/donation/language), the
meeting form, and the summary panel (stats + filter + meeting list).

This module is a view layer only -- all business logic (validation,
persistence, filtering, stats, alarm firing) lives in ``app.py``; here we just
build widgets, expose update/render methods, and forward user actions through
a `Callbacks` bundle. Field layout, labels, and actions mirror
``legacy-php/index.php``.
"""

from __future__ import annotations

import tkinter.messagebox as messagebox
import webbrowser
from dataclasses import dataclass
from typing import Callable, Dict, List

import customtkinter as ctk

from . import __version__, i18n, models, security

DONATE_URL = "https://www.paypal.com/donate/?hosted_button_id=ZABFRXC2P3JQN"

_SOUND_LABEL_KEYS = [
    ("soft", "soundSoft"),
    ("urgent", "soundUrgent"),
    ("alarm", "soundAlarm"),
    ("siren", "soundSiren"),
    ("fire", "soundFireSiren"),
]

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


class MainWindow:
    def __init__(self, root: ctk.CTk, callbacks: Callbacks):
        self.root = root
        self.callbacks = callbacks
        self.language = i18n.DEFAULT_LANGUAGE

        self._sound_profile_var = ctk.StringVar()
        self._recurrence_var = ctk.StringVar()
        self._work_filter_var = ctk.StringVar()
        self._filter_display_to_value: Dict[str, str] = {"": "all"}
        self._sound_id_to_label: Dict[str, str] = {}
        self._sound_label_to_id: Dict[str, str] = {}
        self._recurrence_id_to_label: Dict[str, str] = {}
        self._recurrence_label_to_id: Dict[str, str] = {}
        self._toast_window = None

        self._build_layout()
        self.apply_translations(i18n.DEFAULT_LANGUAGE)
        self.clear_form()

    # -- layout ---------------------------------------------------------------

    def _build_layout(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        self._build_header()

        body = ctk.CTkFrame(self.root, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1, minsize=340)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        self._build_form(body)
        self._build_summary(body)

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.root, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        self.title_label = ctk.CTkLabel(title_box, text="TimerMeet", font=("Segoe UI", 26, "bold"))
        self.title_label.pack(anchor="w")
        self.subtitle_label = ctk.CTkLabel(
            title_box, text="", font=("Segoe UI", 13), text_color=("gray30", "gray70")
        )
        self.subtitle_label.pack(anchor="w", pady=(2, 0))

        chips = ctk.CTkFrame(title_box, fg_color="transparent")
        chips.pack(anchor="w", pady=(10, 0))
        self.version_chip = ctk.CTkLabel(
            chips, text="", fg_color=("gray85", "gray20"), corner_radius=8, padx=10, pady=4
        )
        self.version_chip.pack(side="left", padx=(0, 8))
        self.storage_chip = ctk.CTkLabel(
            chips, text="", fg_color=("gray85", "gray20"), corner_radius=8, padx=10, pady=4
        )
        self.storage_chip.pack(side="left")

        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, sticky="e")
        self.notify_button = ctk.CTkButton(
            actions, text="", width=180, command=self.callbacks.on_test_notification
        )
        self.notify_button.pack(side="left", padx=4)
        self.language_button = ctk.CTkButton(
            actions, text="EN", width=50, command=self.callbacks.on_toggle_language
        )
        self.language_button.pack(side="left", padx=4)
        self.donate_button = ctk.CTkButton(
            actions,
            text="",
            fg_color="#f2c14e",
            hover_color="#e0ad33",
            text_color="#402d00",
            command=self._open_donate,
        )
        self.donate_button.pack(side="left", padx=4)

    def _open_donate(self) -> None:
        if security.is_http_url(DONATE_URL):
            webbrowser.open(DONATE_URL)

    def _add_label(self, parent) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text="", font=("Segoe UI", 12, "bold"), anchor="w")
        label.pack(anchor="w", pady=(0, 2))
        return label

    def _build_form(self, parent) -> None:
        panel = ctk.CTkScrollableFrame(parent, corner_radius=12, label_text="")
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        self.form_eyebrow = ctk.CTkLabel(panel, text="", font=("Segoe UI", 11), text_color=("gray40", "gray60"))
        self.form_eyebrow.pack(anchor="w", pady=(6, 0), padx=6)
        self.form_title_label = ctk.CTkLabel(panel, text="", font=("Segoe UI", 18, "bold"))
        self.form_title_label.pack(anchor="w", pady=(0, 4), padx=6)
        self.form_hint_label = ctk.CTkLabel(
            panel, text="", font=("Segoe UI", 11), text_color=("gray40", "gray60"), wraplength=300, justify="left"
        )
        self.form_hint_label.pack(anchor="w", pady=(0, 12), padx=6)

        self.meeting_id_var = ctk.StringVar(value="")

        self.work_label = self._add_label(panel)
        self.work_entry = ctk.CTkEntry(panel)
        self.work_entry.pack(fill="x", padx=6, pady=(0, 10))

        self.title_label_field = self._add_label(panel)
        self.title_entry = ctk.CTkEntry(panel)
        self.title_entry.pack(fill="x", padx=6, pady=(0, 10))

        date_row = ctk.CTkFrame(panel, fg_color="transparent")
        date_row.pack(fill="x", padx=6, pady=(0, 4))
        date_row.grid_columnconfigure((0, 1), weight=1)
        date_col = ctk.CTkFrame(date_row, fg_color="transparent")
        date_col.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.date_label = self._add_label(date_col)
        self.date_entry = ctk.CTkEntry(date_col, placeholder_text="YYYY-MM-DD")
        self.date_entry.pack(fill="x")
        time_col = ctk.CTkFrame(date_row, fg_color="transparent")
        time_col.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.time_label = self._add_label(time_col)
        self.time_entry = ctk.CTkEntry(time_col, placeholder_text="HH:MM")
        self.time_entry.pack(fill="x")

        self.set_now_button = ctk.CTkButton(panel, text="", command=self.callbacks.on_set_now)
        self.set_now_button.pack(anchor="w", padx=6, pady=(8, 10))

        reminder_row = ctk.CTkFrame(panel, fg_color="transparent")
        reminder_row.pack(fill="x", padx=6, pady=(0, 4))
        reminder_row.grid_columnconfigure((0, 1), weight=1)
        reminder_col = ctk.CTkFrame(reminder_row, fg_color="transparent")
        reminder_col.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.reminder_label = self._add_label(reminder_col)
        self.reminder_entry = ctk.CTkEntry(reminder_col)
        self.reminder_entry.insert(0, "15")
        self.reminder_entry.pack(fill="x")
        sound_col = ctk.CTkFrame(reminder_row, fg_color="transparent")
        sound_col.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.sound_label = self._add_label(sound_col)
        self.sound_menu = ctk.CTkOptionMenu(sound_col, variable=self._sound_profile_var, values=[])
        self.sound_menu.pack(fill="x")

        self.test_sound_button = ctk.CTkButton(panel, text="", command=self._handle_test_sound)
        self.test_sound_button.pack(anchor="w", padx=6, pady=(8, 10))

        recur_row = ctk.CTkFrame(panel, fg_color="transparent")
        recur_row.pack(fill="x", padx=6, pady=(0, 4))
        recur_row.grid_columnconfigure((0, 1), weight=1)
        recur_col = ctk.CTkFrame(recur_row, fg_color="transparent")
        recur_col.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.recurrence_label = self._add_label(recur_col)
        self.recurrence_menu = ctk.CTkOptionMenu(
            recur_col, variable=self._recurrence_var, values=[], command=self._handle_recurrence_change
        )
        self.recurrence_menu.pack(fill="x")
        occ_col = ctk.CTkFrame(recur_row, fg_color="transparent")
        occ_col.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        self.occurrence_label = self._add_label(occ_col)
        self.occurrence_entry = ctk.CTkEntry(occ_col)
        self.occurrence_entry.insert(0, "1")
        self.occurrence_entry.pack(fill="x")

        self.recurrence_hint_label = ctk.CTkLabel(
            panel, text="", font=("Segoe UI", 10), text_color=("gray40", "gray60"), wraplength=300, justify="left"
        )
        self.recurrence_hint_label.pack(anchor="w", padx=6, pady=(4, 10))

        self.url_label = self._add_label(panel)
        self.url_entry = ctk.CTkEntry(panel)
        self.url_entry.pack(fill="x", padx=6, pady=(0, 10))

        self.notes_label = self._add_label(panel)
        self.notes_text = ctk.CTkTextbox(panel, height=80)
        self.notes_text.pack(fill="x", padx=6, pady=(0, 10))

        actions_row = ctk.CTkFrame(panel, fg_color="transparent")
        actions_row.pack(fill="x", padx=6, pady=(4, 4))
        self.save_button = ctk.CTkButton(actions_row, text="", command=self._handle_save)
        self.save_button.pack(side="left", padx=(0, 8))
        self.clear_button = ctk.CTkButton(
            actions_row, text="", fg_color="transparent", border_width=1, command=self._handle_clear
        )
        self.clear_button.pack(side="left")

        self.form_feedback_label = ctk.CTkLabel(panel, text="", wraplength=300, justify="left")
        self.form_feedback_label.pack(anchor="w", padx=6, pady=(8, 12))

    def _build_summary(self, parent) -> None:
        panel = ctk.CTkFrame(parent, corner_radius=12)
        panel.grid(row=0, column=1, sticky="nsew")
        panel.grid_rowconfigure(5, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 4))
        self.stats_eyebrow = ctk.CTkLabel(header, text="", font=("Segoe UI", 11), text_color=("gray40", "gray60"))
        self.stats_eyebrow.pack(anchor="w")
        self.stats_title_label = ctk.CTkLabel(header, text="", font=("Segoe UI", 18, "bold"))
        self.stats_title_label.pack(anchor="w")
        self.notification_hint_label = ctk.CTkLabel(
            header, text="", font=("Segoe UI", 11), text_color=("gray40", "gray60"), wraplength=380, justify="left"
        )
        self.notification_hint_label.pack(anchor="w", pady=(2, 0))

        status_grid = ctk.CTkFrame(panel, fg_color="transparent")
        status_grid.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        status_grid.grid_columnconfigure((0, 1), weight=1)
        self.current_time_card = self._stat_card(status_grid, 0)
        self.next_alert_card = self._stat_card(status_grid, 1)

        stats_grid = ctk.CTkFrame(panel, fg_color="transparent")
        stats_grid.grid(row=2, column=0, sticky="ew", padx=14, pady=4)
        stats_grid.grid_columnconfigure((0, 1, 2), weight=1)
        self.total_card = self._stat_card(stats_grid, 0)
        self.today_card = self._stat_card(stats_grid, 1)
        self.next_meeting_card = self._stat_card(stats_grid, 2)

        toolbar = ctk.CTkFrame(panel, fg_color="transparent")
        toolbar.grid(row=3, column=0, sticky="ew", padx=14, pady=(8, 4))
        self.filter_label = ctk.CTkLabel(toolbar, text="", font=("Segoe UI", 11, "bold"))
        self.filter_label.pack(anchor="w")
        self.filter_menu = ctk.CTkOptionMenu(
            toolbar, variable=self._work_filter_var, values=[""], command=self._handle_filter_change
        )
        self.filter_menu.pack(fill="x", pady=(2, 0))

        list_header = ctk.CTkFrame(panel, fg_color="transparent")
        list_header.grid(row=4, column=0, sticky="ew", padx=14, pady=(8, 4))
        self.list_title_label = ctk.CTkLabel(list_header, text="", font=("Segoe UI", 14, "bold"))
        self.list_title_label.pack(side="left")
        self.meeting_count_label = ctk.CTkLabel(
            list_header, text="0", font=("Segoe UI", 12), text_color=("gray40", "gray60")
        )
        self.meeting_count_label.pack(side="left", padx=(8, 0))

        self.meeting_list_frame = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self.meeting_list_frame.grid(row=5, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.meeting_list_frame.grid_columnconfigure(0, weight=1)

    def _stat_card(self, parent, column: int) -> Dict[str, ctk.CTkLabel]:
        card = ctk.CTkFrame(parent, corner_radius=10, fg_color=("gray92", "gray17"))
        card.grid(row=0, column=column, sticky="ew", padx=4, pady=4)
        label = ctk.CTkLabel(card, text="", font=("Segoe UI", 10), text_color=("gray40", "gray60"))
        label.pack(anchor="w", padx=10, pady=(8, 0))
        value = ctk.CTkLabel(card, text="--", font=("Segoe UI", 15, "bold"))
        value.pack(anchor="w", padx=10, pady=(0, 8))
        return {"label": label, "value": value}

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

    @staticmethod
    def _set_entry(entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value or "")

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
        self.form_feedback_label.configure(text=message, text_color=("#b91c1c" if is_error else "#15803d"))

    def show_toast(self, message: str) -> None:
        if self._toast_window is not None:
            try:
                self._toast_window.destroy()
            except Exception:  # nosec B110 - toast may already be gone; destroying it is best-effort
                pass
        toast = ctk.CTkLabel(
            self.root, text=message, fg_color=("gray20", "gray20"), text_color="white", corner_radius=8, padx=16, pady=8
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

    def update_next_alert(self, text: str) -> None:
        self.next_alert_card["value"].configure(text=text)

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
        self.filter_menu.configure(values=display_values)
        selected_display = selected if selected in work_names else all_label
        self._work_filter_var.set(selected_display)

    def render_meeting_list(self, cards: List[MeetingCardData]) -> None:
        for child in self.meeting_list_frame.winfo_children():
            child.destroy()

        self.meeting_count_label.configure(text=str(len(cards)))

        if not cards:
            empty = ctk.CTkFrame(self.meeting_list_frame, fg_color="transparent")
            empty.grid(row=0, column=0, sticky="ew", pady=24)
            ctk.CTkLabel(empty, text=i18n.t("emptyTitle", self.language), font=("Segoe UI", 14, "bold")).pack()
            ctk.CTkLabel(
                empty,
                text=i18n.t("emptyBody", self.language),
                wraplength=320,
                justify="center",
                text_color=("gray40", "gray60"),
            ).pack(pady=(4, 0))
            return

        for row_index, card_data in enumerate(cards):
            self._render_card(row_index, card_data)

    def _render_card(self, row_index: int, card_data: MeetingCardData) -> None:
        meeting = card_data.meeting
        card = ctk.CTkFrame(self.meeting_list_frame, corner_radius=10, fg_color=("gray95", "gray15"))
        card.grid(row=row_index, column=0, sticky="ew", pady=6)
        card.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        top.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            top, text=meeting.workName or "-", fg_color=card_data.color, corner_radius=6, text_color="black",
            padx=8, pady=2,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            top, text=i18n.t(card_data.status_key, self.language), fg_color=("gray85", "gray25"),
            corner_radius=6, padx=8, pady=2,
        ).grid(row=0, column=1, sticky="e")

        ctk.CTkLabel(card, text=meeting.title or "-", font=("Segoe UI", 15, "bold"), anchor="w").grid(
            row=1, column=0, sticky="ew", padx=12
        )
        ctk.CTkLabel(card, text=card_data.countdown_text, anchor="w", text_color=("gray30", "gray70")).grid(
            row=2, column=0, sticky="ew", padx=12, pady=(2, 0)
        )
        if card_data.recurrence_text:
            ctk.CTkLabel(
                card, text=card_data.recurrence_text, anchor="w", font=("Segoe UI", 11), text_color=("gray40", "gray60")
            ).grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 0))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 10))
        ctk.CTkButton(
            actions, text=i18n.t("openTeams", self.language), width=90,
            command=lambda mid=meeting.id: self.callbacks.on_open_link(mid),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text=i18n.t("edit", self.language), width=70, fg_color="transparent", border_width=1,
            command=lambda mid=meeting.id: self.callbacks.on_edit(mid),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions, text=i18n.t("delete", self.language), width=80, fg_color="#7f1d1d", hover_color="#991b1b",
            command=lambda mid=meeting.id: self._confirm_delete(mid),
        ).pack(side="left")

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
        self.donate_button.configure(text=tr("buyBeer"))

        self.form_eyebrow.configure(text=tr("formEyebrow"))
        self.form_title_label.configure(text=tr("formTitle"))
        self.form_hint_label.configure(text=tr("formHint"))

        self.work_label.configure(text=tr("workLabel"))
        self.work_entry.configure(placeholder_text=tr("workPlaceholder"))
        self.title_label_field.configure(text=tr("titleLabel"))
        self.title_entry.configure(placeholder_text=tr("titlePlaceholder"))
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
        self.list_title_label.configure(text=tr("listTitle"))

        self._rebuild_sound_options(language)
        self._rebuild_recurrence_options(language)

    def _rebuild_sound_options(self, language: str) -> None:
        previous_id = self._sound_label_to_id.get(self._sound_profile_var.get(), "soft")
        self._sound_id_to_label = {pid: i18n.t(key, language) for pid, key in _SOUND_LABEL_KEYS}
        self._sound_label_to_id = {label: pid for pid, label in self._sound_id_to_label.items()}
        self.sound_menu.configure(values=list(self._sound_id_to_label.values()))
        self._sound_profile_var.set(self._sound_label_for(previous_id))

    def _rebuild_recurrence_options(self, language: str) -> None:
        previous_id = self._recurrence_label_to_id.get(self._recurrence_var.get(), "none")
        self._recurrence_id_to_label = {rid: i18n.t(key, language) for rid, key in _RECURRENCE_LABEL_KEYS}
        self._recurrence_label_to_id = {label: rid for rid, label in self._recurrence_id_to_label.items()}
        self.recurrence_menu.configure(values=list(self._recurrence_id_to_label.values()))
        self._recurrence_var.set(self._recurrence_label_for(previous_id))
