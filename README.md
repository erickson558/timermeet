# TimerMeet

Sitio local para EasyPHP que permite guardar varios timers de reuniones de Microsoft Teams.

## Qué hace

- Guarda reuniones por trabajo o empresa.
- Muestra cuenta regresiva para cada reunión.
- Lanza aviso previo con alarma sonora, parpadeo visual y notificación del navegador.
- Permite abrir el enlace de Teams desde cada timer.
- Guarda la información en `data/meetings.json` mediante PHP y deja una copia de respaldo en `localStorage`.
- Permite crear series repetitivas diarias, de semana laboral, semanales, quincenales o mensuales.
- Cada viernes (a partir de las 18:00 hora local), o al abrir la pestaña después de esa hora, TimerMeet extiende automáticamente cada serie recurrente activa para cubrir la semana siguiente, para que una daily o standup nunca deje de recordarse silenciosamente.
- Sincroniza periódicamente con el servidor (y al volver a la pestaña) para que una pestaña abierta por varios días no pierda ni sobreescriba reuniones agregadas desde otra pestaña o dispositivo.
- Usa MP3 locales más agresivos para `Sirena invasiva` y `Sirena de bomberos`, con fallback al tono sintético si el navegador no carga el audio.
- Incluye interfaz en español e inglés.

## Cómo usarlo en EasyPHP

1. Inicia EasyPHP.
2. Asegúrate de que esta carpeta exista dentro de `www/monitoreos/timermeet`.
3. Abre en tu navegador:
   - `http://127.0.0.1/monitoreos/timermeet/`
   - o la URL local equivalente que uses en EasyPHP.
4. Presiona `Activar notificaciones`.
5. Deja la pestaña abierta para que los recordatorios se disparen.
6. Si no ves cambios, recarga con `Ctrl + F5` para forzar la nueva versión `1.3.0`.

## Archivos principales

- `index.php`: estructura del sitio.
- `assets/styles.css`: diseño responsive.
- `assets/app.js`: lógica de timers, notificaciones, idioma, alarmas y almacenamiento.
- `api/meetings.php`: endpoint PHP compatible con EasyPHP 14.1 / PHP 5.4.
- `data/meetings.json`: archivo físico donde quedan guardados los timers.

## Gestión del proyecto

- `SDD.md`: especificación viva y criterios de aceptación.
- `AGENTS.md`: agentes recomendados para analizar, construir y publicar el proyecto.
- `.codex/skills/`: skills versionadas del proyecto para spec, implementación EasyPHP y publicación en GitHub.

## Nota importante

Los recordatorios dependen de que el navegador siga abierto en esta pestaña. Si luego quieres avisos aunque el navegador esté cerrado, el siguiente paso sería crear una app de escritorio o un servicio en segundo plano.

### Por qué antes fallaban algunos recordatorios

Hasta la versión `1.2.4`, cada serie recurrente (daily, weekly, etc.) se creaba con una cantidad fija de eventos (por ejemplo, 5 ocurrencias para "Semana laboral"). Al agotarse esa cantidad, la reunión desaparecía del calendario sin ningún aviso y dejaba de recordarse, aunque en la realidad la reunión seguía ocurriendo cada semana. Además, la pestaña solo leía `data/meetings.json` una vez al cargar, así que una pestaña abierta por varios días nunca se enteraba de reuniones agregadas desde otra pestaña o dispositivo, y su siguiente autoguardado podía sobreescribir esos cambios. Desde `1.3.0`, TimerMeet extiende las series activas automáticamente y vuelve a sincronizar con el servidor de forma periódica, así que ambos escenarios quedan cubiertos.

## Créditos de audio

- `Sirena invasiva`: `Siren Noise` de `KevanGC`, obtenido desde SoundBible bajo dominio público.
- `Sirena de bomberos`: `Fire Engine Siren Yelps And Wails` de `Alexander`, obtenido desde Orange Free Sounds bajo `CC BY 4.0`.
- Detalle y enlaces en `assets/audio/ATTRIBUTION.md`.

## Requisitos

- `EasyPHP-Webserver-14.1b2` o cualquier stack Apache + `PHP >= 5.4` sin dependencias externas ni base de datos.
- Sin dependencias de Composer, npm ni build step: `index.php`, `assets/app.js` y `assets/styles.css` se sirven tal cual.

## Privacidad y seguridad

- `data/meetings.json` guarda el contenido real de tus reuniones (títulos, notas, enlaces de Teams) y está excluido del repositorio mediante `.gitignore`; nunca lo subas a un repositorio público.
- `data/.htaccess` bloquea el acceso HTTP directo a esa carpeta (`Require all denied`).
- La app solo abre enlaces de Teams con esquema `http://` o `https://`; cualquier otro esquema se rechaza al guardar y al abrir.
- El endpoint `api/meetings.php` valida el tipo de cada campo y limita el tamaño del payload antes de escribir en disco.
- Esta app está pensada para uso local de un solo usuario (`127.0.0.1`); no incluye autenticación porque no está diseñada para exponerse a internet.

## Licencia

Este proyecto se publica bajo la licencia [Apache License 2.0](./LICENSE). Los archivos de audio en `assets/audio/` mantienen sus propias licencias originales (dominio público / `CC BY 4.0`); revisa `assets/audio/ATTRIBUTION.md` antes de reutilizarlos fuera de este proyecto.
