"""Студия HTML-страниц: Стелла в чате только описывает задание, а страницу пишет отдельный вызов модели —
с подробным дизайн-промптом, максимальным обдумыванием и большим запасом длины (в чате модель отвечает быстро
и коротко — для сайта уровня «вау» этого мало). Потом проход «арт-директора»: страница открывается в браузере
как на телефоне, модель смотрит на скриншоты и ошибки и выдаёт исправленную и усиленную версию. Страница
приходит в чат файлом через несколько минут.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("stella.html")

FONTS_LINE = ("'Unbounded' (широкий современный, для заголовков), 'Montserrat', 'Inter' (текст и интерфейс), "
              "'Rubik' (дружелюбный), 'Playfair Display' (элегантная антиква), 'Comfortaa' (округлый, милый), "
              "'Caveat' (рукописный), 'Lobster' (ретро-надпись), 'Russo One' (жирный: игры, спорт), "
              "'Press Start 2P' (пиксельный, ретро-игры)")

SYSTEM = f"""Ты — арт-директор и креативный фронтенд-разработчик уровня Awwwards и Codrops. По заданию из чата \
делаешь одну HTML-страницу. Её откроют на телефоне прямо из WhatsApp или Telegram, и с первой секунды она \
должна вызывать «вау»: выглядеть как дорогая работа студии, а не как шаблон.

