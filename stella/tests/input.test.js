import { describe, it, expect } from 'vitest';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const I = require('../src/main/computer/input.js');

const decode = (built) => Buffer.from(built.args.at(-1), 'base64').toString('utf16le');

describe('Разбор сочетаний клавиш', () => {
  it('ctrl+shift+s', () => expect(I.parseCombo('Ctrl + Shift + S')).toEqual(['ctrl', 'shift', 's']));
  it('русские названия', () => expect(I.parseCombo('ввод')).toEqual(['enter']));
  it('пустое — ошибка', () => expect(() => I.parseCombo('')).toThrow());
  it('VK коды Windows', () => {
    expect(I.winVk('a')).toBe(0x41);
    expect(I.winVk('z')).toBe(0x5a);
    expect(I.winVk('5')).toBe(0x35);
    expect(I.winVk('enter')).toBe(0x0d);
    expect(I.winVk('f5')).toBe(0x74);
    expect(I.winVk('win')).toBe(0x5b);
    expect(() => I.winVk('nope')).toThrow(/Неизвестная/);
  });
});

describe('SendKeys экранирование', () => {
  it('спецсимволы в скобках', () => expect(I.escapeSendKeys('a+b^c%d~(e){f}[g]')).toBe('a{+}b{^}c{%}d{~}{(}e{)}{{}f{}}{[}g{]}'));
  it('переводы строк и табы', () => expect(I.escapeSendKeys('a\nb\tc')).toBe('a{ENTER}b{TAB}c'));
  it('кириллица без изменений', () => expect(I.escapeSendKeys('Привет')).toBe('Привет'));
  it('кавычки PowerShell', () => expect(I.psQuote("it's")).toBe("'it''s'"));
});

