// ИИ-помощник: понимает сообщения чата (о чём, кому, что сделать) и отвечает с учётом ДЗ из дневника.
import { parseDayArg, WEEKDAYS, weekdayOf, toDMY } from '../utils/dates.js';
import { markdownToWhatsApp, normalize } from '../utils/text.js';
import { detectIntent } from '../whatsapp/intents.js';
import { draftPrompt, systemPrompt, understandPrompt } from './prompts.js';
import { AiRouter } from './router.js';

const QUESTION_WORDS = [
  'как', 'что', 'чё', 'че', 'чо', 'почему', 'зачем', 'сколько', 'какой', 'какая', 'какое', 'какие', 'каким', 'какую', 'где', 'когда', 'кто',
  'можно', 'помогите', 'помоги', 'помогите-ка', 'объясни', 'объясните', 'подскажите', 'подскажи', 'решите', 'реши', 'проверь', 'проверьте',
  'переведи', 'переведите', 'help',
  // казахский
  'қалай', 'неше', 'қандай', 'қайда', 'қашан', 'кім', 'көмектесіңдерші', 'көмектесші', 'түсіндірші',
];
const CONFUSION = /(не\s*(пойму|понимаю|понял|поняла|понятно|знаю|могу\s*решить|получается)|без понятия|туплю|хелп|sos|түсінбедім|түсінбей)/;
const TOPIC = new RegExp(
  [
    'дз', 'д з', 'домашк', 'домашн', 'задал', 'задани', 'задач', 'упражн', 'упр', 'номер', 'параграф', 'страниц', 'стр', 'учебник', 'тетрад',
    'реш', 'пример', 'уравнен', 'формул', 'правил', 'сочинени', 'эссе', 'доклад', 'презентац', 'проект', 'реферат', 'контрольн', 'сор', 'соч',
    'тест', 'выучить', 'наизусть', 'пересказ', 'перевод', 'перевест', 'слова', 'ответ', 'тема', 'урок', 'сдать', 'сдавать', 'срок', 'на завтра',
    'алгебр', 'геометр', 'математ', 'физик', 'хими', 'биолог', 'истори', 'географ', 'англ', 'русск', 'казах', 'литерат', 'информат',
    'тапсырма', 'үй жұмыс', 'есеп', 'жаттау', 'сабақ',
  ].map((w) => `(^|\\s)${w}`).join('|'),
);

// Быстрая эвристика без нейросети: похоже ли сообщение на вопрос по учёбе
export function looksLikeStudyQuestion(text, subjects = []) {
  const raw = String(text || '').trim();
  if (raw.length < 4 || raw.length > 4000) return false;
  const norm = normalize(raw);
  const first = norm.split(' ')[0];
  const isQuestion = raw.includes('?') || QUESTION_WORDS.includes(first) || CONFUSION.test(norm);
  if (!isQuestion) return false;
  if (TOPIC.test(norm) || /[№§]/.test(raw) || /\d+\s*[+\-*/×÷^=]\s*\d+/.test(raw)) return true;
  return subjects.some((subject) => {
    const word = normalize(subject).split(' ')[0];
    return word.length >= 4 && norm.includes(word.slice(0, Math.max(4, word.length - 2)));
  });
}

function parseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    const match = /\{[\s\S]*\}/.exec(text);
    if (!match) return null;
    try {
      return JSON.parse(match[0]);
    } catch {
      return null;
    }
  }
}

function clipAnswer(text, max) {
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  const lastBreak = Math.max(cut.lastIndexOf('\n'), cut.lastIndexOf('. '));
  return `${cut.slice(0, lastBreak > max * 0.6 ? lastBreak + 1 : max).trimEnd()}\n…`;
}

// Похоже ли сообщение на что-то про учёбу/ДЗ (не обязательно вопрос) — чтобы не тратить ИИ на болтовню
const STUDY_WORDS = /(^|\s)(дз|д з|домашк\S*|домашн\S*|задал\S*|задани\S*|задач\S*|урок\S*|расписан\S*|контрольн\S*|сор|соч|параграф\S*|упр\S*|номер\S*|стр|страниц\S*|тест\S*|экзамен\S*|учебник\S*|реш\S*|объясн\S*|помог\S*|пример\S*|сочинени\S*|эссе|доклад\S*|презентац\S*|проект\S*|выучить|наизусть|пересказ\S*|перевод\S*|тапсырма\S*|сабақ\S*|есеп\S*)(?=\s|$)/;
const THANKS = /(^|\s)(спасибо|спасиб|спс|сяб|благодарю|рахмет|рақмет|thanks|thx|ты лучш\S*|умниц\S*|красава|лучший бот|лучшая)(?=\s|$)/;

