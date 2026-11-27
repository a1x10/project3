import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { CLIPS, clipPose, restPose, idleLayer, sitPose, SIT_SAFE, blendPoses, mergePoses, toVrm0, BONES, FINGERS } from './poses.js';
import { ExpressionMixer, Blinker, EMOTION_GESTURE } from './expressions.js';
import { LipSmoother, VISEMES } from '../core/lipsync.js';

const THEMES = {
  cosmos: { stars: 0xffffff, fog: 0x0b0820, rim: 0xa78bfa, floor: 0x8b5cf6 },
  aurora: { stars: 0xb6fff0, fog: 0x04161a, rim: 0x2dd4bf, floor: 0x14b8a6 },
  sunset: { stars: 0xffe1c4, fog: 0x1d0a12, rim: 0xfb7185, floor: 0xf97316 },
  ocean: { stars: 0xcfe8ff, fog: 0x061226, rim: 0x38bdf8, floor: 0x3b82f6 },
  minimal: { stars: 0x9ca3af, fog: 0x0d0d12, rim: 0xe5e7eb, floor: 0x6b7280 },
};

export class Avatar {
  constructor(canvas, { transparent = false, compact = false, xr = false } = {}) {
    this.canvas = canvas;
    this.compact = compact;
    this.xr = xr;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
    if (xr) this.renderer.xr.enabled = true;
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x000000, 0);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(compact ? 28 : 30, 1, 0.05, 100);
    this.camera.position.set(0, 1.3, 3.2);
    this.controls = new OrbitControls(this.camera, canvas);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.08, enablePan: false, minDistance: 0.6, maxDistance: 6, minPolarAngle: 0.35, maxPolarAngle: 1.75, rotateSpeed: 0.6 });
    this.controls.enabled = !compact && !xr;
    /** Группа, в которой стоит персонаж: её двигают, чтобы поставить его в комнате (AR). */
    this.root = new THREE.Group();

    this.clock = new THREE.Clock();
    this.time = 0;
    this.vrm = null;
    this.isVrm0 = false;
    this.clip = null; // {name, t, variant, weight}
    this.mixer = new ExpressionMixer();
    this.blinker = new Blinker();
    this.lip = new LipSmoother();
    this.mouthTarget = null;
    this.look = { x: 0, y: 0, tx: 0, ty: 0 };
    this.intensity = 1;
    this.idleEnabled = true;
    this.framing = 'full';
    this.posture = 'stand';
    this.facing = 0; this.facingTarget = 0;
    this.locomotion = null; // 'walk' | 'run' | null
    this.listeners = {};
    this.hipsBase = null;
    this._raycaster = new THREE.Raycaster();
    this._buildEnvironment(transparent);
    this._bindPointer();
    this._resize();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(canvas.parentElement || canvas);
    this.renderer.setAnimationLoop(() => this._tick());
  }

  on(ev, cb) { (this.listeners[ev] ||= []).push(cb); }
  _emit(ev, p) { for (const cb of this.listeners[ev] || []) cb(p); }

  _buildEnvironment(transparent) {
    const s = this.scene;
    this.hemi = new THREE.HemisphereLight(0xffffff, 0x303050, 1.4);
    s.add(this.hemi);
    this.key = new THREE.DirectionalLight(0xffffff, 2.2);
    this.key.position.set(1.2, 2.5, 2.5);
    s.add(this.key);
    this.rim = new THREE.DirectionalLight(0xa78bfa, 2.5);
    this.rim.position.set(-2, 2, -2.5);
    s.add(this.rim);
    this.fill = new THREE.PointLight(0x60a5fa, 3, 6);
    this.fill.position.set(-1.5, 1.2, 1.5);
    s.add(this.fill);

    this.envGroup = new THREE.Group();
    s.add(this.envGroup);
    s.add(this.root);
    if (transparent) return;
    // звёзды
    const N = 1800, pos = new Float32Array(N * 3), sizes = new Float32Array(N);
    for (let i = 0; i < N; i++) {
      const r = 12 + Math.random() * 30, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      pos[i * 3] = r * Math.sin(ph) * Math.cos(th); pos[i * 3 + 1] = Math.abs(r * Math.cos(ph)) * 0.8 - 2; pos[i * 3 + 2] = r * Math.sin(ph) * Math.sin(th) - 6;
      sizes[i] = Math.random();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('size', new THREE.BufferAttribute(sizes, 1));
    this.starMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(0xffffff) } },
      vertexShader: 'attribute float size; uniform float uTime; varying float vA; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); gl_Position = projectionMatrix*mv; float tw = 0.55+0.45*sin(uTime*(1.0+size*2.0)+size*40.0); vA = tw*(0.35+size*0.65); gl_PointSize = (1.2+size*2.6)*(300.0/-mv.z)*0.12; }',
      fragmentShader: 'uniform vec3 uColor; varying float vA; void main(){ float d = length(gl_PointCoord-0.5); float a = smoothstep(0.5,0.0,d); gl_FragColor = vec4(uColor, a*vA); }',
    });
    this.stars = new THREE.Points(g, this.starMat);
    this.envGroup.add(this.stars);
    // светящийся круг под ногами
    const ringMat = new THREE.ShaderMaterial({
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
      uniforms: { uTime: { value: 0 }, uColor: { value: new THREE.Color(0x8b5cf6) } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
      fragmentShader: 'uniform float uTime; uniform vec3 uColor; varying vec2 vUv; void main(){ float d = length(vUv-0.5)*2.0; float ring = smoothstep(0.08,0.0,abs(d-0.78-0.03*sin(uTime*1.5))); float glow = smoothstep(1.0,0.0,d)*0.35; float a = (ring*0.9+glow)*smoothstep(1.0,0.9,d); gl_FragColor = vec4(uColor, a); }',
    });
    this.ringMat = ringMat;
    const ring = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 1.6), ringMat);
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.002;
    this.envGroup.add(ring);
    // парящие частицы
    const M = 120, p2 = new Float32Array(M * 3);
    for (let i = 0; i < M; i++) { p2[i * 3] = (Math.random() - 0.5) * 4; p2[i * 3 + 1] = Math.random() * 2.6; p2[i * 3 + 2] = (Math.random() - 0.5) * 3 - 0.5; }
    const g2 = new THREE.BufferGeometry(); g2.setAttribute('position', new THREE.BufferAttribute(p2, 3));
    this.dustMat = new THREE.PointsMaterial({ size: 0.025, color: 0xc4b5fd, transparent: true, opacity: 0.6, depthWrite: false, blending: THREE.AdditiveBlending });
    this.dust = new THREE.Points(g2, this.dustMat);
    this.envGroup.add(this.dust);
  }

  setTheme(name) {
    const t = THEMES[name] || THEMES.cosmos;
    this.rim.color.setHex(t.rim);
    if (this.starMat) this.starMat.uniforms.uColor.value.setHex(t.stars);
    if (this.ringMat) this.ringMat.uniforms.uColor.value.setHex(t.floor);
    if (this.dustMat) this.dustMat.color.setHex(t.rim);
  }

  _resize() {
    if (this.renderer.xr.isPresenting) return;
    const el = this.canvas.parentElement || this.canvas;
    const w = Math.max(1, el.clientWidth), h = Math.max(1, el.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (this.vrm && !this._camAnim) this.frame(this.framing, true);
  }

  _bindPointer() {
    let down = null;
    this.canvas.addEventListener('pointerdown', (e) => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; });
    this.canvas.addEventListener('pointerup', (e) => {
      if (!down || !this.vrm) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      if (moved > 6 || performance.now() - down.t > 500) return;
      const r = this.canvas.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      this._raycaster.setFromCamera(ndc, this.camera);
      const hit = this._raycaster.intersectObject(this.vrm.scene, true)[0];
      if (!hit) return;
      const headY = this._bonePos('head').y;
      const part = hit.point.y > headY - 0.02 ? 'head' : hit.point.y > headY - 0.45 ? 'body' : 'legs';
      this._emit('touch', { part, point: hit.point });
    });
  }

  /** Попадает ли точка экрана в модель. */
  hitTest(clientX, clientY) {
    if (!this.vrm) return false;
    const r = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1);
    this._raycaster.setFromCamera(ndc, this.camera);
    return this._raycaster.intersectObject(this.vrm.scene, true).length > 0;
  }

  _bonePos(name) {
    const n = this.vrm?.humanoid?.getNormalizedBoneNode(name);
    const v = new THREE.Vector3();
    if (n) n.getWorldPosition(v);
    return v;
  }

  async load(url, onProgress) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url, (e) => { if (e.total) onProgress?.(e.loaded / e.total); });
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('Файл не является VRM-моделью');
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    VRMUtils.combineSkeletons?.(gltf.scene);
    this.isVrm0 = vrm.meta?.metaVersion === '0';
    if (this.isVrm0) VRMUtils.rotateVRM0(vrm);
    vrm.scene.traverse((o) => { o.frustumCulled = false; });
    if (this.vrm) { this.root.remove(this.vrm.scene); VRMUtils.deepDispose(this.vrm.scene); }
    this.vrm = vrm;
    this.root.add(vrm.scene);
    const hips = vrm.humanoid.getNormalizedBoneNode('hips');
    this.hipsBase = hips.position.clone();
    this.exprNames = new Set(Object.keys(vrm.expressionManager?.expressionMap || {}));
    this.clip = null;
    // поза покоя сразу, чтобы не мелькала Т-поза
    this._applyPose(mergePoses(restPose(), idleLayer(0, 0)));
    vrm.update(0);
    this.height = this._bonePos('head').y + 0.15;
    this.frame(this.framing, true);
    return vrm;
  }

  frame(mode = 'full', instant = false) {
    this.framing = mode;
    const h = this.height || 1.6;
    let target, pos;
    if (mode === 'portrait') { target = new THREE.Vector3(0, h - 0.22, 0); pos = new THREE.Vector3(0, h - 0.15, 1.15); }
    else if (mode === 'upper') { target = new THREE.Vector3(0, h * 0.72, 0); pos = new THREE.Vector3(0, h * 0.75, 2.0); }
    else {
      // отступаем дальше, если окно узкое, чтобы жесты руками не обрезались
      const halfW = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * Math.max(0.3, this.camera.aspect);
      const dist = Math.max(h * 2.6, 0.62 / halfW) + (this.compact ? 0.4 : 0);
      target = new THREE.Vector3(0, h * 0.5, 0); pos = new THREE.Vector3(0.0, h * 0.56, dist);
    }
    if (instant) { this.camera.position.copy(pos); this.controls.target.copy(target); }
    else this._camAnim = { from: this.camera.position.clone(), to: pos, tFrom: this.controls.target.clone(), tTo: target, t: 0 };
    this.controls.update();
  }

  /** Запустить действие тела. */
  play(name, opts = {}) {
    if (this.posture === 'sit' && name in SIT_SAFE) { name = SIT_SAFE[name]; if (!name) return false; }
    if (!CLIPS[name]) return false;
    const variant = name === 'dance' ? (opts.variant ?? Math.floor(Math.random() * 3)) : 0;
    const dur = name === 'dance' ? (opts.duration || 8) : CLIPS[name].duration;
    this.clip = { name, t: 0, variant, weight: 0, duration: dur, loop: !!opts.loop };
    this._emit('action', name);
    return true;
  }
  stop() { if (this.clip) this.clip.stopping = true; }

  /** Поза тела: стоять или сидеть. */
  setPosture(p) { this.posture = p === 'sit' ? 'sit' : 'stand'; if (this.posture === 'sit') { this.locomotion = null; this.facingTarget = 0.5; } else if (!this.locomotion) this.facingTarget = 0; this._emit('posture', this.posture); }

  /** Ходьба/бег на месте с поворотом в сторону движения (dir: -1 влево, 1 вправо, 0 — к зрителю). */
  move(kind, dir = 0) {
    this.locomotion = kind || null;
    this.facingTarget = kind ? (dir > 0 ? Math.PI / 2 : dir < 0 ? -Math.PI / 2 : 0) : 0;
  }

  /** Повернуть корпус на угол (рад, 0 — лицом к камере/зрителю по +Z). */
  faceYaw(angle) { this.facingTarget = angle; }

  /** Экранная точка кости в пикселях относительно canvas. */
  screenPointOf(bone = 'hips') {
    const p = this._bonePos(bone);
    if (!this.vrm) return null;
    p.project(this.camera);
    const r = this.canvas.getBoundingClientRect();
    return { x: (p.x + 1) / 2 * r.width, y: (1 - p.y) / 2 * r.height };
  }
  get currentAction() { return this.clip?.name || null; }

  setEmotion(name, hold = 7) {
    const ok = this.mixer.set(name, this.time, hold);
    if (ok) this._emit('emotion', name);
    if (ok && !this.clip && EMOTION_GESTURE[name] && Math.random() < 0.5) this.play(EMOTION_GESTURE[name]);
    return ok;
  }

  /** Веса гласных от плеера речи (или null — рот закрыт). */
  setMouth(v) { this.mouthTarget = v; }

  /** Куда смотреть: x,y в диапазоне -1..1 относительно экрана. */
  lookAt(x, y) { this.look.tx = Math.max(-1, Math.min(1, x)); this.look.ty = Math.max(-1, Math.min(1, y)); }

  _setExpr(name, v) {
    const em = this.vrm?.expressionManager;
    if (!em) return;
    if (this.exprNames.has(name)) em.setValue(name, v);
    else if (name === 'surprised' && this.exprNames.has('Surprised')) em.setValue('Surprised', v);
  }

  _applyPose(pose) {
    const h = this.vrm.humanoid;
    for (const bone of this._bones || (this._bones = [...BONES, ...FINGERS])) {
      const node = h.getNormalizedBoneNode(bone);
      if (!node) continue;
      const r = pose[bone] || [0, 0, 0];
      const [x, y, z] = this.isVrm0 ? toVrm0(r) : r;
      node.rotation.set(x, y, z);
    }
    const hips = h.getNormalizedBoneNode('hips');
    if (hips && this.hipsBase) {
      const p = pose.hipsPos || [0, 0, 0];
      const [x, y, z] = this.isVrm0 ? [-p[0], p[1], -p[2]] : p;
      hips.position.set(this.hipsBase.x + x, this.hipsBase.y + y, this.hipsBase.z + z);
    }
  }

  _tick() {
    const dt = Math.min(0.05, this.clock.getDelta());
    this.time += dt;
    const t = this.time;
    if (this.starMat) { this.starMat.uniforms.uTime.value = t; this.ringMat.uniforms.uTime.value = t; this.stars.rotation.y = t * 0.004; }
    if (this.dust) { this.dust.rotation.y = t * 0.03; this.dust.position.y = Math.sin(t * 0.4) * 0.05; }
    if (this._camAnim) {
      const a = this._camAnim; a.t = Math.min(1, a.t + dt * 1.8);
      const k = a.t * a.t * (3 - 2 * a.t);
      this.camera.position.lerpVectors(a.from, a.to, k); this.controls.target.lerpVectors(a.tFrom, a.tTo, k);
      if (a.t >= 1) this._camAnim = null;
    }
    if (!this.xr) this.controls.update();
    this.onFrame?.(dt);
    if (this.vrm) {
      // поза
      let base = mergePoses(restPose(), this.idleEnabled ? idleLayer(t, this.intensity) : {});
      if (this.posture === 'sit') base = mergePoses(base, sitPose(t));
      else if (this.locomotion) base = mergePoses(base, clipPose(this.locomotion, t));
      // разворот корпуса по направлению движения
      let df = this.facingTarget - this.facing;
      df = Math.atan2(Math.sin(df), Math.cos(df));
      this.facing += df * (1 - Math.exp(-dt * 8));
      this.vrm.scene.rotation.y = (this.isVrm0 ? Math.PI : 0) + this.facing;
      let pose = base;
      if (this.clip) {
        const c = this.clip;
        c.t += dt;
        const ending = c.stopping || (!c.loop && c.t >= c.duration - 0.35);
        c.weight += ((ending ? 0 : 1) - c.weight) * (1 - Math.exp(-dt * 7));
        const cp = clipPose(c.name, c.t, c.variant);
        const scaled = {};
        for (const [k, v] of Object.entries(cp)) scaled[k] = v.map((x, i) => (k === 'hipsPos' ? x * this.intensity : (base[k]?.[i] || 0) + (x - (base[k]?.[i] || 0)) * Math.min(1, this.intensity)));
        pose = blendPoses(base, scaled, c.weight);
        if ((ending && c.weight < 0.02) || (!c.loop && c.t > c.duration + 0.5)) { this.clip = null; this._emit('actionEnd', c.name); }
      }
      // взгляд/голова к курсору
      this.look.x += (this.look.tx - this.look.x) * (1 - Math.exp(-dt * 4));
      this.look.y += (this.look.ty - this.look.y) * (1 - Math.exp(-dt * 4));
      const lookW = this.clip && /dance|spin|bow|jump|sleepy/.test(this.clip.name) ? 0.2 : 1;
      const head = pose.head || [0, 0, 0], neck = pose.neck || [0, 0, 0];
      pose.head = [head[0] - this.look.y * 0.25 * lookW, head[1] + this.look.x * 0.45 * lookW, head[2]];
      pose.neck = [neck[0] - this.look.y * 0.1 * lookW, neck[1] + this.look.x * 0.2 * lookW, neck[2]];
      this._applyPose(pose);
      // глаза
      if (this.vrm.lookAt) {
        this.vrm.lookAt.autoUpdate = false;
        this.vrm.lookAt.yaw = this.look.x * 18;
        this.vrm.lookAt.pitch = this.look.y * 12;
      }
      // лицо
      const mouth = this.lip.update(this.mouthTarget, dt);
      const speaking = Math.max(...VISEMES.map((k) => mouth[k]));
      const emo = this.mixer.update(t, dt, speaking);
      for (const [k, v] of Object.entries(emo)) this._setExpr(k, v);
      for (const k of VISEMES) this._setExpr(k, mouth[k]);
      const blink = this.blinker.update(t, emo.happy > 0.6 || emo.surprised > 0.5);
      this._setExpr('blink', blink * (1 - emo.happy));
      this.vrm.update(dt);
    }
    this.renderer.render(this.scene, this.camera);
  }

  /** Снимок кадра (для тестов и превью). */
  snapshot() { this.renderer.render(this.scene, this.camera); return this.canvas.toDataURL('image/png'); }

  dispose() {
    this.renderer.setAnimationLoop(null);
    this._ro.disconnect();
    if (this.vrm) VRMUtils.deepDispose(this.vrm.scene);
    this.renderer.dispose();
  }
}
