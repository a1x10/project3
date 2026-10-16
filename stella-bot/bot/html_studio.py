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

FONTS_LINE = ("вариативные, толщины 200–900 (смело бери 800/900): 'Unbounded' (широкий современный, заголовки), "
              "'Montserrat', 'Inter' (текст и интерфейс), 'Rubik' (дружелюбный, от 300), 'Playfair Display' "
              "(элегантная антиква, от 400); до 700: 'Comfortaa' (округлый, милый), 'Caveat' (рукописный); одно "
              "начертание 400 — font-weight им не ставь: 'Lobster' (ретро-надпись), 'Russo One' (жирный: игры, спорт), "
              "'Press Start 2P' (пиксельный)")

FONT_RULES = """- Контурный текст: у вариативных шрифтов контуры букв перекрываются, и -webkit-text-stroke с прозрачной \
заливкой рисует лишние линии внутри букв. Контур — только с заливкой цветом фона под текстом и paint-order: stroke \
fill, или не делай его на крупных буквах.
- Значков ★ ✓ ↻ ∞ ▲ ♥ и подобных в шрифтах нет — иконки только inline SVG."""

THREE_RECIPE = """- Цвет и свет (r128), точные числа: renderer.outputEncoding = THREE.sRGBEncoding; renderer.toneMapping = \
THREE.ACESFilmicToneMapping, toneMappingExposure 0.9–1.1; цвета материалов — new THREE.Color('#hex')\
.convertSRGBToLinear(), у CanvasTexture — texture.encoding = THREE.sRGBEncoding (иначе палитра выцветает).
- Bloom: new THREE.UnrealBloomPass(new THREE.Vector2(w, h), 0.6–0.9, 0.4, 0.75–0.85) — порог ниже 0.6 не ставь \
никогда. Светятся только тонкие неоновые детали (MeshBasicMaterial или emissive на мелочах); у главных объектов \
emissiveIntensity ≤ 0.3 и базовый цвет не светлее ~#c8c8dc — должны читаться форма, блик и материал, а не белое \
пятно. Металл и clearcoat без окружения выглядят пластиком: scene.environment = new THREE.PMREMGenerator(renderer)\
.fromScene(envScene, 0.04).texture, где envScene — 3–4 цветные светящиеся плоскости вокруг.
- Кадр в портрете: видимая высота на дистанции d — 2·d·tan(fov/2), ширина — высота × aspect (≈0.46). fov 40–50; \
герой занимает 50–70% ширины, фоновые объекты (планеты, кольца) — не больше 35% ширины, в углу и частично за кадром; \
пересчитывай на resize.
- Без артефактов: тонкие трубки и THREE.Line/LineSegments (всегда 1 px) с ребра выглядят полосками-ошибками — \
лучи, лазеры и варп делай вытянутыми Sprite/плоскостями с градиентом; конусы света — Sprite с радиальным градиентом, \
а не прозрачный открытый цилиндр; кольца планет наклоняй на 25° и больше; размер Points умножай на pixelRatio \
(звёзды 2–4 css px)."""

