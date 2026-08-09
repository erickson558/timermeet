# Security audit: reusable finder + verifier prompts

Base context to prepend to every finder prompt (update the last sentence with whatever's specific to the current ask, e.g. "the user just asked X" or "this audit follows the vX.Y.Z release" -- leave the rest as-is):

> TimerMeet is a Python/tkinter desktop app (repo root: this project) that reminds a single local user of Microsoft Teams meetings. It's a local, single-user, no-server desktop app. Data lives in `data/meetings.json` and `data/settings.json` (a shared file some users sync between two PCs via OneDrive, merged on save). It plays sound via Windows MCI (ctypes/winmm.dll) or `winsound.Beep`, shows OS notifications via `plyer`, has a system tray icon via `pystray`, opens Teams links via `webbrowser.open()` gated by `security.is_http_url()`, and ships a PyInstaller `--onefile` Windows `.exe` (currently unsigned, disclosed in `SECURITY.md`). Read `SECURITY.md` first for the project's own stated threat model and existing mitigations before hunting for gaps in it. This is a READ-ONLY investigation -- do not modify any file.

## Finder 1 — URLs and data-field trust boundary

Focus: the trust boundary around data that can arrive from a shared/synced `meetings.json` (potentially edited by another PC, another person with OneDrive access, or a corrupted/malicious sync conflict) and eventually gets acted on by the app.

1. Read `timermeet_app/security.py::is_http_url()` in full and determine EXACTLY which URL schemes it accepts. Then read every call site (`grep` for `is_http_url` and for `webbrowser.open` across the whole repo) and confirm the gate is applied consistently before every browser-opening call, no bypass path. Try to construct a URL that passes `is_http_url()` but does something unexpected when opened (scheme confusion, control characters, UNC-style path disguised as http).
2. Read `models.py::normalize_meeting()`/`validate_meeting()` and confirm every field that later reaches a file path, a command, or a native API (`soundProfile` -> `audio.py`, any field reaching `notifications.py`) is validated against a strict allow-list (not just length-clamped) before use.
3. Check `notifications.py` (plyer wrapper): does it pass raw, attacker-influenceable text (title/body) directly into an OS API that could interpret it as markup/XML/script, rather than plain text?
4. Check for path traversal: any data-derived string concatenated/formatted into a filesystem path without validation.

## Finder 2 — File I/O and persistence

1. Read `timermeet_app/storage.py` and `security.py::atomic_write_text()` for TOCTOU races, symlink-following, or predictable-temp-file issues a malicious local process (or compromised sync partner) could exploit.
2. Read the corrupt-JSON quarantine path -- confirm a malformed `meetings.json` only ever degrades safely (quarantine + empty list), never an uncontrolled crash, an eval/exec of file content, or a resource-exhaustion issue (huge file, deeply nested JSON, duplicate-key tricks).
3. Check the advisory lock file (`meetings.lock`) -- could a malicious local actor hold it to deny service, or is its absence/corruption ever handled unsafely?
4. Grep the ENTIRE codebase for `eval(`, `exec(`, `pickle.`, `os.system(`, `os.popen(`, `subprocess.` with `shell=True`, unsafe `yaml.load(`, and any dynamic import/`getattr` based on data-derived strings.
5. Check file permissions on `data/*.json`/lock/temp files -- overly permissive on a shared/multi-user machine?

## Finder 3 — Dependencies and build/supply-chain

1. Actually run `pip-audit -r requirements.txt` and `-r requirements-dev.txt`, report the raw output (exact versions checked), not a paraphrase.
2. Read `requirements.txt`/`requirements-dev.txt` -- pinned exactly, loosely, or unpinned? Assess the concrete supply-chain risk for THIS project's actual pins.
3. Read `build_exe.py` -- research whether the pinned PyInstaller version's `--onefile` extraction behavior is vulnerable to DLL side-loading or a predictable-extraction-path attack (a real historical PyInstaller CVE class).
4. Confirm the shipped `.exe`'s unsigned status is accurately and adequately disclosed in `SECURITY.md`.
5. Check for `.github/workflows` -- if present, does it run untrusted PR code with secrets access, use overly broad token permissions, or pull unpinned/non-SHA-pinned third-party actions?

## Finder 4 — Code-execution sweep

1. Run `python -m bandit -r timermeet_app timermeet.py build_exe.py -f txt` yourself, report the FULL raw output. For every existing `# nosec` suppression (`grep -rn nosec`), independently judge whether it's still justified -- don't just trust a prior suppression.
2. Grep the whole repo for any f-string/`.format()`/`%` interpolation building a shell command, path, or ctypes call from data ultimately originating in `meetings.json`/`settings.json`.
3. Check `audio.py`'s MCI command-string construction specifically (MCI strings are a real historical Windows injection vector) -- confirm MP3 paths in MCI commands are always from a fixed, validated, hardcoded set, never data-derived.
4. Check `tray_icon.py` (pystray) -- does it load the tray icon from a fixed bundled path only, or could a data-derived path ever reach Pillow's `Image.open`?

## Finder 5 — OS integration surface

1. Read `tray_icon.py` in full -- verify EVERY pystray callback (it runs on a background thread) is wrapped in `root.after(0, ...)` before touching Tkinter, per this project's own documented convention. A callback that skips this isn't just a reliability bug in a native GUI toolkit.
2. Read `notifications.py` -- does it degrade safely if the Windows notification API is unavailable/denied/returns malformed data? Could an unusually long title cause a buffer-handling issue in the native call?
3. Does the app listen on any port/socket, or expose any local IPC surface (named pipe, shared memory, registered URL protocol handler) another local process could reach?
4. Does the app ever request elevated privileges, or write outside its own user-writable folder (Program Files, registry Run keys) in a way that's a privilege-escalation vector if unprotected?
5. Could the alarm/reminder UI be spoofed by another local process (window-title/class-name mimicry) to phish the user?

## Adversarial verifier prompt (run 2 independent copies per candidate finding, in parallel)

> You are an adversarial security skeptic reviewing a candidate vulnerability finding in TimerMeet, a local single-user Python/tkinter desktop app. Your job is to try to REFUTE this finding -- default to `real=false`/`exploitable_in_practice=false` if you cannot personally verify the claim by reading the actual code yourself. Read the exact file/line cited and the surrounding code, and judge honestly whether this is genuinely exploitable in THIS app's real usage (single local user, no server, no untrusted network input) or a theoretical/non-issue given this app's actual threat model.
>
> Candidate finding: [title / file:line / description / claimed attack scenario / claimed severity]
>
> Report whether this is real, your reasoning (cite the actual code you read), and whether it's exploitable in practice given this app's real single-user-local-desktop threat model.

A finding is **confirmed** only if both independent verifiers agree it's real. Split verdicts are **disputed** (report the disagreement, don't silently pick a side). Neither agreeing is **refuted**.