export function mentionsStudy(text, subjects = []) {
  const raw = String(text || '');
  const norm = normalize(raw);
  if (STUDY_WORDS.test(norm) || /[№§]/.test(raw) || /\d+\s*[+\-*/×÷^=]\s*\d+/.test(raw)) return true;
  return subjects.some((subject) => {
    const word = normalize(subject).split(' ')[0];
    return word.length >= 4 && norm.includes(word.slice(0, Math.max(4, word.length - 2)));
  });
}

export const isThanks = (text) => THANKS.test(normalize(text));

export const ACTIONS = ['send_homework', 'send_schedule', 'ask_task', 'answer', 'react', 'ignore'];

// Привести ответ модели к понятному виду (модели бывают небрежны)
export function normalizeDecision(raw, { isPrivate = false } = {}) {
  const d = raw && typeof raw === 'object' ? raw : {};
  const text = (v, max = 60) => (typeof v === 'string' && v.trim() && !/^(null|none|нет)$/i.test(v.trim()) ? v.trim().slice(0, max) : null);
  const action = ACTIONS.includes(d.action) ? d.action : 'ignore';
  let toBot = ['yes', 'no', 'unclear'].includes(d.to_bot) ? d.to_bot : 'unclear';
  if (isPrivate) toBot = 'yes';
  const confidence = Math.min(1, Math.max(0, Number(d.confidence ?? 0.6) || 0));
  return {
    action,
    toBot,
    aboutStudy: Boolean(d.about_study ?? action !== 'ignore'),
    day: text(d.day, 20),
    subject: text(d.subject, 40),
    task: text(d.task, 40),
    hasTaskText: Boolean(d.has_task_text),
    confidence,
    reason: text(d.reason, 200) || '',
  };
}

// Без нейросети: простые правила (если ИИ недоступен или кончился суточный лимит)
export function heuristicDecision(text, { subjects = [], explicit = false, today } = {}) {
  const intent = detectIntent(text, today);
  const base = { toBot: explicit ? 'yes' : 'unclear', day: null, subject: null, task: null, hasTaskText: false, confidence: 0.7, by: 'rules' };
  // аргумент просьбы: «15.10» — день, иначе — предмет
  const fromIntent = intent?.args ? (/^\d{2}\.\d{2}$/.test(intent.args) ? { day: intent.args } : { subject: intent.args }) : {};
  if (intent?.name === 'homework' || intent?.name === 'week') return { ...base, ...fromIntent, action: 'send_homework', aboutStudy: true, reason: 'просят ДЗ (правила)' };
  if (intent?.name === 'schedule') return { ...base, ...fromIntent, action: 'send_schedule', aboutStudy: true, reason: 'спрашивают расписание (правила)' };
  if (isThanks(text) && explicit) return { ...base, action: 'react', aboutStudy: false, reason: 'благодарят бота' };
  const numberOnly = /(№|номер|упр|задач|пример|стр)\.?\s*\d+/i.test(text) && !/[=+\-*/×÷]\s*\d/.test(text) && text.length < 90;
  if (looksLikeStudyQuestion(text, subjects) || explicit) {
    return { ...base, action: numberOnly ? 'ask_task' : 'answer', aboutStudy: true, task: numberOnly ? /(№|номер|упр|задач|пример|стр)\.?\s*\d+/i.exec(text)[0] : null, reason: 'похоже на вопрос по учёбе (правила)' };
  }
  return { ...base, action: 'ignore', aboutStudy: false, confidence: 0.6, reason: 'не про учёбу (правила)' };
}

