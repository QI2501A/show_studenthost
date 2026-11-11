"""voicefx.py -- audio effects applied to the chatbot's TTS output.

The stock Windows (SAPI5) voice is clean and friendly, so for the two moments
that need to sound wrong, Dialogue.py renders the line to a WAV, runs it
through one of these, and plays the result:

  rogue_voice(...)         "The system has taken over" -- slower, deeper,
                           doubled with a much lower copy, ring-modulated,
                           distorted, glitch-stuttered and echoing.

  dying_transformer(...)   The commands read out while control is regained --
                           a machine losing power (pitch and speed sag, motor
                           wobble) while being overwritten by code: bit-crush
                           and sample-hold that worsen over the line, ring-mod
                           that takes over the voice, dropouts, stutters,
                           static, data chirps, and a power-down sweep.

Needs numpy (optional dependency -- Dialogue.py falls back to the plain voice,
just slower, if it is missing). All functions take and return mono float32
arrays in [-1, 1] at the same sample rate.
"""
from __future__ import annotations

import wave

import numpy as np


# --------------------------------------------------------------------------- wav io

def read_wav(path: str):
    """Returns (float32 mono samples, sample_rate), or (None, 0) if the file
    isn't a PCM format we handle."""
    with wave.open(path, "rb") as w:
        channels, width, rate, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(frames)
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        return None, 0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def write_wav(path: str, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.tobytes())


# --------------------------------------------------------------------------- helpers

def _normalise(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.max(np.abs(x))) if x.size else 0.0
    return x * (peak / m) if m > 1e-6 else x


def trim_silence(x: np.ndarray, sr: int, threshold: float = 0.015, pad_s: float = 0.04) -> np.ndarray:
    """Cuts the dead air SAPI leaves before/after the speech, so effects (which
    stretch time) don't multiply it into long awkward gaps."""
    loud = np.flatnonzero(np.abs(x) > threshold)
    if loud.size == 0:
        return x
    pad = int(sr * pad_s)
    return x[max(0, loud[0] - pad): loud[-1] + pad + 1]


def _resample_const(x: np.ndarray, rate: float) -> np.ndarray:
    """Plays x at `rate` x speed with the pitch following it (rate < 1 =
    slower AND lower, like a tape slowing down)."""
    n = x.size
    out_len = max(1, int((n - 1) / rate))
    return np.interp(np.arange(out_len) * rate, np.arange(n), x).astype(np.float32)


def _time_fit(y: np.ndarray, target_len: int, sr: int, grain_s: float = 0.04) -> np.ndarray:
    """Stretches/squeezes y to exactly target_len samples WITHOUT changing its
    pitch (simple windowed overlap-add). Used to keep a pitched-down layer
    lined up with the main voice instead of trailing it."""
    if y.size < 8 or target_len < 8:
        return y
    grain = max(64, int(sr * grain_s))
    hop_out = grain // 2
    hop_in = hop_out * (y.size - grain) / max(1, target_len - grain) if y.size > grain else hop_out
    window = np.hanning(grain).astype(np.float32)
    out = np.zeros(target_len + grain, dtype=np.float32)
    norm = np.zeros(target_len + grain, dtype=np.float32)
    k = 0
    while True:
        o = k * hop_out
        i0 = int(k * hop_in)
        if o >= target_len or i0 + grain > y.size:
            break
        out[o: o + grain] += y[i0: i0 + grain] * window
        norm[o: o + grain] += window
        k += 1
    norm[norm < 1e-3] = 1.0
    return (out / norm)[:target_len]


def _mix(a: np.ndarray, b: np.ndarray, gain_b: float) -> np.ndarray:
    out = np.zeros(max(a.size, b.size), dtype=np.float32)
    out[: a.size] += a
    out[: b.size] += b * gain_b
    return out


def _echo(x: np.ndarray, sr: int, taps) -> np.ndarray:
    out = np.concatenate([x, np.zeros(int(sr * max(d for d, _ in taps)) + 1, dtype=np.float32)])
    for delay, gain in taps:
        k = int(sr * delay)
        out[k: k + x.size] += x * gain
    return out


def _stutter(y: np.ndarray, sr: int, rng: np.random.Generator, count: int,
             grain_s=(0.03, 0.07), bias: float = 0.0) -> np.ndarray:
    """Repeats a tiny slice of the audio a few times -- a skipping/glitching
    effect. `bias` pushes the glitches later in the clip (0 = anywhere)."""
    for _ in range(count):
        if y.size < sr // 4:
            break
        lo = 0.1 + 0.5 * bias
        start = int(y.size * rng.uniform(lo, 0.9))
        g = int(sr * rng.uniform(*grain_s))
        reps = int(rng.integers(2, 5))
        y = np.concatenate([y[:start], np.tile(y[start: start + g], reps), y[start + g:]])
    return y


# --------------------------------------------------------------------------- the effects

