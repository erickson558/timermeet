"""Build TimerMeet.exe with PyInstaller and drop it next to timermeet.py.

Usage: ``python build_exe.py``

Requires the dev dependencies (see requirements-dev.txt): PyInstaller, plus
the app's own runtime dependencies (pygame, plyer). See
``.claude/skills/timermeet-exe-packager/SKILL.md`` for the reasoning behind
each flag below.
"""

from __future__ import annotations

import shutil
import subprocess  # nosec B404 - only used below with a fixed argument list, no shell
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY_POINT = ROOT / "timermeet.py"
ICON_PATH = ROOT / "computer_pc_10894.ico"
APP_NAME = "TimerMeet"


def main() -> None:
    if not ICON_PATH.exists():
        raise SystemExit(f"Icon not found: {ICON_PATH}")

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--icon",
        str(ICON_PATH),
        # plyer picks its OS backend (plyer.platforms.win.notification) via
        # a runtime string import that PyInstaller's static analysis can't
        # see, so it has to be told to include all of plyer's submodules.
        "--collect-submodules",
        "plyer",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT),
        str(ENTRY_POINT),
    ]
    # nosec B603/B404 - `command` is a fixed argument list built entirely from
    # constants above (no shell, no untrusted/user-supplied input); this is
    # the documented safe subprocess pattern bandit expects to see reviewed.
    subprocess.run(command, check=True, cwd=ROOT)  # nosec B603

    built_exe = ROOT / "dist" / f"{APP_NAME}.exe"
    if not built_exe.exists():
        raise SystemExit(f"Expected build output not found: {built_exe}")

    target_exe = ROOT / f"{APP_NAME}.exe"
    shutil.copy2(built_exe, target_exe)
    print(f"Built {target_exe}")
    print("Remember: assets/audio/ and data/ must stay next to TimerMeet.exe")
    print("(they're read as loose files at runtime, not bundled into the .exe).")


if __name__ == "__main__":
    main()