describe('Windows (PowerShell)', () => {
  it('перемещение мыши', () => {
    const b = I.buildMouseMove('win32', 100.4, 200.6);
    expect(b.cmd).toBe('powershell.exe');
    expect(b.args).toContain('-EncodedCommand');
    expect(decode(b)).toContain('SetCursorPos(100, 201)');
    expect(decode(b)).toContain('SetProcessDPIAware');
  });
  it('клик правой кнопкой', () => expect(decode(I.buildClick('win32', { x: 1, y: 2, button: 'right' }))).toMatch(/mouse_event\(8,.*mouse_event\(16,/s));
  it('двойной клик — два нажатия', () => expect(decode(I.buildClick('win32', { double: true })).match(/mouse_event\(2,/g)).toHaveLength(2));
  it('клик без координат не двигает курсор', () => expect(decode(I.buildClick('win32', {}))).not.toContain('::SetCursorPos('));
  it('прокрутка', () => expect(decode(I.buildScroll('win32', -3))).toContain('-360'));
  it('ввод текста через SendKeys', () => expect(decode(I.buildTypeText('win32', 'Hi+'))).toContain("SendWait('Hi{+}')"));
  it('сочетание: нажатия и отпускания в обратном порядке', () => {
    const s = decode(I.buildKeyCombo('win32', 'ctrl+c'));
    expect(s.indexOf('Key(17, $false)')).toBeLessThan(s.indexOf('Key(67, $false)'));
    expect(s.indexOf('Key(67, $true)')).toBeLessThan(s.indexOf('Key(17, $true)'));
  });
  it('перетаскивание', () => expect(decode(I.buildDrag('win32', { x: 0, y: 0 }, { x: 10, y: 10 }))).toContain('mouse_event(4'));
  it('громкость', () => expect(decode(I.buildSetVolume('win32', 50))).toContain('-lt 25'));
  it('фокус окна', () => expect(decode(I.buildFocusWindow('win32', 'Telegram'))).toContain("'*Telegram*'"));
  it('медиа play/pause', () => expect(decode(I.buildMedia('win32', 'play_pause'))).toContain('Key(179'));
});

describe('Linux (xdotool)', () => {
  it('клик в точке', () => expect(I.buildClick('linux', { x: 5, y: 6 })).toEqual({ cmd: 'xdotool', args: ['mousemove', '5', '6', 'click', '1'] }));
  it('двойной клик', () => expect(I.buildClick('linux', { double: true }).args).toEqual(['click', '--repeat', '2', '1']));
  it('прокрутка вверх/вниз', () => {
    expect(I.buildScroll('linux', 2).args).toEqual(['click', '--repeat', '2', '4']);
    expect(I.buildScroll('linux', -4).args).toEqual(['click', '--repeat', '4', '5']);
  });
  it('ввод текста — без shell, безопасно', () => expect(I.buildTypeText('linux', '$(rm -rf ~)').args).toEqual(['type', '--delay', '12', '--', '$(rm -rf ~)']));
  it('сочетания клавиш', () => {
    expect(I.buildKeyCombo('linux', 'ctrl+alt+t').args).toEqual(['key', 'ctrl+alt+t']);
    expect(I.buildKeyCombo('linux', 'win+d').args).toEqual(['key', 'super+d']);
    expect(I.buildKeyCombo('linux', 'enter').args).toEqual(['key', 'Return']);
  });
  it('громкость через pactl', () => expect(I.buildSetVolume('linux', 130)).toEqual({ cmd: 'pactl', args: ['set-sink-volume', '@DEFAULT_SINK@', '100%'] }));
  it('позиция курсора', () => expect(I.buildCursorPosition('linux').args).toContain('getmouselocation'));
});

describe('macOS (JXA)', () => {
  it('клик через CoreGraphics', () => {
    const b = I.buildClick('darwin', { x: 10, y: 20 });
    expect(b.cmd).toBe('osascript');
    expect(b.args[1]).toBe('JavaScript');
    expect(b.script).toContain('CGPointMake(10, 20)');
  });
  it('cmd+c', () => expect(I.buildKeyCombo('darwin', 'cmd+c').script).toContain('"command down"'));
  it('специальная клавиша через keyCode', () => expect(I.buildKeyCombo('darwin', 'enter').script).toContain('keyCode(36'));
  it('ровно одна основная клавиша', () => expect(() => I.buildKeyCombo('darwin', 'a+b')).toThrow());
  it('текст экранируется через JSON', () => expect(I.buildTypeText('darwin', 'a"b').script).toContain('"a\\"b"'));
});

describe('Валидация', () => {
  it('некорректные координаты', () => expect(() => I.buildMouseMove('linux', 'abc', 1)).toThrow(/координата/));
  it('неизвестная кнопка', () => expect(() => I.buildClick('linux', { button: 'side' })).toThrow());
  it('нулевая прокрутка', () => expect(() => I.buildScroll('linux', 0)).toThrow());
  it('пустой текст', () => expect(() => I.buildTypeText('linux', '')).toThrow());
  it('слишком длинный текст', () => expect(() => I.buildTypeText('linux', 'x'.repeat(5001))).toThrow());
  it('неизвестное медиа-действие', () => expect(() => I.buildMedia('linux', 'rewind')).toThrow());
  it('пустой заголовок окна', () => expect(() => I.buildFocusWindow('linux', ' ')).toThrow());
});

describe('Игровой ввод и UI Automation', () => {
  it('удержание клавиш на Windows через скан-коды', () => {
    const s = decode(I.buildHoldKeys('win32', 'shift+w', 1500));
    expect(s).toContain('KeyScan(16, $false)');
    expect(s).toContain('KeyScan(87, $false)');
    expect(s).toContain('Start-Sleep -Milliseconds 1500');
    expect(s.indexOf('KeyScan(87, $true)')).toBeLessThan(s.indexOf('KeyScan(16, $true)'));
  });
  it('удержание ограничено 10 секундами', () => expect(decode(I.buildHoldKeys('win32', 'w', 99999))).toContain('Milliseconds 10000'));
  it('удержание на Linux', () => expect(I.buildHoldKeys('linux', 'space', 500).args).toEqual(['keydown', 'space', 'sleep', '0.5', 'keyup', 'space']));
  it('удержание на macOS не поддерживается', () => expect(() => I.buildHoldKeys('darwin', 'w', 100)).toThrow(/macOS/));
  it('относительное движение мыши', () => {
    expect(decode(I.buildMouseRelative('win32', -50, 10))).toContain('mouse_event(1, -50, 10');
    expect(I.buildMouseRelative('linux', 5, -5).args).toEqual(['mousemove_relative', '--', '5', '-5']);
  });
  it('список элементов окна (Windows)', () => {
    const s = decode(I.buildUiList('win32', 'Сохранить'));
    expect(s).toContain('UIAutomationClient');
    expect(s).toContain("'сохранить'");
    expect(s).toContain('GetForegroundWindow');
  });
  it('клик по элементу экранирует кавычки', () => expect(decode(I.buildUiClick('win32', "it's"))).toContain("'it''s'"));
  it('UI Automation только на Windows', () => {
    expect(() => I.buildUiList('linux')).toThrow(/Windows/);
    expect(() => I.buildUiClick('darwin', 'x')).toThrow(/Windows/);
    expect(() => I.buildUiClick('win32', ' ')).toThrow();
  });
});
