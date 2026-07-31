# TimerMeet Agents

Esta carpeta usa dos convenciones de agentes/skills en paralelo:

- **`.claude/`** — agentes y skills para Claude Code, activos para el desarrollo actual (app de escritorio en Python, `2.0.x`).
- **`.codex/`** — agentes y skills para Codex CLI, congelados junto con el baseline PHP (`legacy-php/`, `1.3.0`). Se conservan como referencia para quien siga usando esa herramienta sobre el código histórico; no se actualizan con los cambios de la versión Python.

## Claude Code — agentes activos (`.claude/agents/`)

### TimerMeet Spec Agent

- Propósito: convertir solicitudes en alcance claro, restricciones, criterios de aceptación y checklist de validación.
- Skill asociada: `.claude/skills/timermeet-spec-driver`
- Archivos principales: `SDD.md`, `AGENTS.md`, `README.md`.
- Cuándo usarlo: nuevas funciones, refactors con riesgo, cambios de alcance, decisiones de backlog.

### TimerMeet Python Builder Agent

- Propósito: implementar cambios en la app de escritorio (timers, alarmas, recurrencia, persistencia, i18n, UI) sin romper la fiabilidad de las alertas.
- Skills asociadas: `.claude/skills/timermeet-python-builder`, `.claude/skills/timermeet-code-commenter`, `.claude/skills/timermeet-exe-packager`
- Archivos principales: `timermeet_app/*.py`, `timermeet.py`, `tests/`.
- Cuándo usarlo: timers, alarmas, persistencia, UI, traducciones, empaquetado del `.exe`.

### TimerMeet GitHub Publisher Agent

- Propósito: preparar commits, revisar alcance Git, publicar de forma segura con `gh` usando la cuenta `erickson558`, y evitar subir datos personales por accidente.
- Skill asociada: `.claude/skills/timermeet-github-publisher`
- Archivos principales: estado Git del repo (que ya es la raíz del proyecto, sin ambigüedad de monorepo), `SDD.md`, `README.md`.
- Cuándo usarlo: commits, tags, releases, sincronización a `main`.

### TimerMeet Security Guardian Agent

- Propósito: correr `bandit`/`pip-audit`, revisar el checklist de hardening, y mantener `SECURITY.md` al día.
- Skill asociada: `.claude/skills/timermeet-security-guardian`
- Archivos principales: `timermeet_app/security.py`, `requirements*.txt`, `SECURITY.md`.
- Cuándo usarlo: antes de cada release, y tras tocar E/S de archivos, apertura de URLs, `subprocess` o dependencias.

### Skill adicional: proceso de fix estable

- `.claude/skills/timermeet-stable-fix-release` — el flujo de "ingeniero senior Python + QA + DevOps" (análisis → corrección → validación → versionado → commit → push) para futuras correcciones de bugs. Cualquiera de los agentes de arriba puede invocarlo.

## Codex CLI — agentes históricos (`.codex/skills/`, congelados)

Las tres skills originales para el baseline PHP siguen intactas para quien las necesite sobre `legacy-php/` (revisar `legacy-php/README.md` antes de reactivarlas, ya que las rutas de datos cambiaron):

- `timermeet-spec-driver`
- `timermeet-easyphp-builder`
- `timermeet-github-publisher`
