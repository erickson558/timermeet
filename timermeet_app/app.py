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
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

from . import i18n, models, notifications, recurrence, retention, security, storage
from .alarm_ui import AlarmController
from .main_window import (
    CALENDAR_MAX_ENTRIES_PER_CELL,
    Callbacks,
    CalendarCellData,
    CalendarEntry,
    MainWindow,
    MeetingCardData,
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
    against i18n.translations before being trusted below."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


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
        self.meetings: List[models.Meeting] = storage.load_meetings()
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
            on_toggle_calendar_view=self.handle_toggle_calendar_view,
            on_calendar_prev_month=self.handle_calendar_prev_month,
            on_calendar_next_month=self.handle_calendar_next_month,
            on_calendar_today=self.handle_calendar_today,
        )
        self.view = MainWindow(self.root, callbacks)
        self.view.apply_translations(self.language)
        self.view.update_company_options(self.companies)
        if self.gadget_mode:
            self.view.set_gadget_mode(True, self._gadget_x, self._gadget_y)

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
            self._save_gadget_settings()
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
                        time_text=meeting.local_datetime().strftime("%H:%M"),
                        title=meeting.title,
                        color=_color_for_work_name(meeting.workName),
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
                    tuple((e.meeting_id, e.time_text, e.title, e.color) for e in cell.entries),
                    cell.overflow_count,
                )
                for cell in cells
            ),
        )
        if signature != self._last_rendered_calendar_signature:
            self.view.render_calendar(month_label, weekday_labels, cells)
            self._last_rendered_calendar_signature = signature

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
        removed = self._apply_meetings([m for m in self.meetings if m.id != meeting_id])
        if removed:
            self._persist(silent=False)
            self.view.show_toast(i18n.t("deleted", self.language))
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
            self.view.set_gadget_mode(True, self._gadget_x, self._gadget_y)
        else:
            self._gadget_x, self._gadget_y = self.view.current_gadget_position()
            self.view.set_gadget_mode(False)
        self._save_gadget_settings()
        self._refresh_all()

    def _save_gadget_settings(self) -> None:
        settings = storage.load_settings()
        settings["gadgetMode"] = self.gadget_mode
        if self._gadget_x is not None and self._gadget_y is not None:
            settings["gadgetX"] = self._gadget_x
            settings["gadgetY"] = self._gadget_y
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

    # -- calendar view ----------------------------------------------------------

    def handle_toggle_calendar_view(self) -> None:
        # Shared by both directions -- "Vista calendario" on the list's
        # header and "Vista de lista" on the calendar's header both wire to
        # this same callback (see `_build_header` in main_window.py), the
        # same pattern "Modo gadget"/"Completo" already use for
        # `on_toggle_gadget_mode`. Unlike gadget/tray mode, this isn't
        # blocked while an alarm is active: both views live inside the same
        # normal, decorated root window, so switching between them can never
        # interfere with AlarmController's independent Toplevel overlay.
        self.active_view = "calendar" if self.active_view == "list" else "list"
        self.view.set_active_view(self.active_view)
        self._refresh_all()

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
