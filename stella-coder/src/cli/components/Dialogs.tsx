import React, { useState } from 'react';
import { Box, Text, useInput } from 'ink';
import { theme } from '../theme.js';
import { renderMarkdown } from '../markdown.js';
import type { PermissionRequest } from '../../agent/events.js';
import type { AskAnswer } from '../../permissions/engine.js';

export interface Option<T> {
  label: string;
  value: T;
  hint?: string;
  needsFeedback?: boolean;
}

/** Arrow/number-key selection list with an optional free-text follow-up. */
export function SelectDialog<T>(props: { title: string; titleColor?: string; body?: React.ReactNode; options: Option<T>[]; onSelect(v: T, feedback?: string): void; onCancel?(): void }) {
  const [sel, setSel] = useState(0);
  const [feedbackFor, setFeedbackFor] = useState<Option<T> | null>(null);
  const [text, setText] = useState('');
  useInput((input, key) => {
    if (feedbackFor) {
      if (key.return) return props.onSelect(feedbackFor.value, text.trim() || undefined);
      if (key.escape) return setFeedbackFor(null);
      if (key.backspace || key.delete) return setText((t) => t.slice(0, -1));
      if (input && !key.ctrl && !key.meta) setText((t) => t + input);
      return;
    }
    if (key.upArrow) setSel((s) => (s - 1 + props.options.length) % props.options.length);
    else if (key.downArrow || key.tab) setSel((s) => (s + 1) % props.options.length);
    else if (key.return) choose(props.options[sel]!);
    else if (key.escape) props.onCancel ? props.onCancel() : choose(props.options[props.options.length - 1]!);
    else if (/^[1-9]$/.test(input) && Number(input) <= props.options.length) choose(props.options[Number(input) - 1]!);
  });
  const choose = (o: Option<T>) => (o.needsFeedback ? setFeedbackFor(o) : props.onSelect(o.value));
  return (
    <Box borderStyle="round" borderColor={props.titleColor ?? theme.warn} flexDirection="column" paddingX={1} marginY={1}>
      <Text bold color={props.titleColor ?? theme.warn}>
        {props.title}
      </Text>
      {props.body}
      <Box flexDirection="column" marginTop={1}>
        {props.options.map((o, i) => (
          <Text key={i} color={i === sel ? theme.brand : undefined}>
            {i === sel ? '❯ ' : '  '}
            {i + 1}. {o.label}
            {o.hint ? <Text color={theme.faint}> {o.hint}</Text> : null}
          </Text>
        ))}
      </Box>
      {feedbackFor ? (
        <Box marginTop={1}>
          <Text color={theme.brand2}>Tell STELLA what to do instead: </Text>
          <Text>{text}</Text>
          <Text inverse> </Text>
        </Box>
      ) : (
        <Text color={theme.faint}>↑↓ or 1-{props.options.length} to choose · enter to confirm · esc to cancel</Text>
      )}
    </Box>
  );
}

export function PermissionDialog({ req, onAnswer }: { req: PermissionRequest; onAnswer(a: AskAnswer): void }) {
  const d = req.descriptor;
  const riskColor = d.risk === 'high' || d.risk === 'critical' ? theme.err : d.risk === 'medium' ? theme.warn : theme.ok;
  const input = req.input as any;
  let detail: React.ReactNode = null;
  if (d.command) detail = <Text color={theme.text}>{'  $ ' + d.command}</Text>;
  else if (req.tool === 'Edit' && input.old_string !== undefined)
    detail = (
      <Box flexDirection="column">
        {String(input.old_string).split('\n').slice(0, 8).map((l: string, i: number) => (
          <Text key={'o' + i} color={theme.del}>{'- ' + l}</Text>
        ))}
        {String(input.new_string).split('\n').slice(0, 8).map((l: string, i: number) => (
          <Text key={'n' + i} color={theme.add}>{'+ ' + l}</Text>
        ))}
      </Box>
    );
  else if (req.tool === 'Write' && typeof input.content === 'string')
    detail = (
      <Box flexDirection="column">
        {input.content.split('\n').slice(0, 10).map((l: string, i: number) => (
          <Text key={i} color={theme.add}>{'+ ' + l}</Text>
        ))}
        {input.content.split('\n').length > 10 ? <Text color={theme.faint}>  … {input.content.split('\n').length - 10} more lines</Text> : null}
      </Box>
    );
  else if (input && Object.keys(input).length) detail = <Text color={theme.dim}>{'  ' + JSON.stringify(input).slice(0, 300)}</Text>;
  return (
    <SelectDialog<AskAnswer['decision']>
      title={`${req.agentId !== 'main' ? `[${req.agentId}] ` : ''}Allow ${req.tool}?`}
      body={
        <Box flexDirection="column">
          <Text>
            <Text bold>{d.summary}</Text>
            <Text color={riskColor}>  ● {d.risk} risk</Text>
          </Text>
          <Text color={theme.faint}>{req.reason}</Text>
          {detail}
        </Box>
      }
      options={[
        { label: 'Yes', value: 'allow_once' },
        { label: `Yes, and don't ask again this session`, value: 'allow_session', hint: req.suggestedRule },
        { label: 'Always allow in this project', value: 'allow_always', hint: `saves ${req.suggestedRule}` },
        { label: 'No, and tell STELLA what to do differently', value: 'deny', needsFeedback: true },
      ]}
      onSelect={(v, fb) => onAnswer({ decision: v, feedback: fb })}
      onCancel={() => onAnswer({ decision: 'deny' })}
    />
  );
}

export function PlanDialog({ plan, onAnswer }: { plan: string; onAnswer(a: { decision: 'approve' | 'edit' | 'reject'; mode?: any; feedback?: string }): void }) {
  return (
    <SelectDialog<string>
      title="✦ Ready to code? Here is STELLA's plan"
      titleColor={theme.brand}
      body={<Text>{renderMarkdown(plan, (process.stdout.columns ?? 100) - 6)}</Text>}
      options={[
        { label: 'Yes, and auto-accept edits', value: 'acceptEdits' },
        { label: 'Yes, and confirm each edit', value: 'default' },
        { label: 'No, keep planning (give feedback)', value: 'edit', needsFeedback: true },
        { label: 'Reject the plan', value: 'reject' },
      ]}
      onSelect={(v, fb) => (v === 'edit' ? onAnswer({ decision: 'edit', feedback: fb }) : v === 'reject' ? onAnswer({ decision: 'reject', feedback: fb }) : onAnswer({ decision: 'approve', mode: v }))}
      onCancel={() => onAnswer({ decision: 'edit', feedback: 'Continue planning.' })}
    />
  );
}

export function QuestionDialog({ question, options, onAnswer }: { question: string; options: string[]; onAnswer(a: string): void }) {
  return (
    <SelectDialog<string>
      title={`? ${question}`}
      titleColor={theme.brand2}
      options={[...options.map((o) => ({ label: o, value: o })), { label: 'Other (type an answer)', value: '__other__', needsFeedback: true }]}
      onSelect={(v, fb) => onAnswer(v === '__other__' ? fb ?? '' : v)}
      onCancel={() => onAnswer('(user skipped the question)')}
    />
  );
}
