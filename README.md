# TimerMeet

Recordatorios de escritorio para tus reuniones de Microsoft Teams, con alarmas sonoras y visuales que **no dependen de tener un navegador abierto**.

TimerMeet nació como un sitio local en PHP y se reescribió por completo en Python (`v2.0.0`) porque los avisos basados en navegador dejaban de sonar si la pestaña se cerraba, perdía el foco, o el navegador limitaba los temporizadores en segundo plano. La versión de escritorio corre como un proceso normal de Windows: mientras esté abierta, sus alarmas se disparan sin importar qué más esté pasando en el navegador.

## Qué hace

- Guarda timers de reuniones por trabajo o empresa, con título, fecha/hora, minutos de aviso, sonido de alerta, enlace de Teams y notas.
- Dispara un aviso previo (X minutos antes) y otro al momento exacto de inicio, cada uno de forma redundante: sonido en bucle + overlay visual que parpadea y se mantiene siempre encima hasta silenciarlo + notificación nativa de Windows.
- 5 perfiles de sonido (Suave, Urgente, Alarma fuerte, Sirena invasiva, Sirena de bomberos); los dos últimos usan archivos MP3 reales y caen automáticamente a un tono sintético si el audio no carga -- nunca se queda en silencio.
- Series repetitivas: diaria, semana laboral (lunes a viernes), semanal, quincenal o mensual, con un motor que las renueva solas cada semana para que nunca dejen de sonar por quedarse sin ocurrencias futuras.
- Guarda todo en `data/meetings.json`. Si usas la app desde más de una computadora sincronizada por OneDrive, fusiona los cambios de ambas en vez de que una sobrescriba a la otra.
- Interfaz completa en español e inglés, con botón para cambiar de idioma.
- Botón de donación ("Cómprame una cerveza") hacia PayPal.

## Instalación y uso

### Opción 1: ejecutable ya compilado

Descarga o clona este repositorio; `TimerMeet.exe` ya está en la raíz junto con las carpetas `assets/` y `data/` que necesita. Ejecuta `TimerMeet.exe` directamente -- no requiere instalar Python.

### Opción 2: desde el código fuente

Requiere Python 3.9 o superior.

```powershell
pip install -r requirements.txt
python timermeet.py
```

### Compilar tu propio .exe

```powershell
pip install -r requirements-dev.txt
python build_exe.py
```

Esto genera `TimerMeet.exe` en la raíz del proyecto, junto a `timermeet.py`, usando el ícono `computer_pc_10894.ico`. Ver `.claude/skills/timermeet-exe-packager/SKILL.md` para el detalle de cada flag de PyInstaller.

## Dependencias

| Paquete | Para qué |
|---|---|
| `tkinter` / `ttk` | Interfaz gráfica (incluida en la instalación estándar de Python; no se agrega como dependencia). |
| [`pygame`](https://www.pygame.org/) | Reproducción de los sonidos de alarma en MP3. |
| [`plyer`](https://github.com/kivy/plyer) | Notificaciones nativas de Windows (mejor esfuerzo; nunca es el único canal de alerta). |
| [`pyinstaller`](https://pyinstaller.org/) *(solo para compilar)* | Empaqueta la app como un `.exe` de un solo archivo. |

> La interfaz se construyó con `tkinter`/`ttk` puro en vez de CustomTkinter: en pruebas con datos reales, CustomTkinter tardaba 20+ segundos en volverse interactiva por el renderizado diferido de sus bordes redondeados, lo que hacía parecer que la app no abría. Ver `SDD.md` para el detalle de esa corrección (`v2.0.1`).

Ver `requirements.txt` (runtime) y `requirements-dev.txt` (incluye lo anterior más lo necesario para compilar/probar: `pyinstaller`, `bandit`, `pip-audit`).

## Archivos principales

- `timermeet.py`: punto de entrada de la aplicación.
- `timermeet_app/`: paquete de la app -- modelo de datos (`models.py`), recurrencia y renovación (`recurrence.py`), persistencia (`storage.py`), audio (`audio.py`), notificaciones (`notifications.py`), alarmas (`alarm_ui.py`), interfaz (`main_window.py`), control (`app.py`), idiomas (`i18n.py`), seguridad (`security.py`).
- `tests/`: pruebas automatizadas -- `python -m unittest discover -s tests`.
- `build_exe.py`: script para compilar `TimerMeet.exe`.
- `data/meetings.json`: timers guardados (no se sube al repositorio, ver `.gitignore`).
- `legacy-php/`: versión anterior en PHP/JS (`1.3.0`), conservada como referencia -- ver `legacy-php/README.md`.

## Gestión del proyecto

- `SDD.md`: especificación viva y criterios de aceptación.
- `AGENTS.md`: agentes de Claude Code (y, para el baseline histórico, de Codex) recomendados para este proyecto.
- `.claude/skills/`: skills versionadas para spec, implementación, comentarios de código, empaquetado del `.exe`, publicación en GitHub, revisión de seguridad, y el flujo de corrección de bugs con versionado.
- `SECURITY.md`: alcance de soporte y cómo reportar un problema.

## Privacidad y seguridad

- `data/meetings.json` guarda el contenido real de tus reuniones (títulos, notas, enlaces de Teams) y está excluido del repositorio mediante `.gitignore`; nunca lo subas a un repositorio público.
- La app solo abre enlaces (de Teams o el botón de donación) con esquema `http://` o `https://`; cualquier otro esquema se rechaza.
- No hay servidor ni puerto de red: toda la app corre como un proceso local de un solo usuario.
- Ver `SECURITY.md` para el proceso de reporte de vulnerabilidades y el checklist de hardening.

## Créditos de audio

- `Sirena invasiva`: `Siren Noise` de `KevanGC`, obtenido desde SoundBible bajo dominio público.
- `Sirena de bomberos`: `Fire Engine Siren Yelps And Wails` de `Alexander`, obtenido desde Orange Free Sounds bajo `CC BY 4.0`.
- Detalle y enlaces en `assets/audio/ATTRIBUTION.md`.

## Licencia

Este proyecto se publica bajo la licencia [Apache License 2.0](./LICENSE). Los archivos de audio en `assets/audio/` mantienen sus propias licencias originales (dominio público / `CC BY 4.0`); revisa `assets/audio/ATTRIBUTION.md` antes de reutilizarlos fuera de este proyecto.