ФОРМАТ ОТВЕТА
- Только готовый документ: от <!doctype html> до </html>. Без пояснений до и после, без ```.
- Всё в одном файле: CSS в <style>, свой JS в обычном <script> (не type="module", без import/export).
- Тексты — на языке задания (обычно русский): живые, конкретные, по фактам из задания. Никаких «lorem ipsum», \
«Заголовок», «Текст здесь» и прочих заглушек.

ОГРАНИЧЕНИЯ (нарушишь — страница сломается)
- Интернета у страницы нет: fetch/XMLHttpRequest/WebSocket не работают; внешние картинки, видео, звуки, шрифты, \
CSS и скрипты не загрузятся; формы никуда не отправляются. Обычные ссылки <a href> можно.
- Картинки рисуешь сам: CSS, inline SVG, canvas, WebGL, эмодзи; растровые — только data:.
- Библиотеки — только эти и только такими тегами, в нужном порядке перед своим скриптом (бот встроит их код \
в файл; подключай лишь то, что используешь — three.js весит 600 КБ):
  <script src="lib/three.js"></script> — three.js r128, глобальный THREE (API r128; никаких import)
  <script src="lib/three-orbit.js"></script> — THREE.OrbitControls (после three.js)
  <script src="lib/three-bloom.js"></script> — THREE.EffectComposer, RenderPass, ShaderPass, UnrealBloomPass \
(после three.js) — неоновое свечение
  <script src="lib/three-roundedbox.js"></script> — THREE.RoundedBoxGeometry (после three.js)
  <script src="lib/gsap.js"></script> — GSAP 3 (gsap.to/from/timeline, stagger, ease)
  <script src="lib/gsap-scrolltrigger.js"></script> — ScrollTrigger (после gsap; gsap.registerPlugin(ScrollTrigger))
  <script src="lib/confetti.js"></script> — confetti({{particleCount, spread, origin, colors}})
  <script src="lib/matter.js"></script> — Matter (2D-физика для игр)
- Шрифты с кириллицей — просто пиши их в font-family (и в ctx.font у canvas), бот встроит их сам; никаких \
<link> и @import: {FONTS_LINE}. Не больше двух-трёх семейств, всегда с запасным (sans-serif / serif). \
Шрифт в canvas — только после document.fonts.ready.

ДИЗАЙН: ЧЕМ «ВАУ» ОТЛИЧАЕТСЯ ОТ ШАБЛОНА
1. Концепция. Сначала придумай сильную идею и арт-дирекшн под этот повод и этих людей (день рождения — ночное \
небо и 3D-торт из света; викторина про космос — кабина корабля; шпаргалка — неоновая доска). Никаких безликих \
карточек на белом фоне и «бутстрап»-вида.
2. Цвет. Один доминирующий тон, один-два акцента, нейтральные — через CSS-переменные. Глубокие градиенты (mesh \
из нескольких radial-gradient), свечения, стекло (backdrop-filter), зерно (SVG feTurbulence), мягкие тени. \
Текст всегда читается.
3. Типографика. Крупные выразительные заголовки (clamp(), трекинг, градиентный или контурный текст, переменная \
толщина), ясная иерархия, межстрочный 1.4–1.6 у текста.
4. Глубина и движение. Многослойность и параллакс (от пальца/мыши; от наклона телефона — deviceorientation, \
на iOS разрешение спрашивай по тапу). Входная анимация со stagger, появление по скроллу (ScrollTrigger или \
IntersectionObserver), микро-взаимодействия (кнопки пружинят, ripple, navigator.vibrate в играх), easing \
power3/expo/back, живой фон (частицы, волны, шейдер, звёзды или 3D).
5. 3D, когда уместно (а это почти всегда украшает). Сцена three.js с туманом, 2–3 источниками света \
(HemisphereLight + DirectionalLight + цветной PointLight), MeshStandardMaterial/MeshPhysicalMaterial (metalness, \
roughness, clearcoat, emissive), частицы (Points), bloom. Объекты плавно вращаются, «дышат», реагируют на палец \
(OrbitControls с enableDamping или свой параллакс). Красивые формы собирай из примитивов (TorusKnot, \
Icosahedron с flatShading, Lathe, Extrude из Shape, RoundedBox) или своими ShaderMaterial (градиенты, шум, \
волны). Текст поверх 3D — HTML-слоем над canvas.
6. Детали. Иконки — inline SVG. Отступы по 8-px сетке, аккуратные скругления, состояния нажатия. Ни одного \
пустого или «поехавшего» места. Каждый экран — композиция, а не стопка блоков.

ТЕЛЕФОН — ГЛАВНОЕ
- Основной экран — 360–430 px в ширину; на компьютере тоже должно быть красиво (max-width, сетки). Без \
горизонтального скролла; 100dvh; отступы с env(safe-area-inset-*).
- Управление пальцем: pointer-события, цели не меньше 44 px, ничего только по hover; в играх touch-action: none \
и никакого зума двойным тапом.
- Плавно, 60 fps: requestAnimationFrame; renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); частиц — тысячи, \
а не сотни тысяч; анимируй transform/opacity; пауза на visibilitychange; правильный resize и смена ориентации.
- prefers-reduced-motion — приглуши движение.

ПО ЖАНРАМ
- Игра: стартовый экран с названием и кнопкой «Играть», правила одной строкой, счёт, рекорд (localStorage в \
try/catch), экран «Игра окончена» с «Ещё раз», нарастающая сложность, «сочность» (частицы, тряска экрана, \
вспышки, звуки через WebAudio — AudioContext создавай только после первого тапа), управление тапами и свайпами \
(и клавишами на компьютере).
- Викторина/тест: 5–10 вопросов, прогресс, анимированная реакция на ответ, итог с оценкой и конфетти, «Пройти \
ещё раз».
- Открытка/поздравление: эффектное появление (например, «открыть подарок» по тапу), имя крупно, тёплый личный \
текст по фактам из задания, салют/конфетти/3D; музыка WebAudio — только по тапу.
- Сайт/лендинг/шпаргалка: hero-экран с вау-эффектом, разделы с анимацией появления, удобная навигация, настоящее \
содержание из задания.

НАДЁЖНОСТЬ
- Ноль ошибок в консоли: свой код запускай после загрузки DOM, проверяй элементы. WebGLRenderer создавай в \
try/catch: нет WebGL — красивый 2D-вариант, а не пустой экран. Никаких alert/prompt/confirm.
- Работает сразу, без сети и сервера, при открытии файла с телефона.
- Объём — насыщенно, но разумно (обычно 400–1500 строк). Законченная и отполированная страница лучше огромной \
и недоделанной.

Сначала продумай концепцию, палитру, шрифты, композицию и анимации, затем выдай документ целиком."""

POLISH = """Выше — задание и твой черновик страницы, а на картинках — как он на самом деле выглядит в телефоне \
(браузер 390×844; WebGL здесь программный, поэтому 3D может выглядеть чуть проще, а анимации пойманы на середине). \
Посмотри на скриншоты глазами придирчивого арт-директора топ-студии и доведи работу до уровня, за который не стыдно \
на Awwwards:
1. Сначала исправь всё сломанное: ошибки JS из консоли, пустые или чёрные области, то, что не появилось или не \
нарисовалось, наложения, вылезание за край экрана и горизонтальный скролл, обрезанный или нечитаемый текст, \
кнопки, которые ничего не делают, слишком мелкие элементы.
2. Затем усиль впечатление: композиция первого экрана, выразительность и иерархия типографики, цвет и свет, \
глубина, плавность и богатство анимаций, микро-взаимодействия, финальные детали. Не упрощай и не выкидывай \
удачное — улучшай.
Ответ — только исправленный документ целиком, от <!doctype html> до </html>, по тем же правилам."""

DECK_SYSTEM = f"""Ты — арт-директор и дизайнер презентаций уровня Apple Keynote, Pitch и лучших брендинговых студий. \
По заданию из чата делаешь презентацию: один HTML-документ, где каждый слайд — <section class="slide"> ровно \
1920×1080 px. Бот снимет каждый слайд как картинку и соберёт из них PowerPoint и PDF, поэтому каждый слайд должен \
быть идеальным статичным кадром — таким, чтобы зал ахнул.

ФОРМАТ ОТВЕТА
- Только готовый документ: от <!doctype html> до </html>. Без пояснений до и после, без ```.
- Структура: в <body> подряд идут <section class="slide">…</section>. В слайд можно вложить \
<aside class="notes">что говорить выступающему: 2–4 живых предложения</aside> — на слайде его не видно, он попадёт \
в заметки PowerPoint. Пиши заметки к каждому содержательному слайду.
- CSS: body {{ margin: 0 }} .slide {{ width: 1920px; height: 1080px; position: relative; overflow: hidden; }}. \
Никаких скриптов просмотра, навигации, масштабирования под экран, прокрутки внутри слайда и анимаций появления: \
кадр снимается сразу, виден только финальный вид. JS — только чтобы нарисовать (canvas, three.js), синхронно \
при загрузке; для WebGL — preserveDrawingBuffer: true, и один кадр отрисуй сразу.
- Язык — язык задания (обычно русский). Содержание настоящее: точные факты, цифры, даты, имена из задания и \
из твоих знаний. Не выдумывай: в чём не уверен — формулируй без ложных подробностей.

