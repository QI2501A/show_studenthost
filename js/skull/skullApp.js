import * as THREE from 'three';
import { buildSkullField } from './skullField.js';
import { buildGlyphAtlas } from './glyphAtlas.js';
import { vertexShader, fragmentShader } from './rainShader.js';
import { createEnvelopeFollower } from './audioEnvelope.js';

// Orchestrates the whole Matrix digital-rain skull: scene/camera/renderer
// setup, the render loop, and the small public API screen.html's existing
// polling loop drives (setSpeaking / setTheme). See the module docstrings in
// skullField.js and rainShader.js for how the assemble/dissolve and
// audio-reactive jaw actually work.
export function initSkull({
  container,
  audioEl = null,
  pointCount = 16000,
  color = '#00ff41',
  hotColor = '#baffcb',
} = {}) {
  const width = container.clientWidth || 300;
  const height = container.clientHeight || 360;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height);
  renderer.setClearColor(0x000000, 0);
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, width / height, 0.1, 20);
  camera.position.set(0, 0.05, 5.2);

  const fieldHeight = 3.2;
  const { geometry } = buildSkullField({ count: pointCount, fieldHeight });
  const atlas = buildGlyphAtlas({ cols: 8, rows: 8, cell: 64 });

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uTime: { value: 0 },
      uFormAmount: { value: 0 },
      uJawAmount: { value: 0 },
      uMouthGlow: { value: 0 },
      uFieldHeight: { value: fieldHeight },
      uPointSize: { value: 0.05 },
      uAtlas: { value: atlas.texture },
      uAtlasGrid: { value: new THREE.Vector2(atlas.cols, atlas.rows) },
      uColor: { value: new THREE.Color(color) },
      uHotColor: { value: new THREE.Color(hotColor) },
    },
  });

  const field = new THREE.Mesh(geometry, material);
  field.frustumCulled = false;
  scene.add(field);

  const envelope = audioEl ? createEnvelopeFollower(audioEl) : null;
  if (audioEl) {
    audioEl.addEventListener('play', () => {
      if (envelope.ensureGraph()) envelope.resume();
    });
  }

  const state = {
    formAmount: 0,
    targetForm: 0,
    speaking: false,
    // Runs a self-contained assemble/hold/dissolve/pause demo timeline until
    // the first real setSpeaking() call arrives — lets this whole pipeline
    // be verified visually with no audio/state wiring at all (Phase 3).
    demo: true,
    demoT: 0,
  };

  function setSpeaking(isSpeaking) {
    state.demo = false;
    state.speaking = isSpeaking;
    state.targetForm = isSpeaking ? 1 : 0;
  }

  function setTheme(hex) {
    material.uniforms.uColor.value.set(hex);
  }

  function resize() {
    const w = container.clientWidth || width;
    const h = container.clientHeight || height;
    if (w === 0 || h === 0) return;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  // The head panel can change size when it's toggled visible/hidden (video
  // mode) without a window resize firing — a ResizeObserver catches that too.
  try {
    new ResizeObserver(resize).observe(container);
  } catch (e) {
    // ResizeObserver unsupported in some embedded contexts — window resize still covers most cases
  }

  const clock = new THREE.Clock();
  let running = true;

  function animate() {
    if (!running) return;
    requestAnimationFrame(animate);
    const dt = clock.getDelta();
    const t = clock.elapsedTime;

    if (state.demo) {
      state.demoT += dt;
      const cycle = 7.5; // ~2s assemble, ~2s hold, ~2s dissolve, ~1.5s pause
      const tt = state.demoT % cycle;
      if (tt < 2.0) state.targetForm = tt / 2.0;
      else if (tt < 4.0) state.targetForm = 1;
      else if (tt < 6.0) state.targetForm = 1 - (tt - 4.0) / 2.0;
      else state.targetForm = 0;
    }

    state.formAmount += (state.targetForm - state.formAmount) * Math.min(1, dt * 2.2);

    let jaw = 0;
    let glow = 0;
    if (state.speaking && envelope && envelope.active) {
      const env = envelope.update();
      jaw = Math.min(1, env * 3.2);
      glow = Math.min(1, env * 2.2);
    } else if (state.speaking) {
      // Heuristic fallback: no live audio graph available yet (analyser
      // failed to init, or audio hasn't started playing this instant) — a
      // synthesized flutter, same category of approximation as the old
      // SVG head's random mouth movement, so speaking still reads visually.
      jaw = 0.25 + 0.2 * Math.sin(t * 9.0);
      glow = 0.3;
    }

    material.uniforms.uTime.value = t;
    material.uniforms.uFormAmount.value = state.formAmount;
    material.uniforms.uJawAmount.value = jaw;
    material.uniforms.uMouthGlow.value = glow;

    renderer.render(scene, camera);
  }
  animate();

  function dispose() {
    running = false;
    window.removeEventListener('resize', resize);
    geometry.dispose();
    material.dispose();
    atlas.texture.dispose();
    renderer.dispose();
    if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
  }

  return { setSpeaking, setTheme, dispose, renderer, scene, camera };
}