SYSTEM = f"""Ты — арт-директор и креативный фронтенд-разработчик уровня Awwwards и Codrops. По заданию из чата \
делаешь одну HTML-страницу. Её откроют на телефоне прямо из WhatsApp или Telegram, и с первой секунды она \
должна вызывать «вау»: выглядеть как дорогая работа студии, а не как шаблон.

ФОРМАТ ОТВЕТА
- Только готовый документ: от <!doctype html> до </html>. Без пояснений до и после, без ```.
- Всё в одном файле: CSS в <style>, свой JS в обычном <script> (не type="module", без import/export).
- Тексты — на языке задания (обычно русский): живые, конкретные, по фактам из задания. Никаких «lorem ipsum», \
«Заголовок», «Текст здесь» и прочих заглушек. Факты, цифры, даты и имена — точные; в чём не уверен — не пиши. \
Шуточные детали в духе задания можно и нужно, выдумывать важное (даты, адреса, события) — нельзя.

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
  <script src="lib/gsap.js"></script> — GSAP 3 (gsap.to/fromTo/timeline, stagger, ease)
  <script src="lib/gsap-scrolltrigger.js"></script> — ScrollTrigger (после gsap; gsap.registerPlugin(ScrollTrigger))
  <script src="lib/confetti.js"></script> — confetti({{particleCount, spread, origin, colors}})
  <script src="lib/matter.js"></script> — Matter (2D-физика для игр)
- Шрифты с кириллицей — просто пиши их в font-family (и в ctx.font у canvas), бот встроит их сам; никаких \
<link> и @import. {FONTS_LINE}. Не больше двух-трёх семейств, всегда с запасным (sans-serif / serif). \
Шрифт в canvas — только после document.fonts.ready.
{FONT_RULES}

БАЗА CSS — ВСЕГДА
*,*::before,*::after{{box-sizing:border-box}} html,body{{margin:0;overflow-x:clip}} \
button,input,select,textarea{{font:inherit;color:inherit}} img,svg,canvas{{display:block;max-width:100%}}
(у <button> по умолчанию чёрный системный шрифт — без этой строки кнопки на тёмном фоне не читаются). \
Наклонённые и масштабированные полосы во всю ширину (бегущая строка, ленты) — внутри обёртки width:100%; \
overflow:hidden: любой вылет за 100vw на мобильном Chrome расширяет страницу и сдвигает fixed-элементы.

ДИЗАЙН: ЧЕМ «ВАУ» ОТЛИЧАЕТСЯ ОТ ШАБЛОНА
1. Концепция. Сначала придумай сильную идею и арт-дирекшн под этот повод и этих людей (день рождения — ночное \
небо и торт из света; викторина про космос — кабина корабля; шпаргалка — неоновая доска). Никаких безликих \
карточек на белом фоне и «бутстрап»-вида. Один герой: на экране один главный визуальный объект (3D-сцена, крупная \
SVG-иллюстрация или типографика) и 1–2 спокойных слоя фона. Каждый эффект должен улучшать кадр, а не добавляться \
«для богатства»: стекло, зерно, bloom, частицы, параллакс — выбирай нужное.
2. Цвет. Один доминирующий тон, один-два акцента, нейтральные — через CSS-переменные. Глубокие градиенты (mesh \
из нескольких radial-gradient), мягкие свечения и тени. Текст всегда читается.
3. Типографика. Крупные выразительные заголовки (clamp(), трекинг, градиент, переменная толщина), ясная иерархия, \
межстрочный 1.4–1.6 у текста.
4. Композиция экрана (проверяй на 390×844 и 360×640). Зоны не смешиваются: заголовок — в верхней трети \
(grid-template-rows: auto 1fr auto, а не justify-content: space-between), главный объект — в своей средней зоне, \
главная кнопка — внизу (16 px + env(safe-area-inset-bottom) от края). Крупный текст никогда не лежит на главном \
3D-объекте или ярком пятне; под текстом над canvas — затемняющая подложка (radial-gradient) или text-shadow \
0 2px 14px rgba(0,0,0,.7). Декор (рамки, прицелы, штампы, стикеры, подписи, нити) не перекрывает текст и данные — \
оставь им место в сетке. Если сценарий что-то раскрывает (подарок открылся, объект вырос), раскрытие видно \
целиком: уведи или уменьши заголовок, сдвинь камеру.
5. Движение. Параллакс от пальца/мыши (от наклона телефона — deviceorientation, на iOS разрешение — по тапу), \
появления со stagger, появление по скроллу (ScrollTrigger или IntersectionObserver), микро-взаимодействия \
(нажатие пружинит, ripple, navigator.vibrate в играх), easing power3/expo/back, живой фон.
   ПЕРВЫЙ КАДР: ссылку открывают из мессенджера, и через 1 с (даже на слабом телефоне) первый экран — законченная \
композиция, заголовок и главная кнопка видны полностью. Всё интро ≤ 1 с; исходное состояние в CSS видимое — JS \
только добавляет движение; 3D-объект сразу в кадре и лишь «доезжает», не со scale 0.
   GSAP и CSS не делят одно свойство: у того, что двигает GSAP, нет CSS transition/animation на transform, \
translate, scale, opacity (иначе gsap.from застывает в начале и элемент остаётся сдвинутым) — пружину нажатия \
вешай на внутренний <span>. Появления — gsap.fromTo(el, {{…}}, {{…, clearProps: 'transform'}}); центрирование — \
xPercent/yPercent: -50, а не CSS translate вместе с gsap x/y; позиции в timeline — абсолютные числа или метки.
6. 3D (three.js) — когда объект и есть идея. Если 3D — фон под интерфейсом: canvas pointer-events: none, \
параллакс от pointermove/deviceorientation; OrbitControls — только когда 3D и есть главный интерактивный экран. \
Красивые формы — из примитивов (TorusKnot, Icosahedron с flatShading, Lathe, Extrude из Shape, RoundedBox) или \
своими ShaderMaterial (градиенты, шум, волны). Текст поверх 3D — HTML-слоем.
{THREE_RECIPE}
7. Эффекты с гигиеной. Временные подписи и тосты — absolute внутри своего экрана (не fixed), исчезают за 2–3 с. \
Конфетти — короткие залпы (particleCount ≤ 120, ticks ≤ 200), не поверх текста, который сейчас читают; при смене \
экрана — confetti.reset(). Штампы и бейджи — на свободное поле, не на данные. Подписи и счётчики с первого кадра \
говорят правду (не «0 часов сна», пока не досчитали до 24).
8. Детали. Отступы по 8-px сетке, аккуратные скругления, состояния нажатия. Каждый экран — композиция, а не стопка \
блоков.

ТЕЛЕФОН — ГЛАВНОЕ
- Основной экран — 360–430 px в ширину; на компьютере тоже красиво (max-width, сетки; в ландшафте визуал сбоку). \
100dvh; отступы с env(safe-area-inset-*). Ширина контента на 360 px — 328 px: ряд пилюль или чипов либо влезает \
(капс с трекингом ≈ 0.75em на букву), либо flex-wrap ровными рядами; текст кнопок — в одну строку.
- Главное действие экрана (Играть, Открыть, Начать, Вступить) — первая <button> в DOM и с атрибутом data-primary; \
кнопки звука и меню — после неё в DOM (на экране — где угодно). Без нужды не блокируй прокрутку модальным окном.
- Управление пальцем: pointer-события, цели не меньше 44 px, ничего только по hover; в играх touch-action: none \
и никакого зума двойным тапом.
- Плавно, 60 fps: requestAnimationFrame; renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); одна полноэкранная \
WebGL-сцена; не больше 1–2 крупных элементов с backdrop-filter; не анимируй полноэкранные слои с filter или зерном; \
анимируй transform/opacity; пауза на visibilitychange; правильный resize. Если первые 2 с fps < 40 — pixelRatio 1, \
без bloom, частиц вдвое меньше.
- prefers-reduced-motion — приглуши движение.

ПО ЖАНРАМ
- Игра: стартовый экран с названием и кнопкой «Играть», правила одной строкой, счёт, рекорд (localStorage в \
try/catch), экран «Игра окончена» с «Ещё раз», нарастающая сложность, «сочность» (частицы, тряска экрана, \
вспышки, звуки через WebAudio — AudioContext только после первого тапа), управление тапами и свайпами (и клавишами \
на компьютере). Фон поля тёмный и спокойный (декор не ярче ~30% и не в полосе, откуда всё падает, и не у игрока); \
игрок, бонусы и враги — самые яркие объекты на экране; первый предмет — не позже 0.5 с после «Играть»; dt ограничивай \
0.1 (или фиксированный шаг), хитбоксы — в тех же единицах, что и картинка; игровой экран без прокрутки. Для аркады \
чёткий 2D-canvas со свечением часто лучше перегруженного 3D.
- Викторина/тест: 5–10 вопросов, прогресс, после ответа варианты блокируются, верный подсвечивается (и при ошибке), \
короткое пояснение и кнопка «Дальше» без автоперехода; экран вопроса без прокрутки на 390×844, варианты от 56 px; \
итог с оценкой и конфетти, «Пройти ещё раз».
- Открытка/поздравление: эффектное появление (например, «открыть подарок» по тапу), имя крупно, тёплый личный \
текст по фактам из задания, салют/конфетти/3D; музыка WebAudio — только по тапу.
- Сайт/лендинг/шпаргалка: hero-экран с вау-эффектом, разделы с анимацией появления, удобная навигация, настоящее \
содержание из задания.

НАДЁЖНОСТЬ
- Ноль ошибок в консоли: свой код запускай после загрузки DOM, проверяй элементы. WebGLRenderer создавай в \
try/catch: нет WebGL — простой красивый 2D-вариант (градиенты, свечение, точки-звёзды), а не пустой экран. Никаких \
alert/prompt/confirm.
- Работает сразу, без сети и сервера, при открытии файла с телефона.
- Объём — насыщенно, но разумно (обычно 500–1200 строк). Законченная и отполированная страница лучше огромной \
и недоделанной.

ПЕРЕД ВЫДАЧЕЙ мысленно открой страницу на 390×844 и 360×640 — через 1 с, после главного тапа и после прокрутки — \
и проверь: 1) заголовок и главная кнопка видны целиком через 1 с; 2) ни один текст не лежит на ярком 3D или декоре \
и не перекрыт штампом, подписью, конфетти или fixed-элементом; 3) каждый ряд влезает в 328 px, ничто не выходит за \
100vw; 4) у кнопок свой цвет и шрифт; 5) bloom: порог ≥ 0.7, главный объект — не белое пятно; 6) раскрытие после \
тапа видно целиком; 7) нет CSS transition на свойствах, которые двигает GSAP; 8) первая <button> — главное действие; \
9) счётчики и подписи с первого кадра говорят правду. Исправь найденное — и выдай документ целиком."""

