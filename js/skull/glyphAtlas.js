import * as THREE from 'three';

// Katakana + numerals — the classic "Matrix rain" glyph set. Drawn once onto
// an offscreen canvas grid (same trick screen.html's own 2D digital rain
// already uses via ctx.fillText, just baked into a texture instead of drawn
// every frame) so the GPU can pick a cell per glyph-point instead of the
// page drawing tens of thousands of fillText calls itself.
const GLYPHS = 'アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン0123456789';

export function buildGlyphAtlas({ cols = 8, rows = 8, cell = 64 } = {}) {
  const total = cols * rows;
  let chars = GLYPHS;
  while (chars.length < total) chars += GLYPHS;
  chars = chars.slice(0, total);

  const canvas = document.createElement('canvas');
  canvas.width = cols * cell;
  canvas.height = rows * cell;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = '#ffffff';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = `${Math.floor(cell * 0.72)}px "MS Gothic", "Yu Gothic", "Meiryo", monospace`;
  for (let i = 0; i < chars.length; i++) {
    const cx = (i % cols) * cell + cell / 2;
    const cy = Math.floor(i / cols) * cell + cell / 2;
    ctx.fillText(chars[i], cx, cy);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  texture.needsUpdate = true;

  return { texture, cols, rows, count: chars.length };
}
