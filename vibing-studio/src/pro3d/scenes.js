// 3D hero scenes for the Pro templates (Three.js, loaded from a CDN inside the generated site).
// Each scene is the body of `function (ctx) { ... return (t, dt) => {} }` and receives:
//   ctx.THREE, ctx.scene, ctx.camera, ctx.renderer,
//   ctx.C = { bg, surface, text, accent, accent2 } (THREE.Color), ctx.light (light background),
//   ctx.mouse = { x, y } in -1..1 (smoothed), ctx.parallax (camera follows the mouse), ctx.target.
// Scenes keep to cheap geometry so they stay smooth on laptops and phones.

export const THREE_URL = "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.min.js";
export const THREE_ADDONS_URL = "https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/";

export const SCENES = {
  nebula: {
    name: "Галактика из частиц",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 2.4, 6.2);
const N = 7000, pos = new Float32Array(N * 3), col = new Float32Array(N * 3);
for (let i = 0; i < N; i++) {
  const r = Math.pow(Math.random(), 0.55) * 4.4, arm = (i % 3) * Math.PI * 2 / 3;
  const a = arm + r * 1.1 + (Math.random() - 0.5) * 0.7;
  pos[i*3] = Math.cos(a) * r + (Math.random() - 0.5) * 0.3;
  pos[i*3+1] = (Math.random() - 0.5) * 0.45 * (1.3 - r / 4.4);
  pos[i*3+2] = Math.sin(a) * r + (Math.random() - 0.5) * 0.3;
  const m = C.accent.clone().lerp(C.accent2, r / 4.4);
  col[i*3] = m.r; col[i*3+1] = m.g; col[i*3+2] = m.b;
}
const g = new THREE.BufferGeometry();
g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
g.setAttribute('color', new THREE.BufferAttribute(col, 3));
const pts = new THREE.Points(g, new THREE.PointsMaterial({ size: 0.032, vertexColors: true, transparent: true, opacity: 0.95, depthWrite: false, blending: ctx.light ? THREE.NormalBlending : THREE.AdditiveBlending }));
scene.add(pts);
return (t) => { pts.rotation.y = t * 0.07; pts.rotation.x = 0.18 + ctx.mouse.y * 0.12; };`,
  },

  blob: {
    name: "Жидкая капля",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 5.2);
const u = { uT: { value: 0 }, uA: { value: C.accent }, uB: { value: C.accent2 }, uL: { value: ctx.light ? 1 : 0 } };
const mat = new THREE.ShaderMaterial({ uniforms: u,
  vertexShader: \`uniform float uT; varying vec3 vN; varying vec3 vV; varying float vD;
    void main(){ vec3 p = position;
      float d = sin(p.x*2.1+uT*1.1)*sin(p.y*2.4+uT*1.3)*sin(p.z*1.9+uT*0.9);
      d += 0.5*sin(p.x*4.3-uT*1.7)*sin(p.z*3.7+uT*1.2);
      p += normal * d * 0.22; vD = d;
      vec4 mv = modelViewMatrix * vec4(p, 1.0); vV = -mv.xyz; vN = normalize(normalMatrix * normal);
      gl_Position = projectionMatrix * mv; }\`,
  fragmentShader: \`uniform vec3 uA; uniform vec3 uB; uniform float uL; varying vec3 vN; varying vec3 vV; varying float vD;
    void main(){ float f = pow(1.0 - max(dot(normalize(vN), normalize(vV)), 0.0), 2.2);
      vec3 c = mix(uA, uB, clamp(vD * 1.4 + 0.5, 0.0, 1.0));
      c = mix(c, vec3(1.0), f * (0.55 - uL * 0.25));
      gl_FragColor = vec4(c, 1.0); }\` });
const blob = new THREE.Mesh(new THREE.IcosahedronGeometry(1.55, 48), mat);
scene.add(blob);
return (t) => { u.uT.value = t; blob.rotation.y = t * 0.15 + ctx.mouse.x * 0.4; blob.rotation.x = ctx.mouse.y * 0.3; };`,
  },

  knot: {
    name: "Стеклянный узел",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 6);
