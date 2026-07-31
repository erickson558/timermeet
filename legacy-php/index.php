<?php
// Version local de la app para mostrarla en la interfaz.
$appVersion = '1.3.0';
?>
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TimerMeet | Recordatorios de Teams</title>
    <meta
        name="description"
        content="Agenda reuniones de Microsoft Teams con varios timers, avisos visuales y notificaciones locales."
    >
    <link rel="stylesheet" href="assets/styles.css?v=<?= urlencode($appVersion) ?>">
</head>
<body>
    <div class="page-blur page-blur--left" aria-hidden="true"></div>
    <div class="page-blur page-blur--right" aria-hidden="true"></div>

    <main class="app-shell">
        <!-- Encabezado principal con resumen rápido de la app. -->
        <header class="hero panel">
            <div class="hero__copy">
                <p class="eyebrow">EasyPHP + Microsoft Teams</p>
                <h1 data-i18n="appTitle">TimerMeet</h1>
                <p class="hero__text" data-i18n="appSubtitle">
                    Organiza recordatorios locales para tus reuniones de Microsoft Teams.
                </p>

                <div class="hero__chips">
                    <span class="chip">
                        <span data-i18n="versionLabel">Versión local</span>
                        <strong><?= htmlspecialchars($appVersion, ENT_QUOTES, 'UTF-8') ?></strong>
                    </span>
                    <span class="chip">
                        <span data-i18n="storageLabel">Guardado</span>
                        <strong id="storageStatusValue">Servidor local + navegador</strong>
                    </span>
                </div>
            </div>

            <div class="hero__actions">
                <button id="notificationButton" class="button button--ghost" type="button" data-i18n="enableNotifications">
                    Activar notificaciones
                </button>
                <button id="languageButton" class="button button--ghost" type="button" aria-label="Cambiar idioma">
                    EN
                </button>
                <a
                    class="button button--ghost button--paypal"
                    href="https://www.paypal.com/donate/?hosted_button_id=ZABFRXC2P3JQN"
                    target="_blank"
                    rel="noreferrer"
                    data-i18n="buyBeer"
                >
                    Cómprame una cerveza
                </a>
            </div>
        </header>

        <section class="dashboard">
            <!-- Formulario para crear o editar timers. -->
            <section class="panel panel--form">
                <div class="section-heading">
                    <div>
                        <p class="section-heading__eyebrow" data-i18n="formEyebrow">Nuevo timer</p>
                        <h2 data-i18n="formTitle">Agregar o editar reunión</h2>
                    </div>
                    <p class="section-heading__hint" data-i18n="formHint">
                        Guarda tantas reuniones como necesites para tus 3 trabajos o más.
                    </p>
                </div>

                <form id="meetingForm" class="meeting-form" novalidate>
                    <input id="meetingId" name="meetingId" type="hidden">

                    <label for="workName" data-i18n="workLabel">Trabajo / Empresa</label>
                    <input
                        id="workName"
                        name="workName"
                        type="text"
                        maxlength="80"
                        placeholder="Ej. Trabajo 1, Cliente A, Freelance"
                        data-i18n-placeholder="workPlaceholder"
                    >

                    <label for="meetingTitle" data-i18n="titleLabel">Nombre de la reunión</label>
                    <input
                        id="meetingTitle"
                        name="meetingTitle"
                        type="text"
                        maxlength="120"
                        placeholder="Ej. Daily, soporte, revisión de sprint"
                        data-i18n-placeholder="titlePlaceholder"
                    >

                    <div class="form-grid">
                        <div>
                            <label for="meetingDate" data-i18n="dateOnlyLabel">Fecha</label>
                            <input id="meetingDate" name="meetingDate" type="date">
                        </div>

                        <div>
                            <label for="meetingTime" data-i18n="timeOnlyLabel">Hora</label>
                            <input id="meetingTime" name="meetingTime" type="time" step="60">
                        </div>
                    </div>

                    <div class="inline-actions">
                        <button id="setNowButton" class="button button--ghost button--small" type="button" data-i18n="setNowButton">
                            Usar fecha y hora actual
                        </button>
                        <span class="inline-actions__hint" data-i18n="dateHint">
                            Selecciona ambas para que el timer se pueda guardar.
                        </span>
                    </div>

                    <div class="form-grid">
                        <div>
                            <label for="reminderMinutes" data-i18n="reminderLabel">Avisar antes</label>
                            <div class="input-with-suffix">
                                <input id="reminderMinutes" name="reminderMinutes" type="number" min="1" max="720" value="15">
                                <span data-i18n="minutesSuffix">minutos</span>
                            </div>
                        </div>

                        <div>
                            <label for="soundProfile" data-i18n="soundLabel">Sonido de alerta</label>
                            <select id="soundProfile" name="soundProfile"></select>
                        </div>
                    </div>

                    <div class="inline-actions">
                        <button id="testSoundButton" class="button button--ghost button--small" type="button" data-i18n="testSoundButton">
                            Probar sonido
                        </button>
                        <span class="inline-actions__hint" data-i18n="soundHint">
                            Usa un perfil más invasivo para reuniones críticas.
                        </span>
                    </div>

                    <div class="form-grid">
                        <div>
                            <label for="recurrenceType" data-i18n="repeatLabel">Repetición</label>
                            <select id="recurrenceType" name="recurrenceType"></select>
                        </div>

                        <div>
                            <label for="occurrenceCount" data-i18n="occurrenceCountLabel">Cuántas crear</label>
                            <div class="input-with-suffix">
                                <input id="occurrenceCount" name="occurrenceCount" type="number" min="1" max="52" value="1">
                                <span data-i18n="occurrenceCountSuffix">eventos</span>
                            </div>
                        </div>
                    </div>

                    <p class="form-helper" id="recurrenceHelp" data-i18n="recurrenceHint">
                        Para "lunes cada 2 semanas", elige una fecha lunes, selecciona "Cada 2 semanas" y cuántos eventos crear.
                    </p>

                    <label for="teamsUrl" data-i18n="urlLabel">Enlace de Teams</label>
                    <input
                        id="teamsUrl"
                        name="teamsUrl"
                        type="url"
                        maxlength="300"
                        placeholder="https://teams.microsoft.com/..."
                    >

                    <label for="notes" data-i18n="notesLabel">Notas rápidas</label>
                    <textarea
                        id="notes"
                        name="notes"
                        rows="4"
                        maxlength="400"
                        placeholder="Datos importantes de la llamada, cliente, agenda, etc."
                        data-i18n-placeholder="notesPlaceholder"
                    ></textarea>

                    <div class="form-actions">
                        <button id="saveButton" class="button button--primary" type="submit" data-i18n="saveButton">
                            Guardar timer
                        </button>
                        <button id="clearButton" class="button button--ghost" type="button" data-i18n="clearButton">
                            Limpiar formulario
                        </button>
                    </div>

                    <p id="formFeedback" class="form-feedback" role="status" aria-live="polite"></p>
                </form>
            </section>

            <!-- Panel derecho con estadísticas y lista de reuniones. -->
            <section class="panel panel--summary">
                <div class="section-heading">
                    <div>
                        <p class="section-heading__eyebrow" data-i18n="statsEyebrow">Vista general</p>
                        <h2 data-i18n="statsTitle">Panel de reuniones</h2>
                    </div>
                    <p class="section-heading__hint" data-i18n="notificationHint">
                        La pestaña debe permanecer abierta para disparar recordatorios.
                    </p>
                </div>

                <div class="status-grid">
                    <article class="status-card">
                        <span data-i18n="currentTimeLabel">Hora actual</span>
                        <strong id="currentTimeValue">--:--</strong>
                    </article>
                    <article class="status-card">
                        <span data-i18n="nextAlertLabel">Siguiente aviso</span>
                        <strong id="nextAlertValue">Sin avisos próximos</strong>
                    </article>
                </div>

                <div class="stats-grid">
                    <article class="stat-box">
                        <span data-i18n="totalMeetings">Timers guardados</span>
                        <strong id="totalMeetingsValue">0</strong>
                    </article>
                    <article class="stat-box">
                        <span data-i18n="todayMeetings">Hoy</span>
                        <strong id="todayMeetingsValue">0</strong>
                    </article>
                    <article class="stat-box">
                        <span data-i18n="activeMeetings">Próxima reunión</span>
                        <strong id="nextMeetingValue">--</strong>
                    </article>
                </div>

                <div class="toolbar">
                    <div class="toolbar__field">
                        <label for="workFilter" data-i18n="filterLabel">Filtrar por trabajo</label>
                        <select id="workFilter" name="workFilter"></select>
                    </div>
                </div>

                <div class="meeting-list-header">
                    <h3 data-i18n="listTitle">Tus reuniones</h3>
                    <span id="meetingCount" class="meeting-count">0</span>
                </div>

                <section id="meetingList" class="meeting-list" aria-live="polite"></section>

                <section id="emptyState" class="empty-state">
                    <h3 data-i18n="emptyTitle">Aún no hay timers</h3>
                    <p data-i18n="emptyBody">
                        Agrega tu primera reunión y el sitio empezará a contar el tiempo restante.
                    </p>
                </section>
            </section>
        </section>
    </main>

    <!-- Diálogo modal para avisos fuertes dentro de la pestaña. -->
    <dialog id="alertDialog" class="alert-dialog">
        <div class="alert-dialog__content">
            <p id="alertDialogTag" class="alert-dialog__tag">Recordatorio</p>
            <h2 id="alertDialogTitle">Aviso activo</h2>
            <p id="alertDialogMessage"></p>
            <div class="alert-dialog__actions">
                <button id="alertDialogOpen" class="button button--primary" type="button" data-i18n="alertDialogOpen">
                    Abrir Teams
                </button>
                <button id="alertDialogClose" class="button button--ghost" type="button" data-i18n="alertDialogClose">
                    Cerrar
                </button>
            </div>
        </div>
    </dialog>

    <!-- Mensaje breve para validar acciones sin usar alertas del navegador. -->
    <div id="toast" class="toast" role="status" aria-live="polite"></div>

    <!-- Capa de alarma persistente para llamar la atención incluso si se cierra el diálogo. -->
    <section id="alarmOverlay" class="alarm-overlay" aria-live="assertive" hidden>
        <div class="alarm-overlay__card">
            <p id="alarmOverlayTag" class="alarm-overlay__tag">Alarma activa</p>
            <h2 id="alarmOverlayTitle">Recordatorio de reunión</h2>
            <p id="alarmOverlayBody" class="alarm-overlay__body"></p>
            <p id="alarmOverlayMeta" class="alarm-overlay__meta"></p>
            <div class="alarm-overlay__actions">
                <button id="alarmOpenButton" class="button button--primary" type="button" data-i18n="openTeams">
                    Abrir Teams
                </button>
                <button id="alarmDismissButton" class="button button--danger" type="button" data-i18n="dismissAlarm">
                    Silenciar alarma
                </button>
            </div>
        </div>
    </section>

    <script>
        window.APP_CONFIG = {
            version: '<?= htmlspecialchars($appVersion, ENT_QUOTES, 'UTF-8') ?>',
            apiEndpoint: 'api/meetings.php'
        };
    </script>
    <script src="assets/app.js?v=<?= urlencode($appVersion) ?>" defer></script>
</body>
</html>
