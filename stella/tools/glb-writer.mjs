// Минимальный писатель GLB (glTF 2.0 binary) без зависимостей.
export class GLBBuilder {
  constructor() {
    this.json = {
      asset: { version: '2.0', generator: 'Stella Mark Generator' },
      scene: 0, scenes: [{ nodes: [] }], nodes: [], meshes: [], materials: [],
      accessors: [], bufferViews: [], buffers: [{ byteLength: 0 }],
      extensionsUsed: [], extensions: {},
    };
    this.chunks = [];
    this.byteLength = 0;
  }
  _pushBytes(u8, target) {
    const pad = (4 - (this.byteLength % 4)) % 4;
    if (pad) { this.chunks.push(new Uint8Array(pad)); this.byteLength += pad; }
    const view = { buffer: 0, byteOffset: this.byteLength, byteLength: u8.byteLength };
    if (target) view.target = target;
    this.chunks.push(u8);
    this.byteLength += u8.byteLength;
    this.json.bufferViews.push(view);
    return this.json.bufferViews.length - 1;
  }
  addAccessor(typed, type, { target, minmax = false, componentType } = {}) {
    const comps = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 }[type];
    const bv = this._pushBytes(new Uint8Array(typed.buffer, typed.byteOffset, typed.byteLength), target);
    const ct = componentType || (typed instanceof Float32Array ? 5126 : typed instanceof Uint32Array ? 5125 : 5123);
    const acc = { bufferView: bv, componentType: ct, count: typed.length / comps, type };
    if (minmax) {
      const min = new Array(comps).fill(Infinity), max = new Array(comps).fill(-Infinity);
      for (let i = 0; i < typed.length; i += comps)
        for (let c = 0; c < comps; c++) { const v = typed[i + c]; if (v < min[c]) min[c] = v; if (v > max[c]) max[c] = v; }
      acc.min = min; acc.max = max;
    }
    this.json.accessors.push(acc);
    return this.json.accessors.length - 1;
  }
  addMaterial(mat) { this.json.materials.push(mat); return this.json.materials.length - 1; }
  addNode(node) { this.json.nodes.push(node); return this.json.nodes.length - 1; }
  addMesh(mesh) { this.json.meshes.push(mesh); return this.json.meshes.length - 1; }
  toGLB() {
    const pad = (4 - (this.byteLength % 4)) % 4;
    if (pad) { this.chunks.push(new Uint8Array(pad)); this.byteLength += pad; }
    this.json.buffers[0].byteLength = this.byteLength;
    if (!this.json.extensionsUsed.length) delete this.json.extensionsUsed;
    let jsonStr = JSON.stringify(this.json);
    while (Buffer.byteLength(jsonStr) % 4) jsonStr += ' ';
    const jsonBuf = Buffer.from(jsonStr);
    const bin = Buffer.concat(this.chunks.map((c) => Buffer.from(c.buffer, c.byteOffset, c.byteLength)));
    const total = 12 + 8 + jsonBuf.length + 8 + bin.length;
    const header = Buffer.alloc(12);
    header.writeUInt32LE(0x46546c67, 0); header.writeUInt32LE(2, 4); header.writeUInt32LE(total, 8);
    const jh = Buffer.alloc(8); jh.writeUInt32LE(jsonBuf.length, 0); jh.writeUInt32LE(0x4e4f534a, 4);
    const bh = Buffer.alloc(8); bh.writeUInt32LE(bin.length, 0); bh.writeUInt32LE(0x004e4942, 4);
    return Buffer.concat([header, jh, jsonBuf, bh, bin]);
  }
}

export function parseGLB(buf) {
  if (buf.readUInt32LE(0) !== 0x46546c67) throw new Error('not glb');
  const jsonLen = buf.readUInt32LE(12);
  const json = JSON.parse(buf.slice(20, 20 + jsonLen).toString());
  const binStart = 20 + jsonLen + 8;
  const binLen = buf.readUInt32LE(20 + jsonLen);
  return { json, bin: buf.slice(binStart, binStart + binLen), version: buf.readUInt32LE(4), length: buf.readUInt32LE(8) };
}
