import * as THREE from 'three';

// PLACEHOLDER GEOMETRY (Phase 0 fallback): no CC0 skull asset is vendored
// here, so the "skull" is a sphere deformed by a handful of Gaussian bumps/
// dents (eye sockets, nasal cavity, brow ridge, cheekbones, jaw taper) rather
// than a real scanned/sculpted mesh. It's a reasonable stand-in once it's
// resampled into thousands of independently-animated rain glyphs (the shape
// only needs to read as "a skull" at a glance, not hold up as a rendered
// mesh) — swap in a real glTF skull later by replacing this function's
// return value with a loaded/sampled geometry of your own.
function smoothstep(edge0, edge1, x) {
  const t = THREE.MathUtils.clamp((x - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

function gauss(dir, center, sharpness) {
  const d = dir.distanceTo(center);
  return Math.exp(-(d * d) * sharpness);
}

export function buildSkullGeometry({ widthSegments = 96, heightSegments = 72 } = {}) {
  const geo = new THREE.SphereGeometry(1, widthSegments, heightSegments);
  const pos = geo.attributes.position;
  const weight = new Float32Array(pos.count);

  const eyeL = new THREE.Vector3(-0.34, 0.12, 0.90).normalize();
  const eyeR = new THREE.Vector3(0.34, 0.12, 0.90).normalize();
  const nose = new THREE.Vector3(0, -0.05, 0.95).normalize();
  const browCenter = new THREE.Vector3(0, 0.28, 0.92).normalize();
  const cheekL = new THREE.Vector3(-0.55, -0.10, 0.78).normalize();
  const cheekR = new THREE.Vector3(0.55, -0.10, 0.78).normalize();
  const jawFront = new THREE.Vector3(0, -0.75, 0.55).normalize();

  const orig = new THREE.Vector3();
  const dir = new THREE.Vector3();
  const out = new THREE.Vector3();

  for (let i = 0; i < pos.count; i++) {
    orig.fromBufferAttribute(pos, i);
    dir.copy(orig).normalize();
    const y = orig.y;

    // Bottom hemisphere narrows into a jaw instead of staying a round chin.
    const jawZone = smoothstep(0.05, 0.9, -y);

    let r = 1.0;
    r -= jawZone * 0.30;
    r -= 0.16 * gauss(dir, eyeL, 22);
    r -= 0.16 * gauss(dir, eyeR, 22);
    r -= 0.10 * gauss(dir, nose, 30);
    r += 0.05 * gauss(dir, browCenter, 18);
    r += 0.035 * gauss(dir, cheekL, 20);
    r += 0.035 * gauss(dir, cheekR, 20);
    r += 0.05 * gauss(dir, jawFront, 12) * jawZone;
    r = Math.max(r, 0.35);

    out.copy(dir).multiplyScalar(r);
    out.z += jawZone * 0.22; // pull the jaw forward
    out.x *= 1 - jawZone * 0.18; // and narrow it
    out.y *= 1.12; // slightly less spherical cranium

    pos.setXYZ(i, out.x, out.y, out.z);

    // Denser sampling around the eyes and jaw/mouth — these read as "the
    // face" and are worth getting more glyph density than the smooth back
    // of the skull, per the brief.
    weight[i] = 1.0 + 2.5 * gauss(dir, eyeL, 14) + 2.5 * gauss(dir, eyeR, 14) + 2.0 * jawZone;
  }

  geo.computeVertexNormals();
  geo.setAttribute('sampleWeight', new THREE.BufferAttribute(weight, 1));
  return geo;
}
