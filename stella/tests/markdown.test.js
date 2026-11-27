import { describe, it, expect } from 'vitest';
import { renderMarkdown, escapeHtml } from '../src/renderer/js/core/markdown.js';

describe('Безопасность (XSS)', () => {
  it('экранирует теги', () => expect(renderMarkdown('<script>alert(1)</script>')).not.toContain('<script>'));
  it('экранирует атрибуты событий', () => expect(renderMarkdown('<img src=x onerror=alert(1)>')).toContain('&lt;img'));
  it('javascript: ссылки не становятся ссылками', () => expect(renderMarkdown('[клик](javascript:alert(1))')).not.toContain('href="javascript'));
  it('кавычки в ссылке экранированы', () => expect(renderMarkdown('https://x.com/"onmouseover="a')).not.toMatch(/href="[^"]*"onmouseover/));
  it('код внутри блоков экранируется', () => expect(renderMarkdown('```\n<b>x</b>\n```')).toContain('&lt;b&gt;'));
  it('escapeHtml', () => expect(escapeHtml(`<>&"'`)).toBe('&lt;&gt;&amp;&quot;&#39;'));
});

describe('Разметка', () => {
  it('жирный и курсив', () => expect(renderMarkdown('**ж** и *к*')).toBe('<p><strong>ж</strong> и <em>к</em></p>'));
  it('инлайн-код', () => expect(renderMarkdown('команда `ls -la`')).toContain('<code>ls -la</code>'));
  it('звёздочки внутри кода не трогаются', () => expect(renderMarkdown('`a*b*c`')).toContain('<code>a*b*c</code>'));
  it('блок кода с языком и кнопкой копирования', () => {
    const h = renderMarkdown('```python\nprint(1)\n```');
    expect(h).toContain('<span>python</span>');
    expect(h).toContain('data-copy');
    expect(h).toContain('print(1)');
  });
  it('маркированный список', () => expect(renderMarkdown('- раз\n- два')).toBe('<ul><li>раз</li><li>два</li></ul>'));
  it('нумерованный список', () => expect(renderMarkdown('1. раз\n2) два')).toBe('<ol><li>раз</li><li>два</li></ol>'));
  it('заголовки', () => expect(renderMarkdown('## Итог')).toBe('<h4>Итог</h4>'));
  it('цитата', () => expect(renderMarkdown('> мудрость')).toBe('<blockquote>мудрость</blockquote>'));
  it('ссылка', () => expect(renderMarkdown('[OpenRouter](https://openrouter.ai)')).toContain('<a href="https://openrouter.ai" target="_blank" rel="noopener">OpenRouter</a>'));
  it('автоссылка', () => expect(renderMarkdown('см. https://example.com')).toContain('href="https://example.com"'));
  it('абзацы и переносы', () => expect(renderMarkdown('a\nb\n\nc')).toBe('<p>a<br>b</p><p>c</p>'));
  it('зачёркнутый', () => expect(renderMarkdown('~~нет~~')).toContain('<del>нет</del>'));
  it('незакрытый блок кода не ломает рендер', () => expect(() => renderMarkdown('```\ncode')).not.toThrow());
  it('пустой текст', () => expect(renderMarkdown('')).toBe(''));
});
