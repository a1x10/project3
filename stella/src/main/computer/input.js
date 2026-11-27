'use strict';
// Построение команд эмуляции мыши/клавиатуры для Windows / macOS / Linux.
// Функции build* чистые (возвращают {cmd, args}) — их легко тестировать.

const WIN_VK = {
  ctrl: 0x11, control: 0x11, shift: 0x10, alt: 0x12, win: 0x5b, meta: 0x5b, cmd: 0x5b, super: 0x5b,
  enter: 0x0d, return: 0x0d, tab: 0x09, esc: 0x1b, escape: 0x1b, backspace: 0x08, delete: 0x2e, del: 0x2e,
  space: 0x20, up: 0x26, down: 0x28, left: 0x25, right: 0x27, home: 0x24, end: 0x23, pageup: 0x21, pagedown: 0x22,
  insert: 0x2d, printscreen: 0x2c, capslock: 0x14, menu: 0x5d,
  volumeup: 0xaf, volumedown: 0xae, volumemute: 0xad, mute: 0xad,
  playpause: 0xb3, nexttrack: 0xb0, prevtrack: 0xb1, stop: 0xb2,
  ',': 0xbc, '.': 0xbe, '-': 0xbd, '=': 0xbb, ';': 0xba, '/': 0xbf, '`': 0xc0, '[': 0xdb, ']': 0xdd, '\\': 0xdc, "'": 0xde,
};
for (let i = 1; i <= 12; i++) WIN_VK['f' + i] = 0x6f + i;

const XDO_KEYS = {
  ctrl: 'ctrl', control: 'ctrl', shift: 'shift', alt: 'alt', win: 'super', meta: 'super', cmd: 'super', super: 'super',
  enter: 'Return', return: 'Return', tab: 'Tab', esc: 'Escape', escape: 'Escape', backspace: 'BackSpace', delete: 'Delete', del: 'Delete',
  space: 'space', up: 'Up', down: 'Down', left: 'Left', right: 'Right', home: 'Home', end: 'End', pageup: 'Prior', pagedown: 'Next',
  insert: 'Insert', printscreen: 'Print', capslock: 'Caps_Lock', menu: 'Menu',
  volumeup: 'XF86AudioRaiseVolume', volumedown: 'XF86AudioLowerVolume', volumemute: 'XF86AudioMute', mute: 'XF86AudioMute',
  playpause: 'XF86AudioPlay', nexttrack: 'XF86AudioNext', prevtrack: 'XF86AudioPrev', stop: 'XF86AudioStop',
};
for (let i = 1; i <= 12; i++) XDO_KEYS['f' + i] = 'F' + i;

const MAC_KEYCODES = {
  enter: 36, return: 36, tab: 48, esc: 53, escape: 53, backspace: 51, delete: 117, del: 117, space: 49,
  up: 126, down: 125, left: 123, right: 124, home: 115, end: 119, pageup: 116, pagedown: 121,
  f1: 122, f2: 120, f3: 99, f4: 118, f5: 96, f6: 97, f7: 98, f8: 100, f9: 101, f10: 109, f11: 103, f12: 111,
};
const MAC_MODS = { ctrl: 'control down', control: 'control down', shift: 'shift down', alt: 'option down', option: 'option down', cmd: 'command down', meta: 'command down', win: 'command down', super: 'command down' };

/** Разбирает «ctrl+shift+s» → ['ctrl','shift','s'] */
function parseCombo(combo) {
  const parts = String(combo || '').toLowerCase().replace(/\s+/g, '').split('+').filter(Boolean);
  if (!parts.length) throw new Error('Пустая комбинация клавиш');
  return parts.map((p) => ({ 'контрл': 'ctrl', 'ввод': 'enter', 'пробел': 'space' }[p] || p));
}

function winVk(key) {
  if (key in WIN_VK) return WIN_VK[key];
  if (/^[a-z]$/.test(key)) return key.toUpperCase().charCodeAt(0);
  if (/^[0-9]$/.test(key)) return key.charCodeAt(0);
  throw new Error(`Неизвестная клавиша: ${key}`);
}