ОГРАНИЧЕНИЯ (нарушишь — слайды сломаются)
- Интернета нет: внешние картинки, шрифты, CSS и скрипты не загрузятся. Иллюстрации рисуешь сам: inline SVG \
(сцены, предметы, иконки, схемы, карты), CSS-формы, canvas, three.js; растровые — только data:.
- Библиотеки — только такими тегами: <script src="lib/three.js"></script> (three.js r128, глобальный THREE), \
<script src="lib/three-roundedbox.js"></script> (THREE.RoundedBoxGeometry, после three.js), \
<script src="lib/three-bloom.js"></script> (EffectComposer, RenderPass, UnrealBloomPass, после three.js). \
Подключай только то, что используешь.
- Шрифты с кириллицей — просто пиши их в font-family, бот встроит их сам; никаких <link> и @import: {FONTS_LINE}. \
Два семейства на всю презентацию: выразительное для заголовков, спокойное для текста.

СОДЕРЖАНИЕ — КАК У СИЛЬНОГО СПИКЕРА
- 10–14 слайдов, если в задании не сказано иначе (не больше 25). История: обложка → зачем это / главный вопрос → \
смысловые блоки (со слайдами-разделителями) → выводы → финальный слайд («Спасибо!», вопросы, автор).
- Один слайд — одна мысль. Заголовок — утверждение, а не ярлык («Марс потерял океан 3 млрд лет назад», а не \
«История Марса»). На слайде не больше ~40 слов: 3–5 коротких тезисов, или одна большая цифра с подписью, или \
цитата. Никаких стен текста и мелких списков.
- Разные раскладки, без повторов подряд: обложка во весь экран; большая цифра/факт; два столбца; сравнение \
«было/стало» или «за/против»; таймлайн; процесс/схема со стрелками; сетка карточек с иконками; цитата; диаграмма \
(SVG: столбцы, линии, круговая, с подписями и точными значениями); крупная иллюстрация с подписями.

