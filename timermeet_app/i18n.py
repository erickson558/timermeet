"""Spanish/English translation dictionary and helpers.

Ported verbatim (same 84 keys, same strings) from ``legacy-php/assets/app.js``
``translations.es`` / ``translations.en``. A small number of *values* are
reworded — never removed — where the original text refers to browser-only
concepts that no longer apply to a desktop app (e.g. "keep this browser tab
open", "this browser cannot..."). Each reworded value is marked with a
`# desktop-adapted` comment below so the change is easy to audit.
"""

from __future__ import annotations

import re
from datetime import date, datetime

DEFAULT_LANGUAGE = "es"

_PLACEHOLDER_RE_CACHE: dict[str, re.Pattern] = {}

translations = {
    "es": {
        "appTitle": "TimerMeet",
        "appSubtitle": "Organiza recordatorios locales para tus reuniones de Microsoft Teams.",
        "versionLabel": "Versión local",
        "storageLabel": "Guardado",
        "enableNotifications": "Probar notificación nativa",  # desktop-adapted
        "notificationsEnabled": "Notificaciones activas",
        "notificationsBlocked": "Notificaciones bloqueadas",
        "buyBeer": "Cómprame una cerveza",
        "formEyebrow": "Nuevo timer",
        "formTitle": "Agregar o editar reunión",
        "formHint": "Guarda tantas reuniones como necesites para tus 3 trabajos o más.",
        "workLabel": "Trabajo / Empresa",
        "workPlaceholder": "Ej. Trabajo 1, Cliente A, Freelance",
        "titleLabel": "Nombre de la reunión",
        "titlePlaceholder": "Ej. Daily, soporte, revisión de sprint",
        "dateLabel": "Fecha y hora",
        "dateOnlyLabel": "Fecha",
        "timeOnlyLabel": "Hora",
        "setNowButton": "Usar fecha y hora actual",
        "dateHint": "Selecciona ambas para que el timer se pueda guardar.",
        "reminderLabel": "Avisar antes",
        "minutesSuffix": "minutos",
        "soundLabel": "Sonido de alerta",
        "testSoundButton": "Probar sonido",
        "soundHint": "Usa un perfil más invasivo para reuniones críticas.",
        "soundSoft": "Suave",
        "soundUrgent": "Urgente",
        "soundAlarm": "Alarma fuerte",
        "soundSiren": "Sirena invasiva",
        "soundFireSiren": "Sirena de bomberos",
        "repeatLabel": "Repetición",
        "occurrenceCountLabel": "Cuántas crear",
        "occurrenceCountSuffix": "eventos",
        "recurrenceHint": (
            "Para una daily laboral, elige \"Semana laboral (L-V)\" con una fecha de lunes a "
            "viernes. Para \"lunes cada 2 semanas\", elige una fecha lunes, selecciona \"Cada 2 "
            "semanas\" y cuántos eventos crear. Al editar, el cambio aplica solo a este timer."
        ),
        "recurrenceNone": "No repetir",
        "recurrenceDaily": "Todos los días",
        "recurrenceWeekdays": "Semana laboral (L-V)",
        "recurrenceWeekly": "Cada semana",
        "recurrenceBiweekly": "Cada 2 semanas",
        "recurrenceMonthly": "Cada mes",
        "urlLabel": "Enlace de Teams",
        "notesLabel": "Notas rápidas",
        "notesPlaceholder": "Datos importantes de la llamada, cliente, agenda, etc.",
        "saveButton": "Guardar timer",
        "updateButton": "Actualizar timer",
        "clearButton": "Limpiar formulario",
        "statsEyebrow": "Vista general",
        "statsTitle": "Panel de reuniones",
        "notificationHint": "Mantén la app abierta en segundo plano para recibir los recordatorios.",  # desktop-adapted
        "currentTimeLabel": "Hora actual",
        "nextAlertLabel": "Siguiente aviso",
        "totalMeetings": "Timers guardados",
        "todayMeetings": "Hoy",
        "activeMeetings": "Próxima reunión",
        "filterLabel": "Filtrar por trabajo",
        "allWorks": "Todos",
        "listTitle": "Tus reuniones",
        "emptyTitle": "Aún no hay timers",
        "emptyBody": "Agrega tu primera reunión y la app empezará a contar el tiempo restante.",  # desktop-adapted
        "openTeams": "Abrir Teams",
        "edit": "Editar",
        "delete": "Eliminar",
        "deleteConfirm": "¿Eliminar este timer?",
        "dueSoon": "Aviso pendiente",
        "live": "En curso",
        "past": "Pasada",
        "upcoming": "Programada",
        "startsIn": "Empieza en",
        "startedAgo": "Inició hace",
        "reminderAt": "Aviso",
        "alertReminderTitle": "Recordatorio de reunión",
        "alertStartTitle": "La reunión empieza ahora",
        "saved": "Timer guardado.",
        "updated": "Timer actualizado.",
        "deleted": "Timer eliminado.",
        "validationWork": "Escribe el nombre del trabajo o empresa.",
        "validationTitle": "Escribe el nombre de la reunión.",
        "validationDate": "Selecciona una fecha válida.",
        "validationTime": "Selecciona una hora válida.",
        "validationReminder": "El aviso debe ser de al menos 1 minuto.",
        "validationWeekdayStart": "La semana laboral debe iniciar en lunes, martes, miércoles, jueves o viernes.",
        "validationOccurrences": "La cantidad de eventos debe estar entre 1 y 52.",
        "nextAlertNone": "Sin avisos próximos",
        "nextMeetingNone": "Sin reuniones futuras",
        "noNotes": "Sin notas",
        "noTeamsLink": "Sin enlace de Teams",
        "startsNow": "Empieza ahora",
        "browserNotificationUnsupported": "Este equipo no soporta notificaciones nativas; seguirás recibiendo la alarma sonora y visual.",  # desktop-adapted
        "notificationsGrantedToast": "Notificación nativa enviada correctamente.",  # desktop-adapted
        "notificationsDeniedToast": "No se pudo mostrar la notificación nativa en este equipo.",  # desktop-adapted
        "alertReminderTag": "Recordatorio",
        "alertStartTag": "Inicio",
        "footerWorkLabel": "Trabajo",
        "footerDateLabel": "Fecha",
        "footerReminderLabel": "Avisar antes",
        "teamsLabel": "Teams",
        "notesLabelCard": "Notas",
        "openTeamsUnavailable": "Agrega un enlace de Teams para abrir la reunión.",
        "storageServer": "Archivo compartido (OneDrive)",  # desktop-adapted
        "storageLocal": "Solo esta copia local",  # desktop-adapted
        "storageFallbackToast": "No se pudo guardar en el archivo compartido. Se reintentará automáticamente.",  # desktop-adapted
        "serverLoadFallback": "No se pudo leer el archivo de datos. Se inició con una lista vacía.",  # desktop-adapted
        "dismissAlarm": "Silenciar alarma",
        "alarmOverlayTag": "Alarma activa",
        "alarmOverlayHint": "La alarma seguirá sonando y parpadeando hasta silenciarla.",
        "saveError": "Ocurrió un problema al guardar el timer.",
        "deleteError": "Ocurrió un problema al eliminar el timer.",
        "formReady": "Completa el formulario y presiona guardar.",
        "formSavedSeries": "Se guardaron {count} timers de la serie.",
        "formSavedSingle": "Timer guardado correctamente.",
        "formUpdatedSingle": "Timer actualizado correctamente.",
        "repeatCardLabel": "Repite",
        "repeatOccurrenceLabel": "Evento {index} de {total}",
        "soundPreviewReady": "Vista previa del sonido actual.",
        "soundPreviewBrowser": "No se pudo reproducir la vista previa de audio en este equipo.",  # desktop-adapted
        "soundCardLabel": "Sonido",
        "validationTeamsUrl": "El enlace de Teams debe iniciar con http:// o https://.",
        "renewalToast": "Se generaron {count} recordatorios nuevos para la próxima semana.",
        "exitButton": "Salir",
        "clearPastButton": "Eliminar eventos pasados",
        "clearPastConfirm": "¿Eliminar todos los eventos pasados de todos los trabajos? Esta acción no se puede deshacer.",
        "clearPastToast": "Se eliminaron {count} eventos pasados.",
        "clearPastNone": "No había eventos pasados para eliminar.",
        "manageCompaniesButton": "Gestionar empresas",
        "manageCompaniesTitle": "Gestionar empresas",
        "manageCompaniesHint": "Estas empresas aparecen en la lista desplegable de Trabajo / Empresa.",
        "addCompanyPlaceholder": "Nombre de la nueva empresa",
        "addCompanyButton": "Agregar",
        "removeCompanyButton": "Eliminar",
        "removeCompanyConfirm": "¿Eliminar esta empresa de la lista? Las reuniones ya guardadas con este nombre no se modifican.",
        "noCompaniesYet": "Aún no hay empresas guardadas.",
        "closeButton": "Cerrar",
        "companyAddedToast": "Empresa agregada.",
        "companyRemovedToast": "Empresa eliminada de la lista.",
        "companyExistsError": "Esa empresa ya está en la lista.",
        "companyEmptyError": "Escribe un nombre antes de agregar.",
        "gadgetModeButton": "Modo gadget",
        "gadgetRestoreButton": "Completo",
        "gadgetCloseButton": "×",
        "gadgetModeBlockedToast": "No se puede cambiar de modo mientras suena una alarma.",
        "trayModeButton": "Bandeja",
        "trayShowMenuItem": "Mostrar TimerMeet",
        "trayModeToast": "TimerMeet sigue activo en la bandeja del sistema.",
        "trayModeUnavailableToast": "No se pudo activar el modo bandeja en este equipo.",
        "calendarViewButton": "Vista calendario",
        "listViewButton": "Vista de lista",
        "calendarPrevMonthButton": "‹",
        "calendarNextMonthButton": "›",
        "calendarTodayButton": "Hoy",
        "calendarWeekdayMon": "Lun",
        "calendarWeekdayTue": "Mar",
        "calendarWeekdayWed": "Mié",
        "calendarWeekdayThu": "Jue",
        "calendarWeekdayFri": "Vie",
        "calendarWeekdaySat": "Sáb",
        "calendarWeekdaySun": "Dom",
        "calendarMoreLabel": "+{count} más",
        "weekViewButton": "Vista semanal",
        "weekPrevButton": "‹",
        "weekNextButton": "›",
        "weekTodayButton": "Esta semana",
    },
    "en": {
        "appTitle": "TimerMeet",
        "appSubtitle": "Organize local reminders for your Microsoft Teams meetings.",
        "versionLabel": "Local version",
        "storageLabel": "Storage",
        "enableNotifications": "Test native notification",  # desktop-adapted
        "notificationsEnabled": "Notifications enabled",
        "notificationsBlocked": "Notifications blocked",
        "buyBeer": "Buy me a beer",
        "formEyebrow": "New timer",
        "formTitle": "Add or edit meeting",
        "formHint": "Save as many meetings as you need for your 3 jobs or more.",
        "workLabel": "Job / Company",
        "workPlaceholder": "Example: Job 1, Client A, Freelance",
        "titleLabel": "Meeting name",
        "titlePlaceholder": "Example: Daily, support, sprint review",
        "dateLabel": "Date and time",
        "dateOnlyLabel": "Date",
        "timeOnlyLabel": "Time",
        "setNowButton": "Use current date and time",
        "dateHint": "Select both so the timer can be saved.",
        "reminderLabel": "Remind before",
        "minutesSuffix": "minutes",
        "soundLabel": "Alert sound",
        "testSoundButton": "Test sound",
        "soundHint": "Use a more invasive profile for critical meetings.",
        "soundSoft": "Soft",
        "soundUrgent": "Urgent",
        "soundAlarm": "Loud alarm",
        "soundSiren": "Intrusive siren",
        "soundFireSiren": "Fire siren",
        "repeatLabel": "Repeat",
        "occurrenceCountLabel": "How many to create",
        "occurrenceCountSuffix": "events",
        "recurrenceHint": (
            "For a workweek daily, choose \"Weekdays (Mon-Fri)\" with a Monday-to-Friday start "
            "date. For \"Monday every 2 weeks\", choose a Monday date, select \"Every 2 weeks\", "
            "and choose how many events to create. When editing, the change only affects this timer."
        ),
        "recurrenceNone": "Do not repeat",
        "recurrenceDaily": "Every day",
        "recurrenceWeekdays": "Weekdays (Mon-Fri)",
        "recurrenceWeekly": "Every week",
        "recurrenceBiweekly": "Every 2 weeks",
        "recurrenceMonthly": "Every month",
        "urlLabel": "Teams link",
        "notesLabel": "Quick notes",
        "notesPlaceholder": "Important call details, client, agenda, etc.",
        "saveButton": "Save timer",
        "updateButton": "Update timer",
        "clearButton": "Clear form",
        "statsEyebrow": "Overview",
        "statsTitle": "Meeting dashboard",
        "notificationHint": "Keep the app running in the background so reminders can fire.",  # desktop-adapted
        "currentTimeLabel": "Current time",
        "nextAlertLabel": "Next alert",
        "totalMeetings": "Saved timers",
        "todayMeetings": "Today",
        "activeMeetings": "Next meeting",
        "filterLabel": "Filter by job",
        "allWorks": "All",
        "listTitle": "Your meetings",
        "emptyTitle": "No timers yet",
        "emptyBody": "Add your first meeting and the app will start counting down.",  # desktop-adapted
        "openTeams": "Open Teams",
        "edit": "Edit",
        "delete": "Delete",
        "deleteConfirm": "Delete this timer?",
        "dueSoon": "Reminder pending",
        "live": "Live now",
        "past": "Past",
        "upcoming": "Scheduled",
        "startsIn": "Starts in",
        "startedAgo": "Started",
        "reminderAt": "Reminder",
        "alertReminderTitle": "Meeting reminder",
        "alertStartTitle": "Meeting starts now",
        "saved": "Timer saved.",
        "updated": "Timer updated.",
        "deleted": "Timer deleted.",
        "validationWork": "Enter the job or company name.",
        "validationTitle": "Enter the meeting name.",
        "validationDate": "Select a valid date.",
        "validationTime": "Select a valid time.",
        "validationReminder": "Reminder must be at least 1 minute.",
        "validationWeekdayStart": "Weekday recurrence must start on Monday, Tuesday, Wednesday, Thursday, or Friday.",
        "validationOccurrences": "Event count must be between 1 and 52.",
        "nextAlertNone": "No upcoming alerts",
        "nextMeetingNone": "No upcoming meetings",
        "noNotes": "No notes",
        "noTeamsLink": "No Teams link",
        "startsNow": "Starts now",
        "browserNotificationUnsupported": "This computer does not support native notifications; you'll still get the sound and visual alarm.",  # desktop-adapted
        "notificationsGrantedToast": "Native notification sent successfully.",  # desktop-adapted
        "notificationsDeniedToast": "Could not show the native notification on this computer.",  # desktop-adapted
        "alertReminderTag": "Reminder",
        "alertStartTag": "Start",
        "footerWorkLabel": "Job",
        "footerDateLabel": "Date",
        "footerReminderLabel": "Remind before",
        "teamsLabel": "Teams",
        "notesLabelCard": "Notes",
        "openTeamsUnavailable": "Add a Teams link to open the meeting.",
        "storageServer": "Shared file (OneDrive)",  # desktop-adapted
        "storageLocal": "This local copy only",  # desktop-adapted
        "storageFallbackToast": "Could not save to the shared data file. It will retry automatically.",  # desktop-adapted
        "serverLoadFallback": "Could not read the data file. Started with an empty list.",  # desktop-adapted
        "dismissAlarm": "Silence alarm",
        "alarmOverlayTag": "Alarm active",
        "alarmOverlayHint": "The alarm will keep sounding and flashing until you dismiss it.",
        "saveError": "There was a problem saving the timer.",
        "deleteError": "There was a problem deleting the timer.",
        "formReady": "Complete the form and press save.",
        "formSavedSeries": "{count} timers were created for the series.",
        "formSavedSingle": "Timer saved successfully.",
        "formUpdatedSingle": "Timer updated successfully.",
        "repeatCardLabel": "Repeats",
        "repeatOccurrenceLabel": "Event {index} of {total}",
        "soundPreviewReady": "Previewing the current sound.",
        "soundPreviewBrowser": "Could not play the audio preview on this computer.",  # desktop-adapted
        "soundCardLabel": "Sound",
        "validationTeamsUrl": "The Teams link must start with http:// or https://.",
        "renewalToast": "{count} new reminders were generated for next week.",
        "exitButton": "Exit",
        "clearPastButton": "Delete past events",
        "clearPastConfirm": "Delete all past events across all jobs? This cannot be undone.",
        "clearPastToast": "{count} past events were deleted.",
        "clearPastNone": "There were no past events to delete.",
        "manageCompaniesButton": "Manage companies",
        "manageCompaniesTitle": "Manage companies",
        "manageCompaniesHint": "These companies show up in the Job / Company dropdown.",
        "addCompanyPlaceholder": "New company name",
        "addCompanyButton": "Add",
        "removeCompanyButton": "Remove",
        "removeCompanyConfirm": "Remove this company from the list? Meetings already saved with this name are not changed.",
        "noCompaniesYet": "No companies saved yet.",
        "closeButton": "Close",
        "companyAddedToast": "Company added.",
        "companyRemovedToast": "Company removed from the list.",
        "companyExistsError": "That company is already in the list.",
        "companyEmptyError": "Type a name before adding.",
        "gadgetModeButton": "Gadget mode",
        "gadgetRestoreButton": "Full",
        "gadgetCloseButton": "×",
        "gadgetModeBlockedToast": "Can't switch modes while an alarm is sounding.",
        "trayModeButton": "Tray",
        "trayShowMenuItem": "Show TimerMeet",
        "trayModeToast": "TimerMeet is still running in the system tray.",
        "trayModeUnavailableToast": "Could not enable tray mode on this computer.",
        "calendarViewButton": "Calendar view",
        "listViewButton": "List view",
        "calendarPrevMonthButton": "‹",
        "calendarNextMonthButton": "›",
        "calendarTodayButton": "Today",
        "calendarWeekdayMon": "Mon",
        "calendarWeekdayTue": "Tue",
        "calendarWeekdayWed": "Wed",
        "calendarWeekdayThu": "Thu",
        "calendarWeekdayFri": "Fri",
        "calendarWeekdaySat": "Sat",
        "calendarWeekdaySun": "Sun",
        "calendarMoreLabel": "+{count} more",
        "weekViewButton": "Week view",
        "weekPrevButton": "‹",
        "weekNextButton": "›",
        "weekTodayButton": "This week",
    },
}

