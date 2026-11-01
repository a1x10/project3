// 3D-сцена фона (Three.js) + 3D-модель дрона для пульта.
import * as THREE from '../node_modules/three/build/three.module.js';

export class Scene3D {
  constructor(canvas) {
    this.r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    this.r.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.scene.fog = new THREE.FogExp2(0x05060d, 0.018);
    this.cam = new THREE.PerspectiveCamera(55, 1, 0.1, 400);
    this.cam.position.set(0, 0, 18);
    this.mouse = { x: 0, y: 0 };
    this.mode = 'core';
    this.t = 0;
    this.build();
    addEventListener('resize', () => this.resize());
    addEventListener('mousemove', (e) => { this.mouse.x = e.clientX / innerWidth - 0.5; this.mouse.y = e.clientY / innerHeight - 0.5; });
    this.resize();
    this.loop();
  }

  build() {
    const s = this.scene;
    s.add(new THREE.AmbientLight(0x6070ff, 0.5));
    const l1 = new THREE.PointLight(0x38e1ff, 120, 60); l1.position.set(8, 6, 10); s.add(l1);
    const l2 = new THREE.PointLight(0xff4fd8, 90, 60); l2.position.set(-10, -6, 6); s.add(l2);

    // звёзды
    const N = 2600, pos = new Float32Array(N * 3), col = new Float32Array(N * 3);
    const c = new THREE.Color();
    for (let i = 0; i < N; i++) {
      const r = 40 + Math.random() * 140, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      pos.set([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), r * Math.cos(ph)], i * 3);
      c.setHSL(0.55 + Math.random() * 0.3, 0.8, 0.6 + Math.random() * 0.4);
      col.set([c.r, c.g, c.b], i * 3);
    }
    const sg = new THREE.BufferGeometry();
    sg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    sg.setAttribute('color', new THREE.BufferAttribute(col, 3));
    this.stars = new THREE.Points(sg, new THREE.PointsMaterial({ size: 0.35, vertexColors: true, transparent: true, opacity: 0.9, sizeAttenuation: true }));
    s.add(this.stars);

    // ядро ИИ
    this.core = new THREE.Group();
    const ico = new THREE.Mesh(new THREE.IcosahedronGeometry(3.2, 1),
      new THREE.MeshBasicMaterial({ color: 0x38e1ff, wireframe: true, transparent: true, opacity: 0.35 }));
    const inner = new THREE.Mesh(new THREE.IcosahedronGeometry(2.1, 4),
      new THREE.MeshStandardMaterial({ color: 0x1a1240, emissive: 0x5b2cff, emissiveIntensity: 0.9, roughness: 0.25, metalness: 0.7, flatShading: true }));
    const glow = new THREE.Mesh(new THREE.SphereGeometry(4.6, 32, 32),
      new THREE.MeshBasicMaterial({ color: 0x8a5cff, transparent: true, opacity: 0.06, side: THREE.BackSide }));
    this.core.add(ico, inner, glow);
    this.coreIco = ico; this.coreInner = inner;
    this.rings = [];
    for (let i = 0; i < 3; i++) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(5 + i * 1.3, 0.025, 8, 160),
        new THREE.MeshBasicMaterial({ color: [0x38e1ff, 0x8a5cff, 0xff4fd8][i], transparent: true, opacity: 0.55 }));
      ring.rotation.set(Math.random() * 3, Math.random() * 3, 0);
      const sat = new THREE.Mesh(new THREE.SphereGeometry(0.13, 12, 12), new THREE.MeshBasicMaterial({ color: 0xffffff }));
      sat.position.x = 5 + i * 1.3;
      ring.add(sat);
      this.rings.push(ring); this.core.add(ring);
    }
    s.add(this.core);

    // 3D-плата (появляется на шаге выбора платы)
    this.board = makeBoard();
    this.board.visible = false;
    s.add(this.board);

    // сетка-«пол»
    const grid = new THREE.GridHelper(200, 80, 0x2b2f6a, 0x15183a);
    grid.position.y = -9; grid.material.transparent = true; grid.material.opacity = 0.35;
    this.grid = grid; s.add(grid);
  }

  setMode(m) { this.mode = m; this.board.visible = m === 'board'; }
  pulse() { this.pulseT = 1; }

  resize() {
    this.r.setSize(innerWidth, innerHeight, false);
    this.cam.aspect = innerWidth / innerHeight;
    this.cam.updateProjectionMatrix();
  }

  loop() {
    requestAnimationFrame(() => this.loop());
    if (document.hidden) return;
    this.t += 0.01;
    const t = this.t;
    this.stars.rotation.y = t * 0.02;
    this.coreIco.rotation.set(t * 0.3, t * 0.4, 0);
    this.coreInner.rotation.set(-t * 0.2, t * 0.25, 0);
    this.rings.forEach((r, i) => { r.rotation.z += 0.004 * (i + 1); r.rotation.x += 0.0015; });
    this.pulseT = Math.max(0, (this.pulseT || 0) - 0.02);
    const sc = 1 + Math.sin(t * 2) * 0.03 + (this.pulseT || 0) * 0.25;
    this.core.scale.setScalar(sc);

    const target = {
      core: [0, 0, 18], board: [6, 1, 20], dash: [9, -1, 26], splash: [0, 0, 14],
    }[this.mode] || [0, 0, 18];
    this.core.position.x += ((this.mode === 'board' ? -7 : this.mode === 'dash' ? 7 : 0) - this.core.position.x) * 0.04;
    this.cam.position.x += (target[0] + this.mouse.x * 3 - this.cam.position.x) * 0.04;
    this.cam.position.y += (target[1] - this.mouse.y * 2 - this.cam.position.y) * 0.04;
    this.cam.position.z += (target[2] - this.cam.position.z) * 0.04;
    this.cam.lookAt(0, 0, 0);
    if (this.board.visible) { this.board.rotation.y = t * 0.5; this.board.rotation.x = 0.5 + Math.sin(t) * 0.1; }
    this.grid.position.z = (t * 4) % 2.5;
    this.r.render(this.scene, this.cam);
  }
}

