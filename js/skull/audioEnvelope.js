// Web Audio AnalyserNode wrapper around an <audio> element (not a
// microphone — the TTS audio itself plays through this element; see
// screen.html and Dialogue.py's play_audio_and_wait). Produces a smoothed
// 0..1 amplitude envelope with a fast attack / slower release, so the
// jaw/mouth reacts snappily to onsets but doesn't flicker between syllables.
export function createEnvelopeFollower(audioEl, { fftSize = 512, attackMs = 15, releaseMs = 200 } = {}) {
  let ctx = null;
  let analyser = null;
  let data = null;
  let envelope = 0;
  let lastT = performance.now();

  function ensureGraph() {
    if (ctx) return true;
    try {
      ctx = new (window.AudioContext || window.webkitAudioContext)();
      const source = ctx.createMediaElementSource(audioEl);
      analyser = ctx.createAnalyser();
      analyser.fftSize = fftSize;
      data = new Uint8Array(analyser.frequencyBinCount);
      source.connect(analyser);
      analyser.connect(ctx.destination);
      return true;
    } catch (e) {
      console.warn('[skull] audio analyser unavailable, falling back to heuristic jaw motion', e);
      ctx = null;
      analyser = null;
      return false;
    }
  }

  function resume() {
    if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {});
  }

  function update() {
    if (!ctx || !analyser) return envelope;
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / data.length);

    const now = performance.now();
    const dt = Math.max(1, now - lastT);
    lastT = now;
    const attackA = 1 - Math.exp(-dt / attackMs);
    const releaseA = 1 - Math.exp(-dt / releaseMs);
    const a = rms > envelope ? attackA : releaseA;
    envelope += (rms - envelope) * a;
    return envelope;
  }

  return {
    ensureGraph,
    resume,
    update,
    get active() { return ctx !== null; },
    get value() { return envelope; },
  };
}
