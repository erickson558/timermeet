# TimerMeet hardening checklist

Walk this before every tag/release, and after any change touching file I/O, URL handling, subprocess, or dependencies.

- [ ] Every call to `webbrowser.open()` is preceded by `security.is_http_url()`. Verify with:
      `grep -rn "webbrowser.open" timermeet_app` -- there should be no call site that skips the check.
- [ ] No `eval`, `exec`, `pickle`, `os.system`, or a `subprocess`/`os.popen` call built from a shell string with variable input.
      `build_exe.py`'s fixed-argument-list `subprocess.run(..., check=True)` is the one reviewed exception (see its inline `# nosec` comments) -- don't add a second, less-reviewed one.
- [ ] Every write to `data/*.json` goes through `security.atomic_write_text()` (directly, or via `storage.save_meetings()`/`storage.save_settings()`). No bare `open(path, "w")` on a data file anywhere.
- [ ] User-supplied text (`workName`, `title`, `notes`, `teamsUrl`) is clamped through `security.clamp_text()` with the same limits as the legacy web form before being persisted.
- [ ] `storage.load_meetings()` still quarantines (renames aside) an unreadable/corrupt `meetings.json` instead of crashing or silently deleting user data.
- [ ] Any new third-party dependency is listed explicitly in `requirements.txt` or `requirements-dev.txt` and passes `pip_audit`.
- [ ] The Tkinter main thread is never blocked by network/file I/O or audio synthesis directly -- background thread or `root.after()`.
- [ ] `TimerMeet.exe` being committed to a public repo is a deliberate, known tradeoff (no code-signing certificate exists for this project) -- don't silently start distributing a differently-built or third-party-modified binary under the same filename without noting it in the release notes.