function makeBoard() {
  const g = new THREE.Group();
  const pcb = new THREE.Mesh(new THREE.BoxGeometry(6, 0.16, 4),
    new THREE.MeshStandardMaterial({ color: 0x0b6b4a, roughness: 0.5, metalness: 0.3, emissive: 0x032a1c }));
  g.add(pcb);
  const metal = new THREE.MeshStandardMaterial({ color: 0xc8ccd8, metalness: 0.9, roughness: 0.25 });
  const chip = new THREE.MeshStandardMaterial({ color: 0x15151c, metalness: 0.4, roughness: 0.4 });
  const add = (geo, mat, x, y, z) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); g.add(m); return m; };
  add(new THREE.BoxGeometry(1.3, 0.18, 1.3), chip, -0.6, 0.17, 0.1);                        // SoC
  add(new THREE.BoxGeometry(1.0, 0.12, 0.7), chip, 0.9, 0.14, 0.4);                         // RAM
  add(new THREE.BoxGeometry(0.9, 0.7, 0.7), metal, 2.6, 0.43, 1.2);                         // Ethernet
  add(new THREE.BoxGeometry(0.9, 0.6, 0.6), metal, 2.6, 0.38, 0.1);                         // USB
  add(new THREE.BoxGeometry(0.9, 0.6, 0.6), metal, 2.6, 0.38, -0.9);                        // USB
  for (let i = 0; i < 20; i++) for (let j = 0; j < 2; j++)
    add(new THREE.BoxGeometry(0.08, 0.35, 0.08), new THREE.MeshStandardMaterial({ color: 0xd4af37, metalness: 1, roughness: 0.3 }), -2.6 + i * 0.25, 0.25, -1.75 + j * 0.25);
  const led = add(new THREE.SphereGeometry(0.06, 8, 8), new THREE.MeshBasicMaterial({ color: 0x3dffa8 }), -2.7, 0.15, 1.7);
  led.userData.led = true;
  const wire = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(6.2, 0.2, 4.2)),
    new THREE.LineBasicMaterial({ color: 0x38e1ff, transparent: true, opacity: 0.6 }));
  g.add(wire);
  g.position.set(5, 0, 0);
  g.scale.setScalar(1.25);
  return g;
}

