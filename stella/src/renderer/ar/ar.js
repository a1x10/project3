// Stella AR: персонаж выходит из компьютера в комнату (WebXR на Android, камера на iPhone, или просто 3D).
import * as THREE from 'three';
import { Avatar } from '/js/avatar/avatar.js';
import { visemesFromSpectrum, textToVisemeTimeline, visemeAt } from '/js/core/lipsync.js';
import { parseTags } from '/js/core/tags.js';

const $ = (s) => document.querySelector(s);
const canvas = $('#c');
const avatar = new Avatar(canvas, { transparent: true, xr: true });
window.__ar = { avatar };
avatar.controls.enabled = false;
avatar.root.visible = false;

const state = { mode: null, placed: false, scale: 1, target: null, hipHeight: 0.75, sitting: false, session: null, hitSource: null, info: {} };
const reticle = new THREE.Mesh(new THREE.RingGeometry(0.09, 0.12, 40).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0x8b5cf6 }));
reticle.matrixAutoUpdate = false;
reticle.visible = false;
avatar.scene.add(reticle);
avatar.scene.add(new THREE.AmbientLight(0xffffff, 0.6));

// ---------- модель ----------
async function loadModel(url = '/model') {
  $('#s-status').textContent = 'Загружаю модель…';
  await avatar.load(url + (url.includes('?') ? '&' : '?') + 't=' + Date.now(), (p) => { $('#s-status').textContent = `Загружаю модель… ${Math.round(p * 100)}%`; });
  avatar.vrm.scene.updateMatrixWorld(true);
  const hip = new THREE.Vector3();
  avatar.vrm.humanoid.getNormalizedBoneNode('hips').getWorldPosition(hip);
  state.hipHeight = hip.y - avatar.root.position.y;
  $('#s-status').textContent = 'Готово!';
}

function setScale(s) {
  state.scale = s;
  avatar.root.scale.setScalar(s);
  $('#btn-size').textContent = s < 1 ? 'В рост' : 'Мини';
}

// ---------- связь с компьютером ----------
let audioCtx = null, analyser = null, freq = null, currentSrc = null;
function unlockAudio() {
  if (audioCtx) return;
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 1024;
  analyser.connect(audioCtx.destination);
  freq = new Uint8Array(analyser.frequencyBinCount);
}

let bubbleTimer;
function bubble(text) {
  const b = $('#bubble');
  clearTimeout(bubbleTimer);
  b.textContent = text;
  b.classList.toggle('show', !!text);
  if (text) bubbleTimer = setTimeout(() => b.classList.remove('show'), Math.max(3000, text.length * 90));
}

let talkGen = 0;
async function say({ text, audio }) {
  const { clean, emotions, actions } = parseTags(text || '');
  if (emotions[0]) avatar.setEmotion(emotions[0]);
  if (actions[0]) avatar.play(actions[0]);
  bubble(clean);
  const gen = ++talkGen;
  try { currentSrc?.stop(); } catch { /* */ }
  if (audio && audioCtx) {
    try {
      const bin = Uint8Array.from(atob(audio), (c) => c.charCodeAt(0));
      const buf = await audioCtx.decodeAudioData(bin.buffer);
      const src = audioCtx.createBufferSource();
      src.buffer = buf; src.connect(analyser); currentSrc = src;
      const loop = () => { if (gen !== talkGen) return; analyser.getByteFrequencyData(freq); avatar.setMouth(visemesFromSpectrum(freq, audioCtx.sampleRate, analyser.fftSize)); if (currentSrc === src) requestAnimationFrame(loop); };
      src.onended = () => { if (currentSrc === src) currentSrc = null; avatar.setMouth(null); };
      src.start(); loop();
      return;
    } catch { /* падаем на «немой» разговор */ }
  }
  const tl = textToVisemeTimeline(clean, 14);
  const t0 = performance.now(), total = tl[tl.length - 1].t;
  const loop = () => {
    if (gen !== talkGen) return;
    const t = (performance.now() - t0) / 1000;
    const v = visemeAt(tl, t);
    avatar.setMouth(v ? { [v]: 0.7 } : null);
    if (t < total) requestAnimationFrame(loop); else avatar.setMouth(null);
  };
  loop();
}

