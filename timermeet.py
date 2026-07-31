"""TimerMeet entry point.

Run directly with ``python timermeet.py``, or build a standalone Windows
.exe with ``python build_exe.py`` (see that file for the exact PyInstaller
invocation, including the icon and bundled audio assets).
"""

import logging
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    _BASE_DIR = Path(sys.executable).resolve().parent
else:
    _BASE_DIR = Path(__file__).resolve().parent

_DATA_DIR = _BASE_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_DATA_DIR / "timermeet.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger("timermeet")


def main() -> None:
    # Imported here so the logging config above is guaranteed to be in
    # place before any module-level code in timermeet_app runs.
    from timermeet_app.app import TimerMeetApp

    try:
        app = TimerMeetApp()
        app.run()
    except Exception:
        # An alarm app must never fail silently -- log the crash and tell
        # the user, instead of just vanishing (the exact complaint that
        # motivated this rewrite, just applied to the app's own failures too).
        logger.exception("TimerMeet crashed")
        try:
            import tkinter.messagebox as messagebox

            messagebox.showerror(
                "TimerMeet",
                "TimerMeet encontró un error y debe cerrarse. Revisa data/timermeet.log para más detalles.",
            )
        except Exception:  # nosec B110 - best-effort dialog; the crash is already logged above
            pass
        raise


if __name__ == "__main__":
    main()