const mat = new THREE.MeshPhysicalMaterial({ color: C.accent, metalness: 0.25, roughness: 0.12, clearcoat: 1, clearcoatRoughness: 0.1, iridescence: 0.8, iridescenceIOR: 1.6, sheen: 0.6, sheenColor: C.accent2 });
ctx.env(0.9);
const knot = new THREE.Mesh(new THREE.TorusKnotGeometry(1.15, 0.36, 240, 36), mat);
scene.add(knot);
scene.add(new THREE.AmbientLight(0xffffff, ctx.light ? 0.9 : 0.35));
const l1 = new THREE.PointLight(C.accent2, 40, 30); l1.position.set(4, 3, 4); scene.add(l1);
const l2 = new THREE.PointLight(0xffffff, 25, 30); l2.position.set(-4, -2, 3); scene.add(l2);
const dots = new THREE.Group();
for (let i = 0; i < 24; i++) {
  const s = new THREE.Mesh(new THREE.SphereGeometry(0.04 + Math.random() * 0.06, 16, 16), new THREE.MeshStandardMaterial({ color: i % 2 ? C.accent : C.accent2, emissive: i % 2 ? C.accent : C.accent2, emissiveIntensity: 0.6 }));
  s.position.set((Math.random() - 0.5) * 8, (Math.random() - 0.5) * 5, (Math.random() - 0.5) * 3 - 1);
  dots.add(s);
}
scene.add(dots);
return (t) => { knot.rotation.x = t * 0.2; knot.rotation.y = t * 0.28; dots.rotation.y = t * 0.03; dots.children.forEach((d, i) => d.position.y += Math.sin(t + i) * 0.0015); };`,
  },

  terrain: {
    name: "Неоновая сетка",
    code: `
const { THREE, scene, camera, C } = ctx;
ctx.parallax = false;
camera.position.set(0, 1.6, 6); camera.lookAt(0, 1, -10);
scene.fog = new THREE.Fog(C.bg, 6, 30);
const geo = new THREE.PlaneGeometry(40, 40, 90, 90); geo.rotateX(-Math.PI / 2);
const base = Float32Array.from(geo.attributes.position.array);
const grid = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: C.accent, wireframe: true, transparent: true, opacity: 0.75 }));
grid.position.z = -8; scene.add(grid);
const sun = new THREE.Mesh(new THREE.CircleGeometry(3.2, 64), new THREE.ShaderMaterial({ transparent: true, uniforms: { a: { value: C.accent2 }, b: { value: C.accent } },
  vertexShader: 'varying vec2 vU; void main(){ vU = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
  fragmentShader: 'uniform vec3 a; uniform vec3 b; varying vec2 vU; void main(){ float stripe = step(0.5, fract(vU.y * 14.0 - 0.2)) + step(0.55, vU.y); vec3 c = mix(b, a, vU.y); gl_FragColor = vec4(c, clamp(stripe, 0.0, 1.0)); }' }));
