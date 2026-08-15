"""Alarm presentation: the persistent, must-dismiss alarm overlay plus the
title-bar blink. Shown whenever a meeting's reminder or start alert fires
(see ``app.py::TimerMeetApp._notify_meeting``), alongside the alarm sound and
a best-effort OS notification (see ``notifications.py``) -- three redundant
"can't miss it" channels per alert, same intent as the original web app's
modal dialog + full-page overlay + OS notification combo (see
``legacy-php/assets/app.js::notifyMeeting``), minus the modal dialog: a
second on-screen window duplicating the overlay's own title/body/buttons
added visual clutter without covering any case the overlay didn't already
handle (the overlay re-lifts itself every ``_RELIFT_INTERVAL_MS`` so it can't
be silently buried, which is strictly stronger than a one-shot modal grab).

Built with plain ``tkinter`` (not CustomTkinter) so an alarm firing for the
first time is never delayed by CustomTkinter's deferred widget-realization
cost (see ``main_window.py``'s module docstring) -- an alarm must appear
instantly, every time.
"""

from __future__ import annotations

import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from typing import Callable, Optional

from . import audio, i18n, notifications, security

_FLASH_COLORS = ("#b91c1c", "#7f1d1d")
_FLASH_INTERVAL_MS = 700
_RELIFT_INTERVAL_MS = 2000
_TITLE_BLINK_INTERVAL_MS = 850

# v2.16.1 visual overhaul: the previous layout put every label (tag, title,
# body, meta, hint, buttons) directly on `container` -- the same frame whose
# `bg` alternates between `_FLASH_COLORS` every `_FLASH_INTERVAL_MS`. Two
# real, reported problems came from that: (1) every label's own flat `bg`
# read as a separate disconnected "chip" rather than one cohesive alert, and
# (2) the old dismiss button's color (`_DANGER_BG = "#7f1d1d"`) was IDENTICAL
# to `_FLASH_COLORS[1]` -- for half of every flash cycle the button visually
# vanished into the background it sat on, which is very likely what read as
# "looks like plain text" rather than a real button.
#
# Fix: split "the flashing attention-grabbing halo" from "the readable
# content" into two layers. `container` (still the thing `_flash_overlay`
# toggles) is now only ever seen as a thin border/glow around a second,
# STATIC-background `card` frame that holds all text and both buttons --
# so nothing the user needs to read or click ever changes color underneath
# them, and no button color is chosen to coincide with a flash color.
_CARD_BG = "#2a0505"
_CARD_BORDER = "#ef4444"
_ACCENT_STRIP_COLORS = ("#ef4444", "#fca5a5")
_TAG_BADGE_BG = "#ef4444"
_TAG_BADGE_FG = "#2a0505"
_DIVIDER_COLOR = "#5b1414"

_TEXT_ON_RED = "white"
_MUTED_ON_RED = "#fecaca"
_BUTTON_BG = "#3b82f6"
_BUTTON_HOVER = "#2563eb"
# Deliberately the same red family as `main_window.DANGER`/`DANGER_HOVER`
# for brand consistency, but chosen without regard for `_FLASH_COLORS`
# above -- safe now because this button lives on the static `_CARD_BG`
# card, never on the flashing `container`, so it can never blend in.
_DANGER_BG = "#b91c1c"
_DANGER_HOVER = "#991b1b"


def _alarm_button(parent, text: str, command, bg: str, hover: str, state: str = "normal") -> tk.Button:
    # pady=13 (not the app's usual 10) is a measured floor, not a style
    # preference: Segoe UI 11pt bold plus this padding clears the ~45px
    # minimum touch/click target height the redesign calls for.
    btn = tk.Button(
        parent, text=text, command=command, bg=bg, fg="white", activebackground=hover, activeforeground="white",
        disabledforeground=_MUTED_ON_RED, relief="flat", borderwidth=0, padx=18, pady=13, cursor="hand2",
        font=("Segoe UI", 11, "bold"), state=state, highlightthickness=1, highlightbackground=_CARD_BORDER,
    )
    if state != "disabled":
        btn.bind("<Enter>", lambda _e: btn.configure(bg=hover))
        btn.bind("<Leave>", lambda _e: btn.configure(bg=bg))
    return btn


