// Проверка настроек перед запуском: npm run check
// Входит в BilimClass, показывает ДЗ на ближайший день и проверяет ключ Groq. В WhatsApp ничего не отправляет.
import path from 'node:path';
import { GroqClient } from '../src/ai/groq.js';
import { BilimClassClient } from '../src/bilimclass/client.js';
import { loadConfig } from '../src/config.js';
import { formatDay, formatWeek } from '../src/homework/format.js';
import { HomeworkService } from '../src/homework/service.js';
import { Store } from '../src/store.js';
import { formatClock, mondayOf, toDMY } from '../src/utils/dates.js';
import { DiaryScreenshotter } from '../src/bilimclass/screenshot.js';
import fs from 'node:fs';

const ok = (s) => console.log(`✅ ${s}`);
const bad = (s) => console.log(`❌ ${s}`);
const info = (s) => console.log(`   ${s}`);

const config = loadConfig();
let failed = false;

console.log('\n— BilimClass —');
const store = new Store(path.join(config.dataDir, 'check-state.json')); // отдельный файл: проверка не трогает рабочее состояние
const client = new BilimClassClient({ ...config.bilim });
const homework = new HomeworkService({ client, store, config });
try {
  const session = await client.login();
  ok(`Вход выполнен: ${session.fullName || 'ученик'}, класс ${session.className || '?'}, ${session.schoolName || ''}`);
  info(`schoolId=${session.schoolId} groupId=${session.groupId} учебный год=${session.eduYear}`);
  const today = homework.today();
  const end = await homework.lessonsEnd(today, { fresh: true });
  if (config.schedule.digestMode === 'after_lessons') {
    info(end != null
      ? `Сегодня уроки до ${formatClock(end)} → рассылка новых ДЗ в ${formatClock(Math.min(end + config.schedule.digestDelayMinutes, 1439))}`
      : `Сегодня уроков нет → рассылка (если завтра учебный день) в ${formatClock(config.schedule.digestTime)}`);
  }
  const next = await homework.nextSchoolDay(today);
  if (next) {
    ok(`Ближайший учебный день: ${toDMY(next)}`);
    console.log(`\n${formatDay(await homework.dayView(next), today)}\n`);
  } else {
    bad('В ближайшие 3 недели нет уроков в дневнике (каникулы?)');
  }
  console.log(formatWeek(await homework.weekView(mondayOf(today)), today));

  if (config.features.homeworkPhoto === 'screenshot' && next) {
    console.log('\n— Скриншот дневника —');
    const shooter = new DiaryScreenshotter({ config, eduYear: () => session.eduYear });
    if (!shooter.available) {
      bad('Chromium не найден: установите chromium или задайте CHROMIUM_PATH (иначе будут нарисованные карточки)');
    } else {
      const view = await homework.dayView(next);
      if (!view.entries.length) {
        info('На ближайший день ДЗ нет — скриншот проверю, когда задания появятся');
      } else {
        try {
          const shots = await shooter.captureDays([{ date: next, subjects: [...new Set(view.entries.map((e) => e.subject))] }]);
          if (!shots.size) throw new Error('страница дня не совпала с данными дневника');
          const file = path.join(config.dataDir, 'screenshot-check.jpg');
          fs.mkdirSync(config.dataDir, { recursive: true });
          fs.writeFileSync(file, shots.get(next));
          ok(`Скриншот готов: ${file} — откройте и проверьте`);
        } catch (error) {
          failed = true;
          bad(`Скриншот не получился: ${error.message}. Бот будет отправлять нарисованные карточки`);
        }
      }
    }
  }
  console.log(
    '\n   Проверьте: ДЗ показано на тот день, к которому его нужно сделать?\n' +
      '   Если задания стоят на уроке, где их задали, а не на дне сдачи — поставьте HOMEWORK_ATTACHED_TO=assigned',
  );
} catch (error) {
  failed = true;
  bad(error.message);
}

console.log('\n— Groq (ИИ) —');
if (!config.groq.apiKey) {
  bad('GROQ_API_KEY не задан — ИИ-ответы будут выключены. Получить ключ: https://console.groq.com/keys');
} else {
  const groq = new GroqClient(config.groq);
  try {
    const { text, model } = await groq.chat({
      model: config.groq.model,
      fallbacks: config.groq.fallbackModels,
      messages: [{ role: 'user', content: 'Сколько будет 7×8? Ответь одним числом.' }],
      maxTokens: 300,
      reasoningEffort: 'low',
    });
    ok(`Groq отвечает (${model}): ${text.slice(0, 60)}`);
  } catch (error) {
    failed = true;
    bad(`Groq: ${error.message}`);
  }
}

console.log('\n— WhatsApp —');
info(config.whatsapp.pairingNumber ? `Привязка по коду для номера ${config.whatsapp.pairingNumber}` : 'Привязка по QR-коду (код появится в логах при npm start)');
info(config.whatsapp.admins.length ? `Админы: ${config.whatsapp.admins.join(', ')}` : 'ADMIN_NUMBERS не задан');
console.log(failed ? '\nЕсть ошибки — исправьте .env и запустите проверку снова.\n' : '\nВсё готово! Запускайте: npm start\n');
process.exit(failed ? 1 : 0);
