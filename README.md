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
- Skins y redimensionado del modo gadget (`v2.12.0`): 4 apariencias seleccionables (Clásico, Cristal, Claro, Neón) desde un botón de ícono en la franja superior del gadget o desde su menú contextual (clic derecho); "Cristal" usa transparencia real de ventana, no un efecto de vidrio esmerilado. Un grip en la esquina inferior-derecha permite redimensionar el gadget libremente entre ~220x100 y ~640x360, siempre dentro de los límites reales del escritorio. La skin y el tamaño elegidos se recuerdan entre reinicios, igual que el modo y la posición.
- Modo bandeja del sistema: otro botón en el encabezado oculta la ventana por completo y la reduce a un ícono en la bandeja; un clic o "Mostrar TimerMeet" desde su menú la restaura, "Salir" desde el mismo menú cierra la app.
- La lista de reuniones se actualiza en su lugar (sin destruir y reconstruir las tarjetas en cada segundo), así que la ventana no se siente lenta ni "reordena" nada al maximizar, mover o simplemente dejarla abierta.
- Vista de calendario mensual: un botón en el encabezado ("Vista calendario") cambia la lista actual por una cuadrícula mensual estilo Outlook/Teams (6 semanas fijas, lunes a domingo, con "‹"/"›" para navegar entre meses y un botón "Hoy"). Cada día muestra hasta 3 reuniones (hora + título, con el mismo color por trabajo que la lista) y un contador "+N más" para el resto; clic en una reunión abre el mismo formulario de edición que usa la lista. Clic en el número de día o en el fondo vacío de una celda abre el formulario ya limpio ("Limpiar") con esa fecha precargada, para crear una reunión nueva sin salir del calendario. "Vista de lista" regresa a la vista normal. Ignora el filtro de trabajo/empresa (siempre muestra todas las reuniones) y no agrega ningún campo nuevo a los timers guardados.
- Vista semanal: una tercera forma de ver los timers, estilo Outlook/Teams "semana" -- eje de horas (00:00-23:00) a la izquierda y 7 columnas de día (lunes a domingo), con una línea de "hora actual" en vivo que cruza la columna de hoy solo cuando la semana visible es la semana real actual. Hasta 2 reuniones por celda-hora antes de un contador "+N más"; clic en una reunión la selecciona (borde de acento; ver `v2.11.0` más abajo -- "Editar"/"Eliminar" de la barra de acciones actúan sobre esa selección), clic en el fondo vacío de una celda-hora crea una reunión nueva con esa fecha y esa hora exacta (`HH:00`) ya precargadas. Navegación propia ("‹ Semana anterior" / "› Semana siguiente" / "Esta semana") con una etiqueta de rango de fechas. Accesible desde "Vista semanal" en el encabezado de la lista o del calendario mensual, y desde ahí "Vista de lista"/"Vista calendario" regresan a las otras dos.
- Interfaz más responsiva (`v2.9.0`): los botones del encabezado (Salir, Donar, cambio de vista, etc.) ya no se salen del borde de la ventana ni el título "TimerMeet" se colapsa al tamaño mínimo de la app (960x640, el mismo piso que produce el Snap de media pantalla de Windows); los títulos largos de las tarjetas de reunión se ajustan en varias líneas en vez de recortarse sin aviso. Ver `SDD.md` para el detalle, incluyendo una limitación conocida y deliberadamente diferida (el panel de lista de reuniones puede quedar atascado en su ancho anterior tras un único salto grande de tamaño de ventana).
- Refuerzo de seguridad (`v2.9.1`, tras una auditoría dedicada): un `data/meetings.json` con contenido extremo pero técnicamente válido (un número desbordado, anidamiento profundo, un byte UTF-8 inválido) ya no puede hacer fallar la app ni saltarse la cuarentena; un `meetings.lock` inutilizable ya no bloquea los guardados para siempre; el enlace de Teams se valida por esquema también al leerlo del disco, no solo al abrirlo. Si al iniciar se descartó algún dato (registros corruptos o el archivo completo puesto en cuarentena), la app ahora lo avisa con un mensaje visible en pantalla, no solo en el registro. Ver `SDD.md` (`v2.9.1`) para el detalle completo.
- Menú contextual (clic derecho) en las vistas de calendario mensual y semanal (`v2.10.0`): clic derecho sobre una reunión muestra "Editar"/"Eliminar" (la misma confirmación de siempre); clic derecho sobre el fondo vacío de una celda/franja muestra "Nueva reunión" con la misma fecha (y hora, en la vista semanal) que ya precarga el clic izquierdo. No se agrega a la vista de lista.
- Toggle "Ver lun-vie" / "Ver semana completa" en la vista semanal (`v2.10.0`), inspirado en Microsoft Teams: oculta u muestra las columnas de sábado y domingo sin afectar la navegación (`Prev`/`Next`/`Esta semana` siguen moviéndose de a una semana calendario completa) ni el calendario mensual. La elección se recuerda entre reinicios.
- Mejor descubribilidad de "Vista semanal" (`v2.10.0`): en la pantalla de inicio (lista), el botón de la vista con eje de horas ahora aparece primero y con el color de acento de la app, para distinguirse de "Vista calendario" (mensual, sin eje de horas).
- "Eliminar serie completa" (`v2.11.0`), en el menú contextual (clic derecho) de mes y semana: borra de un solo golpe **todas** las ocurrencias de una serie recurrente, pasadas y futuras, sin conservar ninguna -- a diferencia de la limpieza automática/manual, que siempre conserva la última ocurrencia para no dejar de avisar. Solo aparece cuando la reunión clickeada tiene 2 o más ocurrencias vivas de esa serie; requiere una confirmación aparte que aclara que se borra la serie completa, no solo esa ocurrencia.
- Selección + barra de acciones en la vista semanal (`v2.11.0`): clic izquierdo en una reunión de la vista semanal ahora la selecciona (borde de acento) en vez de abrir edición directo -- exclusivo de esta vista, el calendario mensual no cambia. La barra de navegación de la vista semanal gana tres botones: "Agregar" (siempre disponible, misma fecha/hora actual que un clic en una celda vacía), "Editar" y "Eliminar" (solo con una reunión seleccionada; "Eliminar" aquí borra una sola ocurrencia -- "Eliminar serie completa" sigue siendo exclusivo del clic derecho). La selección se limpia al navegar de semana, alternar semana laboral/completa, o salir de la vista semanal; un viaje al modo gadget y de vuelta no la borra.
- Corrección de geometría en la vista semanal (`v2.11.3`): la fila de nombres de día y la cuadrícula de horas debajo dejaban de coincidir en cuanto algunos días tenían reuniones y otros no (medido: hasta 143px de diferencia en una sola columna). Ambas partes ahora comparten el mismo ancho mínimo por columna de día, así que la cuadrícula queda alineada con su encabezado sin importar cuántas reuniones tenga cada día -- ver `SDD.md` (`v2.11.3`) para el detalle.

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
