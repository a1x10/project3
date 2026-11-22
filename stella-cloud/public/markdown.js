// Tiny, safe markdown renderer (escapes HTML first)
(function () {
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function inline(s) {
    s = esc(s);
    const codes = [];
    s = s.replace(/`([^`\n]+)`/g, (_, c) => { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
    s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
         .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
         .replace(/~~([^~\n]+)~~/g, '<del>$1</del>')
         .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>')
         .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank">$2</a>');
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => '<code>' + codes[+i] + '</code>');
  }

  function render(md) {
    const lines = String(md || '').replace(/\r\n/g, '\n').split('\n');
    let out = '', i = 0, para = [];
    const flush = () => { if (para.length) { out += '<p>' + para.map(inline).join('<br>') + '</p>'; para = []; } };

    while (i < lines.length) {
      const l = lines[i];
      const fence = l.match(/^\s*```(\S*)/);
      if (fence) {
        flush();
        const buf = []; i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) buf.push(lines[i++]);
        i++;
        out += '<pre><button class="copy">copy</button><code data-lang="' + esc(fence[1]) + '">' + esc(buf.join('\n')) + '</code></pre>';
        continue;
      }
      const h = l.match(/^(#{1,6})\s+(.*)/);
      if (h) { flush(); const n = Math.min(h[1].length, 3); out += `<h${n}>${inline(h[2])}</h${n}>`; i++; continue; }
      if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(l)) { flush(); out += '<hr>'; i++; continue; }
      if (/^\s*>/.test(l)) {
        flush(); const buf = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''));
        out += '<blockquote>' + render(buf.join('\n')) + '</blockquote>'; continue;
      }
      if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) {
        flush();
        const ordered = /^\s*\d/.test(l);
        out += ordered ? '<ol>' : '<ul>';
        while (i < lines.length && /^\s*([-*+]|\d+[.)])\s+/.test(lines[i])) {
          out += '<li>' + inline(lines[i].replace(/^\s*([-*+]|\d+[.)])\s+/, '').replace(/^\[ \]\s/, '☐ ').replace(/^\[x\]\s/i, '☑ ')) + '</li>';
          i++;
        }
        out += ordered ? '</ol>' : '</ul>'; continue;
      }
      if (/^\s*\|.*\|\s*$/.test(l) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
        flush();
        const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
        out += '<table><tr>' + cells(l).map(c => '<th>' + c + '</th>').join('') + '</tr>';
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) out += '<tr>' + cells(lines[i++]).map(c => '<td>' + c + '</td>').join('') + '</tr>';
        out += '</table>'; continue;
      }
      if (!l.trim()) { flush(); i++; continue; }
      para.push(l); i++;
    }
    flush();
    return out;
  }

  window.renderMarkdown = render;
  window.escapeHtml = esc;
})();
