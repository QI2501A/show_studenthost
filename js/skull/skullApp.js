import * as THREE from 'three';
import { EffectComposer } from '../../vendor/three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from '../../vendor/three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '../../vendor/three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from '../../vendor/three/addons/postprocessing/OutputPass.js';
import { buildSolidSkullGeometry } from './solidSkullGeometry.js';
import { buildDigitTexture } from './digitTexture.js';
import { vertexShader, fragmentShader } from './skullShader.js';
import { createEnvelopeFollower } from './audioEnvelope.js';
import { makeNoise3D } from './noise3d.js';

// Orchestrates the humanoid head: a SOLID digital-rain-textured skull mesh
// (not a particle field -- see solidSkullGeometry.js/skullShader.js for why
// that switch happened: true black eye sockets and a crisp silhouette need
// real geometry, not sparse additive-blended points), a real bloom
// post-process for the glow, and the small public API screen.html's
// existing polling loop drives (setSpeaking / setTheme).
export function initSkull({
  container,
  audioEl = null,
  color = '#00ff41',
  hotColor = '#baffcb',
  darkColor = '#020402',
} = {}) {
  const width = container.clientWidth || 300;
  const height = container.clientHeight || 360;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(width, height);
  renderer.setClearColor(0x000000, 0);
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, width / height, 0.1, 20);
  camera.position.set(0, 0.02, 6.4); // far enough that the whole head fits the 3:4 panel with margin

  const geometry = buildSolidSkullGeometry();
  const digitTex = buildDigitTexture();

  const material = new THREE.ShaderMaterial({
    vertexShader,
    fragmentShader,
    transparent: false,
    depthWrite: true,
    depthTest: true,
    uniforms: {
      uFormAmount: { value: 0 },
      uJawAmount: { value: 0 },
      uMouthGlow: { value: 0 },
      uDigitTex: { value: digitTex },
      uTexTiling: { value: 2.5 }, // large enough that single 0/1 glyphs resolve on a ~340px panel
      uColor: { value: new THREE.Color(color) },
      uHotColor: { value: new THREE.Color(hotColor) },
      uDarkColor: { value: new THREE.Color(darkColor) },
    },
  });

  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh);

  // A dim ambient light so the fresnel/normal-based rim has something to
  // read against even where the digit texture and glow contribute little.
  scene.add(new THREE.AmbientLight(0xffffff, 0.15));

  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));
  const bloomPass = new UnrealBloomPass(new THREE.Vector2(width, height), 0.3, 0.4, 0.55); // strength, radius, threshold: only the brightest glyphs/rim bloom
  composer.addPass(bloomPass);
  composer.addPass(new OutputPass());

  const envelope = audioEl ? createEnvelopeFollower(audioEl) : null;
  if (audioEl) {
    audioEl.addEventListener('play', () => {
      if (envelope.ensureGraph()) envelope.resume();
    });
  }
  const jawNoise = makeNoise3D(4242);

  const state = {
    formAmount: 0,
    targetForm: 0,
    speaking: false,
    // Runs a self-contained assemble/hold/dissolve/pause demo timeline until
    // the first real setSpeaking() call arrives -- lets this whole pipeline
    // be verified visually with no audio/state wiring at all.
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
    composer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  // The head panel can change size when it's toggled visible/hidden (video
  // mode) without a window resize firing -- a ResizeObserver catches that too.
  try {
    new ResizeObserver(resize).observe(container);
  } catch (e) {
    // ResizeObserver unsupported in some embedded contexts -- window resize still covers most cases
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
      // Heuristic fallback: no live audio graph available yet. A single
      // sine wave reads as a metronome, not speech -- real jaw movement is
      // irregular and syllable-like. Three noise octaves at incommensurate
      // rates (so their sum never repeats on any observable timescale)
      // approximate that much better.
      const n1 = jawNoise(t * 3.1, 0, 0);
      const n2 = jawNoise(t * 7.3, 50, 0);
      const n3 = jawNoise(t * 13.0, 120, 0);
      const flutter = n1 * 0.5 + n2 * 0.32 + n3 * 0.18;
      jaw = Math.max(0, flutter - 0.12) * 1.15;
      glow = 0.12 + flutter * 0.38;
    }

    material.uniforms.uFormAmount.value = state.formAmount;
    material.uniforms.uJawAmount.value = jaw;
    material.uniforms.uMouthGlow.value = glow;

    composer.render();
  }
  animate();

  function dispose() {
    running = false;
    window.removeEventListener('resize', resize);
    geometry.dispose();
    material.dispose();
    digitTex.dispose();
    renderer.dispose();
    if (renderer.domElement.parentNode) renderer.domElement.parentNode.removeChild(renderer.domElement);
  }

  return { setSpeaking, setTheme, dispose, renderer, scene, camera };
}
