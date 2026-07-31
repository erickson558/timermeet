# TimerMeet SDD

## Product Goal

Recordar al usuario sus reuniones de Microsoft Teams con avisos visibles, sonoros y persistentes, sin depender de que un navegador permanezca abierto. La versión activa (`2.0.1`) es una app de escritorio en Python (Tkinter puro); la versión `1.3.0` en PHP/JS queda congelada en `legacy-php/` como referencia.

## Current Baseline

- Versión actual: `2.0.1` (Python, escritorio).
- Punto de entrada: [timermeet.py](./timermeet.py).
- Paquete de la app: [timermeet_app/](./timermeet_app/) (`models.py`, `recurrence.py`, `storage.py`, `audio.py`, `notifications.py`, `alarm_ui.py`, `main_window.py`, `app.py`, `i18n.py`, `security.py`).
- Persistencia: archivo compartido [data/meetings.json](./data/meetings.json) (mismo esquema que la versión PHP; se lee y escribe con fusión ante posibles ediciones desde otra PC vía OneDrive, ver `timermeet_app/storage.py`).
- Preferencias locales: `data/settings.json` (idioma).
- Pruebas: [tests/](./tests/) (`unittest`).
- Empaquetado: [build_exe.py](./build_exe.py) → `TimerMeet.exe` en la raíz del repo, junto a `timermeet.py` y `computer_pc_10894.ico`.
- Baseline histórico (congelado): [legacy-php/](./legacy-php/) — sitio EasyPHP + JS, versión `1.3.0`, ver `legacy-php/README.md`.

## Por qué se reescribió a Python (v2.0.0)

La versión web dependía de que una pestaña del navegador permaneciera abierta y enfocada para disparar avisos (permiso de `Notification`, temporizadores de la pestaña, ahorro de batería/throttling del navegador). Ese fue el motivo explícito para migrar ("no me alerta como debe"). Un proceso nativo de escritorio elimina esa dependencia por completo y, de paso, elimina toda la superficie de red de la versión anterior (ya no hay endpoint PHP ni servidor HTTP).

## Por qué v2.0.1 dejó de usar CustomTkinter

Al probar `v2.0.0` con datos reales (41 reuniones), la ventana tardaba entre 20 y 26 segundos en volverse interactiva y parecía "no abrir". La causa raíz, confirmada con mediciones (ver `tests/` y el historial de commits): CustomTkinter difiere el renderizado de bordes redondeados de cada widget (imagen PIL por widget) hasta que Tk procesa su cola de tareas en espera; con las ~40-50 widgets de la interfaz más las tarjetas de reuniones, ese primer vaciado de cola tomaba decenas de segundos. Se reescribió toda la interfaz (`timermeet_app/main_window.py`, `alarm_ui.py`) con widgets `tkinter`/`ttk` planos, que no tienen ese costo. Además:
- Las tarjetas de reuniones dejaron de reconstruirse por completo en cada latido de 1 segundo (solo se re-renderizan si su contenido visible cambió).
- La inicialización de `pygame.mixer` se volvió perezosa y se ejecuta en un hilo de fondo, no de forma síncrona al arrancar.
- El recálculo del área de scroll de la lista de reuniones se agrupa (debounce) en vez de recalcularse en cada widget insertado.
- Se corrigió un bug real de arranque bajo `--windowed` de PyInstaller: `sys.stdout`/`sys.stderr` son `None` sin consola adjunta, lo que hacía fallar en silencio la primera impresión de `pygame` y dejaba la ventana creada pero nunca mostrada.

## Technical Constraints

- Windows 10/11, Python 3.9+ (probado con 3.12).
- Interfaz gráfica: `tkinter`/`ttk` puro (sin CustomTkinter, ver arriba).
- Dependencias runtime: `pygame` (audio), `plyer` (notificaciones nativas, mejor esfuerzo). Ver `requirements.txt`.
- Sin base de datos; persistencia en un único archivo JSON compartido.
- Esta carpeta del proyecto vive dentro de OneDrive y puede ejecutarse desde más de una PC: la capa de persistencia debe seguir soportando fusión (merge-on-save) en vez de sobrescritura simple — ver el docstring de `timermeet_app/storage.py`.
- Español como idioma inicial (`i18n.DEFAULT_LANGUAGE = "es"`), inglés soportado por completo; ambos diccionarios deben tener exactamente las mismas claves (verificado en `tests/test_i18n.py`).
- El hilo principal de Tkinter no debe bloquearse: trabajo largo (síntesis de audio, reintentos de E/S) va en hilo de fondo o vía `root.after()`.
- El repositorio Git raíz ya es la raíz del proyecto (a diferencia del monorepo EasyPHP histórico que menciona `legacy-php/`); no hay ambigüedad de alcance al publicar.

## Functional Requirements

