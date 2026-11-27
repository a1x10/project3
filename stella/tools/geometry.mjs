// Процедурная геометрия для генерации аватара (без зависимостей).
export function rotMatrix(rx = 0, ry = 0, rz = 0) {
  const cx = Math.cos(rx), sx = Math.sin(rx), cy = Math.cos(ry), sy = Math.sin(ry), cz = Math.cos(rz), sz = Math.sin(rz);
  // R = Rz * Ry * Rx
  return [
    cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx,
    sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx,
    -sy, cy * sx, cy * cx,
  ];
}
export function applyMat(m, x, y, z) {
  return [m[0] * x + m[1] * y + m[2] * z, m[3] * x + m[4] * y + m[5] * z, m[6] * x + m[7] * y + m[8] * z];
}

/** Суперэллипсоид / эллипсоид. e1/e2 = 1 — эллипсоид, < 1 — скруглённый куб. */
export function superEllipsoid({ center = [0, 0, 0], radii = [1, 1, 1], e1 = 1, e2 = 1, seg = 28, rings = 18, rot = [0, 0, 0], polarMax = null }) {
  const pos = [], idx = [];
  const sgnPow = (v, p) => Math.sign(v) * Math.pow(Math.abs(v), p);
  const m = rotMatrix(...rot);
  for (let r = 0; r <= rings; r++) {
    for (let s = 0; s < seg; s++) {
      const az = (s / seg) * Math.PI * 2;
      const maxP = polarMax ? polarMax(az) : Math.PI;
      const polar = (r / rings) * maxP;
      const sp = Math.sin(polar), cp = Math.cos(polar);
      const x = radii[0] * sgnPow(sp, e1) * sgnPow(Math.sin(az), e2);
      const y = radii[1] * sgnPow(cp, e1);
      const z = radii[2] * sgnPow(sp, e1) * sgnPow(Math.cos(az), e2);
      const p = applyMat(m, x, y, z);
      pos.push(p[0] + center[0], p[1] + center[1], p[2] + center[2]);
    }
  }
  for (let r = 0; r < rings; r++) {
    for (let s = 0; s < seg; s++) {
      const a = r * seg + s, b = r * seg + ((s + 1) % seg), c = (r + 1) * seg + s, d = (r + 1) * seg + ((s + 1) % seg);
      idx.push(a, c, b, b, c, d);
    }
  }
  return { pos, idx };
}

/** Капсула (усечённый конус со сферическими торцами) между точками a и b. */
export function capsule(a, b, r1, r2, seg = 24, rings = 10) {
  const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2];
  const len = Math.hypot(dx, dy, dz);
  // профиль вдоль локальной оси Y: (радиус, y)
  const prof = [];
  for (let i = 0; i <= rings; i++) { const t = (i / rings) * (Math.PI / 2); prof.push([r1 * Math.sin(t), -r1 * Math.cos(t)]); }
  for (let i = 1; i < rings; i++) { const t = i / rings; prof.push([r1 + (r2 - r1) * t, len * t]); }
  for (let i = 0; i <= rings; i++) { const t = (i / rings) * (Math.PI / 2); prof.push([r2 * Math.cos(t), len + r2 * Math.sin(t)]); }
  const pos = [], idx = [];
  // базис: ось Y -> направление d
  const ux = dx / len, uy = dy / len, uz = dz / len;
  let tx = 1, ty = 0, tz = 0;
  if (Math.abs(ux) > 0.9) { tx = 0; ty = 0; tz = 1; }
  // v1 = normalize(t - (t.u)u)
  const dot = tx * ux + ty * uy + tz * uz;
  let v1x = tx - dot * ux, v1y = ty - dot * uy, v1z = tz - dot * uz;
  const l1 = Math.hypot(v1x, v1y, v1z); v1x /= l1; v1y /= l1; v1z /= l1;
  const v2x = uy * v1z - uz * v1y, v2y = uz * v1x - ux * v1z, v2z = ux * v1y - uy * v1x;
  for (const [r, y] of prof) {
    for (let s = 0; s < seg; s++) {
      const ang = (s / seg) * Math.PI * 2, c = Math.cos(ang) * r, sn = Math.sin(ang) * r;
      pos.push(a[0] + ux * y + v1x * c + v2x * sn, a[1] + uy * y + v1y * c + v2y * sn, a[2] + uz * y + v1z * c + v2z * sn);
    }
  }
  const rows = prof.length;
  for (let r = 0; r < rows - 1; r++) for (let s = 0; s < seg; s++) {
    const p = r * seg + s, q = r * seg + ((s + 1) % seg), u = (r + 1) * seg + s, w = (r + 1) * seg + ((s + 1) % seg);
    idx.push(p, q, u, q, w, u);
  }
  return { pos, idx };
}

