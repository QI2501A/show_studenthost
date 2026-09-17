// Minimal seeded 3D value noise. Not "true" simplex noise (no external
// dependency needed for this) — just smooth, deterministic, blob-scale
// randomness used once at build time to seed the skull's assemble/dissolve
// order (see skullField.js), so nearby points lock in together instead of
// every point snapping independently.
function hash3(x, y, z, seed) {
  let n = x * 374761393 + y * 668265263 + z * 2147483647 + seed * 3266489917;
  n = (n ^ (n >>> 13)) * 1274126177;
  n = n ^ (n >>> 16);
  return (n >>> 0) / 4294967295;
}

function fade(t) {
  return t * t * t * (t * (t * 6 - 15) + 10);
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

export function makeNoise3D(seed = 1337) {
  return function noise3D(x, y, z) {
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
    const xf = x - xi, yf = y - yi, zf = z - zi;
    const u = fade(xf), v = fade(yf), w = fade(zf);

    const c000 = hash3(xi, yi, zi, seed);
    const c100 = hash3(xi + 1, yi, zi, seed);
    const c010 = hash3(xi, yi + 1, zi, seed);
    const c110 = hash3(xi + 1, yi + 1, zi, seed);
    const c001 = hash3(xi, yi, zi + 1, seed);
    const c101 = hash3(xi + 1, yi, zi + 1, seed);
    const c011 = hash3(xi, yi + 1, zi + 1, seed);
    const c111 = hash3(xi + 1, yi + 1, zi + 1, seed);

    const x00 = lerp(c000, c100, u), x10 = lerp(c010, c110, u);
    const x01 = lerp(c001, c101, u), x11 = lerp(c011, c111, u);
    const y0 = lerp(x00, x10, v), y1 = lerp(x01, x11, v);
    return lerp(y0, y1, w); // 0..1
  };
}
