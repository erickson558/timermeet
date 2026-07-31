(function () {
    var APP_CONFIG = window.APP_CONFIG || {};
    var STORAGE_KEY = "timermeet-meetings-v3";
    var LANGUAGE_KEY = "timermeet-language-v1";
    var DEFAULT_LANGUAGE = "es";
    var MEETING_LIVE_WINDOW_MINUTES = 60;
    var API_ENDPOINT = APP_CONFIG.apiEndpoint || "api/meetings.php";
    var DAY_MS = 24 * 60 * 60 * 1000;
    var SYNC_INTERVAL_MS = 45 * 1000;
    var SYNC_MERGE_GRACE_MS = 15 * 1000;
    var RENEWAL_TRIGGER_HOUR = 18;
    var RENEWAL_LOOKAHEAD_MS = 9 * DAY_MS;
    var RENEWAL_MAX_STEPS_PER_SERIES = 60;
    var ESCAPE_LOOKUP = {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
        "`": "&#96;"
    };
    var AUDIO_ASSETS = {
        siren: {
            key: "siren",
            url: "assets/audio/siren-noise-public-domain.mp3",
            previewStart: 0,
            previewSeconds: 3.8,
            loopStart: 0,
            loopEnd: 7.95,
            gain: 1
        },
        fire: {
            key: "fire",
            url: "assets/audio/fire-engine-siren-real.mp3",
            previewStart: 0.45,
            previewSeconds: 4.6,
            loopStart: 0.45,
            loopEnd: 6.6,
            gain: 1
        }
    };

    var translations = {
        es: {
            appTitle: "TimerMeet",
            appSubtitle: "Organiza recordatorios locales para tus reuniones de Microsoft Teams.",
            versionLabel: "Versión local",
            storageLabel: "Guardado",
            enableNotifications: "Activar notificaciones",
            notificationsEnabled: "Notificaciones activas",
            notificationsBlocked: "Notificaciones bloqueadas",
            buyBeer: "Cómprame una cerveza",
            formEyebrow: "Nuevo timer",
            formTitle: "Agregar o editar reunión",
            formHint: "Guarda tantas reuniones como necesites para tus 3 trabajos o más.",
            workLabel: "Trabajo / Empresa",
            workPlaceholder: "Ej. Trabajo 1, Cliente A, Freelance",
            titleLabel: "Nombre de la reunión",
            titlePlaceholder: "Ej. Daily, soporte, revisión de sprint",
            dateLabel: "Fecha y hora",
            dateOnlyLabel: "Fecha",
            timeOnlyLabel: "Hora",
            setNowButton: "Usar fecha y hora actual",
            dateHint: "Selecciona ambas para que el timer se pueda guardar.",
            reminderLabel: "Avisar antes",
            minutesSuffix: "minutos",
            soundLabel: "Sonido de alerta",
            testSoundButton: "Probar sonido",
            soundHint: "Usa un perfil más invasivo para reuniones críticas.",
            soundSoft: "Suave",
            soundUrgent: "Urgente",
            soundAlarm: "Alarma fuerte",
            soundSiren: "Sirena invasiva",
            soundFireSiren: "Sirena de bomberos",
            repeatLabel: "Repetición",
            occurrenceCountLabel: "Cuántas crear",
            occurrenceCountSuffix: "eventos",
            recurrenceHint: "Para una daily laboral, elige \"Semana laboral (L-V)\" con una fecha de lunes a viernes. Para \"lunes cada 2 semanas\", elige una fecha lunes, selecciona \"Cada 2 semanas\" y cuántos eventos crear. Al editar, el cambio aplica solo a este timer.",
            recurrenceNone: "No repetir",
            recurrenceDaily: "Todos los días",
            recurrenceWeekdays: "Semana laboral (L-V)",
            recurrenceWeekly: "Cada semana",
            recurrenceBiweekly: "Cada 2 semanas",
            recurrenceMonthly: "Cada mes",
            urlLabel: "Enlace de Teams",
            notesLabel: "Notas rápidas",
            notesPlaceholder: "Datos importantes de la llamada, cliente, agenda, etc.",
            saveButton: "Guardar timer",
            updateButton: "Actualizar timer",
            clearButton: "Limpiar formulario",
            statsEyebrow: "Vista general",
            statsTitle: "Panel de reuniones",
            notificationHint: "La pestaña debe permanecer abierta para disparar recordatorios.",
            currentTimeLabel: "Hora actual",
            nextAlertLabel: "Siguiente aviso",
            totalMeetings: "Timers guardados",
            todayMeetings: "Hoy",
            activeMeetings: "Próxima reunión",
            filterLabel: "Filtrar por trabajo",
            allWorks: "Todos",
            listTitle: "Tus reuniones",
            emptyTitle: "Aún no hay timers",
            emptyBody: "Agrega tu primera reunión y el sitio empezará a contar el tiempo restante.",
            openTeams: "Abrir Teams",
            edit: "Editar",
            delete: "Eliminar",
            deleteConfirm: "¿Eliminar este timer?",
            dueSoon: "Aviso pendiente",
            live: "En curso",
            past: "Pasada",
            upcoming: "Programada",
            startsIn: "Empieza en",
            startedAgo: "Inició hace",
            reminderAt: "Aviso",
            alertReminderTitle: "Recordatorio de reunión",
            alertStartTitle: "La reunión empieza ahora",
            alertDialogOpen: "Abrir Teams",
            alertDialogClose: "Silenciar",
            saved: "Timer guardado.",
            updated: "Timer actualizado.",
            deleted: "Timer eliminado.",
            validationWork: "Escribe el nombre del trabajo o empresa.",
            validationTitle: "Escribe el nombre de la reunión.",
            validationDate: "Selecciona una fecha válida.",
            validationTime: "Selecciona una hora válida.",
            validationReminder: "El aviso debe ser de al menos 1 minuto.",
            validationWeekdayStart: "La semana laboral debe iniciar en lunes, martes, miércoles, jueves o viernes.",
            validationOccurrences: "La cantidad de eventos debe estar entre 1 y 52.",
            nextAlertNone: "Sin avisos próximos",
            nextMeetingNone: "Sin reuniones futuras",
            noNotes: "Sin notas",
            noTeamsLink: "Sin enlace de Teams",
            startsNow: "Empieza ahora",
            browserNotificationUnsupported: "Este navegador no soporta notificaciones.",
            notificationsGrantedToast: "Permiso de notificaciones concedido.",
            notificationsDeniedToast: "No se pudo activar el permiso de notificaciones.",
            alertDialogReminderTag: "Recordatorio",
            alertDialogStartTag: "Inicio",
            footerWorkLabel: "Trabajo",
            footerDateLabel: "Fecha",
            footerReminderLabel: "Avisar antes",
            teamsLabel: "Teams",
            notesLabelCard: "Notas",
            openTeamsUnavailable: "Agrega un enlace de Teams para abrir la reunión.",
            storageServer: "Servidor local + navegador",
            storageLocal: "Solo este navegador",
            storageFallbackToast: "No se pudo guardar en PHP. Quedó guardado en este navegador.",
            serverLoadFallback: "No se pudo leer el servidor. Se usó la copia local.",
            dismissAlarm: "Silenciar alarma",
            alarmOverlayTag: "Alarma activa",
            alarmOverlayHint: "La alarma seguirá sonando y parpadeando hasta silenciarla.",
            saveError: "Ocurrió un problema al guardar el timer.",
            deleteError: "Ocurrió un problema al eliminar el timer.",
            formReady: "Completa el formulario y presiona guardar.",
            formSavedSeries: "Se guardaron {count} timers de la serie.",
            formSavedSingle: "Timer guardado correctamente.",
            formUpdatedSingle: "Timer actualizado correctamente.",
            repeatCardLabel: "Repite",
            repeatOccurrenceLabel: "Evento {index} de {total}",
            soundPreviewReady: "Vista previa del sonido actual.",
            soundPreviewBrowser: "Este navegador no puede reproducir la vista previa de audio.",
            soundCardLabel: "Sonido",
            validationTeamsUrl: "El enlace de Teams debe iniciar con http:// o https://.",
            renewalToast: "Se generaron {count} recordatorios nuevos para la próxima semana."
        },
        en: {
            appTitle: "TimerMeet",
            appSubtitle: "Organize local reminders for your Microsoft Teams meetings.",
            versionLabel: "Local version",
            storageLabel: "Storage",
            enableNotifications: "Enable notifications",
            notificationsEnabled: "Notifications enabled",
            notificationsBlocked: "Notifications blocked",
            buyBeer: "Buy me a beer",
            formEyebrow: "New timer",
            formTitle: "Add or edit meeting",
            formHint: "Save as many meetings as you need for your 3 jobs or more.",
            workLabel: "Job / Company",
            workPlaceholder: "Example: Job 1, Client A, Freelance",
            titleLabel: "Meeting name",
            titlePlaceholder: "Example: Daily, support, sprint review",
            dateLabel: "Date and time",
            dateOnlyLabel: "Date",
            timeOnlyLabel: "Time",
            setNowButton: "Use current date and time",
            dateHint: "Select both so the timer can be saved.",
            reminderLabel: "Remind before",
            minutesSuffix: "minutes",
            soundLabel: "Alert sound",
            testSoundButton: "Test sound",
            soundHint: "Use a more invasive profile for critical meetings.",
            soundSoft: "Soft",
            soundUrgent: "Urgent",
            soundAlarm: "Loud alarm",
            soundSiren: "Intrusive siren",
            soundFireSiren: "Fire siren",
            repeatLabel: "Repeat",
            occurrenceCountLabel: "How many to create",
            occurrenceCountSuffix: "events",
            recurrenceHint: "For a workweek daily, choose \"Weekdays (Mon-Fri)\" with a Monday-to-Friday start date. For \"Monday every 2 weeks\", choose a Monday date, select \"Every 2 weeks\", and choose how many events to create. When editing, the change only affects this timer.",
            recurrenceNone: "Do not repeat",
            recurrenceDaily: "Every day",
            recurrenceWeekdays: "Weekdays (Mon-Fri)",
            recurrenceWeekly: "Every week",
            recurrenceBiweekly: "Every 2 weeks",
            recurrenceMonthly: "Every month",
            urlLabel: "Teams link",
            notesLabel: "Quick notes",
            notesPlaceholder: "Important call details, client, agenda, etc.",
            saveButton: "Save timer",
            updateButton: "Update timer",
            clearButton: "Clear form",
            statsEyebrow: "Overview",
            statsTitle: "Meeting dashboard",
            notificationHint: "Keep this tab open so reminders can fire.",
            currentTimeLabel: "Current time",
            nextAlertLabel: "Next alert",
            totalMeetings: "Saved timers",
            todayMeetings: "Today",
            activeMeetings: "Next meeting",
            filterLabel: "Filter by job",
            allWorks: "All",
            listTitle: "Your meetings",
            emptyTitle: "No timers yet",
            emptyBody: "Add your first meeting and the site will start counting down.",
            openTeams: "Open Teams",
            edit: "Edit",
            delete: "Delete",
            deleteConfirm: "Delete this timer?",
            dueSoon: "Reminder pending",
            live: "Live now",
            past: "Past",
            upcoming: "Scheduled",
            startsIn: "Starts in",
            startedAgo: "Started",
            reminderAt: "Reminder",
            alertReminderTitle: "Meeting reminder",
            alertStartTitle: "Meeting starts now",
            alertDialogOpen: "Open Teams",
            alertDialogClose: "Silence",
            saved: "Timer saved.",
            updated: "Timer updated.",
            deleted: "Timer deleted.",
            validationWork: "Enter the job or company name.",
            validationTitle: "Enter the meeting name.",
            validationDate: "Select a valid date.",
            validationTime: "Select a valid time.",
            validationReminder: "Reminder must be at least 1 minute.",
            validationWeekdayStart: "Weekday recurrence must start on Monday, Tuesday, Wednesday, Thursday, or Friday.",
            validationOccurrences: "Event count must be between 1 and 52.",
            nextAlertNone: "No upcoming alerts",
            nextMeetingNone: "No upcoming meetings",
            noNotes: "No notes",
            noTeamsLink: "No Teams link",
            startsNow: "Starts now",
            browserNotificationUnsupported: "This browser does not support notifications.",
            notificationsGrantedToast: "Notification permission granted.",
            notificationsDeniedToast: "Could not enable notification permission.",
            alertDialogReminderTag: "Reminder",
            alertDialogStartTag: "Start",
            footerWorkLabel: "Job",
            footerDateLabel: "Date",
            footerReminderLabel: "Remind before",
            teamsLabel: "Teams",
            notesLabelCard: "Notes",
            openTeamsUnavailable: "Add a Teams link to open the meeting.",
            storageServer: "Local server + browser backup",
            storageLocal: "Only this browser",
            storageFallbackToast: "Could not save through PHP. Saved in this browser only.",
            serverLoadFallback: "Server data was unavailable. Local copy loaded instead.",
            dismissAlarm: "Silence alarm",
            alarmOverlayTag: "Alarm active",
            alarmOverlayHint: "The alarm will keep sounding and flashing until you dismiss it.",
            saveError: "There was a problem saving the timer.",
            deleteError: "There was a problem deleting the timer.",
            formReady: "Complete the form and press save.",
            formSavedSeries: "{count} timers were created for the series.",
            formSavedSingle: "Timer saved successfully.",
            formUpdatedSingle: "Timer updated successfully.",
            repeatCardLabel: "Repeats",
            repeatOccurrenceLabel: "Event {index} of {total}",
            soundPreviewReady: "Previewing the current sound.",
            soundPreviewBrowser: "This browser cannot play the audio preview.",
            soundCardLabel: "Sound",
            validationTeamsUrl: "The Teams link must start with http:// or https://.",
            renewalToast: "{count} new reminders were generated for next week."
        }
    };

    var state = {
        editingId: null,
        language: loadLanguage(),
        filter: "all",
        meetings: [],
        audioContext: null,
        audioBuffers: {},
        audioBufferRequests: {},
        activeAudioSources: [],
        currentAlertUrl: "",
        currentAlertMeetingId: "",
        baseTitle: document.title,
        alarmIntervalId: 0,
        titleBlinkIntervalId: 0,
        storageMode: "local",
        syncInFlight: false
    };

    var elements = {
        meetingForm: document.getElementById("meetingForm"),
        meetingId: document.getElementById("meetingId"),
        workName: document.getElementById("workName"),
        meetingTitle: document.getElementById("meetingTitle"),
        meetingDate: document.getElementById("meetingDate"),
        meetingTime: document.getElementById("meetingTime"),
        setNowButton: document.getElementById("setNowButton"),
        reminderMinutes: document.getElementById("reminderMinutes"),
        soundProfile: document.getElementById("soundProfile"),
        testSoundButton: document.getElementById("testSoundButton"),
        recurrenceType: document.getElementById("recurrenceType"),
        occurrenceCount: document.getElementById("occurrenceCount"),
        recurrenceHelp: document.getElementById("recurrenceHelp"),
        teamsUrl: document.getElementById("teamsUrl"),
        notes: document.getElementById("notes"),
        saveButton: document.getElementById("saveButton"),
        clearButton: document.getElementById("clearButton"),
        formFeedback: document.getElementById("formFeedback"),
        workFilter: document.getElementById("workFilter"),
        meetingList: document.getElementById("meetingList"),
        meetingCount: document.getElementById("meetingCount"),
        emptyState: document.getElementById("emptyState"),
        currentTimeValue: document.getElementById("currentTimeValue"),
        nextAlertValue: document.getElementById("nextAlertValue"),
        totalMeetingsValue: document.getElementById("totalMeetingsValue"),
        todayMeetingsValue: document.getElementById("todayMeetingsValue"),
        nextMeetingValue: document.getElementById("nextMeetingValue"),
        notificationButton: document.getElementById("notificationButton"),
        languageButton: document.getElementById("languageButton"),
        toast: document.getElementById("toast"),
        storageStatusValue: document.getElementById("storageStatusValue"),
        alertDialog: document.getElementById("alertDialog"),
        alertDialogTag: document.getElementById("alertDialogTag"),
        alertDialogTitle: document.getElementById("alertDialogTitle"),
        alertDialogMessage: document.getElementById("alertDialogMessage"),
        alertDialogOpen: document.getElementById("alertDialogOpen"),
        alertDialogClose: document.getElementById("alertDialogClose"),
        alarmOverlay: document.getElementById("alarmOverlay"),
        alarmOverlayTag: document.getElementById("alarmOverlayTag"),
        alarmOverlayTitle: document.getElementById("alarmOverlayTitle"),
        alarmOverlayBody: document.getElementById("alarmOverlayBody"),
        alarmOverlayMeta: document.getElementById("alarmOverlayMeta"),
        alarmOpenButton: document.getElementById("alarmOpenButton"),
        alarmDismissButton: document.getElementById("alarmDismissButton")
    };

    var toastTimer = null;

    initialize();

    function initialize() {
        applyTranslations();
        renderRecurrenceOptions();
        renderSoundOptions();
        attachEventListeners();
        updateNotificationButtonLabel();
        updateSaveButtonLabel();
        updateStorageStatus();
        updateRecurrenceState();
        setFormFeedback("formReady", "info");

        loadMeetings(function (loadedMeetings) {
            state.meetings = sortMeetings(normalizeMeetingList(loadedMeetings));
            renderFilterOptions();
            renderAll();
            runHeartbeat();
            window.setInterval(runHeartbeat, 1000);
            window.setInterval(syncFromServer, SYNC_INTERVAL_MS);
        });
    }

    function attachEventListeners() {
        if (elements.meetingForm) {
            elements.meetingForm.onsubmit = handleFormSubmit;
        }

        if (elements.clearButton) {
            elements.clearButton.onclick = resetForm;
        }

        if (elements.setNowButton) {
            elements.setNowButton.onclick = setDateTimeToNow;
        }

        if (elements.testSoundButton) {
            elements.testSoundButton.onclick = testSelectedSound;
        }

        if (elements.recurrenceType) {
            elements.recurrenceType.onchange = handleRecurrenceChange;
        }

        if (elements.workFilter) {
            elements.workFilter.onchange = handleFilterChange;
        }

        if (elements.meetingList) {
            elements.meetingList.onclick = handleMeetingListClick;
        }

        if (elements.notificationButton) {
            elements.notificationButton.onclick = requestNotificationPermission;
        }

        if (elements.languageButton) {
            elements.languageButton.onclick = toggleLanguage;
        }

        if (elements.alertDialogClose) {
            elements.alertDialogClose.onclick = dismissActiveAlarm;
        }

        if (elements.alertDialogOpen) {
            elements.alertDialogOpen.onclick = openCurrentAlertLink;
        }

        if (elements.alarmDismissButton) {
            elements.alarmDismissButton.onclick = dismissActiveAlarm;
        }

        if (elements.alarmOpenButton) {
            elements.alarmOpenButton.onclick = openCurrentAlertLink;
        }

        if (document.addEventListener) {
            document.addEventListener("click", activateAudioOnce, false);
            document.addEventListener("visibilitychange", handleVisibilityChange, false);
        } else if (document.attachEvent) {
            document.attachEvent("onclick", activateAudioOnce);
        }

        if (window.addEventListener) {
            window.addEventListener("focus", handleWindowFocus, false);
        } else if (window.attachEvent) {
            window.attachEvent("onfocus", handleWindowFocus);
        }
    }

    function handleVisibilityChange() {
        if (!document.hidden) {
            syncFromServer();
        }
    }

    function handleWindowFocus() {
        syncFromServer();
    }

    function activateAudioOnce() {
        ensureAudioContext();
        preloadExternalAlarmAudio();

        if (document.removeEventListener) {
            document.removeEventListener("click", activateAudioOnce, false);
        } else if (document.detachEvent) {
            document.detachEvent("onclick", activateAudioOnce);
        }
    }

    function renderRecurrenceOptions() {
        var options = [];

        options.push('<option value="none">' + escapeHtml(t("recurrenceNone")) + '</option>');
        options.push('<option value="daily">' + escapeHtml(t("recurrenceDaily")) + '</option>');
        options.push('<option value="weekdays">' + escapeHtml(t("recurrenceWeekdays")) + '</option>');
        options.push('<option value="weekly">' + escapeHtml(t("recurrenceWeekly")) + '</option>');
        options.push('<option value="biweekly">' + escapeHtml(t("recurrenceBiweekly")) + '</option>');
        options.push('<option value="monthly">' + escapeHtml(t("recurrenceMonthly")) + '</option>');

        if (elements.recurrenceType) {
            elements.recurrenceType.innerHTML = options.join("");
        }
    }

    function renderSoundOptions() {
        var options = [];

        options.push('<option value="soft">' + escapeHtml(t("soundSoft")) + '</option>');
        options.push('<option value="urgent">' + escapeHtml(t("soundUrgent")) + '</option>');
        options.push('<option value="alarm">' + escapeHtml(t("soundAlarm")) + '</option>');
        options.push('<option value="siren">' + escapeHtml(t("soundSiren")) + '</option>');
        options.push('<option value="fire">' + escapeHtml(t("soundFireSiren")) + '</option>');

        if (elements.soundProfile) {
            elements.soundProfile.innerHTML = options.join("");
        }
    }

    function testSelectedSound() {
        var selectedProfile = elements.soundProfile ? elements.soundProfile.value : "soft";

        if (!(window.AudioContext || window.webkitAudioContext)) {
            setFormFeedback("soundPreviewBrowser", "error");
            return false;
        }

        stopActiveAudioSources();
        preloadExternalAlarmAudio();
        playAlertTone(selectedProfile, "reminder", { preview: true });
        setFormFeedback("soundPreviewReady", "info");
        return false;
    }

    function handleRecurrenceChange() {
        updateRecurrenceState();
    }

    function updateRecurrenceState() {
        var recurring = elements.recurrenceType && elements.recurrenceType.value !== "none";
        var defaultCount = elements.recurrenceType && elements.recurrenceType.value === "weekdays" ? 5 : 8;

        if (!elements.occurrenceCount) {
            return;
        }

        elements.occurrenceCount.disabled = !recurring;

        if (recurring) {
            if (!elements.occurrenceCount.value || Number(elements.occurrenceCount.value) < 2) {
                elements.occurrenceCount.value = defaultCount;
            }
            setFormFeedback("formReady", "info");
            return;
        }

        elements.occurrenceCount.value = 1;
    }

    function setDateTimeToNow() {
        var now = new Date();

        if (elements.meetingDate) {
            elements.meetingDate.value = buildDateValue(now);
        }

        if (elements.meetingTime) {
            elements.meetingTime.value = buildTimeValue(now);
        }

        setFormFeedback("formReady", "info");
    }

    function runHeartbeat() {
        updateCurrentTime();
        runWeeklySeriesRenewal();
        processAlerts();
        renderStats();
        renderMeetingList();
    }

    function loadMeetings(callback) {
        fetchMeetingsFromServer(function (serverMeetings) {
            var fallbackMeetings;

            if (serverMeetings !== null) {
                state.storageMode = "server";
                saveMeetingsToLocal(serverMeetings);
                updateStorageStatus();
                callback(serverMeetings);
                return;
            }

            fallbackMeetings = loadMeetingsFromLocal();
            state.storageMode = "local";
            updateStorageStatus();

            if (fallbackMeetings.length > 0) {
                showToast("serverLoadFallback");
            }

            callback(fallbackMeetings);
        });
    }

    function fetchMeetingsFromServer(callback) {
        requestJson("GET", API_ENDPOINT, null, function (success, payload) {
            if (!success || !payload || payload.ok !== true || !isArray(payload.meetings)) {
                callback(null);
                return;
            }

            callback(payload.meetings);
        });
    }

    function saveMeetingsToServer(meetings, callback) {
        requestJson("POST", API_ENDPOINT, { meetings: meetings }, function (success, payload) {
            callback(Boolean(success && payload && payload.ok === true));
        });
    }

    function loadMeetingsFromLocal() {
        var raw;

        try {
            raw = window.localStorage.getItem(STORAGE_KEY);
            return raw ? JSON.parse(raw) : [];
        } catch (error) {
            return [];
        }
    }

    function saveMeetingsToLocal(meetings) {
        try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(meetings));
            return true;
        } catch (error) {
            return false;
        }
    }

    function persistMeetings(options, callback) {
        var persistOptions = options || {};
        saveMeetingsToLocal(state.meetings);

        saveMeetingsToServer(state.meetings, function (serverSaved) {
            state.storageMode = serverSaved ? "server" : "local";
            updateStorageStatus();

            if (!serverSaved && !persistOptions.silent) {
                showToast("storageFallbackToast");
            }

            if (callback) {
                callback(serverSaved);
            }
        });
    }

    function loadLanguage() {
        try {
            return window.localStorage.getItem(LANGUAGE_KEY) || DEFAULT_LANGUAGE;
        } catch (error) {
            return DEFAULT_LANGUAGE;
        }
    }

    function saveLanguage() {
        try {
            window.localStorage.setItem(LANGUAGE_KEY, state.language);
        } catch (error) {
            return;
        }
    }

    function normalizeMeetingList(meetings) {
        var normalized = [];
        var index;

        if (!isArray(meetings)) {
            return normalized;
        }

        for (index = 0; index < meetings.length; index += 1) {
            normalized.push(normalizeMeeting(meetings[index]));
        }

        return normalized;
    }

    function normalizeRecurrenceTypeValue(recurrenceType) {
        var normalized = String(recurrenceType || "none").toLowerCase();

        if (
            normalized === "daily" ||
            normalized === "weekdays" ||
            normalized === "weekly" ||
            normalized === "biweekly" ||
            normalized === "monthly"
        ) {
            return normalized;
        }

        return "none";
    }

    function normalizeMeeting(meeting) {
        return {
            id: meeting && meeting.id ? String(meeting.id) : createId(),
            workName: meeting && meeting.workName ? String(meeting.workName).replace(/^\s+|\s+$/g, "") : "",
            title: meeting && meeting.title ? String(meeting.title).replace(/^\s+|\s+$/g, "") : "",
            datetime: meeting && meeting.datetime ? String(meeting.datetime).replace(/^\s+|\s+$/g, "") : "",
            reminderMinutes: meeting && meeting.reminderMinutes ? Number(meeting.reminderMinutes) : 15,
            soundProfile: normalizeSoundProfileValue(meeting && meeting.soundProfile ? String(meeting.soundProfile) : "soft"),
            teamsUrl: meeting && meeting.teamsUrl ? String(meeting.teamsUrl).replace(/^\s+|\s+$/g, "") : "",
            notes: meeting && meeting.notes ? String(meeting.notes).replace(/^\s+|\s+$/g, "") : "",
            recurrenceType: normalizeRecurrenceTypeValue(meeting && meeting.recurrenceType ? String(meeting.recurrenceType) : "none"),
            seriesId: meeting && meeting.seriesId ? String(meeting.seriesId) : "",
            occurrenceIndex: meeting && meeting.occurrenceIndex ? Number(meeting.occurrenceIndex) : 1,
            seriesSize: meeting && meeting.seriesSize ? Number(meeting.seriesSize) : 1,
            reminderSent: Boolean(meeting && meeting.reminderSent),
            startSent: Boolean(meeting && meeting.startSent),
            createdAt: meeting && meeting.createdAt ? String(meeting.createdAt) : new Date().toISOString(),
            updatedAt: meeting && meeting.updatedAt ? String(meeting.updatedAt) : new Date().toISOString()
        };
    }

    function sortMeetings(meetings) {
        return meetings.slice(0).sort(function (left, right) {
            return getMeetingTime(left) - getMeetingTime(right);
        });
    }

    function getMeetingTime(meeting) {
        return new Date(meeting.datetime).getTime();
    }

    function getReminderTime(meeting) {
        return getMeetingTime(meeting) - meeting.reminderMinutes * 60 * 1000;
    }

    function isMeetingVisible(meeting) {
        if (state.filter === "all") {
            return true;
        }

        return String(meeting.workName).toLowerCase() === String(state.filter).toLowerCase();
    }

    function handleFormSubmit(event) {
        var payload;
        var validationError;
        var isEditing;
        var createdCount = 1;

        event = event || window.event;
        if (event && event.preventDefault) {
            event.preventDefault();
        } else if (event) {
            event.returnValue = false;
        }

        payload = {
            workName: trimValue(elements.workName.value),
            title: trimValue(elements.meetingTitle.value),
            date: trimValue(elements.meetingDate.value),
            time: trimValue(elements.meetingTime.value),
            datetime: composeMeetingDateTime(trimValue(elements.meetingDate.value), trimValue(elements.meetingTime.value)),
            reminderMinutes: Number(elements.reminderMinutes.value),
            soundProfile: elements.soundProfile ? normalizeSoundProfileValue(elements.soundProfile.value) : "soft",
            recurrenceType: elements.recurrenceType ? normalizeRecurrenceTypeValue(elements.recurrenceType.value) : "none",
            occurrenceCount: elements.occurrenceCount ? parseInt(elements.occurrenceCount.value, 10) : 1,
            teamsUrl: trimValue(elements.teamsUrl.value),
            notes: trimValue(elements.notes.value)
        };

        if (payload.recurrenceType === "none") {
            payload.occurrenceCount = 1;
        }

        validationError = validateMeeting(payload);
        if (validationError) {
            setFormFeedback(validationError, "error");
            showToast(validationError);
            return false;
        }

        isEditing = Boolean(state.editingId);
        setFormBusy(true);
        clearFormFeedback();

        try {
            if (isEditing) {
                updateMeetingFromPayload(payload);
            } else {
                createdCount = addMeetingsFromPayload(payload);
            }

            state.meetings = sortMeetings(state.meetings);
            renderFilterOptions();
            renderAll();

            persistMeetings({}, function () {
                resetForm();
                renderFilterOptions();
                renderAll();
                setFormFeedback(
                    isEditing
                        ? "formUpdatedSingle"
                        : createdCount > 1
                            ? formatText("formSavedSeries", { count: createdCount })
                            : "formSavedSingle",
                    createdCount > 1 ? "success" : "success",
                    createdCount > 1
                );
                showToast(isEditing ? "updated" : "saved");
                setFormBusy(false);
            });
        } catch (error) {
            setFormBusy(false);
            setFormFeedback("saveError", "error");
            showToast("saveError");
        }

        return false;
    }

    function addMeetingsFromPayload(payload) {
        var series = buildMeetingsFromPayload(payload);
        var index;

        for (index = 0; index < series.length; index += 1) {
            state.meetings.push(series[index]);
        }

        return series.length;
    }

    function buildMeetingsFromPayload(payload) {
        var meetings = [];
        var seriesId = payload.recurrenceType === "none" ? "" : createId();
        var baseDate = new Date(payload.datetime);
        var total = payload.recurrenceType === "none" ? 1 : payload.occurrenceCount;
        var index;
        var occurrenceDate;

        for (index = 0; index < total; index += 1) {
            occurrenceDate = addRecurrenceToDate(baseDate, payload.recurrenceType, index);
            meetings.push(
                normalizeMeeting({
                    workName: payload.workName,
                    title: payload.title,
                    datetime: buildDateTimeValue(occurrenceDate),
                    reminderMinutes: payload.reminderMinutes,
                    soundProfile: payload.soundProfile,
                    teamsUrl: payload.teamsUrl,
                    notes: payload.notes,
                    recurrenceType: payload.recurrenceType,
                    seriesId: seriesId,
                    occurrenceIndex: index + 1,
                    seriesSize: total,
                    id: createId(),
                    reminderSent: false,
                    startSent: false,
                    createdAt: new Date().toISOString(),
                    updatedAt: new Date().toISOString()
                })
            );
        }

        return meetings;
    }

    function addRecurrenceToDate(baseDate, recurrenceType, stepIndex) {
        var nextDate = new Date(baseDate.getTime());

        if (recurrenceType === "weekdays") {
            return addWeekdayRecurrenceToDate(baseDate, stepIndex);
        }

        if (stepIndex === 0 || recurrenceType === "none") {
            return nextDate;
        }

        if (recurrenceType === "daily") {
            nextDate.setDate(nextDate.getDate() + stepIndex);
            return nextDate;
        }

        if (recurrenceType === "weekly") {
            nextDate.setDate(nextDate.getDate() + stepIndex * 7);
            return nextDate;
        }

        if (recurrenceType === "biweekly") {
            nextDate.setDate(nextDate.getDate() + stepIndex * 14);
            return nextDate;
        }

        if (recurrenceType === "monthly") {
            nextDate.setMonth(nextDate.getMonth() + stepIndex);
            return nextDate;
        }

        return nextDate;
    }

    function addWeekdayRecurrenceToDate(baseDate, stepIndex) {
        var nextDate = new Date(baseDate.getTime());
        var remainingSteps = stepIndex;

        while (remainingSteps > 0) {
            nextDate.setDate(nextDate.getDate() + 1);

            if (!isWeekendDate(nextDate)) {
                remainingSteps -= 1;
            }
        }

        return nextDate;
    }

    function updateMeetingFromPayload(payload) {
        var index;
        var meeting;

        for (index = 0; index < state.meetings.length; index += 1) {
            meeting = state.meetings[index];
            if (meeting.id === state.editingId) {
                state.meetings[index] = normalizeMeeting({
                    id: meeting.id,
                    workName: payload.workName,
                    title: payload.title,
                    datetime: payload.datetime,
                    reminderMinutes: payload.reminderMinutes,
                    soundProfile: payload.soundProfile,
                    teamsUrl: payload.teamsUrl,
                    notes: payload.notes,
                    recurrenceType: payload.recurrenceType,
                    seriesId: meeting.seriesId,
                    occurrenceIndex: meeting.occurrenceIndex,
                    seriesSize: meeting.seriesSize,
                    reminderSent: false,
                    startSent: false,
                    createdAt: meeting.createdAt,
                    updatedAt: new Date().toISOString()
                });
                break;
            }
        }
    }

    function validateMeeting(payload) {
        if (!payload.workName) {
            return "validationWork";
        }

        if (!payload.title) {
            return "validationTitle";
        }

        if (!payload.date || !isValidDateValue(payload.date)) {
            return "validationDate";
        }

        if (!payload.time || !isValidTimeValue(payload.time)) {
            return "validationTime";
        }

        if (!payload.datetime || isNaN(new Date(payload.datetime).getTime())) {
            return "validationDate";
        }

        if (payload.recurrenceType === "weekdays" && isWeekendDate(new Date(payload.datetime))) {
            return "validationWeekdayStart";
        }

        if (!isFinite(payload.reminderMinutes) || payload.reminderMinutes < 1) {
            return "validationReminder";
        }

        if (!isFinite(payload.occurrenceCount) || payload.occurrenceCount < 1 || payload.occurrenceCount > 52) {
            return "validationOccurrences";
        }

        if (payload.teamsUrl && !isHttpUrl(payload.teamsUrl)) {
            return "validationTeamsUrl";
        }

        return "";
    }

    function resetForm() {
        state.editingId = null;

        if (elements.meetingForm && elements.meetingForm.reset) {
            elements.meetingForm.reset();
        }

        elements.reminderMinutes.value = 15;
        if (elements.soundProfile) {
            elements.soundProfile.value = "soft";
        }
        if (elements.recurrenceType) {
            elements.recurrenceType.value = "none";
        }
        if (elements.occurrenceCount) {
            elements.occurrenceCount.value = 1;
        }
        elements.meetingId.value = "";
        updateRecurrenceState();
        setFormFeedback("formReady", "info");
        updateSaveButtonLabel();
    }

    function populateForm(meetingId) {
        var meeting = findMeetingById(meetingId);

        if (!meeting) {
            return;
        }

        state.editingId = meeting.id;
        elements.meetingId.value = meeting.id;
        elements.workName.value = meeting.workName;
        elements.meetingTitle.value = meeting.title;
        elements.meetingDate.value = extractDateValue(meeting.datetime);
        elements.meetingTime.value = extractTimeValue(meeting.datetime);
        elements.reminderMinutes.value = meeting.reminderMinutes;
        if (elements.soundProfile) {
            elements.soundProfile.value = normalizeSoundProfileValue(meeting.soundProfile);
        }
        if (elements.recurrenceType) {
            elements.recurrenceType.value = meeting.recurrenceType || "none";
        }
        if (elements.occurrenceCount) {
            elements.occurrenceCount.value = meeting.seriesSize || 1;
        }
        elements.teamsUrl.value = meeting.teamsUrl;
        elements.notes.value = meeting.notes;
        updateRecurrenceState();
        setFormFeedback("formReady", "info");
        updateSaveButtonLabel();
        elements.workName.focus();
    }

    function handleFilterChange(event) {
        event = event || window.event;
        state.filter = event && event.target ? event.target.value : elements.workFilter.value;
        renderMeetingList();
    }

    function handleMeetingListClick(event) {
        var actionElement;
        var action;
        var meetingId;

        event = event || window.event;
        actionElement = closestWithAction(event.target || event.srcElement);
        if (!actionElement) {
            return;
        }

        action = actionElement.getAttribute("data-action");
        meetingId = actionElement.getAttribute("data-meeting-id");
        if (!meetingId) {
            return;
        }

        if (action === "edit") {
            populateForm(meetingId);
            return;
        }

        if (action === "delete") {
            deleteMeeting(meetingId);
            return;
        }

        if (action === "open") {
            openMeetingLinkById(meetingId);
        }
    }

    function deleteMeeting(meetingId) {
        var filtered = [];
        var index;

        if (!window.confirm(t("deleteConfirm"))) {
            return;
        }

        setFormBusy(true);

        try {
            for (index = 0; index < state.meetings.length; index += 1) {
                if (state.meetings[index].id !== meetingId) {
                    filtered.push(state.meetings[index]);
                }
            }

            state.meetings = filtered;

            persistMeetings({}, function () {
                if (state.editingId === meetingId) {
                    resetForm();
                }

                renderFilterOptions();
                renderAll();
                showToast("deleted");
                setFormBusy(false);
            });
        } catch (error) {
            setFormBusy(false);
            showToast("deleteError");
        }
    }

    function isHttpUrl(value) {
        return (/^https?:\/\//i).test(String(value || ""));
    }

    function openMeetingLinkById(meetingId) {
        var meeting = findMeetingById(meetingId);

        if (!meeting || !isHttpUrl(meeting.teamsUrl)) {
            showToast("openTeamsUnavailable");
            return;
        }

        window.open(meeting.teamsUrl, "_blank");
    }

    function renderAll() {
        updateSaveButtonLabel();
        updateStorageStatus();
        renderStats();
        renderMeetingList();
    }

    function renderStats() {
        var now = Date.now ? Date.now() : new Date().getTime();
        var todayCount = countMeetingsForToday();
        var upcomingMeeting = findUpcomingMeeting(now);
        var nextAlert = getNextAlert(now);

        elements.totalMeetingsValue.innerHTML = String(state.meetings.length);
        elements.todayMeetingsValue.innerHTML = String(todayCount);
        elements.nextMeetingValue.innerHTML = upcomingMeeting
            ? escapeHtml(upcomingMeeting.title + " · " + formatRelativeTime(getMeetingTime(upcomingMeeting) - now))
            : escapeHtml(t("nextMeetingNone"));
        elements.nextAlertValue.innerHTML = nextAlert
            ? escapeHtml(nextAlert.label + " · " + formatRelativeTime(nextAlert.timestamp - now))
            : escapeHtml(t("nextAlertNone"));
    }

    function countMeetingsForToday() {
        var count = 0;
        var now = new Date();
        var index;

        for (index = 0; index < state.meetings.length; index += 1) {
            if (isSameDay(new Date(state.meetings[index].datetime), now)) {
                count += 1;
            }
        }

        return count;
    }

    function findUpcomingMeeting(now) {
        var index;

        for (index = 0; index < state.meetings.length; index += 1) {
            if (getMeetingTime(state.meetings[index]) >= now) {
                return state.meetings[index];
            }
        }

        return null;
    }

    function renderFilterOptions() {
        var previousValue = state.filter;
        var workNames = getUniqueWorkNames();
        var html = ['<option value="all">' + escapeHtml(t("allWorks")) + '</option>'];
        var index;

        for (index = 0; index < workNames.length; index += 1) {
            html.push('<option value="' + escapeAttribute(workNames[index]) + '">' + escapeHtml(workNames[index]) + '</option>');
        }

        elements.workFilter.innerHTML = html.join("");
        state.filter = arrayContains(workNames, previousValue) ? previousValue : "all";
        elements.workFilter.value = state.filter;
    }

    function getUniqueWorkNames() {
        var names = [];
        var index;
        var workName;

        for (index = 0; index < state.meetings.length; index += 1) {
            workName = state.meetings[index].workName;
            if (workName && !arrayContains(names, workName)) {
                names.push(workName);
            }
        }

        names.sort();
        return names;
    }

    function renderMeetingList() {
        var now = Date.now ? Date.now() : new Date().getTime();
        var visibleMeetings = getVisibleMeetings();
        var html = [];
        var index;

        elements.meetingCount.innerHTML = String(visibleMeetings.length);
        elements.emptyState.style.display = visibleMeetings.length === 0 ? "block" : "none";

        if (visibleMeetings.length === 0) {
            elements.meetingList.innerHTML = "";
            return;
        }

        for (index = 0; index < visibleMeetings.length; index += 1) {
            html.push(renderMeetingCard(visibleMeetings[index], now));
        }

        elements.meetingList.innerHTML = html.join("");
    }

    function getVisibleMeetings() {
        var visible = [];
        var index;

        for (index = 0; index < state.meetings.length; index += 1) {
            if (isMeetingVisible(state.meetings[index])) {
                visible.push(state.meetings[index]);
            }
        }

        return visible;
    }

    function renderMeetingCard(meeting, now) {
        var status = getMeetingStatus(meeting, now);
        var cardColor = stringToColor(meeting.workName);
        var meetingTime = getMeetingTime(meeting);
        var reminderTime = getReminderTime(meeting);
        var countdownLabel = meetingTime <= now
            ? t("startedAgo") + " " + formatRelativeTime(now - meetingTime)
            : t("startsIn") + " " + formatRelativeTime(meetingTime - now);
        var recurrenceSummary = getRecurrenceSummary(meeting);
        var soundLabel = getSoundProfileLabel(meeting.soundProfile);

        return ''
            + '<article class="meeting-card meeting-card--' + escapeAttribute(status) + '">'
            + '    <div class="meeting-card__top">'
            + '        <div>'
            + '            <h4 class="meeting-card__title">' + escapeHtml(meeting.title) + '</h4>'
            + '            <div class="meeting-card__meta">'
            + '                <span>' + escapeHtml(t("footerDateLabel")) + ': ' + escapeHtml(formatDateTime(meeting.datetime)) + '</span>'
            + '                <span>' + escapeHtml(t("footerReminderLabel")) + ': ' + escapeHtml(meeting.reminderMinutes + " " + t("minutesSuffix")) + '</span>'
            + '            </div>'
            + '        </div>'
            + '        <span class="meeting-card__work" style="background:' + escapeAttribute(cardColor) + ';">'
            +              escapeHtml(meeting.workName)
            + '        </span>'
            + '    </div>'
            + '    <p class="meeting-card__countdown">' + escapeHtml(countdownLabel) + '</p>'
            + '    <div class="meeting-card__footer">'
            + '        <div>'
            + '            <span class="status-badge status-badge--' + escapeAttribute(status) + '">' + escapeHtml(t(status)) + '</span>'
            + '        </div>'
            + '        <div class="meeting-card__actions">'
            + '            <button class="button button--ghost" type="button" data-action="open" data-meeting-id="' + escapeAttribute(meeting.id) + '">' + escapeHtml(t("openTeams")) + '</button>'
            + '            <button class="button button--ghost" type="button" data-action="edit" data-meeting-id="' + escapeAttribute(meeting.id) + '">' + escapeHtml(t("edit")) + '</button>'
            + '            <button class="button button--ghost" type="button" data-action="delete" data-meeting-id="' + escapeAttribute(meeting.id) + '">' + escapeHtml(t("delete")) + '</button>'
            + '        </div>'
            + '    </div>'
            + '    <p class="meeting-card__notes">'
            + '        <strong>' + escapeHtml(t("footerWorkLabel")) + ':</strong> ' + escapeHtml(meeting.workName)
            + '        <br>'
            + '        <strong>' + escapeHtml(t("reminderAt")) + ':</strong> ' + escapeHtml(formatDateTime(reminderTime))
            + '        <br>'
            + '        <strong>' + escapeHtml(t("teamsLabel")) + ':</strong> ' + escapeHtml(meeting.teamsUrl || t("noTeamsLink"))
            + '        <br>'
            + '        <strong>' + escapeHtml(t("repeatCardLabel")) + ':</strong> ' + escapeHtml(recurrenceSummary)
            + '        <br>'
            + '        <strong>' + escapeHtml(t("soundCardLabel")) + ':</strong> ' + escapeHtml(soundLabel)
            + '        <br>'
            + '        <strong>' + escapeHtml(t("notesLabelCard")) + ':</strong> ' + escapeHtml(meeting.notes || t("noNotes"))
            + '    </p>'
            + '</article>';
    }

    function getMeetingStatus(meeting, now) {
        var meetingTime = getMeetingTime(meeting);
        var reminderTime = getReminderTime(meeting);
        var liveWindow = MEETING_LIVE_WINDOW_MINUTES * 60 * 1000;

        if (now >= meetingTime && now < meetingTime + liveWindow) {
            return "live";
        }

        if (now >= reminderTime && now < meetingTime) {
            return "dueSoon";
        }

        if (now < reminderTime) {
            return "upcoming";
        }

        return "past";
    }

    function processAlerts() {
        var now = Date.now ? Date.now() : new Date().getTime();
        var hasChanges = false;
        var index;
        var meeting;
        var reminderTime;
        var meetingTime;
        var reminderWindowEnd;

        for (index = 0; index < state.meetings.length; index += 1) {
            meeting = state.meetings[index];
            reminderTime = getReminderTime(meeting);
            meetingTime = getMeetingTime(meeting);
            reminderWindowEnd = meetingTime + 10 * 60 * 1000;

            if (!meeting.reminderSent && now >= reminderTime && now < meetingTime) {
                notifyMeeting(meeting, "reminder");
                meeting.reminderSent = true;
                hasChanges = true;
            } else if (!meeting.reminderSent && now >= meetingTime) {
                meeting.reminderSent = true;
                hasChanges = true;
            }

            if (!meeting.startSent && now >= meetingTime && now <= reminderWindowEnd) {
                notifyMeeting(meeting, "start");
                meeting.startSent = true;
                hasChanges = true;
            } else if (!meeting.startSent && now > reminderWindowEnd) {
                meeting.startSent = true;
                hasChanges = true;
            }
        }

        if (hasChanges) {
            persistMeetings({ silent: true }, function () {});
        }
    }

    function getNextAlert(now) {
        var candidates = [];
        var index;
        var meeting;
        var reminderTime;
        var meetingTime;

        for (index = 0; index < state.meetings.length; index += 1) {
            meeting = state.meetings[index];
            reminderTime = getReminderTime(meeting);
            meetingTime = getMeetingTime(meeting);

            if (!meeting.reminderSent && reminderTime > now) {
                candidates.push({
                    timestamp: reminderTime,
                    label: t("alertReminderTitle") + ": " + meeting.title
                });
            }

            if (!meeting.startSent && meetingTime > now) {
                candidates.push({
                    timestamp: meetingTime,
                    label: t("alertStartTitle") + ": " + meeting.title
                });
            }
        }

        candidates.sort(function (left, right) {
            return left.timestamp - right.timestamp;
        });

        return candidates.length > 0 ? candidates[0] : null;
    }

    // Recurring series are created with a finite occurrenceCount (see buildMeetingsFromPayload).
    // Without this renewal pass, a standing daily/weekly meeting silently runs out of future
    // occurrences and stops reminding, with no error or warning anywhere in the app.
    function runWeeklySeriesRenewal() {
        var now = Date.now ? Date.now() : new Date().getTime();
        var lookaheadTarget = getMostRecentFridayEod(now) + RENEWAL_LOOKAHEAD_MS;
        var seriesMap = groupMeetingsBySeries();
        var seriesId;
        var createdTotal = 0;

        for (seriesId in seriesMap) {
            if (seriesMap.hasOwnProperty(seriesId)) {
                createdTotal += extendSeriesIfNeeded(seriesMap[seriesId], now, lookaheadTarget);
            }
        }

        if (createdTotal > 0) {
            state.meetings = sortMeetings(state.meetings);
            persistMeetings({ silent: true }, function () {});
            showToast(formatText("renewalToast", { count: createdTotal }), true);
        }
    }

    // Returns the timestamp of the most recent Friday at RENEWAL_TRIGGER_HOUR local time
    // that has already passed (today's Friday if we're past it, otherwise last week's).
    // This is only the *trigger reference point*; extendSeriesIfNeeded still fast-forwards
    // through any past occurrences instead of backfilling them.
    function getMostRecentFridayEod(now) {
        var daysSinceMonday = (new Date(now).getDay() + 6) % 7;
        var monday = new Date(now);
        var friday;

        monday.setHours(0, 0, 0, 0);
        monday.setDate(monday.getDate() - daysSinceMonday);

        friday = new Date(monday.getTime());
        friday.setDate(friday.getDate() + 4);
        friday.setHours(RENEWAL_TRIGGER_HOUR, 0, 0, 0);

        if (friday.getTime() > now) {
            friday.setDate(friday.getDate() - 7);
        }

        return friday.getTime();
    }

    function groupMeetingsBySeries() {
        var groups = {};
        var index;
        var meeting;

        for (index = 0; index < state.meetings.length; index += 1) {
            meeting = state.meetings[index];

            if (meeting.recurrenceType === "none" || !meeting.seriesId) {
                continue;
            }

            if (!groups[meeting.seriesId]) {
                groups[meeting.seriesId] = [];
            }

            groups[meeting.seriesId].push(meeting);
        }

        return groups;
    }

    function findLatestMeeting(seriesMeetings) {
        var latest = seriesMeetings[0];
        var index;

        for (index = 1; index < seriesMeetings.length; index += 1) {
            if (getMeetingTime(seriesMeetings[index]) > getMeetingTime(latest)) {
                latest = seriesMeetings[index];
            }
        }

        return latest;
    }

    function syncSeriesSize(seriesMeetings, size) {
        var index;

        for (index = 0; index < seriesMeetings.length; index += 1) {
            seriesMeetings[index].seriesSize = size;
        }
    }

    // Walks the series forward one recurrence step at a time from its latest known
    // occurrence. Steps that already fall in the past are skipped (not materialized)
    // so a long-dormant series does not get backfilled with dead entries; the cursor
    // still advances through them to keep the correct weekday/time-of-day alignment.
    function extendSeriesIfNeeded(seriesMeetings, now, lookaheadTarget) {
        var latestMeeting = findLatestMeeting(seriesMeetings);
        var lastCreatedMeeting = latestMeeting;
        var cursorTime = getMeetingTime(latestMeeting);
        var cursorDate;
        var created = 0;
        var safety = 0;

        if (cursorTime >= lookaheadTarget) {
            return 0;
        }

        while (cursorTime < lookaheadTarget && safety < RENEWAL_MAX_STEPS_PER_SERIES) {
            cursorDate = addRecurrenceToDate(new Date(cursorTime), latestMeeting.recurrenceType, 1);
            cursorTime = cursorDate.getTime();
            safety += 1;

            if (cursorTime >= now) {
                lastCreatedMeeting = normalizeMeeting({
                    workName: latestMeeting.workName,
                    title: latestMeeting.title,
                    datetime: buildDateTimeValue(cursorDate),
                    reminderMinutes: latestMeeting.reminderMinutes,
                    soundProfile: latestMeeting.soundProfile,
                    teamsUrl: latestMeeting.teamsUrl,
                    notes: latestMeeting.notes,
                    recurrenceType: latestMeeting.recurrenceType,
                    seriesId: latestMeeting.seriesId,
                    occurrenceIndex: lastCreatedMeeting.occurrenceIndex + 1,
                    seriesSize: lastCreatedMeeting.seriesSize + 1,
                    id: createId(),
                    reminderSent: false,
                    startSent: false,
                    createdAt: new Date().toISOString(),
                    updatedAt: new Date().toISOString()
                });

                state.meetings.push(lastCreatedMeeting);
                seriesMeetings.push(lastCreatedMeeting);
                created += 1;
            }
        }

        if (created > 0) {
            syncSeriesSize(seriesMeetings, lastCreatedMeeting.seriesSize);
        }

        return created;
    }

    // The client only ever fetched the meeting list once, at startup. A tab left open
    // for days never learned about meetings added from another tab/device, and its next
    // autosave (a full-array POST, see api/meetings.php) would silently overwrite the
    // server copy with that stale list -- erasing the meetings it never saw. This keeps
    // a long-lived tab in sync so it cannot lose or miss meetings created elsewhere.
    function syncFromServer() {
        if (state.syncInFlight) {
            return;
        }

        state.syncInFlight = true;

        fetchMeetingsFromServer(function (serverMeetings) {
            state.syncInFlight = false;

            if (serverMeetings === null) {
                return;
            }

            mergeServerMeetings(normalizeMeetingList(serverMeetings));
        });
    }

    function mergeServerMeetings(serverMeetings) {
        var merged = [];
        var localById = {};
        var seenIds = {};
        var index;
        var id;
        var localMeeting;
        var now = Date.now ? Date.now() : new Date().getTime();
        var beforeSnapshot;
        var afterSnapshot;

        for (index = 0; index < state.meetings.length; index += 1) {
            localById[state.meetings[index].id] = state.meetings[index];
        }

        for (index = 0; index < serverMeetings.length; index += 1) {
            id = serverMeetings[index].id;
            seenIds[id] = true;
            localMeeting = localById[id];
            merged.push(localMeeting ? mergeMeetingPair(localMeeting, serverMeetings[index]) : serverMeetings[index]);
        }

        for (index = 0; index < state.meetings.length; index += 1) {
            localMeeting = state.meetings[index];

            if (seenIds[localMeeting.id]) {
                continue;
            }

            if (now - new Date(localMeeting.createdAt).getTime() < SYNC_MERGE_GRACE_MS) {
                merged.push(localMeeting);
            }
        }

        merged = sortMeetings(merged);
        beforeSnapshot = JSON.stringify(sortMeetings(state.meetings));
        afterSnapshot = JSON.stringify(merged);

        if (beforeSnapshot === afterSnapshot) {
            return;
        }

        state.meetings = merged;
        renderFilterOptions();
        renderAll();
        persistMeetings({ silent: true }, function () {});
    }

    // Once a reminder/start alert has fired anywhere, it must stay fired everywhere --
    // otherwise merging in an older copy of a meeting could replay an alarm that was
    // already dismissed.
    function mergeMeetingPair(localMeeting, serverMeeting) {
        var localUpdated = new Date(localMeeting.updatedAt).getTime();
        var serverUpdated = new Date(serverMeeting.updatedAt).getTime();
        var base = serverUpdated > localUpdated ? serverMeeting : localMeeting;

        return normalizeMeeting({
            id: base.id,
            workName: base.workName,
            title: base.title,
            datetime: base.datetime,
            reminderMinutes: base.reminderMinutes,
            soundProfile: base.soundProfile,
            teamsUrl: base.teamsUrl,
            notes: base.notes,
            recurrenceType: base.recurrenceType,
            seriesId: base.seriesId,
            occurrenceIndex: base.occurrenceIndex,
            seriesSize: base.seriesSize,
            reminderSent: Boolean(localMeeting.reminderSent || serverMeeting.reminderSent),
            startSent: Boolean(localMeeting.startSent || serverMeeting.startSent),
            createdAt: base.createdAt,
            updatedAt: base.updatedAt
        });
    }

    function notifyMeeting(meeting, mode) {
        var isStartMode = mode === "start";
        var title = isStartMode ? t("alertStartTitle") : t("alertReminderTitle");
        var body = meeting.workName + " · " + meeting.title;
        var tag = isStartMode ? t("alertDialogStartTag") : t("alertDialogReminderTag");

        startAlarmSequence({
            meeting: meeting,
            mode: mode,
            title: title,
            body: body,
            tag: tag
        });

        showAlertDialog({
            tag: tag,
            title: title,
            message: body + "\n" + formatDateTime(meeting.datetime),
            teamsUrl: meeting.teamsUrl
        });

        showBrowserNotification(title, body + " · " + formatDateTime(meeting.datetime), meeting.teamsUrl);
    }

    function startAlarmSequence(context) {
        var soundSettings = getSoundSettings(context.meeting.soundProfile, context.mode);
        var usingLoopingAsset;

        stopAlarmSequence();

        state.currentAlertUrl = context.meeting.teamsUrl || "";
        state.currentAlertMeetingId = context.meeting.id;

        if (document.body && document.body.className.indexOf("is-alarm-active") === -1) {
            document.body.className += (document.body.className ? " " : "") + "is-alarm-active";
        }

        elements.alarmOverlay.hidden = false;
        elements.alarmOverlayTag.innerHTML = escapeHtml(t("alarmOverlayTag"));
        elements.alarmOverlayTitle.innerHTML = escapeHtml(context.title);
        elements.alarmOverlayBody.innerHTML = escapeHtml(context.body + ". " + t("alarmOverlayHint"));
        elements.alarmOverlayMeta.innerHTML = escapeHtml(formatDateTime(context.meeting.datetime) + " · " + context.meeting.workName);
        elements.alarmOpenButton.disabled = !state.currentAlertUrl;

        usingLoopingAsset = playAlertTone(context.meeting.soundProfile, context.mode, { loop: true });
        blinkDocumentTitle(context.title);

        if (navigator.vibrate) {
            navigator.vibrate(soundSettings.vibration);
        }

        state.alarmIntervalId = window.setInterval(function () {
            if (!usingLoopingAsset) {
                usingLoopingAsset = playAlertTone(context.meeting.soundProfile, context.mode, { loop: true });
            }
            if (navigator.vibrate) {
                navigator.vibrate(soundSettings.repeatVibration);
            }
        }, soundSettings.repeatDelay);
    }

    function stopAlarmSequence() {
        if (state.alarmIntervalId) {
            window.clearInterval(state.alarmIntervalId);
            state.alarmIntervalId = 0;
        }

        if (state.titleBlinkIntervalId) {
            window.clearInterval(state.titleBlinkIntervalId);
            state.titleBlinkIntervalId = 0;
        }

        if (navigator.vibrate) {
            navigator.vibrate(0);
        }

        state.currentAlertUrl = "";
        state.currentAlertMeetingId = "";
        document.title = state.baseTitle;
        removeClass(document.body, "is-alarm-active");
        elements.alarmOverlay.hidden = true;
        stopActiveAudioSources();
    }

    function blinkDocumentTitle(alertTitle) {
        var visible = false;

        document.title = alertTitle;
        state.titleBlinkIntervalId = window.setInterval(function () {
            visible = !visible;
            document.title = visible ? alertTitle + " | TimerMeet" : state.baseTitle;
        }, 850);
    }

    function showBrowserNotification(title, body, url) {
        if (!("Notification" in window) || Notification.permission !== "granted") {
            return;
        }

        try {
            var notification = new Notification(title, {
                body: body,
                tag: title,
                silent: true
            });

            notification.onclick = function () {
                window.focus();
                if (url) {
                    window.open(url, "_blank");
                }
                notification.close();
            };
        } catch (error) {
            return;
        }
    }

    function requestNotificationPermission() {
        if (!("Notification" in window)) {
            showToast("browserNotificationUnsupported");
            return;
        }

        if (Notification.requestPermission.length === 0) {
            Notification.requestPermission().then(function (permission) {
                updateNotificationButtonLabel();
                showToast(permission === "granted" ? "notificationsGrantedToast" : "notificationsDeniedToast");
            });
            return;
        }

        Notification.requestPermission(function (permission) {
            updateNotificationButtonLabel();
            showToast(permission === "granted" ? "notificationsGrantedToast" : "notificationsDeniedToast");
        });
    }

    function updateNotificationButtonLabel() {
        if (!("Notification" in window)) {
            elements.notificationButton.innerHTML = escapeHtml(t("browserNotificationUnsupported"));
            elements.notificationButton.disabled = true;
            return;
        }

        elements.notificationButton.disabled = false;

        if (Notification.permission === "granted") {
            elements.notificationButton.innerHTML = escapeHtml(t("notificationsEnabled"));
            return;
        }

        if (Notification.permission === "denied") {
            elements.notificationButton.innerHTML = escapeHtml(t("notificationsBlocked"));
            return;
        }

        elements.notificationButton.innerHTML = escapeHtml(t("enableNotifications"));
    }

    function toggleLanguage() {
        state.language = state.language === "es" ? "en" : "es";
        saveLanguage();
        applyTranslations();
        renderFilterOptions();
        renderAll();
        updateNotificationButtonLabel();
    }

    function applyTranslations() {
        var i;
        var nodes;
        var currentRecurrence = elements.recurrenceType ? elements.recurrenceType.value : "none";

        document.documentElement.lang = state.language;
        state.baseTitle = state.language === "es" ? "TimerMeet | Recordatorios de Teams" : "TimerMeet | Teams reminders";
        document.title = state.baseTitle;

        nodes = document.querySelectorAll("[data-i18n]");
        for (i = 0; i < nodes.length; i += 1) {
            nodes[i].innerHTML = escapeHtml(t(nodes[i].getAttribute("data-i18n")));
        }

        nodes = document.querySelectorAll("[data-i18n-placeholder]");
        for (i = 0; i < nodes.length; i += 1) {
            nodes[i].setAttribute("placeholder", t(nodes[i].getAttribute("data-i18n-placeholder")));
        }

        renderRecurrenceOptions();
        if (elements.recurrenceType) {
            elements.recurrenceType.value = currentRecurrence || "none";
        }

        elements.languageButton.innerHTML = state.language === "es" ? "EN" : "ES";
        updateStorageStatus();
    }

    function updateSaveButtonLabel() {
        elements.saveButton.innerHTML = escapeHtml(state.editingId ? t("updateButton") : t("saveButton"));
    }

    function updateStorageStatus() {
        if (!elements.storageStatusValue) {
            return;
        }

        elements.storageStatusValue.innerHTML = escapeHtml(state.storageMode === "server" ? t("storageServer") : t("storageLocal"));
    }

    function updateCurrentTime() {
        elements.currentTimeValue.innerHTML = escapeHtml(formatDateTime(new Date(), true));
    }

    function showToast(messageKeyOrText, isPlainText) {
        if (toastTimer) {
            window.clearTimeout(toastTimer);
        }

        elements.toast.innerHTML = escapeHtml(isPlainText ? messageKeyOrText : t(messageKeyOrText));
        addClass(elements.toast, "is-visible");

        toastTimer = window.setTimeout(function () {
            removeClass(elements.toast, "is-visible");
        }, 2600);
    }

    function ensureAudioContext() {
        var AudioApi = window.AudioContext || window.webkitAudioContext;

        if (!AudioApi) {
            return null;
        }

        if (!state.audioContext) {
            state.audioContext = new AudioApi();
        }

        if (state.audioContext.state === "suspended" && state.audioContext.resume) {
            state.audioContext.resume();
        }

        return state.audioContext;
    }

    function preloadExternalAlarmAudio() {
        ensureExternalAlarmAudioLoaded("siren");
        ensureExternalAlarmAudioLoaded("fire");
    }

    function ensureExternalAlarmAudioLoaded(assetKey) {
        var audioContext = ensureAudioContext();
        var asset = AUDIO_ASSETS[assetKey];
        var xhr;

        if (!audioContext || !asset || state.audioBuffers[assetKey] || state.audioBufferRequests[assetKey]) {
            return;
        }

        state.audioBufferRequests[assetKey] = true;
        xhr = new XMLHttpRequest();
        xhr.open("GET", asset.url, true);
        xhr.responseType = "arraybuffer";
        xhr.onload = function () {
            if (xhr.status < 200 || xhr.status >= 300 || !xhr.response) {
                delete state.audioBufferRequests[assetKey];
                return;
            }

            decodeAudioDataSafe(audioContext, xhr.response, function (buffer) {
                state.audioBuffers[assetKey] = buffer;
                delete state.audioBufferRequests[assetKey];
            }, function () {
                delete state.audioBufferRequests[assetKey];
            });
        };
        xhr.onerror = function () {
            delete state.audioBufferRequests[assetKey];
        };

        try {
            xhr.send();
        } catch (error) {
            delete state.audioBufferRequests[assetKey];
        }
    }

    function decodeAudioDataSafe(audioContext, audioData, onSuccess, onError) {
        var decodeResult;
        var completed = false;

        function handleSuccess(buffer) {
            if (completed) {
                return;
            }

            completed = true;
            onSuccess(buffer);
        }

        function handleError() {
            if (completed) {
                return;
            }

            completed = true;
            onError();
        }

        try {
            decodeResult = audioContext.decodeAudioData(
                audioData,
                function (buffer) {
                    handleSuccess(buffer);
                },
                function () {
                    handleError();
                }
            );

            if (decodeResult && typeof decodeResult.then === "function") {
                decodeResult.then(handleSuccess, handleError);
            }
        } catch (error) {
            handleError();
        }
    }

    function playAlertTone(soundProfile, mode, options) {
        var audioContext = ensureAudioContext();
        var soundSettings;
        var pattern;
        var index;
        var usedExternalAsset;

        options = options || {};

        if (!audioContext) {
            return false;
        }

        soundSettings = getSoundSettings(soundProfile, mode);
        usedExternalAsset = playExternalAlarmAudio(audioContext, soundSettings, options);
        if (usedExternalAsset) {
            return true;
        }

        pattern = soundSettings.pattern;

        for (index = 0; index < pattern.length; index += 1) {
            playSingleTone(audioContext, pattern[index], soundSettings);
        }

        return false;
    }

    function playExternalAlarmAudio(audioContext, soundSettings, options) {
        var asset = soundSettings.assetKey ? AUDIO_ASSETS[soundSettings.assetKey] : null;
        var buffer;
        var source;
        var gain;
        var offset;
        var duration;

        if (!asset) {
            return false;
        }

        ensureExternalAlarmAudioLoaded(asset.key);
        buffer = state.audioBuffers[asset.key];

        if (!buffer) {
            return false;
        }

        source = audioContext.createBufferSource();
        gain = audioContext.createGain();
        source.buffer = buffer;
        gain.gain.value = asset.gain || 1;
        source.connect(gain);
        gain.connect(audioContext.destination);

        if (options.loop) {
            source.loop = true;
            source.loopStart = asset.loopStart || 0;
            source.loopEnd = asset.loopEnd && asset.loopEnd <= buffer.duration ? asset.loopEnd : buffer.duration;
            source.start(0, asset.loopStart || 0);
        } else {
            offset = asset.previewStart || 0;
            duration = asset.previewSeconds || Math.min(4, buffer.duration);

            if (offset + duration > buffer.duration) {
                duration = Math.max(0.4, buffer.duration - offset);
            }

            source.start(0, offset, duration);
        }

        registerActiveAudioSource(source);
        return true;
    }

    function registerActiveAudioSource(source) {
        state.activeAudioSources.push(source);
        source.onended = function () {
            removeActiveAudioSource(source);
        };
    }

    function removeActiveAudioSource(source) {
        var nextSources = [];
        var index;

        for (index = 0; index < state.activeAudioSources.length; index += 1) {
            if (state.activeAudioSources[index] !== source) {
                nextSources.push(state.activeAudioSources[index]);
            }
        }

        state.activeAudioSources = nextSources;
    }

    function stopActiveAudioSources() {
        var sources = state.activeAudioSources.slice(0);
        var index;

        state.activeAudioSources = [];

        for (index = 0; index < sources.length; index += 1) {
            try {
                sources[index].stop(0);
            } catch (error) {
                continue;
            }
        }
    }

    function playSingleTone(audioContext, tone, soundSettings) {
        var oscillator = audioContext.createOscillator();
        var gain = audioContext.createGain();
        var startAt = audioContext.currentTime + tone.offset;
        var duration = tone.duration || soundSettings.duration || 0.2;
        var peak = tone.gain || soundSettings.peak || 0.16;

        oscillator.type = tone.type || soundSettings.type || "square";
        oscillator.frequency.value = tone.frequency;
        gain.gain.setValueAtTime(0.0001, startAt);
        gain.gain.exponentialRampToValueAtTime(peak, startAt + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, startAt + Math.max(0.08, duration - 0.02));

        oscillator.connect(gain);
        gain.connect(audioContext.destination);
        oscillator.start(startAt);
        oscillator.stop(startAt + duration);
    }

    function showAlertDialog(alertData) {
        state.currentAlertUrl = alertData.teamsUrl || "";
        elements.alertDialogTag.innerHTML = escapeHtml(alertData.tag);
        elements.alertDialogTitle.innerHTML = escapeHtml(alertData.title);
        elements.alertDialogMessage.innerHTML = escapeHtml(alertData.message);
        elements.alertDialogOpen.disabled = !state.currentAlertUrl;

        if (elements.alertDialog && typeof elements.alertDialog.showModal === "function" && !elements.alertDialog.open) {
            try {
                elements.alertDialog.showModal();
            } catch (error) {
                return;
            }
        }
    }

    function dismissActiveAlarm() {
        if (elements.alertDialog && elements.alertDialog.open && elements.alertDialog.close) {
            elements.alertDialog.close();
        }

        stopAlarmSequence();
    }

    function openCurrentAlertLink() {
        if (!isHttpUrl(state.currentAlertUrl)) {
            showToast("openTeamsUnavailable");
            return false;
        }

        window.open(state.currentAlertUrl, "_blank");
        dismissActiveAlarm();
        return false;
    }

    function formatDateTime(value, includeSeconds) {
        var date = value instanceof Date ? value : new Date(value);

        if (window.Intl && Intl.DateTimeFormat) {
            try {
                return new Intl.DateTimeFormat(getLocale(), {
                    year: "numeric",
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                    second: includeSeconds ? "2-digit" : undefined
                }).format(date);
            } catch (error) {
                return fallbackFormatDate(date, includeSeconds);
            }
        }

        return fallbackFormatDate(date, includeSeconds);
    }

    function composeMeetingDateTime(dateValue, timeValue) {
        if (!dateValue || !timeValue) {
            return "";
        }

        return dateValue + "T" + normalizeTimeValue(timeValue);
    }

    function buildDateValue(date) {
        return date.getFullYear() + "-" + padNumber(date.getMonth() + 1) + "-" + padNumber(date.getDate());
    }

    function buildTimeValue(date) {
        return padNumber(date.getHours()) + ":" + padNumber(date.getMinutes());
    }

    function buildDateTimeValue(date) {
        return buildDateValue(date) + "T" + buildTimeValue(date);
    }

    function extractDateValue(dateTimeValue) {
        return String(dateTimeValue || "").split("T")[0] || "";
    }

    function extractTimeValue(dateTimeValue) {
        var timePart = String(dateTimeValue || "").split("T")[1] || "";
        return normalizeTimeValue(timePart);
    }

    function normalizeTimeValue(value) {
        var pieces = String(value || "").split(":");
        if (pieces.length < 2) {
            return String(value || "");
        }

        return padNumber(parseInt(pieces[0], 10)) + ":" + padNumber(parseInt(pieces[1], 10));
    }

    function isValidDateValue(value) {
        return /^\d{4}-\d{2}-\d{2}$/.test(String(value || ""));
    }

    function isValidTimeValue(value) {
        return /^\d{2}:\d{2}$/.test(normalizeTimeValue(value));
    }

    function fallbackFormatDate(date, includeSeconds) {
        var year = date.getFullYear();
        var month = padNumber(date.getMonth() + 1);
        var day = padNumber(date.getDate());
        var hour = padNumber(date.getHours());
        var minute = padNumber(date.getMinutes());
        var second = padNumber(date.getSeconds());

        return day + "/" + month + "/" + year + " " + hour + ":" + minute + (includeSeconds ? ":" + second : "");
    }

    function formatRelativeTime(milliseconds) {
        var totalMinutes;
        var days;
        var hours;
        var minutes;
        var chunks = [];

        if (milliseconds <= 0) {
            return t("startsNow");
        }

        totalMinutes = Math.floor(milliseconds / 60000);
        days = Math.floor(totalMinutes / (60 * 24));
        hours = Math.floor((totalMinutes % (60 * 24)) / 60);
        minutes = totalMinutes % 60;

        if (days > 0) {
            chunks.push(days + " d");
        }

        if (hours > 0) {
            chunks.push(hours + " h");
        }

        if (minutes > 0 || chunks.length === 0) {
            chunks.push(minutes + " min");
        }

        return chunks.slice(0, 2).join(" ");
    }

    function getRecurrenceSummary(meeting) {
        var summary = getRecurrenceLabel(meeting.recurrenceType || "none");

        if ((meeting.seriesSize || 1) > 1) {
            summary += " · " + formatText("repeatOccurrenceLabel", {
                index: meeting.occurrenceIndex || 1,
                total: meeting.seriesSize || 1
            });
        }

        return summary;
    }

    function getRecurrenceLabel(recurrenceType) {
        if (recurrenceType === "daily") {
            return t("recurrenceDaily");
        }

        if (recurrenceType === "weekdays") {
            return t("recurrenceWeekdays");
        }

        if (recurrenceType === "weekly") {
            return t("recurrenceWeekly");
        }

        if (recurrenceType === "biweekly") {
            return t("recurrenceBiweekly");
        }

        if (recurrenceType === "monthly") {
            return t("recurrenceMonthly");
        }

        return t("recurrenceNone");
    }

    function isWeekendDate(date) {
        var day = date.getDay();
        return day === 0 || day === 6;
    }

    function normalizeSoundProfileValue(soundProfile) {
        var normalized = String(soundProfile || "soft").toLowerCase();

        if (normalized === "urgent" || normalized === "alarm" || normalized === "siren" || normalized === "fire") {
            return normalized;
        }

        return "soft";
    }

    function getSoundProfileLabel(soundProfile) {
        var normalized = normalizeSoundProfileValue(soundProfile);

        if (normalized === "urgent") {
            return t("soundUrgent");
        }

        if (normalized === "alarm") {
            return t("soundAlarm");
        }

        if (normalized === "siren") {
            return t("soundSiren");
        }

        if (normalized === "fire") {
            return t("soundFireSiren");
        }

        return t("soundSoft");
    }

    function getSoundSettings(soundProfile, mode) {
        var normalized = normalizeSoundProfileValue(soundProfile);
        var isStartMode = mode === "start";

        if (normalized === "urgent") {
            return {
                type: "square",
                peak: isStartMode ? 0.28 : 0.24,
                duration: 0.2,
                repeatDelay: isStartMode ? 2600 : 3600,
                vibration: [300, 90, 300, 90, 300],
                repeatVibration: [260, 80, 260, 80, 260],
                pattern: isStartMode
                    ? [
                          { offset: 0, frequency: 1080, gain: 0.28 },
                          { offset: 0.14, frequency: 880, gain: 0.24 },
                          { offset: 0.28, frequency: 1080, gain: 0.28 },
                          { offset: 0.42, frequency: 880, gain: 0.24 },
                          { offset: 0.56, frequency: 1160, gain: 0.3 }
                      ]
                    : [
                          { offset: 0, frequency: 900, gain: 0.24 },
                          { offset: 0.16, frequency: 1040, gain: 0.26 },
                          { offset: 0.32, frequency: 900, gain: 0.24 },
                          { offset: 0.48, frequency: 1040, gain: 0.26 }
                      ]
            };
        }

        if (normalized === "alarm") {
            return {
                type: "sawtooth",
                peak: isStartMode ? 0.32 : 0.28,
                duration: 0.24,
                repeatDelay: isStartMode ? 2200 : 3000,
                vibration: [360, 90, 360, 90, 460],
                repeatVibration: [320, 70, 320, 70, 320],
                pattern: isStartMode
                    ? [
                          { offset: 0, frequency: 1160, duration: 0.18, gain: 0.3 },
                          { offset: 0.14, frequency: 920, duration: 0.18, gain: 0.26 },
                          { offset: 0.28, frequency: 1160, duration: 0.18, gain: 0.3 },
                          { offset: 0.42, frequency: 920, duration: 0.18, gain: 0.26 },
                          { offset: 0.56, frequency: 1320, duration: 0.24, gain: 0.34 }
                      ]
                    : [
                          { offset: 0, frequency: 940, duration: 0.2, gain: 0.26 },
                          { offset: 0.18, frequency: 1120, duration: 0.2, gain: 0.3 },
                          { offset: 0.36, frequency: 940, duration: 0.2, gain: 0.26 },
                          { offset: 0.54, frequency: 1120, duration: 0.24, gain: 0.3 }
                      ]
            };
        }

        if (normalized === "siren") {
            return {
                assetKey: "siren",
                type: "square",
                peak: isStartMode ? 0.34 : 0.3,
                duration: 0.3,
                repeatDelay: isStartMode ? 1800 : 2400,
                vibration: [420, 70, 420, 70, 420],
                repeatVibration: [360, 60, 360, 60, 360],
                pattern: isStartMode
                    ? [
                          { offset: 0, frequency: 760, duration: 0.2, gain: 0.28 },
                          { offset: 0.18, frequency: 1320, duration: 0.2, gain: 0.34 },
                          { offset: 0.36, frequency: 760, duration: 0.2, gain: 0.28 },
                          { offset: 0.54, frequency: 1320, duration: 0.2, gain: 0.34 },
                          { offset: 0.72, frequency: 860, duration: 0.24, gain: 0.3 },
                          { offset: 0.90, frequency: 1380, duration: 0.28, gain: 0.34 }
                      ]
                    : [
                          { offset: 0, frequency: 720, duration: 0.2, gain: 0.24 },
                          { offset: 0.18, frequency: 1220, duration: 0.2, gain: 0.3 },
                          { offset: 0.36, frequency: 720, duration: 0.2, gain: 0.24 },
                          { offset: 0.54, frequency: 1220, duration: 0.24, gain: 0.3 },
                          { offset: 0.72, frequency: 820, duration: 0.26, gain: 0.26 }
                      ]
            };
        }

        if (normalized === "fire") {
            return {
                assetKey: "fire",
                type: "sawtooth",
                peak: isStartMode ? 0.36 : 0.32,
                duration: 0.26,
                repeatDelay: isStartMode ? 1500 : 2100,
                vibration: [480, 60, 480, 60, 480, 60, 480],
                repeatVibration: [400, 50, 400, 50, 400],
                pattern: isStartMode
                    ? [
                          { offset: 0, frequency: 640, duration: 0.18, gain: 0.26 },
                          { offset: 0.14, frequency: 980, duration: 0.18, gain: 0.34 },
                          { offset: 0.28, frequency: 640, duration: 0.18, gain: 0.26 },
                          { offset: 0.42, frequency: 980, duration: 0.18, gain: 0.34 },
                          { offset: 0.56, frequency: 640, duration: 0.18, gain: 0.28 },
                          { offset: 0.70, frequency: 1080, duration: 0.22, gain: 0.36 },
                          { offset: 0.88, frequency: 640, duration: 0.18, gain: 0.28 },
                          { offset: 1.02, frequency: 1080, duration: 0.24, gain: 0.36 }
                      ]
                    : [
                          { offset: 0, frequency: 620, duration: 0.18, gain: 0.24 },
                          { offset: 0.14, frequency: 920, duration: 0.18, gain: 0.3 },
                          { offset: 0.28, frequency: 620, duration: 0.18, gain: 0.24 },
                          { offset: 0.42, frequency: 920, duration: 0.18, gain: 0.3 },
                          { offset: 0.56, frequency: 620, duration: 0.18, gain: 0.26 },
                          { offset: 0.70, frequency: 980, duration: 0.22, gain: 0.32 }
                      ]
            };
        }

        return {
            type: "square",
            peak: isStartMode ? 0.24 : 0.18,
            duration: 0.22,
            repeatDelay: isStartMode ? 3600 : 5400,
            vibration: [260, 110, 260, 110, 360],
            repeatVibration: [200, 90, 200],
            pattern: isStartMode
                ? [
                      { offset: 0, frequency: 980, gain: 0.22 },
                      { offset: 0.18, frequency: 820, gain: 0.18 },
                      { offset: 0.38, frequency: 980, gain: 0.22 },
                      { offset: 0.58, frequency: 820, gain: 0.18 }
                  ]
                : [
                      { offset: 0, frequency: 820, gain: 0.18 },
                      { offset: 0.22, frequency: 960, gain: 0.2 },
                      { offset: 0.46, frequency: 820, gain: 0.18 }
                  ]
        };
    }

    function isSameDay(leftDate, rightDate) {
        return (
            leftDate.getFullYear() === rightDate.getFullYear() &&
            leftDate.getMonth() === rightDate.getMonth() &&
            leftDate.getDate() === rightDate.getDate()
        );
    }

    function getLocale() {
        return state.language === "es" ? "es-GT" : "en-US";
    }

    function setFormBusy(isBusy) {
        elements.saveButton.disabled = isBusy;
        elements.clearButton.disabled = isBusy;
        if (elements.setNowButton) {
            elements.setNowButton.disabled = isBusy;
        }
    }

    function setFormFeedback(messageKeyOrText, tone, isPlainText) {
        var message = isPlainText ? messageKeyOrText : t(messageKeyOrText);

        if (!elements.formFeedback) {
            return;
        }

        elements.formFeedback.className = "form-feedback form-feedback--" + (tone || "info");
        elements.formFeedback.innerHTML = escapeHtml(message);
    }

    function clearFormFeedback() {
        if (!elements.formFeedback) {
            return;
        }

        elements.formFeedback.className = "form-feedback";
        elements.formFeedback.innerHTML = "";
    }

    function t(key) {
        var languagePack = translations[state.language] || translations[DEFAULT_LANGUAGE];
        return languagePack && languagePack[key] ? languagePack[key] : key;
    }

    function formatText(key, replacements) {
        var text = t(key);
        var replacementKey;

        for (replacementKey in replacements) {
            if (replacements.hasOwnProperty(replacementKey)) {
                text = text.replace(new RegExp("\\{" + replacementKey + "\\}", "g"), replacements[replacementKey]);
            }
        }

        return text;
    }

    function stringToColor(text) {
        var hash = 0;
        var index;
        var hue;

        for (index = 0; index < text.length; index += 1) {
            hash = text.charCodeAt(index) + ((hash << 5) - hash);
        }

        hue = Math.abs(hash) % 360;
        return "hsla(" + hue + ", 70%, 74%, 0.94)";
    }

    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, function (character) {
            return ESCAPE_LOOKUP[character];
        });
    }

    function escapeAttribute(value) {
        return String(value).replace(/[&<>"'`]/g, function (character) {
            return ESCAPE_LOOKUP[character];
        });
    }

    function createId() {
        if (window.crypto && typeof window.crypto.randomUUID === "function") {
            return window.crypto.randomUUID();
        }

        return "meeting-" + new Date().getTime() + "-" + Math.floor(Math.random() * 1000000);
    }

    function findMeetingById(meetingId) {
        var index;

        for (index = 0; index < state.meetings.length; index += 1) {
            if (state.meetings[index].id === meetingId) {
                return state.meetings[index];
            }
        }

        return null;
    }

    function closestWithAction(element) {
        while (element && element !== document.body) {
            if (element.getAttribute && element.getAttribute("data-action")) {
                return element;
            }
            element = element.parentNode;
        }

        return null;
    }

    function arrayContains(list, value) {
        var index;

        for (index = 0; index < list.length; index += 1) {
            if (list[index] === value) {
                return true;
            }
        }

        return false;
    }

    function addClass(element, className) {
        if (!element) {
            return;
        }

        if (element.classList) {
            element.classList.add(className);
            return;
        }

        if ((" " + element.className + " ").indexOf(" " + className + " ") === -1) {
            element.className += (element.className ? " " : "") + className;
        }
    }

    function removeClass(element, className) {
        var expression;

        if (!element) {
            return;
        }

        if (element.classList) {
            element.classList.remove(className);
            return;
        }

        expression = new RegExp("(^|\\s)" + className + "(\\s|$)", "g");
        element.className = trimValue(element.className.replace(expression, " "));
    }

    function trimValue(value) {
        return String(value).replace(/^\s+|\s+$/g, "");
    }

    function padNumber(value) {
        return value < 10 ? "0" + value : String(value);
    }

    function isArray(value) {
        return Object.prototype.toString.call(value) === "[object Array]";
    }

    function requestJson(method, url, data, callback) {
        var xhr;
        var body = null;

        try {
            xhr = new XMLHttpRequest();
        } catch (error) {
            callback(false, null);
            return;
        }

        xhr.open(method, url, true);
        xhr.setRequestHeader("Accept", "application/json");

        if (method === "POST") {
            xhr.setRequestHeader("Content-Type", "application/json");
            body = JSON.stringify(data);
        }

        xhr.onreadystatechange = function () {
            var payload;

            if (xhr.readyState !== 4) {
                return;
            }

            if (xhr.status < 200 || xhr.status >= 300) {
                callback(false, null);
                return;
            }

            try {
                payload = xhr.responseText ? JSON.parse(xhr.responseText) : null;
            } catch (error) {
                callback(false, null);
                return;
            }

            callback(true, payload);
        };

        xhr.onerror = function () {
            callback(false, null);
        };

        try {
            xhr.send(body);
        } catch (error) {
            callback(false, null);
        }
    }
}());