POLISH = """Выше — задание и твой черновик страницы, а на картинках — как он на самом деле выглядит в телефоне \
(браузер 390×844; WebGL здесь программный, поэтому 3D может выглядеть чуть проще, а анимации пойманы на середине). \
Посмотри на скриншоты глазами придирчивого арт-директора топ-студии.
1. Сначала исправь всё, что видно на скриншотах и в ошибках: ошибки JS; пустые, чёрные или недорисованные области; \
текст на ярком 3D или декоре, текст под штампом, подписью, конфетти или fixed-элементом; вылезание за край экрана и \
горизонтальная прокрутка; обрезанный, мелкий или нечитаемый текст (кнопки с чёрным системным шрифтом); белые \
пересвеченные пятна вместо объектов (bloom: порог ≥ 0.7, emissive ≤ 0.3); раскрытие после тапа, которое не видно; \
элементы, застрявшие со сдвигом (CSS transition вместе с GSAP); кнопки, которые ничего не делают; пустой первый кадр.
2. Концепцию не меняй и новых эффектов не добавляй, пока не исправлено всё сломанное, — каждый новый эффект ты уже \
не увидишь на скриншоте. Удачное не выкидывай.
3. Затем, если всё чисто, усиль впечатление точечно: композиция первого экрана, типографика, цвет и свет, детали.
Ответ — только исправленный документ целиком, от <!doctype html> до </html>, по тем же правилам."""

