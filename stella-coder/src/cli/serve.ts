import { createInterface } from 'node:readline';
import { Runtime } from '../agent/runtime.js';
import type { PermissionMode } from '../config/settings.js';

/**
 * `stella-coder serve`: the agent as a long-running process speaking JSON lines on stdio,
 * for desktop apps (Vibing AI Studio). One session, many prompts; permission prompts, plan
 * approvals and questions are forwarded to the app and answered by the user there.
 *
 * In:  {"type":"prompt","text":"…"} · {"type":"answer","id":"…","value":…} · {"type":"interrupt"} · {"type":"mode","mode":"acceptEdits"}
 * Out: {"type":"ready",…} · {"type":"event","event":AgentEvent} · {"type":"permission_request"|"plan_request"|"question",…}
 *      {"type":"done","stopReason":…} · {"type":"error","message":…}
 */
export async function serve(opts: { cwd: string; model?: string; permissionMode?: PermissionMode; resume?: string }) {
  const out = (o: unknown) => process.stdout.write(JSON.stringify(o) + '\n');
  // anything else written to stdout would break the protocol
  console.log = (...a: unknown[]) => process.stderr.write(a.map(String).join(' ') + '\n');

  let rt: Runtime;
  try {
    rt = await Runtime.create({
      cwd: opts.cwd,
      model: opts.model,
      permissionMode: opts.permissionMode ?? 'default',
      resume: opts.resume === '?' ? 'last' : opts.resume,
      interactive: true,
      connectMcp: false,
      trust: false,
    });
  } catch (e) {
    out({ type: 'error', fatal: true, message: (e as Error).message });
    process.exit(1);
  }

  // what an unanswered dialog resolves to when the user stops the agent
  const CANCEL: Record<string, unknown> = { permission_request: { decision: 'deny', feedback: 'interrupted' }, plan_request: { decision: 'reject', feedback: 'interrupted' }, question: null };
  const pending = new Map<string, { resolve: (v: any) => void; type: string }>();
  let seq = 0;
  const ask = <T>(payload: { type: string } & Record<string, unknown>) =>
    new Promise<T>((resolve) => {
      const id = `q${++seq}`;
      pending.set(id, { resolve, type: payload.type });
      out({ ...payload, id });
    });

  rt.handlers.permission = (req) =>
    ask({ type: 'permission_request', tool: req.tool, summary: req.descriptor.summary, reason: req.reason, suggestedRule: req.suggestedRule, input: req.input });
  rt.handlers.planApproval = (plan) => ask({ type: 'plan_request', plan });
  rt.handlers.question = (question, options) => ask({ type: 'question', question, options });
  rt.events.on('event', (event) => out({ type: 'event', event }));

  out({ type: 'ready', cwd: rt.cwd, root: rt.root, model: `${rt.main.model.provider}:${rt.main.model.id}`, session: rt.session.id, warnings: rt.warnings });

  let running = false;
  const rl = createInterface({ input: process.stdin });
  rl.on('line', (line) => {
    let msg: any;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }
    if (msg.type === 'prompt' && typeof msg.text === 'string') {
      if (running) return out({ type: 'error', message: 'Агент ещё работает — дождитесь окончания или остановите его.' });
      running = true;
      rt.submit(msg.text)
        .then((r) => out({ type: 'done', stopReason: r?.stopReason ?? 'end_turn', text: r?.text ?? '', usage: r?.usage }))
        .catch((e) => out({ type: 'error', message: (e as Error).message }))
        .finally(() => (running = false));
    } else if (msg.type === 'answer' && pending.has(msg.id)) {
      const p = pending.get(msg.id)!;
      pending.delete(msg.id);
      p.resolve(msg.value);
    } else if (msg.type === 'interrupt') {
      rt.interrupt();
      // unblock any dialog the agent is waiting on
      for (const [id, p] of pending) {
        pending.delete(id);
        p.resolve(CANCEL[p.type] ?? null);
      }
    } else if (msg.type === 'mode' && typeof msg.mode === 'string') {
      rt.setMode(msg.mode as PermissionMode);
    }
  });
  rl.on('close', async () => {
    await rt.shutdown().catch(() => undefined);
    process.exit(0);
  });
}