// 3D-модель дрона: показывает крен/тангаж/рыскание из телеметрии.
export class Drone3D {
  constructor(container) {
    this.el = container;
    this.r = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.r.setPixelRatio(Math.min(devicePixelRatio, 2));
    container.appendChild(this.r.domElement);
    this.scene = new THREE.Scene();
    this.cam = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    this.cam.position.set(0, 3.2, 6.5);
    this.cam.lookAt(0, 0, 0);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const d = new THREE.DirectionalLight(0xffffff, 2); d.position.set(3, 6, 4); this.scene.add(d);
    const p = new THREE.PointLight(0x38e1ff, 30, 20); p.position.set(-3, 2, 3); this.scene.add(p);
    this.drone = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.35, 1.5), new THREE.MeshStandardMaterial({ color: 0x1b1f3a, metalness: 0.7, roughness: 0.3 }));
    const top = new THREE.Mesh(new THREE.SphereGeometry(0.45, 24, 12, 0, Math.PI * 2, 0, Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0x8a5cff, metalness: 0.5, roughness: 0.2, emissive: 0x2a1060 }));
    top.position.y = 0.17;
    const camM = new THREE.Mesh(new THREE.SphereGeometry(0.18, 16, 16), new THREE.MeshStandardMaterial({ color: 0x050505, metalness: 1, roughness: 0.1 }));
    camM.position.set(0, -0.15, 0.75);
    this.drone.add(body, top, camM);
    this.props = [];
    const arm = new THREE.MeshStandardMaterial({ color: 0x2a2f55, metalness: 0.6, roughness: 0.4 });
    [[1, 1], [-1, 1], [1, -1], [-1, -1]].forEach(([x, z], i) => {
      const a = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.06, 2.0), arm);
      a.rotation.z = Math.PI / 2; a.rotation.y = Math.atan2(z, x) * -1;
      a.position.set(x * 0.7, 0, z * 0.7);
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 0.22, 16), new THREE.MeshStandardMaterial({ color: 0x777c99, metalness: 0.9, roughness: 0.2 }));
      motor.position.set(x * 1.4, 0.08, z * 1.4);
      const prop = new THREE.Mesh(new THREE.CylinderGeometry(0.62, 0.62, 0.02, 32), new THREE.MeshBasicMaterial({ color: i < 2 ? 0x38e1ff : 0xff4fd8, transparent: true, opacity: 0.35 }));
      prop.position.set(x * 1.4, 0.22, z * 1.4);
      this.props.push(prop);
      this.drone.add(a, motor, prop);
    });
    this.scene.add(this.drone);
    const grid = new THREE.GridHelper(12, 24, 0x38e1ff, 0x1d2250); grid.position.y = -1.3; grid.material.transparent = true; grid.material.opacity = 0.4;
    this.scene.add(grid);
    this.grid = grid;
    this.att = { roll: 0, pitch: 0, yaw: 0, alt: 0, armed: false };
    this.ro = new ResizeObserver(() => this.resize()); this.ro.observe(container);
    this.resize();
    this.alive = true;
    this.loop();
  }
  set(t) { Object.assign(this.att, t); }
  resize() {
    const w = this.el.clientWidth || 300, h = this.el.clientHeight || 200;
    this.r.setSize(w, h); this.cam.aspect = w / h; this.cam.updateProjectionMatrix();
  }
  loop() {
    if (!this.alive) return;
    requestAnimationFrame(() => this.loop());
    const a = this.att, k = Math.PI / 180;
    this.drone.rotation.z += (-(a.roll || 0) * k - this.drone.rotation.z) * 0.15;
    this.drone.rotation.x += ((a.pitch || 0) * k - this.drone.rotation.x) * 0.15;
    this.drone.rotation.y += (-(a.yaw || 0) * k - this.drone.rotation.y) * 0.1;
    this.drone.position.y = Math.min(1.2, (a.alt || 0) * 0.08) + Math.sin(performance.now() / 600) * 0.04;
    const spin = a.armed ? 0.9 : 0.02;
    this.props.forEach((p, i) => { p.rotation.y += i % 2 ? spin : -spin; p.material.opacity = a.armed ? 0.55 : 0.25; });
    this.r.render(this.scene, this.cam);
  }
  dispose() { this.alive = false; this.ro.disconnect(); this.r.dispose(); this.r.domElement.remove(); }
}
