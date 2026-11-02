// 42+ Completely Unique, Real-World Website Templates with High-Fidelity Interactive Layouts
export const TEMPLATES = [
  {
    "id": "tech-saas",
    "category": "SaaS & AI",
    "name": "AI Copilot Landing",
    "desc": "Современный лендинг AI-ассистента с неоновыми карточками, живой статистикой и тарифами.",
    "tags": [
      "AI",
      "SaaS",
      "Dark"
    ],
    "previewGradient": "from-indigo-600 via-purple-600 to-pink-500",
    "previewSvg": "saas",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>VibeAI — Next-Gen AI Copilot</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n  <link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap\" rel=\"stylesheet\">\n  <style>body { font-family: 'Inter', sans-serif; }</style>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"border-b border-slate-800/80 backdrop-blur sticky top-0 z-50 px-6 py-4 flex items-center justify-between\">\n    <div class=\"flex items-center gap-2 font-bold text-xl tracking-tight text-white\">\n      <div class=\"w-8 h-8 rounded-lg bg-indigo-500 flex items-center justify-center text-white\"><i data-lucide=\"sparkles\" class=\"w-5 h-5\"></i></div>\n      VibeAI\n    </div>\n    <div class=\"hidden md:flex gap-6 text-sm text-slate-300\">\n      <a href=\"#features\" class=\"hover:text-white transition\">Возможности</a>\n      <a href=\"#pricing\" class=\"hover:text-white transition\">Цены</a>\n      <a href=\"#testimonials\" class=\"hover:text-white transition\">Отзывы</a>\n    </div>\n    <button class=\"bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-2 rounded-lg text-sm font-semibold transition shadow-lg shadow-indigo-500/25\">Попробовать</button>\n  </nav>\n\n  <header class=\"py-20 px-6 text-center max-w-4xl mx-auto\">\n    <span class=\"inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-950/80 border border-indigo-500/30 text-indigo-300 text-xs font-semibold mb-6\">\n      🚀 Вышла версия 3.0 с поддержкой gpt-oss-20b\n    </span>\n    <h1 class=\"text-4xl md:text-6xl font-extrabold tracking-tight mb-6 bg-gradient-to-r from-white via-slate-200 to-indigo-400 bg-clip-text text-transparent\">\n      Автоматизируйте рутину с умным AI-интеллектом\n    </h1>\n    <p class=\"text-base md:text-lg text-slate-400 mb-8 max-w-2xl mx-auto\">\n      Генерация кода, анализ документов и веб-дизайн прямо на вашем локальном компьютере с нулевой задержкой.\n    </p>\n    <div class=\"flex flex-col sm:flex-row justify-center gap-4\">\n      <button class=\"bg-white text-slate-950 font-bold px-8 py-3 rounded-xl hover:bg-slate-200 transition shadow-xl\">Начать работу</button>\n      <button class=\"border border-slate-800 bg-slate-900/60 hover:bg-slate-800 text-slate-300 font-medium px-8 py-3 rounded-xl transition flex items-center justify-center gap-2\">\n        <i data-lucide=\"play\" class=\"w-4 h-4\"></i> Смотреть демо\n      </button>\n    </div>\n  </header>\n\n  <section id=\"features\" class=\"py-12 px-6 max-w-6xl mx-auto grid md:grid-cols-3 gap-6\">\n    <div class=\"p-6 rounded-2xl bg-slate-900/40 border border-slate-800/80 hover:border-indigo-500/50 transition\">\n      <div class=\"w-12 h-12 rounded-xl bg-indigo-500/10 text-indigo-400 flex items-center justify-center mb-4\"><i data-lucide=\"cpu\" class=\"w-6 h-6\"></i></div>\n      <h3 class=\"text-lg font-bold mb-2\">Локальный инференс</h3>\n      <p class=\"text-sm text-slate-400\">Полная приватность данных. Модель работает в локальной памяти ПК.</p>\n    </div>\n    <div class=\"p-6 rounded-2xl bg-slate-900/40 border border-slate-800/80 hover:border-purple-500/50 transition\">\n      <div class=\"w-12 h-12 rounded-xl bg-purple-500/10 text-purple-400 flex items-center justify-center mb-4\"><i data-lucide=\"zap\" class=\"w-6 h-6\"></i></div>\n      <h3 class=\"text-lg font-bold mb-2\">Мгновенный отклик</h3>\n      <p class=\"text-sm text-slate-400\">MoE архитектура выдает до 40 токенов в секунду на вашей видеокарте.</p>\n    </div>\n    <div class=\"p-6 rounded-2xl bg-slate-900/40 border border-slate-800/80 hover:border-pink-500/50 transition\">\n      <div class=\"w-12 h-12 rounded-xl bg-pink-500/10 text-pink-400 flex items-center justify-center mb-4\"><i data-lucide=\"code\" class=\"w-6 h-6\"></i></div>\n      <h3 class=\"text-lg font-bold mb-2\">Live-генератор сайтов</h3>\n      <p class=\"text-sm text-slate-400\">Визуальный инспектор и реактивный рендеринг готовых HTML страниц на лету.</p>\n    </div>\n  </section>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "crypto-exchange",
    "category": "Fintech",
    "name": "Web3 DEX & Crypto Hub",
    "desc": "Футуристичный темный криптовалютный терминал с графиками, стаканом котировок и быстрым Swap.",
    "tags": [
      "Crypto",
      "Web3",
      "Finance"
    ],
    "previewGradient": "from-amber-500 via-orange-600 to-red-600",
    "previewSvg": "crypto",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>VibeDEX — Decentralized Trading</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#09080e] text-amber-50 min-h-screen\">\n  <header class=\"border-b border-amber-950/40 px-6 py-4 flex items-center justify-between\">\n    <div class=\"flex items-center gap-2 font-black text-xl text-amber-400\">\n      <i data-lucide=\"coins\" class=\"w-6 h-6\"></i> VibeDEX\n    </div>\n    <div class=\"flex gap-4 items-center\">\n      <span class=\"text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 px-3 py-1 rounded-full\">ETH: $3,450.20 (+4.8%)</span>\n      <button class=\"bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 font-bold px-4 py-2 rounded-lg text-sm shadow-lg shadow-amber-500/20\">Подключить кошелек</button>\n    </div>\n  </header>\n  <main class=\"max-w-6xl mx-auto p-6 grid lg:grid-cols-3 gap-6 mt-6\">\n    <div class=\"lg:col-span-2 bg-[#12101b] border border-amber-500/10 rounded-2xl p-6\">\n      <div class=\"flex justify-between items-center mb-6\">\n        <div>\n          <h2 class=\"text-2xl font-bold text-white\">BTC / USDT</h2>\n          <span class=\"text-3xl font-extrabold text-emerald-400\">$89,450.00</span>\n        </div>\n        <div class=\"flex gap-2\">\n          <button class=\"px-3 py-1 bg-amber-500/10 rounded text-xs text-amber-400 font-bold\">1H</button>\n          <button class=\"px-3 py-1 bg-white/5 rounded text-xs text-slate-400\">1D</button>\n          <button class=\"px-3 py-1 bg-white/5 rounded text-xs text-slate-400\">1W</button>\n        </div>\n      </div>\n      <div class=\"h-60 bg-gradient-to-t from-emerald-500/10 via-transparent to-transparent border border-emerald-500/20 rounded-xl flex items-center justify-center text-slate-400 text-sm\">\n        📈 Живой интерактивный график котировок (TradingView API)\n      </div>\n    </div>\n    <div class=\"bg-[#12101b] border border-amber-500/10 rounded-2xl p-6 flex flex-col justify-between\">\n      <h3 class=\"font-bold text-lg mb-4 text-white\">Быстрый обмен</h3>\n      <div class=\"space-y-4\">\n        <div class=\"bg-[#1a1727] p-3 rounded-xl border border-white/5\">\n          <label class=\"text-xs text-slate-400 block mb-1\">Отдаете</label>\n          <div class=\"flex justify-between font-bold text-xl\">\n            <input type=\"number\" value=\"1.5\" class=\"bg-transparent outline-none w-32 text-white\">\n            <span class=\"text-amber-400\">ETH</span>\n          </div>\n        </div>\n        <div class=\"bg-[#1a1727] p-3 rounded-xl border border-white/5\">\n          <label class=\"text-xs text-slate-400 block mb-1\">Получаете</label>\n          <div class=\"flex justify-between font-bold text-xl\">\n            <input type=\"number\" value=\"5175.3\" class=\"bg-transparent outline-none w-32 text-white\" readonly>\n            <span class=\"text-emerald-400\">USDT</span>\n          </div>\n        </div>\n      </div>\n      <button class=\"w-full mt-6 bg-gradient-to-r from-amber-400 to-orange-500 text-slate-950 font-extrabold py-3.5 rounded-xl shadow-lg shadow-amber-500/25 hover:opacity-95\">Совершить Swap</button>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "portfolio-minimal",
    "category": "Портфолио",
    "name": "Minimalist Designer Portfolio",
    "desc": "Чистый скандинавский минимализм для дизайнера, сетка кейсов, биография и контакты.",
    "tags": [
      "Minimal",
      "Design",
      "Portfolio"
    ],
    "previewGradient": "from-zinc-700 to-slate-900",
    "previewSvg": "portfolio",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>Алексей Смирнов — Senior Product Designer</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-50 text-stone-900 antialiased p-6 md:p-14 max-w-4xl mx-auto\">\n  <header class=\"mb-14\">\n    <div class=\"w-16 h-16 rounded-full bg-stone-300 mb-4 overflow-hidden flex items-center justify-center font-bold text-stone-700 text-xl\">АС</div>\n    <h1 class=\"text-3xl md:text-5xl font-black tracking-tight mb-2\">Алексей Смирнов</h1>\n    <p class=\"text-lg text-stone-600 font-serif italic mb-4\">Проектирую цифровые продукты, упрощающие сложные бизнес-процессы.</p>\n    <div class=\"flex gap-4 text-xs font-semibold uppercase tracking-wider text-stone-500\">\n      <a href=\"#\" class=\"underline hover:text-stone-900\">Почта</a>\n      <a href=\"#\" class=\"underline hover:text-stone-900\">Telegram</a>\n      <a href=\"#\" class=\"underline hover:text-stone-900\">Dribbble</a>\n    </div>\n  </header>\n  <section class=\"space-y-8 mb-14\">\n    <h2 class=\"text-xs uppercase tracking-widest font-bold text-stone-400 border-b pb-2\">Избранные проекты (2025–2026)</h2>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"group cursor-pointer\">\n        <div class=\"aspect-[4/3] bg-gradient-to-tr from-stone-300 to-stone-200 rounded-2xl mb-3 flex items-center justify-center text-stone-600 font-bold group-hover:scale-[1.02] transition\">\n          FinPay iOS App\n        </div>\n        <h3 class=\"font-bold text-base\">FinPay — Необанк нового поколения</h3>\n        <p class=\"text-stone-500 text-xs\">Редизайн мобильного приложения с 2M+ пользователей.</p>\n      </div>\n      <div class=\"group cursor-pointer\">\n        <div class=\"aspect-[4/3] bg-gradient-to-tr from-stone-400 to-stone-200 rounded-2xl mb-3 flex items-center justify-center text-stone-700 font-bold group-hover:scale-[1.02] transition\">\n          CloudPulse Analytics\n        </div>\n        <h3 class=\"font-bold text-base\">CloudPulse — B2B Аналитика</h3>\n        <p class=\"text-stone-500 text-xs\">Сложная система мониторинга кластеров серверов.</p>\n      </div>\n    </div>\n  </section>\n  <footer class=\"text-xs text-stone-400 pt-6 border-t flex justify-between\">\n    <span>© 2026 Алексей Смирнов</span>\n    <span class=\"text-emerald-600 font-bold\">● Доступен для новых контрактов</span>\n  </footer>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "ecommerce-sneakers",
    "category": "Интернет-магазин",
    "name": "Sneakers Hub — E-Commerce",
    "desc": "Каталог уличной обуви с корзиной, рейтингом, выбором размеров и яркими ценниками.",
    "tags": [
      "Shop",
      "Shoes",
      "Streetwear"
    ],
    "previewGradient": "from-rose-500 via-orange-500 to-amber-500",
    "previewSvg": "shop",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>KICKS — Streetwear Sneakers</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-950 text-neutral-100 min-h-screen\">\n  <nav class=\"border-b border-neutral-800 px-6 py-4 flex items-center justify-between sticky top-0 bg-neutral-950/80 backdrop-blur z-50\">\n    <div class=\"text-2xl font-black italic tracking-tighter text-white\">KICKS<span class=\"text-rose-500\">.</span></div>\n    <div class=\"hidden md:flex gap-6 text-xs uppercase tracking-wider font-bold\">\n      <a href=\"#\" class=\"text-rose-500\">Новинки</a>\n      <a href=\"#\" class=\"hover:text-rose-400\">Мужские</a>\n      <a href=\"#\" class=\"hover:text-rose-400\">Женские</a>\n      <a href=\"#\" class=\"hover:text-rose-400\">Sale 30%</a>\n    </div>\n    <div class=\"flex items-center gap-3\">\n      <button class=\"relative p-2 bg-neutral-900 rounded-full\"><i data-lucide=\"shopping-bag\" class=\"w-5 h-5\"></i><span class=\"absolute -top-1 -right-1 bg-rose-500 text-[10px] w-4 h-4 rounded-full flex items-center justify-center font-bold\">2</span></button>\n    </div>\n  </nav>\n  <main class=\"max-w-6xl mx-auto px-6 py-10\">\n    <div class=\"flex justify-between items-end mb-8\">\n      <div>\n        <span class=\"text-xs uppercase tracking-widest text-rose-500 font-bold\">Limited Drop</span>\n        <h1 class=\"text-3xl font-extrabold uppercase\">Коллекция Весна 2026</h1>\n      </div>\n      <div class=\"flex gap-2\">\n        <button class=\"px-3 py-1 bg-neutral-800 rounded-lg text-xs font-bold text-white\">Все</button>\n        <button class=\"px-3 py-1 bg-neutral-900 text-neutral-400 rounded-lg text-xs\">Nike</button>\n        <button class=\"px-3 py-1 bg-neutral-900 text-neutral-400 rounded-lg text-xs\">Yeezy</button>\n      </div>\n    </div>\n    <div class=\"grid sm:grid-cols-2 md:grid-cols-3 gap-6\">\n      <div class=\"bg-neutral-900 border border-neutral-800 rounded-2xl p-5 hover:border-rose-500/50 transition\">\n        <div class=\"h-44 bg-gradient-to-tr from-neutral-800 to-neutral-700 rounded-xl flex items-center justify-center mb-4 text-neutral-400 font-bold text-lg\">Air Vapor 2026</div>\n        <div class=\"flex justify-between items-start mb-2\">\n          <h3 class=\"font-bold text-base text-white\">Nike Air Retro High</h3>\n          <span class=\"text-rose-400 font-extrabold\">18 990 ₽</span>\n        </div>\n        <p class=\"text-xs text-neutral-400 mb-4\">Натуральная кожа, амортизация Air Sole.</p>\n        <button class=\"w-full bg-white hover:bg-rose-500 hover:text-white text-neutral-950 font-bold py-2 rounded-xl text-xs transition\">В корзину</button>\n      </div>\n      <div class=\"bg-neutral-900 border border-neutral-800 rounded-2xl p-5 hover:border-rose-500/50 transition\">\n        <div class=\"h-44 bg-gradient-to-tr from-rose-900/40 to-neutral-800 rounded-xl flex items-center justify-center mb-4 text-rose-300 font-bold text-lg\">Boost 350 Urban</div>\n        <div class=\"flex justify-between items-start mb-2\">\n          <h3 class=\"font-bold text-base text-white\">Yeezy Boost 350</h3>\n          <span class=\"text-rose-400 font-extrabold\">24 490 ₽</span>\n        </div>\n        <p class=\"text-xs text-neutral-400 mb-4\">Текстильный дышащий верх Primeknit.</p>\n        <button class=\"w-full bg-white hover:bg-rose-500 hover:text-white text-neutral-950 font-bold py-2 rounded-xl text-xs transition\">В корзину</button>\n      </div>\n      <div class=\"bg-neutral-900 border border-neutral-800 rounded-2xl p-5 hover:border-rose-500/50 transition\">\n        <div class=\"h-44 bg-gradient-to-tr from-stone-800 to-neutral-800 rounded-xl flex items-center justify-center mb-4 text-stone-300 font-bold text-lg\">NB 990v6</div>\n        <div class=\"flex justify-between items-start mb-2\">\n          <h3 class=\"font-bold text-base text-white\">New Balance 990v6</h3>\n          <span class=\"text-rose-400 font-extrabold\">21 200 ₽</span>\n        </div>\n        <p class=\"text-xs text-neutral-400 mb-4\">Премиальная замша, сделано в США.</p>\n        <button class=\"w-full bg-white hover:bg-rose-500 hover:text-white text-neutral-950 font-bold py-2 rounded-xl text-xs transition\">В корзину</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "restaurant-menu",
    "category": "Рестораны & Кафе",
    "name": "La Bella Vista — Ресторан",
    "desc": "Атмосферное меню ресторана авторской пасты и винной карты с бронированием столика.",
    "tags": [
      "Ресторан",
      "Еда",
      "Уют"
    ],
    "previewGradient": "from-emerald-700 to-teal-900",
    "previewSvg": "restaurant",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>La Bella Vista — Ristorante Italiano</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#0f1411] text-stone-100 font-serif min-h-screen\">\n  <header class=\"py-14 text-center border-b border-emerald-950/80\">\n    <span class=\"text-emerald-400 uppercase tracking-widest text-xs font-sans font-bold\">Основан в 1988 году</span>\n    <h1 class=\"text-4xl md:text-5xl font-bold mt-2 mb-3 text-amber-100\">La Bella Vista</h1>\n    <p class=\"text-stone-400 font-sans text-xs max-w-md mx-auto\">Аутентичная кухня Тосканы, свежая домашняя паста и дровяная печь.</p>\n  </header>\n  <main class=\"max-w-2xl mx-auto px-6 py-10 font-sans space-y-8\">\n    <div>\n      <h2 class=\"text-xl font-serif text-amber-200 border-b border-emerald-900/60 pb-2 mb-4\">Паста ручной работы</h2>\n      <div class=\"space-y-4\">\n        <div class=\"flex justify-between items-baseline border-b border-white/5 pb-2\">\n          <div><h4 class=\"font-bold text-sm text-white\">Тальятелле с белыми грибами</h4><p class=\"text-xs text-stone-400\">Сливочно-трюфельный соус, пармезан 24 месяца</p></div>\n          <span class=\"font-bold text-amber-400\">790 ₽</span>\n        </div>\n        <div class=\"flex justify-between items-baseline border-b border-white/5 pb-2\">\n          <div><h4 class=\"font-bold text-sm text-white\">Спагетти Карбонара Классика</h4><p class=\"text-xs text-stone-400\">Гуанчиале, желтки фермерских яиц, пекорино романо</p></div>\n          <span class=\"font-bold text-amber-400\">680 ₽</span>\n        </div>\n        <div class=\"flex justify-between items-baseline border-b border-white/5 pb-2\">\n          <div><h4 class=\"font-bold text-sm text-white\">Равиоли с рикоттой и шпинатом</h4><p class=\"text-xs text-stone-400\">Шалфейное сливочное масло, кедровые орешки</p></div>\n          <span class=\"font-bold text-amber-400\">720 ₽</span>\n        </div>\n      </div>\n    </div>\n    <div class=\"text-center pt-4\">\n      <button class=\"bg-emerald-600 hover:bg-emerald-500 text-white font-bold px-8 py-3 rounded-full text-xs transition shadow-lg shadow-emerald-700/30\">Забронировать столик онлайн</button>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "agency-creative",
    "category": "Агентства",
    "name": "Aura Studio — Креативное агентство",
    "desc": "Стильный брендинг, интерактивные шоурилы, манифест компании и сетка наград.",
    "tags": [
      "Агентство",
      "Дизайн",
      "Брендинг"
    ],
    "previewGradient": "from-blue-600 to-violet-800",
    "previewSvg": "agency",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>AURA — Digital Creative Agency</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-black text-white min-h-screen selection:bg-violet-500\">\n  <nav class=\"p-8 flex justify-between items-center max-w-6xl mx-auto\">\n    <div class=\"text-2xl font-black tracking-widest uppercase\">AURA<span class=\"text-violet-500\">®</span></div>\n    <button class=\"border border-white/30 rounded-full px-5 py-2 text-xs font-bold uppercase tracking-wider hover:bg-white hover:text-black transition\">Обсудить проект</button>\n  </nav>\n  <main class=\"max-w-6xl mx-auto px-8 py-16\">\n    <h1 class=\"text-5xl md:text-7xl font-black uppercase tracking-tighter leading-none mb-8\">\n      Создаем бренды,<br><span class=\"text-violet-400\">которые меняют</span> правила.\n    </h1>\n    <div class=\"grid md:grid-cols-3 gap-8 pt-12 border-t border-white/20\">\n      <div>\n        <span class=\"text-violet-400 font-mono text-sm\">01 / BRANDING</span>\n        <h3 class=\"text-xl font-bold mt-2 mb-2\">Айдентика и стиль</h3>\n        <p class=\"text-zinc-400 text-xs\">Логотипы, дизайн-системы, гайдлайны и упаковка продуктов.</p>\n      </div>\n      <div>\n        <span class=\"text-violet-400 font-mono text-sm\">02 / WEB & 3D</span>\n        <h3 class=\"text-xl font-bold mt-2 mb-2\">Сайты со смыслом</h3>\n        <p class=\"text-zinc-400 text-xs\">Кастомные WebGL решения, анимации и конверсионный UX/UI.</p>\n      </div>\n      <div>\n        <span class=\"text-violet-400 font-mono text-sm\">03 / MOTION</span>\n        <h3 class=\"text-xl font-bold mt-2 mb-2\">Моушн & Видео</h3>\n        <p class=\"text-zinc-400 text-xs\">Рекламные ролики, 3D анимация и интерактивные презентации.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "cyberpunk-game",
    "category": "Гейминг",
    "name": "NEON 2088 — Cyberpunk Hub",
    "desc": "Неоновый геймерский портал с неоновыми кнопками, HUD-панелями и рейтингом игроков.",
    "tags": [
      "Гейминг",
      "Киберпанк",
      "Neon"
    ],
    "previewGradient": "from-yellow-400 via-pink-500 to-purple-600",
    "previewSvg": "game",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>NEON 2088 — Cyberpunk Tournament</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#050508] text-pink-50 min-h-screen font-mono\">\n  <div class=\"border-b border-pink-500/30 p-4 flex justify-between items-center bg-black/60 backdrop-blur\">\n    <div class=\"text-yellow-400 font-black tracking-widest text-lg flex items-center gap-2\">\n      <i data-lucide=\"zap\" class=\"w-5 h-5 text-pink-500\"></i> [NEON_GRID_v4]\n    </div>\n    <div class=\"flex items-center gap-4 text-xs\">\n      <span class=\"text-emerald-400\">SERVER: ONLINE (4,821 PLAYERS)</span>\n      <button class=\"bg-yellow-400 text-black px-4 py-1.5 font-bold uppercase hover:bg-pink-500 hover:text-white transition\">CONNECT HUD</button>\n    </div>\n  </div>\n  <main class=\"max-w-5xl mx-auto p-6 py-12\">\n    <div class=\"border-2 border-yellow-400 p-8 relative bg-black/80 shadow-[0_0_30px_rgba(234,179,8,0.2)]\">\n      <div class=\"absolute -top-3 left-6 bg-black px-2 text-yellow-400 text-xs font-bold tracking-widest\">TOURNAMENT #88</div>\n      <h1 class=\"text-4xl md:text-5xl font-black text-transparent bg-clip-text bg-gradient-to-r from-yellow-400 via-pink-500 to-cyan-400 uppercase tracking-wider mb-4\">\n        КИБЕР-ТУРНИР 2088\n      </h1>\n      <p class=\"text-zinc-400 text-sm mb-6 max-w-xl\">\n        Призовой фонд: <span class=\"text-yellow-400 font-bold\">$250,000 CYBER-CREDITS</span>. Битва 64 сильнейших кланов за контроль над Неоновым Сектором 9.\n      </p>\n      <div class=\"flex gap-4\">\n        <button class=\"bg-pink-600 text-white font-bold px-6 py-3 uppercase text-xs tracking-widest hover:bg-pink-500 shadow-[0_0_15px_rgba(236,72,153,0.5)]\">Подать заявку клана</button>\n        <button class=\"border border-cyan-400 text-cyan-400 font-bold px-6 py-3 uppercase text-xs tracking-widest hover:bg-cyan-400/20\">Сетка боев</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "fitness-coach",
    "category": "Спорт & Здоровье",
    "name": "IronFit — Персональный тренер",
    "desc": "Энергичный спортивный лендинг с программами сушки/набора, калькулятором калорий и записью.",
    "tags": [
      "Фитнес",
      "Спорт",
      "Здоровье"
    ],
    "previewGradient": "from-red-600 to-orange-700",
    "previewSvg": "fit",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>IronFit — Достигай максимума</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-zinc-950 text-white min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center\">\n    <div class=\"text-2xl font-black italic text-red-500 flex items-center gap-2\"><i data-lucide=\"flame\" class=\"w-6 h-6\"></i> IRONFIT</div>\n    <button class=\"bg-red-600 hover:bg-red-500 text-white font-bold px-5 py-2 rounded-xl text-xs uppercase tracking-wider transition\">Пробная тренировка</button>\n  </nav>\n  <main class=\"max-w-5xl mx-auto px-6 py-12\">\n    <div class=\"grid md:grid-cols-2 gap-10 items-center\">\n      <div>\n        <span class=\"text-xs font-bold uppercase tracking-widest text-red-500\">Авторская методика</span>\n        <h1 class=\"text-4xl md:text-5xl font-black uppercase mt-2 mb-4 leading-tight\">Твое тело готово к трансформации</h1>\n        <p class=\"text-zinc-400 text-sm mb-6\">Индивидуальный план тренировок и питания под контролем мастера спорта. Результат через 30 дней или возврат денег.</p>\n        <div class=\"flex gap-4\">\n          <button class=\"bg-red-600 hover:bg-red-500 text-white font-bold px-6 py-3 rounded-xl text-xs uppercase tracking-wider shadow-lg shadow-red-600/30\">Выбрать программу</button>\n        </div>\n      </div>\n      <div class=\"bg-zinc-900 border border-zinc-800 rounded-3xl p-6 space-y-4\">\n        <h3 class=\"font-bold text-lg text-white\">Программы тренировок</h3>\n        <div class=\"p-4 bg-zinc-950 rounded-xl border border-zinc-800 flex justify-between items-center\">\n          <div><div class=\"font-bold text-sm\">Сжигание жира & Рельеф</div><div class=\"text-xs text-zinc-500\">12 недель / 3 раза в неделю</div></div>\n          <span class=\"text-red-400 font-bold\">4 900 ₽</span>\n        </div>\n        <div class=\"p-4 bg-zinc-950 rounded-xl border border-zinc-800 flex justify-between items-center\">\n          <div><div class=\"font-bold text-sm\">Набор сухой массы</div><div class=\"text-xs text-zinc-500\">16 недель / силовая база</div></div>\n          <span class=\"text-red-400 font-bold\">5 900 ₽</span>\n        </div>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "mobile-app-landing",
    "category": "Мобильные приложения",
    "name": "PocketTask — App Showcase",
    "desc": "Презентация трекера задач с мокапом смартфона, кнопками App Store и фичами.",
    "tags": [
      "App",
      "Mobile",
      "Productivity"
    ],
    "previewGradient": "from-cyan-500 to-blue-600",
    "previewSvg": "mobile",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>PocketTask — Управляй временем</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-900 text-slate-100 min-h-screen\">\n  <header class=\"max-w-5xl mx-auto p-6 flex justify-between items-center\">\n    <div class=\"text-xl font-bold flex items-center gap-2\"><i data-lucide=\"check-circle-2\" class=\"w-6 h-6 text-cyan-400\"></i> PocketTask</div>\n    <span class=\"text-xs bg-cyan-500/10 text-cyan-400 px-3 py-1 rounded-full border border-cyan-500/20\">Рейтинг 4.9 ★ в App Store</span>\n  </header>\n  <main class=\"max-w-5xl mx-auto px-6 py-16 grid md:grid-cols-2 gap-12 items-center\">\n    <div>\n      <h1 class=\"text-4xl md:text-5xl font-extrabold tracking-tight mb-4\">Все дела в полном порядке за пару свайпов</h1>\n      <p class=\"text-slate-400 text-sm mb-8\">Интеллектуальная сортировка задач по методу матриц Эйзенхауэра и синхронизация между всеми вашими устройствами.</p>\n      <div class=\"flex gap-4\">\n        <button class=\"bg-white text-slate-950 font-bold px-6 py-3 rounded-2xl flex items-center gap-2 hover:bg-slate-200 transition text-xs\"><i data-lucide=\"apple\" class=\"w-4 h-4\"></i> App Store</button>\n        <button class=\"bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-bold px-6 py-3 rounded-2xl flex items-center gap-2 transition text-xs\"><i data-lucide=\"play\" class=\"w-4 h-4\"></i> Google Play</button>\n      </div>\n    </div>\n    <div class=\"flex justify-center\">\n      <div class=\"w-64 h-[440px] bg-slate-950 border-4 border-slate-700 rounded-[40px] p-4 shadow-2xl flex flex-col justify-between\">\n        <div class=\"w-20 h-4 bg-slate-800 rounded-full mx-auto mb-4\"></div>\n        <div class=\"space-y-3\">\n          <div class=\"p-3 bg-cyan-950/60 border border-cyan-500/30 rounded-xl text-xs\"><div class=\"font-bold text-cyan-300\">Презентация клиенту</div><div class=\"text-[10px] text-slate-400\">Сегодня в 14:00</div></div>\n          <div class=\"p-3 bg-slate-900 border border-slate-800 rounded-xl text-xs\"><div class=\"font-bold text-white\">Тренировка ног</div><div class=\"text-[10px] text-slate-400\">Завтра в 09:00</div></div>\n        </div>\n        <div class=\"text-center text-[10px] text-slate-500\">Синхронизировано</div>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "real-estate",
    "category": "Недвижимость",
    "name": "PrimeEstate — Элитное жилье",
    "desc": "Каталог апартаментов бизнес-класса с фильтрами по локации, комнатам и стоимости.",
    "tags": [
      "Недвижимость",
      "Luxury",
      "Архитектура"
    ],
    "previewGradient": "from-amber-600 to-stone-800",
    "previewSvg": "house",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>PrimeEstate — Недвижимость премиум-класса</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-900 text-stone-100 min-h-screen\">\n  <nav class=\"border-b border-stone-800 p-6 flex justify-between items-center max-w-6xl mx-auto\">\n    <div class=\"text-xl font-bold tracking-widest text-amber-300 uppercase\">PRIME•ESTATE</div>\n    <div class=\"text-xs text-stone-400\">+7 (495) 777-00-11 • Консьерж-сервис 24/7</div>\n  </nav>\n  <main class=\"max-w-6xl mx-auto p-6 py-10\">\n    <h1 class=\"text-3xl md:text-4xl font-light tracking-wide mb-6\">Коллекция видовых резиденций</h1>\n    <div class=\"grid md:grid-cols-2 gap-8\">\n      <div class=\"bg-stone-800/60 rounded-2xl overflow-hidden border border-stone-700\">\n        <div class=\"h-56 bg-stone-700 flex items-center justify-center text-stone-400 font-bold\">[Фото пентхауса с террасой]</div>\n        <div class=\"p-6\">\n          <span class=\"text-amber-400 text-xs uppercase font-bold tracking-wider\">Хамовники • 180 м²</span>\n          <h3 class=\"text-xl font-bold mt-1 mb-2\">Пентхаус «Golden Mile»</h3>\n          <p class=\"text-xs text-stone-400 mb-4\">Панорамный вид на набережную, потолки 4.2 метра, 3 спальни, закрытый паркинг.</p>\n          <div class=\"flex justify-between items-center pt-4 border-t border-stone-700\">\n            <span class=\"text-xl font-bold text-amber-300\">145 000 000 ₽</span>\n            <button class=\"bg-amber-400 text-stone-950 font-bold px-4 py-2 rounded-xl text-xs\">Записаться на показ</button>\n          </div>\n        </div>\n      </div>\n      <div class=\"bg-stone-800/60 rounded-2xl overflow-hidden border border-stone-700\">\n        <div class=\"h-56 bg-stone-700 flex items-center justify-center text-stone-400 font-bold\">[Фото резиденции в парке]</div>\n        <div class=\"p-6\">\n          <span class=\"text-amber-400 text-xs uppercase font-bold tracking-wider\">Пресня • 125 м²</span>\n          <h3 class=\"text-xl font-bold mt-1 mb-2\">Апартаменты «Sky Garden»</h3>\n          <p class=\"text-xs text-stone-400 mb-4\">Собственный сад на крыше, консьерж, отделка из натурального мрамора и дуба.</p>\n          <div class=\"flex justify-between items-center pt-4 border-t border-stone-700\">\n            <span class=\"text-xl font-bold text-amber-300\">89 500 000 ₽</span>\n            <button class=\"bg-amber-400 text-stone-950 font-bold px-4 py-2 rounded-xl text-xs\">Записаться на показ</button>\n          </div>\n        </div>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "medical-clinic",
    "category": "Медицина",
    "name": "MedClinic — Семейная клиника",
    "desc": "Медицинский центр с записью к врачу, списком специалистов и прайсом чекапов.",
    "tags": [
      "Медицина",
      "Здоровье",
      "Клиника"
    ],
    "previewGradient": "from-teal-500 to-emerald-700",
    "previewSvg": "med",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>МедКлиник — Семейная медицина</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-50 text-slate-800 min-h-screen\">\n  <header class=\"bg-white border-b border-slate-200 px-6 py-4 flex justify-between items-center max-w-6xl mx-auto\">\n    <div class=\"flex items-center gap-2 font-bold text-xl text-teal-700\"><i data-lucide=\"cross\" class=\"w-6 h-6 text-teal-600\"></i> МедКлиник</div>\n    <div class=\"flex gap-4 items-center\">\n      <span class=\"text-xs text-slate-500 hidden sm:inline\">Работаем ежедневно 8:00 - 21:00</span>\n      <button class=\"bg-teal-600 hover:bg-teal-700 text-white font-bold px-4 py-2 rounded-xl text-xs\">Запись к врачу</button>\n    </div>\n  </header>\n  <main class=\"max-w-6xl mx-auto p-6 py-12\">\n    <div class=\"bg-gradient-to-r from-teal-700 to-emerald-800 text-white rounded-3xl p-8 mb-12 flex flex-col md:flex-row justify-between items-center gap-6\">\n      <div>\n        <h1 class=\"text-3xl font-extrabold mb-2\">Комплексный Check-Up 2026</h1>\n        <p class=\"text-teal-100 text-sm max-w-md\">Полная диагностика здоровья всего организма за 1 день со скидкой 20%.</p>\n      </div>\n      <button class=\"bg-white text-teal-900 font-bold px-6 py-3 rounded-2xl text-xs shadow-lg\">Записаться на чекап</button>\n    </div>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-6 rounded-2xl border border-slate-200 shadow-sm\">\n        <i data-lucide=\"heart-pulse\" class=\"w-8 h-8 text-teal-600 mb-3\"></i>\n        <h3 class=\"font-bold text-base mb-1\">Кардиология</h3>\n        <p class=\"text-xs text-slate-500\">УЗИ сердца, ЭКГ с расшифровкой и консультация кардиолога высшей категории.</p>\n      </div>\n      <div class=\"bg-white p-6 rounded-2xl border border-slate-200 shadow-sm\">\n        <i data-lucide=\"smile\" class=\"w-8 h-8 text-teal-600 mb-3\"></i>\n        <h3 class=\"font-bold text-base mb-1\">Стоматология</h3>\n        <p class=\"text-xs text-slate-500\">Лечение без боли, 3D-томография челюсти и бережная ультразвуковая чистка.</p>\n      </div>\n      <div class=\"bg-white p-6 rounded-2xl border border-slate-200 shadow-sm\">\n        <i data-lucide=\"activity\" class=\"w-8 h-8 text-teal-600 mb-3\"></i>\n        <h3 class=\"font-bold text-base mb-1\">Лаборатория</h3>\n        <p class=\"text-xs text-slate-500\">Более 1500 анализов. Готовность результатов за 24 часа в мобильном приложении.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "online-school",
    "category": "Образование",
    "name": "CodeCamp — Онлайн-курсы IT",
    "desc": "Платформа обучения программированию с программой курса, наставниками и гарантией оффера.",
    "tags": [
      "Образование",
      "IT",
      "Курсы"
    ],
    "previewGradient": "from-indigo-700 to-sky-600",
    "previewSvg": "edu",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>CodeCamp — Твой старт в IT</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-black text-indigo-400 flex items-center gap-2\"><i data-lucide=\"terminal\" class=\"w-6 h-6\"></i> CODECAMP</div>\n    <button class=\"bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Войти в кабинет</button>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-12\">\n    <div class=\"text-center max-w-2xl mx-auto mb-12\">\n      <span class=\"text-xs font-bold text-indigo-400 bg-indigo-950/80 px-3 py-1 rounded-full border border-indigo-500/30\">Трудоустройство или возврат денег</span>\n      <h1 class=\"text-4xl font-extrabold mt-4 mb-3\">Стань Fullstack-разработчиком с нуля</h1>\n      <p class=\"text-slate-400 text-sm\">Практика на реальных проектах, код-ревью от сеньоров из BigTech и помощь с резюме.</p>\n    </div>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"bg-slate-900 border border-slate-800 p-6 rounded-2xl\">\n        <span class=\"text-xs text-indigo-400 font-bold uppercase\">9 месяцев • 4 проекта в портфолио</span>\n        <h3 class=\"text-xl font-bold mt-1 mb-2\">Python & AI Инженер</h3>\n        <p class=\"text-xs text-slate-400 mb-4\">FastAPI, PostgreSQL, PyTorch, интеграция LLM-моделей и деплой в облако.</p>\n        <button class=\"w-full bg-white text-slate-950 font-bold py-2.5 rounded-xl text-xs hover:bg-slate-200\">Смотреть программу</button>\n      </div>\n      <div class=\"bg-slate-900 border border-slate-800 p-6 rounded-2xl\">\n        <span class=\"text-xs text-sky-400 font-bold uppercase\">7 месяцев • 5 проектов в портфолио</span>\n        <h3 class=\"text-xl font-bold mt-1 mb-2\">Frontend React & Vue Pro</h3>\n        <p class=\"text-xs text-slate-400 mb-4\">TypeScript, Next.js, Redux Toolkit, адаптивная верстка и интеграция с REST/GraphQL.</p>\n        <button class=\"w-full bg-white text-slate-950 font-bold py-2.5 rounded-xl text-xs hover:bg-slate-200\">Смотреть программу</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "barbershop",
    "category": "Услуги",
    "name": "Chop & Blade — Барбершоп",
    "desc": "Брутальный темный сайт мужской парикмахерской с записью к мастеру и ценами.",
    "tags": [
      "Барбершоп",
      "Стиль",
      "Услуги"
    ],
    "previewGradient": "from-neutral-800 to-neutral-950",
    "previewSvg": "barber",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>Chop & Blade — Мужской барбершоп</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-950 text-neutral-100 min-h-screen\">\n  <header class=\"p-6 text-center border-b border-neutral-800\">\n    <div class=\"text-2xl font-black tracking-widest text-amber-500 uppercase\">CHOP & BLADE</div>\n    <div class=\"text-[10px] text-neutral-500 tracking-widest uppercase mt-1\">EST. 2017 • TRADITIONAL BARBERSHOP</div>\n  </header>\n  <main class=\"max-w-2xl mx-auto p-6 py-10 space-y-6\">\n    <div class=\"text-center\">\n      <h1 class=\"text-3xl font-extrabold uppercase\">Мужские стрижки и бритье</h1>\n      <p class=\"text-xs text-neutral-400 mt-2\">Атмосфера хорошего виски, джаза и идеального опасного лезвия.</p>\n    </div>\n    <div class=\"bg-neutral-900 border border-neutral-800 rounded-2xl p-6 space-y-4\">\n      <div class=\"flex justify-between items-center border-b border-neutral-800 pb-3\">\n        <div><div class=\"font-bold text-sm\">Классическая мужская стрижка</div><div class=\"text-xs text-neutral-500\">Мытье головы, укладка, стайлинг</div></div>\n        <span class=\"font-bold text-amber-400\">2 200 ₽</span>\n      </div>\n      <div class=\"flex justify-between items-center border-b border-neutral-800 pb-3\">\n        <div><div class=\"font-bold text-sm\">Моделирование бороды</div><div class=\"text-xs text-neutral-500\">Распаривание горячим полотенцем, масла</div></div>\n        <span class=\"font-bold text-amber-400\">1 600 ₽</span>\n      </div>\n      <div class=\"flex justify-between items-center\">\n        <div><div class=\"font-bold text-sm\">Комплекс «Шеф»</div><div class=\"text-xs text-neutral-500\">Стрижка + борода + уход за кожей лица</div></div>\n        <span class=\"font-bold text-amber-400\">3 400 ₽</span>\n      </div>\n    </div>\n    <button class=\"w-full bg-amber-500 hover:bg-amber-400 text-neutral-950 font-black uppercase tracking-wider py-3.5 rounded-xl text-xs transition\">Записаться к барберу онлайн</button>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "coffee-shop",
    "category": "Кафе",
    "name": "Roast & Bean — Спешелти кофе",
    "desc": "Уютная кофейня с картой зерна свежей обжарки, десертами и предзаказом.",
    "tags": [
      "Кофе",
      "Кафе",
      "Уют"
    ],
    "previewGradient": "from-amber-800 to-amber-950",
    "previewSvg": "coffee",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>Roast & Bean — Кофе свежей обжарки</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#1c1612] text-amber-50 min-h-screen\">\n  <nav class=\"max-w-4xl mx-auto p-6 flex justify-between items-center border-b border-amber-900/40\">\n    <div class=\"text-lg font-bold flex items-center gap-2 text-amber-300\"><i data-lucide=\"coffee\" class=\"w-5 h-5\"></i> ROAST & BEAN</div>\n    <div class=\"text-xs text-amber-200/60\">Открыты с 07:30 до 22:00</div>\n  </nav>\n  <main class=\"max-w-3xl mx-auto p-6 py-12\">\n    <div class=\"text-center mb-10\">\n      <h1 class=\"text-3xl font-serif font-bold text-amber-100\">Кофе, который вдохновляет</h1>\n      <p class=\"text-xs text-amber-300/70 mt-2\">100% арабика спешелти класса из Эфиопии, Колумбии и Кении.</p>\n    </div>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"bg-[#2a211b] border border-amber-900/30 rounded-2xl p-5\">\n        <h3 class=\"font-bold text-amber-200 mb-3 border-b border-amber-900/40 pb-1\">Черный кофе</h3>\n        <div class=\"space-y-3 text-xs\">\n          <div class=\"flex justify-between\"><span>Фильтр-кофе Эфиопия Иргачеффе</span><span class=\"font-bold text-amber-400\">250 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Эспрессо двойной</span><span class=\"font-bold text-amber-400\">190 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Воронка V60 / Аэропресс</span><span class=\"font-bold text-amber-400\">320 ₽</span></div>\n        </div>\n      </div>\n      <div class=\"bg-[#2a211b] border border-amber-900/30 rounded-2xl p-5\">\n        <h3 class=\"font-bold text-amber-200 mb-3 border-b border-amber-900/40 pb-1\">С молоком</h3>\n        <div class=\"space-y-3 text-xs\">\n          <div class=\"flex justify-between\"><span>Флэт Уайт на кокосовом</span><span class=\"font-bold text-amber-400\">310 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Капучино с корицей</span><span class=\"font-bold text-amber-400\">270 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Раф лавандовый</span><span class=\"font-bold text-amber-400\">340 ₽</span></div>\n        </div>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "lawyer-firm",
    "category": "Юриспруденция",
    "name": "LexAdvocate — Юридическая защита",
    "desc": "Солидный сайт адвокатского бюро с практиками, консультацией и гарантиями конфиденциальности.",
    "tags": [
      "Юрист",
      "Бизнес",
      "Право"
    ],
    "previewGradient": "from-slate-700 to-slate-900",
    "previewSvg": "law",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>LexAdvocate — Адвокатское бюро</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"border-b border-slate-800 p-6 flex justify-between items-center max-w-6xl mx-auto\">\n    <div class=\"text-xl font-serif font-bold tracking-widest text-slate-200 flex items-center gap-2\"><i data-lucide=\"scale\" class=\"w-5 h-5 text-amber-400\"></i> LEX ADVOCATE</div>\n    <button class=\"bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold px-4 py-2 rounded-lg text-xs\">Консультация</button>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-serif font-bold mb-4\">Надежная защита ваших интересов в суде и бизнесе</h1>\n    <p class=\"text-slate-400 text-sm max-w-2xl mb-8\">20 лет успешной практики. 94% выигранных дел в арбитражных и гражданских спорах.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-xl\">\n        <h3 class=\"font-bold text-white mb-2\">Корпоративное право</h3>\n        <p class=\"text-xs text-slate-400\">Сопровождение сделок M&A, защита активов и налоговый консалтинг.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-xl\">\n        <h3 class=\"font-bold text-white mb-2\">Арбитражные споры</h3>\n        <p class=\"text-xs text-slate-400\">Взыскание задолженностей, споры по договорам поставки и строительному подряду.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-xl\">\n        <h3 class=\"font-bold text-white mb-2\">Интеллектуальная собственность</h3>\n        <p class=\"text-xs text-slate-400\">Регистрация товарных знаков, патентные споры и защита софта/IT прав.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "event-festival",
    "category": "События",
    "name": "ElectroWave 2026 Festival",
    "desc": "Фестиваль электронной музыки с расписанием хедлайнеров, билетами и схемой сцен.",
    "tags": [
      "Фестиваль",
      "Музыка",
      "Event"
    ],
    "previewGradient": "from-fuchsia-600 to-purple-900",
    "previewSvg": "event",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>ElectroWave 2026 — Open Air Festival</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-black text-fuchsia-50 min-h-screen\">\n  <div class=\"p-6 text-center border-b border-fuchsia-900/50\">\n    <span class=\"text-xs font-mono uppercase tracking-widest text-fuchsia-400\">18-20 ИЮЛЯ 2026 • СОЧИ</span>\n    <h1 class=\"text-4xl md:text-6xl font-black uppercase tracking-tighter mt-1 text-transparent bg-clip-text bg-gradient-to-r from-fuchsia-400 via-pink-400 to-cyan-400\">ELECTROWAVE</h1>\n  </div>\n  <main class=\"max-w-4xl mx-auto p-6 py-10 space-y-8\">\n    <div class=\"grid md:grid-cols-3 gap-4 text-center\">\n      <div class=\"p-4 bg-fuchsia-950/40 border border-fuchsia-800/40 rounded-2xl\"><div class=\"text-2xl font-black text-white\">4 СЦЕНЫ</div><div class=\"text-xs text-zinc-400\">Main, Techno, Bass, Chill</div></div>\n      <div class=\"p-4 bg-fuchsia-950/40 border border-fuchsia-800/40 rounded-2xl\"><div class=\"text-2xl font-black text-white\">40+ DJ'S</div><div class=\"text-xs text-zinc-400\">Мировые хедлайнеры</div></div>\n      <div class=\"p-4 bg-fuchsia-950/40 border border-fuchsia-800/40 rounded-2xl\"><div class=\"text-2xl font-black text-white\">72 ЧАСА</div><div class=\"text-xs text-zinc-400\">Нон-стоп звука и света</div></div>\n    </div>\n    <div class=\"bg-gradient-to-r from-purple-900/60 to-fuchsia-900/60 border border-fuchsia-500/30 p-6 rounded-3xl flex flex-col sm:flex-row justify-between items-center gap-4\">\n      <div>\n        <h3 class=\"text-xl font-bold text-white\">Билет Early Bird</h3>\n        <p class=\"text-xs text-fuchsia-200\">Вход на все 3 дня фестиваля + кемпинг зона.</p>\n      </div>\n      <button class=\"bg-fuchsia-500 hover:bg-fuchsia-400 text-black font-black px-6 py-3 rounded-2xl text-xs uppercase tracking-wider transition shadow-lg shadow-fuchsia-500/30\">Купить за 4 500 ₽</button>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "car-service",
    "category": "Авто",
    "name": "TurboAuto — Детейлинг & Сервис",
    "desc": "Премиальный автосервис: бронепленка, полировка кузова, диагностика и замена масла.",
    "tags": [
      "Авто",
      "Детейлинг",
      "Сервис"
    ],
    "previewGradient": "from-zinc-900 to-red-800",
    "previewSvg": "car",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>TurboAuto — Премиальный детейлинг</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-zinc-950 text-zinc-100 min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-zinc-800\">\n    <div class=\"text-xl font-black italic tracking-wider text-red-500 flex items-center gap-2\"><i data-lucide=\"wrench\" class=\"w-5 h-5\"></i> TURBOAUTO</div>\n    <button class=\"bg-red-600 hover:bg-red-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Запись на детейлинг</button>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black uppercase mb-4\">Безупречный блеск и защита вашего автомобиля</h1>\n    <p class=\"text-zinc-400 text-sm max-w-xl mb-8\">Используем немецкую автохимию Koch-Chemie и полиуретановые пленки SunTek с гарантией 5 лет.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-6 bg-zinc-900 border border-zinc-800 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-2\">Оклейка полиуретаном</h3>\n        <p class=\"text-xs text-zinc-400 mb-4\">Полная защита кузова от гравия, сколов и реагентов.</p>\n        <span class=\"text-red-400 font-bold text-sm\">от 85 000 ₽</span>\n      </div>\n      <div class=\"p-6 bg-zinc-900 border border-zinc-800 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-2\">Керамика 9H Pro</h3>\n        <p class=\"text-xs text-zinc-400 mb-4\">Глубокий зеркальный глянец и мощный гидрофобный эффект.</p>\n        <span class=\"text-red-400 font-bold text-sm\">от 28 000 ₽</span>\n      </div>\n      <div class=\"p-6 bg-zinc-900 border border-zinc-800 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-2\">Химчистка салона</h3>\n        <p class=\"text-xs text-zinc-400 mb-4\">Разборная чистка, озонирование и консервация кожи.</p>\n        <span class=\"text-red-400 font-bold text-sm\">от 14 000 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "photographer",
    "category": "Портфолио",
    "name": "Elena Grey — Свадебный фотограф",
    "desc": "Нежное светлое портфолио с эстетичной галереей живых кадров и отзывами молодоженов.",
    "tags": [
      "Фотограф",
      "Свадьба",
      "Портфолио"
    ],
    "previewGradient": "from-stone-600 to-stone-900",
    "previewSvg": "photo",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>Elena Grey — Свадебная фотография</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#faf8f5] text-stone-900 min-h-screen font-serif\">\n  <header class=\"p-10 text-center\">\n    <h1 class=\"text-3xl font-light tracking-widest uppercase\">ELENA GREY</h1>\n    <p class=\"text-xs font-sans text-stone-500 uppercase tracking-widest mt-1\">Wedding & Editorial Photography</p>\n  </header>\n  <main class=\"max-w-4xl mx-auto px-6 pb-12 font-sans\">\n    <p class=\"text-center font-serif text-lg italic text-stone-600 max-w-lg mx-auto mb-10\">«Сохраняю искренние эмоции, теплоту взглядов и легкие моменты, которые останутся с вами навсегда»</p>\n    <div class=\"grid grid-cols-2 md:grid-cols-3 gap-4 mb-10\">\n      <div class=\"aspect-[3/4] bg-stone-200 rounded-xl flex items-center justify-center text-stone-400 text-xs\">[Серия: Утро невесты]</div>\n      <div class=\"aspect-[3/4] bg-stone-300 rounded-xl flex items-center justify-center text-stone-500 text-xs\">[Серия: Прогулка в саду]</div>\n      <div class=\"aspect-[3/4] bg-stone-200 rounded-xl flex items-center justify-center text-stone-400 text-xs\">[Серия: Церемония на закате]</div>\n    </div>\n    <div class=\"text-center\">\n      <button class=\"bg-stone-900 hover:bg-stone-800 text-white font-medium px-8 py-3 rounded-full text-xs uppercase tracking-wider transition\">Смотреть серии & Узнать дату</button>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "travel-agency",
    "category": "Туризм",
    "name": "WildVoyage — Авторские туры",
    "desc": "Приключенческие экспедиции на Алтай, Камчатку и Байкал в мини-группах.",
    "tags": [
      "Туризм",
      "Путешествия",
      "Горы"
    ],
    "previewGradient": "from-emerald-600 to-teal-800",
    "previewSvg": "travel",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>WildVoyage — Экспедиции и приключения</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-950 text-stone-100 min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-stone-800\">\n    <div class=\"text-xl font-bold tracking-tight text-emerald-400 flex items-center gap-2\"><i data-lucide=\"compass\" class=\"w-6 h-6\"></i> WILDVOYAGE</div>\n    <button class=\"bg-emerald-600 hover:bg-emerald-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Календарь туров 2026</button>\n  </nav>\n  <main class=\"max-w-6xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-extrabold mb-4\">Туда, где заканчиваются дороги</h1>\n    <p class=\"text-stone-400 text-sm max-w-xl mb-8\">Авторские туры по диким уголкам планеты с опытными гидами-альпинистами и комфортными глэмпингами.</p>\n    <div class=\"grid md:grid-cols-2 gap-8\">\n      <div class=\"bg-stone-900 border border-stone-800 rounded-3xl overflow-hidden p-6 flex flex-col justify-between\">\n        <div>\n          <span class=\"text-xs font-bold uppercase text-emerald-400\">7 дней • Сложность: средняя</span>\n          <h3 class=\"text-2xl font-bold mt-1 mb-2 text-white\">Камчатка: Вулканы и Тихий океан</h3>\n          <p class=\"text-xs text-stone-400\">Восхождение на вулкан Горелый, сёрфинг на Халактырском пляже и горячие источники.</p>\n        </div>\n        <div class=\"flex justify-between items-center pt-6 border-t border-stone-800 mt-6\">\n          <span class=\"text-xl font-bold text-emerald-400\">92 000 ₽</span>\n          <button class=\"bg-white text-stone-950 font-bold px-4 py-2 rounded-xl text-xs\">Забронировать место</button>\n        </div>\n      </div>\n      <div class=\"bg-stone-900 border border-stone-800 rounded-3xl overflow-hidden p-6 flex flex-col justify-between\">\n        <div>\n          <span class=\"text-xs font-bold uppercase text-emerald-400\">6 дней • Сложность: комфорт</span>\n          <h3 class=\"text-2xl font-bold mt-1 mb-2 text-white\">Ледовый Байкал: Прозрачный космос</h3>\n          <p class=\"text-xs text-stone-400\">Катание на коньках по зеркальному льду, гроты острова Ольхон и сибирская баня.</p>\n        </div>\n        <div class=\"flex justify-between items-center pt-6 border-t border-stone-800 mt-6\">\n          <span class=\"text-xl font-bold text-emerald-400\">78 000 ₽</span>\n          <button class=\"bg-white text-stone-950 font-bold px-4 py-2 rounded-xl text-xs\">Забронировать место</button>\n        </div>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "podcast-landing",
    "category": "Медиа",
    "name": "DeepTalk — Еженедельный подкаст",
    "desc": "Интервью с учеными и фаундерами, плеер свежих выпусков и ссылки на Spotify/Apple.",
    "tags": [
      "Подкаст",
      "Медиа",
      "Аудио"
    ],
    "previewGradient": "from-purple-700 to-indigo-900",
    "previewSvg": "pod",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>DeepTalk — Подкаст о будущем</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <header class=\"p-6 border-b border-slate-800 flex justify-between items-center max-w-4xl mx-auto\">\n    <div class=\"text-xl font-black text-purple-400 flex items-center gap-2\"><i data-lucide=\"mic\" class=\"w-5 h-5\"></i> DEEPTALK</div>\n    <div class=\"flex gap-2\">\n      <button class=\"p-2 bg-slate-900 rounded-lg text-xs font-bold text-purple-300\">Apple Podcasts</button>\n      <button class=\"p-2 bg-slate-900 rounded-lg text-xs font-bold text-emerald-400\">Spotify</button>\n    </div>\n  </header>\n  <main class=\"max-w-3xl mx-auto p-6 py-12\">\n    <div class=\"bg-slate-900/80 border border-purple-500/20 rounded-3xl p-6 mb-8\">\n      <span class=\"text-xs bg-purple-500/10 text-purple-400 border border-purple-500/30 px-3 py-1 rounded-full font-bold\">Свежий эпизод #142</span>\n      <h2 class=\"text-2xl font-bold mt-3 mb-2\">ИИ, локальные модели и будущее веб-разработки</h2>\n      <p class=\"text-xs text-slate-400 mb-6\">Гость: Илья Суцкевер (Safe Superintelligence). Обсуждаем gpt-oss-20b, приватный инференс и будущее ассистентов.</p>\n      <div class=\"bg-slate-950 p-4 rounded-2xl flex items-center gap-4\">\n        <button class=\"w-12 h-12 rounded-full bg-purple-600 hover:bg-purple-500 flex items-center justify-center text-white\"><i data-lucide=\"play\" class=\"w-5 h-5 ml-0.5\"></i></button>\n        <div class=\"flex-1\">\n          <div class=\"h-1.5 bg-slate-800 rounded-full overflow-hidden\"><div class=\"w-1/3 h-full bg-purple-400\"></div></div>\n          <div class=\"flex justify-between text-[10px] text-slate-500 mt-1\"><span>24:18</span><span>1:12:00</span></div>\n        </div>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "pet-care",
    "category": "Зоотовары",
    "name": "HappyTail — Забота о питомцах",
    "desc": "Премиальные корма, эко-игрушки и ветеринарная телемедицина для кошек и собак.",
    "tags": [
      "Питомцы",
      "Зоомагазин",
      "Уход"
    ],
    "previewGradient": "from-pink-500 to-rose-600",
    "previewSvg": "pet",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>HappyTail — Все для счастья хвостиков</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-amber-50 text-stone-900 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center\">\n    <div class=\"text-2xl font-black text-rose-500 flex items-center gap-2\"><i data-lucide=\"heart\" class=\"w-6 h-6\"></i> HappyTail</div>\n    <button class=\"bg-rose-500 hover:bg-rose-600 text-white font-bold px-4 py-2 rounded-2xl text-xs\">Консультация ветврача</button>\n  </nav>\n  <main class=\"max-w-5xl mx-auto px-6 py-10\">\n    <div class=\"bg-rose-100/60 rounded-3xl p-8 mb-10 flex flex-col md:flex-row justify-between items-center gap-6\">\n      <div>\n        <h1 class=\"text-3xl font-extrabold text-stone-900 mb-2\">Натуральное питание для вашего любимца</h1>\n        <p class=\"text-stone-600 text-xs max-w-md\">100% фермерское мясо без консервантов и сои. Составлено ведущими диетологами-нутрициологами.</p>\n      </div>\n      <button class=\"bg-rose-500 text-white font-bold px-6 py-3 rounded-2xl text-xs shadow-lg shadow-rose-500/20\">Подобрать рацион</button>\n    </div>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-5 rounded-2xl shadow-sm border border-stone-200\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 font-bold text-xs\">[Паштет с индейкой]</div>\n        <h3 class=\"font-bold text-sm\">Свежий рацион для щенков</h3>\n        <p class=\"text-xs text-stone-500 my-1\">Омега-3, кальций и витамины группы B</p>\n        <span class=\"font-bold text-rose-500 text-sm\">450 ₽ / 400г</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl shadow-sm border border-stone-200\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 font-bold text-xs\">[Игрушка канатик]</div>\n        <h3 class=\"font-bold text-sm\">Эко-игрушка из джута</h3>\n        <p class=\"text-xs text-stone-500 my-1\">Безопасна для зубов, очищает налет</p>\n        <span class=\"font-bold text-rose-500 text-sm\">390 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl shadow-sm border border-stone-200\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 font-bold text-xs\">[Умная кормушка]</div>\n        <h3 class=\"font-bold text-sm\">Автопоилка с фильтром</h3>\n        <p class=\"text-xs text-stone-500 my-1\">Постоянная циркуляция чистой воды</p>\n        <span class=\"font-bold text-rose-500 text-sm\">2 490 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "vpn-service",
    "category": "SaaS",
    "name": "ShieldVPN — Быстрый & Безопасный",
    "desc": "Приватный VPN без логов: скорость 10 Гбит/с, обход блокировок и протокол WireGuard.",
    "tags": [
      "VPN",
      "Безопасность",
      "SaaS"
    ],
    "previewGradient": "from-blue-600 to-indigo-800",
    "previewSvg": "vpn",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>ShieldVPN — Полная свобода в сети</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-blue-400\"><i data-lucide=\"shield\" class=\"w-6 h-6\"></i> ShieldVPN</div>\n    <button class=\"bg-blue-600 hover:bg-blue-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Подключить тариф</button>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-14 text-center\">\n    <h1 class=\"text-4xl md:text-5xl font-extrabold mb-4\">Интернет без цензуры, слежки и ограничений скорости</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mx-auto mb-10\">Протокол нового поколения WireGuard, 60+ локаций по всему миру и строгая политика No-Logs.</p>\n    <div class=\"grid md:grid-cols-3 gap-6 text-left\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-base mb-1\">10 Гбит/с порты</h4>\n        <p class=\"text-xs text-slate-400\">Смотрите 4K стримы и играйте онлайн с минимальным пингом.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-base mb-1\">До 10 устройств</h4>\n        <p class=\"text-xs text-slate-400\">Один аккаунт для смартфона, ноутбука, роутера и планшета.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-base mb-1\">Шифрование AES-256</h4>\n        <p class=\"text-xs text-slate-400\">Военный стандарт защиты персональных данных в публичном Wi-Fi.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "eco-store",
    "category": "Магазин",
    "name": "GreenLeaf — Эко-продукты",
    "desc": "Фермерские овощи, сыры и экологичные товары для дома с быстрой доставкой.",
    "tags": [
      "Эко",
      "Органик",
      "Ферма"
    ],
    "previewGradient": "from-green-600 to-lime-700",
    "previewSvg": "eco",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>GreenLeaf — Органические продукты</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#f4f7f4] text-stone-900 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-stone-200\">\n    <div class=\"text-xl font-bold text-green-700 flex items-center gap-2\"><i data-lucide=\"leaf\" class=\"w-6 h-6\"></i> GreenLeaf</div>\n    <span class=\"text-xs text-stone-500\">Доставка ко времени • Сертификат Organic</span>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-10\">\n    <div class=\"bg-green-800 text-white rounded-3xl p-8 mb-10 flex justify-between items-center\">\n      <div>\n        <h1 class=\"text-3xl font-extrabold mb-2\">Настоящая деревенская еда</h1>\n        <p class=\"text-green-100 text-xs\">Без нитратов, пестицидов и антибиотиков прямо с семейных ферм Подмосковья.</p>\n      </div>\n      <button class=\"bg-white text-green-950 font-bold px-6 py-3 rounded-2xl text-xs\">Каталог урожая</button>\n    </div>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200 shadow-sm\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 font-bold text-xs\">[Корзина овощей 5кг]</div>\n        <h3 class=\"font-bold text-sm\">Сезонный набор овощей</h3>\n        <p class=\"text-xs text-stone-500 my-1\">Томаты, хрустящие огурцы, молодой картофель</p>\n        <span class=\"font-bold text-green-700 text-sm\">1 290 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200 shadow-sm\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 font-bold text-xs\">[Ремесленный сыр Качотта]</div>\n        <h3 class=\"font-bold text-sm\">Сыр Качотта с пажитником</h3>\n        <p class=\"text-xs text-stone-500 my-1\">Цельное коровье молоко, выдержка 2 месяца</p>\n        <span class=\"font-bold text-green-700 text-sm\">680 ₽ / 300г</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200 shadow-sm\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 font-bold text-xs\">[Мед с пасеки]</div>\n        <h3 class=\"font-bold text-sm\">Липовый сырой мед</h3>\n        <p class=\"text-xs text-stone-500 my-1\">Без пастеризации и сахара, сбор лето 2025</p>\n        <span class=\"font-bold text-green-700 text-sm\">550 ₽ / 500г</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "gaming-server",
    "category": "Гейминг",
    "name": "CraftWorld — Minecraft Сервер",
    "desc": "Уютный ламповый сервер выживания с кастомной экономикой, кланами и донат-кейсами.",
    "tags": [
      "Minecraft",
      "Сервер",
      "Гейминг"
    ],
    "previewGradient": "from-orange-500 to-red-600",
    "previewSvg": "craft",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>CraftWorld — Сервер Твоего Выживания</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-950 text-neutral-100 min-h-screen\">\n  <header class=\"p-6 border-b border-neutral-800 flex justify-between items-center max-w-4xl mx-auto\">\n    <div class=\"text-xl font-black text-amber-400 flex items-center gap-2\"><i data-lucide=\"box\" class=\"w-5 h-5\"></i> CRAFTWORLD</div>\n    <span class=\"text-xs text-emerald-400 font-mono\">Онлайн: 342 / 500 игроков</span>\n  </header>\n  <main class=\"max-w-3xl mx-auto p-6 py-12 text-center\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-3\">Классическое выживание без гриферов</h1>\n    <p class=\"text-neutral-400 text-xs mb-8\">Версия 1.20.4 • Кастомные квесты, ванильная генерация и дружное комьюнити.</p>\n    <div class=\"bg-neutral-900 border border-neutral-800 p-4 rounded-2xl flex items-center justify-between mb-8\">\n      <div class=\"font-mono text-xs text-amber-300\">IP: play.craftworld.ru</div>\n      <button class=\"bg-amber-500 text-black font-bold px-4 py-2 rounded-xl text-xs\">Скопировать IP</button>\n    </div>\n    <div class=\"grid grid-cols-2 gap-4 text-left\">\n      <div class=\"p-4 bg-neutral-900/60 border border-neutral-800 rounded-xl\">\n        <h4 class=\"font-bold text-sm text-white\">Приват территории</h4>\n        <p class=\"text-[11px] text-neutral-400 mt-1\">Твои постройки в безопасности благодаря умной защите флажков.</p>\n      </div>\n      <div class=\"p-4 bg-neutral-900/60 border border-neutral-800 rounded-xl\">\n        <h4 class=\"font-bold text-sm text-white\">Рынок и кланы</h4>\n        <p class=\"text-[11px] text-neutral-400 mt-1\">Создавай клановые базы, торгуй с другими игроками на аукционе.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "accounting",
    "category": "Финансы",
    "name": "FinAudit — Бухгалтерский аутсорсинг",
    "desc": "Сдача отчетности, расчет налогов и зарплат для ООО и ИП без штрафов и блокировок счетов.",
    "tags": [
      "Бухгалтерия",
      "Финансы",
      "Бизнес"
    ],
    "previewGradient": "from-blue-800 to-slate-900",
    "previewSvg": "calc",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>FinAudit — Бухгалтерия для бизнеса</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-sky-400\"><i data-lucide=\"calculator\" class=\"w-5 h-5\"></i> FINAUDIT</div>\n    <button class=\"bg-sky-500 hover:bg-sky-400 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs\">Рассчитать стоимость</button>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-extrabold mb-4\">Бухгалтерия под ключ с финансовой гарантией по договору</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">Страховка профессиональной ответственности на 10 млн рублей. Никаких пеней от налоговой.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-slate-900 border border-slate-800 p-6 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-2\">Для ИП на УСН</h3>\n        <p class=\"text-xs text-slate-400 mb-4\">Книга доходов и расходов, декларация, расчет страховых взносов.</p>\n        <span class=\"text-sky-400 font-bold text-sm\">от 3 500 ₽ / мес</span>\n      </div>\n      <div class=\"bg-slate-900 border border-slate-800 p-6 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-2\">Для ООО (ОСНО)</h3>\n        <p class=\"text-xs text-slate-400 mb-4\">НДС, налог на прибыль, кадровый учет до 15 сотрудников.</p>\n        <span class=\"text-sky-400 font-bold text-sm\">от 12 000 ₽ / мес</span>\n      </div>\n      <div class=\"bg-slate-900 border border-slate-800 p-6 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-2\">Восстановление учета</h3>\n        <p class=\"text-xs text-slate-400 mb-4\">Быстрый аудит и исправление пробелов за прошлые отчетные периоды.</p>\n        <span class=\"text-sky-400 font-bold text-sm\">от 15 000 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "tattoo-studio",
    "category": "Услуги",
    "name": "InkSanctum — Тату салон",
    "desc": "Авторские эскизы, безопасные пигменты, реализм, графика и перекрытие старых татуировок.",
    "tags": [
      "Тату",
      "Стиль",
      "Искусство"
    ],
    "previewGradient": "from-neutral-900 via-rose-950 to-black",
    "previewSvg": "tattoo",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>InkSanctum — Студия художественной татуировки</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-black text-white min-h-screen\">\n  <header class=\"p-8 text-center border-b border-zinc-900\">\n    <div class=\"text-3xl font-black tracking-widest uppercase\">INK SANCTUM</div>\n    <div class=\"text-[10px] text-zinc-500 uppercase tracking-widest mt-1\">MOSCOW • PRIVATE TATTOO STUDIO</div>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <div class=\"text-center mb-10\">\n      <h1 class=\"text-4xl font-black uppercase tracking-tight\">Твое тело — галерея твоих смыслов</h1>\n      <p class=\"text-zinc-500 text-xs mt-2\">Стерильное медицинское оборудование, японские иглы и авторская разработка эскиза.</p>\n    </div>\n    <div class=\"grid grid-cols-2 md:grid-cols-3 gap-4 mb-10\">\n      <div class=\"aspect-square bg-zinc-900 border border-zinc-800 rounded-2xl flex items-center justify-center text-zinc-600 text-xs font-bold\">[Графика / Дотворк]</div>\n      <div class=\"aspect-square bg-zinc-900 border border-zinc-800 rounded-2xl flex items-center justify-center text-zinc-600 text-xs font-bold\">[Реализм / Портреты]</div>\n      <div class=\"aspect-square bg-zinc-900 border border-zinc-800 rounded-2xl flex items-center justify-center text-zinc-600 text-xs font-bold\">[Япония / Ориентал]</div>\n    </div>\n    <div class=\"text-center\">\n      <button class=\"bg-rose-700 hover:bg-rose-600 text-white font-bold px-8 py-3 rounded-full text-xs uppercase tracking-wider transition\">Консультация с мастером</button>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "bakery",
    "category": "Еда",
    "name": "WarmCrust — Французская пекарня",
    "desc": "Хрустящие круассаны на сливочном масле, ремесленный тартин на закваске и свежий кофе.",
    "tags": [
      "Пекарня",
      "Выпечка",
      "Еда"
    ],
    "previewGradient": "from-amber-600 to-yellow-700",
    "previewSvg": "bake",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>WarmCrust — Ремесленная пекарня</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#fbf7f0] text-amber-950 min-h-screen\">\n  <header class=\"p-6 text-center border-b border-amber-200\">\n    <div class=\"text-2xl font-serif font-bold text-amber-900\">WarmCrust</div>\n    <p class=\"text-xs text-amber-800/60 uppercase tracking-widest mt-0.5\">Выпекаем свежий хлеб каждое утро в 06:00</p>\n  </header>\n  <main class=\"max-w-3xl mx-auto p-6 py-10\">\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"p-5 bg-white rounded-2xl border border-amber-200 shadow-sm\">\n        <h3 class=\"font-serif font-bold text-lg mb-2\">Хлеб на живой закваске</h3>\n        <div class=\"space-y-2 text-xs text-amber-900\">\n          <div class=\"flex justify-between\"><span>Тартин деревенский (800г)</span><span class=\"font-bold\">220 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Бородинский с кориандром</span><span class=\"font-bold\">180 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Багет традиционный парижский</span><span class=\"font-bold\">140 ₽</span></div>\n        </div>\n      </div>\n      <div class=\"p-5 bg-white rounded-2xl border border-amber-200 shadow-sm\">\n        <h3 class=\"font-serif font-bold text-lg mb-2\">Слоёная выпечка</h3>\n        <div class=\"space-y-2 text-xs text-amber-900\">\n          <div class=\"flex justify-between\"><span>Классический круассан</span><span class=\"font-bold\">190 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Миндальный круассан с кремом</span><span class=\"font-bold\">260 ₽</span></div>\n          <div class=\"flex justify-between\"><span>Улитка с корицей и пеканом</span><span class=\"font-bold\">230 ₽</span></div>\n        </div>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "beauty-salon",
    "category": "Красота",
    "name": "GlowAura — Салон красоты & SPA",
    "desc": "Маникюр, уход за волосами, массаж лица и расслабляющие ритуалы в атмосфере гармонии.",
    "tags": [
      "Красота",
      "SPA",
      "Уход"
    ],
    "previewGradient": "from-rose-400 to-pink-600",
    "previewSvg": "beauty",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>GlowAura — Пространство красоты и спа</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#faf5f6] text-stone-800 min-h-screen\">\n  <nav class=\"max-w-4xl mx-auto p-6 flex justify-between items-center\">\n    <div class=\"text-xl font-light tracking-widest text-pink-900 uppercase\">GLOW•AURA</div>\n    <button class=\"bg-pink-600 hover:bg-pink-700 text-white font-medium px-4 py-2 rounded-full text-xs\">Онлайн запись</button>\n  </nav>\n  <main class=\"max-w-3xl mx-auto p-6 py-10 space-y-6\">\n    <div class=\"text-center\">\n      <h1 class=\"text-3xl font-light tracking-wide text-stone-900\">Время позаботиться о себе</h1>\n      <p class=\"text-xs text-stone-500 mt-2\">Премиальные бренды косметики Davines, Comfort Zone и La Sultane de Saba.</p>\n    </div>\n    <div class=\"bg-white rounded-3xl p-6 border border-pink-100 shadow-sm space-y-4\">\n      <div class=\"flex justify-between items-center border-b border-pink-50 pb-3\">\n        <div><div class=\"font-medium text-sm\">Сет Маникюр + SMART-педикюр</div><div class=\"text-xs text-stone-400\">Снятие, выравнивание, покрытие гель-лаком</div></div>\n        <span class=\"font-bold text-pink-700\">4 200 ₽</span>\n      </div>\n      <div class=\"flex justify-between items-center border-b border-pink-50 pb-3\">\n        <div><div class=\"font-medium text-sm\">Уход за волосами «Абсолютное счастье»</div><div class=\"text-xs text-stone-400\">Многоступенчатое восстановление Lebel</div></div>\n        <span class=\"font-bold text-pink-700\">5 500 ₽</span>\n      </div>\n      <div class=\"flex justify-between items-center\">\n        <div><div class=\"font-medium text-sm\">Скульптурный массаж лица (60 мин)</div><div class=\"text-xs text-stone-400\">Снятие отеков и выраженный лифтинг-эффект</div></div>\n        <span class=\"font-bold text-pink-700\">3 800 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "architecture",
    "category": "Архитектура",
    "name": "FormaStudio — Проекты домов",
    "desc": "Индивидуальное проектирование энергоэффективных загородных вилл и коттеджей.",
    "tags": [
      "Архитектура",
      "Виллы",
      "Проекты"
    ],
    "previewGradient": "from-stone-700 to-stone-900",
    "previewSvg": "arch",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>FormaStudio — Архитектурное бюро</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-900 text-neutral-100 min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-neutral-800\">\n    <div class=\"text-lg font-bold tracking-widest uppercase\">FORMA STUDIO</div>\n    <span class=\"text-xs text-neutral-400\">Архитектура • Конструктив • Ландшафт</span>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-light mb-4\">Чистая геометрия и гармония с природой</h1>\n    <p class=\"text-neutral-400 text-sm max-w-xl mb-8\">Создаем современные дома с панорамным остеклением, плоскими кровлями и умными инженерными системами.</p>\n    <div class=\"grid md:grid-cols-2 gap-8\">\n      <div class=\"bg-neutral-800/50 border border-neutral-700 rounded-2xl p-6\">\n        <div class=\"h-44 bg-neutral-700 rounded-xl mb-4 flex items-center justify-center text-neutral-400 text-xs font-bold\">[Вилла «Forest House» — 350 м²]</div>\n        <h3 class=\"text-xl font-bold mb-1\">Проект «Forest House»</h3>\n        <p class=\"text-xs text-neutral-400\">Монолитный железобетон, вентилируемый фасад из лиственницы, второй свет.</p>\n      </div>\n      <div class=\"bg-neutral-800/50 border border-neutral-700 rounded-2xl p-6\">\n        <div class=\"h-44 bg-neutral-700 rounded-xl mb-4 flex items-center justify-center text-neutral-400 text-xs font-bold\">[Резиденция «Lake View» — 480 м²]</div>\n        <h3 class=\"text-xl font-bold mb-1\">Проект «Lake View»</h3>\n        <p class=\"text-xs text-neutral-400\">Консольные выносы террас, спа-комплекс с бассейном, энергоэффективность А+.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "music-label",
    "category": "Музыка",
    "name": "SonicPulse — Независимый лейбл",
    "desc": "Дистрибуция треков на стриминги, продюсирование и продвижение независимых музыкантов.",
    "tags": [
      "Музыка",
      "Лейбл",
      "Артисты"
    ],
    "previewGradient": "from-violet-800 to-fuchsia-900",
    "previewSvg": "music",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>SonicPulse Music Label</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-black text-white min-h-screen\">\n  <header class=\"p-6 border-b border-zinc-900 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-black text-fuchsia-400 flex items-center gap-2\"><i data-lucide=\"disc\" class=\"w-5 h-5\"></i> SONICPULSE</div>\n    <button class=\"bg-fuchsia-600 text-white font-bold px-4 py-2 rounded-xl text-xs\">Отправить демо</button>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-4xl md:text-6xl font-black uppercase tracking-tight mb-4\">Твой трек зазвучит по всему миру</h1>\n    <p class=\"text-zinc-400 text-sm max-w-lg mb-8\">Быстрая доставка на Яндекс Музыку, VK, Apple Music и Spotify. Прозрачные роялти 85/15 в пользу артиста.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-5 bg-zinc-900/60 border border-zinc-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Синхронизация в кино</h4>\n        <p class=\"text-xs text-zinc-400\">Размещение музыки в сериалах, рекламе и играх.</p>\n      </div>\n      <div class=\"p-5 bg-zinc-900/60 border border-zinc-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Питчинг в плейлисты</h4>\n        <p class=\"text-xs text-zinc-400\">Прямой выход на кураторов редакционных плейлистов.</p>\n      </div>\n      <div class=\"p-5 bg-zinc-900/60 border border-zinc-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Юридическая защита</h4>\n        <p class=\"text-xs text-zinc-400\">Регистрация авторских прав и защита от пиратства.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "charity-fund",
    "category": "Благотворительность",
    "name": "HopeHeart — Помощь детям",
    "desc": "Прозрачный благотворительный фонд с финансовыми отчетами и быстрой формой пожертвования.",
    "tags": [
      "Благотворительность",
      "Помощь",
      "Добро"
    ],
    "previewGradient": "from-teal-600 to-cyan-700",
    "previewSvg": "heart",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>HopeHeart — Фонд помощи детям</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-cyan-50/40 text-slate-800 min-h-screen\">\n  <header class=\"bg-white border-b border-cyan-100 p-6 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-bold text-teal-700 flex items-center gap-2\"><i data-lucide=\"heart\" class=\"w-5 h-5 text-rose-500\"></i> HopeHeart</div>\n    <span class=\"text-xs text-slate-500\">Отчеты публикуются ежемесячно</span>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <div class=\"bg-white rounded-3xl p-8 border border-cyan-100 shadow-sm mb-8\">\n      <span class=\"text-xs font-bold text-teal-600 uppercase\">Срочный сбор</span>\n      <h1 class=\"text-3xl font-extrabold text-slate-900 mt-1 mb-3\">Поможем Мише снова ходить</h1>\n      <p class=\"text-slate-600 text-xs mb-6\">Мише 6 лет, у него ДЦП. Необходим курс интенсивной реабилитации в институте травматологии.</p>\n      <div class=\"mb-6\">\n        <div class=\"flex justify-between text-xs font-bold mb-1\"><span>Собрано: 320 000 ₽</span><span class=\"text-slate-500\">Цель: 500 000 ₽</span></div>\n        <div class=\"h-3 bg-slate-100 rounded-full overflow-hidden\"><div class=\"w-[64%] h-full bg-teal-500 rounded-full\"></div></div>\n      </div>\n      <div class=\"flex gap-3\">\n        <button class=\"bg-teal-600 hover:bg-teal-500 text-white font-bold px-6 py-3 rounded-xl text-xs\">Помочь 500 ₽</button>\n        <button class=\"bg-slate-100 hover:bg-slate-200 text-slate-800 font-bold px-6 py-3 rounded-xl text-xs\">Другая сумма</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "startup-pitch",
    "category": "SaaS",
    "name": "PitchDeck AI — Инвест-презентации",
    "desc": "Генератор инвестиционных презентаций за 5 минут на основе описания стартапа.",
    "tags": [
      "AI",
      "Стартап",
      "Презентации"
    ],
    "previewGradient": "from-indigo-600 to-blue-700",
    "previewSvg": "pitch",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>PitchDeck AI — Привлекайте инвестиции быстрее</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-indigo-400\"><i data-lucide=\"layers\" class=\"w-5 h-5\"></i> PITCHDECK AI</div>\n    <button class=\"bg-indigo-600 hover:bg-indigo-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Создать питч</button>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12 text-center\">\n    <h1 class=\"text-4xl md:text-5xl font-extrabold mb-4\">Идеальный Pitch Deck для инвесторов за пару минут</h1>\n    <p class=\"text-slate-400 text-sm max-w-lg mx-auto mb-8\">AI анализирует ваш рынок, конкурентов и финмодель, генерируя 12 профессиональных слайдов в стандарте Y Combinator.</p>\n    <div class=\"grid md:grid-cols-3 gap-6 text-left\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-1\">Анализ рынка (TAM/SAM)</h3>\n        <p class=\"text-xs text-slate-400\">Автоматический расчет объемов рынка со ссылками на отчеты Gartner.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-1\">Экспорт в PDF и PPTX</h3>\n        <p class=\"text-xs text-slate-400\">Редактируемые файлы, готовые к отправке венчурным фондам.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h3 class=\"font-bold text-white mb-1\">Q&A Симулятор</h3>\n        <p class=\"text-xs text-slate-400\">Бот прогонит вас по 50 каверзным вопросам от венчурных аналитиков.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "furniture-store",
    "category": "Магазин",
    "name": "NordicHome — Скандинавская мебель",
    "desc": "Дизайнерские диваны, столы из массива дуба и светильники для уютного интерьера.",
    "tags": [
      "Мебель",
      "Интерьер",
      "Дизайн"
    ],
    "previewGradient": "from-amber-700 to-stone-800",
    "previewSvg": "furn",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>NordicHome — Скандинавский интерьер</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-50 text-stone-900 min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-stone-200\">\n    <div class=\"text-2xl font-light tracking-widest text-stone-900\">NORDIC HOME</div>\n    <div class=\"flex gap-4 text-xs font-semibold\">\n      <a href=\"#\" class=\"hover:underline\">Гостиная</a>\n      <a href=\"#\" class=\"hover:underline\">Спальня</a>\n      <a href=\"#\" class=\"hover:underline\">Свет</a>\n    </div>\n  </nav>\n  <main class=\"max-w-6xl mx-auto p-6 py-10\">\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-44 bg-stone-100 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold\">[Диван Bergen Boucle]</div>\n        <h3 class=\"font-bold text-base\">Диван трехместный Bergen</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Ткань букле, ножки из массива ясеня.</p>\n        <span class=\"font-extrabold text-stone-900\">68 900 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-44 bg-stone-100 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold\">[Обеденный стол Oslo Oak]</div>\n        <h3 class=\"font-bold text-base\">Обеденный стол Oslo</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Натуральный массив белого дуба, 180×90 см.</p>\n        <span class=\"font-extrabold text-stone-900\">44 500 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-44 bg-stone-100 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold\">[Кресло Stockholm]</div>\n        <h3 class=\"font-bold text-base\">Кресло для отдыха Stockholm</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Эргономичная посадка, велюровая обивка.</p>\n        <span class=\"font-extrabold text-stone-900\">29 900 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "coworking",
    "category": "Недвижимость",
    "name": "HiveSpace — Коворкинг & Офисы",
    "desc": "Гибкие рабочие места в центре, переговорные комнаты, оптоволоконный интернет и кофе-поинты.",
    "tags": [
      "Коворкинг",
      "Офис",
      "Бизнес"
    ],
    "previewGradient": "from-yellow-600 to-amber-700",
    "previewSvg": "work",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>HiveSpace — Коворкинг в центре</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-950 text-neutral-100 min-h-screen\">\n  <header class=\"p-6 border-b border-neutral-800 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-black text-amber-400 flex items-center gap-2\"><i data-lucide=\"coffee\" class=\"w-5 h-5\"></i> HIVESPACE</div>\n    <button class=\"bg-amber-400 text-neutral-950 font-bold px-4 py-2 rounded-xl text-xs\">Тестовый день бесплатно</button>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Работайте там, где рождаются смелые идеи</h1>\n    <p class=\"text-neutral-400 text-sm max-w-lg mb-8\">2000 м² стильного рабочего пространства: переговорки со спикерфонами, скайп-румы и терраса на крыше.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-6 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Hot Desk</h4>\n        <p class=\"text-xs text-neutral-400 mb-4\">Любое свободное место в open-space зоне, чай и кофе.</p>\n        <span class=\"font-bold text-amber-400 text-sm\">1 200 ₽ / день</span>\n      </div>\n      <div class=\"p-6 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Fixed Desk</h4>\n        <p class=\"text-xs text-neutral-400 mb-4\">Закрепленный стол с тумбой, доступ 24/7 и часы в переговорках.</p>\n        <span class=\"font-bold text-amber-400 text-sm\">19 000 ₽ / мес</span>\n      </div>\n      <div class=\"p-6 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Team Office</h4>\n        <p class=\"text-xs text-neutral-400 mb-4\">Изолированный смарт-офис для команды от 4 до 20 человек.</p>\n        <span class=\"font-bold text-amber-400 text-sm\">от 80 000 ₽ / мес</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "cleaning",
    "category": "Услуги",
    "name": "SparkClean — Клининг квартир",
    "desc": "Уборка квартир и офисов безопасными эко-средствами с калькулятором комнат.",
    "tags": [
      "Клининг",
      "Уборка",
      "Дом"
    ],
    "previewGradient": "from-sky-500 to-blue-600",
    "previewSvg": "clean",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>SparkClean — Идеальная чистота дома</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-sky-50/50 text-slate-800 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-sky-100\">\n    <div class=\"text-xl font-bold text-sky-600 flex items-center gap-2\"><i data-lucide=\"sparkles\" class=\"w-5 h-5\"></i> SPARKCLEAN</div>\n    <span class=\"text-xs text-slate-500\">Клинеры с опытом от 3 лет</span>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <div class=\"text-center max-w-xl mx-auto mb-10\">\n      <h1 class=\"text-3xl font-extrabold text-slate-900 mb-2\">Наведем идеальный порядок, пока вы отдыхаете</h1>\n      <p class=\"text-xs text-slate-500\">Привозим свои пылесосы Kärcher, парогенераторы и гипоаллергенные средства.</p>\n    </div>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-6 rounded-2xl border border-sky-100 shadow-sm text-center\">\n        <h4 class=\"font-bold text-base mb-1\">1-комнатная квартира</h4>\n        <p class=\"text-xs text-slate-400 mb-4\">Влажная уборка, обеспыливание, санузел и кухня.</p>\n        <span class=\"text-xl font-bold text-sky-600 block mb-4\">2 800 ₽</span>\n        <button class=\"w-full bg-sky-600 text-white font-bold py-2 rounded-xl text-xs\">Заказать</button>\n      </div>\n      <div class=\"bg-white p-6 rounded-2xl border border-sky-100 shadow-sm text-center\">\n        <h4 class=\"font-bold text-base mb-1\">2-комнатная квартира</h4>\n        <p class=\"text-xs text-slate-400 mb-4\">Глубокая очистка поверхностей, мытье зеркал.</p>\n        <span class=\"text-xl font-bold text-sky-600 block mb-4\">3 600 ₽</span>\n        <button class=\"w-full bg-sky-600 text-white font-bold py-2 rounded-xl text-xs\">Заказать</button>\n      </div>\n      <div class=\"bg-white p-6 rounded-2xl border border-sky-100 shadow-sm text-center\">\n        <h4 class=\"font-bold text-base mb-1\">Генеральная уборка</h4>\n        <p class=\"text-xs text-slate-400 mb-4\">Мытье окон, вытяжки, духового шкафа и кафеля.</p>\n        <span class=\"text-xl font-bold text-sky-600 block mb-4\">6 900 ₽</span>\n        <button class=\"w-full bg-sky-600 text-white font-bold py-2 rounded-xl text-xs\">Заказать</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "jewel-store",
    "category": "Магазин",
    "name": "AuraGems — Ювелирные изделия",
    "desc": "Авторские кольца из платины и золота с натуральными бриллиантами и изумрудами.",
    "tags": [
      "Ювелирный",
      "Золото",
      "Luxury"
    ],
    "previewGradient": "from-purple-900 via-stone-900 to-black",
    "previewSvg": "gem",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>AuraGems — Высокое ювелирное искусство</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-950 text-stone-100 min-h-screen font-serif\">\n  <header class=\"p-8 text-center border-b border-stone-800\">\n    <div class=\"text-2xl tracking-widest text-amber-200 uppercase\">AURA GEMS</div>\n    <div class=\"text-[10px] font-sans text-stone-400 uppercase tracking-widest mt-1\">Fine Jewelry & Diamonds</div>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12 font-sans\">\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-stone-900/60 border border-stone-800 rounded-2xl p-5 text-center\">\n        <div class=\"h-44 bg-stone-800 rounded-xl mb-4 flex items-center justify-center text-stone-500 text-xs font-bold font-serif\">[Кольцо Solitaire Platinum]</div>\n        <h4 class=\"font-serif font-bold text-sm text-stone-200\">Помолвочное кольцо Grace</h4>\n        <p class=\"text-xs text-stone-400 my-1\">Платина 950, бриллиант 0.7 карата (G/VS1)</p>\n        <span class=\"font-bold text-amber-300 text-base\">210 000 ₽</span>\n      </div>\n      <div class=\"bg-stone-900/60 border border-stone-800 rounded-2xl p-5 text-center\">\n        <div class=\"h-44 bg-stone-800 rounded-xl mb-4 flex items-center justify-center text-stone-500 text-xs font-bold font-serif\">[Серьги Emerald Drop]</div>\n        <h4 class=\"font-serif font-bold text-sm text-stone-200\">Серьги с изумрудами Royal</h4>\n        <p class=\"text-xs text-stone-400 my-1\">Желтое золото 750, колумбийские изумруды</p>\n        <span class=\"font-bold text-amber-300 text-base\">165 000 ₽</span>\n      </div>\n      <div class=\"bg-stone-900/60 border border-stone-800 rounded-2xl p-5 text-center\">\n        <div class=\"h-44 bg-stone-800 rounded-xl mb-4 flex items-center justify-center text-stone-500 text-xs font-bold font-serif\">[Колье Diamond Tennis]</div>\n        <h4 class=\"font-serif font-bold text-sm text-stone-200\">Теннисное колье Infinity</h4>\n        <p class=\"text-xs text-stone-400 my-1\">Белое золото 750, дорожка бриллиантов 3.2 ct</p>\n        <span class=\"font-bold text-amber-300 text-base\">380 000 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "cinema-club",
    "category": "Развлечения",
    "name": "KinoLounge — Артхаусный кинотеатр",
    "desc": "Камерный кинозал с мягкими диванами, фильмами на языке оригинала и кинолекциями.",
    "tags": [
      "Кино",
      "Культура",
      "Отдых"
    ],
    "previewGradient": "from-red-900 to-black",
    "previewSvg": "film",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>KinoLounge — Киноклуб & Бар</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-black text-white min-h-screen\">\n  <header class=\"p-6 border-b border-red-950 flex justify-between items-center max-w-4xl mx-auto\">\n    <div class=\"text-xl font-bold tracking-widest text-red-500 flex items-center gap-2\"><i data-lucide=\"clapperboard\" class=\"w-5 h-5\"></i> KINOLOUNGE</div>\n    <span class=\"text-xs text-zinc-400\">Показы на языке оригинала с субтитрами</span>\n  </header>\n  <main class=\"max-w-3xl mx-auto p-6 py-10 space-y-6\">\n    <h2 class=\"text-2xl font-bold\">Афиша на сегодня</h2>\n    <div class=\"bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex justify-between items-center\">\n      <div>\n        <span class=\"text-red-500 text-xs font-mono font-bold\">19:30 • ЗАЛ 1</span>\n        <h3 class=\"font-bold text-base text-white\">«Малхолланд Драйв» — Дэвид Линч</h3>\n        <p class=\"text-xs text-zinc-400\">Обсуждение фильма с кинокритиком Антоном Долиным.</p>\n      </div>\n      <button class=\"bg-red-600 hover:bg-red-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Билет 600 ₽</button>\n    </div>\n    <div class=\"bg-zinc-900 border border-zinc-800 rounded-2xl p-5 flex justify-between items-center\">\n      <div>\n        <span class=\"text-red-500 text-xs font-mono font-bold\">22:00 • ЗАЛ 2</span>\n        <h3 class=\"font-bold text-base text-white\">«Бегущий по лезвию 2049» — Дени Вильнёв</h3>\n        <p class=\"text-xs text-zinc-400\">Dolby Atmos объемный звук и 4K лазерная проекция.</p>\n      </div>\n      <button class=\"bg-red-600 hover:bg-red-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Билет 750 ₽</button>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "logistics",
    "category": "Бизнес",
    "name": "FastCargo — Экспресс логистика",
    "desc": "Грузоперевозки по России и СНГ, онлайн-трекинг отправлений и страхование грузов.",
    "tags": [
      "Логистика",
      "Доставка",
      "Бизнес"
    ],
    "previewGradient": "from-amber-600 to-slate-800",
    "previewSvg": "truck",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>FastCargo — Доставка грузов точно в срок</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-black text-amber-400 flex items-center gap-2\"><i data-lucide=\"truck\" class=\"w-6 h-6\"></i> FASTCARGO</div>\n    <div class=\"text-xs text-slate-400\">8 (800) 555-35-35 • Круглосуточно</div>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Надежные грузоперевозки от 100 кг до 20 тонн</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">Собственный автопарк более 120 еврофур с GPS-маяками. Подача машины в день заказа.</p>\n    <div class=\"bg-slate-900 border border-slate-800 p-6 rounded-2xl mb-8\">\n      <h3 class=\"font-bold text-white mb-3 text-sm\">Отследить отправление</h3>\n      <div class=\"flex gap-2\">\n        <input type=\"text\" placeholder=\"Введите номер накладной (например, FC-98214)\" class=\"bg-slate-950 border border-slate-700 rounded-xl px-4 py-2 text-xs text-white flex-1 outline-none\">\n        <button class=\"bg-amber-400 text-slate-950 font-bold px-5 py-2 rounded-xl text-xs\">Проверить</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "marketing-agency",
    "category": "Маркетинг",
    "name": "AdRocket — Трафик & Перформанс",
    "desc": "Привлечение целевых лидов из Яндекс Директ, Telegram Ads и VK с оплатой за результат.",
    "tags": [
      "Маркетинг",
      "Реклама",
      "Лидогенерация"
    ],
    "previewGradient": "from-rose-600 to-indigo-800",
    "previewSvg": "rocket",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>AdRocket — Масштабируем продажи</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <header class=\"p-6 border-b border-slate-800 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-black text-rose-500 flex items-center gap-2\"><i data-lucide=\"rocket\" class=\"w-5 h-5\"></i> ADROCKET</div>\n    <button class=\"bg-rose-600 text-white font-bold px-4 py-2 rounded-xl text-xs\">Аудит рекламы</button>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-4xl md:text-5xl font-black mb-4\">Увеличиваем выручку вашего бизнеса через окупаемый трафик</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">Управляем рекламными бюджетами свыше 50 млн руб в месяц. Глубокая сквозная аналитика до ROMI.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-5 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Яндекс Директ</h4>\n        <p class=\"text-xs text-slate-400\">Мастер кампаний, поиск и РСЯ с оптимизацией по целевым конверсиям.</p>\n      </div>\n      <div class=\"p-5 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Telegram Ads</h4>\n        <p class=\"text-xs text-slate-400\">Прямой выход на платежеспособную аудиторию тематических каналов.</p>\n      </div>\n      <div class=\"p-5 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Сквозная Roistat</h4>\n        <p class=\"text-xs text-slate-400\">Настройка дашбордов окупаемости до конкретного ключевого слова.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "florist-shop",
    "category": "Магазин",
    "name": "BloomBox — Цветочная мастерская",
    "desc": "Авторские букеты из свежих пионов, ранункулюсов и эвкалипта с доставкой за 60 минут.",
    "tags": [
      "Цветы",
      "Подарки",
      "Флористика"
    ],
    "previewGradient": "from-pink-400 to-rose-500",
    "previewSvg": "flower",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>BloomBox — Авторские букеты</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#fef9f9] text-stone-800 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-rose-100\">\n    <div class=\"text-xl font-serif font-bold text-rose-800\">BloomBox</div>\n    <span class=\"text-xs text-rose-600 font-medium\">Бесплатная открытка с вашими словами к каждому заказу</span>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-10\">\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-5 rounded-2xl border border-rose-100 shadow-sm\">\n        <div class=\"h-44 bg-rose-50 rounded-xl mb-4 flex items-center justify-center text-rose-400 text-xs font-bold\">[Букет «Розовый рассвет»]</div>\n        <h3 class=\"font-bold text-sm\">Букет «Розовый рассвет»</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Пионовидные розы О'Хара, эустома, эвкалипт.</p>\n        <span class=\"font-bold text-rose-600\">4 800 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-rose-100 shadow-sm\">\n        <div class=\"h-44 bg-rose-50 rounded-xl mb-4 flex items-center justify-center text-rose-400 text-xs font-bold\">[Шляпная коробка «Прованс»]</div>\n        <h3 class=\"font-bold text-sm\">Цветы в коробке «Прованс»</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Гортензии, лаванда, кустовые пионы.</p>\n        <span class=\"font-bold text-rose-600\">6 200 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-rose-100 shadow-sm\">\n        <div class=\"h-44 bg-rose-50 rounded-xl mb-4 flex items-center justify-center text-rose-400 text-xs font-bold\">[Монобукет из 25 тюльпанов]</div>\n        <h3 class=\"font-bold text-sm\">Монобукет «Весенний бриз»</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Белые махровые тюльпаны в матовой бумаге.</p>\n        <span class=\"font-bold text-rose-600\">3 500 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "hostel-hotel",
    "category": "Отели",
    "name": "NomadHaven — Бутик-отель",
    "desc": "Уютные дизайнерские номера с панорамными окнами, шведским столом и SPA-зоной.",
    "tags": [
      "Отель",
      "Отдых",
      "Туризм"
    ],
    "previewGradient": "from-teal-700 to-slate-900",
    "previewSvg": "hotel",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>NomadHaven — Бутик-отель & Спа</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-900 text-stone-100 min-h-screen\">\n  <header class=\"p-6 border-b border-stone-800 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-serif tracking-widest text-teal-300\">NOMAD HAVEN</div>\n    <button class=\"bg-teal-500 text-stone-950 font-bold px-4 py-2 rounded-xl text-xs\">Забронировать номер</button>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-serif font-light mb-4\">Оазис спокойствия и уюта в сердце города</h1>\n    <p class=\"text-stone-400 text-sm max-w-xl mb-8\">Ортопедические матрасы King Koil, меню подушек, кофемашина Nespresso в каждом номере.</p>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"p-6 bg-stone-800/60 border border-stone-700 rounded-2xl\">\n        <div class=\"h-40 bg-stone-700 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold\">[Номер Deluxe King — 32 м²]</div>\n        <h3 class=\"font-bold text-lg mb-1\">Deluxe Room с видом на парк</h3>\n        <p class=\"text-xs text-stone-400 mb-4\">Включает завтрак a la carte и посещение термальной зоны.</p>\n        <span class=\"text-teal-300 font-bold text-lg\">8 500 ₽ / ночь</span>\n      </div>\n      <div class=\"p-6 bg-stone-800/60 border border-stone-700 rounded-2xl\">\n        <div class=\"h-40 bg-stone-700 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold\">[Люкс с камином — 55 м²]</div>\n        <h3 class=\"font-bold text-lg mb-1\">Signature Suite с камином</h3>\n        <p class=\"text-xs text-stone-400 mb-4\">Отдельная гостиная, гидромассажная ванна и мини-бар.</p>\n        <span class=\"text-teal-300 font-bold text-lg\">15 000 ₽ / ночь</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "recruitment",
    "category": "HR",
    "name": "TalentMatch — IT Рекрутинг",
    "desc": "Быстрый поиск Middle/Senior разработчиков, тимлидов и архитекторов за 14 дней.",
    "tags": [
      "HR",
      "IT",
      "Найм"
    ],
    "previewGradient": "from-blue-700 to-indigo-900",
    "previewSvg": "users",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>TalentMatch — Подбор IT-талантов</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-blue-400\"><i data-lucide=\"users\" class=\"w-5 h-5\"></i> TALENTMATCH</div>\n    <button class=\"bg-blue-600 hover:bg-blue-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Оставить заявку на найм</button>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-extrabold mb-4\">Закрываем сложные IT-вакансии с гарантией замены 3 месяца</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">База из 45 000+ разработчиков, техлидов и DevOps инженеров. Первые проверенные кандидаты через 48 часов.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Скрининг софт-скиллов</h4>\n        <p class=\"text-xs text-slate-400\">Проверяем мотивацию, коммуникацию и соответствие культуре компании.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Техническое интервью</h4>\n        <p class=\"text-xs text-slate-400\">Наши технические эксперты проводят первичное лайв-кодинг собеседование.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Оплата по факту выхода</h4>\n        <p class=\"text-xs text-slate-400\">Никаких предоплат. Вы платите только когда специалист вышел на работу.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "dental-clinic",
    "category": "Медицина",
    "name": "WhiteSmile — Стоматология",
    "desc": "Имплантация зубов, виниры и бережное отбеливание с рассрочкой 0%.",
    "tags": [
      "Стоматология",
      "Медицина",
      "Здоровье"
    ],
    "previewGradient": "from-cyan-600 to-teal-800",
    "previewSvg": "smile",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>WhiteSmile — Стоматологическая клиника</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-cyan-50/30 text-slate-800 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-cyan-100\">\n    <div class=\"text-xl font-bold text-teal-800 flex items-center gap-2\"><i data-lucide=\"sparkles\" class=\"w-5 h-5 text-teal-500\"></i> WhiteSmile</div>\n    <span class=\"text-xs text-slate-500\">Лечение под микроскопом Carl Zeiss</span>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <div class=\"bg-white rounded-3xl p-8 border border-cyan-100 shadow-sm mb-8 flex flex-col md:flex-row justify-between items-center gap-6\">\n      <div>\n        <h1 class=\"text-3xl font-extrabold text-slate-900 mb-2\">Безупречная здоровая улыбка за 2 визита</h1>\n        <p class=\"text-xs text-slate-500 max-w-md\">Компьютерная 3D томография и консультация главного ортопеда клиники бесплатно при первом посещении.</p>\n      </div>\n      <button class=\"bg-teal-600 text-white font-bold px-6 py-3 rounded-2xl text-xs\">Записаться на осмотр</button>\n    </div>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-5 rounded-2xl border border-cyan-100 shadow-sm\">\n        <h3 class=\"font-bold text-sm mb-1\">Керамические виниры</h3>\n        <p class=\"text-xs text-slate-500 mb-2\">Идеальная форма и естественная белизна зубов.</p>\n        <span class=\"font-bold text-teal-700 text-sm\">от 28 000 ₽ / ед</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-cyan-100 shadow-sm\">\n        <h3 class=\"font-bold text-sm mb-1\">Имплантация Nobel Biocare</h3>\n        <p class=\"text-xs text-slate-500 mb-2\">Швейцарское качество с пожизненной гарантией производителя.</p>\n        <span class=\"font-bold text-teal-700 text-sm\">от 42 000 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-cyan-100 shadow-sm\">\n        <h3 class=\"font-bold text-sm mb-1\">Отбеливание Zoom 4</h3>\n        <p class=\"text-xs text-slate-500 mb-2\">Осветление эмали до 8 тонов без чувствительности.</p>\n        <span class=\"font-bold text-teal-700 text-sm\">22 000 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "interior-design",
    "category": "Дизайн",
    "name": "AtelierSpace — Студия интерьера",
    "desc": "Дизайн-проекты квартир и загородных резиденций с полной комплектацией мебелью.",
    "tags": [
      "Интерьер",
      "Дизайн",
      "Ремонт"
    ],
    "previewGradient": "from-stone-600 to-amber-900",
    "previewSvg": "interior",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>AtelierSpace — Авторский дизайн интерьера</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-900 text-stone-100 min-h-screen\">\n  <header class=\"p-6 border-b border-stone-800 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-light tracking-widest text-amber-200\">ATELIER SPACE</div>\n    <button class=\"border border-amber-200/40 text-amber-200 px-4 py-1.5 rounded-full text-xs hover:bg-amber-200 hover:text-stone-900 transition\">Портфолио проектов</button>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-light mb-4\">Создаем пространства, в которых хочется жить и творить</h1>\n    <p class=\"text-stone-400 text-sm max-w-lg mb-8\">3D визуализации фотографического качества, чертежи для строителей и авторский надзор на стройке.</p>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"p-6 bg-stone-800/60 rounded-2xl border border-stone-700\">\n        <h3 class=\"text-lg font-bold mb-1\">Пакет «Полный проект»</h3>\n        <p class=\"text-xs text-stone-400 mb-4\">Обмерный план, планировочные решения, развертки стен, схемы электрики и 3D визуализации.</p>\n        <span class=\"text-amber-300 font-bold text-base\">от 3 800 ₽ / м²</span>\n      </div>\n      <div class=\"p-6 bg-stone-800/60 rounded-2xl border border-stone-700\">\n        <h3 class=\"text-lg font-bold mb-1\">Пакет «Комплектация под ключ»</h3>\n        <p class=\"text-xs text-stone-400 mb-4\">Закупка материалов и сантехники со скидками студии до 25%, контроль доставки и рекламации.</p>\n        <span class=\"text-amber-300 font-bold text-base\">от 1 500 ₽ / м²</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "drone-service",
    "category": "Услуги",
    "name": "SkyCam — Аэросъемка 4K",
    "desc": "Съемка с квадрокоптера недвижимости, мероприятий, картография и инспекция фасадов.",
    "tags": [
      "Дроны",
      "Видео",
      "Съемка"
    ],
    "previewGradient": "from-sky-600 to-indigo-800",
    "previewSvg": "drone",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>SkyCam — Профессиональная аэросъемка</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-sky-400\"><i data-lucide=\"video\" class=\"w-5 h-5\"></i> SKYCAM</div>\n    <span class=\"text-xs text-slate-400\">DJI Inspire 3 • Разрешение до 8K ProRes RAW</span>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Потрясающие кадры с высоты птичьего полета</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">Лицензированные пилоты, официальные разрешения на полеты над городом и цветокоррекция в комплекте.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Съемка недвижимости</h4>\n        <p class=\"text-xs text-slate-400\">Эффектные видеоролики коттеджных поселков и ЖК для рекламы.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">FPV-полеты динамика</h4>\n        <p class=\"text-xs text-slate-400\">Скоростные пролеты сквозь здания для презентаций и автогонок.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Ортофотопланы</h4>\n        <p class=\"text-xs text-slate-400\">Точная топографическая съемка участков и карьеров.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "smart-home",
    "category": "Технологии",
    "name": "OmniDom — Умный дом",
    "desc": "Автоматизация освещения, климата, штор и систем безопасности на базе Apple Home / Алисы.",
    "tags": [
      "Умный дом",
      "IoT",
      "Автоматизация"
    ],
    "previewGradient": "from-cyan-500 to-emerald-600",
    "previewSvg": "smarthome",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>OmniDom — Системы Умного Дома</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-950 text-neutral-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-neutral-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-cyan-400\"><i data-lucide=\"home\" class=\"w-5 h-5\"></i> OMNIDOM</div>\n    <button class=\"bg-cyan-500 text-neutral-950 font-bold px-4 py-2 rounded-xl text-xs\">Калькулятор проекта</button>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Ваш дом предугадывает ваши желания</h1>\n    <p class=\"text-neutral-400 text-sm max-w-xl mb-8\">Управление голосом, сценарии «Ушел из дома» и защита от протечек воды с автоматическим перекрытием кранов.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-6 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <i data-lucide=\"thermometer\" class=\"w-6 h-6 text-cyan-400 mb-2\"></i>\n        <h4 class=\"font-bold text-white mb-1\">Климат-контроль</h4>\n        <p class=\"text-xs text-neutral-400\">Автоматическая поддержка идеальной температуры и влажности в каждой комнате.</p>\n      </div>\n      <div class=\"p-6 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <i data-lucide=\"sun\" class=\"w-6 h-6 text-cyan-400 mb-2\"></i>\n        <h4 class=\"font-bold text-white mb-1\">Биодинамический свет</h4>\n        <p class=\"text-xs text-neutral-400\">Плавное изменение теплоты и яркости освещения в зависимости от времени суток.</p>\n      </div>\n      <div class=\"p-6 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <i data-lucide=\"shield-check\" class=\"w-6 h-6 text-cyan-400 mb-2\"></i>\n        <h4 class=\"font-bold text-white mb-1\">Безопасность 360°</h4>\n        <p class=\"text-xs text-neutral-400\">Датчики газа, движения, взлома и умный домофон с видеозаписью на телефон.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "language-tutor",
    "category": "Образование",
    "name": "LinguaFlow — Английский онлайн",
    "desc": "Индивидуальные уроки английского языка с носителями из Великобритании и США.",
    "tags": [
      "Языки",
      "Английский",
      "Обучение"
    ],
    "previewGradient": "from-red-500 to-amber-600",
    "previewSvg": "lang",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>LinguaFlow — Свободный английский</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-amber-400\"><i data-lucide=\"globe\" class=\"w-5 h-5\"></i> LINGUAFLOW</div>\n    <button class=\"bg-amber-400 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs\">Бесплатный пробный урок</button>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12 text-center\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Заговори на английском уже через 3 месяца</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mx-auto mb-8\">Никакой скучной зубрежки правил. 80% времени урока — разговорная практика на интересные жизненные темы.</p>\n    <div class=\"grid md:grid-cols-3 gap-6 text-left\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Разговорный интенсив</h4>\n        <p class=\"text-xs text-slate-400\">Преодолей языковой барьер для путешествий и знакомств.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Business & IT English</h4>\n        <p class=\"text-xs text-slate-400\">Подготовка к собеседованиям в международные компании и деловой переписке.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Сдача IELTS & TOEFL</h4>\n        <p class=\"text-xs text-slate-400\">Стратегии сдачи на балл 7.5+ для поступления в зарубежные вузы.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "tea-house",
    "category": "Кафе",
    "name": "ZenLeaf — Китайский чайный клуб",
    "desc": "Коллекционный пуэр, улуны Да Хун Пао, традиционные чайные церемонии и глиняная посуда.",
    "tags": [
      "Чай",
      "Церемония",
      "Релакс"
    ],
    "previewGradient": "from-emerald-800 to-stone-900",
    "previewSvg": "tea",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>ZenLeaf — Чайное пространство</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#151916] text-stone-200 min-h-screen font-serif\">\n  <header class=\"p-8 text-center border-b border-emerald-950/60\">\n    <div class=\"text-2xl font-bold tracking-widest text-emerald-300\">ZEN LEAF</div>\n    <div class=\"text-xs font-sans text-stone-400 mt-1\">Традиции китайского чаепития Пин Ча и Гун Фу Ча</div>\n  </header>\n  <main class=\"max-w-3xl mx-auto p-6 py-12 font-sans space-y-8\">\n    <div class=\"text-center\">\n      <h1 class=\"text-3xl font-serif text-stone-100\">Остановитесь и почувствуйте вкус момента</h1>\n      <p class=\"text-xs text-stone-400 mt-2\">Прямые поставки с высокогорных плантаций провинций Юньнань и Фуцзянь.</p>\n    </div>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"p-5 bg-stone-900/60 border border-emerald-900/30 rounded-2xl\">\n        <h3 class=\"font-serif font-bold text-emerald-200 mb-2\">Шу Пуэр Гунтин (10 лет)</h3>\n        <p class=\"text-xs text-stone-400 mb-2\">Глубокий древесно-ореховый вкус с нотами горького шоколада.</p>\n        <span class=\"font-bold text-amber-400 text-sm\">650 ₽ / церемония</span>\n      </div>\n      <div class=\"p-5 bg-stone-900/60 border border-emerald-900/30 rounded-2xl\">\n        <h3 class=\"font-serif font-bold text-emerald-200 mb-2\">Утесный Да Хун Пао</h3>\n        <p class=\"text-xs text-stone-400 mb-2\">Знаменитый Большой Красный Халат с ярким медово-дымным послевкусием.</p>\n        <span class=\"font-bold text-amber-400 text-sm\">750 ₽ / церемония</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "book-store",
    "category": "Магазин",
    "name": "PageTurn — Независимый книжный",
    "desc": "Редкие иллюстрированные издания, философия, современная проза и виниловые пластинки.",
    "tags": [
      "Книги",
      "Культура",
      "Магазин"
    ],
    "previewGradient": "from-amber-800 to-stone-900",
    "previewSvg": "book",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>PageTurn — Независимый книжный магазин</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#fcfaf7] text-stone-900 min-h-screen font-serif\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-stone-200\">\n    <div class=\"text-2xl font-bold tracking-tight text-amber-950\">PAGETURN</div>\n    <div class=\"text-xs font-sans text-stone-500\">Книги, меняющие угол зрения</div>\n  </nav>\n  <main class=\"max-w-5xl mx-auto p-6 py-10 font-sans\">\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-44 bg-stone-100 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold font-serif\">[Обложка книги]</div>\n        <h3 class=\"font-serif font-bold text-base\">Искусство мыслить масштабно</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Твердый переплет, дизайнерская бумага.</p>\n        <span class=\"font-bold text-amber-900\">890 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-44 bg-stone-100 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold font-serif\">[Обложка книги]</div>\n        <h3 class=\"font-serif font-bold text-base\">История визуальной культуры</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Альбом с 400 цветными иллюстрациями.</p>\n        <span class=\"font-bold text-amber-900\">2 400 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-44 bg-stone-100 rounded-xl mb-4 flex items-center justify-center text-stone-400 text-xs font-bold font-serif\">[Винил]</div>\n        <h3 class=\"font-serif font-bold text-base\">Miles Davis — Kind of Blue (Vinyl)</h3>\n        <p class=\"text-xs text-stone-500 mb-2\">Оригинальное 180-граммовое переиздание.</p>\n        <span class=\"font-bold text-amber-900\">3 800 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "car-rental",
    "category": "Авто",
    "name": "ApexDrive — Прокат спорткаров",
    "desc": "Аренда Porsche 911, Mustang и BMW M4 без водителя с быстрой доставкой к отелю или в аэропорт.",
    "tags": [
      "Авто",
      "Спорткары",
      "Аренда"
    ],
    "previewGradient": "from-red-600 via-zinc-900 to-black",
    "previewSvg": "sportcar",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>ApexDrive — Прокат спорткаров в Москве</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-black text-white min-h-screen\">\n  <nav class=\"max-w-6xl mx-auto p-6 flex justify-between items-center border-b border-zinc-900\">\n    <div class=\"text-xl font-black italic tracking-widest text-red-500 flex items-center gap-2\"><i data-lucide=\"gauge\" class=\"w-6 h-6\"></i> APEXDRIVE</div>\n    <button class=\"bg-red-600 text-white font-bold px-4 py-2 rounded-xl text-xs uppercase tracking-wider\">Забронировать</button>\n  </nav>\n  <main class=\"max-w-6xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black uppercase mb-4\">Эмоции от вождения настоящего спорткара</h1>\n    <p class=\"text-zinc-400 text-sm max-w-lg mb-8\">Никаких наклеек каршеринга. Чистые автомобили с полным баком и КАСКО без франшизы.</p>\n    <div class=\"grid md:grid-cols-2 gap-8\">\n      <div class=\"bg-zinc-900 border border-zinc-800 rounded-3xl p-6\">\n        <div class=\"h-44 bg-zinc-800 rounded-2xl mb-4 flex items-center justify-center text-zinc-500 font-bold\">[Porsche 911 Carrera S — 450 л.с.]</div>\n        <div class=\"flex justify-between items-start mb-2\">\n          <h3 class=\"text-xl font-bold\">Porsche 911 Carrera S</h3>\n          <span class=\"text-red-400 font-extrabold text-lg\">35 000 ₽ / сутки</span>\n        </div>\n        <p class=\"text-xs text-zinc-400 mb-4\">Разгон до 100 км/ч за 3.5 сек. Спортивный выхлоп.</p>\n        <button class=\"w-full bg-white text-black font-bold py-2.5 rounded-xl text-xs\">Выбрать даты</button>\n      </div>\n      <div class=\"bg-zinc-900 border border-zinc-800 rounded-3xl p-6\">\n        <div class=\"h-44 bg-zinc-800 rounded-2xl mb-4 flex items-center justify-center text-zinc-500 font-bold\">[BMW M4 Competition — 510 л.с.]</div>\n        <div class=\"flex justify-between items-start mb-2\">\n          <h3 class=\"text-xl font-bold\">BMW M4 Competition</h3>\n          <span class=\"text-red-400 font-extrabold text-lg\">28 000 ₽ / сутки</span>\n        </div>\n        <p class=\"text-xs text-zinc-400 mb-4\">Полный привод xDrive, карбоновые ковши.</p>\n        <button class=\"w-full bg-white text-black font-bold py-2.5 rounded-xl text-xs\">Выбрать даты</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "solar-energy",
    "category": "Технологии",
    "name": "SolarSun — Солнечные станции",
    "desc": "Установка солнечных батарей и накопителей энергии для загородных домов и производств.",
    "tags": [
      "Энергия",
      "Солнце",
      "Зеленые технологии"
    ],
    "previewGradient": "from-amber-500 to-emerald-600",
    "previewSvg": "solar",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>SolarSun — Автономная солнечная энергия</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-amber-400\"><i data-lucide=\"sun\" class=\"w-5 h-5\"></i> SOLARSUN</div>\n    <button class=\"bg-amber-400 text-slate-950 font-bold px-4 py-2 rounded-xl text-xs\">Расчет окупаемости</button>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Энергетическая независимость вашего дома</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">Сократите счета за электричество до 80%. Бесперебойное питание при любых авариях на внешней электросети.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Комплект «Дача 5 кВт»</h4>\n        <p class=\"text-xs text-slate-400 mb-4\">Освещение, холодильник, насос и ТВ без ограничений.</p>\n        <span class=\"text-amber-400 font-bold text-sm\">290 000 ₽</span>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Комплект «Дом 15 кВт»</h4>\n        <p class=\"text-xs text-slate-400 mb-4\">Полная автономия коттеджа, кондиционеры и отопление.</p>\n        <span class=\"text-amber-400 font-bold text-sm\">680 000 ₽</span>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Накопители LiFePO4</h4>\n        <p class=\"text-xs text-slate-400 mb-4\">Литий-железо-фосфатные батареи со сроком службы 15 лет.</p>\n        <span class=\"text-amber-400 font-bold text-sm\">от 140 000 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "dance-school",
    "category": "Спорт & Здоровье",
    "name": "RhythmLab — Школа танцев",
    "desc": "Занятия по хип-хопу, High Heels, contemporary и растяжке для начинающих и про.",
    "tags": [
      "Танцы",
      "Спорт",
      "Школа"
    ],
    "previewGradient": "from-fuchsia-600 via-rose-500 to-amber-500",
    "previewSvg": "dance",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>RhythmLab — Танцевальная студия</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-950 text-neutral-100 min-h-screen\">\n  <header class=\"p-6 border-b border-neutral-800 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-black italic tracking-widest text-fuchsia-500\">RHYTHMLAB</div>\n    <button class=\"bg-fuchsia-600 hover:bg-fuchsia-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Пробное занятие 500 ₽</button>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black uppercase mb-4\">Раскрой свою пластику и уверенность в себе</h1>\n    <p class=\"text-neutral-400 text-sm max-w-lg mb-8\">Просторные залы с панорамными зеркалами, мощная акустика и поддерживающая дружеская атмосфера.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"p-5 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">High Heels</h4>\n        <p class=\"text-xs text-neutral-400\">Женственность, уверенная походка и яркая хореография на каблуках.</p>\n      </div>\n      <div class=\"p-5 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Hip-Hop & Choreography</h4>\n        <p class=\"text-xs text-neutral-400\">Кач, музыкальность и крутые связки под свежие треки.</p>\n      </div>\n      <div class=\"p-5 bg-neutral-900 border border-neutral-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Stretching & Здоровая спина</h4>\n        <p class=\"text-xs text-neutral-400\">Мягкая растяжка всех групп мышц и снятие зажимов после работы.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "optics-store",
    "category": "Магазин",
    "name": "FocusVision — Салон оптики",
    "desc": "Дизайнерские оправы из титана и ацетата, проверка зрения на японском авторефрактометре.",
    "tags": [
      "Оптика",
      "Очки",
      "Здоровье"
    ],
    "previewGradient": "from-teal-600 to-sky-700",
    "previewSvg": "glasses",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>FocusVision — Салон премиальной оптики</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-50 text-stone-900 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-stone-200\">\n    <div class=\"text-xl font-light tracking-widest text-teal-900\">FOCUS•VISION</div>\n    <span class=\"text-xs text-stone-500\">Бесплатная диагностика зрения при заказе очков</span>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl font-light tracking-wide mb-4\">Очки как главный акцент вашего стиля</h1>\n    <p class=\"text-stone-500 text-xs max-w-lg mb-8\">Японские линзы Hoya с защитой от синего спектра экранов и антибликовым покрытием.</p>\n    <div class=\"grid md:grid-cols-3 gap-6\">\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 text-xs font-bold\">[Титановая оправа Silhouette]</div>\n        <h4 class=\"font-bold text-sm\">Ультралегкий титан</h4>\n        <p class=\"text-xs text-stone-500 my-1\">Вес всего 4 грамма, не оставляет следов на переносице.</p>\n        <span class=\"font-bold text-teal-800 text-sm\">16 900 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 text-xs font-bold\">[Ацетат Mazzucchelli]</div>\n        <h4 class=\"font-bold text-sm\">Итальянский ацетат</h4>\n        <p class=\"text-xs text-stone-500 my-1\">Глубокий черепаховый оттенок, винтажная геометрия.</p>\n        <span class=\"font-bold text-teal-800 text-sm\">14 200 ₽</span>\n      </div>\n      <div class=\"bg-white p-5 rounded-2xl border border-stone-200\">\n        <div class=\"h-32 bg-stone-100 rounded-xl mb-3 flex items-center justify-center text-stone-400 text-xs font-bold\">[Солнцезащитные поляризованные]</div>\n        <h4 class=\"font-bold text-sm\">Поляризационные очки</h4>\n        <p class=\"text-xs text-stone-500 my-1\">100% защита от ультрафиолета UV400.</p>\n        <span class=\"font-bold text-teal-800 text-sm\">11 800 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "game-developer",
    "category": "Гейминг",
    "name": "PixelForge — Инди-студия игр",
    "desc": "Разработка захватывающих пиксельных RPG и платформеров на Unreal Engine 5.",
    "tags": [
      "Игры",
      "Gamedev",
      "PixelArt"
    ],
    "previewGradient": "from-purple-600 via-indigo-600 to-cyan-500",
    "previewSvg": "gamedev",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>PixelForge Games — Создаем миры</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <header class=\"p-6 border-b border-slate-800 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-black text-cyan-400 flex items-center gap-2\"><i data-lucide=\"gamepad-2\" class=\"w-6 h-6\"></i> PIXELFORGE</div>\n    <span class=\"text-xs text-slate-400 font-mono\">Wishlist on Steam</span>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <div class=\"bg-slate-900 border border-cyan-500/30 rounded-3xl p-8 mb-8\">\n      <span class=\"text-xs font-mono text-cyan-400 uppercase\">Флагманский проект • Релиз осень 2026</span>\n      <h1 class=\"text-3xl md:text-5xl font-black mt-2 mb-4 text-white\">Chronicles of Aetheria</h1>\n      <p class=\"text-slate-400 text-sm max-w-xl mb-6\">Тактическая пошаговая RPG с глубокой историей, процедурно генерируемыми подземельями и авторским оркестровым саундтреком.</p>\n      <div class=\"flex gap-4\">\n        <button class=\"bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-black px-6 py-3 rounded-2xl text-xs uppercase tracking-wider\">Добавить в желаемое Steam</button>\n        <button class=\"border border-slate-700 bg-slate-800 text-white font-bold px-6 py-3 rounded-2xl text-xs\">Трейлер игры</button>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "eco-house",
    "category": "Архитектура",
    "name": "WoodCraft — Модульные дома",
    "desc": "Скандинавские модульные дома с чистовой отделкой, доставкой на участок и сборкой за 45 дней.",
    "tags": [
      "Дома",
      "Модули",
      "Дерево"
    ],
    "previewGradient": "from-amber-800 to-green-900",
    "previewSvg": "barn",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>WoodCraft — Скандинавские модульные дома</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-stone-900 text-stone-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-stone-800\">\n    <div class=\"text-xl font-bold tracking-tight text-amber-400\">WOODCRAFT HOMES</div>\n    <button class=\"bg-amber-500 text-stone-950 font-bold px-4 py-2 rounded-xl text-xs\">Экскурсия на производство</button>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-light mb-4\">Готовый теплый дом для круглогодичного проживания</h1>\n    <p class=\"text-stone-400 text-sm max-w-xl mb-8\">Утепление 200 мм минеральной ватой, панорамные стеклопакеты и скрытая разводка всех коммуникаций.</p>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"bg-stone-800 border border-stone-700 p-6 rounded-2xl\">\n        <h3 class=\"font-bold text-lg mb-1\">Модуль «Scandi 45»</h3>\n        <p class=\"text-xs text-stone-400 mb-4\">Площадь 45 м²: кухня-гостиная, спальня, санузел и терраса 15 м².</p>\n        <span class=\"text-amber-400 font-bold text-xl\">2 950 000 ₽</span>\n      </div>\n      <div class=\"bg-stone-800 border border-stone-700 p-6 rounded-2xl\">\n        <h3 class=\"font-bold text-lg mb-1\">Модуль «Scandi Family 85»</h3>\n        <p class=\"text-xs text-stone-400 mb-4\">Площадь 85 м²: 2 отдельные спальни, просторная гостиная, сауна.</p>\n        <span class=\"text-amber-400 font-bold text-xl\">4 850 000 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "craft-beer",
    "category": "Рестораны & Кафе",
    "name": "HopCraft — Крафтовый паб",
    "desc": "32 крана свежего разливного пива, сочные бургеры на бриоши и трансляции матчей.",
    "tags": [
      "Паб",
      "Крафт",
      "Бургеры"
    ],
    "previewGradient": "from-amber-600 via-orange-800 to-neutral-950",
    "previewSvg": "beer",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>HopCraft — Крафтовый бар & Гриль</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-neutral-950 text-neutral-100 min-h-screen\">\n  <header class=\"p-6 border-b border-neutral-800 flex justify-between items-center max-w-4xl mx-auto\">\n    <div class=\"text-xl font-black text-amber-500 uppercase tracking-widest\">HOPCRAFT BAR</div>\n    <span class=\"text-xs text-neutral-400\">Пн-Вс: 15:00 - 02:00</span>\n  </header>\n  <main class=\"max-w-3xl mx-auto p-6 py-10 space-y-6\">\n    <h2 class=\"text-2xl font-bold text-amber-100\">На кранах прямо сейчас</h2>\n    <div class=\"bg-neutral-900 border border-neutral-800 rounded-2xl p-5 space-y-3\">\n      <div class=\"flex justify-between items-baseline border-b border-neutral-800 pb-2\">\n        <div><div class=\"font-bold text-sm text-white\">Citra Hazy New England IPA</div><div class=\"text-xs text-neutral-400\">ABV 6.8% • IBU 45 • Тропические цитрусы и сочная мутность</div></div>\n        <span class=\"font-bold text-amber-400\">420 ₽ / 0.4л</span>\n      </div>\n      <div class=\"flex justify-between items-baseline border-b border-neutral-800 pb-2\">\n        <div><div class=\"font-bold text-sm text-white\">Imperial Chocolate Stout</div><div class=\"text-xs text-neutral-400\">ABV 9.5% • IBU 30 • Плотный десертный стаут с какао-бобами</div></div>\n        <span class=\"font-bold text-amber-400\">480 ₽ / 0.33л</span>\n      </div>\n      <div class=\"flex justify-between items-baseline\">\n        <div><div class=\"font-bold text-sm text-white\">Raspberry Sour Ale</div><div class=\"text-xs text-neutral-400\">ABV 5.2% • Освежающий кислый эль со свежей малиной</div></div>\n        <span class=\"font-bold text-amber-400\">390 ₽ / 0.4л</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "drone-delivery",
    "category": "Технологии",
    "name": "SkyDrop — Дрон-доставка",
    "desc": "Быстрая доставка медикаментов и посылок дронами за 15 минут в радиусе 20 км.",
    "tags": [
      "Дроны",
      "AI",
      "Доставка"
    ],
    "previewGradient": "from-blue-500 via-cyan-500 to-indigo-700",
    "previewSvg": "skydrop",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>SkyDrop — Автономная доставка посылок</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-cyan-400\"><i data-lucide=\"navigation\" class=\"w-5 h-5\"></i> SKYDROP</div>\n    <span class=\"text-xs text-slate-400\">Экологично • 0 выбросов CO2</span>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12 text-center\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Доставка по воздуху быстрее, чем остынет кофе</h1>\n    <p class=\"text-slate-400 text-sm max-w-lg mx-auto mb-8\">Беспилотники облетают дорожные пробки на высоте 100 метров и точно спускают посылку прямо на вашу лужайку.</p>\n    <div class=\"grid md:grid-cols-3 gap-6 text-left\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">15 минут среднее время</h4>\n        <p class=\"text-xs text-slate-400\">Скорость полета до 90 км/ч независимо от трафика.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Грузоподъемность 5 кг</h4>\n        <p class=\"text-xs text-slate-400\">Термоизолированный отсек для горячей еды и лекарств.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h4 class=\"font-bold text-white mb-1\">Компьютерное зрение</h4>\n        <p class=\"text-xs text-slate-400\">Датчики LiDAR определяют безопасную точку посадки без людей и проводов.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "financial-advisor",
    "category": "Финансы",
    "name": "WealthPlan — Инвестиционный советник",
    "desc": "Составление диверсифицированного инвестиционного портфеля акций, облигаций и золота.",
    "tags": [
      "Инвестиции",
      "Финансы",
      "Активы"
    ],
    "previewGradient": "from-emerald-700 via-teal-800 to-slate-900",
    "previewSvg": "wealth",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>WealthPlan — Персональный финансовый план</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <header class=\"p-6 border-b border-slate-800 flex justify-between items-center max-w-5xl mx-auto\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-emerald-400\"><i data-lucide=\"trending-up\" class=\"w-5 h-5\"></i> WEALTHPLAN</div>\n    <button class=\"bg-emerald-600 hover:bg-emerald-500 text-white font-bold px-4 py-2 rounded-xl text-xs\">Получить аудит портфеля</button>\n  </header>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-extrabold mb-4\">Формируйте пассивный доход и защищайте капитал от инфляции</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">Индивидуальная стратегия накоплений с учетом вашего риск-профиля и горизонта планирования.</p>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <span class=\"text-xs font-bold text-emerald-400 uppercase\">Доходность 16-19% годовых</span>\n        <h3 class=\"text-xl font-bold mt-1 mb-2\">Облигационный консервативный</h3>\n        <p class=\"text-xs text-slate-400\">Надежные ОФЗ и корпоративные бонды первого эшелона с ежемесячным купоном.</p>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <span class=\"text-xs font-bold text-emerald-400 uppercase\">Потенциал роста 25%+</span>\n        <h3 class=\"text-xl font-bold mt-1 mb-2\">Сбалансированный дивидендный</h3>\n        <p class=\"text-xs text-slate-400\">Акции лидеров рынка, золото и замещающие еврооблигации.</p>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "ceramic-workshop",
    "category": "Услуги",
    "name": "ClayArt — Мастерская керамики",
    "desc": "Мастер-классы за гончарным кругом, ручная лепка кружек и создание авторских тарелок.",
    "tags": [
      "Керамика",
      "Творчество",
      "Хобби"
    ],
    "previewGradient": "from-amber-700 via-stone-700 to-stone-900",
    "previewSvg": "clay",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>ClayArt — Студия ручной керамики</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-[#f6f2ec] text-stone-900 min-h-screen font-serif\">\n  <header class=\"p-8 text-center border-b border-stone-200\">\n    <div class=\"text-2xl font-bold text-amber-900\">CLAY ART</div>\n    <div class=\"text-xs font-sans text-stone-500 mt-1\">Тепло глины и магия ваших рук</div>\n  </header>\n  <main class=\"max-w-3xl mx-auto p-6 py-12 font-sans space-y-8\">\n    <div class=\"text-center\">\n      <h1 class=\"text-3xl font-serif text-stone-900\">Создайте свою первую чашку сами</h1>\n      <p class=\"text-xs text-stone-600 mt-2\">После обжига и глазурования посудой можно пользоваться дома каждый день.</p>\n    </div>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"bg-white p-6 rounded-2xl border border-stone-200 shadow-sm\">\n        <h3 class=\"font-serif font-bold text-lg mb-1\">Свидание за гончарным кругом</h3>\n        <p class=\"text-xs text-stone-500 mb-4\">2 часа вдвоем, бокалы вина, свечи и 2 готовых изделия.</p>\n        <span class=\"font-bold text-amber-900 text-base\">5 500 ₽ за пару</span>\n      </div>\n      <div class=\"bg-white p-6 rounded-2xl border border-stone-200 shadow-sm\">\n        <h3 class=\"font-serif font-bold text-lg mb-1\">Групповой мастер-класс</h3>\n        <p class=\"text-xs text-stone-500 mb-4\">Лепка тарелочек с ботаническими отпечатками трав.</p>\n        <span class=\"font-bold text-amber-900 text-base\">2 400 ₽ / чел</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  },
  {
    "id": "clean-air",
    "category": "Технологии",
    "name": "PureAura — Очистители воздуха",
    "desc": "Интеллектуальные бризеры и приточная вентиляция с HEPA H14 фильтрацией для квартир.",
    "tags": [
      "Экология",
      "Дом",
      "Здоровье"
    ],
    "previewGradient": "from-sky-400 via-teal-500 to-blue-700",
    "previewSvg": "air",
    "html": "<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n  <meta charset=\"UTF-8\">\n  <title>PureAura — Чистый горный воздух в квартире</title>\n  <script src=\"https://cdn.tailwindcss.com\"></script>\n  <script src=\"https://unpkg.com/lucide@latest\"></script>\n</head>\n<body class=\"bg-slate-950 text-slate-100 min-h-screen\">\n  <nav class=\"max-w-5xl mx-auto p-6 flex justify-between items-center border-b border-slate-800\">\n    <div class=\"text-xl font-bold flex items-center gap-2 text-sky-400\"><i data-lucide=\"wind\" class=\"w-5 h-5\"></i> PUREAURA</div>\n    <span class=\"text-xs text-slate-400\">Уровень шума всего 19 дБ • Бесшумный ночной режим</span>\n  </nav>\n  <main class=\"max-w-4xl mx-auto p-6 py-12\">\n    <h1 class=\"text-3xl md:text-5xl font-black mb-4\">Дышите чистым воздухом без пыли, пыльцы и выхлопных газов</h1>\n    <p class=\"text-slate-400 text-sm max-w-xl mb-8\">Многоступенчатая фильтрация задерживает 99.97% аллергенов, бактерий и микрочастиц PM2.5 с улицы при закрытых окнах.</p>\n    <div class=\"grid md:grid-cols-2 gap-6\">\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h3 class=\"text-xl font-bold mb-1\">Бризер PureAura Pro</h3>\n        <p class=\"text-xs text-slate-400 mb-4\">Приток свежего воздуха до 160 м³/час с подогревом в мороз до -30°C.</p>\n        <span class=\"text-sky-400 font-bold text-xl\">49 900 ₽</span>\n      </div>\n      <div class=\"p-6 bg-slate-900 border border-slate-800 rounded-2xl\">\n        <h3 class=\"text-xl font-bold mb-1\">Мойка воздуха HydroPure</h3>\n        <p class=\"text-xs text-slate-400 mb-4\">Естественное холодное увлажнение без белого налета на мебели.</p>\n        <span class=\"text-sky-400 font-bold text-xl\">27 500 ₽</span>\n      </div>\n    </div>\n  </main>\n  <script>lucide.createIcons();</script>\n</body>\n</html>"
  }
];
