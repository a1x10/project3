// Собирает renderer/icons.js из lucide-static (ISC). Запуск: node tools/build-icons.js
const fs = require('fs'), path = require('path');
const dir = path.join(__dirname, '..', 'node_modules', 'lucide-static', 'icons');
const NAMES = ['house','gamepad-2','scan-eye','cpu','brain-circuit','square-terminal','book-open','settings','life-buoy','drone','car','bot','cctv','power','camera','satellite-dish','code','square','search','usb','plug-zap','wifi','radar','play','circle-stop','plane-takeoff','plane-landing','house-plus','octagon-x','shield-check','shield-alert','key-round','download','folder-open','file-code-2','x','minus','copy','check','chevron-right','chevron-left','arrow-right','triangle-alert','info','circle-check','circle-x','thermometer','activity','gauge','battery-medium','mountain','compass','navigation','crosshair','video','circle-dot','image','bell','zap','plus','trash-2','refresh-cw','server','monitor','laptop','layers','sparkles','eye','move','hand','rotate-ccw','save','terminal','message-circle','send','user','phone','lock','globe','hard-drive','box','command','lightbulb','megaphone','grip','sliders-horizontal','map-pin','satellite','router','microchip','circuit-board','scan','target','orbit','cloud','link','unplug','external-link','list','loader','bolt','house','route','undo-2','arm', 'grab','person-standing'];
const out = {}; const miss = [];
for (const n of [...new Set(NAMES)]) {
  const f = path.join(dir, n + '.svg');
  if (!fs.existsSync(f)) { miss.push(n); continue; }
  const s = fs.readFileSync(f, 'utf8');
  out[n] = s.slice(s.indexOf('>', s.indexOf('<svg')) + 1, s.lastIndexOf('</svg>')).replace(/\s*\n\s*/g, '').trim();
}
const js = `// Иконки: Lucide (https://lucide.dev), лицензия ISC. Сгенерировано tools/build-icons.js\nconst P = ${JSON.stringify(out)};\nexport function icon(name, size = 18, cls = '') {\n  const p = P[name] || P.square;\n  return \`<svg class="i \${cls}" width="\${size}" height="\${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">\${p}</svg>\`;\n}\n`;
fs.writeFileSync(path.join(__dirname, '..', 'renderer', 'icons.js'), js);
console.log('icons:', Object.keys(out).length, 'missing:', miss.join(','));