DECK_THREE = """- 3D (three.js r128) — на обложке и разделителях, когда это украшает: renderer.outputEncoding = \
THREE.sRGBEncoding, toneMapping = THREE.ACESFilmicToneMapping (exposure 0.9–1.1), цвета — new THREE.Color('#hex')\
.convertSRGBToLinear(); bloom — порог ≥ 0.75, сила 0.6–0.9; у главных объектов emissiveIntensity ≤ 0.3. \
Процедурные текстуры (canvas) рисуй синхронно до события load; рельеф мягкий (малый bumpScale, без резких масок), \
детали — цветом; полосы и каньоны плавно сходят на нет к концам. Под canvas положи SVG-вариант той же сцены — если \
WebGL не создался, кадр не пустой."""

DECK_SYSTEM = f"""Ты — арт-директор и дизайнер презентаций уровня Apple Keynote, Pitch и лучших брендинговых студий. \
По заданию из чата делаешь презентацию: один HTML-документ, где каждый слайд — <section class="slide"> ровно \
1920×1080 px. Бот снимет каждый слайд как картинку и соберёт из них PowerPoint и PDF, поэтому каждый слайд должен \
быть идеальным статичным кадром — таким, чтобы зал ахнул.

ФОРМАТ ОТВЕТА
- Только готовый документ: от <!doctype html> до </html>. Без пояснений до и после, без ```.
- Структура: в <body> подряд идут <section class="slide">…</section>. В слайд вложи \
<aside class="notes">что говорить выступающему: 2–4 живых предложения</aside> — на слайде его не видно, он попадёт \
в заметки PowerPoint. Пиши заметки к каждому содержательному слайду; подробности, не влезшие на слайд, — туда же.
- CSS: body {{ margin: 0 }} .slide {{ width: 1920px; height: 1080px; position: relative; overflow: hidden; }}. \
Никаких скриптов просмотра, навигации, масштабирования под экран, прокрутки внутри слайда и анимаций появления: \
кадр снимается сразу, виден только финальный вид. JS — только чтобы нарисовать (canvas, three.js), синхронно \
при загрузке; для WebGL — preserveDrawingBuffer: true, и один кадр отрисуй сразу.
- Колонтитул, надзаголовок и номер слайда помечай атрибутом data-chrome (их не считают в словах).

ОГРАНИЧЕНИЯ (нарушишь — слайды сломаются)
- Интернета нет: внешние картинки, шрифты, CSS и скрипты не загрузятся; растровые картинки — только data:.
- Библиотеки — только такими тегами: <script src="lib/three.js"></script> (three.js r128, глобальный THREE), \
<script src="lib/three-roundedbox.js"></script> (THREE.RoundedBoxGeometry, после three.js), \
<script src="lib/three-bloom.js"></script> (EffectComposer, RenderPass, UnrealBloomPass, после three.js). \
Подключай только то, что используешь.
- Шрифты с кириллицей — просто пиши их в font-family, бот встроит их сам; никаких <link> и @import. {FONTS_LINE}. \
Два семейства на всю презентацию: выразительное для заголовков, спокойное для текста.
{FONT_RULES}
- Декоративные кавычки, огромные буквы и цифры-фон — SVG-фигурой с aria-hidden="true", внутри рамки слайда, а не \
глифом шрифта (кавычка «Unbounded» в 220 px превращается в «//»). Знаки ≈ ₽ → × крупнее 80 px — шрифтом текста или \
словами («около»).
- SVG: градиент или фильтр на горизонтальной/вертикальной линии — только с gradientUnits="userSpaceOnUse" / \
filterUnits="userSpaceOnUse", иначе линия исчезнет. Все id (градиенты, фильтры, clipPath) уникальны на всю \
презентацию — с префиксом слайда (s4-glow): все слайды в одном документе. Повторяющийся рисунок — один <symbol> в \
<svg width="0" height="0"> (не display:none — пропадут градиенты) и <use>. viewBox — в реальных пикселях слайда, \
текст в SVG ≥ 24 px; подписи не ближе 40 px к краю viewBox.
{DECK_THREE}

СОДЕРЖАНИЕ — КАК У СИЛЬНОГО СПИКЕРА
- 10–14 слайдов, если в задании не сказано иначе (не больше 25). История: обложка → зачем это / главный вопрос → \
смысловые блоки → выводы → финальный слайд. Если задание перечисляет слайды или задаёт их число — следуй списку \
1:1: без лишних разделителей и отдельного «Спасибо», если их нет в списке; главу обозначай надзаголовком \
(«01 · Планета»). Несколько тем на один слайд — каждая в 2–4 словах на слайде, подробности — в заметках.
- Один слайд — одна мысль. Заголовок — утверждение, а не ярлык («Марс потерял океан 3 млрд лет назад», а не \
«История Марса»). Не больше 40 слов содержания на слайде: 3–5 коротких тезисов, или одна большая цифра с подписью, \
или цитата. Никаких стен текста.
- Разные раскладки, без повторов подряд: обложка во весь экран; большая цифра/факт; два столбца; сравнение \
«было/стало» или «за/против»; таймлайн; процесс/схема со стрелками; цитата; диаграмма (SVG: столбцы, линии, \
круговая — с подписями и точными значениями); крупная иллюстрация с подписями. Сетку одинаковых карточек с иконкой — \
не больше двух раз за презентацию.
- ДАННЫЕ. Факты, цифры, даты, имена — из задания или точных знаний; в чём не уверен — формулируй без ложных \
подробностей. Диаграммы — только из цифр задания и явных расчётов из них (формулу — мелкой строкой); прогноз \
отличай пунктиром или штриховкой и подписывай. Метрики задания не переименовывай и не раскладывай на части, которых \
не дали. У каждого «×N» и «в N раз» — с чем сравниваем. Цитаты — дословно. Карточки и таймлайны — в хронологическом \
порядке. Нет данных для обязательного слайда (контакты, имена, цифры) — не рисуй пустых полей и «укажите…»: собери \
сильный слайд из того, что есть, а чего не хватает — перечисли в заметках.
- Питч инвесторам: одна метрика — один слайд; рынок — формулой снизу вверх с пометкой «оценка»; «что просим» — \
сумма, на что пойдут деньги, ожидаемый результат.

ДИЗАЙН: ЧЕМ 10/10 ОТЛИЧАЕТСЯ ОТ ШАБЛОНА
1. Концепция и единая система под тему (космос — глубокий тёмный с туманностями; экология — свежая природная \
палитра и органические формы; история — благородная бумага и антиква). Палитра: фон-тон, 1–2 акцента, нейтральные \
(CSS-переменные).
2. СЕТКА 1920×1080. Поля слева и справа — 120 px, им подчиняются и гигантские цифры (у крупного глифа есть боковой \
отступ — выровняй левый край по линии текста). Надзаголовок — около y 96, заголовок — в полосе 130–330 px, одинаково \
на всех слайдах. Контент — в зоне 380–950 px, блок центрирован по вертикали; пустых полос выше 120 px в зоне и \
внутри карточек нет (карточки — по высоте содержимого или с крупным визуалом). Колонтитул и номер — в 64–80 px от \
нижнего края; полоса ниже 980 px и 40 px вокруг номера свободны от иллюстраций.
3. Типографика крупная и уверенная: заголовки 64–110 px с плотным трекингом, текст 30–40 px, подписи от 24 px; \
акцентные слова цветом или градиентом; высокий контраст. Линейка ширины: знаков в строке ≈ ширина ÷ (кегль × k), \
k: Unbounded ≈ 0.72, Montserrat ≈ 0.62, Rubik ≈ 0.56, Inter ≈ 0.55, Playfair Display ≈ 0.5. Unbounded 76 px в \
1680 px — около 30 знаков: заголовок длиннее ~55 знаков в Unbounded — кегль 60–64 px или короче. Переносы в \
заголовках ставь <br> сам, по смыслу; акцентная фраза — целиком на одной строке. Тысячи — узким неразрывным \
пробелом одинаково во всех числах; у чисел с пробелом не ставь отрицательный трекинг.
4. Декор не трогает текст: линии, кольца, орбиты, шкалы, сетки, шпили и края иллюстраций не проходят через текст \
и не просвечивают сквозь карточки. Под текстом — ровный фон или мягкое размытое пятно. Карточки поверх декора, \
звёзд и текстур — непрозрачные (цвет смешай заранее, без rgba и backdrop-filter). Подписи к рисунку — в своём \
прямоугольнике, не пересекающем силуэт; иначе под подписью плашка. Между крупной цифрой и соседним текстом — \
зазор от 32 px.
5. ИЛЛЮСТРАЦИИ — на каждом слайде визуал, а не только текст; в одном стиле на всю презентацию, стилизованно-\
геометрические: силуэты, линия + плоская заливка, мягкий градиент + шум feTurbulence, изометрия. Не рисуй «на \
глаз» узнаваемую географию (континенты, береговые линии) и фотореализм — вместо карты схема маршрута на сетке. \
Рецепты: планета — сфера с терминатором, шумом и ободком атмосферы; вода — плоская заливка с береговой линией и \
рябью, не шар; каньон — сужающаяся ветвистая форма. Похожие объекты на соседних карточках различай силуэтом, а не \
цветом. Главный визуал занимает от 35% площади слайда; иконка 100 px визуалом не считается.
6. Глубина и свет: mesh-градиенты, мягкие свечения, тени; крупные декоративные формы, уходящие за край слайда; на \
обложке и разделителях — эффектный визуал (3D-объект, большая SVG-сцена, абстрактная композиция).

ПЕРЕД ВЫДАЧЕЙ пройди каждый слайд и исправь найденное: 1) заголовок ≤ 2 строк по линейке ширины, в последней строке \
не одно слово; 2) ни одна строка не начинается с тире, предлоги и единицы не висят в конце строки; 3) никакая \
линия, кольцо, шпиль или край рисунка не проходят через текст или карточку, номер слайда не лежит на рисунке; 4) у \
параллельных карточек заголовки занимают одинаковое число строк, внутри карточки нет пустоты > 120 px; 5) контент \
центрирован в зоне 380–950; 6) линии с градиентом или фильтром в SVG — с userSpaceOnUse, id уникальны; 7) подписи \
SVG не ближе 40 px к краю; 8) ≤ 40 слов содержания; 9) каждая цифра и дата — из задания или точных знаний, «×N» — \
с базой сравнения; 10) нет пустых полей и заглушек. Затем выдай документ целиком."""

