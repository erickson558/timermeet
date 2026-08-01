"""Best-effort native OS toast notifications via ``plyer``.

Never allowed to raise or block: the alarm's sound + always-on-top overlay
(see ``alarm_ui.py``) are the load-bearing alert mechanisms and always fire
regardless of this module's outcome. This is a bonus channel only, unlike the
original web app's browser Notification permission flow.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Imported lazily (on first real use), not at module load time, so this
# module costs nothing on the startup critical path.
_plyer_notification = None
_plyer_import_failed = False


def _get_plyer_notification():
    global _plyer_notification, _plyer_import_failed
    if _plyer_notification is None and not _plyer_import_failed:
        try:
            from plyer import notification as _notification

            _plyer_notification = _notification
        except Exception:  # plyer or its platform backend may be unavailable
            _plyer_import_failed = True
    return _plyer_notification


def is_supported() -> bool:
    return _get_plyer_notification() is not None


def notify(title: str, message: str) -> bool:
    """Fire a native OS notification. Returns whether it succeeded -- callers
    may surface that to the user, but must never treat failure as fatal."""
    plyer_notification = _get_plyer_notification()
    if plyer_notification is None:
        return False
    try:
        plyer_notification.notify(title=title, message=message, app_name="TimerMeet", timeout=10)
        return True
    except Exception as exc:
        logger.warning("Native notification failed: %s", exc)
        return False
