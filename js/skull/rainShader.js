// Vertex shader: places each glyph either falling through its own "rain
// column" (ambient mode) or locked to its sampled point on the skull surface
// (speaking mode), blended per-instance by uFormAmount. Each instance is a
// camera-facing billboard quad sized in view-space units (offset applied
// AFTER the modelView transform), so it stays flat-on to the camera with no
// per-instance rotation math needed.
export const vertexShader = /* glsl */ `
attribute vec3 aSkullPos;
attribute vec3 aSkullNormal;
attribute float aJaw;
attribute float aSeed;
attribute vec2 aColXZ;
attribute float aFallSpeed;
attribute float aFallOffset;

uniform float uTime;
uniform float uFormAmount;
uniform float uJawAmount;
uniform float uFieldHeight;
uniform float uPointSize;

varying float vBrightness;
varying float vGlyphIndex;
varying vec2 vUv;

// Points with a lower aSeed lock in first as uFormAmount rises (and unlock
// first as it falls), so the transition sweeps across the skull instead of
// every glyph snapping into place on the same frame.
float formLocalFor(float seed, float form) {
  float width = 0.30;
  return clamp((form - seed) / width + seed, 0.0, 1.0);
}

void main() {
  vUv = uv;

  float fallY = mod(uTime * aFallSpeed + aFallOffset * uFieldHeight, uFieldHeight) - uFieldHeight * 0.5;
  vec3 rainPos = vec3(aColXZ.x, fallY, aColXZ.y);

  float formLocal = formLocalFor(aSeed, uFormAmount);

  // Jaw-region points push outward/down while "speaking", proportional to
  // live (or heuristic) audio amplitude — see skullApp.js.
  vec3 jawOffset = aSkullNormal * (uJawAmount * aJaw * 0.22) + vec3(0.0, -uJawAmount * aJaw * 0.16, 0.0);
  vec3 skullPos = aSkullPos + jawOffset;

  vec3 worldPos = mix(rainPos, skullPos, formLocal);

  vec4 mvPosition = modelViewMatrix * vec4(worldPos, 1.0);
  mvPosition.xy += position.xy * uPointSize;
  gl_Position = projectionMatrix * mvPosition;

  // Per-point brightness while falling: bright near the top of its own fall
  // cycle (the "head" of a rain streak), fading toward the bottom — with
  // many independently-phased points sharing a column this reads as a
  // trailing streak without needing a literal multi-glyph trail per column.
  float phase = fract(uTime * aFallSpeed * 0.5 + aFallOffset);
  float fallBrightness = mix(0.12, 1.0, pow(1.0 - phase, 3.0));
  float flicker = 0.75 + 0.25 * fract(sin(aSeed * 91.7 + floor(uTime * 6.0)) * 43758.5453);
  float lockedBrightness = mix(0.55, 1.0, flicker);
  vBrightness = mix(fallBrightness, lockedBrightness, formLocal);

  vGlyphIndex = floor(uTime * 8.0 + aSeed * 97.0);
}
`;

export const fragmentShader = /* glsl */ `
precision mediump float;

uniform sampler2D uAtlas;
uniform vec2 uAtlasGrid;
uniform vec3 uColor;
uniform vec3 uHotColor;
uniform float uMouthGlow;

varying float vBrightness;
varying float vGlyphIndex;
varying vec2 vUv;

void main() {
  float cellCount = uAtlasGrid.x * uAtlasGrid.y;
  float idx = mod(vGlyphIndex, cellCount);
  float cx = mod(idx, uAtlasGrid.x);
  float cy = floor(idx / uAtlasGrid.x);
  vec2 cellUv = (vec2(cx, cy) + vUv) / uAtlasGrid;

  float mask = texture2D(uAtlas, cellUv).a;
  if (mask < 0.06) discard;

  vec3 col = mix(uColor, uHotColor, clamp(vBrightness - 0.55, 0.0, 1.0) * 2.0);
  col += uHotColor * uMouthGlow * 0.4;
  gl_FragColor = vec4(col * mask * vBrightness, mask * vBrightness);
}
`;
