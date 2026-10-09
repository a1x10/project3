// ИИ-помощник: решает, отвечать ли на сообщение, и формирует ответ с учётом ДЗ из дневника.
import { markdownToWhatsApp, normalize } from '../utils/text.js';
import { classifierPrompt, systemPrompt } from './prompts.js';

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

export class Assistant {
  constructor({ groq, homework, config, logger }) {
    this.groq = groq;
    this.homework = homework;
    this.config = config;
    this.logger = logger;
  }

  get enabled() {
    return this.config.ai.mode !== 'off' && Boolean(this.config.groq.apiKey);
  }

  // Решение «отвечать ли» для сообщений, где бота не звали явно (режим smart)
  async shouldRespond(text, recent = []) {
    const subjects = await this.homework.knownSubjects();
    if (!looksLikeStudyQuestion(text, subjects)) return { respond: false, reason: 'эвристика' };
    try {
      const transcript = recent.slice(-4).map((m) => `[${m.name}]: ${m.text}`).join('\n');
      const { text: raw } = await this.groq.chat({
        model: this.config.groq.fastModel,
        fallbacks: [this.config.groq.model],
        messages: [
          { role: 'system', content: classifierPrompt(subjects) },
          { role: 'user', content: `${transcript ? `Предыдущие сообщения:\n${transcript}\n\n` : ''}Последнее сообщение:\n${text}` },
        ],
        maxTokens: 400,
        temperature: 0,
        json: true,
        reasoningEffort: 'low',
      });
      const parsed = parseJson(raw);
      if (parsed && typeof parsed.respond === 'boolean') return { respond: parsed.respond, reason: parsed.reason || '' };
    } catch (error) {
      this.logger?.warn({ err: error.message }, 'Классификатор не сработал — решаю по эвристике');
    }
    return { respond: true, reason: 'эвристика (классификатор недоступен)' };
  }

  // Сформировать ответ. history — недавние сообщения чата [{name, text, fromBot}]
  async answer({ question, senderName, history = [], quoted = null, image = null }) {
    const context = await this.homework.aiContext();
    const system = systemPrompt({ botName: this.config.ai.botName, style: this.config.ai.style, context });

    const parts = [];
    const recent = history.slice(-this.config.ai.historySize);
    if (recent.length) {
      parts.push('Недавние сообщения в чате (для контекста):');
      for (const m of recent) parts.push(`[${m.fromBot ? this.config.ai.botName : m.name}]: ${m.text.slice(0, 600)}`);
      parts.push('');
    }
    if (quoted?.text) parts.push(`Пользователь отвечает на сообщение${quoted.name ? ` от ${quoted.name}` : ''}: «${quoted.text.slice(0, 1500)}»`, '');
    parts.push(`Вопрос от ${senderName || 'ученика'}:`, question || (image ? 'Помоги с заданием на фото.' : ''));
    const userText = parts.join('\n');

    let messages;
    let model = this.config.groq.model;
    let fallbacks = this.config.groq.fallbackModels;
    if (image) {
      model = this.config.groq.visionModel;
      fallbacks = [];
      const dataUrl = `data:${image.mimetype || 'image/jpeg'};base64,${image.buffer.toString('base64')}`;
      messages = [
        { role: 'system', content: system },
        { role: 'user', content: [{ type: 'text', text: userText }, { type: 'image_url', image_url: { url: dataUrl } }] },
      ];
    } else {
      messages = [{ role: 'system', content: system }, { role: 'user', content: userText }];
    }

    const result = await this.groq.chat({ model, fallbacks, messages, maxTokens: 3000, temperature: 0.3, reasoningEffort: 'medium' });
    this.logger?.debug({ model: result.model, usage: result.usage }, 'Ответ ИИ получен');
    return clipAnswer(markdownToWhatsApp(result.text), this.config.ai.maxAnswerChars);
  }

  async transcribe(buffer, mimetype) {
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
