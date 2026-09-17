import * as THREE from 'three';
import { MeshSurfaceSampler } from '../../vendor/three/addons/math/MeshSurfaceSampler.js';
import { buildSkullGeometry } from './proceduralSkull.js';
import { makeNoise3D } from './noise3d.js';

// Builds the instanced glyph-point field: one instance per rain glyph, each
// carrying both a "resting" position on the skull surface and a "rain
// column" position it falls through in ambient mode. The vertex shader
// (rainShader.js) blends between the two using uFormAmount.
export function buildSkullField({ count = 16000, fieldRadius = 1.7, fieldHeight = 3.2 } = {}) {
  const skullGeo = buildSkullGeometry();
  const skullMesh = new THREE.Mesh(skullGeo);
  const sampler = new MeshSurfaceSampler(skullMesh).setWeightAttribute('sampleWeight').build();

  const skullPos = new Float32Array(count * 3);
  const skullNormal = new Float32Array(count * 3);
  const jawWeight = new Float32Array(count);
  const seed = new Float32Array(count);
  const colXZ = new Float32Array(count * 2);
  const fallSpeed = new Float32Array(count);
  const fallOffset = new Float32Array(count);

  const noise = makeNoise3D(2024);
  const p = new THREE.Vector3();
  const n = new THREE.Vector3();
  // Mouth/jaw region center, in the same local skull space proceduralSkull.js
  // builds — used to weight which points displace when the skull "speaks".
  const jawCenter = new THREE.Vector3(0, -0.85, 0.55);

  for (let i = 0; i < count; i++) {
    sampler.sample(p, n);

    skullPos[i * 3 + 0] = p.x;
    skullPos[i * 3 + 1] = p.y;
    skullPos[i * 3 + 2] = p.z;
    skullNormal[i * 3 + 0] = n.x;
    skullNormal[i * 3 + 1] = n.y;
    skullNormal[i * 3 + 2] = n.z;

    const dJaw = p.distanceTo(jawCenter);
    jawWeight[i] = Math.exp(-(dJaw * dJaw) * 2.2);

    // Blob-scale noise (rather than pure per-point random) seeds the
    // assemble/dissolve order so nearby points lock in together — an
    // organic wave sweeping across the skull instead of a uniform snap.
    const nz = noise(p.x * 1.6, p.y * 1.6, p.z * 1.6);
    seed[i] = THREE.MathUtils.clamp(nz * 0.7 + Math.random() * 0.3, 0, 1);

    const ang = Math.random() * Math.PI * 2;
    const rad = Math.sqrt(Math.random()) * fieldRadius;
    colXZ[i * 2 + 0] = Math.cos(ang) * rad;
    colXZ[i * 2 + 1] = Math.sin(ang) * rad;
    fallSpeed[i] = 0.35 + Math.random() * 0.5;
    fallOffset[i] = Math.random();
  }

  const quad = new THREE.PlaneGeometry(1, 1);
  const geometry = new THREE.InstancedBufferGeometry();
  geometry.index = quad.index;
  geometry.attributes.position = quad.attributes.position;
  geometry.attributes.uv = quad.attributes.uv;
  geometry.instanceCount = count;

  geometry.setAttribute('aSkullPos', new THREE.InstancedBufferAttribute(skullPos, 3));
  geometry.setAttribute('aSkullNormal', new THREE.InstancedBufferAttribute(skullNormal, 3));
  geometry.setAttribute('aJaw', new THREE.InstancedBufferAttribute(jawWeight, 1));
  geometry.setAttribute('aSeed', new THREE.InstancedBufferAttribute(seed, 1));
  geometry.setAttribute('aColXZ', new THREE.InstancedBufferAttribute(colXZ, 2));
  geometry.setAttribute('aFallSpeed', new THREE.InstancedBufferAttribute(fallSpeed, 1));
  geometry.setAttribute('aFallOffset', new THREE.InstancedBufferAttribute(fallOffset, 1));

  // Bounding sphere covering the whole rain field, not just the skull, so
  // three.js never frustum-culls the falling glyphs (we also set
  // frustumCulled = false on the Mesh itself as a second guard).
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(0, 0, 0), Math.max(fieldRadius, fieldHeight) + 1);

  return { geometry, count, fieldHeight };
}