// Ответ «скинь сюда весь пример» — живой и разный
const ASK_TASK = {
  exact: [
    'Скинь сюда сам пример{task} целиком — текстом или фоткой из учебника 📸 Разберу по шагам.',
    'Кинь условие{task} полностью (можно фото страницы) — помогу разобраться 🙌',
    'Давай сам текст задания{task} — учебника у меня под рукой нет. Фото тоже подойдёт, разберём вместе.',
    'Пришли пример{task} целиком, и я покажу, как решать 😉',
  ],
  humanities: [
    'Скинь сюда сам вопрос{task} полностью (или фото страницы) — помогу разобраться.',
    'Кинь текст задания{task} — подскажу, как ответить и что написать 🙌',
  ],
  generic: [
    'Скинь сюда задание{task} целиком — текстом или фото, помогу 🙌',
    'Пришли полный текст задания{task}, разберёмся вместе.',
  ],
};
const HUMANITIES = /(литерат|истори|русск|казах|қазақ|англ|язык|тіл|обществ|самопозн|географ|биолог)/i;
const EXACT = /(алгебр|геометр|математ|физик|хими|информат)/i;

export function askTaskText(decision, { random = Math.random } = {}) {
  const subject = decision.subject || '';
  const set = EXACT.test(subject) ? ASK_TASK.exact : HUMANITIES.test(subject) ? ASK_TASK.humanities : decision.task && /\d/.test(decision.task) ? ASK_TASK.exact : ASK_TASK.generic;
  const template = set[Math.floor(random() * set.length) % set.length];
  const task = decision.task ? ` ${decision.task.replace(/^номер\s*/i, '№')}` : '';
  return template.replace('{task}', task);
}

