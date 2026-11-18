"""Generates audio/rain_theme.ogg -- the background music for the digital-rain
chatbot portion (from SPACE on the welcome screen until the IGNITE video).

Pure numpy/scipy, no samples: a slow A-minor electronic bed (Am - F - C - G)
of detuned-saw pads, a deep sub bass, a soft heartbeat kick and a sparse
echoing arpeggio, at 96 BPM for 16 bars (40 s).

It loops seamlessly because EVERYTHING is rendered circularly: notes, the
echo and the reverb tail all wrap around the end of the buffer back to the
start, and the filters are applied in the frequency domain over the whole
loop, so the last sample flows straight into the first with no gap, click
or cut-off tail. (screen.html plays it as a Web Audio buffer with loop=true,
which is sample-accurate.)

    python make_rain_music.py            # writes audio/rain_theme.ogg
"""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve  # noqa: F401  (kept for experimenting with IRs)

SR = 44100
BPM = 96
BARS = 16
BEAT = 60.0 / BPM
N = int(round(BARS * 4 * BEAT * SR))
OUT = Path(__file__).resolve().parent / "audio"

rng = np.random.default_rng(7)


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def wrap_add(buf, start, sig):
    """Adds sig into buf at `start`, wrapping past the end back to 0."""
    n = len(sig)
    start %= len(buf)
    first = min(n, len(buf) - start)
    buf[start:start + first] += sig[:first]
    if first < n:
        rest = n - first
        while rest > 0:
            k = min(rest, len(buf))
            buf[:k] += sig[first:first + k]
            first += k
            rest -= k


def saw(freq, n, phase=0.0):
    t = (np.arange(n) / SR * freq + phase) % 1.0
    return 2 * t - 1


def env(n, a, r, hold_to=None):
    """Attack / sustain / release envelope over n samples."""
    e = np.ones(n)
    na = max(1, int(a * SR))
    nr = max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na) ** 2
    e[-nr:] *= np.linspace(1, 0, nr) ** 2
    return e


