# TimerMeet SDD

## Product Goal

Recordar al usuario sus reuniones de Microsoft Teams con avisos visibles, sonoros y persistentes, sin depender de que un navegador permanezca abierto. La versión activa (`2.6.0`) es una app de escritorio en Python (Tkinter puro); la versión `1.3.0` en PHP/JS queda congelada en `legacy-php/` como referencia.

## Current Baseline

- Versión actual: `2.6.0` (Python, escritorio).
- Punto de entrada: [timermeet.py](./timermeet.py).
- Paquete de la app: [timermeet_app/](./timermeet_app/) (`models.py`, `recurrence.py`, `retention.py`, `storage.py`, `audio.py`, `notifications.py`, `alarm_ui.py`, `main_window.py`, `app.py`, `i18n.py`, `security.py`, `tray_icon.py`).
- Persistencia: archivo compartido [data/meetings.json](./data/meetings.json) (mismo esquema que la versión PHP; se lee y escribe con fusión ante posibles ediciones desde otra PC vía OneDrive, ver `timermeet_app/storage.py`).
- Preferencias locales: `data/settings.json` (idioma, lista de empresas).
- Pruebas: [tests/](./tests/) (`unittest`).
- Empaquetado: [build_exe.py](./build_exe.py) → `TimerMeet.exe` en la raíz del repo, junto a `timermeet.py` y `computer_pc_10894.ico`.
- Baseline histórico (congelado): [legacy-php/](./legacy-php/) — sitio EasyPHP + JS, versión `1.3.0`, ver `legacy-php/README.md`.

## Arquitectura: backend y frontend sí están separados

TimerMeet ya sigue una separación tipo modelo-vista-controlador dentro de `timermeet_app/`, aunque todo viva en un mismo paquete (no en carpetas `backend/`/`frontend/` separadas):

| Capa | Archivos | Regla |
|---|---|---|
| **Backend** (lógica pura, sin ventanas ni widgets) | `models.py`, `recurrence.py`, `retention.py`, `storage.py`, `audio.py`, `notifications.py`, `security.py`, `i18n.py` | No importan `tkinter` ni conocen la existencia de la ventana. Se pueden probar con `unittest` sin abrir ninguna GUI (ver `tests/`). |
| **Frontend** (vista, sin lógica de negocio) | `main_window.py`, `alarm_ui.py` | Solo construyen/actualizan widgets y reenvían acciones del usuario a través de `Callbacks`; no validan datos, no deciden cuándo suena una alarma, no tocan `storage.py` directamente. |
| **Controlador** (conecta ambos) | `app.py` | Único lugar que orquesta: cuándo guardar, cuándo disparar una alarma, qué mostrar en cada panel. Le pasa datos ya calculados al frontend; nunca al revés. |

Esta separación ya existía antes de esta versión; lo que se agrega aquí es dejarlo explícito en la documentación para que sea fácil de verificar (`.claude/skills/timermeet-python-builder/references/module-map.md` tiene el detalle archivo por archivo).

## Por qué se reescribió a Python (v2.0.0)

La versión web dependía de que una pestaña del navegador permaneciera abierta y enfocada para disparar avisos (permiso de `Notification`, temporizadores de la pestaña, ahorro de batería/throttling del navegador). Ese fue el motivo explícito para migrar ("no me alerta como debe"). Un proceso nativo de escritorio elimina esa dependencia por completo y, de paso, elimina toda la superficie de red de la versión anterior (ya no hay endpoint PHP ni servidor HTTP).

## Por qué v2.0.1 dejó de usar CustomTkinter

Al probar `v2.0.0` con datos reales (41 reuniones), la ventana tardaba entre 20 y 26 segundos en volverse interactiva y parecía "no abrir". La causa raíz, confirmada con mediciones (ver `tests/` y el historial de commits): CustomTkinter difiere el renderizado de bordes redondeados de cada widget (imagen PIL por widget) hasta que Tk procesa su cola de tareas en espera; con las ~40-50 widgets de la interfaz más las tarjetas de reuniones, ese primer vaciado de cola tomaba decenas de segundos. Se reescribió toda la interfaz (`timermeet_app/main_window.py`, `alarm_ui.py`) con widgets `tkinter`/`ttk` planos, que no tienen ese costo. Además:
- Las tarjetas de reuniones dejaron de reconstruirse por completo en cada latido de 1 segundo (solo se re-renderizan si su contenido visible cambió).
- La inicialización de `pygame.mixer` se volvió perezosa y se ejecuta en un hilo de fondo, no de forma síncrona al arrancar.
- El recálculo del área de scroll de la lista de reuniones se agrupa (debounce) en vez de recalcularse en cada widget insertado.
- Se corrigió un bug real de arranque bajo `--windowed` de PyInstaller: `sys.stdout`/`sys.stderr` son `None` sin consola adjunta, lo que hacía fallar en silencio la primera impresión de `pygame` y dejaba la ventana creada pero nunca mostrada.

