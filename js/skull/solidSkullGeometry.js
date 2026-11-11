import * as THREE from 'three';
import { makeNoise3D } from './noise3d.js';

// PLACEHOLDER GEOMETRY (no CC0 skull asset is vendored here): a sphere
// sculpted with deliberately exaggerated skull landmarks -- deep eye
// sockets, a hollow nasal cavity, cheekbone flare, temple taper, and a
// mandible shaped against a real front-view skull reference photo. Unlike
// the earlier point-cloud version, this is rendered as a SOLID mesh (see
// skullShader.js/skullApp.js) -- the eye sockets read as genuinely black
// because the fragment shader masks emission to zero there (see
// aCavityMask below), not because fewer particles happen to land in that
// area. Swap in a real glTF skull later by replacing this function's return
// value with a loaded geometry of your own (keep the aCavityMask /
// aJawWeight / aDissolveSeed attributes, or the shader needs matching edits).
function smoothstep(edge0, edge1, x) {
  const t = THREE.MathUtils.clamp((x - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function gauss(dir, center, sharpness) {
  const d = dir.distanceTo(center);
  return Math.exp(-(d * d) * sharpness);
}

export function buildSolidSkullGeometry({ widthSegments = 160, heightSegments = 120 } = {}) {
  const geo = new THREE.SphereGeometry(1, widthSegments, heightSegments);
  const pos = geo.attributes.position;
  const cavityMask = new Float32Array(pos.count);
  const jawWeight = new Float32Array(pos.count);
  const dissolveSeed = new Float32Array(pos.count);

  const eyeL = new THREE.Vector3(-0.37, 0.08, 0.88).normalize();
  const eyeR = new THREE.Vector3(0.37, 0.08, 0.88).normalize();
  const nose = new THREE.Vector3(0, -0.14, 0.97).normalize();
  const browCenter = new THREE.Vector3(0, 0.34, 0.90).normalize();
  const cheekL = new THREE.Vector3(-0.64, -0.20, 0.70).normalize();
  const cheekR = new THREE.Vector3(0.64, -0.20, 0.70).normalize();
  const templeL = new THREE.Vector3(-0.80, 0.20, 0.30).normalize();
  const templeR = new THREE.Vector3(0.80, 0.20, 0.30).normalize();
  const jawFront = new THREE.Vector3(0, -0.92, 0.60).normalize();
  const chinTip = new THREE.Vector3(0, -1.0, 0.55).normalize();
  const hollowL = new THREE.Vector3(-0.52, -0.46, 0.72).normalize();
  const hollowR = new THREE.Vector3(0.52, -0.46, 0.72).normalize();

  const noise = makeNoise3D(2024);
  const orig = new THREE.Vector3();
  const dir = new THREE.Vector3();
  const out = new THREE.Vector3();

  for (let i = 0; i < pos.count; i++) {
    orig.fromBufferAttribute(pos, i);
    dir.copy(orig).normalize();
    const y = orig.y;

    // jawT: 0 at/above the cheekbone line, 1 by the chin tip.
    const jawT = smoothstep(-0.05, 0.85, -y);
    const craniumZone = smoothstep(0.10, 0.95, y);

    let r = 1.0;
    r += craniumZone * 0.06;
    r -= 0.16 * gauss(dir, templeL, 11);
    r -= 0.16 * gauss(dir, templeR, 11);
    r += 0.18 * gauss(dir, cheekL, 8);
    r += 0.18 * gauss(dir, cheekR, 8);
    r += 0.08 * gauss(dir, browCenter, 15);
    // Subtle chin/jaw-front mass -- the overall mandible SHAPE (width
    // profile, not a simple radial bump) is handled below, after `out` is
    // computed; these are just small local bulges on top of it.
    r += 0.05 * gauss(dir, jawFront, 9) * jawT;
    r += 0.04 * gauss(dir, chinTip, 14) * jawT;
    // Hollow cheeks under the cheekbones.
    r -= 0.07 * gauss(dir, hollowL, 14);
    r -= 0.07 * gauss(dir, hollowR, 14);

    const eyeDepthL = gauss(dir, eyeL, 42);
    const eyeDepthR = gauss(dir, eyeR, 42);
    r -= 0.36 * eyeDepthL;
    r -= 0.36 * eyeDepthR;

    const noseDepth = gauss(dir, nose, 55);
    r -= 0.22 * noseDepth;

    r = Math.max(r, 0.26);

    out.copy(dir).multiplyScalar(r);

    // --- Mandible width profile -----------------------------------------
    // A real jaw does not taper to a point: the gonial angle (the back
    // corner of the jaw, up near the ears) is close to cheekbone width,
    // the jawline curves in only moderately from there, and the chin is a
    // rounded, blunt mass. widthMul flares OUT a little past the
    // cheekbone line before narrowing toward the chin, instead of
    // shrinking monotonically the whole way down (the old behaviour,
    // which produced the "icicle" taper).
    const widthMul = jawT < 0.42
      ? lerp(1.0, 1.08, smoothstep(0, 0.42, jawT))
      : lerp(1.08, 0.56, smoothstep(0.42, 1.0, jawT));
    out.x *= widthMul;
    out.z *= widthMul;
    out.z += jawT * 0.12; // chin projects forward slightly, as in the reference photo
    out.y *= 1.0 + jawT * 0.16; // modest extra length for mouth/jaw-drop room (not the old 1.38x)

    // A UV sphere's own vertices pinch to near-zero x/z at the pole purely
    // from the latitude/longitude parameterization -- no radial scale
    // above can fix that, since scaling an already-tiny vector keeps it
    // tiny. Explicitly floor the horizontal (xz) radius near the very
    // bottom so the chin ends in a rounded, slightly flattened underside
    // instead of collapsing to a point.
    const minRing = 0.24 * smoothstep(0.75, 1.0, jawT);
    const ring = Math.hypot(out.x, out.z);
    if (ring < minRing && ring > 1e-6) {
      const scale = minRing / ring;
      out.x *= scale;
      out.z *= scale;
    }

    pos.setXYZ(i, out.x, out.y, out.z);

    // Cavity mask: 1 = normal surface, 0 = deep inside an eye socket/nasal
    // cavity. Wider gaussians than the geometric depth ones above and a
    // hard smoothstep cutoff -- the visible hole needs to be a good deal
    // bigger than the subtle geometric dent to read as a true hollow rather
    // than a shadow.
    const eyeMaskL = gauss(dir, eyeL, 16);
    const eyeMaskR = gauss(dir, eyeR, 16);
    const noseMaskDepth = gauss(dir, nose, 22);
    const socketMaskL = smoothstep(0.22, 0.5, eyeMaskL);
    const socketMaskR = smoothstep(0.22, 0.5, eyeMaskR);
    const noseMask = smoothstep(0.32, 0.58, noseMaskDepth);
    // Thin dark mouth slot across the front of the face, between the upper
    // and lower teeth line -- reads as an opening when the jaw drops.
    const slot = Math.exp(-((out.y + 0.37) * (out.y + 0.37)) * 900)
      * smoothstep(0.36, 0.20, Math.abs(out.x))
      * smoothstep(0.15, 0.40, out.z);
    cavityMask[i] = Math.min(1.0 - Math.max(socketMaskL, socketMaskR, noseMask), 1.0 - slot * 0.95);

    // Jaw weight: the whole mandible (everything below the mouth line)
    // hinges down together, ramping 0 -> 1 from the mouth to the chin.
    // (Thresholds rescaled from the old -0.44/-0.80 to match the jaw's
    // shorter y-span now that it no longer over-stretches toward a point.)
    jawWeight[i] = smoothstep(-0.37, -0.67, out.y);

    // Dissolve seed: blob-scale noise (not per-vertex random) so nearby
    // vertices lock in together as uFormAmount rises -- an organic sweep
    // across the mesh instead of a uniform fade or per-triangle static.
    const nz = noise(out.x * 1.6, out.y * 1.6, out.z * 1.6);
    dissolveSeed[i] = THREE.MathUtils.clamp(nz * 0.75 + Math.random() * 0.25, 0, 1);
  }

  geo.computeVertexNormals();
  geo.setAttribute('aCavityMask', new THREE.BufferAttribute(cavityMask, 1));
  geo.setAttribute('aJawWeight', new THREE.BufferAttribute(jawWeight, 1));
  geo.setAttribute('aDissolveSeed', new THREE.BufferAttribute(dissolveSeed, 1));
  return geo;
}
