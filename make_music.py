"""Generates the show's two background-music loops (pure numpy/scipy, no samples):

    audio/rain_theme.ogg      -- under the green digital-rain chatbot portion, from the
                                 welcome-screen hand-over until the IGNITE video. A dark
                                 "Matrix"-style bed: low string clusters, a sub pedal, a
                                 slow trip-hop beat, a lone echoing piano motif and
                                 falling data blips. D minor, 88 BPM, 16 bars.
    audio/recovery_theme.ogg  -- once OVERRIDE has worked and the robots are back under
                                 control. A big, dramatic score: brass swells, driving
                                 string ostinato, timpani and toms, a rising hero line
                                 and risers. D minor, 112 BPM, 16 bars.

Both loop seamlessly because EVERYTHING is rendered circularly: notes, echoes and
reverb tails wrap around the end of the buffer back to the start, and the filters are
applied in the frequency domain over the whole loop, so the last sample flows straight
into the first with no gap, click or cut-off tail. (screen.html plays them as Web Audio
buffers with loop=true, which repeats sample-accurately.)

    python make_music.py            # writes both
    python make_music.py rain       # or just one of: rain, recovery
"""
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent / "audio"


# ----------------------------------------------------------------- helpers
def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def wrap_add(buf, start, sig):
    """Adds sig into buf at `start`, wrapping past the end back to 0."""
    n, size = len(sig), len(buf)
    pos = start % size
    i = 0
    while i < n:
        k = min(n - i, size - pos)
        buf[pos:pos + k] += sig[i:i + k]
        i += k
        pos = 0


def saw_vib(freq, n, rng, vib_hz=5.0, vib_depth=0.0025):
    """A saw with gentle vibrato (phase accumulated so the pitch glides cleanly)."""
    t = np.arange(n) / SR
    f = freq * (1 + vib_depth * np.sin(2 * np.pi * (vib_hz + rng.random() * 0.6) * t + rng.random() * 6.28))
    ph = (np.cumsum(f) / SR + rng.random()) % 1.0
    return 2 * ph - 1


def env(n, a, r):
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na) ** 2
    e[-nr:] *= np.linspace(1, 0, nr) ** 2
    return e


def lowpass(x, cutoff_hz, slope=2.0):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(X / (1.0 + (f / cutoff_hz) ** (2 * slope)), len(x))


def highpass(x, cutoff_hz, slope=2.0):
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    H = 1.0 - 1.0 / (1.0 + (f / cutoff_hz) ** (2 * slope))
    return np.fft.irfft(X * H, len(x))


def echo(x, delay_s, feedback, taps=6):
    out = x.copy()
    d = int(delay_s * SR)
    for i in range(1, taps + 1):
        out += np.roll(x, d * i) * feedback ** i
    return out


def reverb(x, rng, seconds=2.6, wet=0.35, decay=3.2, gain=2.2):
    """Circular convolution with a decaying noise burst: the tail wraps into the start."""
    n = len(x)
    ir_len = int(seconds * SR)
    t = np.arange(ir_len) / SR
    ir = rng.standard_normal(ir_len) * np.exp(-t * decay)
    ir = lowpass(np.pad(ir, (0, n - ir_len)), 3500)[:ir_len]
    ir /= np.sqrt((ir ** 2).sum())
    wetsig = np.fft.irfft(np.fft.rfft(x) * np.fft.rfft(ir, n), n)
    return x * (1 - wet) + wetsig * wet * gain


def noise_burst(n, decay, rng):
    t = np.arange(n) / SR
    return rng.standard_normal(n) * np.exp(-t * decay)


