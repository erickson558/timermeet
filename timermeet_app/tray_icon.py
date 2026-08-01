"""System tray icon ("modo tray"): hide the window entirely and keep only a
taskbar-tray icon, built on `pystray`.

Imported lazily (only when tray mode is actually used, never at startup) for
the same reason `audio.py`/`notifications.py` defer their own imports -- this
one is heavier than either (pystray itself is tiny, but it depends on
Pillow, ~15MB across 200+ files) and this app's startup time is a hard
constraint (see SDD.md).

`pystray.Icon.run()` blocks and drives its own Win32 message loop, so it
always runs on a background daemon thread here, never the Tkinter main
thread. Every callback passed in from `app.py` is expected to already be
wrapped in `root.after(0, ...)` by the caller -- this module has no idea
Tkinter exists and never touches a widget directly, exactly so it can be
invoked safely from pystray's own thread.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_pystray_module = None
_pystray_import_failed = False


def _get_pystray():
    global _pystray_module, _pystray_import_failed
    if _pystray_module is None and not _pystray_import_failed:
        try:
            import pystray

            _pystray_module = pystray
        except Exception as exc:  # pystray/Pillow missing, or no tray support on this system
            logger.warning("pystray unavailable, tray mode disabled: %s", exc)
            _pystray_import_failed = True
    return _pystray_module


class TrayIcon:
    """Owns the single tray icon for the app's lifetime, built lazily on
    first use and reused (just toggling visibility) after that."""

    def __init__(
        self,
        icon_path: Path,
        tooltip: str,
        on_restore: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._icon_path = icon_path
        self._tooltip = tooltip
        self._on_restore = on_restore
        self._on_exit = on_exit
        self._icon = None  # pystray.Icon, created on first show()

    def is_available(self) -> bool:
        return _get_pystray() is not None

    def set_tooltip(self, tooltip: str) -> None:
        self._tooltip = tooltip
        if self._icon is not None:
            try:
                self._icon.title = tooltip
            except Exception:  # nosec B110 - cosmetic only; never worth failing over
                pass

    def is_visible(self) -> bool:
        return self._icon is not None and bool(self._icon.visible)

    def show(self, restore_label: str, exit_label: str) -> bool:
        """Create (first call) or re-show (later calls) the tray icon.
        Returns False if pystray/Pillow aren't available -- tray mode is
        best-effort, and callers must never leave the window hidden with no
        way back if this fails."""
        pystray = _get_pystray()
        if pystray is None:
            return False
        try:
            if self._icon is None:
                from PIL import Image

                image = Image.open(self._icon_path)
                menu = pystray.Menu(
                    pystray.MenuItem(restore_label, lambda: self._on_restore(), default=True),
                    pystray.MenuItem(exit_label, lambda: self._on_exit()),
                )
                icon = pystray.Icon("TimerMeet", image, self._tooltip, menu)
                # run_detached(), not run() on a manually-spawned thread:
                # pystray's own docs say run() "must be called from the main
                # thread" -- Tkinter's mainloop already occupies that role
                # here, so run_detached() (designed exactly for integrating
                # with another library's own mainloop) is the correct call;
                # it manages the icon's Win32 message loop on its own
                # internal thread and returns immediately.
                icon.run_detached()
                self._icon = icon
            else:
                self._icon.visible = True
        except Exception as exc:  # defensive -- a broken tray icon must never strand the user
            logger.warning("Could not show the tray icon: %s", exc)
            return False
        return True

    def hide(self) -> None:
        if self._icon is not None:
            try:
                self._icon.visible = False
            except Exception:  # nosec B110 - best-effort, mirrors AlarmController's teardown style
                pass

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # nosec B110 - best-effort; process exit cleans up the daemon thread regardless
                pass
            self._icon = None