/** Плоская «линза» (рот): сетка u∈[-1,1], v∈[-1,1]. */
export function lens({ center, width, height, curve = 0, cols = 16, rowsN = 6 }) {
  const pos = [], idx = [], uv = [];
  for (let j = 0; j <= rowsN; j++) for (let i = 0; i <= cols; i++) {
    const u = (i / cols) * 2 - 1, v = (j / rowsN) * 2 - 1;
    const env = Math.sqrt(Math.max(0, 1 - u * u));
    pos.push(center[0] + u * width, center[1] + v * height * env, center[2] - curve * u * u);
    uv.push(u, v);
  }
  for (let j = 0; j < rowsN; j++) for (let i = 0; i < cols; i++) {
    const a = j * (cols + 1) + i, b = a + 1, c = a + cols + 1, d = c + 1;
    idx.push(a, b, c, b, d, c);
  }
  return { pos, idx, uv };
}

export function computeNormals(pos, idx) {
  const n = new Float32Array(pos.length);
  for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
    const e1x = pos[b] - pos[a], e1y = pos[b + 1] - pos[a + 1], e1z = pos[b + 2] - pos[a + 2];
    const e2x = pos[c] - pos[a], e2y = pos[c + 1] - pos[a + 1], e2z = pos[c + 2] - pos[a + 2];
    const nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
    for (const k of [a, b, c]) { n[k] += nx; n[k + 1] += ny; n[k + 2] += nz; }
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1;
    n[i] /= l; n[i + 1] /= l; n[i + 2] /= l;
  }
  return n;
}

/** Ориентация треугольников наружу: если нормаль смотрит к центру масс части — переворачиваем все. */
export function orientOutward(geom) {
  const { pos, idx } = geom;
  let cx = 0, cy = 0, cz = 0; const nv = pos.length / 3;
  for (let i = 0; i < pos.length; i += 3) { cx += pos[i]; cy += pos[i + 1]; cz += pos[i + 2]; }
  cx /= nv; cy /= nv; cz /= nv;
  let score = 0;
  for (let i = 0; i < idx.length; i += 3) {
    const a = idx[i] * 3, b = idx[i + 1] * 3, c = idx[i + 2] * 3;
    const e1 = [pos[b] - pos[a], pos[b + 1] - pos[a + 1], pos[b + 2] - pos[a + 2]];
    const e2 = [pos[c] - pos[a], pos[c + 1] - pos[a + 1], pos[c + 2] - pos[a + 2]];
    const nx = e1[1] * e2[2] - e1[2] * e2[1], ny = e1[2] * e2[0] - e1[0] * e2[2], nz = e1[0] * e2[1] - e1[1] * e2[0];
    score += nx * (pos[a] - cx) + ny * (pos[a + 1] - cy) + nz * (pos[a + 2] - cz);
  }
  if (score < 0) for (let i = 0; i < idx.length; i += 3) { const t = idx[i + 1]; idx[i + 1] = idx[i + 2]; idx[i + 2] = t; }
  return geom;
}
