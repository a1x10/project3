// "Команда агентов": one request -> a plan -> several agents working in parallel -> one report.
//   1) a planner splits the request into 2–5 independent parts (JSON schema output)
//   2) each part runs as its own agent: on the server (own chat) or on the user's PC (browser/screen tasks)
//      parts that need results of other parts wait for them and get those results as context
//   3) a final report is written into the team chat; every change is pushed live to phone and PC
const crypto = require('crypto');

let agent = null, emit = () => {}, toPc = () => 0, pcOnline = () => false;
function setup(o) { agent = o.agent; emit = o.emit; toPc = o.toPc; pcOnline = o.pcOnline; }

const teams = new Map();                 // teamId -> team
const pcWaiting = new Map();             // pc chatId -> { team, member }
const uid = () => Date.now().toString(36) + crypto.randomBytes(3).toString('hex');

const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    title: { type: 'string', description: 'short title of the whole job (3–6 words, user language)' },
    agents: {
      type: 'array', minItems: 1, maxItems: 5,
      items: {
        type: 'object',
        properties: {
          key: { type: 'string', description: 'short id like a1, a2' },
          title: { type: 'string', description: 'what this agent does, 2–6 words, user language' },
          task: { type: 'string', description: 'complete self-contained instruction for this agent, with all details from the request' },
          where: { type: 'string', enum: ['server', 'pc'], description: 'pc ONLY if it must use the browser/screen/apps on the user computer (e.g. BilimClass site, desktop apps); otherwise server' },
          needs: { type: 'array', items: { type: 'string' }, description: 'keys of agents whose results this one needs first (empty = start immediately)' }
        },
        required: ['key', 'title', 'task', 'where']
      }
    }
  },
  required: ['title', 'agents']
};

function publicTeam(t) {
  return {
    id: t.id, title: t.title, status: t.status, started: t.started, finished: t.finished || null, request: t.request,
    agents: t.members.map(m => ({ key: m.key, title: m.title, where: m.where, status: m.status, chatId: m.chatId, started: m.started || null, finished: m.finished || null, summary: (m.result || '').slice(0, 300) }))
  };
}
function push(t) {
  const c = agent.findChat(t.u, t.chatId);
  if (c) { const msg = c.messages.find(x => x.id === t.msgId); if (msg) { msg.team = publicTeam(t); msg.busy = t.status !== 'done' && t.status !== 'failed' && t.status !== 'stopped'; } }
  emit(t.u.name, { t: 'team', team: publicTeam(t), chatId: t.chatId, msgId: t.msgId });
}

async function start(u, request) {
  request = String(request || '').trim();
  if (!request) throw new Error('empty request');
  const c = agent.newChat(u, '👥 ' + request.split('\n')[0].slice(0, 44), 'team');
  c.messages.push({ id: uid(), role: 'user', text: request, ts: Date.now() });
  const msgId = uid();
  c.messages.push({ id: msgId, role: 'agent', text: '', tools: [], busy: true, started: Date.now(), status: 'Составляю план…' });
  const t = { id: uid(), u, chatId: c.id, msgId, request, title: 'Команда агентов', status: 'planning', started: Date.now(), members: [] };
  teams.set(t.id, t);
  emit(u.name, { t: 'chat', where: 'server', chat: c });
  push(t);

  // 1) plan
  let plan;
  const pcOk = pcOnline(u.name);
  try {
    plan = await agent.runOnce(u,
      agent.serverNote(u) +
      'You are the PLANNER of a team of AI agents (like Manus). Split the user request into 2–5 parts that different agents can do IN PARALLEL. ' +
      'Each part must be self-contained (include every detail from the request it needs). Use "needs" only when a part truly requires another part\'s result. ' +
      `The user's PC is ${pcOk ? 'ONLINE (agents there can use the browser, BilimClass, screen and apps)' : 'OFFLINE (use only server agents)'}. ` +
      'Server agents can: WhatsApp (read chats, learn the user\'s style, send messages, create groups, broadcast), e-mail, generate presentations/documents, research, write texts, run code. ' +
      'If the request is simple, 1–2 agents are fine. Titles and tasks in the user\'s language.\n\nUSER REQUEST:\n' + request,
      180000, PLAN_SCHEMA);
    if (!plan || !Array.isArray(plan.agents) || !plan.agents.length) throw new Error('planner returned no agents');
  } catch (e) {
    t.status = 'failed'; push(t);
    agent.addNote(u, c.id, 'Не удалось составить план: ' + e.message);
    return publicTeam(t);
  }
  t.title = plan.title || t.title;
  t.members = plan.agents.slice(0, 5).map((a, i) => ({
    key: String(a.key || 'a' + (i + 1)), title: String(a.title || 'Агент ' + (i + 1)), task: String(a.task || ''),
    where: a.where === 'pc' && pcOk ? 'pc' : 'server', needs: Array.isArray(a.needs) ? a.needs.map(String) : [], status: 'waiting'
  }));
  t.status = 'running';
  push(t);
  pump(t);
  return publicTeam(t);
}

