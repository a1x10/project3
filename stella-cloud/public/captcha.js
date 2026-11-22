// Captcha page for Stella on the PC: the token is handed back to the app via the window title.
fetch('/api/info').then(r => r.json()).then(info => {
  if (!info.turnstile) { document.title = 'STELLA_CAPTCHA:none'; return; }
  const sc = document.createElement('script');
  sc.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit';
  sc.onload = () => turnstile.render('#box', { sitekey: info.turnstile, language: 'ru', callback: t => { document.title = 'STELLA_CAPTCHA:' + t; } });
  document.head.appendChild(sc);
});