def finish(name, left, right, rms_db=-20.0, drive=1.4):
    """Glue, level (a background level), write wav -> ogg."""
    st = np.stack([highpass(left, 28), highpass(right, 28)], axis=1)
    st = np.tanh(st * drive) / drive
    st *= 10 ** (rms_db / 20) / np.sqrt((st ** 2).mean())
    peak = np.abs(st).max()
    if peak > 0.89:
        st *= 0.89 / peak
    OUT.mkdir(exist_ok=True)
    wav_path = OUT / f"{name}.wav"
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(st, -1, 1) * 32767).astype("<i2").tobytes())
    seam = np.abs(st[0] - st[-1]).max()
    step = np.abs(np.diff(st, axis=0)).mean()
    print(f"{name}: {len(st) / SR:.2f}s, loop seam jump {seam:.4f} vs typical step {step:.4f}, peak {np.abs(st).max():.2f}")
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav_path), "-c:a", "libvorbis", "-q:a", "5",
                        str(OUT / f"{name}.ogg")], check=True)
        wav_path.unlink()
    except Exception as exc:
        print("ffmpeg unavailable, kept", wav_path, exc, file=sys.stderr)


def kick(n_len=0.4, f0=52, drop=70, decay=10, amp=0.5):
    t = np.arange(int(n_len * SR)) / SR
    return np.sin(2 * np.pi * (f0 * t + drop * (1 - np.exp(-t * 30)) / 30)) * np.exp(-t * decay) * amp


# ----------------------------------------------------------------- rain: Matrix-style
def make_rain():
    rng = np.random.default_rng(11)
    BPM, BARS = 88, 16
    beat = 60.0 / BPM
    N = int(round(BARS * 4 * beat * SR))

    def at(bar, pos_beats):
        return int(round((bar * 4 + pos_beats) * beat * SR))

    strings, sub, drums, piano, blips, fx = (np.zeros(N) for _ in range(6))

    # Chords, four bars each: Dm(add9) | Bb(maj7) | Gm(add9) | A (the dominant: pulls back to Dm)
    chords = [
        ([50, 57, 62, 64, 65], 38),     # D3 A3 D4 E4 F4   (cluster: minor 3rd + 9th rubbing)
        ([46, 53, 57, 62, 64], 34 + 12),
        ([43, 50, 55, 58, 62, 69], 43),
        ([45, 52, 57, 61, 67], 45),     # A major with a b7: tense
    ]
    for sec in range(4):
        tones, root = chords[sec]
        start = at(sec * 4, 0)
        seg = int(4 * 4 * beat * SR + 2.2 * SR)
        for tone in tones:
            for dt in (-0.09, 0.0, 0.09):
                s = saw_vib(midi(tone) * 2 ** (dt / 12), seg, rng) * env(seg, 1.8, 2.2) * 0.045
                wrap_add(strings, start, s)
        t = np.arange(seg) / SR
        f = midi(root)
        pedal = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t)) * env(seg, 0.6, 1.5) * 0.20
        wrap_add(sub, start, pedal)
    strings = lowpass(strings, 1500, 2.5)

    # Trip-hop beat (bars 2-13; a stripped breakdown in 14-15 builds into the loop)
    for bar in range(2, 14):
        for pos in (0.0, 2.75):
            wrap_add(drums, at(bar, pos), kick(amp=0.5 if pos == 0 else 0.35))
        for pos in (1.0, 3.0):
            n = int(0.22 * SR)
            t = np.arange(n) / SR
            sn = highpass(noise_burst(n, 20, rng), 300) * 0.32 + np.sin(2 * np.pi * 185 * t) * np.exp(-t * 28) * 0.28
            wrap_add(drums, at(bar, pos), sn)
        for i in range(8):            # swung hats
            swing = 0.18 * beat * (i % 2)
            n = int(0.05 * SR)
            wrap_add(drums, at(bar, i * 0.5) + int(swing * SR),
                     highpass(noise_burst(n, 90, rng), 6500) * (0.07 if i % 2 else 0.11))
    for bar in (14, 15):
        for pos in (0.0, 2.0):
            wrap_add(drums, at(bar, pos), kick(amp=0.35))
        if bar == 15:
            for i in range(8):
                n = int(0.12 * SR)
                wrap_add(drums, at(bar, 2 + i * 0.25), highpass(noise_burst(n, 30, rng), 700) * (0.06 + 0.03 * i))

    # The lone echoing piano motif (from bar 4; falls an octave on the last phrase's second half)
    motif = [(0, 69), (1.5, 74), (3, 72), (4, 69), (5.5, 65), (7, 67), (8, 69), (9.5, 70), (11, 69), (12, 67),
             (13.5, 65), (15, 64)]
    for phrase in range(1, 4):
        for pos, note in motif:
            n = int(1.6 * SR)
            t = np.arange(n) / SR
            f = midi(note - (12 if phrase == 3 and pos > 8 else 0))
            tone = (np.sin(2 * np.pi * f * t) + 0.45 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 6)
                    + 0.2 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 10)) * np.exp(-t * 2.6) * 0.16
            wrap_add(piano, at(phrase * 4, pos), tone * env(n, 0.004, 0.2))
    piano = echo(piano, beat * 0.75, 0.55)

    # Falling data blips: the rain itself, sparse and high
    scale = [74, 77, 79, 81, 82, 84, 86]
    for bar in range(BARS):
        for _ in range(int(rng.integers(2, 6))):
            pos = rng.random() * 4
            n = int(0.05 * SR)
            t = np.arange(n) / SR
            f = midi(scale[int(rng.integers(0, len(scale)))] + 12)
            wrap_add(blips, at(bar, pos), np.sin(2 * np.pi * f * t) * np.exp(-t * 55) * 0.05)
    blips = echo(blips, beat * 0.5, 0.5)

    # A slow impact on the downbeat of the loop and a riser into it
    n = int(2.5 * SR)
    t = np.arange(n) / SR
    wrap_add(fx, at(0, 0), np.sin(2 * np.pi * 38 * t) * np.exp(-t * 1.6) * 0.45)
    rn = int(4 * beat * SR)
    riser = lowpass(rng.standard_normal(rn), 5000) * np.linspace(0, 1, rn) ** 3 * 0.10
    wrap_add(fx, at(15, 0), highpass(riser, 500))

    left = strings + sub + drums + piano + blips + fx
    right = np.roll(strings, int(0.019 * SR)) + sub + drums + np.roll(piano, int(0.011 * SR)) \
        + np.roll(blips, int(0.007 * SR)) + fx
    finish("rain_theme", reverb(left, rng, wet=0.30), reverb(right, rng, wet=0.30))


