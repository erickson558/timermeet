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
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from typing import List, Optional

from . import i18n, models, notifications, recurrence, retention, security, storage
from .alarm_ui import AlarmController
from .main_window import Callbacks, MainWindow, MeetingCardData

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
    just guaranteed stable for a given work name."""
    if not name:
        return "#d4d4d8"
    hash_value = 0
    for char in name:
        hash_value = ord(char) + ((hash_value << 5) - hash_value)
        hash_value &= 0xFFFFFFFF
    hue = abs(_to_signed_32(hash_value)) % 360
    red, green, blue = colorsys.hls_to_rgb(hue / 360, 0.74, 0.70)
    return "#{:02x}{:02x}{:02x}".format(int(red * 255), int(green * 255), int(blue * 255))


class TimerMeetApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.geometry("1180x760")
        self.root.minsize(960, 640)
        # Belt-and-suspenders against a packaged build ever ending up with a
        # window that exists but never gets shown (observed once under
        # PyInstaller --windowed, root-caused to sys.stdout/stderr being
        # None -- see timermeet.py).
        self.root.after(0, self._force_show_window)

        # Cheap, immediate feedback while the real UI builds underneath.
        loading_label = tk.Label(
            self.root, text="Cargando TimerMeet…", font=("Segoe UI", 14), bg="#1a1a1a", fg="#f5f5f5"
        )
        loading_label.place(relx=0.5, rely=0.5, anchor="center")
        self.root.update()

        settings = storage.load_settings()
        saved_language = settings.get("language")
        self.language = saved_language if saved_language in i18n.translations else i18n.DEFAULT_LANGUAGE
        self.work_filter = "all"
        self.meetings: List[models.Meeting] = storage.load_meetings()
        self.meetings, purged_at_startup = retention.purge_stale_meetings(self.meetings)
        self.storage_ok = True
        self._dirty = bool(purged_at_startup)
        self._resync_accumulator_ms = 0
        self._purge_accumulator_ms = 0
        self._last_rendered_signature = None

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
        )
        self.view = MainWindow(self.root, callbacks)
        self.view.apply_translations(self.language)

        self.alarms = AlarmController(self.root, get_language=lambda: self.language)
        self.alarms.set_base_title(i18n.t("appTitle", self.language))

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
        loading_label.destroy()

        # Run on a background thread, not via root.after(): pygame.mixer
        # initialization (inside AlarmPlayer._ensure_mixer) measurably slows
        # down Tk's own idle-task/event processing on some systems even when
        # scheduled through Tk's own timer, so it has to stay off the Tk
        # thread entirely for the window to be responsive immediately.
        # warm_cache() only touches pygame, never a Tkinter widget, so it's
        # safe to run concurrently with the UI thread. The alarm system
        # works fine in the meantime either way -- it lazily loads/falls
        # back to a synth tone on demand (see audio.py).
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

    # -- persistence ----------------------------------------------------------

    def _persist(self, silent: bool = True) -> None:
        try:
            merged = storage.save_meetings(self.meetings)
        except OSError as exc:
            logger.warning("Could not save meetings: %s", exc)
            self.storage_ok = False
            self._dirty = True
            if not silent:
                self.view.show_toast(i18n.t("storageFallbackToast", self.language))
            return
        self.meetings = merged
        self.storage_ok = True
        self._dirty = False

    def _resync_from_disk(self) -> None:
        try:
            disk_meetings = storage.load_meetings()
        except OSError:
            return
        merged = storage.merge_meeting_lists(disk_meetings, self.meetings)
        before = sorted((m.to_dict() for m in self.meetings), key=lambda d: d["id"])
        after = sorted((m.to_dict() for m in merged), key=lambda d: d["id"])
        if before != after:
            self.meetings = sorted(merged, key=_meeting_sort_key)
            self._persist(silent=True)
            self._refresh_all()

    def _on_focus_in(self, _event=None) -> None:
        self._resync_from_disk()

    def _on_close(self) -> None:
        self.alarms.dismiss(run_callback=False)
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
            self.meetings, purged = retention.purge_stale_meetings(self.meetings, now)

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
        self.view.update_filter_options(self._work_names(), self.work_filter)

        cards = [
            MeetingCardData(
                meeting=meeting,
                status_key=_meeting_status(meeting, now),
                countdown_text=_countdown_text(meeting, now, self.language),
                recurrence_text=_recurrence_text(meeting, self.language),
                color=_color_for_work_name(meeting.workName),
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
                (c.meeting.id, c.status_key, c.countdown_text, c.recurrence_text, c.meeting.updatedAt)
                for c in cards
            ),
        )
        if signature != self._last_rendered_signature:
            self.view.render_meeting_list(cards)
            self._last_rendered_signature = signature

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
        before = len(self.meetings)
        self.meetings = [m for m in self.meetings if m.id != meeting_id]
        if len(self.meetings) != before:
            self._persist(silent=False)
            self.view.show_toast(i18n.t("deleted", self.language))
            self._refresh_all()

    def handle_clear_past(self) -> None:
        """Manual "delete past events" button -- removes every past meeting
        across all work names right now (ignores the current filter and the
        automatic purge's grace period), but still keeps each recurring
        series' latest occurrence so it doesn't silently stop reminding."""
        self.meetings, removed = retention.clear_past_meetings(self.meetings)
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
        storage.save_settings({"language": self.language})
        self.view.apply_translations(self.language)
        self.alarms.set_base_title(i18n.t("appTitle", self.language))
        self._refresh_all()

    def handle_test_notification(self) -> None:
        ok = notifications.notify(i18n.t("appTitle", self.language), i18n.t("soundPreviewReady", self.language))
        key = "notificationsGrantedToast" if ok else "notificationsDeniedToast"
        self.view.show_toast(i18n.t(key, self.language))

    def handle_filter_change(self, value: str) -> None:
        self.work_filter = value
        self._refresh_all()
