# TimerMeet Python module map

| File | Owns | Don't put here |
|---|---|---|
| `timermeet_app/models.py` | `Meeting` dataclass, `normalize_meeting()`, `validate_meeting()` | UI text, persistence |
| `timermeet_app/recurrence.py` | Occurrence generation (`add_recurrence_to_date`), the Friday-18:00 weekly renewal engine (`run_weekly_series_renewal`) | Persistence, UI |
| `timermeet_app/retention.py` | Two cleanup functions: `purge_stale_meetings` (automatic, conservative -- 7-day grace, only fully-alerted) and `clear_past_meetings` (manual "delete past events" button -- immediate, ignores alert flags). Both always keep each series' latest occurrence | Persistence, UI, anything about *when* an alert fires (that's `app.py`) |
| `timermeet_app/storage.py` | Atomic JSON read/write, the same-machine advisory lock, merge-on-save (`merge_meeting_lists`/`merge_meeting_pair`), settings persistence (language, company list -- `load_companies`/`save_companies`, local to this machine, not merged like meetings) | Business rules about *when* to fire an alert (that's `app.py`) |
| `timermeet_app/audio.py` | The 5 sound profiles, MP3 playback via Windows MCI (`winmm.dll` through `ctypes`) with `winsound.Beep` synth fallback | UI widgets |
| `timermeet_app/notifications.py` | Best-effort native OS toast via `plyer` | Anything load-bearing -- this must never be relied on as the only alert channel |
| `timermeet_app/alarm_ui.py` | The one-shot alert dialog + persistent alarm overlay + title-bar blink (`AlarmController`) | Business logic about which meeting fires next (that's `app.py`) |
| `timermeet_app/main_window.py` | All widget construction and rendering (`MainWindow`) -- view layer only | Validation, persistence, stats computation |
| `timermeet_app/app.py` | The controller: heartbeat (`root.after` every 1s), alert firing gate, stats/next-alert computation, save/edit/delete handlers, resync-from-disk | Widget construction |
| `timermeet_app/i18n.py` | ES/EN translation dict, `t()`/`format_text()` | Anything not a translated string |
| `timermeet_app/security.py` | `is_http_url()`, `clamp_text()`, `atomic_write_text()`, the field-length constants | Anything unrelated to input safety/file safety |

When in doubt about where new logic belongs: business rules and computed state go in `app.py`; anything about one meeting's shape/validity goes in `models.py`; anything about the on-disk representation goes in `storage.py`; anything the user sees goes in `main_window.py` (rendered) driven by `i18n.py` (translated).