def rogue_voice(x: np.ndarray, sr: int, seed=None) -> np.ndarray:
    """A deeper, slower, doubled, distorted voice -- the machine that has
    decided it is in charge."""
    rng = np.random.default_rng(seed)
    x = trim_silence(x, sr)
    low = _resample_const(x, 0.80)
    deep = _time_fit(_resample_const(x, 0.58), low.size, sr)   # much lower, but kept in step with the words
    y = _mix(low, deep, 0.65)                       # the same voice, with something much bigger under it
    t = np.arange(y.size) / sr
    y = y * 0.72 + y * np.sin(2 * np.pi * 47.0 * t) * 0.28   # slow ring-mod: a metallic growl
    y = _stutter(y, sr, rng, count=3)
    y = np.tanh(2.6 * _normalise(y, 0.85))          # drive into soft clipping
    y = _echo(y, sr, [(0.11, 0.36), (0.24, 0.22), (0.41, 0.12)])
    return _normalise(y).astype(np.float32)


def dying_transformer(x: np.ndarray, sr: int, intensity: float = 0.5, seed=None) -> np.ndarray:
    """A giant machine powering down while code overwrites it. `intensity`
    (0..1) is how far gone it is -- the caller raises it across successive
    lines so the corruption builds through the whole readout."""
    i = float(np.clip(intensity, 0.0, 1.0))
    rng = np.random.default_rng(seed)
    x = trim_silence(x, sr)
    n = x.size
    if n < 64:
        return x

    # 1. Power-down: playback speed decays through the line (starts at normal
    #    speed, ends at roughly half of it), with a motor wobble that grows.
    a = 1.22 + 0.10 * i
    b = a - 1.0
    total = int(n * a)
    t = np.arange(total)
    u = t / total
    pos = n * (a * u - b * u * u)
    pos = pos + sr * 0.0025 * np.sin(2 * np.pi * 6.5 * t / sr) * (0.3 + u * (0.7 + i))
    y = np.interp(np.clip(pos, 0, n - 1), np.arange(n), x).astype(np.float32)

    # 2. Digital decay: sample-and-hold and bit depth both get worse as it goes.
    hold = 1 + (u * (2 + 9 * i)).astype(int)
    y = y[t - (t % hold)]
    bits = np.clip(12 - u * (5 + 6 * i), 3, 12)
    levels = 2.0 ** (bits - 1)
    y = np.round(y * levels) / levels

    # 3. Code taking over: a ring-modulation carrier that climbs in pitch and
    #    takes over more and more of the signal.
    carrier_hz = 70 + 260 * u
    phase = 2 * np.pi * np.cumsum(carrier_hz) / sr
    mix = (0.08 + 0.55 * i) * np.power(u, 0.8)
    y = y * (1 - mix) + y * np.sin(phase) * mix

    # 4. Dropouts and stutters -- more of both the further gone it is.
    for _ in range(int(2 + 8 * i)):
        start = int(total * rng.uniform(0.1, 0.95))
        length = int(sr * rng.uniform(0.015, 0.06))
        y[start: start + length] *= rng.choice([0.0, 0.12])
    y = _stutter(y, sr, rng, count=int(1 + 3 * i), grain_s=(0.02, 0.05), bias=0.6)
    total = y.size

    # 5. Static, crackle and "code" chirps.
    hiss = np.diff(rng.normal(0, 1, total), prepend=0).astype(np.float32)
    ramp = np.linspace(0.3, 1.0, total, dtype=np.float32)
    y = y + hiss * 0.02 * ramp * (0.5 + i)
    crackle = rng.random(total) < 0.0008 * (1 + 4 * i)
    y[crackle] += rng.uniform(-0.8, 0.8, int(crackle.sum())).astype(np.float32)
    for _ in range(int(2 + 5 * i)):
        c_len = int(sr * rng.uniform(0.02, 0.035))
        c_start = int(total * rng.uniform(0.05, 0.98))
        freq = rng.uniform(900, 3200)
        env = np.linspace(1.0, 0.0, c_len, dtype=np.float32)
        chirp = np.sign(np.sin(2 * np.pi * freq * np.arange(c_len) / sr)) * env * 0.12
        end = min(total, c_start + c_len)
        y[c_start:end] += chirp[: end - c_start]

    y = _normalise(y, 0.8)

    # 6. The last gasp: a falling power-down whine and a puff of static,
    #    overlapping the end of the line.
    tail_len = int(sr * 0.45)
    tt = np.arange(tail_len) / sr
    freq = 40 + 700 * np.exp(-6.0 * tt)
    ph = 2 * np.pi * np.cumsum(freq) / sr
    saw = 2 * ((ph / (2 * np.pi)) % 1.0) - 1
    tone = (0.5 * saw + 0.5 * np.sin(ph)) * np.exp(-3.5 * tt) * (0.28 + 0.25 * i)
    puff = np.diff(rng.normal(0, 1, tail_len), prepend=0) * np.exp(-9.0 * tt) * 0.06
    out = np.concatenate([y, np.zeros(tail_len, dtype=np.float32)])
    overlap = int(sr * 0.12)
    s = total - overlap
    out[s: s + tail_len] += (tone + puff).astype(np.float32)
    return _normalise(out).astype(np.float32)