sun.position.set(0, 3.2, -22); scene.add(sun);
return (t) => {
  const p = geo.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = base[i*3], z = base[i*3+2];
    const ridge = Math.min(1, Math.abs(x) / 6);
    p.array[i*3+1] = (Math.sin(x * 0.45 + t * 0.8) * Math.cos((z + t * 3) * 0.35) * 0.9 + 0.6) * ridge * ridge * 2.2;
  }
  p.needsUpdate = true;
  camera.position.x = ctx.mouse.x * 0.8; camera.lookAt(ctx.mouse.x * 0.5, 1, -10);
};`,
  },

  crystals: {
    name: "Кристаллы",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 9);
ctx.env(0.7);
scene.add(new THREE.AmbientLight(0xffffff, ctx.light ? 0.8 : 0.25));
const d1 = new THREE.DirectionalLight(C.accent2, 3); d1.position.set(5, 5, 5); scene.add(d1);
const d2 = new THREE.DirectionalLight(C.accent, 2.5); d2.position.set(-5, -3, 2); scene.add(d2);
const shapes = [new THREE.IcosahedronGeometry(0.6, 0), new THREE.OctahedronGeometry(0.6, 0), new THREE.TetrahedronGeometry(0.7, 0), new THREE.DodecahedronGeometry(0.55, 0)];
const group = new THREE.Group(); const items = [];
for (let i = 0; i < 46; i++) {
  const m = new THREE.Mesh(shapes[i % 4], new THREE.MeshStandardMaterial({ color: C.accent.clone().lerp(C.accent2, Math.random()), metalness: 0.7, roughness: 0.18, flatShading: true }));
  const r = 2.2 + Math.random() * 4.5, a = Math.random() * Math.PI * 2;
  m.position.set(Math.cos(a) * r, (Math.random() - 0.5) * 5, Math.sin(a) * r * 0.6 - 1.5);
  m.scale.setScalar(0.4 + Math.random() * 0.9);
  m.userData = { s: 0.2 + Math.random() * 0.6, o: Math.random() * 6 };
  group.add(m); items.push(m);
}
scene.add(group);
return (t) => { group.rotation.y = t * 0.06; items.forEach((m) => { m.rotation.x += 0.004 * m.userData.s * 3; m.rotation.y += 0.006 * m.userData.s * 3; m.position.y += Math.sin(t * m.userData.s + m.userData.o) * 0.003; }); };`,
  },

  tunnel: {
    name: "Световой туннель",
    code: `
const { THREE, scene, camera, C } = ctx;
ctx.parallax = false;
scene.fog = new THREE.Fog(C.bg, 2, 40);
const rings = [];
for (let i = 0; i < 64; i++) {
  const m = new THREE.Mesh(new THREE.TorusGeometry(3, 0.035 + (i % 4 === 0 ? 0.03 : 0), 8, 96), new THREE.MeshBasicMaterial({ color: i % 2 ? C.accent : C.accent2, transparent: true, opacity: 0.85 }));
  m.position.z = -i * 1.2; m.userData.i = i; scene.add(m); rings.push(m);
}
camera.position.set(0, 0, 4);
return (t) => {
  rings.forEach((r) => {
    r.position.z += 0.06;
    if (r.position.z > 4) r.position.z -= 64 * 1.2;
    const k = r.position.z * 0.08 + t * 0.6;
    r.position.x = Math.sin(k) * 1.2; r.position.y = Math.cos(k * 0.8) * 0.8;
    r.rotation.z = t * 0.2 + r.userData.i * 0.05;
  });
  camera.position.x = ctx.mouse.x * 0.6; camera.position.y = ctx.mouse.y * 0.4; camera.lookAt(0, 0, -20);
};`,
  },

  helix: {
    name: "Спираль ДНК",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 9);
scene.add(new THREE.AmbientLight(0xffffff, ctx.light ? 1 : 0.5));
const dl = new THREE.DirectionalLight(0xffffff, 2.5); dl.position.set(3, 4, 5); scene.add(dl);
const n = 54, group = new THREE.Group();
const sph = new THREE.InstancedMesh(new THREE.SphereGeometry(0.13, 20, 20), new THREE.MeshStandardMaterial({ roughness: 0.3, metalness: 0.2 }), n * 2);
const rung = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.025, 0.025, 1, 8), new THREE.MeshStandardMaterial({ color: C.text, transparent: true, opacity: 0.35 }), n);
const o = new THREE.Object3D(), up = new THREE.Vector3(0, 1, 0);
for (let i = 0; i < n; i++) {
  const y = (i - n / 2) * 0.15, a = i * 0.34;
  const p1 = new THREE.Vector3(Math.cos(a) * 1.1, y, Math.sin(a) * 1.1), p2 = new THREE.Vector3(-Math.cos(a) * 1.1, y, -Math.sin(a) * 1.1);
  o.position.copy(p1); o.scale.setScalar(1); o.quaternion.identity(); o.updateMatrix(); sph.setMatrixAt(i * 2, o.matrix); sph.setColorAt(i * 2, C.accent);
  o.position.copy(p2); o.updateMatrix(); sph.setMatrixAt(i * 2 + 1, o.matrix); sph.setColorAt(i * 2 + 1, C.accent2);
  const dir = p2.clone().sub(p1); o.position.copy(p1).add(p2).multiplyScalar(0.5);
  o.quaternion.setFromUnitVectors(up, dir.clone().normalize()); o.scale.set(1, dir.length(), 1); o.updateMatrix(); rung.setMatrixAt(i, o.matrix);
}
group.add(sph, rung); group.rotation.z = 0.45; group.scale.setScalar(0.85); scene.add(group);
return (t) => { group.rotation.y = t * 0.35; };`,
  },

  city: {
    name: "Город",
    code: `
