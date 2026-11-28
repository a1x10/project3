// «Живое присутствие»: взгляд за курсором, реакции на касания, отлучки, инициатива.
const LINES = {
  stella: {
    head: ['Хи-хи, щекотно!', 'Эй, причёску помнёшь!', 'Мур… ещё разок?', 'Гладишь меня? Приятно ✨'],
    body: ['Ой! Ты чего?', 'Хе-хе, я тут!', 'Не тыкай, я стесняюсь!', 'Привет-привет!'],
    legs: ['Эй, это мои ноги!', 'Хочешь, станцую?', 'Щекотно же!'],
    back: ['С возвращением! Я скучала.', 'О, ты вернулся! Продолжим?', 'Ура, ты снова здесь!'],
    wake: ['Да? Слушаю!', 'Я здесь! Что сделать?', 'М? Говори!'],
    bored: ['Скучно… Может, поболтаем?', 'Эй, я тут, если что!', 'Хочешь, покажу новый танец?'],
  },
  mark: {
    head: ['Эй, полегче с причёской!', 'Ха, щекотно.', 'Ну ладно, ладно.'],
    body: ['Эй! Я тут.', 'Чего тыкаешь? Спроси что-нибудь!', 'На связи!'],
    legs: ['Это ноги, а не кнопки.', 'Хочешь, станцую?'],
    back: ['С возвращением! Я тут всё держал под контролем.', 'О, привет снова!', 'Вернулся? Отлично, продолжаем.'],
    wake: ['Да, слушаю.', 'На связи!', 'Говори.'],
    bored: ['Тихо как-то… Может, займёмся чем-нибудь?', 'Если что, я рядом.', 'Могу помочь разобрать файлы, кстати.'],
  },
};

export const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
export function linesFor(persona, kind) { return (LINES[persona] || LINES.stella)[kind] || []; }

export class Presence {
  constructor(ctx) {
    this.ctx = ctx;
    this.lastInteraction = Date.now();
    this.lastProactive = Date.now();
    this.away = false;
    this.nextIdleAction = Date.now() + 20000;
    this.touches = [];
  }

  start() {
    const { avatar } = this.ctx;
    avatar.on('touch', ({ part }) => this.onTouch(part));
    // взгляд за курсором (в т.ч. за пределами окна)
    this._cursorTimer = setInterval(async () => {
      if (!this.ctx.settings.lookAtCursor) { avatar.lookAt(0, 0); return; }
      try {
        const c = await window.stella.invoke('system:cursor');
        const stage = document.getElementById('avatar-layer').getBoundingClientRect();
        const cx = c.win.x + stage.left + stage.width / 2, cy = c.win.y + stage.top + stage.height * 0.2;
        avatar.lookAt((c.x - cx) / (window.screen.width * 0.5), (c.y - cy) / (window.screen.height * 0.5));
      } catch { /* */ }
    }, 90);
    this._idleTimer = setInterval(() => this.tick(), 5000);
  }

  userInteracted() { this.lastInteraction = Date.now(); this.lastProactive = Date.now(); }

  onTouch(part) {
    const { avatar, settings } = this.ctx;
    const now = Date.now();
    this.touches = this.touches.filter((t) => now - t < 4000).concat(now);
    if (this.touches.length >= 5) { this.touches = []; avatar.setEmotion('angry', 3); avatar.play('shake'); this.ctx.say(settings.persona === 'mark' ? 'Так, хватит меня тыкать!' : 'Ну всё, хватит! Я обиделась… почти.', {}); return; }
    if (part === 'head') { avatar.setEmotion(Math.random() < 0.5 ? 'shy' : 'happy', 4); avatar.play(Math.random() < 0.5 ? 'shy' : 'laugh'); }
    else if (part === 'legs') { avatar.setEmotion('surprised', 3); avatar.play('jump'); }
    else { avatar.setEmotion('surprised', 3); avatar.play('surprised'); }
    if (!this.ctx.speaker.busy && !this.ctx.chat.busy) this.ctx.say(pick(linesFor(settings.persona, part)), {});
    this.userInteracted();
  }

  onWake() {
    const { avatar, settings } = this.ctx;
    avatar.setEmotion('happy', 4);
    avatar.play('nod');
    // не говорим вслух: пока она говорит, микрофон не слушает — а человек хочет сразу сказать команду
    this.ctx.bubble?.(pick(linesFor(settings.persona, 'wake')) + ' 🎤');
  }

  async tick() {
    const { avatar, settings, speaker, chat } = this.ctx;
    if (document.body.classList.contains('companion')) return;
    let idleSec = 0;
    try { idleSec = await window.stella.invoke('system:idle'); } catch { /* */ }
    const busy = speaker.busy || chat.busy;
    // отлучка и возвращение
    const awayLimit = Math.max(3, settings.proactiveMinutes) * 60;
    if (!this.away && idleSec > awayLimit) { this.away = true; avatar.play('sleepy'); avatar.setEmotion('relaxed', 30); }
    else if (this.away && idleSec < 5) {
      this.away = false;
      if (settings.proactive && !busy) { avatar.setEmotion('happy', 5); avatar.play('wave'); this.ctx.say(pick(linesFor(settings.persona, 'back')), {}); }
    }
    if (this.away || busy) return;
    // спонтанные движения
    if (settings.idleAnimations && Date.now() > this.nextIdleAction && !avatar.currentAction) {
      const r = Math.random();
      avatar.play(r < 0.35 ? 'lookAround' : r < 0.6 ? 'stretch' : r < 0.8 ? 'nod' : 'dance', { duration: 5 });
      this.nextIdleAction = Date.now() + 25000 + Math.random() * 45000;
    }
    // инициатива: пользователь за компьютером, но давно не общался
    const quietMs = Date.now() - this.lastProactive;
    if (settings.proactive && idleSec < 60 && quietMs > settings.proactiveMinutes * 60000) {
      this.lastProactive = Date.now();
      let line = null;
      if (settings.hasOpenrouterKey) {
        try { line = await window.stella.invoke('llm:quick', 'Ты давно не общалась с пользователем, он сейчас за компьютером. Скажи одну короткую дружелюбную реплику (до 15 слов), чтобы завязать разговор: вопрос, забавный факт или предложение помочь. Начни с тега эмоции.'); } catch { /* */ }
      }
      this.ctx.say(line || pick(linesFor(settings.persona, 'bored')), { emotion: 'happy', action: 'wave' });
    }
  }
}
