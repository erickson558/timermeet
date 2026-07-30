# TimerMeet Agents

## TimerMeet Spec Agent

- Propósito: convertir solicitudes en alcance claro, restricciones, criterios de aceptación y checklist de validación.
- Skills asociadas:
- `.codex/skills/timermeet-spec-driver`
- Archivos principales: `SDD.md`, `AGENTS.md`, `README.md`.
- Cuándo usarlo: nuevas funciones, refactors con riesgo, cambios de alcance, decisiones de backlog.
- Prompt sugerido: `Use $timermeet-spec-driver to update the SDD and acceptance criteria for the next TimerMeet feature.`

## TimerMeet EasyPHP Builder Agent

- Propósito: implementar cambios en la app sin romper compatibilidad con EasyPHP y PHP 5.4.
- Skills asociadas:
- `.codex/skills/timermeet-easyphp-builder`
- Archivos principales: `index.php`, `assets/app.js`, `assets/styles.css`, `api/meetings.php`, `data/meetings.json`.
- Cuándo usarlo: timers, alarmas, persistencia, UI, traducciones, fixes de JavaScript o PHP.
- Prompt sugerido: `Use $timermeet-easyphp-builder to implement and verify a TimerMeet change under PHP 5.4 constraints.`

## TimerMeet GitHub Publisher Agent

- Propósito: preparar commits, revisar alcance Git, publicar de forma segura con `gh`, y evitar subir proyectos hermanos por accidente.
- Skills asociadas:
- `.codex/skills/timermeet-github-publisher`
- Archivos principales: estado Git del repo raíz, `SDD.md`, `README.md`, y el árbol de `timermeet`.
- Cuándo usarlo: primer push, creación de repo público, tagging, release, sincronización a `main`.
- Riesgo principal: el repositorio Git raíz actual es `.../www`, no `.../timermeet`; antes de publicar hay que decidir si GitHub recibirá solo `timermeet` o el monorepo completo.
- Prompt sugerido: `Use $timermeet-github-publisher to publish only the TimerMeet project safely with the authenticated gh account.`