function psQuote(s) { return "'" + String(s).replace(/'/g, "''") + "'"; }

function escapeSendKeys(text) {
  return String(text).replace(/[+^%~(){}[\]]/g, (c) => `{${c}}`).replace(/\r?\n/g, '{ENTER}').replace(/\t/g, '{TAB}');
}

const WIN_HELPER = `
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
public static class StellaInput {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, int dx, int dy, int d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, UIntPtr e);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint type);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  public static void KeyScan(byte vk, bool up) { keybd_event(vk, (byte)MapVirtualKey(vk, 0), (up ? 2u : 0u) | 8u, UIntPtr.Zero); }
  public struct POINT { public int X; public int Y; }
  public static void Key(byte vk, bool up) { keybd_event(vk, 0, up ? 2u : 0u, UIntPtr.Zero); }
}
"@
[void][StellaInput]::SetProcessDPIAware()
`;

function encodePs(script) { return Buffer.from(script, 'utf16le').toString('base64'); }
function ps(script) {
  return { cmd: 'powershell.exe', args: ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', encodePs(script)], script };
}
function jxa(script) { return { cmd: 'osascript', args: ['-l', 'JavaScript', '-e', script], script }; }

const BTN = { left: [0x02, 0x04], right: [0x08, 0x10], middle: [0x20, 0x40] };

function int(v, name) {
  const n = Math.round(Number(v));
  if (!Number.isFinite(n)) throw new Error(`Некорректная координата ${name}`);
  return n;
}

function buildMouseMove(platform, x, y) {
  x = int(x, 'x'); y = int(y, 'y');
  if (platform === 'win32') return ps(WIN_HELPER + `[void][StellaInput]::SetCursorPos(${x}, ${y})`);
  if (platform === 'darwin') return jxa(`ObjC.import('CoreGraphics'); var e=$.CGEventCreateMouseEvent(null, 5, $.CGPointMake(${x}, ${y}), 0); $.CGEventPost(0, e);`);
  return { cmd: 'xdotool', args: ['mousemove', String(x), String(y)] };
}

function buildClick(platform, { x, y, button = 'left', double = false } = {}) {
  if (!BTN[button]) throw new Error('Кнопка мыши: left, right или middle');
  const hasPos = x !== undefined && y !== undefined && x !== null && y !== null;
  if (hasPos) { x = int(x, 'x'); y = int(y, 'y'); }
  const times = double ? 2 : 1;
  if (platform === 'win32') {
    const [d, u] = BTN[button];
    let s = WIN_HELPER + (hasPos ? `[void][StellaInput]::SetCursorPos(${x}, ${y}); Start-Sleep -Milliseconds 40\n` : '');
    for (let i = 0; i < times; i++) s += `[StellaInput]::mouse_event(${d},0,0,0,[UIntPtr]::Zero); [StellaInput]::mouse_event(${u},0,0,0,[UIntPtr]::Zero); Start-Sleep -Milliseconds 60\n`;
    return ps(s);
  }
  if (platform === 'darwin') {
    const [dn, up] = { left: [1, 2], right: [3, 4], middle: [25, 26] }[button];
    const pos = hasPos ? `$.CGPointMake(${x}, ${y})` : '$.CGEventGetLocation($.CGEventCreate(null))';
    let s = `ObjC.import('CoreGraphics'); var p=${pos}; $.CGEventPost(0, $.CGEventCreateMouseEvent(null, 5, p, 0));`;
    for (let i = 0; i < times; i++) s += `var d=$.CGEventCreateMouseEvent(null, ${dn}, p, ${button === 'right' ? 1 : 0}); $.CGEventSetIntegerValueField(d, 1, ${i + 1}); $.CGEventPost(0, d); var u=$.CGEventCreateMouseEvent(null, ${up}, p, ${button === 'right' ? 1 : 0}); $.CGEventSetIntegerValueField(u, 1, ${i + 1}); $.CGEventPost(0, u);`;
    return jxa(s);
  }
  const b = { left: '1', right: '3', middle: '2' }[button];
  const args = hasPos ? ['mousemove', String(x), String(y), 'click'] : ['click'];
  if (double) args.push('--repeat', '2');
  args.push(b);
  return { cmd: 'xdotool', args };
}

function buildScroll(platform, amount = -3) {
  const n = Math.max(-50, Math.min(50, Math.round(Number(amount) || 0)));
  if (!n) throw new Error('Количество прокрутки не должно быть 0');
  if (platform === 'win32') return ps(WIN_HELPER + `[StellaInput]::mouse_event(0x0800,0,0,${n * 120},[UIntPtr]::Zero)`);
  if (platform === 'darwin') return jxa(`ObjC.import('CoreGraphics'); $.CGEventPost(0, $.CGEventCreateScrollWheelEvent(null, 0, 1, ${n * 3}));`);
  return { cmd: 'xdotool', args: ['click', '--repeat', String(Math.abs(n)), n > 0 ? '4' : '5'] };
}

function buildDrag(platform, from, to) {
  const [x1, y1, x2, y2] = [int(from.x, 'x'), int(from.y, 'y'), int(to.x, 'x'), int(to.y, 'y')];
  if (platform === 'win32') {
    let s = WIN_HELPER + `[void][StellaInput]::SetCursorPos(${x1}, ${y1}); Start-Sleep -Milliseconds 50; [StellaInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero)\n`;
    s += `for($i=1;$i -le 20;$i++){ [void][StellaInput]::SetCursorPos([int](${x1}+(${x2}-${x1})*$i/20), [int](${y1}+(${y2}-${y1})*$i/20)); Start-Sleep -Milliseconds 15 }\n`;
    s += '[StellaInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero)';
    return ps(s);
  }
  if (platform === 'darwin') {
    return jxa(`ObjC.import('CoreGraphics'); $.CGEventPost(0,$.CGEventCreateMouseEvent(null,1,$.CGPointMake(${x1},${y1}),0)); for(var i=1;i<=20;i++){ $.CGEventPost(0,$.CGEventCreateMouseEvent(null,6,$.CGPointMake(${x1}+(${x2 - x1})*i/20,${y1}+(${y2 - y1})*i/20),0)); delay(0.015);} $.CGEventPost(0,$.CGEventCreateMouseEvent(null,2,$.CGPointMake(${x2},${y2}),0));`);
  }
  return { cmd: 'xdotool', args: ['mousemove', String(x1), String(y1), 'mousedown', '1', 'mousemove', '--sync', String(x2), String(y2), 'mouseup', '1'] };
}

function buildTypeText(platform, text) {
  const t = String(text ?? '');
  if (!t) throw new Error('Пустой текст');
  if (t.length > 5000) throw new Error('Слишком длинный текст (максимум 5000 символов)');
  if (platform === 'win32') return ps(`Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait(${psQuote(escapeSendKeys(t))})`);
  if (platform === 'darwin') return jxa(`Application('System Events').keystroke(${JSON.stringify(t)});`);
  return { cmd: 'xdotool', args: ['type', '--delay', '12', '--', t] };
}

function buildKeyCombo(platform, combo) {
  const keys = parseCombo(combo);
  if (platform === 'win32') {
    const vks = keys.map(winVk);
    let s = WIN_HELPER;
    for (const vk of vks) s += `[StellaInput]::Key(${vk}, $false); Start-Sleep -Milliseconds 20\n`;
    for (const vk of [...vks].reverse()) s += `[StellaInput]::Key(${vk}, $true)\n`;
    return ps(s);
  }
  if (platform === 'darwin') {
    const mods = keys.filter((k) => MAC_MODS[k]).map((k) => MAC_MODS[k]);
    const main = keys.filter((k) => !MAC_MODS[k]);
    if (main.length !== 1) throw new Error('На macOS нужна ровно одна основная клавиша в комбинации');
    const k = main[0];
    const using = mods.length ? `, {using: ${JSON.stringify(mods)}}` : '';
    if (k in MAC_KEYCODES) return jxa(`Application('System Events').keyCode(${MAC_KEYCODES[k]}${using});`);
    if (k.length === 1) return jxa(`Application('System Events').keystroke(${JSON.stringify(k)}${using});`);
    throw new Error(`Неизвестная клавиша: ${k}`);
  }
  const mapped = keys.map((k) => XDO_KEYS[k] || (k.length === 1 ? k : null));
  if (mapped.includes(null)) throw new Error(`Неизвестная клавиша в «${combo}»`);
  return { cmd: 'xdotool', args: ['key', mapped.join('+')] };
}

function buildCursorPosition(platform) {
  if (platform === 'win32') return ps(WIN_HELPER + '$p = New-Object StellaInput+POINT; [void][StellaInput]::GetCursorPos([ref]$p); Write-Output "$($p.X),$($p.Y)"');
  if (platform === 'darwin') return jxa("ObjC.import('CoreGraphics'); var p=$.CGEventGetLocation($.CGEventCreate(null)); Math.round(p.x)+','+Math.round(p.y);");
  return { cmd: 'xdotool', args: ['getmouselocation', '--shell'] };
}

function buildListWindows(platform) {
  if (platform === 'win32') return ps("Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object Id, ProcessName, MainWindowTitle | ConvertTo-Json -Compress");
  if (platform === 'darwin') return jxa("var se=Application('System Events'); JSON.stringify(se.processes.whose({backgroundOnly:false})().map(function(p){ try { return {name:p.name(), windows:p.windows().map(function(w){return w.name();})}; } catch(e){ return {name:p.name()}; } }));");
  return { cmd: 'wmctrl', args: ['-l', '-p'] };
}

function buildFocusWindow(platform, title) {
  const t = String(title || '').trim();
  if (!t) throw new Error('Укажите заголовок или имя окна');
  if (platform === 'win32') {
    return ps(`$w = New-Object -ComObject WScript.Shell; $p = Get-Process | Where-Object { $_.MainWindowTitle -like ${psQuote('*' + t + '*')} -or $_.ProcessName -like ${psQuote('*' + t + '*')} } | Select-Object -First 1; if ($p) { [void]$w.AppActivate($p.Id); Write-Output "OK: $($p.MainWindowTitle)" } else { Write-Output 'NOT_FOUND' }`);
  }
  if (platform === 'darwin') return jxa(`Application(${JSON.stringify(t)}).activate(); 'OK';`);
  return { cmd: 'wmctrl', args: ['-a', t] };
}

function buildMedia(platform, action) {
  const map = { play_pause: 'playpause', next: 'nexttrack', previous: 'prevtrack', stop: 'stop', volume_up: 'volumeup', volume_down: 'volumedown', mute: 'volumemute' };
  const key = map[action];
  if (!key) throw new Error('Действие: play_pause, next, previous, stop, volume_up, volume_down, mute');
  if (platform === 'darwin') {
    if (action === 'volume_up') return jxa('var a=Application.currentApplication(); a.includeStandardAdditions=true; var v=a.getVolumeSettings().outputVolume; a.setVolume(null,{outputVolume:Math.min(100,v+10)});');
    if (action === 'volume_down') return jxa('var a=Application.currentApplication(); a.includeStandardAdditions=true; var v=a.getVolumeSettings().outputVolume; a.setVolume(null,{outputVolume:Math.max(0,v-10)});');
    if (action === 'mute') return jxa('var a=Application.currentApplication(); a.includeStandardAdditions=true; a.setVolume(null,{outputMuted:!a.getVolumeSettings().outputMuted});');
    const cmd = { play_pause: 'playpause', next: 'next track', previous: 'previous track', stop: 'pause' }[action];
    return { cmd: 'osascript', args: ['-e', `tell application "Music" to ${cmd}`] };
  }
  return buildKeyCombo(platform, key);
}

function buildSetVolume(platform, level) {
  const v = Math.max(0, Math.min(100, Math.round(Number(level))));
  if (!Number.isFinite(v)) throw new Error('Громкость 0–100');
  if (platform === 'win32') {
    // 50 нажатий «тише» (обнуление), затем v/2 нажатий «громче» (шаг 2%)
    return ps(WIN_HELPER + `for($i=0;$i -lt 50;$i++){[StellaInput]::Key(0xAE,$false);[StellaInput]::Key(0xAE,$true)}; for($i=0;$i -lt ${Math.round(v / 2)};$i++){[StellaInput]::Key(0xAF,$false);[StellaInput]::Key(0xAF,$true)}`);
  }
  if (platform === 'darwin') return { cmd: 'osascript', args: ['-e', `set volume output volume ${v}`] };
  return { cmd: 'pactl', args: ['set-sink-volume', '@DEFAULT_SINK@', `${v}%`] };
}

/** Удержать клавиши N мс (для игр: WASD, пробел…). На Windows — скан-коды, их видят DirectInput-игры. */
function buildHoldKeys(platform, combo, ms = 500) {
  const keys = parseCombo(combo);
  const dur = Math.max(30, Math.min(10000, Math.round(Number(ms) || 500)));
  if (platform === 'win32') {
    const vks = keys.map(winVk);
    let s = WIN_HELPER;
    for (const vk of vks) s += `[StellaInput]::KeyScan(${vk}, $false)\n`;
    s += `Start-Sleep -Milliseconds ${dur}\n`;
    for (const vk of [...vks].reverse()) s += `[StellaInput]::KeyScan(${vk}, $true)\n`;
    return ps(s);
  }
  if (platform === 'darwin') throw new Error('Удержание клавиш на macOS пока не поддерживается — используйте press_keys');
  const mapped = keys.map((k) => XDO_KEYS[k] || (k.length === 1 ? k : null));
  if (mapped.includes(null)) throw new Error(`Неизвестная клавиша в «${combo}»`);
  const k = mapped.join('+');
  return { cmd: 'xdotool', args: ['keydown', k, 'sleep', String(dur / 1000), 'keyup', k] };
}

/** Относительное движение мыши (поворот камеры в 3D-играх). */
function buildMouseRelative(platform, dx, dy) {
  const x = int(dx, 'dx'), y = int(dy, 'dy');
  if (platform === 'win32') return ps(WIN_HELPER + `[StellaInput]::mouse_event(1, ${x}, ${y}, 0, [UIntPtr]::Zero)`);
  if (platform === 'darwin') return jxa(`ObjC.import('CoreGraphics'); var p=$.CGEventGetLocation($.CGEventCreate(null)); $.CGEventPost(0, $.CGEventCreateMouseEvent(null, 5, $.CGPointMake(p.x+${x}, p.y+${y}), 0));`);
  return { cmd: 'xdotool', args: ['mousemove_relative', '--', String(x), String(y)] };
}

const UIA_PRELUDE = `Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$h = [StellaInput]::GetForegroundWindow()
$root = [System.Windows.Automation.AutomationElement]::FromHandle($h)
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
`;

/** Список элементов интерфейса активного окна (Windows UI Automation). */
function buildUiList(platform, filter = '') {
  if (platform !== 'win32') throw new Error('Чтение элементов интерфейса доступно только на Windows. Используйте take_screenshot.');
  return ps(WIN_HELPER + UIA_PRELUDE + `$f = ${psQuote(String(filter || '').toLowerCase())}
"Окно: " + $root.Current.Name
$n = 0
foreach ($e in $all) {
  $c = $e.Current
  if ($c.IsOffscreen -or -not $c.Name) { continue }
  $r = $c.BoundingRectangle
  if ($r.Width -le 0 -or $r.Height -le 0) { continue }
  if ($f -and -not $c.Name.ToLower().Contains($f)) { continue }
  "{0} | {1} | {2},{3}" -f $c.ControlType.ProgrammaticName.Replace('ControlType.', ''), $c.Name.Replace("\`n", ' '), [int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2)
  $n++; if ($n -ge 150) { "…(показаны первые 150)"; break }
}`);
}

/** Нажать на элемент интерфейса по названию (InvokePattern или клик по центру). */
function buildUiClick(platform, name) {
  if (platform !== 'win32') throw new Error('Клик по элементам доступен только на Windows. Используйте скриншот и mouse_click.');
  const n = String(name || '').trim();
  if (!n) throw new Error('Укажите название элемента');
  return ps(WIN_HELPER + UIA_PRELUDE + `$q = ${psQuote(n.toLowerCase())}
$best = $null
foreach ($e in $all) { $c = $e.Current; if ($c.IsOffscreen -or -not $c.Name) { continue }; $nm = $c.Name.ToLower(); if ($nm -eq $q) { $best = $e; break }; if (-not $best -and $nm.Contains($q)) { $best = $e } }
if (-not $best) { 'NOT_FOUND'; exit }
$c = $best.Current
try { $p = $best.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern); $p.Invoke(); "INVOKED: " + $c.Name }
catch { $r = $c.BoundingRectangle; [void][StellaInput]::SetCursorPos([int]($r.X + $r.Width / 2), [int]($r.Y + $r.Height / 2)); Start-Sleep -Milliseconds 40; [StellaInput]::mouse_event(2,0,0,0,[UIntPtr]::Zero); [StellaInput]::mouse_event(4,0,0,0,[UIntPtr]::Zero); "CLICKED: " + $c.Name }`);
}

module.exports = {
  buildHoldKeys, buildMouseRelative, buildUiList, buildUiClick,
  parseCombo, escapeSendKeys, psQuote, encodePs, winVk,
  buildMouseMove, buildClick, buildScroll, buildDrag, buildTypeText, buildKeyCombo, buildCursorPosition,
  buildListWindows, buildFocusWindow, buildMedia, buildSetVolume,
  WIN_VK, XDO_KEYS, MAC_KEYCODES,
};
