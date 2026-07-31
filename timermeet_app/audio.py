"""Sound alarms: local MP3 sirens with a synthesized-tone fallback.

Ported from ``legacy-php/assets/app.js``'s five sound profiles (soft/urgent/
alarm/siren/fire). The original used the Web Audio API to synthesize square/
sawtooth tones with millisecond envelopes and looped MP3 sub-clips; a desktop
process has no clean equivalent for either, so this module makes two
deliberate, documented simplifications:

- ``siren``/``fire`` loop the *whole* MP3 file from the start via
  ``pygame.mixer`` instead of the original's sample-accurate
  ``loopStart``/``loopEnd`` sub-clip — still a continuous, loud siren, just
  not byte-identical looping.
- the synthesized fallback uses ``winsound.Beep`` (frequency + duration only —
  no waveform shape or volume envelope, which a PC-speaker-style beep can't
  do), playing each tone in the pattern back-to-back on a background thread
  so the UI thread never blocks.

A failing/missing MP3 always falls back to the synth beep pattern — for an
alarm app, silence is never an acceptable failure mode.
"""

from __future__ import annotations

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
    import pygame
except ImportError:  # pragma: no cover - optional dependency
    pygame = None


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
    """Owns the mixer and whichever sound (MP3 channel or synth thread) is
    currently playing. A new call to `play()` always stops the previous
    sound first -- alarms replace rather than stack, matching the original."""

    def __init__(self) -> None:
        self._mixer_ready = False
        if pygame is not None:
            try:
                pygame.mixer.init()
                self._mixer_ready = True
            except Exception as exc:  # audio device issues must never crash the app
                logger.warning("Could not initialize audio mixer: %s", exc)
        self._sounds: Dict[str, "pygame.mixer.Sound"] = {}
        self._active_channel = None
        self._synth_stop_event: Optional[threading.Event] = None

    def _load_sound(self, profile: SoundProfile):
        if not self._mixer_ready or not profile.asset_key:
            return None
        if profile.asset_key in self._sounds:
            return self._sounds[profile.asset_key]
        path = _asset_path(profile.asset_filename)
        try:
            sound = pygame.mixer.Sound(str(path))
        except Exception as exc:  # a bad/missing mp3 must fall back, never crash
            logger.warning("Could not load alarm asset %s: %s", path, exc)
            return None
        self._sounds[profile.asset_key] = sound
        return sound

    def stop(self) -> None:
        if self._synth_stop_event is not None:
            self._synth_stop_event.set()
            self._synth_stop_event = None
        if self._active_channel is not None:
            try:
                self._active_channel.stop()
            except Exception:  # nosec B110 - channel may already be stopped/invalid; stop() must not raise
                pass
            self._active_channel = None

    def play(self, profile_id: str, mode: str, loop: bool = False) -> None:
        """Play one profile/mode. ``loop=True`` is a live alarm (keeps going
        until `stop()`); ``loop=False`` is a one-shot preview/test."""
        self.stop()
        profile = SOUND_PROFILES.get(profile_id, SOUND_PROFILES[DEFAULT_PROFILE_ID])
        sound = self._load_sound(profile)
        if sound is not None:
            try:
                self._active_channel = sound.play(loops=-1 if loop else 0)
                return
            except Exception as exc:
                logger.warning("Could not play alarm asset for %s: %s", profile_id, exc)

        self._play_synth_pattern(profile, mode, loop)

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


def preload(profile_ids: Optional[List[str]] = None) -> None:
    """Best-effort warm-up so the first real alarm doesn't stall on disk I/O.
    Failures are swallowed -- `AlarmPlayer.play()` already falls back safely."""
    player = AlarmPlayer()
    for profile_id in profile_ids or ("siren", "fire"):
        profile = SOUND_PROFILES.get(profile_id)
        if profile and profile.asset_key:
            player._load_sound(profile)
