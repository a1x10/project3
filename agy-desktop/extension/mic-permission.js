navigator.mediaDevices.getUserMedia({ audio: true }).then(s => {
  s.getTracks().forEach(t => t.stop());
  document.getElementById('t').innerHTML = '<span class="ok">Готово!</span> Микрофон разрешён. Закройте эту вкладку и нажмите 🎤 в Стелле ещё раз.';
  setTimeout(() => window.close(), 2500);
}).catch(() => { document.getElementById('t').textContent = 'Доступ не разрешён. Разрешите микрофон для расширения в настройках Chrome (значок замка → Микрофон).'; });
