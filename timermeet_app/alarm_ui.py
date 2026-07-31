"""Alarm presentation: the one-shot alert dialog + the persistent, must-dismiss
alarm overlay, plus the title-bar blink. Both windows are shown together
whenever a meeting's reminder or start alert fires (see
``app.py::TimerMeetApp._notify_meeting``), mirroring the original web app's
redundant "can't miss it" design (modal dialog + full-page overlay + OS
notification, all at once, see ``legacy-php/assets/app.js::notifyMeeting``).
"""

from __future__ import annotations

import webbrowser
from typing import Callable, Optional

import customtkinter as ctk

from . import audio, i18n, notifications, security

_FLASH_COLORS = ("#b91c1c", "#7f1d1d")
_FLASH_INTERVAL_MS = 700
_RELIFT_INTERVAL_MS = 2000
_TITLE_BLINK_INTERVAL_MS = 850


class AlarmController:
    """Owns the single active alarm (if any) for the whole app: the sound
    player, the alert dialog, the persistent overlay, and the title-bar
    blink. Firing a new alert always replaces whatever is currently active
    rather than stacking, matching the original app."""

    def __init__(self, root: ctk.CTk, get_language: Callable[[], str]):
        self._root = root
        self._get_language = get_language
        self._player = audio.AlarmPlayer()

        self._dialog: Optional[ctk.CTkToplevel] = None
        self._overlay: Optional[ctk.CTkToplevel] = None
        self._flash_container = None
        self._flash_state = False
        self._flash_job = None
        self._relift_job = None
        self._title_blink_job = None
        self._blink_on = False

        self._current_url = ""
        self._base_title = "TimerMeet"
        self._on_dismiss: Optional[Callable[[], None]] = None

    def set_base_title(self, title: str) -> None:
        self._base_title = title

    def is_active(self) -> bool:
        return self._overlay is not None

    def test_play(self, profile_id: str) -> None:
        """One-shot preview for the form's "Probar sonido" button. Reuses
        the same player as a live alarm, so -- exactly like the original
        `testSelectedSound()` -- previewing a sound while a real alarm is
        ringing stops that alarm's audio too (the overlay/dialog stay open,
        just silently, until dismissed)."""
        self._player.play(profile_id, "reminder", loop=False)

    def notify(self, meeting, mode: str, on_dismiss: Callable[[], None]) -> None:
        """Fire all three channels for one meeting: sound + overlay, the
        one-shot dialog, and a best-effort native OS toast. `mode` is
        "reminder" or "start"."""
        self.dismiss(run_callback=False)
        self._on_dismiss = on_dismiss
        language = self._get_language()
        self._current_url = meeting.teamsUrl if security.is_http_url(meeting.teamsUrl) else ""

        title_key = "alertReminderTitle" if mode == "reminder" else "alertStartTitle"
        tag_key = "alertDialogReminderTag" if mode == "reminder" else "alertDialogStartTag"
        title_text = i18n.t(title_key, language)
        body_text = f"{meeting.workName} · {meeting.title}".strip(" ·")
        when = meeting.local_datetime()
        meta_text = i18n.format_datetime_display(when, language) if when else ""

        self._player.play(meeting.soundProfile, mode, loop=True)
        self._show_overlay(language, tag_key, title_text, body_text, meta_text)
        self._show_dialog(language, tag_key, title_text, body_text)
        self._start_title_blink(title_text)
        notifications.notify(title_text, body_text)

    def open_link(self) -> None:
        if self._current_url and security.is_http_url(self._current_url):
            webbrowser.open(self._current_url)
        self.dismiss()

    def dismiss(self, run_callback: bool = True) -> None:
        self._player.stop()

        # Every teardown step below is best-effort: dismiss() must always
        # fully clear alarm state even if a widget was already destroyed by
        # the window manager (e.g. the user closed the overlay directly) or
        # a Tkinter job id is already stale -- a raised exception here would
        # leave the alarm "stuck" active, which is worse than ignoring it.
        for attr in ("_flash_job", "_title_blink_job", "_relift_job"):
            job = getattr(self, attr)
            if job is not None:
                try:
                    self._root.after_cancel(job)
                except Exception:  # nosec B110
                    pass
                setattr(self, attr, None)

        if self._dialog is not None:
            try:
                self._dialog.grab_release()
            except Exception:  # nosec B110
                pass
            try:
                self._dialog.destroy()
            except Exception:  # nosec B110
                pass
            self._dialog = None

        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:  # nosec B110
                pass
            self._overlay = None

        try:
            self._root.title(self._base_title)
        except Exception:  # nosec B110
            pass

        callback = self._on_dismiss
        self._on_dismiss = None
        if run_callback and callback is not None:
            callback()

    # -- window construction -------------------------------------------------

    def _show_overlay(self, language, tag_key, title_text, body_text, meta_text) -> None:
        overlay = ctk.CTkToplevel(self._root)
        overlay.title(i18n.t("alarmOverlayTag", language))
        overlay.geometry("560x340")
        overlay.attributes("-topmost", True)
        overlay.protocol("WM_DELETE_WINDOW", self.dismiss)

        container = ctk.CTkFrame(overlay, fg_color=_FLASH_COLORS[0], corner_radius=0)
        container.pack(fill="both", expand=True)

        ctk.CTkLabel(
            container, text=i18n.t(tag_key, language), font=("Segoe UI", 14, "bold"), text_color="white"
        ).pack(pady=(28, 4))
        ctk.CTkLabel(
            container, text=title_text, font=("Segoe UI", 22, "bold"), text_color="white", wraplength=480
        ).pack(pady=(0, 8))
        ctk.CTkLabel(
            container, text=body_text, font=("Segoe UI", 14), text_color="white", wraplength=480
        ).pack(pady=(0, 4))
        if meta_text:
            ctk.CTkLabel(
                container, text=meta_text, font=("Segoe UI", 12), text_color="#fecaca"
            ).pack(pady=(0, 4))
        ctk.CTkLabel(
            container,
            text=i18n.t("alarmOverlayHint", language),
            font=("Segoe UI", 11),
            text_color="#fecaca",
            wraplength=480,
        ).pack(pady=(4, 18))

        buttons = ctk.CTkFrame(container, fg_color="transparent")
        buttons.pack(pady=(0, 24))
        ctk.CTkButton(
            buttons,
            text=i18n.t("openTeams", language),
            command=self.open_link,
            state="normal" if self._current_url else "disabled",
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            buttons,
            text=i18n.t("dismissAlarm", language),
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            command=self.dismiss,
        ).pack(side="left", padx=8)

        self._overlay = overlay
        self._flash_container = container
        self._flash_state = False
        self._flash_overlay()
        self._relift()

    def _show_dialog(self, language, tag_key, title_text, body_text) -> None:
        dialog = ctk.CTkToplevel(self._root)
        dialog.title(i18n.t(tag_key, language))
        dialog.geometry("420x220")
        dialog.attributes("-topmost", True)
        dialog.protocol("WM_DELETE_WINDOW", self.dismiss)

        ctk.CTkLabel(dialog, text=i18n.t(tag_key, language), font=("Segoe UI", 12, "bold")).pack(pady=(20, 4))
        ctk.CTkLabel(dialog, text=title_text, font=("Segoe UI", 16, "bold"), wraplength=360).pack(pady=(0, 8))
        ctk.CTkLabel(dialog, text=body_text, wraplength=360).pack(pady=(0, 16))

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.pack(pady=(0, 16))
        ctk.CTkButton(
            buttons,
            text=i18n.t("alertDialogOpen", language),
            command=self.open_link,
            state="normal" if self._current_url else "disabled",
        ).pack(side="left", padx=8)
        ctk.CTkButton(buttons, text=i18n.t("alertDialogClose", language), command=self.dismiss).pack(
            side="left", padx=8
        )

        try:
            dialog.grab_set()
        except Exception:  # nosec B110 - modal grab is a nicety, not required for the alarm to work
            pass
        self._dialog = dialog

    # -- periodic effects ------------------------------------------------------

    def _flash_overlay(self) -> None:
        if self._overlay is None:
            return
        self._flash_state = not self._flash_state
        try:
            self._flash_container.configure(fg_color=_FLASH_COLORS[int(self._flash_state)])
        except Exception:
            return
        self._flash_job = self._root.after(_FLASH_INTERVAL_MS, self._flash_overlay)

    def _relift(self) -> None:
        """Periodically re-raise the overlay so it can't be buried under
        other windows or the taskbar while an alarm is active."""
        if self._overlay is None:
            return
        try:
            self._overlay.deiconify()
            self._overlay.lift()
            self._overlay.attributes("-topmost", True)
        except Exception:
            return
        self._relift_job = self._root.after(_RELIFT_INTERVAL_MS, self._relift)

    def _start_title_blink(self, alert_title: str) -> None:
        def _tick() -> None:
            if self._overlay is None:
                return
            self._blink_on = not self._blink_on
            try:
                self._root.title(f"{alert_title} | {self._base_title}" if self._blink_on else self._base_title)
            except Exception:
                return
            self._title_blink_job = self._root.after(_TITLE_BLINK_INTERVAL_MS, _tick)

        _tick()
