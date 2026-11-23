// Stella: voice input for the side panel — Russian, Kazakh, English (Web Speech API).
(() => {
  const input = document.getElementById('promptInput');
  const mic = document.getElementById('micBtn');
  const langBtn = document.getElementById('voiceLangBtn');
  const send = document.getElementById('sendBtn');
  if (!input || !mic) return;
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) { mic.style.display = 'none'; if (langBtn) langBtn.style.display = 'none'; return; }
  const LANGS = [['RU', 'ru-RU'], ['KZ', 'kk-KZ'], ['EN', 'en-US']];
  let idx = 0; try { idx = Math.max(0, LANGS.findIndex(l => l[0] === localStorage.getItem('stellaVoiceLang'))); } catch {}
  const paint = () => { if (langBtn) langBtn.textContent = LANGS[idx][0]; };
  paint();
  if (langBtn) langBtn.addEventListener('click', () => { idx = (idx + 1) % LANGS.length; try { localStorage.setItem('stellaVoiceLang', LANGS[idx][0]); } catch {} paint(); });
  let rec = null;
  mic.addEventListener('click', () => {
    if (rec) { rec.stop(); return; }
    rec = new SR(); rec.lang = LANGS[idx][1]; rec.interimResults = true; rec.continuous = false;
    const base = input.value ? input.value.trimEnd() + ' ' : '';
    rec.onresult = e => { let t = ''; for (const r of e.results) t += r[0].transcript; input.value = base + t; input.dispatchEvent(new Event('input', { bubbles: true })); };
    rec.onend = () => { rec = null; mic.classList.remove('rec'); if (input.value.trim() && send && !send.classList.contains('is-running')) send.click(); };
    rec.onerror = e => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        // the side panel cannot show the permission prompt — ask once in a normal tab
        chrome.tabs.create({ url: chrome.runtime.getURL('mic-permission.html') });
      }
    };
    mic.classList.add('rec');
    try { rec.start(); } catch { rec = null; mic.classList.remove('rec'); }
  });
})();
