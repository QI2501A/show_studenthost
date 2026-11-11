import * as THREE from 'three';
import { makeNoise3D } from './noise3d.js';

// PLACEHOLDER GEOMETRY (no CC0 skull asset is vendored here): a sphere
// sculpted with deliberately exaggerated skull landmarks -- deep eye
// sockets, a hollow nasal cavity, cheekbone flare, temple taper, and a
// narrow jaw. Unlike the earlier point-cloud version, this is rendered as a
// SOLID mesh (see skullShader.js/skullApp.js) -- the eye sockets read as
// genuinely black because the fragment shader masks emission to zero there
// (see aCavityMask below), not because fewer particles happen to land in
// that area. Swap in a real glTF skull later by replacing this function's
// return value with a loaded geometry of your own (keep the aCavityMask /
// aJawWeight / aDissolveSeed attributes, or the shader needs matching edits).
function smoothstep(edge0, edge1, x) {
  const t = THREE.MathUtils.clamp((x - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
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
  const gonialL = new THREE.Vector3(-0.62, -0.62, 0.20).normalize();
  const gonialR = new THREE.Vector3(0.62, -0.62, 0.20).normalize();
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

    const jawZone = smoothstep(-0.05, 0.85, -y);
    const craniumZone = smoothstep(0.10, 0.95, y);

    let r = 1.0;
    r += craniumZone * 0.06;
    r -= 0.16 * gauss(dir, templeL, 11);
    r -= 0.16 * gauss(dir, templeR, 11);
    r += 0.18 * gauss(dir, cheekL, 8);
    r += 0.18 * gauss(dir, cheekR, 8);
    r += 0.08 * gauss(dir, browCenter, 15);
    r -= jawZone * 0.30;
    r += 0.12 * gauss(dir, jawFront, 9) * jawZone;
    // Jaw corners (gonial angle) and a squarer chin give the lower face a
    // defined mandible instead of a tapering nub.
    r += 0.12 * gauss(dir, gonialL, 10) * jawZone;
    r += 0.12 * gauss(dir, gonialR, 10) * jawZone;
    r += 0.05 * gauss(dir, chinTip, 14) * jawZone;
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
    out.z += jawZone * 0.14;
    out.x *= 1 - jawZone * 0.22;
    out.y *= 1.08 + jawZone * 0.30; // longer lower face so the mouth/jaw have room

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
    const slot = Math.exp(-((out.y + 0.44) * (out.y + 0.44)) * 900)
      * smoothstep(0.34, 0.18, Math.abs(out.x))
      * smoothstep(0.15, 0.40, out.z);
    cavityMask[i] = Math.min(1.0 - Math.max(socketMaskL, socketMaskR, noseMask), 1.0 - slot * 0.95);

    // Jaw weight: the whole mandible (everything below the mouth line)
    // hinges down together, ramping 0 -> 1 from the mouth to the chin.
    jawWeight[i] = smoothstep(-0.44, -0.80, out.y);

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
