"""Студия HTML-страниц: Стелла в чате только описывает задание, а страницу пишет отдельный вызов модели —
с подробным дизайн-промптом, долгим обдумыванием и большим запасом длины (в чате модель отвечает быстро и
коротко — для сайта уровня «вау» этого мало). Страница приходит в чат файлом через несколько минут.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
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


@dataclass
class _State:
    busy_chats: set[int] = field(default_factory=set)
    running: int = 0
    waiting: int = 0
    seconds: float = 240.0  # сколько обычно делается страница (скользящее среднее)


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


def _thinking(model: str) -> dict[str, Any]:
    # у моделей 5-го поколения адаптивное обдумывание; глубину задаёт effort
    return {"thinking": {"type": "adaptive"}} if re.search(r"-5(?:[-.]|$)|fable", model) else {}


def client(timeout: float) -> Any:
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.AsyncAnthropic(max_retries=1, timeout=timeout)
    return _client


async def generate(settings: Any, brief: str, title: str, image: tuple[str, bytes] | None = None) -> StudioResult:
    """Написать страницу по заданию. image — фото из чата, которое модель видит (вставляется как __PHOTO__)."""
    import base64

    import anthropic

    from .llm.messages_api import estimate_cost

    model = settings.html_model
    text = f"Название: {title}\n\nЗадание:\n{brief.strip()}" + (PHOTO_NOTE if image else "")
    content: Any = text
    if image is not None:
        mime, data = image
        content = [{"type": "image", "source": {"type": "base64", "media_type": mime,
                                                "data": base64.b64encode(data).decode()}},
                   {"type": "text", "text": text}]
    kwargs: dict[str, Any] = {
        "model": model, "max_tokens": settings.html_max_tokens, "system": SYSTEM,
        "messages": [{"role": "user", "content": content}], **_thinking(model),
    }
    if settings.html_effort:
        kwargs["output_config"] = {"effort": settings.html_effort}
    started = time.monotonic()
    cl = client(settings.html_timeout)

    async def call() -> Any:
        async with cl.messages.stream(**kwargs) as stream:
            return await stream.get_final_message()

    try:
        msg = await asyncio.wait_for(call(), timeout=settings.html_timeout)
    except asyncio.TimeoutError as exc:
        raise StudioError("страница делалась слишком долго — попробуй попроще") from exc
    except anthropic.APIStatusError as exc:
        raise StudioError(f"студия недоступна ({exc.status_code})") from exc
    except anthropic.APIConnectionError as exc:
        raise StudioError("студия недоступна (нет связи)") from exc
    cost = estimate_cost(model, msg.usage)
    seconds = time.monotonic() - started
    out_tokens = getattr(msg.usage, "output_tokens", 0) or 0
    log.info("страница: %.0f с, %d токенов, %.3f$, %s", seconds, out_tokens, cost, msg.stop_reason)
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
    STATE.seconds = 0.7 * STATE.seconds + 0.3 * seconds
    return StudioResult(html, cost, seconds, out_tokens)


async def run(settings: Any, brief: str, title: str, image: tuple[str, bytes] | None = None) -> StudioResult:
    """generate() с общей очередью: одновременно не больше HTML_CONCURRENCY страниц."""
    slots = _semaphore(settings.html_concurrency)
    STATE.waiting += 1
    try:
        await slots.acquire()
    finally:
        STATE.waiting -= 1
    STATE.running += 1
    try:
        return await generate(settings, brief, title, image)
    finally:
        STATE.running -= 1
        slots.release()