function connect() {
  const es = new EventSource('/events');
  es.onopen = () => $('#dot').classList.remove('off');
  es.onerror = () => $('#dot').classList.add('off');
  es.onmessage = async (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === 'hello') applyInfo(ev);
    if (ev.type === 'say') say(ev);
    if (ev.type === 'action') avatar.play(ev.name);
    if (ev.type === 'emotion') avatar.setEmotion(ev.name);
    if (ev.type === 'model') { const info = await (await fetch('/api/info')).json(); applyInfo(info); await loadModel(info.model); }
  };
}

function applyInfo(info) {
  state.info = info;
  $('#name').textContent = info.name;
  $('#s-name').textContent = info.name;
  $('#s-pre').textContent = info.persona === 'mark' ? 'твой' : 'твоя';
}

async function sendMessage() {
  const inp = $('#msg');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = '';
  bubble('…');
  avatar.play('think');
  await fetch('/api/message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }).catch(() => bubble('Нет связи с компьютером'));
}

// ---------- перемещение ----------
const tmp = new THREE.Vector3();
function cameraPos() {
  const cam = state.mode === 'xr' ? avatar.renderer.xr.getCamera() : avatar.camera;
  return cam.getWorldPosition(tmp.clone());
}

function placeAt(p) {
  avatar.root.position.copy(p);
  if (state.sitting) avatar.root.position.y -= state.hipHeight * state.scale;
  avatar.root.visible = true;
  state.placed = true;
  avatar.setEmotion('happy', 4);
  if (!state.sitting) avatar.play('wave');
  $('#hint').textContent = 'Нажми в другое место — я подойду. Кнопки внизу — действия';
}

function walkTo(p) {
  if (state.sitting) { placeAt(p); return; }
  state.target = p.clone();
  state.target.y = avatar.root.position.y;
}

avatar.onFrame = (dt) => {
  // поиск поверхности в AR
  if (state.mode === 'xr' && state.hitSource) {
    const frame = avatar.renderer.xr.getFrame();
    const ref = avatar.renderer.xr.getReferenceSpace();
    const hits = frame?.getHitTestResults(state.hitSource) || [];
    reticle.visible = hits.length > 0;
    if (hits.length) reticle.matrix.fromArray(hits[0].getPose(ref).transform.matrix);
  }
  if (!state.placed) return;
  const root = avatar.root.position;
  const cam = cameraPos();
  if (state.target) {
    const d = tmp.copy(state.target).sub(root); d.y = 0;
    const dist = d.length();
    const speed = (dist > 1.5 * state.scale ? 1.5 : 0.7) * state.scale;
    if (dist < 0.03 * state.scale) { state.target = null; avatar.locomotion = null; }
    else {
      root.addScaledVector(d.normalize(), Math.min(dist, speed * dt));
      avatar.locomotion = speed > 1 * state.scale ? 'run' : 'walk';
      avatar.faceYaw(Math.atan2(d.x, d.z));
    }
  }
  if (!state.target) avatar.faceYaw(Math.atan2(cam.x - root.x, cam.z - root.z));
};

// ---------- режимы ----------
async function startXR() {
  unlockAudio();
  const session = await navigator.xr.requestSession('immersive-ar', { requiredFeatures: ['hit-test'], optionalFeatures: ['dom-overlay', 'local-floor'], domOverlay: { root: $('#overlay') } });
  state.mode = 'xr';
  avatar.renderer.xr.setReferenceSpaceType('local');
  await avatar.renderer.xr.setSession(session);
  const viewer = await session.requestReferenceSpace('viewer');
  state.hitSource = await session.requestHitTestSource({ space: viewer });
  state.session = session;
  session.addEventListener('select', () => {
    if (!reticle.visible) return;
    const p = new THREE.Vector3().setFromMatrixPosition(reticle.matrix);
    if (!state.placed) placeAt(p); else walkTo(p);
  });
  session.addEventListener('end', exitToStart);
  showOverlay('Наведи камеру на пол или стол и нажми — я встану туда');
}

async function startFlat(withCamera) {
  unlockAudio();
  state.mode = withCamera ? 'camera' : 'flat';
  if (withCamera) {
    const v = $('#cam');
    v.srcObject = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    await v.play();
    v.style.display = 'block';
  }
  avatar.frame('full', true);
  placeAt(new THREE.Vector3(0, 0, 0));
  showOverlay('Нажми на экран — я подбегу туда');
}

function showOverlay(hint) {
  $('#start-screen').classList.add('hidden');
  $('#overlay').classList.remove('hidden');
  $('#hint').textContent = hint;
}

function exitToStart() {
  state.session = null; state.hitSource = null; state.mode = null; state.placed = false; state.target = null;
  avatar.root.visible = false;
  reticle.visible = false;
  const v = $('#cam');
  v.srcObject?.getTracks().forEach((t) => t.stop());
  v.style.display = 'none';
  $('#overlay').classList.add('hidden');
  $('#start-screen').classList.remove('hidden');
}

// касание экрана в режимах без AR — бежит к точке на «полу»
canvas.addEventListener('pointerdown', (e) => {
  if (state.mode !== 'camera' && state.mode !== 'flat') return;
  const r = canvas.getBoundingClientRect();
  const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(ndc, avatar.camera);
  const p = new THREE.Vector3();
  if (ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), p)) { p.x = Math.max(-1.2, Math.min(1.2, p.x)); p.z = Math.max(-1, Math.min(0.8, p.z)); walkTo(p); }
});

