import { describe, expect, it } from 'vitest';
import { applyEdit } from '../../src/tools/fs.js';
import { unifiedDiff } from '../../src/utils/diff.js';

describe('edit engine', () => {
  it('replaces a unique exact match', () => {
    expect(applyEdit('a\nb\nc\n', { old_string: 'b', new_string: 'B' }, 'f')).toBe('a\nB\nc\n');
  });
  it('rejects ambiguous matches unless replace_all', () => {
    expect(() => applyEdit('x x', { old_string: 'x', new_string: 'y' }, 'f')).toThrow(/occurs 2 times/);
    expect(applyEdit('x x', { old_string: 'x', new_string: 'y', replace_all: true }, 'f')).toBe('y y');
  });
  it('reports a helpful error when not found', () => {
    expect(() => applyEdit('  const a = 1;\n', { old_string: 'const a = 2;', new_string: 'z' }, 'f')).toThrow(/not found/);
  });
  it('handles CRLF files with LF old_string', () => {
    const out = applyEdit('one\r\ntwo\r\nthree\r\n', { old_string: 'one\ntwo', new_string: '1\n2' }, 'f');
    expect(out).toBe('1\r\n2\r\nthree\r\n');
  });
  it('does not interpret $ patterns in replacement', () => {
    expect(applyEdit('a', { old_string: 'a', new_string: "$& $1 $$" }, 'f')).toBe("$& $1 $$");
  });
  it('produces unified diffs with counts', () => {
    const d = unifiedDiff('a\nb\nc\nd\n', 'a\nB\nc\nd\ne\n', 'x.txt');
    expect(d.added).toBe(2);
    expect(d.removed).toBe(1);
    expect(d.text).toContain('-b');
    expect(d.text).toContain('+B');
    expect(d.text).toContain('@@');
    expect(unifiedDiff('same', 'same').text).toBe('');
  });
});