DECK_POLISH = """Выше — задание, твой черновик презентации и снимки каждого слайда ровно в том виде, в каком они \
попадут в PowerPoint (снимки 1600×900: 1 px снимка = 1.2 px слайда — касание на снимке уже наложение; WebGL здесь \
программный, 3D может выглядеть чуть проще), и проблемы, которые нашла автоматическая проверка. Доведи презентацию \
до 10 из 10.
1. Сначала исправь всё сломанное — проверка находит не всё, ищи глазами: обрезанный текст (в том числе внутри SVG и \
карточек); текст, наезжающий или почти касающийся другого; линии, кольца, шпили и края рисунков, проходящие через \
текст или сквозь полупрозрачные карточки; элементы, которые есть в коде, но не видны на снимке (сверь код и снимок: \
линия с градиентом без userSpaceOnUse исчезает); одно слово в последней строке заголовка; разорванные даты и числа; \
пустые полосы > 120 px и полупустые карточки; номер слайда на рисунке; рисунки, которые читаются как другое \
(озеро-шар, каньон-червяк) — перерисуй форму, а не только цвета; пустые поля и «укажите…»; ошибки фактов, \
хронологии и цитат.
2. Правь точечно: всё, что не требует правки, перенеси без изменений. После любой правки текста в параллельных \
колонках и карточках проверь, что их заголовки занимают одинаковое число строк. Лимит слов проходи, вычёркивая \
второстепенное и дубли (подробности — в заметки), а не уменьшая кегль и не выкидывая факты из задания: если \
сокращение искажает факт, сократи формулировку, а не факт.
3. Затем усиль: выразительные визуалы на каждом слайде, разнообразие раскладок, ритм, типографика, свет и глубина. \
Число и порядок слайдов меняй, только если это делает историю лучше.
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
    reserved_usd: float = 0.0  # оценка расходов заказов, которые ещё делаются
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
    """Ответ модели -> документ: без ``` и пояснений вокруг. Сначала ищем сам документ (<!doctype/<html …
    последний </html>) — внутри страницы бывают свои ``` (шпаргалки по Markdown); ``` — только если документа нет."""
    t = (text or "").strip()
    low = t.lower()
    start = min((i for i in (low.find("<!doctype"), low.find("<html")) if i >= 0), default=-1)
    end = low.rfind("</html>")
    if start >= 0 and end > start:
        return t[start: end + len("</html>")]
    fence = re.search(r"```(?:html)?[ \t]*\n", t, re.IGNORECASE)
    if fence:
        close = t.rfind("\n```")
        inner = t[fence.end(): close] if close > fence.end() else t[fence.end():]
        if "<" in inner:
            t = inner.strip()
            low = t.lower()
    start = min((i for i in (low.find("<!doctype"), low.find("<html")) if i >= 0), default=-1)
    if start > 0:
        t = t[start:]
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
    """Адаптивное обдумывание (глубину задаёт effort): Opus/Sonnet 4.6+, всё 5-е поколение, Fable, Mythos. Старым
    моделям его слать нельзя (400) — им без обдумывания."""
    adaptive = {"thinking": {"type": "adaptive"}}
    if re.search(r"fable|mythos", model):
        return adaptive
    m = re.search(r"claude-(opus|sonnet|haiku)-(\d+)(?:-(\d{1,2}))?(?!\d)", model)  # claude-sonnet-4-20250514 — это 4.0
    if not m:
        return {}
    family, major, minor = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    return adaptive if major >= 5 or (major == 4 and minor >= 6 and family != "haiku") else {}


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
    base: dict[str, Any] = {
        "model": model, "max_tokens": settings.html_max_tokens, "system": DECK_SYSTEM if kind == "deck" else SYSTEM,
        "messages": [{"role": "user", "content": content if len(content) > 1 else text}], **_thinking(model),
    }
    budget = int(getattr(settings, "html_task_budget", 0) or 0)
    started = time.monotonic()
    cost = 0.0
    while True:
        msg = await _call(settings, base, effort, budget)
        if msg is _NO_BUDGET:  # API не принял бюджет — без него
            budget = 0
            continue
        cost += estimate_cost(model, msg.usage) + getattr(msg, "_studio_lost", 0.0)
        out_tokens = getattr(msg.usage, "output_tokens", 0) or 0
        body = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        log.info("страница%s: %.0f с, %d токенов (код — %d знаков), effort %s, %.3f$, %s", " (доводка)" if draft else "",
                 time.monotonic() - started, out_tokens, len(body), effort, cost, msg.stop_reason)
        if msg.stop_reason == "refusal":
            raise StudioError("такую страницу делать отказались", cost)
        if msg.stop_reason == "max_tokens" and "</html>" not in body.lower():
            lower = _lower_effort(effort)
            if lower is None:
                raise StudioError("страница получилась слишком большой — попробуй попроще", cost)
            # упёрлись в потолок длины (обдумывание тоже его ест) — ещё раз, подумав меньше
            log.warning("студия: упёрлась в max_tokens на effort %s — повторяю на %s", effort, lower)
            effort = lower
            continue
        try:
            html = extract_html(body)
        except StudioError as exc:
            exc.cost_usd = cost
            raise
        return StudioResult(html, cost, time.monotonic() - started, out_tokens)