// кнопки поверх AR не должны ставить персонажа
for (const el of document.querySelectorAll('#overlay button, #overlay input')) el.addEventListener('beforexrselect', (e) => e.preventDefault());

document.querySelectorAll('[data-a]').forEach((b) => b.addEventListener('click', () => {
  const a = b.dataset.a;
  if (a === 'come') {
    const cam = cameraPos();
    const root = avatar.root.position;
    const d = new THREE.Vector3(cam.x - root.x, 0, cam.z - root.z);
    const dist = d.length();
    if (dist > 0.6 * state.scale) walkTo(root.clone().addScaledVector(d.normalize(), dist - 0.6 * state.scale));
    return;
  }
  if (a === 'sit') {
    state.sitting = !state.sitting;
    avatar.setPosture(state.sitting ? 'sit' : 'stand');
    avatar.root.position.y += (state.sitting ? -1 : 1) * state.hipHeight * state.scale;
    $('#hint').textContent = state.sitting ? 'Нажми на край стола или дивана — я сяду туда' : 'Нажми в другое место — я подойду';
    return;
  }
  avatar.play(a, a === 'dance' ? { duration: 10 } : {});
  avatar.setEmotion('happy', 3);
}));
$('#btn-size').onclick = () => setScale(state.scale < 1 ? 1 : 0.3);
$('#btn-exit').onclick = () => (state.session ? state.session.end() : exitToStart());
$('#btn-send').onclick = sendMessage;
$('#msg').addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(); });
$('#btn-ar').onclick = () => startXR().catch((e) => { $('#s-status').textContent = 'AR не запустился: ' + e.message; });
$('#btn-cam').onclick = () => startFlat(true).catch((e) => { $('#s-status').textContent = 'Нет доступа к камере: ' + e.message; });
$('#btn-3d').onclick = () => startFlat(false);

// ---------- старт ----------
(async () => {
  try {
    const info = await (await fetch('/api/info')).json();
    applyInfo(info);
    connect();
    await loadModel(info.model);
    if (navigator.xr && (await navigator.xr.isSessionSupported('immersive-ar').catch(() => false))) $('#btn-ar').classList.remove('hidden');
    else $('#s-text').textContent += ' На этом телефоне AR (WebXR) недоступен — используй режим «Через камеру».';
    window.__arReady = true;
  } catch (e) { $('#s-status').textContent = 'Ошибка: ' + e.message; }
})();
