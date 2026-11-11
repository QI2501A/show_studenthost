import * as THREE from 'three';

// Draws a tileable grid of binary digits onto an offscreen canvas and wraps
// it as a THREE.CanvasTexture -- this is the "0100101" surface texture in
// the reference look, sampled once per-pixel across the solid skull mesh
// (see skullShader.js), not per-particle like the old point-cloud version.
export function buildDigitTexture({ size = 1024, cols = 28, glyphColor = '#eafff2' } = {}) {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, size, size);

  const cell = size / cols;
  ctx.font = `${Math.floor(cell * 0.86)}px "Courier New", monospace`;
  ctx.fillStyle = glyphColor;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  for (let row = 0; row < cols; row++) {
    for (let col = 0; col < cols; col++) {
      const ch = Math.random() < 0.5 ? '0' : '1';
      // Slight per-glyph opacity variation so the surface doesn't read as a
      // perfectly uniform grid -- closer to the reference's organic noise.
      ctx.globalAlpha = 0.55 + Math.random() * 0.45;
      ctx.fillText(ch, col * cell + cell / 2, row * cell + cell / 2);
    }
  }
  ctx.globalAlpha = 1;

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.needsUpdate = true;
  return texture;
}
