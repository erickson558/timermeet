# TimerMeet SDD

## Product Goal

Construir y mantener un sitio local para EasyPHP que permita registrar varios timers de reuniones de Microsoft Teams para distintos trabajos, con recordatorios visibles, sonoros y persistentes.

## Current Baseline

- Versión actual: `1.3.0`.
- Interfaz principal: [index.php](./index.php).
- Lógica cliente: [assets/app.js](./assets/app.js).
- Estilos: [assets/styles.css](./assets/styles.css).
- Persistencia local del servidor: [api/meetings.php](./api/meetings.php) y [data/meetings.json](./data/meetings.json).
- Respaldo local: `localStorage`.

## Technical Constraints

- Debe funcionar en `EasyPHP-Webserver-14.1b2`.
- Debe ser compatible con `PHP 5.4.31`.
- No debe requerir base de datos para el flujo base.
- Debe seguir funcionando si `fetch` al backend falla, usando la copia local del navegador.
- Debe mantener español como idioma inicial y permitir inglés.
- Debe considerar que las alarmas del navegador requieren la pestaña abierta y permisos del usuario.
- Este proyecto está dentro de un repositorio Git mayor con raíz en `C:/Program Files (x86)/EasyPHP-Webserver-14.1b2/www`; cualquier push a GitHub debe revisar si se publicará solo `timermeet` o todo el monorepo.

## Functional Requirements

1. Permitir crear, editar y eliminar timers de reuniones.
2. Permitir asociar cada timer con trabajo, título, fecha/hora, minutos de aviso, enlace de Teams y notas.
3. Mostrar la próxima reunión, el próximo aviso y el total de timers.
4. Permitir filtrar reuniones por trabajo.
5. Disparar un recordatorio antes del inicio de la reunión y otro al momento de inicio.
6. Mostrar una alarma sonora y una alarma visual persistente hasta que el usuario la silencie.
7. Permitir abrir el enlace de Teams desde la alarma y desde la tarjeta de la reunión.
8. Guardar la lista en disco mediante PHP y mantener una copia local de respaldo.
9. Permitir crear series repetitivas diarias, de semana laboral, semanales, quincenales o mensuales.
10. Si la recurrencia es de semana laboral, la fecha inicial debe ser lunes a viernes y las ocurrencias siguientes deben omitir sábado y domingo.
11. Permitir que los perfiles de audio más agresivos usen archivos MP3 locales servidos por EasyPHP en lugar de tonos sintéticos.
12. Si un MP3 no carga o el navegador no lo decodifica, la alarma debe caer al tono sintético existente.
13. Cada serie recurrente activa (`recurrenceType` distinto de `none`) debe extenderse automáticamente para cubrir al menos la semana siguiente, evaluado cada vez que la app está abierta a partir del viernes 18:00 hora local (o al abrirla después de esa hora si estuvo cerrada). No debe generar eventos con fecha pasada al ponerse al día tras una ausencia larga.
14. El cliente debe volver a sincronizar la lista de reuniones con el servidor de forma periódica y al recuperar el foco/visibilidad de la pestaña, sin perder reuniones agregadas desde otra pestaña o dispositivo ni reproducir de nuevo una alarma ya silenciada en otra sesión.
15. Un enlace de Teams solo debe guardarse o abrirse si usa esquema `http://` o `https://`.

## Non-Functional Requirements

- Mantener el código legible y con comentarios solo en bloques no obvios.
- Evitar sintaxis de PHP moderna incompatible con `PHP 5.4`.
- Mantener el frontend usable en escritorio y móvil.
- Forzar recarga de assets con versión cuando cambien `JS` o `CSS`.
- No guardar secretos, tokens o credenciales en el proyecto.

## Acceptance Criteria

- Al guardar un timer, aparece en la lista y sobrevive a recarga del navegador.
- Si el backend `PHP` responde, los timers quedan escritos en `data/meetings.json`.
- Si el backend falla, el usuario recibe aviso y la copia local sigue disponible.
- Cuando falta poco para una reunión, la app reproduce tono y muestra una señal visual clara.
- Cuando empieza la reunión, la alarma vuelve a dispararse.
- El idioma cambia entre `ES` y `EN` sin romper la interfaz.
- El filtro por trabajo funciona sobre los timers guardados.
- Al crear una serie de `Semana laboral`, la app genera solo eventos de lunes a viernes y rechaza una fecha inicial en sábado o domingo.
- Los perfiles `Sirena invasiva` y `Sirena de bomberos` reproducen audio más fuerte desde archivos locales, y la alarma sigue sonando aunque falle la carga del MP3 gracias al fallback sintético.
- Una serie recurrente cuya última ocurrencia guardada ya pasó vuelve a tener ocurrencias futuras la próxima vez que se abre la app un viernes después de las 18:00 (o después), sin crear eventos con fecha pasada.
- Ejecutar el motor de renovación dos veces seguidas con los mismos datos no debe crear ocurrencias duplicadas (idempotente).
- Dos pestañas abiertas en momentos distintos convergen: una reunión creada en una pestaña aparece en la otra tras la sincronización periódica o al recuperar el foco, sin que ninguna borre los cambios de la otra.
- Un enlace de Teams que no empiece con `http://` o `https://` se rechaza al guardar y no se abre desde la tarjeta ni desde la alarma.

## SDD Workflow

1. Traducir la petición del usuario a objetivo, restricciones y criterio de aceptación.
2. Actualizar este `SDD.md` antes de hacer cambios grandes o ambiguos.
3. Identificar archivos impactados y el mínimo cambio necesario.
4. Implementar.
5. Verificar sintaxis y comportamiento.
6. Actualizar `SDD.md`, `README.md` y versionado si cambió el comportamiento visible.

## Verification Checklist

- Ejecutar sintaxis PHP sobre `index.php` y `api/meetings.php`.
- Ejecutar `node --check` sobre `assets/app.js`.
- Validar `GET` y `POST` contra `api/meetings.php`.
- Confirmar que `Semana laboral` aparece en el selector y crea ocurrencias sin sábado ni domingo.
- Confirmar que `Sirena invasiva` y `Sirena de bomberos` usan MP3 locales y que, si se interrumpe esa carga, la app aún emite el tono sintético.
- Confirmar que la versión en `index.php` cambió si se modificaron assets cacheables.
- Revisar que no se introdujeron dependencias nuevas innecesarias.
- Simular el motor de renovación semanal contra `data/meetings.json` real (o una copia) y confirmar que series vencidas generan ocurrencias futuras sin fechas pasadas, y que una segunda pasada no duplica nada.

## Near-Term Backlog

- Exportación e importación de timers.
- Patrones personalizados por días específicos.
- Pruebas automatizadas del flujo en navegador.
- Avisos en segundo plano sin depender de una pestaña abierta.
- Empaquetado standalone fuera de EasyPHP.
- Permitir "pausar" o cancelar explícitamente una serie recurrente completa (hoy, borrar todas sus ocurrencias es la única forma de detener la renovación automática; borrar solo la última ocurrencia hace que la próxima renovación la regenere).