const { THREE, scene, camera, C } = ctx;
ctx.parallax = false;
scene.fog = new THREE.Fog(C.bg, 12, 32);
scene.add(new THREE.HemisphereLight(0xffffff, C.bg, ctx.light ? 1.6 : 0.9));
const dl = new THREE.DirectionalLight(C.accent2, 2.2); dl.position.set(6, 10, 4); scene.add(dl);
const S = 26, count = S * S;
const box = new THREE.BoxGeometry(0.8, 1, 0.8); box.translate(0, 0.5, 0);
ctx.env(0.5);
const mesh = new THREE.InstancedMesh(box, new THREE.MeshStandardMaterial({ roughness: 0.35, metalness: 0.5 }), count);
const o = new THREE.Object3D(), hs = [];
for (let i = 0; i < count; i++) {
  const x = (i % S) - S / 2, z = Math.floor(i / S) - S / 2;
  const d = Math.sqrt(x * x + z * z);
  const h = Math.max(0.2, (Math.random() * 3 + 2.5) * Math.exp(-d * 0.11)) * (Math.random() < 0.08 ? 2 : 1);
  hs.push(h);
  o.position.set(x, 0, z); o.scale.set(1, h, 1); o.updateMatrix(); mesh.setMatrixAt(i, o.matrix);
  mesh.setColorAt(i, C.surface.clone().lerp(C.accent, Math.min(0.85, h / 7)).lerp(C.accent2, h > 5 ? 0.35 : 0));
}
scene.add(mesh);
return (t) => {
  const a = t * 0.08 + ctx.mouse.x * 0.5;
  camera.position.set(Math.cos(a) * 18, 11 + ctx.mouse.y * 2, Math.sin(a) * 18); camera.lookAt(0, 1.2, 0);
  for (let i = 0; i < count; i += 7) {
    const x = (i % S) - S / 2, z = Math.floor(i / S) - S / 2;
    o.position.set(x, 0, z); o.scale.set(1, hs[i] * (0.85 + 0.15 * Math.sin(t * 1.5 + x * 0.4 + z * 0.3)), 1); o.updateMatrix(); mesh.setMatrixAt(i, o.matrix);
  }
  mesh.instanceMatrix.needsUpdate = true;
};`,
  },

  bokeh: {
    name: "Тёплое боке",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 8);
const cv = document.createElement('canvas'); cv.width = cv.height = 128;
const g2 = cv.getContext('2d'); const gr = g2.createRadialGradient(64, 64, 0, 64, 64, 64);
gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.45, 'rgba(255,255,255,0.55)'); gr.addColorStop(1, 'rgba(255,255,255,0)');
g2.fillStyle = gr; g2.fillRect(0, 0, 128, 128);
const tex = new THREE.CanvasTexture(cv); const items = [];
for (let i = 0; i < 140; i++) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, color: C.accent.clone().lerp(C.accent2, Math.random()), transparent: true, opacity: 0.12 + Math.random() * 0.5, depthWrite: false, blending: ctx.light ? THREE.NormalBlending : THREE.AdditiveBlending }));
  const z = -Math.random() * 10; s.position.set((Math.random() - 0.5) * 18, (Math.random() - 0.5) * 10, z);
  s.scale.setScalar(0.3 + Math.random() * 1.8 * (1 - z / 12)); s.userData = { v: 0.004 + Math.random() * 0.01, o: Math.random() * 6 };
  scene.add(s); items.push(s);
}
return (t) => { items.forEach((s) => { s.position.y += s.userData.v; s.position.x += Math.sin(t * 0.5 + s.userData.o) * 0.003; if (s.position.y > 6) s.position.y = -6; }); };`,
  },

  planets: {
    name: "Планетарная система",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 3.2, 8.5);