// start every member whose dependencies are done
function pump(t) {
  if (t.status !== 'running') return;
  for (const m of t.members) {
    if (m.status !== 'waiting') continue;
    const deps = m.needs.map(k => t.members.find(x => x.key === k)).filter(Boolean);
    if (deps.some(d => d.status === 'failed' || d.status === 'stopped')) { m.status = 'failed'; m.result = 'Пропущено: не выполнена зависимая задача'; continue; }
    if (deps.some(d => d.status !== 'done')) continue;
    run(t, m, deps);
  }
  if (t.members.every(m => ['done', 'failed', 'stopped'].includes(m.status))) finish(t);
  else push(t);
}

function teamNote(t, m, deps) {
  const others = t.members.filter(x => x !== m).map(x => `- ${x.title} (${x.where === 'pc' ? 'on the PC' : 'on the server'})`).join('\n');
  return `[Team mode] You are one agent of a team working IN PARALLEL on the user's request: «${t.request.slice(0, 1500)}».\n` +
    `YOUR PART ONLY: ${m.title}. Other agents handle:\n${others || '-'}\nDo not do their parts. ` +
    (deps.length ? 'Results of the parts you depend on:\n' + deps.map(d => `### ${d.title}\n${(d.result || '').slice(0, 3000)}`).join('\n') + '\n' : '') +
    'Work fast and decisively. At the end write a SHORT report: what you did, results, file paths, anything the user must check.\n\n';
}

function run(t, m, deps) {
  m.status = 'running'; m.started = Date.now();
  const note = teamNote(t, m, deps);
  if (m.where === 'pc' && pcOnline(t.u.name)) {
    m.chatId = 'team-' + uid();
    pcWaiting.set(m.chatId, { t, m });
    toPc(t.u.name, { t: 'pc.run', chatId: m.chatId, title: '👥 ' + m.title, text: note + m.task, display: '👥 ' + m.title + ': ' + m.task.slice(0, 300) });
    return;
  }
  m.where = 'server';
  try {
    const c = agent.newChat(t.u, '↳ ' + m.title, 'team');
    m.chatId = c.id;
    agent.send(t.u, c.id, m.task, { team: true, quiet: true, note, onDone: (msg) => {
      m.finished = Date.now();
      m.result = msg.text || msg.error || '';
      m.status = msg.error && !msg.text ? 'failed' : (t.status === 'stopped' ? 'stopped' : 'done');
      pump(t);
    } });
  } catch (e) { m.status = 'failed'; m.result = e.message; m.finished = Date.now(); setTimeout(() => pump(t), 0); }
}

// PC finished a team part (pc.ev done) -> result from the server's live copy of that PC chat
function pcDone(username, chatId, pcChat) {
  const w = pcWaiting.get(chatId);
  if (!w || w.t.u.name !== username) return;
  pcWaiting.delete(chatId);
  const last = pcChat && [...(pcChat.messages || [])].reverse().find(x => x.role === 'agent');
  w.m.finished = Date.now();
  w.m.result = (last && (last.text || last.error)) || '';
  w.m.status = last && last.error && !last.text ? 'failed' : 'done';
  pump(w.t);
}

async function finish(t) {
  if (t.status !== 'running') return;
  t.status = 'summarizing'; push(t);
  let report = '';
  try {
    report = await agent.runOnce(t.u, agent.serverNote(t.u) +
      'Several agents worked in parallel on the user request below. Write the FINAL REPORT for the user in their language: ' +
      'a one-line result, then a short bullet list per agent (what was done, links/files, problems), then what the user should check or decide. Be concise.\n\n' +
      'REQUEST: ' + t.request + '\n\n' + t.members.map(m => `## ${m.title} — ${m.status}\n${(m.result || '').slice(0, 4000)}`).join('\n\n'), 180000);
  } catch (e) {
    report = '**Готово.**\n\n' + t.members.map(m => `- **${m.title}** — ${m.status === 'done' ? '✅' : '⚠️'} ${(m.result || '').slice(0, 300)}`).join('\n');
  }
  t.status = t.members.some(m => m.status === 'done') ? 'done' : 'failed';
  t.finished = Date.now();
  const c = agent.findChat(t.u, t.chatId);
  if (c) { const msg = c.messages.find(x => x.id === t.msgId); if (msg) { msg.text = String(report); msg.busy = false; msg.duration = Math.round((t.finished - t.started) / 1000); } }
  push(t);
  emit(t.u.name, { t: 'chat', where: 'server', chat: agent.findChat(t.u, t.chatId) });
  emit(t.u.name, { t: 'notify', title: '👥 Команда закончила: ' + t.title, body: String(report).split('\n')[0].slice(0, 140), chatId: t.chatId, where: 'server' });
}

function stop(u, teamId) {
  const t = teams.get(teamId);
  if (!t || t.u.name !== u.name) return;
  t.status = 'stopped';
  for (const m of t.members) {
    if (m.status === 'running') { if (m.where === 'server' && m.chatId) agent.stop(u, m.chatId); else toPc(u.name, { t: 'pc.stop', chatId: m.chatId }); m.status = 'stopped'; }
    else if (m.status === 'waiting') m.status = 'stopped';
  }
  const c = agent.findChat(u, t.chatId);
  if (c) { const msg = c.messages.find(x => x.id === t.msgId); if (msg) { msg.busy = false; msg.text = msg.text || 'Остановлено.'; } }
  push(t);
}

module.exports = { setup, start, stop, pcDone, PLAN_SCHEMA };
