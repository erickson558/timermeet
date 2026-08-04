"""Security-focused helpers shared across the app.

Kept in one module so a single review pass (see
``.claude/agents/timermeet-security-guardian.md``) can audit every place the
app touches the filesystem or opens an external URL.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Field length caps, mirrored from the legacy web form's HTML maxlength
# attributes (legacy-php/index.php) so the desktop UI enforces the same limits.
MAX_WORK_NAME_LENGTH = 80
MAX_TITLE_LENGTH = 120
MAX_TEAMS_URL_LENGTH = 300
MAX_NOTES_LENGTH = 400


def is_http_url(value: str) -> bool:
    """Return True only for ``http://``/``https://`` URLs.

    This is the single allow-list used everywhere a URL might be opened
    (Teams links, the alarm overlay, the donation button), so no other scheme
    (``file://``, ``javascript:``, a custom app scheme, ...) is ever handed to
    ``webbrowser.open()``.
    """
    if not value:
        return False
    return bool(_HTTP_URL_RE.match(value.strip()))


def clamp_text(value, max_length: int) -> str:
    """Trim and hard-cap a string field.

    Defends against oversized input even though the UI widgets already limit
    typed length — this is what the on-disk record and any future importer
    actually get validated against.
    """
    text = str(value if value is not None else "").strip()
    return text[:max_length]


def atomic_write_text(path: Path, data: str) -> None:
    """Write ``data`` to ``path`` atomically.

    Writes to a temp file in the same directory, flushes + fsyncs, then
    ``os.replace()``s it into place, so a crash mid-write (or a OneDrive sync
    snapshot taken at the wrong moment) can never observe a half-written file.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise
