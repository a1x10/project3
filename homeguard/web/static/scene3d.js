// 3D-сцена HomeGuard: щит в центре, устройства сети на орбитах, пакеты трафика,
// вспышки на заблокированных угрозах, глобус VPN. Один canvas на всё приложение.
import * as THREE from './vendor/three.module.min.js';

const C = {
  mint: 0x3cf2b0, cyan: 0x4cc9ff, violet: 0x8b5cff, red: 0xff4d6d, amber: 0xffc24c, pink: 0xff7ad9, bg: 0x05060d,
};
export const TYPE_COLOR = {
  router: C.mint, computer: C.cyan, phone: C.violet, tv: C.amber, speaker: C.pink,
  appliance: 0x7affd4, iot: 0x9aa4ff, unknown: 0x8a90ad,
};
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

function glowTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.25, 'rgba(255,255,255,0.55)');
  grd.addColorStop(0.6, 'rgba(255,255,255,0.12)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function shieldShape() {
  const s = new THREE.Shape();
  s.moveTo(0, 1.62);
  s.bezierCurveTo(0.55, 1.28, 1.05, 1.2, 1.38, 1.2);
  s.bezierCurveTo(1.38, 0.15, 1.12, -0.95, 0, -1.62);
  s.bezierCurveTo(-1.12, -0.95, -1.38, 0.15, -1.38, 1.2);
  s.bezierCurveTo(-1.05, 1.2, -0.55, 1.28, 0, 1.62);
  return s;
}

const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => 1 - Math.pow(1 - t, 3);

export function createScene(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(C.bg, 0.028);
  const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 200);
  camera.position.set(0, 0.4, 10);
  const GLOW = glowTexture();

  scene.add(new THREE.AmbientLight(0x8899ff, 0.35));
  const l1 = new THREE.PointLight(C.cyan, 60, 30); l1.position.set(5, 4, 6); scene.add(l1);
  const l2 = new THREE.PointLight(C.violet, 50, 30); l2.position.set(-6, -3, 4); scene.add(l2);
  const l3 = new THREE.PointLight(C.mint, 25, 20); l3.position.set(0, 0, 5); scene.add(l3);

  // ---------- фон: звёзды и пыль ----------
  const stars = (() => {
    const n = 2600, pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    const palette = [new THREE.Color(0xffffff), new THREE.Color(C.cyan), new THREE.Color(C.violet), new THREE.Color(C.mint)];
    for (let i = 0; i < n; i++) {
      const r = 18 + Math.random() * 60, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      pos.set([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), r * Math.cos(ph)], i * 3);
      const c = palette[Math.random() < 0.7 ? 0 : 1 + Math.floor(Math.random() * 3)];
      col.set([c.r, c.g, c.b], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    const m = new THREE.PointsMaterial({ size: 0.12, vertexColors: true, transparent: true, opacity: 0.8,
      map: GLOW, depthWrite: false, blending: THREE.AdditiveBlending });
    return new THREE.Points(g, m);
  })();
  scene.add(stars);

  // ---------- щит ----------
  const core = new THREE.Group();
  scene.add(core);
  const shield = new THREE.Group();
  core.add(shield);
  const sGeo = new THREE.ExtrudeGeometry(shieldShape(), { depth: 0.28, bevelEnabled: true, bevelThickness: 0.09,
    bevelSize: 0.07, bevelSegments: 4, curveSegments: 48 });
  sGeo.center();
  const sMat = new THREE.MeshPhysicalMaterial({ color: 0x0c1c2a, metalness: 0.7, roughness: 0.22, clearcoat: 1,
    clearcoatRoughness: 0.15, emissive: C.mint, emissiveIntensity: 0.06, transparent: true, opacity: 0.95 });
  shield.add(new THREE.Mesh(sGeo, sMat));
  const edgeMat = new THREE.LineBasicMaterial({ color: C.mint, transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending });
  shield.add(new THREE.LineSegments(new THREE.EdgesGeometry(sGeo, 25), edgeMat));
  const check = new THREE.Mesh(
    new THREE.TubeGeometry(new THREE.CatmullRomCurve3([
      new THREE.Vector3(-0.52, 0.08, 0.27), new THREE.Vector3(-0.14, -0.32, 0.27), new THREE.Vector3(0.6, 0.48, 0.27)],
    false, 'catmullrom', 0.05), 48, 0.075, 12, false),
    new THREE.MeshBasicMaterial({ color: C.mint, transparent: true }));
  shield.add(check);
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: C.mint, transparent: true, opacity: 0.55,
    depthWrite: false, blending: THREE.AdditiveBlending }));
  halo.scale.set(7, 7, 1);
  core.add(halo);
  const inner = new THREE.Mesh(new THREE.IcosahedronGeometry(2.25, 1),
    new THREE.MeshBasicMaterial({ color: C.cyan, wireframe: true, transparent: true, opacity: 0.08 }));
  core.add(inner);

  const rings = [];
  [[2.7, C.mint, 0.9, 0.2], [3.5, C.cyan, -0.5, 0.6], [4.4, C.violet, 0.3, -0.4]].forEach(([r, col, rx, ry], i) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(r, 0.012, 8, 220),
      new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.45, blending: THREE.AdditiveBlending }));
    ring.rotation.set(Math.PI / 2 + rx, ry, 0);
    ring.userData.speed = (i % 2 ? -1 : 1) * (0.08 + i * 0.04);
    const bead = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: col, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending }));
    bead.scale.set(0.5, 0.5, 1);
    bead.position.set(r, 0, 0);
    ring.add(bead);
    core.add(ring);
    rings.push(ring);
  });

  // ---------- глобус VPN ----------
  const globe = new THREE.Group();
  globe.visible = false;
  core.add(globe);
  {
    const n = 1400, pos = new Float32Array(n * 3), R = 2.9;
    for (let i = 0; i < n; i++) {
      const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
      pos.set([Math.cos(th) * r * R, y * R, Math.sin(th) * r * R], i * 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    globe.add(new THREE.Points(g, new THREE.PointsMaterial({ size: 0.07, color: C.cyan, map: GLOW, transparent: true,
      opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending })));
    globe.userData.R = R;
  }
  const arcs = [];
  function addArc() {
    const R = globe.userData.R;
    const rnd = () => new THREE.Vector3().randomDirection().multiplyScalar(R);
    const a = rnd(), b = rnd();
    const mid = a.clone().add(b).multiplyScalar(0.5).normalize().multiplyScalar(R + 0.6 + a.distanceTo(b) * 0.35);
    const pts = new THREE.QuadraticBezierCurve3(a, mid, b).getPoints(60);
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    g.setDrawRange(0, 0);
    const line = new THREE.Line(g, new THREE.LineBasicMaterial({ color: Math.random() < 0.5 ? C.mint : C.violet,
      transparent: true, opacity: 0.9, blending: THREE.AdditiveBlending }));
    line.userData = { t: 0 };
    globe.add(line);
    arcs.push(line);
  }

  // ---------- устройства ----------
  const nodes = new Map(); // key → {group, sprite, line, data, angle, radius, tilt, speed}
  const nodeGroup = new THREE.Group();
  core.add(nodeGroup);
  const sphereGeo = new THREE.SphereGeometry(0.13, 20, 20);

  function makeNode(key, d, index, total) {
    const col = TYPE_COLOR[d.type] || TYPE_COLOR.unknown;
    const g = new THREE.Group();
    const mesh = new THREE.Mesh(sphereGeo, new THREE.MeshBasicMaterial({ color: col, transparent: true }));
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color: col, transparent: true, opacity: 0.9,
      depthWrite: false, blending: THREE.AdditiveBlending }));
    spr.scale.set(1.1, 1.1, 1);
    g.add(mesh, spr);
    const lg = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3()]);
    const line = new THREE.Line(lg, new THREE.LineBasicMaterial({ color: col, transparent: true, opacity: 0.22,
      blending: THREE.AdditiveBlending }));
    nodeGroup.add(g, line);
    const ringIdx = d.type === 'router' ? 0 : index % 3;
    const n = {
      key, group: g, mesh, sprite: spr, line, data: d,
      angle: (index / Math.max(total, 1)) * Math.PI * 2 + Math.random() * 0.3,
      radius: [3.0, 3.9, 4.8][ringIdx] + (Math.random() - 0.5) * 0.3,
      tilt: (Math.random() - 0.5) * 0.9, speed: 0.05 + Math.random() * 0.05,
      appear: 0, flash: 0, hl: 1, alive: true, baseCol: new THREE.Color(col),
    };
    g.scale.setScalar(0.001);
    nodes.set(key, n);
    return n;
  }

  function setDevices(list) {
    const keep = new Set();
    list.slice(0, 48).forEach((d, i) => {
      const key = d.ip || d.mac;
      keep.add(key);
      let n = nodes.get(key);
      if (!n) n = makeNode(key, d, i, Math.min(list.length, 48));
      else if (n.data.type !== d.type) {
        const col = new THREE.Color(TYPE_COLOR[d.type] || TYPE_COLOR.unknown);
        n.baseCol = col; n.mesh.material.color.copy(col); n.sprite.material.color.copy(col); n.line.material.color.copy(col);
      }
      n.data = d; n.alive = true;
    });
    for (const [k, n] of nodes) if (!keep.has(k)) n.alive = false;
  }

  // ---------- пакеты и вспышки ----------
  const packets = [];
  const packetPool = [];
  function packet(key, blocked = false) {
    const n = key ? nodes.get(key) : [...nodes.values()][Math.floor(Math.random() * nodes.size)];
    if (!n || !n.alive) return;
    let p = packetPool.pop();
    if (!p) {
      p = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, transparent: true, depthWrite: false,
        blending: THREE.AdditiveBlending }));
      scene.add(p);
    }
    p.visible = true;
    p.material.color.setHex(blocked ? C.red : (Math.random() < 0.5 ? C.mint : C.cyan));
    p.scale.setScalar(blocked ? 0.55 : 0.32);
    p.userData = { n, t: 0, blocked, speed: 0.55 + Math.random() * 0.4, out: !blocked && Math.random() < 0.5 };
    packets.push(p);
  }

  const bursts = [];
  function burst(pos, color, count = 22, power = 1) {
    for (let i = 0; i < count; i++) {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: GLOW, color, transparent: true, depthWrite: false,
        blending: THREE.AdditiveBlending }));
      s.position.copy(pos);
      s.scale.setScalar(0.25 + Math.random() * 0.25);
      s.userData = { v: new THREE.Vector3().randomDirection().multiplyScalar((0.8 + Math.random() * 1.6) * power), life: 1 };
      scene.add(s);
      bursts.push(s);
    }
  }
  let shieldFlash = 0;
  function threat(key) {
    packet(key, true);
  }
  function celebrate() {
    burst(core.position.clone(), C.mint, 90, 2.2);
    burst(core.position.clone(), C.cyan, 50, 1.5);
    shieldFlash = -1;
  }

  // ---------- режимы и шаги ----------
  const state = {
    step: 0, camZ: 10, camY: 0.4, coreScale: 1, globe: 0, nodesVisible: 0, focus: null, mode: 'intro',
    highlight: null, spin: 1, auto: true, dim: 0,
  };
  const target = { ...state };
  const STEPS = [
    { camZ: 10.5, camY: 0.6, coreScale: 1.15, globe: 0, nodesVisible: 0, spin: 1 },
    { camZ: 13.5, camY: 2.2, coreScale: 0.85, globe: 0, nodesVisible: 1, spin: 1 },
    { camZ: 11, camY: 0.8, coreScale: 1.05, globe: 0, nodesVisible: 1, spin: 1.6 },
    { camZ: 11.5, camY: 0.4, coreScale: 0.6, globe: 1, nodesVisible: 0, spin: 0.6 },
    { camZ: 12.5, camY: 1.8, coreScale: 0.8, globe: 0, nodesVisible: 1, spin: 1, highlight: ['tv', 'speaker', 'appliance'] },
    { camZ: 10.5, camY: 0.3, coreScale: 1.1, globe: 0, nodesVisible: 0.4, spin: 2.2 },
  ];
  function setStep(i) {
    state.step = i;
    Object.assign(target, { highlight: null }, STEPS[i] || STEPS[0]);
    if (i === 3) while (arcs.length < 14) addArc();
  }
  function setMode(mode) {
    state.mode = mode;
    if (mode === 'dash') Object.assign(target, { camZ: 13.5, camY: 3, coreScale: 0.9, globe: 0, nodesVisible: 1, spin: 1, highlight: null });
  }
  function setFocus(el) { state.focus = el; }
  function setDim(v) { target.dim = v; }

  const DEMO = [
    { ip: 'd1', type: 'router' }, { ip: 'd2', type: 'computer' }, { ip: 'd3', type: 'phone' }, { ip: 'd4', type: 'tv' },
    { ip: 'd5', type: 'speaker' }, { ip: 'd6', type: 'appliance' }, { ip: 'd7', type: 'phone' }, { ip: 'd8', type: 'computer' },
    { ip: 'd9', type: 'iot' }, { ip: 'd10', type: 'phone' },
  ];

  // ---------- мышь / наведение ----------
  const mouse = new THREE.Vector2(0, 0), mouseNdc = new THREE.Vector2(-9, -9);
  let hovered = null;
  const ray = new THREE.Raycaster();
  addEventListener('pointermove', (e) => {
    mouse.set(e.clientX / innerWidth - 0.5, e.clientY / innerHeight - 0.5);
    const r = canvas.getBoundingClientRect();
    mouseNdc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  }, { passive: true });

  // ---------- размер и смещение центра ----------
  let W = 1, H = 1;
  function resize() {
    W = canvas.clientWidth || innerWidth; H = canvas.clientHeight || innerHeight;
    renderer.setSize(W, H, false);
    camera.aspect = W / H;
    camera.updateProjectionMatrix();
  }
  addEventListener('resize', resize);
  resize();

  function applyFocus() {
    if (!state.focus || !state.focus.isConnected) { camera.clearViewOffset(); return; }
    const r = state.focus.getBoundingClientRect();
    if (!r.width) { camera.clearViewOffset(); return; }
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    camera.setViewOffset(W, H, W / 2 - cx, H / 2 - cy, W, H);
  }

  // ---------- проекция в экран (для подписей) ----------
  const tmp = new THREE.Vector3();
  function screenPositions() {
    const out = [];
    for (const n of nodes.values()) {
      if (!n.alive || n.appear < 0.5) continue;
      n.group.getWorldPosition(tmp);
      tmp.project(camera);
      if (tmp.z > 1) continue;
      out.push({ key: n.key, data: n.data, x: (tmp.x + 1) / 2 * W, y: (1 - tmp.y) / 2 * H, hovered: n === hovered });
    }
    return out;
  }

  // ---------- цикл ----------
  const clock = new THREE.Clock();
  let running = true, t = 0, demoTimer = 0;
  document.addEventListener('visibilitychange', () => { running = !document.hidden; if (running) loop(); });

  function fade(obj, k) {
    obj.traverse((o) => {
      if (!o.material) return;
      if (o.userData.base === undefined) o.userData.base = o.material.opacity ?? 1;
      o.material.opacity = o.userData.base * k;
    });
  }

  function loop() {
    if (!running) return;
    requestAnimationFrame(loop);
    const dt = Math.min(clock.getDelta(), 0.05) * (REDUCED ? 0.2 : 1);
    t += dt;
    for (const k of ['camZ', 'camY', 'coreScale', 'globe', 'nodesVisible', 'spin', 'dim']) state[k] = lerp(state[k], target[k], 1 - Math.pow(0.02, dt));

    camera.position.x = lerp(camera.position.x, mouse.x * 1.6, 0.04);
    camera.position.y = lerp(camera.position.y, state.camY - mouse.y * 1.0, 0.04);
    camera.position.z = state.camZ * (camera.aspect < 1 ? 1 + (1 - camera.aspect) * 1.4 : 1);
    camera.lookAt(0, 0, 0);
    applyFocus();

    stars.rotation.y += dt * 0.01;
    stars.rotation.x += dt * 0.003;
    core.scale.setScalar(state.coreScale);
    shield.rotation.y = Math.sin(t * 0.5) * 0.35 + mouse.x * 0.6;
    shield.rotation.x = Math.sin(t * 0.37) * 0.08 - mouse.y * 0.3;
    shield.position.y = Math.sin(t * 1.1) * 0.06;
    inner.rotation.y += dt * 0.15 * state.spin;
    inner.rotation.z += dt * 0.05;
    rings.forEach((r) => { r.rotation.z += dt * r.userData.speed * state.spin; });

    // вспышка щита
    if (shieldFlash > 0) shieldFlash = Math.max(0, shieldFlash - dt * 2.2);
    if (shieldFlash < 0) shieldFlash = Math.min(0, shieldFlash + dt * 0.8);
    const hit = Math.max(shieldFlash, 0), joy = Math.max(-shieldFlash, 0);
    edgeMat.color.setHex(C.mint).lerp(new THREE.Color(C.red), hit);
    sMat.emissive.setHex(C.mint).lerp(new THREE.Color(C.red), hit);
    sMat.emissiveIntensity = 0.06 + hit * 0.5 + joy * 0.4 + Math.sin(t * 2) * 0.02;
    halo.material.color.setHex(C.mint).lerp(new THREE.Color(C.red), hit);
    halo.material.opacity = 0.45 + hit * 0.5 + joy * 0.4 + Math.sin(t * 1.6) * 0.06;
    halo.scale.setScalar(7 + hit * 2 + joy * 3);
    check.material.color.setHex(C.mint).lerp(new THREE.Color(C.red), hit);

    // глобус
    globe.visible = state.globe > 0.02;
    if (globe.visible) {
      globe.rotation.y += dt * 0.25;
      globe.scale.setScalar(0.6 + state.globe * 0.4 / Math.max(state.coreScale, 0.3) * 0.9);
      fade(globe, state.globe);
      for (const a of arcs) {
        a.userData.t += dt * 0.45;
        const k = a.userData.t;
        const cnt = 61;
        const head = Math.min(cnt, Math.floor(ease(Math.min(k, 1)) * cnt));
        const tail = k > 1.4 ? Math.min(cnt, Math.floor(ease(Math.min(k - 1.4, 1)) * cnt)) : 0;
        a.geometry.setDrawRange(tail, head - tail);
        if (k > 2.5) { a.userData.t = Math.random() * -0.5; a.geometry.dispose(); globe.remove(a); arcs.splice(arcs.indexOf(a), 1); addArc(); }
      }
    }
    rings.forEach((r) => fade(r, 1 - state.globe * 0.7));

    // демо-устройства для знакомства
    if (state.mode === 'intro' && nodes.size === 0) setDevices(DEMO);

    // устройства
    ray.setFromCamera(mouseNdc, camera);
    let newHover = null;
    for (const n of nodes.values()) {
      const want = n.alive ? state.nodesVisible : 0;
      n.appear = lerp(n.appear, want, 1 - Math.pow(0.05, dt));
      const online = n.data.online !== false;
      n.angle += dt * n.speed * (online ? 1 : 0.3);
      const x = Math.cos(n.angle) * n.radius, z = Math.sin(n.angle) * n.radius, y = Math.sin(n.angle * 2 + n.tilt * 3) * 0.5 + n.tilt;
      n.group.position.set(x, y, z);
      const hl = target.highlight ? (target.highlight.includes(n.data.type) ? 1.8 : 0.5) : 1;
      n.flash = Math.max(0, n.flash - dt * 2);
      n.hl = lerp(n.hl, hl * (n === hovered ? 1.7 : 1), 1 - Math.pow(0.02, dt));
      const s = n.appear * (online ? 1 : 0.6) * n.hl;
      n.group.scale.setScalar(Math.max(s, 0.001));
      const col = n.baseCol.clone().lerp(new THREE.Color(C.red), n.flash);
      if (!online) col.multiplyScalar(0.45);
      n.mesh.material.color.copy(col);
      n.sprite.material.color.copy(col);
      n.sprite.material.opacity = 0.9 * n.appear * (online ? 1 : 0.4);
      n.mesh.material.opacity = n.appear;
      const lp = n.line.geometry.attributes.position;
      lp.setXYZ(1, x, y, z);
      lp.needsUpdate = true;
      n.line.material.opacity = 0.2 * n.appear * (online ? 1 : 0.35) + n.flash * 0.6;
      n.line.material.color.copy(col);
      if (!n.alive && n.appear < 0.01) {
        nodeGroup.remove(n.group, n.line); n.line.geometry.dispose(); n.mesh.material.dispose(); n.sprite.material.dispose();
        nodes.delete(n.key);
        continue;
      }
      if (state.mode === 'dash' && n.appear > 0.5 && ray.intersectObject(n.mesh).length) newHover = n;
    }
    hovered = newHover;
    canvas.style.cursor = hovered ? 'pointer' : '';

    // синтетический трафик на шагах знакомства
    demoTimer -= dt;
    if (state.mode === 'intro' && demoTimer < 0 && state.nodesVisible > 0.5) {
      demoTimer = state.step === 2 ? 0.18 : 0.12;
      packet(null, state.step === 2 && Math.random() < 0.55);
    }

    // пакеты
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i], u = p.userData;
      u.t += dt * u.speed;
      const from = u.n.group.getWorldPosition(new THREE.Vector3());
      const to = core.getWorldPosition(new THREE.Vector3());
      const k = u.out ? 1 - u.t : u.t;
      const stop = u.blocked ? 0.62 : 1;
      p.position.lerpVectors(from, to, Math.min(k, stop) * 0.97);
      p.material.opacity = Math.min(1, u.t * 4) * (u.n.appear || 0);
      if ((u.blocked && u.t >= stop) || u.t >= 1) {
        if (u.blocked) { burst(p.position, C.red, 18, 1); shieldFlash = Math.max(shieldFlash, 0.9); u.n.flash = 1; }
        p.visible = false;
        packets.splice(i, 1);
        packetPool.push(p);
      }
    }
    // осколки
    for (let i = bursts.length - 1; i >= 0; i--) {
      const s = bursts[i], u = s.userData;
      u.life -= dt * 1.4;
      s.position.addScaledVector(u.v, dt);
      u.v.multiplyScalar(1 - dt * 1.8);
      s.material.opacity = Math.max(u.life, 0);
      if (u.life <= 0) { scene.remove(s); s.material.dispose(); bursts.splice(i, 1); }
    }

    renderer.setClearColor(C.bg, 0);
    canvas.style.opacity = String(1 - state.dim * 0.6);
    renderer.render(scene, camera);
  }
  loop();

  return { setStep, setMode, setDevices, setFocus, setDim, packet, threat, celebrate, screenPositions,
    get hovered() { return hovered ? { key: hovered.key, data: hovered.data } : null; } };
}

window.HGScene = { createScene, TYPE_COLOR };
window.dispatchEvent(new Event('hg-scene-ready'));