## Por qué v2.1.0: el freeze seguía ahí, y de dónde salía de verdad

Después de `v2.0.1` el arranque seguía sintiéndose "congelado" (~10s sin responder). La causa real, aislada con mediciones directas (no con suposiciones): `TimerMeetApp.__init__` llamaba a `self.root.update_idletasks()` justo antes de mostrar la ventana, para forzar que todo el trabajo de renderizado pendiente terminara antes de quitar el letrero de "Cargando...". Esa llamada es **bloqueante y síncrona** — obliga a Tcl/Tk a vaciar *toda* su cola de tareas pendientes de una sola vez, sin importar cuánto tarde, y mientras tanto Windows marca la ventana como "Sin respuesta". Quitar esa llamada (dejar que `mainloop()` procese la misma cola de forma incremental, intercalada con el bombeo normal de mensajes) eliminó el freeze por completo: la ventana queda respondiendo desde el primer segundo. **Regla dura de ahora en adelante: nunca llamar a `root.update()`/`root.update_idletasks()` de forma síncrona en el camino de arranque** — ver el comentario en `app.py::TimerMeetApp.__init__`.

De paso, esta versión responde a otra causa de lentitud: el archivo de datos crecía sin límite porque nada purgaba reuniones pasadas ya notificadas. Se agregó `timermeet_app/retention.py` (ver requisito funcional #12 abajo) que elimina esas reuniones "muertas" con una ventana de gracia de 7 días, revisado una vez por hora y también al arrancar.

## v2.2.0: qué tan rápido puede abrir realmente, y dos botones nuevos

El usuario reportó que seguía sintiendo la app lenta para abrir y para responder. Se validó de nuevo, esta vez comparando puntos de referencia concretos:

- `python timermeet.py` (código fuente, sin empaquetar): se vuelve interactiva en ~2-3 segundos y nunca deja de responder — confirmado con mediciones repetidas.
- `TimerMeet.exe` (`--onefile`): tarda entre 7 y 10 segundos en mostrar contenido, pero **nunca aparece como "Sin respuesta"** durante ese tiempo — es tiempo de arranque de PyInstaller (extraer el bundle a una carpeta temporal, cargar los DLL de `pygame`, posible inspección de un antivirus sobre un ejecutable poco visto) y no un bloqueo del código de la app.
- Se probó una compilación `--onedir` (carpeta en vez de un solo archivo) como alternativa: no fue más rápida en esta máquina (de hecho un poco más lenta en su primera ejecución, probablemente por revisión de antivirus sobre más archivos nuevos), así que se mantiene `--onefile` tal como se pidió originalmente.
- Se midió el tiempo de importar cada dependencia por separado: `pygame` es la más pesada (~0.75s en código fuente), el resto es insignificante.

**Conclusión:** el bloqueo real (la ventana "congelada" sin responder) ya está resuelto desde v2.1.0 y sigue confirmado aquí. Los 7-10 segundos que quedan al abrir el `.exe` son un costo de arranque de PyInstaller/antivirus, no un bug de la aplicación, y no mejoraron al probar `--onedir` ni al relanzar el mismo ejecutable varias veces. Si en el futuro se necesita reducir esto más, la palanca disponible es aligerar dependencias (ej. quitar `pygame` y los MP3 de sirena/bomberos en favor de solo tonos sintéticos) — un cambio de *funcionalidad*, no solo de rendimiento, que debe decidirse explícitamente con el usuario antes de aplicarse.

Además se agregaron dos controles pedidos directamente:
- Botón **Salir** en el encabezado (usa el mismo cierre ordenado que el botón X de la ventana: silencia cualquier alarma activa y luego cierra).
- Botón **Eliminar eventos pasados** en el panel de resumen: borra de inmediato todos los eventos ya pasados de **todos** los trabajos (ignora el filtro activo), sin la ventana de gracia de 7 días ni el requisito de "ambas alarmas ya dispararon" que sí aplica la purga automática — es una acción manual y explícita. Igual conserva la última ocurrencia de cada serie recurrente para no perder la referencia de renovación (`timermeet_app/retention.py::clear_past_meetings`).

## v2.3.0: un bug real (borrar no se quedaba borrado) y arranque más liviano

**Bug crítico encontrado y corregido:** el botón "Eliminar eventos pasados" (y también el botón individual de borrar, y la purga automática) quitaban la reunión de la lista en memoria, pero `storage.save_meetings()` vuelve a leer el disco y fusiona esa lectura con la memoria antes de escribir (`merge_meeting_lists`, pensado para que dos PCs sincronizadas por OneDrive no se pisen los datos). El problema: una reunión que acabas de borrar en memoria y una reunión que "otra PC agregó y todavía no hemos visto" se ven exactamente igual para la fusión (existe en el disco, no existe en memoria) — así que la fusión la volvía a agregar sola, deshaciendo el borrado en silencio. Esto afectaba **todo** lo que borra reuniones: el botón de borrar individual, "Eliminar eventos pasados", y la purga automática de `retention.py` (por eso el archivo real seguía creciendo en vez de quedarse en 30 reuniones tras la limpieza).

**Corrección:** `merge_meeting_lists`/`save_meetings` ahora aceptan `deleted_ids` — los ids que *este mismo proceso* acaba de quitar a propósito — y nunca los revive desde esa lectura del disco. `TimerMeetApp` centraliza esto en `_apply_meetings()`: cualquier código que quite reuniones de `self.meetings` debe pasar por ahí, no asignar la lista directamente. Verificado contra el archivo real: sin la corrección, un borrado volvía a aparecer de inmediato; con ella, se queda borrado tanto en memoria como en el archivo.

**Arranque más liviano:** `pygame` y `plyer` ahora se importan de forma perezosa (solo la primera vez que realmente se necesita un sonido o una notificación), no al arrancar la app. Antes, el simple hecho de importar `timermeet_app.app` ya cargaba `pygame` (~0.75s solo esa importación, más en el `.exe` empaquetado) aunque el sonido no se fuera a usar hasta más tarde. Medido: el tiempo de importar todo el paquete bajó de ~1.26s a ~0.19s.

## v2.4.0: el `.exe` ya abre en menos de 5 segundos, y empresas configurables

El usuario reportó que el `.exe` seguía sintiéndose lento (medido: 6.13s hasta mostrar contenido) y pidió explícitamente un límite duro: "no tarde más de 5 segundos en abrir". v2.2.0 ya había identificado la causa (arranque de PyInstaller, no el código de la app) pero la había dejado sin resolver porque la palanca disponible entonces -- quitar `pygame` -- era un cambio de funcionalidad que requería decidirse explícitamente. Esta versión lo resuelve:

- **`pygame` → API MCI de Windows.** `timermeet_app/audio.py` se reescribió para reproducir los MP3 de sirena/bomberos con `winmm.dll` vía `ctypes` (stdlib, sin nada que empaquetar) en vez de `pygame.mixer`. El paquete de `pygame` pesaba ~24.3MB en 730 archivos, y `--onefile` de PyInstaller reextrae *todo* el bundle a una carpeta temporal en cada arranque -- ese costo de extracción, no el código Python, era el cuello de botella real. El tono sintético de respaldo (`winsound.Beep`) no cambió. Verificado con una prueba directa de MCI (abrir/reproducir/medir posición/detener sobre el MP3 real) antes de reescribir, y con una prueba end-to-end después (siren/fire en bucle, perfil solo-sintético) -- ningún perfil de sonido quedó en silencio.
- **`plyer` con `--hidden-import` en vez de `--collect-submodules`.** `plyer.notification` elige su backend con un import dinámico (`plyer.platforms.<os>.notification`) que el análisis estático de PyInstaller no puede seguir, así que antes se empaquetaban los ~294 archivos de **todos** los backends de **todos** los facades de plyer (Android, iOS, macOS, Linux, Windows) para cubrir ese único import. Como esta app solo corre en Windows, nombrar exactamente `plyer.platforms.win.notification` en `build_exe.py` es suficiente -- PyInstaller sigue automáticamente sus imports estáticos (`plyer.facades`, `plyer.platforms.win.libs.balloontip`/`win_api_defs`) y el resto de plyer (~250 archivos que esta app nunca toca) se queda fuera.
- **Un `root.update()` síncrono de más en el arranque.** Perfilado con `cProfile` reveló que `TimerMeetApp.__init__` llamaba `self.root.update()` justo después de mostrar la etiqueta "Cargando…", para forzar su primer pintado -- pero `update()` también procesa el `after(0, self._force_show_window)` ya encolado (deiconify/state/lift/focus_force), medido en ~0.5s aparte. Se cambió a `update_idletasks()`, que solo vacía la cola de geometría/pintado (barato aquí porque en ese punto del arranque solo existe esa etiqueta) y deja que `_force_show_window` corra en la primera vuelta de `mainloop()` en vez de forzarlo de forma síncrona dentro de `__init__`.

**Resultado medido:** el `.exe` (`TimerMeet.exe`, 36.2MB → 11.4MB) pasó de 6.13s a un rango estable de 3.2-3.9s hasta mostrar la ventana con contenido real, medido lanzándolo repetidamente y sondeando el título de la ventana vía Win32 -- cumple el límite de 5 segundos con margen.

**Empresas configurables + combobox:** el campo "Trabajo / Empresa" del formulario pasó de un `Entry` de texto libre a un `ttk.Combobox` (el único widget ttk de la app -- ver el docstring de `_configure_ttk_style` en `main_window.py` sobre por qué es una excepción segura a la regla de "solo tkinter puro": no es una reescritura basada en PIL como CustomTkinter, así que no repite ese costo de arranque). La lista de empresas:
- Se guarda en `data/settings.json` bajo la clave `"companies"` (local a esta PC, igual que el idioma -- no pasa por la fusión de `meetings.json`).
- Se siembra una sola vez, en el primer arranque bajo esta versión, con los nombres de trabajo ya presentes en `meetings.json` (para que quien actualice no vea el combobox vacío); después de eso la lista guardada manda -- no se vuelve a derivar de `meetings.json` en arranques siguientes, o una eliminación explícita reaparecería sola mientras exista una reunión vieja con ese nombre.
- Se agrega automáticamente al guardar un timer con un nombre de trabajo que aún no está en la lista (escribirlo una vez alcanza para que quede disponible la próxima vez).
- Se administra explícitamente con el enlace "Gestionar empresas" junto a la etiqueta del campo: agregar un nombre sin necesidad de guardar un timer primero, o eliminar uno de la lista (eliminar solo afecta el combobox -- las reuniones ya guardadas con ese nombre no se tocan ni se pierden).

De paso se corrigió un bug preexistente que este cambio habría hecho visible: `handle_toggle_language` sobrescribía `settings.json` completo con `{"language": ...}`, lo que habría borrado la lista de empresas cada vez que alguien cambiara de idioma. Ahora relee y fusiona antes de guardar.

## v2.5.0: modo gadget/mini (estilo "skin mode" de Windows Media Player)

El usuario pidió un segundo modo, flotante y compacto, "algo como lo hacía Windows Media Player en su modo máscara". Antes de implementar se corrió un panel de diseño (3 propuestas independientes) para decidir el mecanismo correcto en Tkinter/Windows; la síntesis eligió **reutilizar la misma ventana `root`** (nunca un segundo `Tk()`/`Toplevel` para toda la app) en vez de crear una ventana flotante separada, precisamente porque es la única opción que no exige tocar `alarm_ui.py` ni el arranque (`_force_show_window`).

**Cómo funciona:**
- `main_window.py` ahora construye dos marcos hermanos en la misma celda de `root`: `full_view` (el layout de siempre: encabezado + formulario + resumen, sin cambios visuales) y `gadget_view` (nuevo, 280x130px, sin bordes de Windows). Solo uno está `grid()`eado a la vez; `set_gadget_mode()` intercambia cuál.
- El modo gadget usa `overrideredirect(True)` + `attributes("-topmost", True)` para lograr el look "sin marco, siempre encima" real (no solo una ventana chica con barra de título nativa). Cada cambio de modo envuelve el toggle de `overrideredirect` en un `withdraw()` inmediatamente antes y un `deiconify()` inmediatamente después -- evita un problema conocido de Windows/Tk donde ese atributo no se aplica de forma confiable en una ventana ya visible.
- Arrastrar desde cualquier punto del gadget (etiquetas, franja superior) mueve la ventana; doble clic o el botón "Completo" regresa a la vista normal; el botón "×" cierra la app igual que "Salir".
- El modo y la última posición se guardan en `settings.json` (`gadgetMode`, `gadgetX`, `gadgetY`) con el mismo patrón leer-fusionar-guardar que ya usan `language`/`companies` -- nunca sobrescribe esas otras claves.
- `AlarmController` (`alarm_ui.py`) **no se modificó en absoluto**: su overlay y diálogo ya eran `Toplevel`s independientes, no-`transient()`, cuya visibilidad nunca dependió del tamaño/posición/decoración de `root` -- verificado disparando una alarma real con el modo gadget activo (overlay y diálogo siguen apareciendo, quedando encima, y funcionando igual). Cambiar de modo se bloquea explícitamente mientras `AlarmController.is_active()` sea verdadero (con aviso), como garantía adicional a que el `grab_set()` del diálogo ya hace esto físicamente imposible por la UI.

**Validación exhaustiva antes de dar por terminado:** además de la validación manual de siempre, esta vez se corrió una revisión adversarial con paneles independientes (corrección/regresión, particularidades de Windows/Tkinter, consistencia de código) seguida de un intento de refutación por cada hallazgo. Se encontraron y corrigieron **8 bugs reales**, ninguno detectado por la batería de pruebas automatizadas existente (este proyecto no tiene pruebas de ventanas/geometría de Tkinter):

1. **Arrastre sin límites** podía sacar el gadget completamente de la pantalla (sin barra de tareas ni Alt-Tab por ser `overrideredirect`, quedando inalcanzable). Corregido: cada evento de arrastre ahora se recorta con la misma lógica que ya usaba el posicionamiento inicial.
2. **Doble clic para restaurar + un pequeño temblor de mouse** reposicionaba la ventana grande recién restaurada usando un offset de arrastre obsoleto (calculado cuando la ventana aún era el gadget chico). Corregido: los manejadores de arrastre ahora verifican que el modo gadget siga activo antes de mover nada.
3. **Ventana de carga a tamaño completo** se alcanzaba a pintar antes de colapsar al gadget, en cada arranque que retomaba el modo gadget (las preferencias se leían después de fijar la geometría 1180x760). Corregido: ahora se leen primero, y si el modo gadget estaba activo, `root` nunca se muestra a tamaño completo.
4. **Recorte a un solo monitor:** `winfo_screenwidth()/height()` en Windows solo reportan el monitor primario, no el escritorio virtual completo -- en una máquina con 2 monitores, esto regresaba el gadget al monitor primario cada vez que se reactivaba el modo, aunque el usuario lo hubiera dejado a propósito en el segundo. Corregido con `GetSystemMetrics` (vía `ctypes`) para los límites reales del escritorio virtual, con reserva al valor de Tk si esa llamada falla.
5. **`gadgetX`/`gadgetY` sin validar** podían tumbar el arranque completo si `settings.json` tenía un valor no numérico (edición manual, corrupción). Corregido con la misma disciplina defensiva que ya se usa para `language`.
6. **Texto de "siguiente aviso" sin límite de líneas** en una ventana de alto fijo (130px) podía recortarse a la mitad si el título de la reunión era largo. Corregido con un truncado específico para la vista gadget (no afecta la vista completa, que sí tiene espacio).
7. **El botón "×"** no pasaba por el sistema de traducciones (i18n) como el resto de los textos del archivo. Corregido agregando la clave `gadgetCloseButton` (mismo glifo en ambos idiomas) y asignándola en `apply_translations()` igual que los demás.
8. Un detalle de tipado (`-> tuple` en vez de `-> Tuple[int, int]`) para consistencia con el resto del archivo.

**Nota sobre el tiempo de arranque medido en esta sesión:** al recompilar el `.exe` con este cambio, el tiempo medido subió por encima de los 5 segundos en varias corridas. Se descartó como regresión de este cambio mediante una comparación directa: el `.exe` anterior (idéntico al ya publicado en v2.4.0, sin ningún código de esta versión) mostró el mismo aumento bajo las mismas condiciones del sistema en ese momento (varias sesiones de Claude Code y procesos `node` corriendo en paralelo en esa máquina). El tiempo de inicialización a nivel de código fuente (`TimerMeetApp.__init__`, medido con `time.perf_counter()`, no afectado por el antivirus ni por el arranque de PyInstaller) se mantuvo igual (~1.7-2.0s) antes y después de este cambio. Repetir la medición del `.exe` en una máquina menos ocupada es la validación pendiente antes de confiar en un número absoluto.

## v2.6.0: el bug real detrás de "sigue lenta" + modo bandeja

El usuario reportó que la UI seguía sintiéndose lenta, en particular que maximizar o mover la ventana se sentía lento y "reordenaba" los componentes, y pidió además un modo bandeja del sistema.

**El bug real (no solo percepción):** perfilando `TimerMeetApp._refresh_all()` con los datos reales (24 reuniones) se encontró que un re-render completo de la lista de reuniones tomaba **entre 1.5 y 1.75 segundos** -- un bloqueo síncrono del hilo de la UI de esa duración, disparado cada vez que el heartbeat de 1 segundo detectaba un cambio real (como mínimo una vez por minuto, porque el texto de cuenta regresiva cambia en cada minuto exacto). La causa: `render_meeting_list()` destruía y reconstruía las ~10 widgets de **cada** tarjeta en **cada** render, y `tkinter.Widget.destroy()` no es barato cuando el widget tiene comandos vinculados (cada botón de tarjeta liga 3: `command=` más `<Enter>`/`<Leave>`) -- para 24 reuniones x ~3 botones, son ~72 comandos que Tcl debe desregistrar uno por uno. Un bloqueo síncrono de 1.5+ segundos, si coincide con que el usuario está arrastrando o maximizando la ventana, explica exactamente el síntoma reportado: la ventana "se congela" y luego, cuando el heartbeat termina, Tk pinta de golpe todo el trabajo de geometría acumulado -- lo que se percibe como que los componentes "se reordenan".

**La corrección:** `render_meeting_list()` ahora reutiliza las widgets de cada tarjeta entre renders (indexadas por id de reunión) en vez de destruir y reconstruir todo -- solo actualiza el texto/color con `.configure()` y la fila con `.grid()`, y solo crea o destruye tarjetas para reuniones que realmente aparecen o desaparecen (guardar, borrar, cambiar el filtro). Un cambio de idioma sigue forzando una reconstrucción completa (es la única actualización que no se puede resolver con `.configure()` en cada campo), pero eso es una acción explícita del usuario, no algo que pasa cada segundo. Medido: el mismo re-render completo bajó de ~1.5-1.75s a **~18ms** (unas 85-95 veces más rápido). De paso se aplicó el mismo debounce vía `after_idle` que ya usaba el recálculo de `scrollregion` al ajuste de ancho del canvas en `_ScrollablePanel` (antes se recalculaba en cada evento `<Configure>` individual, que se dispara en ráfaga durante un arrastre/maximizado en vivo).

**Modo bandeja del sistema:** nuevo botón "Bandeja" en el encabezado oculta la ventana por completo y deja solo un ícono en la bandeja del sistema (clic o "Mostrar TimerMeet" en su menú para regresar; "Salir" en el mismo menú cierra la app). Implementado con [`pystray`](https://github.com/moses-palmer/pystray) (no a mano vía `ctypes`/Win32 crudo como el audio MCI, esta vez sí se agregó una dependencia nueva -- pystray es una librería madura y ampliamente usada específicamente para esto, y reimplementar un mensaje-loop de Win32 a mano tenía más riesgo de bugs sutiles que reimplementar la reproducción de un MP3). `pystray.Icon.run()` **debe** llamarse desde el hilo principal según su propia documentación -- como Tkinter ya ocupa ese rol con su propio `mainloop()`, se usa `run_detached()` en su lugar (pensado exactamente para integrarse con el mainloop de otra librería), y todo callback que el ícono dispara (desde su propio hilo) se reenvía al hilo principal de Tk vía `root.after(0, ...)` antes de tocar cualquier widget. Igual que el modo gadget, cambiar a modo bandeja se bloquea mientras suena una alarma. `AlarmController` no necesitó ningún cambio -- se disparó una alarma real con la app en modo bandeja y el overlay/diálogo/sonido siguieron funcionando exactamente igual, por la misma razón que en modo gadget (sus Toplevels son independientes del estado de `root`).

**Costo de la nueva dependencia, medido y mitigado:** `pystray` es minúsculo (0.2MB/26 archivos), pero depende de `Pillow` para cargar la imagen del ícono, y por defecto el hook de PyInstaller para Pillow empaqueta los ~47 módulos `PIL.*ImagePlugin` (JPEG, TIFF, WEBP, etc.), sumando ~19MB al `.exe` de un solo archivo. Medido en una comparación A/B controlada (mismo momento, misma carga del sistema): esto agregó ~0.8-1.1 segundos al arranque, suficiente para poner en riesgo el límite de 5 segundos. Como esta app solo necesita abrir su propio archivo `.ico` (que puede contener cuadros en PNG o BMP), `build_exe.py` ahora excluye explícitamente los ~44 plugins de PIL que no hacen falta (calculado dinámicamente contra la lista real de Pillow, no una lista fija a mano, para que siga siendo correcto si una versión futura de Pillow agrega o renombra plugins) -- esto bajó el `.exe` de ~30.8MB a ~26.0MB y, medido de nuevo en la misma comparación A/B, dejó el arranque prácticamente igual al de antes de agregar el modo bandeja.

## Technical Constraints

- Windows 10/11, Python 3.9+ (probado con 3.12).
- Interfaz gráfica: `tkinter`/`ttk` puro (sin CustomTkinter, ver arriba).
- Dependencias runtime: `plyer` (notificaciones nativas, mejor esfuerzo), `pystray` + `Pillow` (ícono de la bandeja del sistema, modo bandeja). Ver `requirements.txt`. El audio (MP3 vía MCI, tono sintético vía `winsound`) usa solo la librería estándar y DLL del propio Windows -- no agrega dependencia.
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
5. Perfiles `Sirena invasiva` y `Sirena de bomberos` usan MP3 locales (`assets/audio/`) vía la API MCI de Windows (`winmm.dll`); si el archivo falla o no carga, cae automáticamente a un tono sintético (`winsound.Beep`) — nunca debe quedar en silencio.
6. Series repetitivas: diaria, semana laboral (L-V), semanal, quincenal, mensual. "Semana laboral" exige fecha inicial de lunes a viernes.
7. Motor de renovación semanal: cada serie activa se extiende automáticamente para cubrir ~1 semana adelante, evaluado en cada heartbeat pero con efecto real solo a partir del viernes 18:00 hora local (o al abrir la app después de esa hora). Es idempotente (una segunda pasada no duplica) y nunca crea ocurrencias con fecha pasada.
8. El enlace de Teams solo se abre/guarda si usa esquema `http://` o `https://` (`security.is_http_url`); mismo criterio para el botón de donación.
9. Botón de donación "Cómprame una cerveza" enlazando a PayPal (`https://www.paypal.com/donate/?hosted_button_id=ZABFRXC2P3JQN`).
10. Interfaz completa en español e inglés, con selector de idioma que recuerda la preferencia entre sesiones (`data/settings.json`).
11. Persistencia resiliente ante múltiples PCs sincronizadas por OneDrive: al guardar, se relee el disco y se fusiona con la memoria (gana el registro con `updatedAt` más reciente; `reminderSent`/`startSent` siempre se combinan con OR para no repetir una alarma ya silenciada en otra sesión); se refresca desde disco periódicamente y al recuperar el foco de la ventana.
12. Retención automática (`timermeet_app/retention.py`): una reunión se elimina del archivo solo si ya pasó, sus dos avisos (`reminderSent` y `startSent`) ya se dispararon, y han pasado al menos 7 días desde entonces. Nunca se purga si algún aviso sigue pendiente (evita perder recordatorios silenciosamente) ni la ocurrencia más reciente de una serie recurrente (el motor de renovación la necesita como ancla). Se revisa al arrancar y luego una vez por hora.
13. Botón "Salir" en el encabezado: cierra la app de forma ordenada (silencia cualquier alarma activa antes de cerrar), igual que el botón X de la ventana.
14. Botón "Eliminar eventos pasados" en el panel de resumen: pide confirmación y luego elimina de inmediato todos los eventos ya pasados de todos los trabajos (sin importar el filtro activo ni si sus avisos ya dispararon), conservando siempre la última ocurrencia de cada serie recurrente.
15. El campo "Trabajo / Empresa" del formulario es un combobox editable (`ttk.Combobox`) con la lista de empresas guardadas como opciones, en vez de un campo de texto libre a escribir cada vez; sigue aceptando escribir un nombre nuevo directamente.
16. Lista de empresas configurable desde "Gestionar empresas" (junto a la etiqueta del campo): agregar una empresa nueva o eliminar una existente de la lista, sin afectar las reuniones ya guardadas con ese nombre. Guardar un timer con un nombre no listado lo agrega automáticamente a la lista.
17. La app debe volverse interactiva (ventana con contenido real, no solo el letrero de carga) en menos de 5 segundos al abrir `TimerMeet.exe`.
18. Modo gadget/mini: un botón en el encabezado ("Modo gadget") reemplaza la ventana completa por un panel flotante, sin bordes, siempre-encima y arrastrable (280x130px) con reloj, siguiente aviso, y botones para volver a la vista completa o cerrar la app. El modo y la última posición se recuerdan entre reinicios. Cambiar de modo se bloquea mientras suena una alarma.
19. Modo bandeja del sistema: un botón en el encabezado ("Bandeja") oculta la ventana por completo y deja solo un ícono en la bandeja del sistema; un clic o "Mostrar TimerMeet" en su menú restaura la ventana, y "Salir" en el mismo menú cierra la app de forma ordenada. No se recuerda entre reinicios (siempre inicia visible, en el modo completo o gadget que estuviera guardado). Cambiar a este modo se bloquea mientras suena una alarma.
20. La lista de reuniones se actualiza sin reconstruir por completo las tarjetas visibles en cada latido del heartbeat -- solo el texto/color de cada tarjeta existente cambia, y solo se crean o destruyen tarjetas para reuniones que realmente aparecen o desaparecen.

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
- La ventana responde a eventos de Windows (no aparece "Sin respuesta") durante todo el arranque, incluso con decenas de reuniones guardadas.
- Una reunión pasada con ambos avisos ya disparados desaparece del archivo después de 7 días; una con algún aviso pendiente (aunque sea vieja) nunca desaparece sola.
- Lanzar `TimerMeet.exe` repetidamente muestra la ventana con contenido real (no solo el letrero de carga) en menos de 5 segundos, medido sondeando el título de la ventana.
- El combobox de "Trabajo / Empresa" ofrece las empresas guardadas y sigue aceptando texto libre; guardar un timer con un nombre nuevo lo deja disponible en el combobox la próxima vez sin pasos adicionales.
- "Gestionar empresas" permite agregar o eliminar una empresa de la lista; eliminar una empresa no modifica ni borra las reuniones ya guardadas con ese nombre, y la lista persiste entre reinicios de la app.
- Cambiar de idioma no borra la lista de empresas guardada (ni ninguna otra clave de `data/settings.json`).
- El botón "Salir" cierra la app sin dejar procesos colgados ni perder cambios sin guardar.
- El modo gadget se puede activar y desactivar repetidamente sin dejar la ventana fuera de la pantalla (el arrastre y la posición inicial siempre quedan dentro de los límites reales del escritorio, incluyendo monitores secundarios); una alarma real disparada durante el modo gadget sigue mostrando el overlay, el diálogo y el sonido con normalidad, y cambiar de modo se rechaza mientras esa alarma esté activa.
- El botón "Eliminar eventos pasados" borra todos los eventos vencidos de todos los trabajos tras confirmar, y conserva la última ocurrencia de cada serie recurrente.
- Una reunión borrada (individualmente, por "Eliminar eventos pasados", o por la purga automática) desaparece de la GUI de inmediato y sigue desaparecida después de guardar, recargar el archivo, o reiniciar la app -- nunca reaparece sola.
- El modo bandeja oculta la ventana y muestra un ícono en la bandeja del sistema; mostrar desde el menú del ícono (o el clic por defecto) restaura la ventana con normalidad, y "Salir" desde ese mismo menú cierra la app sin dejar el ícono ni procesos colgados. Una alarma real disparada en modo bandeja sigue sonando y mostrando el overlay con normalidad, y cambiar a este modo se rechaza mientras esa alarma esté activa.
- Un re-render completo de la lista de reuniones con datos reales toma milisegundos, no segundos (verificado con `time.perf_counter()`, no con una llamada a `update()`, que por sí sola fuerza un vaciado de cola que contaminaría la medición); mover o maximizar la ventana no se siente congelado ni "reordena" visualmente las tarjetas.

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