# Both languages must define exactly the same keys — enforced by tests/test_i18n.py.


def t(key: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Look up a translation, falling back to the default language, then to
    the raw key itself if it's missing everywhere (never raises)."""
    table = translations.get(language, translations[DEFAULT_LANGUAGE])
    if key in table:
        return table[key]
    return translations[DEFAULT_LANGUAGE].get(key, key)


def format_text(key: str, language: str = DEFAULT_LANGUAGE, **replacements) -> str:
    """``t(key)`` with ``{name}`` placeholders substituted from ``replacements``."""
    text = t(key, language)
    for name, value in replacements.items():
        pattern = _PLACEHOLDER_RE_CACHE.setdefault(name, re.compile(r"\{" + re.escape(name) + r"\}"))
        text = pattern.sub(str(value), text)
    return text


_MONTHS = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def format_datetime_display(value: datetime, language: str = DEFAULT_LANGUAGE) -> str:
    """Human-readable "6 ago 2026, 15:30" / "Aug 6 2026, 15:30" style string.

    Deliberately hand-rolled instead of relying on the OS's ICU locale data
    (``locale.setlocale`` / ``Intl``-equivalent), since a packaged .exe can't
    assume the end-user's Windows install has the "es-GT"/"en-US" locale
    available — this keeps date formatting 100% self-contained.
    """
    months = _MONTHS.get(language, _MONTHS[DEFAULT_LANGUAGE])
    month_name = months[value.month - 1]
    if language == "es":
        return f"{value.day} {month_name} {value.year}, {value.strftime('%H:%M')}"
    return f"{month_name} {value.day}, {value.year}, {value.strftime('%H:%M')}"


# Separate from `_MONTHS` above on purpose: that list is deliberately
# abbreviated ("ago") for the alarm's compact date/time line, while the
# calendar view's "Mes Año" navigation header (e.g. "Agosto 2026") reads
# better unabbreviated -- same "small lookup table beside the main dict"
# pattern as `_MONTHS`, just spelled out in full.
_MONTH_NAMES_FULL = {
    "es": [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}


def format_month_year(year: int, month: int, language: str = DEFAULT_LANGUAGE) -> str:
    """"Mes Año" header for the monthly calendar view, e.g. "Agosto 2026" /
    "August 2026"."""
    names = _MONTH_NAMES_FULL.get(language, _MONTH_NAMES_FULL[DEFAULT_LANGUAGE])
    return f"{names[month - 1]} {year}"


def _month_abbrev(month: int, language: str) -> str:
    """3-letter, capitalized month abbreviation for the weekly view's range
    header (e.g. "Ago", "Jul") -- sliced from `_MONTH_NAMES_FULL`, not the
    already-abbreviated, lowercase `_MONTHS` table `format_datetime_display`
    uses. `_MONTHS`'s casing ("ago", "jul") reads fine inline in a sentence
    but looks wrong as a capitalized standalone header token, and this view
    family's other header (`format_month_year`) already reads "Agosto
    2026", not "ago 2026" -- this keeps that same capitalized precedent."""
    names = _MONTH_NAMES_FULL.get(language, _MONTH_NAMES_FULL[DEFAULT_LANGUAGE])
    return names[month - 1][:3]


def format_week_range(start: date, end: date, language: str = DEFAULT_LANGUAGE) -> str:
    """Date-range header for the weekly calendar view's nav bar (SDD.md
    v2.9.0), e.g. "10-16 Ago 2026" (same month), "27 Jul - 2 Ago 2026"
    (month crossing), or a year-crossing week (only reachable by a
    Monday-first week straddling Dec 31/Jan 1, e.g. "29 Dic 2025 - 4 Ene
    2026"). No new `translations[...]` key for the format itself -- same
    precedent `format_month_year` already established: this is date
    arithmetic plus a per-language day/month ordering, not a translated
    sentence with placeholders.
    """
    is_es = language == "es"
    start_month = _month_abbrev(start.month, language)
    end_month = _month_abbrev(end.month, language)

    if start.year != end.year:
        if is_es:
            return f"{start.day} {start_month} {start.year} - {end.day} {end_month} {end.year}"
        return f"{start_month} {start.day}, {start.year} - {end_month} {end.day}, {end.year}"

    if start.month != end.month:
        if is_es:
            return f"{start.day} {start_month} - {end.day} {end_month} {end.year}"
        return f"{start_month} {start.day} - {end_month} {end.day}, {end.year}"

    if is_es:
        return f"{start.day}-{end.day} {start_month} {end.year}"
    return f"{start_month} {start.day}-{end.day}, {end.year}"
