// Окно в стиле VS Code: редактор коннектора + настоящий терминал + вывод коннектора.
// Кнопка «Подключить коннектор» запускает скрипт и связывает его с пультом.
import { LANGS, TEMPLATES } from './data.js';
import { link } from './link.js';
import { icon } from './icons.js';

const api = window.stells;
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const stripAnsi = (s) => s.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '').replace(/\x1b\][^\x07]*\x07/g, '');

const KW = {
  python: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield print',
  javascript: 'await break case catch class const continue default delete do else export extends false finally for function if import in instanceof let new null return super switch this throw true try typeof var void while yield require',
  c: 'auto break case char const continue default do double else enum extern float for goto if int long register return short signed sizeof static struct switch typedef union unsigned void volatile while include define bool true false std string namespace using class public private template auto',
  rust: 'as break const continue crate else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while',
  go: 'break case chan const continue default defer else fallthrough for func go goto if import interface map package range return select struct switch type var true false nil',
  java: 'abstract boolean break byte case catch char class const continue default do double else extends final finally float for if implements import instanceof int interface long new package private protected public return short static super switch this throw throws try void while true false null var val fun',
  bash: 'if then else elif fi case esac for while until do done in function return echo read local export true false',
  ruby: 'def end if elsif else unless while until for in do return class module require puts true false nil and or not next rescue',
  php: 'echo function if else elseif while for foreach as return true false null array new class public private',
  lua: 'and break do else elseif end false for function if in local nil not or repeat return then true until while print',
};
const kwFor = (l) => new Set((KW[l] || KW[{ typescript: 'javascript', cpp: 'c', kotlin: 'java', csharp: 'java', perl: 'bash', powershell: 'bash' }[l]] || KW.javascript).split(' '));