def _format_countdown(delta: timedelta) -> str:
    """``MM:SS`` (or ``HH:MM:SS`` past an hour) for the alarm's live
    countdown -- always non-negative, the caller decides which side of "now"
    ``delta`` came from."""
    total_seconds = max(0, int(delta.total_seconds()))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


class AlarmController:
    """Owns the currently-showing alarm (if any) for the whole app: the sound
    player, the persistent overlay, and the title-bar blink.

    A second alert firing while one is already on screen is queued (FIFO)
    rather than replacing the active one. An earlier version tore down
    whatever was showing every time `notify()` was called (matching the
    original app's `startAlarmSequence`) -- but `app.py::_process_alerts`
    marks a meeting's alert "sent" immediately after calling `notify()`, so
    when two meetings became due in the same 1-second heartbeat tick (e.g.
    two meetings both starting at 9:00), the first one's overlay/sound was
    silently destroyed before the user ever saw it, and it could never fire
    again -- a permanent, silent loss of a notification. Queueing instead
    means the first alert keeps ringing undisturbed and the second is shown
    automatically, back-to-back, the instant the first is dismissed."""

    def __init__(self, root: tk.Tk, get_language: Callable[[], str]):
        self._root = root
        self._get_language = get_language
        self._player = audio.AlarmPlayer()

        self._overlay: Optional[tk.Toplevel] = None
        self._flash_container = None
        # Thin strip at the top of the static card (see `_CARD_BG` note
        # above) that pulses in sync with `_flash_container`'s own halo --
        # keeps the "still ringing, still urgent" motion cue alive even
        # though the text/buttons underneath no longer change color.
        self._flash_accent = None
        self._flash_state = False
        self._flash_job = None
        self._relift_job = None
        self._title_blink_job = None
        self._blink_on = False

        # Live "starts in / started ago" countdown (v2.17.0): its own
        # `after()` chain, separate from `_flash_job`, because it needs
        # whole-second precision independent of the 700ms flash cadence.
        self._countdown_label = None
        self._indicator_label = None
        self._current_meeting_start: Optional[datetime] = None
        self._countdown_job = None

        self._current_url = ""
        self._base_title = "TimerMeet"
        self._on_dismiss: Optional[Callable[[], None]] = None
        # FIFO of (meeting, mode, on_dismiss) tuples still waiting to be
        # shown -- see class docstring. Never re-ordered, capped, or
        # deduplicated: multiple meetings due in the exact same second is a
        # rare edge case, not a hot path worth extra machinery.
        self._queue: list = []

    def set_base_title(self, title: str) -> None:
        self._base_title = title

    def is_active(self) -> bool:
        return self._overlay is not None

    def warm_cache(self) -> None:
        """Sanity-check the siren/fire MP3s exist so a missing asset is
        logged early instead of discovered mid-alarm. Safe to call from a
        background thread (touches only the filesystem, never a Tkinter
        widget)."""
        audio.preload(self._player)

    def test_play(self, profile_id: str) -> None:
        """One-shot preview for the form's "Probar sonido" button. Reuses
        the same player as a live alarm, so -- exactly like the original
        `testSelectedSound()` -- previewing a sound while a real alarm is
        ringing stops that alarm's audio too (the overlay stays open, just
        silently, until dismissed)."""
        self._player.play(profile_id, "reminder", loop=False)

    def notify(self, meeting, mode: str, on_dismiss: Callable[[], None]) -> None:
        """Fire all three channels for one meeting: sound + overlay, and a
        best-effort native OS toast. `mode` is "reminder" or "start". If an
        alarm is already on screen, this one is queued instead -- see class
        docstring -- and will be presented automatically once the active
        one is dismissed."""
        if self.is_active():
            self._queue.append((meeting, mode, on_dismiss))
            return
        self._present(meeting, mode, on_dismiss)

    def _present(self, meeting, mode: str, on_dismiss: Callable[[], None]) -> None:
        """Actually build and show the sound + overlay + title-blink + OS
        toast for one meeting. Called by `notify()` when nothing is
        currently active, and again by `dismiss()` to present the next
        queued alert immediately after the previous one finishes tearing
        down."""
        self._on_dismiss = on_dismiss
        language = self._get_language()
        self._current_url = meeting.teamsUrl if security.is_http_url(meeting.teamsUrl) else ""

        title_key = "alertReminderTitle" if mode == "reminder" else "alertStartTitle"
        tag_key = "alertReminderTag" if mode == "reminder" else "alertStartTag"
        title_text = i18n.t(title_key, language)
        body_text = f"{meeting.workName} · {meeting.title}".strip(" ·")
        when = meeting.local_datetime()
        meta_text = i18n.format_datetime_display(when, language) if when else ""
        self._current_meeting_start = when

        self._player.play(meeting.soundProfile, mode, loop=True)
        self._show_overlay(language, tag_key, title_text, body_text, meta_text)
        self._start_title_blink(title_text)
        notifications.notify(title_text, body_text)

    def open_link(self) -> None:
        if self._current_url and security.is_http_url(self._current_url):
            webbrowser.open(self._current_url)
        self.dismiss()

    def dismiss(self, run_callback: bool = True, advance_queue: bool = True) -> None:
        self._player.stop()

        # Every teardown step below is best-effort: dismiss() must always
        # fully clear alarm state even if a widget was already destroyed by
        # the window manager (e.g. the user closed the overlay directly) or
        # a Tkinter job id is already stale -- a raised exception here would
        # leave the alarm "stuck" active, which is worse than ignoring it.
        for attr in ("_flash_job", "_title_blink_job", "_relift_job", "_countdown_job"):
            job = getattr(self, attr)
            if job is not None:
                try:
                    self._root.after_cancel(job)
                except Exception:  # nosec B110
                    pass
                setattr(self, attr, None)

        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:  # nosec B110
                pass
            self._overlay = None
        self._countdown_label = None
        self._indicator_label = None
        self._current_meeting_start = None

        try:
            self._root.title(self._base_title)
        except Exception:  # nosec B110
            pass

        # Capture the outgoing alert's callback and clear it now, but do
        # NOT invoke it yet -- see below. If we invoke it here (the old
        # order), it runs while self._overlay is still None and the next
        # queued alert hasn't been presented, so any caller that checks
        # is_active() from inside the callback (e.g. app.py::_refresh_all
        # -> keep_gadget_on_top(self.alarms.is_active())) observably sees
        # "no alarm active" for one call even though another alert is a
        # single line away from appearing -- a real, empirically-confirmed
        # bug. Presenting the next alert (if any) *before* firing the
        # callback means self._overlay already reflects the post-hand-off
        # state by the time the callback runs.
        callback = self._on_dismiss
        self._on_dismiss = None

        if not advance_queue:
            # Shutdown path (app.py::_on_close calls dismiss(advance_queue=
            # False) while destroying the root window): drop any still-
            # pending alerts outright rather than leaving them for some
            # future dismiss() to pop -- there will be no live root to
            # parent a new Toplevel to.
            self._queue.clear()
        elif self._queue:
            # Show the next queued alert immediately, in the same call --
            # no Tkinter mainloop turn happens between the teardown above
            # and _present() below, so is_active() (self._overlay is not
            # None) is already True again by the time the outgoing
            # callback (fired below) runs.
            next_meeting, next_mode, next_on_dismiss = self._queue.pop(0)
            self._present(next_meeting, next_mode, next_on_dismiss)

        if run_callback and callback is not None:
            callback()

    # -- window construction -------------------------------------------------

    def _show_overlay(self, language, tag_key, title_text, body_text, meta_text) -> None:
        overlay = tk.Toplevel(self._root)
        overlay.title(i18n.t("alarmOverlayTag", language))
        # 620x460 (was 600x380): still within the compact 600-700px width
        # target, but the height was measured up to fit the countdown +
        # pulse-indicator lines added in v2.17.0 without cramping the
        # existing content.
        overlay.geometry("620x460")
        overlay.resizable(False, False)
        overlay.attributes("-topmost", True)
        overlay.protocol("WM_DELETE_WINDOW", self.dismiss)
        # Esc must never dismiss an active alarm (only the two explicit
        # buttons/shortcuts below may) -- "break" consumes the key so no
        # ancestor/default binding can act on it either.
        overlay.bind("<Escape>", lambda _e: "break")

        # Outer "halo": the only thing whose color `_flash_overlay` ever
        # toggles now. It fills the whole window and is visible only as a
        # thin pulsing border around `card` (below), never behind readable
        # text/buttons -- see the module-level comment above `_CARD_BG`.
        container = tk.Frame(overlay, bg=_FLASH_COLORS[0])
        container.pack(fill="both", expand=True)

        card = tk.Frame(container, bg=_CARD_BG, highlightthickness=2, highlightbackground=_CARD_BORDER)
        card.pack(fill="both", expand=True, padx=16, pady=16)

        accent_strip = tk.Frame(card, bg=_ACCENT_STRIP_COLORS[0], height=5)
        accent_strip.pack(fill="x", side="top")
        accent_strip.pack_propagate(False)

        content = tk.Frame(card, bg=_CARD_BG)
        content.pack(fill="both", expand=True, padx=28, pady=(20, 22))

        # Tag as a small solid "badge" (one intentional chip, not several
        # disconnected ones) so it visually reads as a category label sitting
        # above the actual headline below it, rather than a second headline.
        tk.Label(
            content, text=i18n.t(tag_key, language).upper(), font=("Segoe UI", 10, "bold"),
            fg=_TAG_BADGE_FG, bg=_TAG_BADGE_BG, padx=10, pady=3,
        ).pack(anchor="w", pady=(0, 12))

        tk.Label(
            content, text=title_text, font=("Segoe UI", 22, "bold"), fg=_TEXT_ON_RED, bg=_CARD_BG,
            wraplength=500, justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 6))
        tk.Label(
            content, text=body_text, font=("Segoe UI", 14), fg=_TEXT_ON_RED, bg=_CARD_BG, wraplength=500,
            justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 2))
        if meta_text:
            tk.Label(
                content, text=meta_text, font=("Segoe UI", 11), fg=_MUTED_ON_RED, bg=_CARD_BG, anchor="w",
            ).pack(fill="x", pady=(0, 4))

        # Live countdown ("Starts in 04:32" / "Meeting started 00:15 ago"),
        # updated once a second via its own `after()` chain (see
        # `_update_countdown`) -- independent of `_flash_job`'s 700ms
        # cadence since this needs whole-second precision, not a flash beat.
        self._countdown_label = tk.Label(
            content, text="", font=("Segoe UI", 12, "bold"), fg=_TEXT_ON_RED, bg=_CARD_BG, anchor="w",
        )
        self._countdown_label.pack(fill="x", pady=(2, 6))

        # "ALARMA ACTIVA" pulse indicator: rides the same `_flash_job` tick
        # as the accent strip/halo (see `_flash_overlay`) so it pulses in
        # sync with the rest of the "still ringing" motion cue, without a
        # third independent timer -- the countdown above is the only piece
        # that genuinely needs its own cadence.
        self._indicator_label = tk.Label(
            content, text=f"● {i18n.t('alarmActiveIndicator', language)}", font=("Segoe UI", 9, "bold"),
            fg=_ACCENT_STRIP_COLORS[0], bg=_CARD_BG, anchor="w",
        )
        self._indicator_label.pack(fill="x", pady=(0, 4))

        tk.Frame(content, bg=_DIVIDER_COLOR, height=1).pack(fill="x", pady=(14, 12))

        tk.Label(
            content, text=i18n.t("alarmOverlayHint", language), font=("Segoe UI", 10), fg=_MUTED_ON_RED,
            bg=_CARD_BG, wraplength=500, justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 18))

        buttons = tk.Frame(content, bg=_CARD_BG)
        buttons.pack(anchor="w")
        _alarm_button(
            buttons, i18n.t("openTeams", language), self.open_link, _BUTTON_BG, _BUTTON_HOVER,
            state="normal" if self._current_url else "disabled",
        ).pack(side="left", padx=(0, 10))
        _alarm_button(
            buttons, i18n.t("dismissAlarm", language), self.dismiss, _DANGER_BG, _DANGER_HOVER,
        ).pack(side="left")

        self._overlay = overlay
        self._flash_container = container
        self._flash_accent = accent_strip
        self._flash_state = False
        self._flash_overlay()
        self._relift()
        self._update_countdown()

        # Keyboard shortcuts: Enter = Open Teams (only when a real link is
        # available, mirroring the button's own disabled state -- otherwise
        # Enter would silently dismiss the alarm without opening anything),
        # Alt+S = Silence alarm. Esc is deliberately excluded (bound to a
        # no-op above). Needs real keyboard focus on the overlay itself,
        # which `-topmost` alone doesn't guarantee.
        overlay.bind("<Return>", lambda _e: self.open_link() if self._current_url else None)
        overlay.bind("<Alt-s>", lambda _e: self.dismiss())
        overlay.bind("<Alt-S>", lambda _e: self.dismiss())
        overlay.focus_force()

    # -- periodic effects ------------------------------------------------------

    def _flash_overlay(self) -> None:
        if self._overlay is None:
            return
        self._flash_state = not self._flash_state
        try:
            self._flash_container.configure(bg=_FLASH_COLORS[int(self._flash_state)])
            self._flash_accent.configure(bg=_ACCENT_STRIP_COLORS[int(self._flash_state)])
            if self._indicator_label is not None:
                self._indicator_label.configure(fg=_ACCENT_STRIP_COLORS[int(self._flash_state)])
        except Exception:
            return
        self._flash_job = self._root.after(_FLASH_INTERVAL_MS, self._flash_overlay)

    def _update_countdown(self) -> None:
        """Refresh the "starts in / started ago" label once a second while
        the overlay is up. Reads `_current_meeting_start` fresh each tick
        (set in `_present`) rather than closing over it, so a queued
        hand-off (`dismiss` -> `_present` for the next alert, no mainloop
        turn in between) is picked up automatically without restarting this
        loop."""
        if self._overlay is None or self._countdown_label is None:
            return
        if self._current_meeting_start is not None:
            language = self._get_language()
            delta = self._current_meeting_start - datetime.now()
            if delta.total_seconds() > 0:
                text = i18n.format_text("alarmStartsIn", language, time=_format_countdown(delta))
            else:
                text = i18n.format_text("alarmStartedAgo", language, time=_format_countdown(-delta))
        else:
            text = ""
        try:
            self._countdown_label.configure(text=text)
        except Exception:
            return
        self._countdown_job = self._root.after(1000, self._update_countdown)

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
        # Reset the toggle for every newly-presented alert (same precedent
        # as the self._flash_state reset in _show_overlay, right before its
        # own periodic effect is kicked off). Without this, a queued
        # alert's very first synchronous tick just flips whatever parity
        # the *previous* alert's ticking happened to leave it at, so the
        # new alert's title could silently stay on the plain base-title
        # phase for up to one full _TITLE_BLINK_INTERVAL_MS instead of
        # announcing itself immediately.
        self._blink_on = False

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
