// Solid-mesh skull shader: a continuous surface (not a particle field) so
// the eye sockets/nasal cavity can read as genuinely black -- aCavityMask
// (see solidSkullGeometry.js) masks emission to zero there, rather than
// relying on point density being merely sparser. The digit texture
// (digitTexture.js) supplies the "binary code" surface detail; a fresnel
// rim term adds the edge-glow look; a real bloom pass (see skullApp.js)
// handles the glow blur instead of a blanket CSS filter, so bright glyphs
// bloom without washing out the dark cavities right next to them.
export const vertexShader = /* glsl */ `
attribute float aCavityMask;
attribute float aJawWeight;
attribute float aDissolveSeed;

uniform float uFormAmount;
uniform float uJawAmount;

varying vec2 vUv;
varying vec3 vNormalW;
varying vec3 vWorldPos;
varying float vCavityMask;
varying float vReveal;

// Points with a lower seed lock in first as uFormAmount rises (and unlock
// first as it falls) -- the assemble/dissolve sweeps across the skull
// instead of every vertex snapping at once.
float revealFor(float seed, float form) {
  float width = 0.28;
  return clamp((form - seed) / width + seed, 0.0, 1.0);
}

void main() {
  vUv = uv;
  vCavityMask = aCavityMask;
  vReveal = revealFor(aDissolveSeed, uFormAmount);

  vec3 displaced = position
    + normal * (uJawAmount * aJawWeight * 0.16)
    + vec3(0.0, -uJawAmount * aJawWeight * 0.12, 0.0);

  vec4 worldPos = modelMatrix * vec4(displaced, 1.0);
  vWorldPos = worldPos.xyz;
  vNormalW = normalize(mat3(modelMatrix) * normal);

  gl_Position = projectionMatrix * viewMatrix * worldPos;
}
`;

export const fragmentShader = /* glsl */ `
precision mediump float;

uniform sampler2D uDigitTex;
uniform float uTexTiling;
uniform vec3 uColor;
uniform vec3 uHotColor;
uniform vec3 uDarkColor;
uniform float uMouthGlow;

varying vec2 vUv;
varying vec3 vNormalW;
varying vec3 vWorldPos;
varying float vCavityMask;
varying float vReveal;

void main() {
  // Not materialized yet at this point on the mesh -- a hard cut (not an
  // alpha fade) reads as a "digital" scan-in rather than a soft dissolve,
  // matching the rest of this page's aesthetic.
  if (vReveal < 0.5) discard;

  vec2 tiledUv = fract(vUv * uTexTiling);
  float digit = texture2D(uDigitTex, tiledUv).r;

  vec3 base = mix(uDarkColor, uColor, digit);

  vec3 viewDir = normalize(cameraPosition - vWorldPos);
  float fresnel = pow(1.0 - clamp(dot(normalize(vNormalW), viewDir), 0.0, 1.0), 2.2);
  vec3 rim = uHotColor * fresnel * 0.9;

  // The cavity mask is the whole point: true black inside the eye sockets
  // and nasal cavity, not just a dimmer version of the surrounding surface.
  vec3 col = (base + rim) * vCavityMask;
  col += uHotColor * uMouthGlow * 0.3 * vCavityMask;

  gl_FragColor = vec4(col, 1.0);
}
`;