function highlight(code, lang) {
  const kws = kwFor(lang);
  const hashComment = ['python', 'bash', 'ruby', 'perl', 'powershell'].includes(lang);
  const luaComment = lang === 'lua';
  const re = hashComment
    ? /(#[^\n]*)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|"""[\s\S]*?""")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)(?=\s*\()|([A-Za-z_]\w*)/g
    : luaComment
      ? /(--[^\n]*)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)(?=\s*\()|([A-Za-z_]\w*)/g
      : /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`[^`]*`)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)(?=\s*\()|([A-Za-z_]\w*)/g;
  let out = '', last = 0, m;
  while ((m = re.exec(code))) {
    out += esc(code.slice(last, m.index));
    const [t, c, s, n, f, w] = m;
    if (c) out += `<span class="tk-c">${esc(t)}</span>`;
    else if (s) out += `<span class="tk-s">${esc(t)}</span>`;
    else if (n) out += `<span class="tk-n">${t}</span>`;
    else if (f) out += kws.has(f) ? `<span class="tk-k">${f}</span>` : `<span class="tk-f">${f}</span>`;
    else if (w) out += kws.has(w) ? `<span class="tk-k">${w}</span>` : /^[A-Z]/.test(w) ? `<span class="tk-t">${w}</span>` : w;
    last = m.index + t.length;
  }
  return out + esc(code.slice(last)) + '\n';
}

let open = null;
const drafts = {};

export async function openIDE({ onConnected } = {}) {
  if (open) return;
  const root = document.createElement('div');
  root.className = 'ide-bg';
  root.innerHTML = `
  <div class="ide">
    <div class="ide-top">
      <span class="t">STELLS Connector Studio</span>
      <select id="ideLang">${LANGS.map(([v, n]) => `<option value="${v}">${n}</option>`).join('')}</select>
      <button class="ide-btn" id="ideOpen">Открыть…</button>
      <button class="ide-btn" id="ideSave">Сохранить…</button>
      <button class="ide-btn" id="ideTpl">Шаблон</button>
      <span style="flex:1"></span>
      <button class="ide-btn connect" id="ideConnect">${icon('plug-zap', 14)} Подключить коннектор</button>
      <button class="ide-btn stop" id="ideStop" hidden>${icon('circle-stop', 14)} Остановить</button>
      <button class="ide-btn" id="ideClose" title="Закрыть (Esc)">${icon('x', 14)}</button>
    </div>
    <div class="ide-mid">
      <div class="ide-act"><span class="on" title="Проводник">${icon('copy', 22)}</span><span title="Поиск">${icon('search', 22)}</span><span title="Терминал">${icon('terminal', 22)}</span></div>
      <div class="ide-explorer">
        <div class="h">Проводник — connectors</div>
        <div class="f on" id="ideFile">connector.py</div>
        <div class="h" style="margin-top:14px">Протокол</div>
        <div class="doc">
          Пульт → stdin (JSON-строки):<br>
          <code>{"type":"rc","roll":0,"pitch":0,"yaw":0,"throttle":0.5}</code><br>
          <code>{"type":"drone","cmd":"arm"}</code><br>
          cmd: arm, disarm, takeoff, land, rtl, mode<br><br>
          stdout → пульт:<br>
          <code>{"type":"telemetry","drone":{"alt":2,"battery":90,"armed":true}}</code><br>
          <code>{"type":"log","text":"..."}</code><br><br>
          Терминал — настоящий: ставьте пакеты (<code>pip install pymavlink</code>), запускайте любые команды.
        </div>
      </div>
      <div class="ide-work">
        <div class="ide-tabs"><div class="it" id="ideTab">connector.py</div></div>
        <div class="editor"><div class="gut" id="ideGut">1</div><div class="ed"><pre id="ideHl"></pre><textarea id="ideCode" spellcheck="false"></textarea></div></div>
        <div class="ide-split" id="ideSplit"></div>
        <div class="ide-panel">
          <div class="ide-ptabs"><span class="on" data-p="term">Терминал</span><span data-p="out">Вывод коннектора</span><span style="flex:1"></span><span id="ideClear">очистить</span></div>
          <div class="term-out" id="termOut"></div>
          <div class="term-in" id="termIn"><b>›</b><input id="termInput" placeholder="введите команду и нажмите Enter (например: python --version)"></div>
        </div>
      </div>
    </div>
    <div class="ide-status" id="ideStatus"><span>${icon('route', 13)} connector</span><span id="ideStLang">Python</span><span id="ideStConn">Коннектор не запущен</span><span style="flex:1"></span><span id="ideStPos">Стр 1, Стлб 1</span><span>UTF-8</span></div>
  </div>`;
  document.body.appendChild(root);
  open = root;
  const $ = (s) => root.querySelector(s);
  const ta = $('#ideCode'), hl = $('#ideHl'), gut = $('#ideGut'), langSel = $('#ideLang');
  const termOut = $('#termOut'), termInput = $('#termInput');
  let lang = 'python', panel = 'term', termId = null, connectorLog = '', termLog = '', live = false;
  const hist = []; let hIdx = 0;

  const render = () => {
    hl.innerHTML = highlight(ta.value, lang);
    const n = ta.value.split('\n').length;
    gut.textContent = Array.from({ length: n }, (_, i) => i + 1).join('\n');
    ta.style.height = hl.offsetHeight + 'px';
    ta.style.width = Math.max(hl.scrollWidth, ta.parentElement.clientWidth) + 'px';
  };
  let loaded = false;
  const setLang = async (l) => {
    if (loaded && ta.value.trim()) drafts[lang] = ta.value;
    loaded = true;
    lang = l; langSel.value = l;
    const ext = { python: 'py', javascript: 'js', typescript: 'ts', c: 'c', cpp: 'cpp', rust: 'rs', go: 'go', java: 'java', kotlin: 'kts', csharp: 'csx', lua: 'lua', ruby: 'rb', php: 'php', perl: 'pl', bash: 'sh', powershell: 'ps1' }[l];
    const fname = l === 'java' ? 'Connector.java' : `connector.${ext}`;
    $('#ideFile').textContent = fname; $('#ideTab').textContent = fname;
    $('#ideStLang').textContent = LANGS.find((x) => x[0] === l)[1];
    ta.value = drafts[l] || (await api.connector.template(l)) || TEMPLATES[l] || '';
    render();
  };
  const showPanel = (p) => {
    panel = p;
    root.querySelectorAll('.ide-ptabs [data-p]').forEach((s) => s.classList.toggle('on', s.dataset.p === p));
    $('#termIn').style.display = p === 'term' ? '' : 'none';
    termOut.textContent = p === 'term' ? termLog : connectorLog;
    termOut.scrollTop = termOut.scrollHeight;
  };
  const appendTerm = (t) => { termLog = (termLog + stripAnsi(t)).slice(-200000); if (panel === 'term') { termOut.textContent = termLog; termOut.scrollTop = termOut.scrollHeight; } };
  const appendOut = (t) => { connectorLog = (connectorLog + t).slice(-200000); if (panel === 'out') { termOut.textContent = connectorLog; termOut.scrollTop = termOut.scrollHeight; } };
  const setLive = (v) => {
    live = v;
    $('#ideConnect').classList.toggle('live', v);
    $('#ideConnect').innerHTML = v ? icon('circle-check', 14) + ' Коннектор подключён' : icon('plug-zap', 14) + ' Подключить коннектор';
    $('#ideStop').hidden = !v;
    $('#ideStatus').classList.toggle('live', v);
    $('#ideStConn').textContent = v ? 'Коннектор работает · пульт управляет через него' : 'Коннектор не запущен';
  };

  ta.addEventListener('input', render);
  ta.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') { e.preventDefault(); const s = ta.selectionStart; ta.setRangeText('    ', s, ta.selectionEnd, 'end'); render(); }
    if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); $('#ideSave').click(); }
  });
  ta.addEventListener('keyup', () => { const p = ta.value.slice(0, ta.selectionStart).split('\n'); $('#ideStPos').textContent = `Стр ${p.length}, Стлб ${p.at(-1).length + 1}`; });
  langSel.onchange = () => setLang(langSel.value);
  $('#ideTpl').onclick = async () => { delete drafts[lang]; ta.value = (await api.connector.template(lang)) || TEMPLATES[lang] || ''; render(); };
  $('#ideSave').onclick = async () => { const p = await api.file.save({ name: $('#ideFile').textContent, content: ta.value }); if (p) appendTerm(`\n[сохранено] ${p}\n`); };
  $('#ideOpen').onclick = async () => { const f = await api.file.open(); if (f) { ta.value = f.content; render(); appendTerm(`\n[открыт] ${f.path}\n`); } };
  root.querySelectorAll('.ide-ptabs [data-p]').forEach((s) => (s.onclick = () => showPanel(s.dataset.p)));
  $('#ideClear').onclick = () => { if (panel === 'term') termLog = ''; else connectorLog = ''; showPanel(panel); };

  // перетаскивание разделителя редактор/терминал
  $('#ideSplit').onpointerdown = (e) => {
    const work = root.querySelector('.ide-work'), startY = e.clientY, startH = parseInt(getComputedStyle(work).getPropertyValue('--panel-h')) || 240;
    const mv = (ev) => work.style.setProperty('--panel-h', Math.max(100, Math.min(600, startH - (ev.clientY - startY))) + 'px');
    const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); };
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  };

  // настоящий терминал
  const t = await api.term.start();
  termId = t.id;
  appendTerm(`STELLS Terminal — ${t.shell}\nРабочая папка: ${t.cwd}\n\n`);
  const offData = api.term.onData(({ id, data }) => id === termId && appendTerm(data));
  const offExit = api.term.onExit(({ id, code }) => { if (id === termId) { appendTerm(`\n[оболочка завершена, код ${code}] Перезапуск…\n`); api.term.start().then((n) => (termId = n.id)); } });
  termInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const cmd = termInput.value; termInput.value = '';
      if (cmd.trim()) { hist.push(cmd); hIdx = hist.length; }
      appendTerm(`› ${cmd}\n`);
      if (cmd.trim() === 'clear' || cmd.trim() === 'cls') { termLog = ''; showPanel('term'); return; }
      api.term.write(termId, cmd + '\n');
    } else if (e.key === 'ArrowUp') { if (hIdx > 0) termInput.value = hist[--hIdx]; e.preventDefault(); }
    else if (e.key === 'ArrowDown') { termInput.value = hIdx < hist.length - 1 ? hist[++hIdx] : (hIdx = hist.length, ''); e.preventDefault(); }
    else if (e.key === 'c' && e.ctrlKey) { api.term.kill(termId); }
  });

  // коннектор
  const offCData = api.connector.onData((d) => appendOut(d));
  const offClosed = api.connector.onClosed(() => setLive(false));
  $('#ideConnect').onclick = async () => {
    showPanel('out');
    appendOut(`\n[STELLS] Запуск коннектора (${$('#ideStLang').textContent})…\n`);
    const r = await api.connector.start(lang, ta.value);
    if (!r.ok) { appendOut(`[STELLS] Ошибка: ${r.reason}\n`); return; }
    appendOut(`[STELLS] Файл: ${r.file}\n[STELLS] Коннектор подключён. Пульт теперь управляет дроном через ваш скрипт.\n`);
    link.useConnector();
    setLive(true);
    onConnected && onConnected();
  };
  $('#ideStop').onclick = async () => { await link.disconnect(); setLive(false); };

  const close = () => {
    offData(); offExit(); offCData(); offClosed();
    api.term.kill(termId);
    root.remove(); open = null;
  };
  $('#ideClose').onclick = close;
  root.addEventListener('mousedown', (e) => { if (e.target === root) close(); });
  addEventListener('keydown', function escH(e) { if (e.key === 'Escape' && open === root) { close(); removeEventListener('keydown', escH); } });

  if (link.via === 'connector') setLive(true);
  await setLang('python');
  ta.focus();
}
