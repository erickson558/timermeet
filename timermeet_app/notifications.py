"""Best-effort native OS toast notifications via ``plyer``.

Never allowed to raise or block: the alarm's sound + always-on-top overlay
(see ``alarm_ui.py``) are the load-bearing alert mechanisms and always fire
regardless of this module's outcome. This is a bonus channel only, unlike the
original web app's browser Notification permission flow.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from plyer import notification as _plyer_notification
except Exception:  # plyer or its platform backend may be unavailable
    _plyer_notification = None


def is_supported() -> bool:
    return _plyer_notification is not None


def notify(title: str, message: str) -> bool:
    """Fire a native OS notification. Returns whether it succeeded -- callers
    may surface that to the user, but must never treat failure as fatal."""
    if _plyer_notification is None:
        return False
    try:
        _plyer_notification.notify(title=title, message=message, app_name="TimerMeet", timeout=10)
        return True
    except Exception as exc:
        logger.warning("Native notification failed: %s", exc)
        return False