def circular_lowpass(x, cutoff_hz, slope=2.0):
    """Smooth frequency-domain lowpass over the whole (circular) loop."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    H = 1.0 / (1.0 + (f / cutoff_hz) ** (2 * slope))
    return np.fft.irfft(X * H, len(x))


def circular_highpass(x, cutoff_hz):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    H = 1.0 - 1.0 / (1.0 + (f / cutoff_hz) ** 4)
    return np.fft.irfft(X * H, len(x))


def circular_echo(x, delay_s, feedback, taps=6):
    out = x.copy()
    d = int(delay_s * SR)
    for i in range(1, taps + 1):
        out += np.roll(x, d * i) * feedback ** i
    return out


def circular_reverb(x, seconds=2.6, wet=0.35):
    """Convolves with an exponentially decaying noise burst *circularly*
    (FFT multiplication), so the tail wraps into the start of the loop."""
    n = len(x)
    ir_len = int(seconds * SR)
    t = np.arange(ir_len) / SR
    ir = rng.standard_normal(ir_len) * np.exp(-t * 3.2)
    ir = circular_lowpass(np.pad(ir, (0, n - ir_len)), 3500)[:ir_len]
    ir /= np.sqrt((ir ** 2).sum())
    IR = np.fft.rfft(ir, n)
    wetsig = np.fft.irfft(np.fft.rfft(x) * IR, n)
    return x * (1 - wet) + wetsig * wet * 2.2


# ---------------------------------------------------------------- the music
chords = [  # (root midi for bass, chord tones for pad)
    (45, [57, 60, 64, 67]),    # Am7
    (41, [53, 57, 60, 64]),    # Fmaj7
    (48, [55, 60, 64, 67]),    # C
    (43, [55, 59, 62, 67]),    # G
]
bar_s = 4 * BEAT
n_bar = int(round(bar_s * SR))

pad = np.zeros(N)
bass = np.zeros(N)
kick = np.zeros(N)
arp = np.zeros(N)
hats = np.zeros(N)

for bar in range(BARS):
    root, tones = chords[bar % 4]
    start = int(round(bar * bar_s * SR))
    seg = n_bar + int(1.2 * SR)  # a little overlap so chords cross-fade
    # pad: 3 detuned saws per tone, slow swell
    for tone in tones:
        for detune in (-0.07, 0.0, 0.07):
            f = midi(tone) * 2 ** (detune / 12)
            s = saw(f, seg, rng.random()) * env(seg, 0.9, 1.2) * 0.05
            wrap_add(pad, start, s)
    # sub bass: sine + a touch of 2nd harmonic, pulsing on beats 1 and 3
    for beat in (0, 2):
        nb = int(1.7 * BEAT * SR)
        t = np.arange(nb) / SR
        f = midi(root)
        s = (np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)) * env(nb, 0.02, 0.5) * 0.30
        wrap_add(bass, start + int(beat * BEAT * SR), s)
    # heartbeat kick on every beat 1 and the "and" of 3: pitch-dropping sine
    for off in (0.0, 2.5):
        nk = int(0.35 * SR)
        t = np.arange(nk) / SR
        ph = 2 * np.pi * (46 * t + 60 * (1 - np.exp(-t * 28)) / 28)
        s = np.sin(ph) * np.exp(-t * 11) * 0.34
        wrap_add(kick, start + int(off * BEAT * SR), s)
    # arpeggio: 8th notes, a rising/falling pattern over the chord an octave up
    pattern = [0, 2, 1, 3, 2, 1, 3, 2]
    if bar % 4 == 3:
        pattern = [3, 2, 1, 0, 1, 2, 3, 2]
    for i, p in enumerate(pattern):
        if bar % 2 == 0 and i % 2 == 1 and bar % 8 < 4:
            continue  # leave air in the first half of each 8 bars
        tone = tones[p] + 12
        na = int(0.7 * SR)
        t = np.arange(na) / SR
        f = midi(tone)
        s = (np.sin(2 * np.pi * f * t) + 0.5 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 9)
             + 0.25 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 14)) * np.exp(-t * 6.5) * 0.085
        s *= env(na, 0.004, 0.05)
        wrap_add(arp, start + int(i * 0.5 * BEAT * SR), s)
    # soft off-beat tick (filtered noise) -- barely there, keeps it moving
    for i in range(8):
        nh = int(0.06 * SR)
        t = np.arange(nh) / SR
        s = rng.standard_normal(nh) * np.exp(-t * 70) * (0.035 if i % 2 else 0.02)
        wrap_add(hats, start + int(i * 0.5 * BEAT * SR), s)

pad = circular_lowpass(pad, 1500, 2.5)
hats = circular_highpass(hats, 6000)
arp = circular_echo(arp, BEAT * 0.75, 0.5)           # dotted-eighth echo, wraps around
arp_l, arp_r = arp, np.roll(arp, int(0.011 * SR))    # slight stereo spread
pad_l = pad
pad_r = np.roll(pad, int(0.017 * SR))

left = pad_l + bass + kick + arp_l + hats
right = pad_r + bass + kick + arp_r + hats * 0.8
left = circular_reverb(left)
right = circular_reverb(right)

stereo = np.stack([left, right], axis=1)
stereo = circular_highpass(stereo[:, 0], 28)[:, None] * np.array([[1.0, 0.0]]) + \
    circular_highpass(stereo[:, 1], 28)[:, None] * np.array([[0.0, 1.0]])
stereo = np.tanh(stereo * 1.4) / 1.4                  # gentle glue
rms = np.sqrt((stereo ** 2).mean())
stereo *= 10 ** (-20 / 20) / rms                      # about -20 dBFS RMS: a background level
peak = np.abs(stereo).max()
if peak > 0.89:
    stereo *= 0.89 / peak

OUT.mkdir(exist_ok=True)
wav_path = OUT / "rain_theme.wav"
pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
with wave.open(str(wav_path), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(f"{N} samples = {N / SR:.2f}s, loop seam jump = "
      f"{np.abs(stereo[0] - stereo[-1]).max():.4f} (typical step {np.abs(np.diff(stereo, axis=0)).mean():.4f})")

try:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav_path), "-c:a", "libvorbis", "-q:a", "5",
                    str(OUT / "rain_theme.ogg")], check=True)
    wav_path.unlink()
    print("wrote", OUT / "rain_theme.ogg")
except Exception as exc:  # no ffmpeg: keep the wav, screen.html accepts either
    print("ffmpeg unavailable, kept", wav_path, exc, file=sys.stderr)