// День из ответа модели → аргумент для команд (!дз завтра, !расписание пт, !дз 20.10)
export function dayArg(day, todayIso) {
  if (!day) return '';
  const value = { today: 'сегодня', tomorrow: 'завтра' }[String(day).toLowerCase()] || String(day);
  const iso = parseDayArg(value, todayIso);
  return iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}` : '';
}

export class Assistant {
  // ai — AiRouter (несколько провайдеров); groq — клиент Groq (нужен для голосовых: Whisper)
  constructor({ ai = null, groq = null, homework, config, logger, backup = null }) {
    this.groq = groq;
    this.ai = ai || new AiRouter({ config, clients: groq ? { groq } : {}, backup, logger });
    this.homework = homework;
    this.config = config;
    this.logger = logger;
    this.backup = backup;
  }

  get lastProvider() {
    return this.ai.last?.chat?.provider || null;
  }

  get hasProvider() {
    return this.ai.anyKey;
  }

  get enabled() {
    return this.config.ai.mode !== 'off' && this.hasProvider;
  }

  // Совместимость: запрос «ответа» через роутер
  async complete(params, role = 'chat') {
    return this.ai.chat(role, params);
  }

  /**
   * Понять сообщение: что сделать (action), обращено ли к боту (toBot), к какому дню и предмету.
   * recent — последние сообщения чата [{name, text, fromBot}].
   */
  async understand({ text, recent = [], explicit = false, isPrivate = false, quoted = null, hasImage = false, senderName = '' }) {
    const subjects = await this.homework.knownSubjects();
    const today = this.homework.today();
    const started = Date.now();
    try {
      const transcript = recent.slice(-6).map((m) => `[${m.fromBot ? this.config.ai.botName : m.name || 'Ученик'}]: ${String(m.text).slice(0, 300)}`).join('\n');
      const lines = [];
      if (transcript) lines.push(`Предыдущие сообщения:\n${transcript}`, '');
      if (quoted?.text) lines.push(`Это ответ на сообщение${quoted.fromBot ? ' бота' : ''}: «${quoted.text.slice(0, 300)}»`, '');
      if (explicit) lines.push('(К боту обратились явно: по имени, @упоминанием или ответом на его сообщение.)');
      if (hasImage) lines.push('(К сообщению приложено фото.)');
      lines.push(`Последнее сообщение от ${senderName || 'ученика'}:\n${text}`);
      const { text: raw, model, provider } = await this.ai.chat('understand', {
        messages: [
          { role: 'system', content: understandPrompt({ botName: this.config.ai.botName, wakeWords: this.config.ai.wakeWords, subjects, today: `${WEEKDAYS[weekdayOf(today) - 1]}, ${toDMY(today)}`, isPrivate }) },
          { role: 'user', content: lines.join('\n') },
        ],
        maxTokens: 400,
        temperature: 0,
        json: true,
        reasoningEffort: 'low',
      });
      const parsed = parseJson(raw);
      if (!parsed) throw new Error('модель ответила не JSON');
      const decision = normalizeDecision(parsed, { isPrivate });
      return { ...decision, by: 'ai', provider, model, ms: Date.now() - started };
    } catch (error) {
      this.logger?.warn({ err: error.message }, 'Понимание через ИИ не сработало — решаю по правилам');
      return { ...heuristicDecision(text, { subjects, explicit: explicit || isPrivate, today }), error: error.message, ms: Date.now() - started };
    }
  }

  // Старый интерфейс «отвечать ли» (для совместимости)
  async shouldRespond(text, recent = []) {
    const subjects = await this.homework.knownSubjects();
    if (!looksLikeStudyQuestion(text, subjects)) return { respond: false, reason: 'эвристика' };
    const decision = await this.understand({ text, recent });
    return { respond: decision.action !== 'ignore' && decision.toBot !== 'no', reason: decision.reason };
  }

  // Сформировать ответ. history — недавние сообщения чата [{name, text, fromBot}].
  // В личке история идёт настоящим диалогом (user/assistant), в группе — как стенограмма чата.
  async answer({ question, senderName, history = [], quoted = null, image = null, isPrivate = false, persona = null }) {
    const context = await this.homework.aiContext();
    const { botName, style, humanLike } = this.config.ai;
    const system = systemPrompt({ botName, style, context, humanLike, isPrivate, senderName, persona: persona || this.config.ai.persona });
    const recent = history.slice(-this.config.ai.historySize);

    const parts = [];
    const dialog = [];
    if (isPrivate) {
      for (const m of recent) dialog.push({ role: m.fromBot ? 'assistant' : 'user', content: m.text.slice(0, 1500) });
    } else if (recent.length) {
      parts.push('Недавние сообщения в чате (для контекста):');
      for (const m of recent) parts.push(`[${m.fromBot ? botName : m.name}]: ${m.text.slice(0, 600)}`);
      parts.push('');
    }
    if (quoted?.text) parts.push(`Пользователь отвечает на сообщение${quoted.name ? ` от ${quoted.name}` : ''}: «${quoted.text.slice(0, 1500)}»`, '');
    if (isPrivate) parts.push(question || (image ? 'Помоги с заданием на фото.' : ''));
    else parts.push(`Вопрос от ${senderName || 'ученика'}:`, question || (image ? 'Помоги с заданием на фото.' : ''));
    const userText = parts.join('\n');

    let userMessage = { role: 'user', content: userText };
    if (image) {
      const dataUrl = `data:${image.mimetype || 'image/jpeg'};base64,${image.buffer.toString('base64')}`;
      userMessage = { role: 'user', content: [{ type: 'text', text: userText }, { type: 'image_url', image_url: { url: dataUrl } }] };
    }
    const messages = [{ role: 'system', content: system }, ...dialog, userMessage];
    const temperature = this.config.ai.temperature ?? (humanLike ? 0.5 : 0.3);
    const result = await this.ai.chat(image ? 'vision' : 'chat', { messages, maxTokens: 3000, temperature, reasoningEffort: 'medium' });
    this.logger?.debug({ model: result.model, provider: result.provider, usage: result.usage }, 'Ответ ИИ получен');
    return clipAnswer(markdownToWhatsApp(result.text), this.config.ai.maxAnswerChars);
  }

  // Черновик сообщения в группу «о чём-то» — для панели
  async draft(about) {
    const context = await this.homework.aiContext().catch(() => '');
    const result = await this.ai.chat('chat', {
      messages: [
        { role: 'system', content: draftPrompt({ botName: this.config.ai.botName, persona: this.config.ai.persona, context }) },
        { role: 'user', content: String(about).slice(0, 1000) },
      ],
      maxTokens: 800,
      temperature: 0.7,
      reasoningEffort: 'low',
    });
    return markdownToWhatsApp(result.text).slice(0, 3000);
  }

  async transcribe(buffer, mimetype) {
    if (!this.groq || this.groq.hasKey === false) throw new Error('для голосовых нужен ключ Groq (Whisper)');
    const subjects = await this.homework.knownSubjects();
    const ext = /mp4|m4a|aac/.test(mimetype || '') ? 'm4a' : /mpeg|mp3/.test(mimetype || '') ? 'mp3' : 'ogg';
    return this.groq.transcribe(buffer, {
      model: this.config.groq.whisperModel,
      filename: `voice.${ext}`,
      mimetype: mimetype || 'audio/ogg',
      prompt: `Школьник спрашивает про домашнее задание. Предметы: ${subjects.join(', ')}.`,
    });
  }
}