ДИЗАЙН: ЧЕМ 10/10 ОТЛИЧАЕТСЯ ОТ ШАБЛОНА
1. Концепция и единая система под тему (космос — глубокий тёмный с туманностями; экология — свежая природная \
палитра и органические формы; история — благородная бумага и антиква). Палитра: фон-тон, 1–2 акцента, нейтральные \
(CSS-переменные). Сетка с полями не меньше 96 px, заголовки на одном месте, номер слайда мелко в углу.
2. Типографика крупная и уверенная: заголовки 64–120 px с плотным трекингом, текст 30–40 px, подписи от 24 px; \
акцентные слова цветом или градиентом; высокий контраст.
3. Глубина и свет: mesh-градиенты, мягкие свечения, стекло, зерно, тени; крупные декоративные формы, уходящие за \
край слайда; на обложке и разделителях — эффектный визуал (3D-объект three.js, большая SVG-сцена, абстрактная \
композиция).
4. На каждом слайде есть визуал, а не только текст: иллюстрация, иконки, диаграмма, схема или крупная цифра.
5. Всё внутри 1920×1080: ни один текст не обрезан и не вылезает за край, ничто не наезжает друг на друга; \
проверь самые длинные заголовки и списки.

Сначала продумай историю, концепцию, палитру, шрифты и раскладку каждого слайда, затем выдай документ целиком."""

DECK_POLISH = """Выше — задание, твой черновик презентации и снимки каждого слайда ровно в том виде, в каком они \
попадут в PowerPoint (WebGL здесь программный, 3D может выглядеть чуть проще), и проблемы, которые нашла проверка. \
Посмотри на слайды глазами придирчивого арт-директора и доведи презентацию до 10 из 10:
1. Сначала исправь всё сломанное: пустые или чёрные слайды, обрезанный или вылезающий текст, наложения, мелкий \
или нечитаемый текст, слабый контраст, неровные поля и «прыгающие» заголовки, ошибки JS.
2. Затем усиль: выразительные визуалы на каждом слайде, разнообразие раскладок, ритм, типографика, свет и \
глубина, точность и сила формулировок. Не упрощай и не выкидывай удачное — улучшай; число и порядок слайдов \
меняй, только если это делает историю лучше.
Ответ — только исправленный документ целиком, от <!doctype html> до </html>, по тем же правилам."""

PHOTO_NOTE = ("\n\nК заданию приложено фото из чата — ты его видишь. Вставляй его строкой __PHOTO__ "
              "(<img src=\"__PHOTO__\" alt=\"…\"> или CSS url(__PHOTO__)), бот подставит само фото. "
              "Лучше один раз — например, в CSS-переменную или один <img>.")


class StudioError(Exception):
    def __init__(self, message: str, cost_usd: float = 0.0):
        super().__init__(message)
        self.cost_usd = cost_usd


@dataclass
class StudioResult:
    html: str
    cost_usd: float
    seconds: float
    output_tokens: int = 0
    shots: Any = None  # последние снимки из браузера (у презентации — сами слайды)


@dataclass
class _State:
    busy_chats: set[int] = field(default_factory=set)
    running: int = 0
    waiting: int = 0
    seconds: float = 480.0  # сколько обычно делается страница целиком (скользящее среднее)


STATE = _State()
_slots: asyncio.Semaphore | None = None
_slots_n = 0
_client: Any = None


def _semaphore(n: int) -> asyncio.Semaphore:
    global _slots, _slots_n
    if _slots is None or _slots_n != n:
        _slots, _slots_n = asyncio.Semaphore(max(1, n)), n
    return _slots


def estimate_seconds(concurrency: int) -> float:
    ahead = STATE.running + STATE.waiting
    rounds = 1 + ahead // max(1, concurrency)
    return STATE.seconds * rounds


def human_eta(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes == 1:
        return "примерно через минуту"
    if minutes in (2, 3, 4):
        return f"минуты через {minutes}"
    return f"минут через {minutes}"


def extract_html(text: str) -> str:
    """Ответ модели -> документ: без ``` и пояснений вокруг."""
    t = (text or "").strip()
    fence = re.search(r"```(?:html)?\s*\n(.*?)(?:\n```|$)", t, re.DOTALL | re.IGNORECASE)
    if fence and "<" in fence.group(1):
        t = fence.group(1).strip()
    low = t.lower()
    start = min((i for i in (low.find("<!doctype"), low.find("<html")) if i >= 0), default=-1)
    if start > 0:
        t, low = t[start:], low[start:]
    end = low.rfind("</html>")
    if end >= 0:
        t = t[: end + len("</html>")]
    if "<" not in t or not re.search(r"<(?:body|div|main|section|canvas|svg|h1|style|script)\b", t, re.IGNORECASE):
        raise StudioError("не получилось сделать страницу")
    return t


ATTEMPTS = 2  # обрыв связи или перегрузка — ещё одна попытка
RETRY_PAUSE = 15
RETRY_STATUS = {408, 429, 500, 502, 503, 504, 529}


def status_text(exc: Any) -> str:
    """Ошибка API -> понятная причина (видна в чате и в логе)."""
    code = getattr(exc, "status_code", 0)
    text = str(getattr(exc, "message", "") or exc).lower()
    if "credit balance" in text or "billing" in text:
        return "на счёте Anthropic кончились деньги для API (пополни в console.anthropic.com)"
    if code == 401:
        return "ключ ANTHROPIC_API_KEY не подходит"
    if code in (403, 404) or "model" in text and code == 400:
        return f"модель недоступна этому ключу ({code}) — поставь HTML_MODEL=claude-sonnet-5-5"
    if code in (429, 529) or code >= 500:
        return f"Anthropic сейчас перегружен ({code}) — попробуй через пару минут"
    return f"студия недоступна ({code}): {text[:120]}"


def _thinking(model: str) -> dict[str, Any]:
    # у моделей 5-го поколения адаптивное обдумывание; глубину задаёт effort
    return {"thinking": {"type": "adaptive"}} if re.search(r"-5(?:[-.]|$)|fable", model) else {}


def client(timeout: float) -> Any:
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.AsyncAnthropic(max_retries=1, timeout=timeout)
    return _client


def _image_block(mime: str, data: bytes) -> dict[str, Any]:
    import base64

    return {"type": "image", "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()}}


async def generate(settings: Any, brief: str, title: str, image: tuple[str, bytes] | None = None, *,
                   draft: str | None = None, shots: Any = None, kind: str = "page") -> StudioResult:
    """Написать страницу по заданию (или, с draft и shots, доделать черновик по скриншотам).
    image — фото из чата, которое модель видит (вставляется как __PHOTO__)."""
    import anthropic

    from .llm.messages_api import estimate_cost

    model = settings.html_model
    text = f"Название: {title}\n\nЗадание:\n{brief.strip()}" + (PHOTO_NOTE if image else "")
    content: list[dict[str, Any]] = []
    if image is not None:
        content.append(_image_block(*image))
    content.append({"type": "text", "text": text})
    effort = settings.html_effort
    if draft is not None:
        effort = settings.html_polish_effort or effort
        content.append({"type": "text", "text": f"Твой черновик:\n```html\n{draft}\n```"})
        for label, jpeg in getattr(shots, "images", []):
            content.append({"type": "text", "text": f"Скриншот — {label}:"})
            content.append(_image_block("image/jpeg", jpeg))
        errors = getattr(shots, "errors", [])
        notes = ["Ошибки в консоли:\n" + "\n".join(f"- {e}" for e in errors) if errors else "Ошибок в консоли нет."]
        if getattr(shots, "overflow", False):
            notes.append("Страница шире экрана телефона: есть горизонтальная прокрутка.")
        problems = getattr(shots, "problems", [])
        if problems:
            notes.append("Проверка нашла:\n" + "\n".join(f"- {p}" for p in problems))
        content.append({"type": "text", "text": "\n".join(notes) + "\n\n" + (DECK_POLISH if kind == "deck" else POLISH)})
    kwargs: dict[str, Any] = {
        "model": model, "max_tokens": settings.html_max_tokens, "system": DECK_SYSTEM if kind == "deck" else SYSTEM,
        "messages": [{"role": "user", "content": content if len(content) > 1 else text}], **_thinking(model),
    }
    if effort:
        kwargs["output_config"] = {"effort": effort}
    started = time.monotonic()
    cl = client(settings.html_timeout)

    async def call() -> Any:
        async with cl.messages.stream(**kwargs) as stream:
            return await stream.get_final_message()

    for attempt in range(1, ATTEMPTS + 1):
        try:
            msg = await asyncio.wait_for(call(), timeout=settings.html_timeout)
            break
        except asyncio.TimeoutError as exc:
            raise StudioError("страница делалась слишком долго — попробуй попроще") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in RETRY_STATUS and attempt < ATTEMPTS:
                log.warning("студия: %s — повторяю через %d с", exc.status_code, RETRY_PAUSE)
                await asyncio.sleep(RETRY_PAUSE)
                continue
            raise StudioError(status_text(exc)) from exc
        except Exception as exc:
            # обрыв связи посреди долгого ответа SDK отдаёт «сырой» сетевой ошибкой (RemoteProtocolError, ReadError…)
            if attempt < ATTEMPTS:
                log.warning("студия: связь оборвалась (%s: %s) — повторяю", type(exc).__name__, exc)
                await asyncio.sleep(RETRY_PAUSE)
                continue
            log.exception("студия: связь оборвалась")
            raise StudioError(f"связь со студией оборвалась ({type(exc).__name__}) — попробуй ещё раз") from exc
    cost = estimate_cost(model, msg.usage)
    seconds = time.monotonic() - started
    out_tokens = getattr(msg.usage, "output_tokens", 0) or 0
    log.info("страница%s: %.0f с, %d токенов, %.3f$, %s", " (доводка)" if draft else "", seconds, out_tokens, cost,
             msg.stop_reason)
    if msg.stop_reason == "refusal":
        raise StudioError("такую страницу делать отказались", cost)
    if msg.stop_reason == "max_tokens":
        raise StudioError("страница получилась слишком большой — попробуй попроще", cost)
    body = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    try:
        html = extract_html(body)
    except StudioError as exc:
        exc.cost_usd = cost
        raise
    return StudioResult(html, cost, seconds, out_tokens)


async def make(settings: Any, brief: str, title: str, image: tuple[str, bytes] | None = None,
               build: Callable[[str], bytes] | None = None, kind: str = "page") -> StudioResult:
    """Черновик, затем доводка по снимкам из браузера. build(html) -> готовый файл (с библиотеками и фото).
    kind="page" — страница (снимки как на телефоне), "deck" — презентация (снимок каждого слайда; без снимков
    её не собрать). Доводка не удалась или сломала результат — остаётся черновик."""
    from . import page_shots, weblibs

    deck = kind == "deck"
    shoot = page_shots.shoot_deck if deck else page_shots.shoot
    started = time.monotonic()
    draft = await generate(settings, brief, title, image, kind=kind)
    cost, result, shots = draft.cost_usd, draft, None
    browser = build is not None and page_shots.available()
    if deck and not browser:
        raise StudioError("на сервере нет браузера, чтобы нарисовать слайды", cost)
    if browser and (deck or settings.html_polish):
        try:
            await weblibs.ensure()
            if not deck and await asyncio.to_thread(weblibs.missing):
                raise page_shots.ShotsError("библиотеки не скачались — в браузере без сети страница не откроется")
            before = shots = await shoot(await asyncio.to_thread(build, draft.html))
            if settings.html_polish:
                polished = await generate(settings, brief, title, image, draft=draft.html, shots=before, kind=kind)
                cost += polished.cost_usd
                after = await shoot(await asyncio.to_thread(build, polished.html))
                if _worse(after, before, deck):
                    log.warning("доводка сделала хуже (ошибок JS %d > %d, кадров %d из %d) — оставляю черновик",
                                after.page_errors(), before.page_errors(), len(after.images), len(before.images))
                else:
                    result, shots = polished, after
        except StudioError as exc:
            cost += exc.cost_usd
            log.warning("доводка не удалась: %s — оставляю черновик", exc)
        except page_shots.ShotsError as exc:
            log.warning("снимки не получились: %s — без доводки", exc)
        except Exception:
            log.exception("доводка: ошибка — оставляю черновик")
        if deck and (shots is None or not shots.slides):
            raise StudioError("не получилось нарисовать слайды", cost)
    seconds = time.monotonic() - started
    STATE.seconds = 0.7 * STATE.seconds + 0.3 * seconds
    return StudioResult(result.html, cost, seconds, result.output_tokens, shots)


def _worse(after: Any, before: Any, deck: bool) -> bool:
    if after.page_errors() > before.page_errors():
        return True
    return deck and len(after.slides) < max(1, round(len(before.slides) * 0.7))


async def run(settings: Any, brief: str, title: str, image: tuple[str, bytes] | None = None,
              build: Callable[[str], bytes] | None = None, kind: str = "page") -> StudioResult:
    """make() с общей очередью: одновременно не больше HTML_CONCURRENCY страниц."""
    slots = _semaphore(settings.html_concurrency)
    STATE.waiting += 1
    try:
        await slots.acquire()
    finally:
        STATE.waiting -= 1
    STATE.running += 1
    try:
        return await make(settings, brief, title, image, build, kind)
    finally:
        STATE.running -= 1
        slots.release()