# ----------------------------------------------------------------- recovery: dramatic
def make_recovery():
    rng = np.random.default_rng(23)
    BPM, BARS = 112, 16
    beat = 60.0 / BPM
    N = int(round(BARS * 4 * beat * SR))

    def at(bar, pos):
        return int(round((bar * 4 + pos) * beat * SR))

    brass, strings, bass, drums, lead, fx = (np.zeros(N) for _ in range(6))
    # 8 bars, played twice (the second time higher and bigger): Dm | Bb | F | C | Dm | Bb | Gm | A
    prog = [
        (38, [50, 57, 62]), (34 + 12, [46, 53, 58]), (41, [53, 57, 60]), (36 + 12, [48, 55, 60]),
        (38, [50, 57, 62]), (34 + 12, [46, 53, 58]), (43, [55, 58, 62]), (45, [57, 61, 64]),
    ]
    for bar in range(BARS):
        root, tones = prog[bar % 8]
        lift = 1.0 if bar < 8 else 1.35
        start = at(bar, 0)
        seg = int(4 * beat * SR + 0.9 * SR)
        # brass-like swell chord (stacked saws, low-passed, slow attack)
        for tone in tones:
            for dt in (-0.1, 0.0, 0.1):
                s = saw_vib(midi(tone - 12) * 2 ** (dt / 12), seg, rng, vib_hz=4.6, vib_depth=0.002)
                wrap_add(brass, start, s * env(seg, 0.55, 0.7) * 0.06 * lift)
        # driving string ostinato: 16ths on chord tones, accented on the beat
        pat = [0, 1, 2, 1, 0, 1, 2, 1, 0, 1, 2, 1, 2, 1, 2, 1]
        for i, p in enumerate(pat):
            f = midi(tones[p] + 12)
            n = int(0.16 * SR)
            ph = (np.arange(n) / SR * f) % 1.0
            s = (2 * ph - 1) * np.exp(-np.arange(n) / SR * 14) * (0.07 if i % 4 == 0 else 0.045) * lift
            wrap_add(strings, at(bar, i * 0.25), s)
        # pulsing 8th-note bass
        for i in range(8):
            n = int(0.42 * beat * SR)
            t = np.arange(n) / SR
            f = midi(root)
            s = (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 2 * f * t)) * env(n, 0.005, 0.06) * 0.30
            wrap_add(bass, at(bar, i * 0.5), s)
        # timpani on 1 and 3, a snare-ish crack on 2 and 4 (heavier in the second half)
        for pos in (0, 2):
            wrap_add(drums, at(bar, pos), kick(0.5, f0=70, drop=60, decay=6, amp=0.55 * lift))
        if bar >= 4:
            for pos in (1, 3):
                n = int(0.25 * SR)
                t = np.arange(n) / SR
                wrap_add(drums, at(bar, pos), (highpass(noise_burst(n, 16, rng), 400) * 0.22
                                               + np.sin(2 * np.pi * 170 * t) * np.exp(-t * 24) * 0.22) * lift)
        # tom fill + cymbal swell closing each 4 bars
        if bar % 4 == 3:
            for i, pos in enumerate((2.0, 2.5, 3.0, 3.25, 3.5, 3.75)):
                wrap_add(drums, at(bar, pos), kick(0.3, f0=95 - i * 6, drop=40, decay=9, amp=0.40))
            rn = int(2 * beat * SR)
            wrap_add(fx, at(bar, 2), highpass(lowpass(rng.standard_normal(rn), 9000), 2500)
                     * np.linspace(0, 1, rn) ** 2.5 * 0.12)
        if bar % 8 == 0:   # a big crash and a deep boom on the downbeat
            n = int(3.2 * SR)
            wrap_add(fx, at(bar, 0), highpass(noise_burst(n, 1.4, rng), 3000) * 0.20)
            t = np.arange(int(2.0 * SR)) / SR
            wrap_add(fx, at(bar, 0), np.sin(2 * np.pi * 36 * t) * np.exp(-t * 1.4) * 0.5)

    # The rising hero line, long notes over the second half (and a quieter echo of it in the first)
    hero = [(8, 0, 69, 4), (8, 2, 74, 2), (9, 0, 70, 4), (10, 0, 72, 2), (10, 2, 77, 2), (11, 0, 76, 4),
            (12, 0, 74, 3), (12, 3, 77, 1), (13, 0, 82, 4), (14, 0, 79, 2), (14, 2, 77, 2), (15, 0, 81, 4)]
    for bar, pos, note, dur in hero:
        n = int(dur * beat * SR + 0.5 * SR)
        f = midi(note)
        s = saw_vib(f, n, rng, 5.2, 0.004) * 0.5 + np.sin(2 * np.pi * f * np.arange(n) / SR) * 0.5
        wrap_add(lead, at(bar, pos), s * env(n, 0.12, 0.45) * 0.085)
    for bar, pos, note, dur in hero[:6]:   # first-half foreshadowing, an octave down and quiet
        n = int(dur * beat * SR + 0.5 * SR)
        f = midi(note - 12)
        wrap_add(lead, at(bar - 8, pos), saw_vib(f, n, rng, 5.0, 0.004) * env(n, 0.2, 0.5) * 0.04)

    brass = lowpass(brass, 2300, 2.5)
    strings = lowpass(strings, 3500)
    lead = lowpass(lead, 3200)
    left = brass + strings + bass + drums + lead + fx
    right = np.roll(brass, int(0.015 * SR)) + np.roll(strings, int(0.009 * SR)) + bass + drums \
        + np.roll(lead, int(0.012 * SR)) + fx
    finish("recovery_theme", reverb(left, rng, 3.4, 0.33, 2.6), reverb(right, rng, 3.4, 0.33, 2.6),
           rms_db=-19, drive=1.6)


if __name__ == "__main__":
    which = sys.argv[1:] or ["rain", "recovery"]
    if "rain" in which:
        make_rain()
    if "recovery" in which:
        make_recovery()