scene.add(new THREE.AmbientLight(0xffffff, ctx.light ? 0.9 : 0.25));
const sunLight = new THREE.PointLight(C.accent2, 60, 40); scene.add(sunLight);
const sys = new THREE.Group(); sys.rotation.x = 0.2; scene.add(sys);
sys.add(new THREE.Mesh(new THREE.SphereGeometry(0.7, 48, 48), new THREE.MeshBasicMaterial({ color: C.accent2 })));
const halo = new THREE.Mesh(new THREE.SphereGeometry(0.95, 48, 48), new THREE.MeshBasicMaterial({ color: C.accent2, transparent: true, opacity: 0.15 })); sys.add(halo);
const orbits = [];
for (let i = 0; i < 5; i++) {
  const r = 1.5 + i * 0.75;
  const ring = new THREE.Mesh(new THREE.RingGeometry(r - 0.005, r + 0.005, 128), new THREE.MeshBasicMaterial({ color: C.text, transparent: true, opacity: 0.18, side: THREE.DoubleSide }));
  ring.rotation.x = Math.PI / 2; sys.add(ring);
  const p = new THREE.Mesh(new THREE.SphereGeometry(0.1 + Math.random() * 0.18, 32, 32), new THREE.MeshStandardMaterial({ color: C.accent.clone().lerp(C.accent2, i / 5), roughness: 0.5 }));
  sys.add(p); orbits.push({ p, r, s: 0.5 / (1 + i * 0.6), o: Math.random() * 6 });
}
const N = 1200, sp = new Float32Array(N * 3);
for (let i = 0; i < N * 3; i++) sp[i] = (Math.random() - 0.5) * 60;
const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(sp, 3));
scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: C.text, size: 0.05, transparent: true, opacity: 0.5 })));
return (t) => { orbits.forEach((o) => { const a = t * o.s + o.o; o.p.position.set(Math.cos(a) * o.r, 0, Math.sin(a) * o.r); }); halo.scale.setScalar(1 + Math.sin(t * 1.5) * 0.05); sys.rotation.y = ctx.mouse.x * 0.3; };`,
  },

  ribbon: {
    name: "Шёлковые ленты",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 7);
scene.add(new THREE.AmbientLight(0xffffff, ctx.light ? 1.1 : 0.45));
const dl = new THREE.DirectionalLight(0xffffff, 2.6); dl.position.set(2, 4, 6); scene.add(dl);
ctx.env(0.6);
const ribbons = [];
for (let k = 0; k < 4; k++) {
  const geo = new THREE.PlaneGeometry(16, 0.7 + k * 0.15, 220, 1);
  const base = Float32Array.from(geo.attributes.position.array);
  const m = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ color: C.accent.clone().lerp(C.accent2, k / 3), side: THREE.DoubleSide, roughness: 0.3, metalness: 0.15, sheen: 1, sheenColor: C.accent2, clearcoat: 0.5, transparent: true, opacity: 0.88 }));
  m.position.y = (k - 1.5) * 0.9; m.rotation.z = -0.25; scene.add(m); ribbons.push({ geo, base, k });
}
return (t) => {
  ribbons.forEach(({ geo, base, k }) => {
    const p = geo.attributes.position;
    for (let i = 0; i < p.count; i++) {
      const x = base[i*3], y = base[i*3+1];
      p.array[i*3+1] = y + Math.sin(x * 0.55 + t * (0.8 + k * 0.15) + k) * 0.45;
      p.array[i*3+2] = Math.cos(x * 0.4 + t * 0.7 + k * 1.3) * 0.8 + y * Math.sin(x * 0.3 + t) * 0.8;
    }
    p.needsUpdate = true; geo.computeVertexNormals();
  });
};`,
  },

  gyro: {
    name: "Гироскоп",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 7);
