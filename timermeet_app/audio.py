"""Sound alarms: local MP3 sirens with a synthesized-tone fallback.

Ported from ``legacy-php/assets/app.js``'s five sound profiles (soft/urgent/
alarm/siren/fire). The original used the Web Audio API to synthesize square/
sawtooth tones with millisecond envelopes and looped MP3 sub-clips; a desktop
process has no clean equivalent for either, so this module makes two
deliberate, documented simplifications:

- ``siren``/``fire`` loop the *whole* MP3 file from the start via Windows'
  built-in MCI audio API (``winmm.dll``, accessed through ``ctypes`` --
  stdlib only, nothing to bundle) instead of the original's sample-accurate
  ``loopStart``/``loopEnd`` sub-clip — still a continuous, loud siren, just
  not byte-identical looping. An earlier version used ``pygame.mixer`` for
  this; it was replaced because pygame bundles ~24MB/730 files that a
  PyInstaller ``--onefile`` build must re-extract on every launch, which was
  a meaningful chunk of the app's startup time for a feature (MP3 playback)
  that ``winmm.dll`` already provides for free on every Windows install.
- the synthesized fallback uses ``winsound.Beep`` (frequency + duration only —
  no waveform shape or volume envelope, which a PC-speaker-style beep can't
  do), playing each tone in the pattern back-to-back on a background thread
  so the UI thread never blocks.

A failing/missing MP3 always falls back to the synth beep pattern — for an
alarm app, silence is never an acceptable failure mode.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import storage

logger = logging.getLogger(__name__)

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows dev environments
    winsound = None

try:
    _winmm = ctypes.windll.winmm  # pragma: no cover - Windows-only
except (AttributeError, OSError):  # pragma: no cover - non-Windows dev environments
    _winmm = None

_MCI_ALIAS = "timermeet_alarm"


def _mci_send(command: str) -> Tuple[int, str]:
    """Send one MCI command string via winmm.dll. Returns (error_code, reply)
    -- error_code is 0 on success. Never raises: a missing/unavailable MCI
    subsystem just means every call below returns a failure code, which the
    caller already treats as "fall back to the synth tone"."""
    if _winmm is None:
        return -1, ""
    buffer = ctypes.create_unicode_buffer(255)
    try:
        error_code = _winmm.mciSendStringW(command, buffer, 254, 0)
    except Exception as exc:  # defensive -- must never crash the alarm thread
        logger.warning("MCI command failed (%s): %s", command, exc)
        return -1, ""
    return error_code, buffer.value


def _mci_open(path: str) -> bool:
    error_code, _ = _mci_send(f'open "{path}" type mpegvideo alias {_MCI_ALIAS}')
    return error_code == 0


def _mci_close() -> None:
    _mci_send(f"close {_MCI_ALIAS}")


def _mci_play_from_start() -> bool:
    error_code, _ = _mci_send(f"play {_MCI_ALIAS} from 0")
    return error_code == 0


def _mci_length_ms() -> int:
    _, value = _mci_send(f"status {_MCI_ALIAS} length")
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _mci_stop() -> None:
    _mci_send(f"stop {_MCI_ALIAS}")


@dataclass(frozen=True)
class SoundProfile:
    asset_key: Optional[str]
    asset_filename: Optional[str]
    repeat_delay_ms: Dict[str, int]
    patterns: Dict[str, List[Tuple[int, float]]]  # mode -> [(frequency_hz, duration_s), ...]


# Frequency/duration pairs below are transcribed from each profile's exact
# Web Audio tone pattern in assets/app.js (getSoundSettings); gain/oscillator
# shape are dropped since winsound.Beep has no volume or waveform control.
SOUND_PROFILES: Dict[str, SoundProfile] = {
    "soft": SoundProfile(
        asset_key=None,
        asset_filename=None,
        repeat_delay_ms={"start": 3600, "reminder": 5400},
        patterns={
            "start": [(980, 0.22), (820, 0.22), (980, 0.22), (820, 0.22)],
            "reminder": [(820, 0.22), (960, 0.22), (820, 0.22)],
        },
    ),
    "urgent": SoundProfile(
        asset_key=None,
        asset_filename=None,
        repeat_delay_ms={"start": 2600, "reminder": 3600},
        patterns={
            "start": [(1080, 0.2), (880, 0.2), (1080, 0.2), (880, 0.2), (1160, 0.2)],
            "reminder": [(900, 0.2), (1040, 0.2), (900, 0.2), (1040, 0.2)],
        },
    ),
    "alarm": SoundProfile(
        asset_key=None,
        asset_filename=None,
        repeat_delay_ms={"start": 2200, "reminder": 3000},
        patterns={
            "start": [(1160, 0.30), (920, 0.26), (1160, 0.30), (920, 0.26), (1320, 0.34)],
            "reminder": [(940, 0.26), (1120, 0.30), (940, 0.26), (1120, 0.30)],
        },
    ),
    "siren": SoundProfile(
        asset_key="siren",
        asset_filename="siren-noise-public-domain.mp3",
        repeat_delay_ms={"start": 1800, "reminder": 2400},
        patterns={
            "start": [(760, 0.28), (1320, 0.34), (760, 0.28), (1320, 0.34), (860, 0.30), (1380, 0.34)],
            "reminder": [(720, 0.24), (1220, 0.30), (720, 0.24), (1220, 0.30), (820, 0.26)],
        },
    ),
    "fire": SoundProfile(
        asset_key="fire",
        asset_filename="fire-engine-siren-real.mp3",
        repeat_delay_ms={"start": 1500, "reminder": 2100},
        patterns={
            "start": [
                (640, 0.26), (980, 0.34), (640, 0.26), (980, 0.34),
                (640, 0.28), (1080, 0.36), (640, 0.28), (1080, 0.36),
            ],
            "reminder": [(620, 0.24), (920, 0.30), (620, 0.24), (920, 0.30), (620, 0.26), (980, 0.32)],
        },
    ),
}

DEFAULT_PROFILE_ID = "soft"
AUDIO_SUBDIR = Path("assets") / "audio"


def _asset_path(filename: str) -> Path:
    return storage.base_dir() / AUDIO_SUBDIR / filename


def _beep(frequency_hz: int, duration_s: float) -> None:
    duration_ms = max(60, int(duration_s * 1000))
    if winsound is None:
        time.sleep(duration_ms / 1000)
        return
    try:
        winsound.Beep(int(frequency_hz), duration_ms)
    except RuntimeError as exc:
        # e.g. no sound device present -- keep the cadence going in silence
        # rather than raising and killing the alarm thread.
        logger.warning("winsound.Beep failed: %s", exc)
        time.sleep(duration_ms / 1000)


class AlarmPlayer:
    """Owns whichever sound (MP3 via MCI, or a synth thread) is currently
    playing. A new call to `play()` always stops the previous sound first --
    alarms replace rather than stack, matching the original. Only one MP3
    can be "open" under the shared MCI alias at a time, which is fine since
    only one alarm is ever active at once."""

    def __init__(self) -> None:
        self._mci_loaded_key: Optional[str] = None
        self._synth_stop_event: Optional[threading.Event] = None
        self._mci_loop_stop_event: Optional[threading.Event] = None

    def stop(self) -> None:
        if self._synth_stop_event is not None:
            self._synth_stop_event.set()
            self._synth_stop_event = None
        if self._mci_loop_stop_event is not None:
            self._mci_loop_stop_event.set()
            self._mci_loop_stop_event = None
        _mci_stop()

    def play(self, profile_id: str, mode: str, loop: bool = False) -> None:
        """Play one profile/mode. ``loop=True`` is a live alarm (keeps going
        until `stop()`); ``loop=False`` is a one-shot preview/test."""
        self.stop()
        profile = SOUND_PROFILES.get(profile_id, SOUND_PROFILES[DEFAULT_PROFILE_ID])
        if profile.asset_key and self._play_mp3(profile, loop):
            return
        self._play_synth_pattern(profile, mode, loop)

    def _play_mp3(self, profile: SoundProfile, loop: bool) -> bool:
        if self._mci_loaded_key != profile.asset_key:
            _mci_close()
            path = str(_asset_path(profile.asset_filename))
            if not _mci_open(path):
                self._mci_loaded_key = None
                logger.warning("Could not open alarm asset via MCI: %s", path)
                return False
            self._mci_loaded_key = profile.asset_key

        if not _mci_play_from_start():
            return False

        if loop:
            length_ms = _mci_length_ms()
            if length_ms <= 0:
                return False  # can't loop something we can't measure; let the synth pattern take over
            stop_event = threading.Event()
            self._mci_loop_stop_event = stop_event

            def _run() -> None:
                while not stop_event.is_set():
                    if stop_event.wait(timeout=length_ms / 1000):
                        return
                    if stop_event.is_set():
                        return
                    _mci_play_from_start()

            threading.Thread(target=_run, daemon=True).start()

        return True

    def _play_synth_pattern(self, profile: SoundProfile, mode: str, loop: bool) -> None:
        pattern = profile.patterns.get(mode) or profile.patterns["reminder"]
        repeat_delay_ms = profile.repeat_delay_ms.get(mode, 3000)
        stop_event = threading.Event()
        self._synth_stop_event = stop_event

        def _run() -> None:
            while not stop_event.is_set():
                pattern_start = time.monotonic()
                for frequency, duration_s in pattern:
                    if stop_event.is_set():
                        return
                    _beep(frequency, duration_s)
                if not loop:
                    return
                elapsed_ms = (time.monotonic() - pattern_start) * 1000
                stop_event.wait(timeout=max(0.0, (repeat_delay_ms - elapsed_ms) / 1000))

        threading.Thread(target=_run, daemon=True).start()


def preload(player: "AlarmPlayer", profile_ids: Optional[List[str]] = None) -> None:
    """Best-effort warm-up: just confirms each MP3 asset file exists so a
    missing file is logged early (on a background thread) rather than
    discovered silently at the moment an alarm needs it. Unlike the old
    pygame-based version, there's no persistent handle to keep "loaded" --
    MCI opens/closes per play() call -- so this is now a cheap sanity check,
    not a cache warm-up. Failures are swallowed -- `AlarmPlayer.play()`
    already falls back safely."""
    for profile_id in profile_ids or ("siren", "fire"):
        profile = SOUND_PROFILES.get(profile_id)
        if profile and profile.asset_key:
            path = _asset_path(profile.asset_filename)
            if not path.exists():
                logger.warning("Alarm asset missing: %s", path)