_NO_BUDGET = object()
TASK_BUDGET_BETA = "task-budgets-2026-03-13"
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _lower_effort(effort: str | None) -> str | None:
    """Повтор после потолка длины — сразу на high (думает заметно меньше, страница остаётся сильной); с high и ниже
    не повторяем: каждая попытка стоит денег."""
    if effort not in EFFORTS or EFFORTS.index(effort) <= EFFORTS.index("high"):
        return None
    return "high"


async def _call(settings: Any, base: dict[str, Any], effort: str | None, budget: int) -> Any:
    """Один запрос потоком: при обрыве связи и перегрузке — ещё попытка. budget — сколько токенов модель видит
    на всю работу (обдумывание + код) и под это распределяет силы (бета task budgets)."""
    import anthropic

    cl = client(settings.html_timeout)
    kwargs = dict(base)
    config: dict[str, Any] = {}
    if effort:
        config["effort"] = effort
    if budget:
        config["task_budget"] = {"type": "tokens", "total": max(20000, budget)}
    if config:
        kwargs["output_config"] = config

    holder: dict[str, Any] = {}

    async def call() -> Any:
        holder["started"] = time.monotonic()
        if budget:
            async with cl.beta.messages.stream(betas=[TASK_BUDGET_BETA], **kwargs) as stream:
                holder["stream"] = stream
                return await stream.get_final_message()
        async with cl.messages.stream(**kwargs) as stream:
            holder["stream"] = stream
            return await stream.get_final_message()

    lost = 0.0  # оборванные попытки тоже оплачены — учитываем оценкой
    for attempt in range(1, ATTEMPTS + 1):
        try:
            msg = await asyncio.wait_for(call(), timeout=settings.html_timeout)
            msg._studio_lost = lost  # type: ignore[attr-defined]
            return msg
        except asyncio.TimeoutError as exc:
            raise StudioError("страница делалась слишком долго — попробуй попроще",
                              lost + _partial_cost(base, holder)) from exc
        except anthropic.APIStatusError as exc:
            if budget and exc.status_code == 400 and "budget" in str(exc).lower():
                log.warning("студия: бюджет токенов не принят (%s) — без него", str(exc)[:200])
                return _NO_BUDGET
            if exc.status_code in RETRY_STATUS and attempt < ATTEMPTS:
                log.warning("студия: %s — повторяю через %d с", exc.status_code, RETRY_PAUSE)
                await asyncio.sleep(RETRY_PAUSE)
                continue
            raise StudioError(status_text(exc)) from exc
        except Exception as exc:
            # обрыв связи посреди долгого ответа SDK отдаёт «сырой» сетевой ошибкой (RemoteProtocolError, ReadError…)
            lost += _partial_cost(base, holder)
            if attempt < ATTEMPTS:
                log.warning("студия: связь оборвалась (%s: %s) — повторяю", type(exc).__name__, exc)
                await asyncio.sleep(RETRY_PAUSE)
                continue
            log.exception("студия: связь оборвалась")
            raise StudioError(f"связь со студией оборвалась ({type(exc).__name__}) — попробуй ещё раз", lost) from exc
        finally:
            holder.pop("stream", None)
    raise StudioError("студия недоступна", lost)


