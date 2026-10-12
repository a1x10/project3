// Терминал: команды бота с историей и автодополнением, живой журнал (logs -f).
// Это не shell сервера — выполняются только команды бота (список: help).
import { clock, h, on, post } from '../lib.js';

const COMMANDS = ['help', 'status', 'logs', 'logs -f', 'dz', 'week', 'lessons', 'check', 'digest preview', 'digest send', 'plan', 'pause', 'resume', 'skip', 'groups', 'queue',
  'wa status', 'wa reconnect', 'bilim status', 'bilim relogin', 'ai ask', 'ai keys', 'send', 'get', 'set', 'settings', 'alerts', 'uptime', 'whoami', 'date', 'clear', 'restart'];
const BANNER = [
  '  ____   ___ _____   ____ _____',
  ' | __ ) / _ \\_   _| |  _ \\__  /',
  " |  _ \\| | | || |   | | | |/ / ",
  ' | |_) | |_| || |   | |_| / /_ ',
  ' |____/ \\___/ |_|   |____/____|',
].join('\n');

export async function render(root) {
  const out = h('div.term-out', { role: 'log', 'aria-live': 'polite' });
  const input = h('input', { type: 'text', autocomplete: 'off', spellcheck: false, 'aria-label': 'Команда', autocapitalize: 'off' });
  const prompt = 'admin@бот-дз:~$';
  const term = h('div.term',
    h('div.term-bar', h('i'), h('i'), h('i'), 'терминал бота — команды и журнал', h('span.follow', '● живой журнал · Ctrl+C — стоп')),
    out,
    h('label.term-in', h('span.pr', prompt), input));
  root.append(term);

  let history = [];
  try {
    history = JSON.parse(sessionStorage.getItem('hwb-term-history') || '[]');
  } catch {
    history = [];
  }
  let pos = history.length;
  let following = false;
  let busy = false;

  const scroll = () => {
    out.scrollTop = out.scrollHeight;
  };
  const print = (text, cls) => {
    out.append(h(`div${cls ? `.${cls}` : ''}`, text));
    while (out.children.length > 1500) out.firstChild.remove();
  };
  const printLog = (item) => {
    const cls = item.level === 'error' || item.level === 'fatal' ? 'err' : item.level === 'warn' ? 'warn' : '';
    const extra = item.extra ? ` ${JSON.stringify(item.extra)}` : '';
    out.append(h(`div.lg${cls ? `.${cls}` : ''}`, h('time', `${clock(item.time)} `), item.module ? h('span.m', `[${item.module}] `) : null, `${item.msg}${extra.length < 300 ? extra : ''}`));
    while (out.children.length > 1500) out.firstChild.remove();
  };

  print(BANNER, 'banner-art');
  print('Терминал бота ДЗ. Здесь работают команды бота — не shell сервера.', 'dim');
  print('Начните с help или status. Tab — дополнение, ↑/↓ — история, Ctrl+L — очистить.', 'dim');
  print('');

  function setFollowing(value) {
    following = value;
    term.classList.toggle('following', value);
  }

  async function run(command) {
    const text = command.trim();
    out.append(h('div.cmd', h('span.pr', `${prompt} `), text));
    if (!text) return scroll();
    if (history.at(-1) !== text) history.push(text);
    history = history.slice(-100);
    pos = history.length;
    try {
      sessionStorage.setItem('hwb-term-history', JSON.stringify(history));
    } catch {
      /* без истории */
    }
    busy = true;
    input.disabled = true;
    const spinner = h('div.dim', '…');
    out.append(spinner);
    scroll();
    try {
      const { output } = await post('/api/console', { command: text });
      spinner.remove();
      for (const line of output) {
        if (line.clear) out.replaceChildren();
        else if (line.follow) {
          setFollowing(true);
          print('Живой журнал включён. Ctrl+C — остановить.', 'dim');
        } else if (line.log) printLog(line.log);
        else print(line.t, line.c);
      }
    } catch (error) {
      spinner.remove();
      print(`Ошибка: ${error.message}`, 'err');
    } finally {
      busy = false;
      input.disabled = false;
      input.focus();
      scroll();
    }
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      if (busy) return;
      const value = input.value;
      input.value = '';
      run(value);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (pos > 0) input.value = history[--pos] || '';
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      pos = Math.min(history.length, pos + 1);
      input.value = history[pos] || '';
    } else if (e.key === 'Tab') {
      e.preventDefault();
      const v = input.value.toLowerCase();
      const matches = COMMANDS.filter((c) => c.startsWith(v));
      if (matches.length === 1) input.value = `${matches[0]} `;
      else if (matches.length > 1) {
        out.append(h('div.cmd', h('span.pr', `${prompt} `), input.value));
        print(matches.join('   '), 'dim');
        const common = matches.reduce((a, b) => {
          let i = 0;
          while (i < a.length && a[i] === b[i]) i += 1;
          return a.slice(0, i);
        });
        input.value = common;
        scroll();
      }
    } else if (e.key === 'c' && e.ctrlKey && !window.getSelection()?.toString()) {
      if (following) {
        setFollowing(false);
        print('^C — живой журнал остановлен', 'dim');
      } else {
        out.append(h('div.cmd', h('span.pr', `${prompt} `), `${input.value}^C`));
        input.value = '';
      }
      scroll();
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault();
      out.replaceChildren();
    }
  });
  out.addEventListener('click', () => {
    if (!window.getSelection()?.toString()) input.focus();
  });

  const off = on('sse:log', (item) => {
    if (!following) return;
    const atBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 80;
    printLog(item);
    if (atBottom) scroll();
  });
  input.focus();
  return () => off();
}
