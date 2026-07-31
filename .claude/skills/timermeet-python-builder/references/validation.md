# TimerMeet validation commands

Run from the repository root (where `timermeet.py` lives).

## Syntax check

```powershell
python -m py_compile timermeet.py timermeet_app/*.py build_exe.py
```

## Unit tests (recurrence, merge, i18n, models -- no GUI/audio device needed)

```powershell
python -m unittest discover -s tests -v
```

All tests must pass. If you touched `recurrence.py` or `storage.py`, pay special attention to the idempotency and merge tests -- those cover the highest-regression-risk logic in the app.

## Manual smoke test (when UI/alarm behavior changed)

```powershell
python timermeet.py
```

Confirm the window opens without an exception in `data/timermeet.log`, then close it. This does not verify sound/visuals by ear/eye -- flag to the user that they should confirm those manually after a UI/audio change.

## Security checks (before a release -- see the `timermeet-security-guardian` skill for the full checklist)

```powershell
python -m bandit -r timermeet_app timermeet.py build_exe.py -f txt
python -m pip_audit -r requirements.txt
```

## Rebuilding the .exe (when shipping a compiled binary -- see `timermeet-exe-packager`)

```powershell
python build_exe.py
```