1. Crear, editar y eliminar timers de reuniones (mismos campos que la versión PHP: trabajo, título, fecha/hora, minutos de aviso, sonido, enlace de Teams y notas).
2. Mostrar la próxima reunión, el próximo aviso y el total de timers; filtrar por trabajo.
3. Disparar un recordatorio antes del inicio y otro al momento de inicio, cada uno como máximo una vez, con ventanas de "aviso perdido" que marcan el flag sin notificar si el momento ya pasó (evita alarmas fuera de tiempo tras una ausencia larga).
4. Alarma sonora (5 perfiles) + overlay visual persistente (siempre-encima, parpadeante, se re-eleva si queda tapada) + notificación nativa best-effort, disparados juntos y de forma redundante.
5. Perfiles `Sirena invasiva` y `Sirena de bomberos` usan MP3 locales (`assets/audio/`) vía `pygame.mixer`; si el archivo falla o no carga, cae automáticamente a un tono sintético (`winsound.Beep`) — nunca debe quedar en silencio.
6. Series repetitivas: diaria, semana laboral (L-V), semanal, quincenal, mensual. "Semana laboral" exige fecha inicial de lunes a viernes.
7. Motor de renovación semanal: cada serie activa se extiende automáticamente para cubrir ~1 semana adelante, evaluado en cada heartbeat pero con efecto real solo a partir del viernes 18:00 hora local (o al abrir la app después de esa hora). Es idempotente (una segunda pasada no duplica) y nunca crea ocurrencias con fecha pasada.
8. El enlace de Teams solo se abre/guarda si usa esquema `http://` o `https://` (`security.is_http_url`); mismo criterio para el botón de donación.
9. Botón de donación "Cómprame una cerveza" enlazando a PayPal (`https://www.paypal.com/donate/?hosted_button_id=ZABFRXC2P3JQN`).
10. Interfaz completa en español e inglés, con selector de idioma que recuerda la preferencia entre sesiones (`data/settings.json`).
11. Persistencia resiliente ante múltiples PCs sincronizadas por OneDrive: al guardar, se relee el disco y se fusiona con la memoria (gana el registro con `updatedAt` más reciente; `reminderSent`/`startSent` siempre se combinan con OR para no repetir una alarma ya silenciada en otra sesión); se refresca desde disco periódicamente y al recuperar el foco de la ventana.

## Non-Functional Requirements

- Código legible; comentarios solo donde el "por qué" no sea obvio (recurrencia, idempotencia de renovación, fusión de datos, fallback de audio).
- Sin dependencias de red ni servidor: toda la lógica corre en un solo proceso local.
- No guardar secretos, tokens ni credenciales en el proyecto.
- Un fallo inesperado (audio, archivo corrupto, notificación nativa) se registra en `data/timermeet.log` y se maneja con degradación controlada — la app no debe cerrarse en silencio ni dejar de alertar por un error periférico.
- Compatibilidad de datos: cualquier `data/meetings.json` generado por la versión PHP (`1.3.0`) debe seguir cargando sin errores.

## Acceptance Criteria

- Al guardar un timer, aparece en la lista y sobrevive a un reinicio de la app.
- Cuando falta poco para una reunión, la app reproduce sonido y muestra el overlay visual persistente hasta que se silencie.
- Cuando empieza la reunión, la alarma vuelve a dispararse (independiente del aviso previo).
- El idioma cambia entre ES y EN sin romper la interfaz ni perder la preferencia al reiniciar.
- El filtro por trabajo funciona sobre los timers guardados; las estadísticas siempre reflejan todos los timers, no solo los filtrados.
- Crear una serie de "Semana laboral" genera solo eventos de lunes a viernes y rechaza una fecha inicial en sábado o domingo.
- Los perfiles `Sirena invasiva`/`Sirena de bomberos` reproducen el MP3 en bucle; si falla la carga, el tono sintético suena igual.
- Ejecutar el motor de renovación semanal dos veces seguidas con los mismos datos no crea duplicados.
- Dos instancias en PCs distintas sincronizadas por OneDrive convergen: una reunión creada en una aparece en la otra tras la resincronización periódica o al recuperar el foco, sin que ninguna borre los cambios de la otra.
- Un enlace de Teams que no empiece con `http://`/`https://` se rechaza al guardar y no se abre desde ningún lado de la interfaz.
- `TimerMeet.exe` arranca desde la raíz del repo usando `computer_pc_10894.ico` como ícono, con `assets/audio/` y `data/` presentes junto al ejecutable.

## SDD Workflow

1. Traducir la petición del usuario a objetivo, restricciones y criterio de aceptación (skill `timermeet-spec-driver`).
2. Actualizar este `SDD.md` antes de cambios grandes o ambiguos.
3. Identificar módulos impactados (ver `.claude/skills/timermeet-python-builder/references/module-map.md`) y el mínimo cambio necesario.
4. Implementar (skill `timermeet-python-builder`; comentar con `timermeet-code-commenter`).
5. Verificar sintaxis, pruebas y comportamiento (`.claude/skills/timermeet-python-builder/references/validation.md`).
6. Ejecutar revisión de seguridad antes de publicar (skill `timermeet-security-guardian`).
7. Actualizar `SDD.md`, `README.md` y versionado si cambió el comportamiento visible.
8. Publicar con la skill `timermeet-github-publisher`.

## Verification Checklist

- `python -m py_compile timermeet.py timermeet_app/*.py`
- `python -m unittest discover -s tests -v`
- `python -m bandit -r timermeet_app timermeet.py build_exe.py -f txt`
- `python -m pip_audit -r requirements.txt`
- Arranque manual (`python timermeet.py`) sin excepciones en `data/timermeet.log`.
- Si se reconstruyó el `.exe`: arranque manual de `TimerMeet.exe` sin fallo inmediato.
- Confirmar que la versión coincide en `timermeet_app/__init__.py`, `README.md`, `SDD.md`, el commit y el tag.

## Near-Term Backlog

- Exportación e importación de timers.
- Patrones personalizados por días específicos.
- Empaquetado como instalador (hoy es un `.exe` de un solo archivo, sin instalador ni accesos directos automáticos).
- Permitir "pausar" o cancelar explícitamente una serie recurrente completa sin borrar todas sus ocurrencias.
- Limitación conocida: una serie `diaria` abandonada por más de ~60 días no se autocorrige en una sola pasada del motor de renovación (tope de seguridad heredado de la versión original; ver `tests/test_recurrence.py::test_safety_cap_is_a_known_limit_for_a_daily_series_stale_beyond_it`).