scene.add(new THREE.AmbientLight(0xffffff, ctx.light ? 0.9 : 0.3));
const l1 = new THREE.PointLight(C.accent, 50, 30); l1.position.set(3, 3, 4); scene.add(l1);
const l2 = new THREE.PointLight(C.accent2, 50, 30); l2.position.set(-3, -2, 4); scene.add(l2);
ctx.env(0.8);
const group = new THREE.Group(); scene.add(group);
const rings = [];
for (let i = 0; i < 3; i++) {
  const r = new THREE.Mesh(new THREE.TorusGeometry(1.2 + i * 0.42, 0.07, 24, 160), new THREE.MeshStandardMaterial({ color: i === 1 ? C.accent2 : C.accent, metalness: 0.85, roughness: 0.2 }));
  group.add(r); rings.push(r);
}
const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.62, 1), new THREE.MeshStandardMaterial({ color: C.accent2, wireframe: true }));
group.add(core);
return (t) => { rings[0].rotation.x = t * 0.9; rings[1].rotation.y = t * 0.7; rings[2].rotation.x = t * 0.4; rings[2].rotation.z = t * 0.5; core.rotation.y = -t * 0.8; core.rotation.x = t * 0.3; };`,
  },

  flow: {
    name: "Потоки линий",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 9);
const L = 70, P = 160, lines = [];
for (let k = 0; k < L; k++) {
  const arr = new Float32Array(P * 3), g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(arr, 3));
  const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: C.accent.clone().lerp(C.accent2, k / L), transparent: true, opacity: 0.25 + 0.6 * Math.sin(Math.PI * k / L) }));
  scene.add(line); lines.push({ g, arr, k });
}
return (t) => {
  lines.forEach(({ g, arr, k }) => {
    const off = (k - L / 2) * 0.07;
    for (let i = 0; i < P; i++) {
      const x = (i / (P - 1) - 0.5) * 18;
      arr[i*3] = x;
      arr[i*3+1] = off + Math.sin(x * 0.35 + t * 0.6 + k * 0.04) * 1.2 * Math.cos(x * 0.12 - t * 0.3) + ctx.mouse.y * 0.3 * Math.exp(-x * x * 0.05);
      arr[i*3+2] = Math.cos(x * 0.25 + t * 0.4 + k * 0.08) * 1.5;
    }
    g.attributes.position.needsUpdate = true;
  });
};`,
  },

  globe: {
    name: "Глобус со связями",
    code: `
const { THREE, scene, camera, C } = ctx;
camera.position.set(0, 0, 7);
const globe = new THREE.Group(); globe.rotation.z = 0.35; scene.add(globe);
const N = 1800, R = 2, pos = new Float32Array(N * 3);
for (let i = 0; i < N; i++) {
  const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
  pos[i*3] = Math.cos(th) * r * R; pos[i*3+1] = y * R; pos[i*3+2] = Math.sin(th) * r * R;
}
const pg = new THREE.BufferGeometry(); pg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
globe.add(new THREE.Points(pg, new THREE.PointsMaterial({ color: C.accent, size: 0.035, transparent: true, opacity: 0.9 })));
globe.add(new THREE.Mesh(new THREE.SphereGeometry(R * 0.985, 48, 48), new THREE.MeshBasicMaterial({ color: C.bg, transparent: true, opacity: 0.6 })));
const arcs = [];
const pt = () => { const i = Math.floor(Math.random() * N); return new THREE.Vector3(pos[i*3], pos[i*3+1], pos[i*3+2]); };
for (let k = 0; k < 18; k++) {
  const a = pt(), b = pt(), mid = a.clone().add(b).multiplyScalar(0.5).normalize().multiplyScalar(R * (1.25 + a.distanceTo(b) * 0.15));
  const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
  const g = new THREE.BufferGeometry().setFromPoints(curve.getPoints(64));
  const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: C.accent2, transparent: true, opacity: 0.9 }));
  globe.add(line); arcs.push({ g, o: Math.random() * 64, s: 0.4 + Math.random() * 0.8 });
}
return (t) => { globe.rotation.y = t * 0.12 + ctx.mouse.x * 0.3; arcs.forEach((a) => { const p = (t * 30 * a.s + a.o) % 96; a.g.setDrawRange(Math.max(0, p - 32), Math.min(32, p)); }); };`,
  },
};
