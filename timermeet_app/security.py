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
from urllib.parse import urlsplit

_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Defense-in-depth alongside the scheme prefix check below: reject any URL
# carrying a raw control character (could confuse a downstream API/log line)
# or a quote character (a common injection primitive if this string is ever
# interpolated into another context, e.g. a shell/HTML/URI attribute) before
# it's ever considered "safe". Not currently reachable by any known input
# (every call site already re-validates and nothing untrusted feeds this
# directly), but cheap to close off.
_UNSAFE_CHAR_RE = re.compile(r'[\x00-\x1f"\']')

# Field length caps, mirrored from the legacy web form's HTML maxlength
# attributes (legacy-php/index.php) so the desktop UI enforces the same limits.
MAX_WORK_NAME_LENGTH = 80
MAX_TITLE_LENGTH = 120
MAX_TEAMS_URL_LENGTH = 300
MAX_NOTES_LENGTH = 400


def is_http_url(value: str) -> bool:
    """Return True only for structurally-valid ``http://``/``https://`` URLs.

    This is the single allow-list used everywhere a URL might be opened
    (Teams links, the alarm overlay, the donation button), so no other scheme
    (``file://``, ``javascript:``, a custom app scheme, ...) is ever handed to
    ``webbrowser.open()``. The scheme prefix check is confirmed with
    ``urllib.parse.urlsplit()`` (rather than trusting the prefix regex alone)
    and any embedded control/quote character rejects the URL outright.
    """
    if not value:
        return False
    # Check the unsafe-character set against the RAW input, before
    # str.strip() runs -- str.strip() (with no argument) removes not just
    # ordinary whitespace but also the ASCII "information separator"
    # control characters \x1c-\x1f (a CPython/Unicode quirk: they're
    # classified as whitespace), so a control character sitting at the very
    # start/end of the raw string used to be silently stripped away *before*
    # ever reaching this check, letting it slip through undetected. Ordinary
    # padding like " https://example.com " must still be accepted below --
    # plain space (0x20) is outside the \x00-\x1f range this regex covers,
    # so it's untouched by this reordering.
    if _UNSAFE_CHAR_RE.search(value):
        return False
    text = value.strip()
    if not _HTTP_URL_RE.match(text):
        return False
    try:
        scheme = urlsplit(text).scheme.lower()
    except ValueError:
        return False
    return scheme in ("http", "https")


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
