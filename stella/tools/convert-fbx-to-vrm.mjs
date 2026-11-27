#!/usr/bin/env node
// Конвертация FBX-модели (скелет AdvancedSkeleton) в VRM 1.0 для Stella.
// node tools/convert-fbx-to-vrm.mjs  → assets/models/nick.vrm
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright-core';
import { parseGLB } from './glb-writer.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SRC = 'tools/source/nick';

// AdvancedSkeleton → гуманоид VRM 1.0 (_L — левая сторона персонажа)
export const BONE_MAP = {
  hips: 'Root_M', spine: 'Spine1_M', chest: 'Spine2_M', upperChest: 'Chest_M', neck: 'Neck_M', head: 'Head_M',
  leftShoulder: 'Scapula_L', leftUpperArm: 'Shoulder_L', leftLowerArm: 'Elbow_L', leftHand: 'Wrist_L',
  rightShoulder: 'Scapula_R', rightUpperArm: 'Shoulder_R', rightLowerArm: 'Elbow_R', rightHand: 'Wrist_R',
  leftUpperLeg: 'Hip_L', leftLowerLeg: 'Knee_L', leftFoot: 'Ankle_L', leftToes: 'Toes_L',
  rightUpperLeg: 'Hip_R', rightLowerLeg: 'Knee_R', rightFoot: 'Ankle_R', rightToes: 'Toes_R',
  leftMiddleProximal: 'MiddleFinger1_L', rightMiddleProximal: 'MiddleFinger1_R',
  leftThumbMetacarpal: 'ThumbFinger1_L', leftThumbProximal: 'ThumbFinger2_L',
  rightThumbMetacarpal: 'ThumbFinger1_R', rightThumbProximal: 'ThumbFinger2_R',
};

function expressionsFor(json, targets) {
  const node = json.nodes.findIndex((n) => n.name === 'Mouth' && n.mesh !== undefined);
  const preset = {};
  if (node < 0) return preset;
  targets.forEach((t, i) => { preset[t] = { morphTargetBinds: [{ node, index: i, weight: 1 }], isBinary: false, overrideMouth: 'none', overrideBlink: 'none', overrideLookAt: 'none' }; });
  return preset;
}

function serve() {
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png', '.fbx': 'application/octet-stream' };
  const srv = http.createServer((req, res) => {
    const p = path.join(ROOT, decodeURIComponent(req.url.split('?')[0]));
    if (!p.startsWith(ROOT) || !fs.existsSync(p)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': types[path.extname(p)] || 'application/octet-stream' });
    fs.createReadStream(p).pipe(res);
  });
  return new Promise((r) => srv.listen(0, '127.0.0.1', () => r(srv)));
}

export function buildVrmFromGlb(glbBuf, { name = 'Mark (Nick)', boneMap = BONE_MAP, mouthTargets = [] } = {}) {
  const { json, bin } = parseGLB(glbBuf);
  const find = (bone) => json.nodes.findIndex((n) => n.name === bone || n.name?.endsWith(':' + bone) || n.name?.endsWith(bone) && n.name.replace(/^.*?[:_]?Nick[:_]?/, '') === bone);
  const humanBones = {};
  const missing = [];
  for (const [vrm, src] of Object.entries(boneMap)) { const i = find(src); if (i >= 0) humanBones[vrm] = { node: i }; else missing.push(src); }
  json.extensionsUsed = [...new Set([...(json.extensionsUsed || []), 'VRMC_vrm'])];
  json.extensions = { ...(json.extensions || {}), VRMC_vrm: {
    specVersion: '1.0',
    meta: { name, version: '1.0', authors: ['Imported via Stella converter'], licenseUrl: 'https://vrm.dev/licenses/1.0/', avatarPermission: 'onlyAuthor', commercialUsage: 'personalNonProfit', creditNotation: 'required', allowRedistribution: false, modification: 'prohibited', allowExcessivelyViolentUsage: false, allowExcessivelySexualUsage: false, allowPoliticalOrReligiousUsage: false, allowAntisocialOrHateUsage: false },
    humanoid: { humanBones },
    expressions: { preset: expressionsFor(json, mouthTargets) },
  } };
  // собираем GLB заново
  let jsonStr = JSON.stringify(json); while (Buffer.byteLength(jsonStr) % 4) jsonStr += ' ';
  const jb = Buffer.from(jsonStr);
  const pad = (4 - (bin.length % 4)) % 4;
  const bb = Buffer.concat([bin, Buffer.alloc(pad)]);
  const head = Buffer.alloc(12); head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(12 + 8 + jb.length + 8 + bb.length, 8);
  const c1 = Buffer.alloc(8); c1.writeUInt32LE(jb.length, 0); c1.writeUInt32LE(0x4e4f534a, 4);
  const c2 = Buffer.alloc(8); c2.writeUInt32LE(bb.length, 0); c2.writeUInt32LE(0x004e4942, 4);
  return { vrm: Buffer.concat([head, c1, jb, c2, bb]), missing, humanBones };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const srv = await serve();
  const base = `http://127.0.0.1:${srv.address().port}`;
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage();
  page.on('console', (m) => { if (m.type() === 'error') console.log('[page]', m.text()); });
  await page.goto(base + '/tools/fbx-convert.html');
  await page.waitForFunction(() => window.ready);
  const flipY = process.argv.includes('--flip');
  const info = await page.evaluate((o) => window.convert(o), {
    fbx: `/${SRC}/Nick_T_pose.fbx`, textures: { body: `/${SRC}/Nick_Body_Mat_2D_View.png`, costume: `/${SRC}/Nick_Costume_Mat_2D_View.png` },
    height: 1.25, flipY, mouth: { bone: 'NickHead_M', dy: Number(process.argv.find((a) => a.startsWith('--mouth-dy='))?.slice(11) ?? -0.10), w: 0.034, h: 0.005, curve: 0.012 }, probe: ['NickHead_M', 'NickWrist_L', 'NickWrist_R', 'NickToes_L', 'NickAnkle_L'],
    views: JSON.parse(process.argv.find((a) => a.startsWith('--views='))?.slice(8) || '[[0, 0.7, 3.4, 0.62], [0, 0.95, 1.2, 0.92], [3.4, 0.7, 0, 0.62]]'),
  });
  await browser.close(); srv.close();
  const out = process.argv.find((a) => a.startsWith('--preview='))?.slice(10);
  if (out) info.views.forEach((v, i) => fs.writeFileSync(`${out}_${i}.png`, Buffer.from(v.split(',')[1], 'base64')));
  console.log(JSON.stringify({ dupesRemoved: info.dupesRemoved, mouthHit: info.mouthHit, mouthZ: info.mouthZ, meshes: info.meshes, height: info.height, scale: info.scale, pos: info.pos, bones: info.bones.length }, null, 1));
  const { vrm, missing } = buildVrmFromGlb(Buffer.from(info.glb, 'base64'), { mouthTargets: info.mouthTargets });
  if (missing.length) console.log('Не найдены кости:', missing);
  fs.writeFileSync(path.join(ROOT, 'assets/models/nick.vrm'), vrm);
  console.log(`Готово: assets/models/nick.vrm (${(vrm.length / 1024 / 1024).toFixed(1)} МБ)`);
}
