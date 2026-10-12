// Сборка бота целиком для тестов: фейковые дневник, WhatsApp и нейросеть.
import { Assistant } from '../src/ai/assistant.js';
import { BotCore } from '../src/core.js';
import { HomeworkService } from '../src/homework/service.js';
import { Inbox } from '../src/inbox.js';
import { Scheduler } from '../src/scheduler.js';
import { Settings } from '../src/settings.js';
import { Commands } from '../src/whatsapp/commands.js';
import { MessageHandler } from '../src/whatsapp/handler.js';
import { FakeBilimClient, FakeWA, memoryStore, rawWeek, testConfig, TUESDAY_10AM } from './helpers.js';

export const GROUP = '120363000000000001@g.us';
export const OTHER_GROUP = '120363000000000999@g.us';
export const ADMIN = '77015556677@s.whatsapp.net';
export const STUDENT = '77011112233@s.whatsapp.net';

export const WEEKS = {
  '2025-10-13': rawWeek('2025-10-13', {
    1: [['Алгебра', '№ 1']],
    2: [['Физика', '§ 12']],
    3: [['Алгебра', '№ 250'], ['Русский язык', 'Упр. 5']],
    4: [['История', null]],
    5: [['Литература', 'Читать стр. 40-55']],
  }),
  '2025-10-20': rawWeek('2025-10-20', { 1: [['Алгебра', '№ 300']] }),
};

// Фейковая нейросеть: запоминает запросы, отвечает заданным текстом
export class FakeGroq {
  constructor() {
    this.calls = [];
    this.classifierAnswer = '{"respond": true, "reason": "вопрос по ДЗ"}';
    this.fail = null;
  }

  async chat(req) {
    this.calls.push(req);
    if (this.fail) throw this.fail;
    if (req.json) return { text: this.classifierAnswer, model: req.model };
    return { text: '**Ответ:** реши уравнение по шагам', model: req.model };
  }

  async transcribe() {
    return 'что задали по физике';
  }
}

export function setup(env = {}, { withInbox = false } = {}) {
  // по умолчанию в тестах — текстовый режим (проверять содержимое проще); фото проверяются отдельно
  const config = testConfig({ ADMIN_NUMBERS: '77015556677', WA_GROUP_IDS: GROUP, HOMEWORK_AS_IMAGE: 'false', ...env });
  const store = memoryStore();
  const wa = new FakeWA();
  wa.groups[GROUP] = { id: GROUP, subject: '7А класс', participants: [{ id: STUDENT }, { id: ADMIN, admin: 'admin' }] };
  wa.groups[OTHER_GROUP] = { id: OTHER_GROUP, subject: 'Футбол', participants: [{ id: STUDENT }] };
  const client = new FakeBilimClient(structuredClone(WEEKS)); // копия: тесты меняют дневник
  const homework = new HomeworkService({ client, store, config, now: TUESDAY_10AM });
  homework.today = () => '2025-10-14';
  const groq = new FakeGroq();
  const warnings = [];
  const logger = { info() {}, warn(...args) { warnings.push(args); }, error() {}, debug() {}, child() { return this; } };
  const settings = new Settings({ config, file: null, logger });
  const core = new BotCore({ config, store, wa, logger });
  core.today = () => '2025-10-14';
  const assistant = new Assistant({ groq, homework, config, logger });
  core.assistant = assistant;
  const scheduler = new Scheduler({ config, store, homework, wa, core, logger, settings });
  const commands = new Commands({ core, homework, wa, scheduler, config, logger, settings });
  const inbox = withInbox ? new Inbox({ file: null, logger }) : null;
  if (inbox) wa.on('sent', () => {}); // FakeWA не шлёт событий — исходящие пишем вручную в тестах
  const handler = new MessageHandler({ config, core, wa, homework, assistant, commands, logger, inbox });
  handler.sleep = async () => {}; // «печатает…» в тестах без пауз
  return { config, store, wa, client, homework, groq, core, assistant, scheduler, commands, handler, warnings, settings, logger, inbox };
}
