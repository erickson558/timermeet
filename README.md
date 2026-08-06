# TimerMeet

Recordatorios de escritorio para tus reuniones de Microsoft Teams, con alarmas sonoras y visuales que **no dependen de tener un navegador abierto**.

TimerMeet nació como un sitio local en PHP y se reescribió por completo en Python (`v2.0.0`) porque los avisos basados en navegador dejaban de sonar si la pestaña se cerraba, perdía el foco, o el navegador limitaba los temporizadores en segundo plano. La versión de escritorio corre como un proceso normal de Windows: mientras esté abierta, sus alarmas se disparan sin importar qué más esté pasando en el navegador.

## Qué hace

- Guarda timers de reuniones por trabajo o empresa, con título, fecha/hora, minutos de aviso, sonido de alerta, enlace de Teams y notas. El campo de trabajo/empresa es un combobox con las empresas ya guardadas -- se administran (agregar o eliminar) desde "Gestionar empresas", junto a ese campo.
- Dispara un aviso previo (X minutos antes) y otro al momento exacto de inicio, cada uno de forma redundante: sonido en bucle + overlay visual que parpadea y se mantiene siempre encima hasta silenciarlo + notificación nativa de Windows.
- 5 perfiles de sonido (Suave, Urgente, Alarma fuerte, Sirena invasiva, Sirena de bomberos); los dos últimos usan archivos MP3 reales y caen automáticamente a un tono sintético si el audio no carga -- nunca se queda en silencio.
- Series repetitivas: diaria, semana laboral (lunes a viernes), semanal, quincenal o mensual, con un motor que las renueva solas cada semana para que nunca dejen de sonar por quedarse sin ocurrencias futuras.
- Guarda todo en `data/meetings.json`. Si usas la app desde más de una computadora sincronizada por OneDrive, fusiona los cambios de ambas en vez de que una sobrescriba a la otra.
- Limpieza automática: una reunión pasada cuyos dos avisos ya sonaron se elimina sola después de 7 días, para que el archivo y la lista no crezcan para siempre. Si algún aviso quedó pendiente, nunca se borra sola aunque sea vieja.
- Botón "Eliminar eventos pasados" para borrar de inmediato todos los eventos ya vencidos de todos los trabajos, sin esperar los 7 días de la limpieza automática.
- Botón "Salir" para cerrar la app de forma ordenada.
- Interfaz completa en español e inglés, con botón para cambiar de idioma.
- Botón de donación ("Cómprame una cerveza") hacia PayPal.
- `TimerMeet.exe` abre en menos de 5 segundos (medido; ver `SDD.md` v2.4.0 para el detalle de qué se optimizó).
- Modo gadget/mini: un botón en el encabezado convierte la ventana en un panel flotante, sin bordes, siempre-encima y arrastrable (estilo "skin mode" de Windows Media Player) con el reloj y el siguiente aviso; un botón regresa a la vista completa. El modo y la posición se recuerdan entre reinicios.
- Modo bandeja del sistema: otro botón en el encabezado oculta la ventana por completo y la reduce a un ícono en la bandeja; un clic o "Mostrar TimerMeet" desde su menú la restaura, "Salir" desde el mismo menú cierra la app.
- La lista de reuniones se actualiza en su lugar (sin destruir y reconstruir las tarjetas en cada segundo), así que la ventana no se siente lenta ni "reordena" nada al maximizar, mover o simplemente dejarla abierta.
- Vista de calendario mensual: un botón en el encabezado ("Vista calendario") cambia la lista actual por una cuadrícula mensual estilo Outlook/Teams (6 semanas fijas, lunes a domingo, con "‹"/"›" para navegar entre meses y un botón "Hoy"). Cada día muestra hasta 3 reuniones (hora + título, con el mismo color por trabajo que la lista) y un contador "+N más" para el resto; clic en una reunión abre el mismo formulario de edición que usa la lista. "Vista de lista" regresa a la vista normal. Ignora el filtro de trabajo/empresa (siempre muestra todas las reuniones) y no agrega ningún campo nuevo a los timers guardados.

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
| `winmm.dll` (vía `ctypes`, stdlib) / `winsound` | Reproducción de los sonidos de alarma en MP3 (API MCI de Windows) y el tono sintético de respaldo; no se agrega como dependencia. |
| [`plyer`](https://github.com/kivy/plyer) | Notificaciones nativas de Windows (mejor esfuerzo; nunca es el único canal de alerta). |
| [`pystray`](https://github.com/moses-palmer/pystray) + [`Pillow`](https://python-pillow.org/) | Ícono de la bandeja del sistema (modo bandeja). `build_exe.py` excluye los plugins de imagen de Pillow que la app no usa, para no afectar el tiempo de arranque. |
| [`pyinstaller`](https://pyinstaller.org/) *(solo para compilar)* | Empaqueta la app como un `.exe` de un solo archivo. |

> La interfaz se construyó con `tkinter`/`ttk` puro en vez de CustomTkinter: en pruebas con datos reales, CustomTkinter tardaba 20+ segundos en volverse interactiva por el renderizado diferido de sus bordes redondeados, lo que hacía parecer que la app no abría. Ver `SDD.md` para el detalle de esa corrección (`v2.0.1`).

Ver `requirements.txt` (runtime) y `requirements-dev.txt` (incluye lo anterior más lo necesario para compilar/probar: `pyinstaller`, `bandit`, `pip-audit`).

## Archivos principales

- `timermeet.py`: punto de entrada de la aplicación.
- `timermeet_app/`: paquete de la app -- modelo de datos (`models.py`), recurrencia y renovación (`recurrence.py`), limpieza de reuniones vencidas (`retention.py`), persistencia (`storage.py`), audio (`audio.py`), notificaciones (`notifications.py`), alarmas (`alarm_ui.py`), interfaz (`main_window.py`), ícono de bandeja (`tray_icon.py`), control (`app.py`), idiomas (`i18n.py`), seguridad (`security.py`).
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
