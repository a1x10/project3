import React, { useEffect, useRef, useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { theme } from '../theme.js';

export interface Suggestion {
  value: string;
  label: string;
  description?: string;
}

export interface InputProps {
  placeholder?: string;
  history: string[];
  active: boolean;
  busy: boolean;
  modeLabel: string;
  modeColor: string;
  onSubmit(value: string): void;
  onInterrupt(): void;
  onExitRequest(): void;
  onCycleMode(): void;
  onClearScreen(): void;
  getSuggestions(value: string): Promise<Suggestion[]>;
}

/** Multi-line prompt editor with history, Tab completion and suggestion dropdown. */
export function PromptInput(props: InputProps) {
  const [value, setValue] = useState('');
  const [cursor, setCursor] = useState(0);
  const [histIdx, setHistIdx] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [sugs, setSugs] = useState<Suggestion[]>([]);
  const [sel, setSel] = useState(0);
  const lastCtrlC = useRef(0);

  useEffect(() => {
    let alive = true;
    const trigger = /(^\/[\w:-]*$)|(@[^\s]*$)/.test(value.slice(0, cursor));
    if (!trigger) {
      setSugs([]);
      return;
    }
    props.getSuggestions(value.slice(0, cursor)).then((s) => {
      if (alive) {
        setSugs(s);
        setSel(0);
      }
    });
    return () => {
      alive = false;
    };
  }, [value, cursor]);

  const set = (v: string, c = v.length) => {
    setValue(v);
    setCursor(Math.max(0, Math.min(v.length, c)));
  };

  const applySuggestion = (s: Suggestion) => {
    const before = value.slice(0, cursor);
    const after = value.slice(cursor);
    const m = /(\/[\w:-]*|@[^\s]*)$/.exec(before);
    if (!m) return;
    const start = before.length - m[0].length;
    const insert = s.value + (s.value.endsWith('/') ? '' : ' ');
    set(value.slice(0, start) + insert + after, start + insert.length);
  };

  useInput(
    (input, key) => {
      if (key.ctrl && input === 'c') {
        if (props.busy) return props.onInterrupt();
        if (value) return set('');
        const now = Date.now();
        if (now - lastCtrlC.current < 1500) return props.onExitRequest();
        lastCtrlC.current = now;
        return;
      }
      if (key.escape) {
        if (sugs.length) return setSugs([]);
        if (props.busy) return props.onInterrupt();
        return;
      }
      if (key.ctrl && input === 'l') return props.onClearScreen();
      if (key.ctrl && input === 'd') {
        if (!value) props.onExitRequest();
        return;
      }
      if (key.tab && key.shift) return props.onCycleMode();
      if (key.tab) {
        if (sugs.length) applySuggestion(sugs[sel] ?? sugs[0]!);
        return;
      }
      if (key.upArrow) {
        if (sugs.length) return setSel((s) => (s - 1 + sugs.length) % sugs.length);
        if (value.slice(0, cursor).includes('\n')) {
          const before = value.slice(0, cursor);
          const lineStart = before.lastIndexOf('\n');
          const prevStart = before.lastIndexOf('\n', lineStart - 1) + 1;
          return setCursor(Math.min(lineStart, prevStart + (cursor - lineStart - 1)));
        }
        if (!props.history.length) return;
        const idx = histIdx === null ? props.history.length - 1 : Math.max(0, histIdx - 1);
        if (histIdx === null) setDraft(value);
        setHistIdx(idx);
        return set(props.history[idx] ?? '');
      }
      if (key.downArrow) {
        if (sugs.length) return setSel((s) => (s + 1) % sugs.length);
        const nextNl = value.indexOf('\n', cursor);
        if (nextNl >= 0) {
          const lineStart = value.lastIndexOf('\n', cursor - 1) + 1;
          return setCursor(Math.min(value.length, nextNl + 1 + (cursor - lineStart)));
        }
        if (histIdx === null) return;
        const idx = histIdx + 1;
        if (idx >= props.history.length) {
          setHistIdx(null);
          return set(draft);
        }
        setHistIdx(idx);
        return set(props.history[idx] ?? '');
      }
      if (key.leftArrow) return setCursor((c) => Math.max(0, c - (key.ctrl || key.meta ? wordLeft(value, c) : 1)));
      if (key.rightArrow) return setCursor((c) => Math.min(value.length, c + (key.ctrl || key.meta ? wordRight(value, c) : 1)));
      if (key.ctrl && input === 'a') return setCursor(value.lastIndexOf('\n', cursor - 1) + 1);
      if (key.ctrl && input === 'e') {
        const nl = value.indexOf('\n', cursor);
        return setCursor(nl < 0 ? value.length : nl);
      }
      if (key.ctrl && input === 'u') return set(value.slice(cursor), 0);
      if (key.ctrl && input === 'k') return set(value.slice(0, cursor), cursor);
      if (key.ctrl && input === 'w') {
        const n = wordLeft(value, cursor);
        return set(value.slice(0, cursor - n) + value.slice(cursor), cursor - n);
      }
      if ((key.ctrl && input === 'j') || (key.return && key.meta)) return set(value.slice(0, cursor) + '\n' + value.slice(cursor), cursor + 1);
      if (key.return) {
        if (sugs.length && /^\/[\w:-]*$/.test(value) && sugs[sel] && sugs[sel]!.value !== value.trim()) {
          applySuggestion(sugs[sel]!);
          return;
        }
        if (value.slice(0, cursor).endsWith('\\')) return set(value.slice(0, cursor - 1) + '\n' + value.slice(cursor), cursor);
        const v = value;
        if (!v.trim()) return;
        set('');
        setHistIdx(null);
        setSugs([]);
        return props.onSubmit(v);
      }
      if (key.backspace || key.delete) {
        if (key.delete && !key.backspace && process.platform !== 'darwin' && cursor < value.length && input === '') {
          // Real "Delete" key on most terminals arrives as delete; treat as backspace for compatibility.
        }
        if (cursor === 0) return;
        return set(value.slice(0, cursor - 1) + value.slice(cursor), cursor - 1);
      }
      if (input && !key.ctrl && !key.meta) {
        const clean = input.replace(/\r\n?/g, '\n').replace(/\x1b\[20[01]~/g, '');
        set(value.slice(0, cursor) + clean + value.slice(cursor), cursor + clean.length);
      }
    },
    { isActive: props.active },
  );

  const lines = renderWithCursor(value, cursor, props.active);
  return (
    <Box flexDirection="column">
      <Box borderStyle="round" borderColor={props.busy ? theme.faint : theme.brand} paddingX={1} flexDirection="column">
        {value ? (
          lines.map((l, i) => (
            <Text key={i}>
              <Text color={theme.brand}>{i === 0 ? '❯ ' : '  '}</Text>
              {l}
            </Text>
          ))
        ) : (
          <Text>
            <Text color={theme.brand}>❯ </Text>
            {props.active ? <Text inverse> </Text> : null}
            <Text color={theme.faint}>{props.placeholder}</Text>
          </Text>
        )}
      </Box>
      {sugs.length > 0 && (
        <Box flexDirection="column" paddingX={2}>
          {sugs.slice(0, 8).map((s, i) => (
            <Text key={s.value} color={i === sel ? theme.brand : theme.dim}>
              {i === sel ? '▸ ' : '  '}
              <Text bold={i === sel}>{s.label}</Text>
              {s.description ? <Text color={theme.faint}>  {s.description.slice(0, 70)}</Text> : null}
            </Text>
          ))}
        </Box>
      )}
      <Box paddingX={2} justifyContent="space-between">
        <Text color={props.modeColor}>{props.modeLabel}</Text>
        <Text color={theme.faint}>{props.busy ? 'esc to interrupt · type to queue a message' : '/ commands · @ files · ! shell · shift+tab mode'}</Text>
      </Box>
    </Box>
  );
}

function renderWithCursor(value: string, cursor: number, show: boolean): React.ReactNode[] {
  const lines = value.split('\n');
  let offset = 0;
  return lines.map((line, i) => {
    const start = offset;
    offset += line.length + 1;
    if (!show || cursor < start || cursor > start + line.length) return <Text key={i}>{line}</Text>;
    const c = cursor - start;
    return (
      <Text key={i}>
        {line.slice(0, c)}
        <Text inverse>{line[c] ?? ' '}</Text>
        {line.slice(c + 1)}
      </Text>
    );
  });
}

function wordLeft(v: string, c: number): number {
  let i = c;
  while (i > 0 && /\s/.test(v[i - 1]!)) i--;
  while (i > 0 && !/\s/.test(v[i - 1]!)) i--;
  return c - i;
}
function wordRight(v: string, c: number): number {
  let i = c;
  while (i < v.length && /\s/.test(v[i]!)) i++;
  while (i < v.length && !/\s/.test(v[i]!)) i++;
  return i - c;
}
