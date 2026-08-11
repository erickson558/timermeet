# Security Policy

TimerMeet es una aplicación de escritorio local, de un solo usuario, sin servidor ni puerto de red expuesto. Este documento describe qué versión recibe correcciones y cómo reportar un problema.

## Versiones soportadas

Solo la última versión etiquetada (ver [Releases](https://github.com/erickson558/timermeet/releases)) recibe correcciones de seguridad. Este es un proyecto de un solo mantenedor; no existe una matriz de soporte de largo plazo para versiones anteriores.

## Cómo reportar una vulnerabilidad

Abre un [issue en GitHub](https://github.com/erickson558/timermeet/issues) describiendo el problema. No incluyas datos sensibles (reuniones reales, enlaces de Teams, credenciales) en el reporte.

## Superficie de riesgo y mitigaciones

- **Sin red**: no hay servidor HTTP ni puerto abierto; la app no acepta conexiones entrantes. Esta es la diferencia principal frente a la versión PHP anterior (`legacy-php/`), que sí exponía un endpoint HTTP.
- **Apertura de enlaces**: los enlaces de Teams y el botón de donación solo se abren si usan `http://` o `https://` (`timermeet_app/security.py::is_http_url`); cualquier otro esquema (`file://`, `javascript:`, esquemas de apps personalizadas) se rechaza.
- **Persistencia**: toda escritura a `data/*.json` es atómica (archivo temporal + reemplazo) para evitar corrupción ante un cierre abrupto o un conflicto de sincronización de OneDrive.
- **Datos corruptos**: un `data/meetings.json` ilegible se pone en cuarentena (se renombra, nunca se borra) y la app arranca con una lista vacía en vez de fallar. Cada valor individual leído de `data/settings.json` (idioma, posición/tamaño/skin del modo gadget, modo de columnas de la semana, etc.) se valida por separado antes de usarse -- un valor ausente, del tipo incorrecto, o un `NaN`/`Infinity` (el módulo `json` de Python acepta esas dos extensiones no estándar al leer, aunque nunca las escribe) cae a su valor por defecto en vez de tumbar el arranque.
- **Sin `eval`/`exec`/`pickle`/comandos de shell con entrada variable**: la única llamada a `subprocess` en todo el proyecto vive en `build_exe.py`, con una lista de argumentos fija (sin `shell=True`, sin entrada de usuario).
- **Dependencias**: se auditan con `pip-audit` antes de cada release; ver `.claude/skills/timermeet-security-guardian`.
- **Análisis estático**: se revisa con `bandit` antes de cada release; los hallazgos aceptados quedan documentados inline con `# nosec B<código> - <motivo>`, nunca suprimidos en silencio.
- **Sin código firmado**: `TimerMeet.exe` no está firmado digitalmente (no existe un certificado de firma de código para este proyecto). Descarga el ejecutable únicamente desde este repositorio o sus Releases oficiales.