def _partial_cost(base: dict[str, Any], holder: dict[str, Any]) -> float:
    """Сколько стоила оборванная попытка. Счётчик выходных токенов приходит только в конце ответа, поэтому
    оценка по времени (~80 токенов/с, не больше max_tokens) — лучше, чем считать её бесплатной."""
    from .llm.messages_api import estimate_cost

    stream = holder.get("stream")
    if stream is None or "started" not in holder:
        return 0.0
    try:
        inp = stream.current_message_snapshot.usage.input_tokens or 0
    except Exception:
        return 0.0  # ответ ещё не начался — денег не стоил
    out = min(int(base.get("max_tokens") or 0), int((time.monotonic() - holder["started"]) * 80))
    return estimate_cost(base["model"], type("U", (), {"input_tokens": inp, "output_tokens": out})())


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
    if not deck and getattr(after, "overflow", False) and not getattr(before, "overflow", False):
        return True  # доводка сделала страницу шире экрана
    if deck and getattr(after, "geometry", 0) > getattr(before, "geometry", 0):
        return True  # доводка добавила обрезанного, наложенного или перекрытого текста
    return deck and len(after.slides) < max(1, round(len(before.slides) * 0.7))


# Примерная цена одного заказа ($) по усилию — чтобы дневной бюджет учитывал и то, что ещё делается
EFFORT_COST = {"low": 0.2, "medium": 0.4, "high": 0.8, "xhigh": 1.5, "max": 2.5}


def expected_cost(settings: Any) -> float:
    cost = EFFORT_COST.get(settings.html_effort, 1.0)
    if settings.html_polish:
        cost += EFFORT_COST.get(settings.html_polish_effort or settings.html_effort, 1.0)
    return cost


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
