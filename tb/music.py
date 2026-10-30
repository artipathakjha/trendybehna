"""Original background music for Reels, synthesised per deal: no licence, no download, and every Reel gets a
different key / tempo / progression (Instagram demotes accounts whose Reels repeat one template and one track).

Soft pad chords + Karplus-Strong plucked arpeggio + a light kick/shaker groove, mixed quietly under the visuals."""
from __future__ import annotations

import hashlib
import wave
from pathlib import Path

import numpy as np

SR = 48_000
KEYS = {"C": 261.63, "D": 293.66, "E": 329.63, "F": 349.23, "G": 392.00, "A": 220.00 * 2}
# chord roots as semitones above the key, major/minor triads (pop progressions that sit well under speech)
PROGRESSIONS = (
    ((0, "maj"), (7, "maj"), (9, "min"), (5, "maj")),   # I  V  vi IV
    ((9, "min"), (5, "maj"), (0, "maj"), (7, "maj")),   # vi IV I  V
    ((0, "maj"), (9, "min"), (5, "maj"), (7, "maj")),   # I  vi IV V
    ((0, "maj"), (5, "maj"), (9, "min"), (7, "maj")),   # I  IV vi V
)
TRIAD = {"maj": (0, 4, 7), "min": (0, 3, 7)}


def _hz(base: float, semis: float) -> float:
    return base * 2 ** (semis / 12)


def _env(n: int, attack: float, release: float) -> np.ndarray:
    e = np.ones(n)
    a, r = min(int(attack * SR), n), min(int(release * SR), n)
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[n - r:] *= np.linspace(1, 0, r)
    return e


def _pad(freqs: list[float], seconds: float) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    tone = sum(np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * f * 1.003 * t) for f in freqs)
    return tone / (1.5 * len(freqs)) * _env(len(t), 0.25, 0.35)


def _pluck(freq: float, seconds: float, rng: np.random.Generator) -> np.ndarray:
    """Karplus-Strong: a noise burst through a damped delay line, computed one period-block at a time."""
    n, period = int(seconds * SR), max(int(SR / freq), 2)
    y = np.zeros(n + period + 1)
    y[:period + 1] = rng.uniform(-1, 1, period + 1)
    for k in range(period + 1, n + period + 1, period):
        end = min(k + period, n + period + 1)
        y[k:end] = 0.996 * 0.5 * (y[k - period:end - period] + y[k - period - 1:end - period - 1])
    return y[period + 1:] * _env(n, 0.002, 0.05)


def _kick(seconds: float = 0.25) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return np.sin(2 * np.pi * (50 * t + 70 * (1 - np.exp(-t * 30)) / 30)) * np.exp(-t * 18)


def _shaker(rng: np.random.Generator, seconds: float = 0.06) -> np.ndarray:
    n = int(seconds * SR)
    noise = rng.uniform(-1, 1, n)
    return np.diff(noise, prepend=0) * np.exp(-np.arange(n) / SR * 60)  # diff = crude high-pass


def compose(seed: str, seconds: float) -> np.ndarray:
    """Stereo float32 array (n, 2) in [-1, 1], `seconds` long, deterministic for a given seed (the deal id)."""
    h = int(hashlib.sha1(seed.encode()).hexdigest(), 16)
    rng = np.random.default_rng(h % 2**32)
    key = list(KEYS.values())[h % len(KEYS)] / 2           # pad/pluck an octave down: warm, under the voice
    prog = PROGRESSIONS[(h // 7) % len(PROGRESSIONS)]
    bpm = 84 + (h // 31) % 17                               # 84-100 bpm
    beat = 60 / bpm
    n = int(seconds * SR)
    left, right = np.zeros(n), np.zeros(n)

    def add(sig: np.ndarray, at: float, gain: float, pan: float = 0.0) -> None:
        i = int(at * SR)
        if i >= n:
            return
        seg = sig[: n - i] * gain
        left[i:i + len(seg)] += seg * (1 - pan)
        right[i:i + len(seg)] += seg * (1 + pan)

    bar = 4 * beat
    for b in range(int(seconds / bar) + 1):
        root, kind = prog[b % len(prog)]
        chord = [_hz(key, root + s) for s in TRIAD[kind]]
        add(_pad(chord, bar), b * bar, 0.16)
        arp = chord + [chord[0] * 2, chord[1] * 2, chord[0] * 2, chord[2], chord[1]]
        for s in range(8):  # eighth-note arpeggio, alternating sides
            add(_pluck(arp[s] * 2, beat * 1.5, rng), b * bar + s * beat / 2, 0.22, pan=0.35 if s % 2 else -0.35)
        for q in range(4):
            if q in (0, 2):
                add(_kick(), b * bar + q * beat, 0.30)
            add(_shaker(rng), b * bar + q * beat + beat / 2, 0.05)
    mix = np.stack([left, right], axis=1)
    mix *= _env(n, 0.3, 1.0)[:, None]
    peak = np.max(np.abs(mix)) or 1.0
    return (mix / peak * 0.5).astype(np.float32)          # peak at -6 dBFS; ffmpeg ducks it further under a voice


def write_wav(samples: np.ndarray, path: Path) -> Path:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path
