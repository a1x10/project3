/** Line-based Myers diff producing unified hunks. */
export type DiffOp = { op: ' ' | '+' | '-'; line: string };

export function diffLines(a: string[], b: string[]): DiffOp[] {
  const n = a.length;
  const m = b.length;
  // Trim common prefix/suffix for speed on large files.
  let pre = 0;
  while (pre < n && pre < m && a[pre] === b[pre]) pre++;
  let suf = 0;
  while (suf < n - pre && suf < m - pre && a[n - 1 - suf] === b[m - 1 - suf]) suf++;
  const A = a.slice(pre, n - suf);
  const B = b.slice(pre, m - suf);
  const mid = myers(A, B);
  return [...a.slice(0, pre).map((line) => ({ op: ' ' as const, line })), ...mid, ...a.slice(n - suf).map((line) => ({ op: ' ' as const, line }))];
}

function myers(a: string[], b: string[]): DiffOp[] {
  const n = a.length;
  const m = b.length;
  if (!n) return b.map((line) => ({ op: '+', line }));
  if (!m) return a.map((line) => ({ op: '-', line }));
  const max = n + m;
  if (max > 20000) {
    // Degenerate fallback: full replace (keeps memory bounded on huge rewrites).
    return [...a.map((line) => ({ op: '-' as const, line })), ...b.map((line) => ({ op: '+' as const, line }))];
  }
  const off = max;
  let v = new Int32Array(2 * max + 2);
  const trace: Int32Array[] = [];
  for (let d = 0; d <= max; d++) {
    trace.push(v.slice());
    for (let k = -d; k <= d; k += 2) {
      let x: number;
      if (k === -d || (k !== d && v[off + k - 1]! < v[off + k + 1]!)) x = v[off + k + 1]!;
      else x = v[off + k - 1]! + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) {
        x++;
        y++;
      }
      v[off + k] = x;
      if (x >= n && y >= m) return backtrack(trace, a, b, off, d);
    }
  }
  return [];
}

function backtrack(trace: Int32Array[], a: string[], b: string[], off: number, dEnd: number): DiffOp[] {
  const out: DiffOp[] = [];
  let x = a.length;
  let y = b.length;
  for (let d = dEnd; d > 0; d--) {
    const v = trace[d]!;
    const k = x - y;
    const prevK = k === -d || (k !== d && v[off + k - 1]! < v[off + k + 1]!) ? k + 1 : k - 1;
    const prevX = v[off + prevK]!;
    const prevY = prevX - prevK;
    while (x > prevX && y > prevY) {
      out.push({ op: ' ', line: a[x - 1]! });
      x--;
      y--;
    }
    if (x === prevX) out.push({ op: '+', line: b[y - 1]! });
    else out.push({ op: '-', line: a[x - 1]! });
    x = prevX;
    y = prevY;
  }
  while (x > 0 && y > 0) {
    out.push({ op: ' ', line: a[x - 1]! });
    x--;
    y--;
  }
  return out.reverse();
}

export interface UnifiedDiff {
  text: string;
  added: number;
  removed: number;
}

export function unifiedDiff(before: string, after: string, file = 'file', context = 3): UnifiedDiff {
  const a = before.length ? before.split(/\r?\n/) : [];
  const b = after.length ? after.split(/\r?\n/) : [];
  const ops = diffLines(a, b);
  let added = 0;
  let removed = 0;
  for (const o of ops) {
    if (o.op === '+') added++;
    else if (o.op === '-') removed++;
  }
  if (!added && !removed) return { text: '', added, removed };
  const lines: string[] = [`--- a/${file}`, `+++ b/${file}`];
  let i = 0;
  let ai = 0;
  let bi = 0;
  const pos: Array<{ a: number; b: number }> = [];
  for (const o of ops) {
    pos.push({ a: ai, b: bi });
    if (o.op !== '+') ai++;
    if (o.op !== '-') bi++;
  }
  while (i < ops.length) {
    if (ops[i]!.op === ' ') {
      i++;
      continue;
    }
    const start = Math.max(0, i - context);
    let end = i;
    let lastChange = i;
    while (end < ops.length) {
      if (ops[end]!.op !== ' ') lastChange = end;
      else if (end - lastChange > context * 2) break;
      end++;
    }
    end = Math.min(ops.length, lastChange + context + 1);
    const hunk = ops.slice(start, end);
    const aLen = hunk.filter((o) => o.op !== '+').length;
    const bLen = hunk.filter((o) => o.op !== '-').length;
    lines.push(`@@ -${pos[start]!.a + 1},${aLen} +${pos[start]!.b + 1},${bLen} @@`);
    for (const o of hunk) lines.push(o.op + o.line);
    i = end;
  }
  return { text: lines.join('\n'), added, removed };
}
