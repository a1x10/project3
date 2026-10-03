"""Игры и развлечения: «Города», викторина, «Угадай число», загадки, «Камень, ножницы, бумага»,
сказки на ночь, анекдоты, монетка и кубик. Эмоции Стеллы меняются по ходу игры."""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path

from ..nlp.numbers import plural, words_to_number
from ..nlp.text import clean, similarity, stem
from .base import Reply, Skill, intent

DATA = Path(__file__).resolve().parent.parent / "data"

RIDDLES = [
    ("Зимой и летом одним цветом.", ["ёлка", "ель", "елка", "сосна"]),
    ("Сидит дед, во сто шуб одет. Кто его раздевает, тот слёзы проливает.", ["лук", "луковица"]),
    ("Без окон, без дверей, полна горница людей.", ["огурец"]),
    ("Висит груша — нельзя скушать.", ["лампочка", "лампа"]),
    ("Не лает, не кусает, а в дом не пускает.", ["замок"]),
    ("Что можно увидеть с закрытыми глазами?", ["сон", "сны"]),
    ("Два конца, два кольца, посередине гвоздик.", ["ножницы"]),
    ("Кто ходит сидя?", ["шахматист", "шахматы"]),
    ("Чем больше из неё берёшь, тем больше она становится.", ["яма"]),
    ("Что принадлежит тебе, но другие пользуются этим чаще?", ["имя"]),
    ("Красная девица сидит в темнице, а коса на улице.", ["морковь", "морковка"]),
    ("Течёт, течёт — не вытечет, бежит, бежит — не выбежит.", ["река"]),
    ("Сто одёжек и все без застёжек.", ["капуста", "кочан"]),
    ("Не море, не земля, корабли не плавают, а ходить нельзя.", ["болото"]),
    ("Что становится больше, если его поставить вверх ногами?", ["6", "шесть", "шестерка", "цифра 6"]),
    ("Летит — молчит, лежит — молчит, когда умрёт, тогда заревёт.", ["снег"]),
    ("Под землёй птица гнездо свила, яиц нанесла.", ["картошка", "картофель"]),
    ("Один глаз, один рог, но не носорог.", ["корова из-за угла", "корова"]),
    ("Что нельзя съесть на завтрак?", ["обед", "ужин", "обед и ужин"]),
    ("Хвост пушистый, мех золотистый, в лесу живёт, в деревне кур крадёт.", ["лиса", "лисица"]),
]
QUIZ = [
    ("Какая планета самая большая в Солнечной системе?", ["Юпитер", "Сатурн", "Земля"], 0),
    ("Сколько ног у паука?", ["Шесть", "Восемь", "Десять"], 1),
    ("Какой город является столицей Австралии?", ["Сидней", "Мельбурн", "Канберра"], 2),
    ("Кто написал «Евгения Онегина»?", ["Лермонтов", "Пушкин", "Толстой"], 1),
    ("Какой химический символ у золота?", ["Au", "Ag", "Zn"], 0),
    ("Сколько дней в високосном году?", ["365", "366", "364"], 1),
    ("Какое самое глубокое озеро в мире?", ["Байкал", "Танганьика", "Виктория"], 0),
    ("Кто изобрёл радио по версии российских учебников?", ["Эдисон", "Попов", "Тесла"], 1),
    ("В каком году человек впервые полетел в космос?", ["1957", "1961", "1969"], 1),
    ("Какой самый большой океан?", ["Атлантический", "Индийский", "Тихий"], 2),
    ("Сколько цветов у радуги?", ["Семь", "Шесть", "Восемь"], 0),
    ("Какое животное самое быстрое на суше?", ["Лев", "Гепард", "Антилопа"], 1),
    ("Кто написал картину «Чёрный квадрат»?", ["Кандинский", "Малевич", "Шагал"], 1),
    ("Сколько игроков в футбольной команде на поле?", ["Десять", "Одиннадцать", "Двенадцать"], 1),
    ("Какая самая длинная река в России?", ["Волга", "Лена", "Обь с Иртышом"], 2),
    ("Из чего состоит вода?", ["Водород и кислород", "Азот и кислород", "Углерод и водород"], 0),
    ("Какая птица не умеет летать?", ["Пингвин", "Ласточка", "Чайка"], 0),
    ("Сколько континентов на Земле?", ["Пять", "Шесть", "Семь"], 2),
    ("Как называется самая высокая гора в мире?", ["Эльбрус", "Эверест", "Килиманджаро"], 1),
    ("Сколько секунд в одном часе?", ["3600", "6000", "360"], 0),
]
JOKES = [
    "Программист ставит на тумбочку два стакана: один с водой — если захочет пить, второй пустой — если не захочет.",
    "— Алло, это служба поддержки? У меня робот-пылесос сбежал. — Вы его выключали? — Нет. — Тогда ждите, он вернётся, когда сядет батарейка.",
    "Встречаются два ассистента. Один говорит: «Меня сегодня спросили, в чём смысл жизни». Второй: «И что ты ответил?» — «Поставил таймер на 42 минуты».",
    "Учитель: «Вовочка, назови пять животных Африки». Вовочка: «Три льва и два жирафа!»",
    "Почему математики не ходят в лес? Потому что там слишком много корней.",
    "Купил умную колонку. Теперь в доме два умных — колонка и кот.",
    "Говорят, ИИ скоро заменит людей. Не знаю, меня пока даже будильник не может заменить — я его переставляю.",
    "Оптимист изучает английский, пессимист — китайский, а реалист — автомат Калашникова. А я изучаю тебя!",
    "— Доктор, у меня бессонница. — Считайте овец. — Досчитал до миллиона, потом пришлось вставать на работу.",
    "Кот — это маленький диван, который любит лежать на большом диване.",
]
TALES = [
    ("о ёжике и звёздочке",
     "Жил-был маленький ёжик. Каждый вечер он смотрел на небо и мечтал подружиться со звёздочкой. Однажды одна звёздочка "
     "упала прямо в траву у его норки. «Мне так одиноко на небе», — сказала она. Ёжик напоил её чаем с малиной, и они "
     "болтали до самого утра. А когда звёздочке пришло время возвращаться, она пообещала каждую ночь светить ярче всех — "
     "чтобы ёжик всегда находил дорогу домой. С тех пор, если увидишь самую яркую звезду, знай: это она светит своему другу. "
     "Спокойной ночи."),
    ("о добром драконе",
     "В далёких горах жил дракон, который боялся огня. Другие драконы смеялись над ним, а он выращивал цветы и пел песни. "
     "Однажды зимой в деревне погасли все печки, и люди начали мёрзнуть. Дракон собрался с духом, тихонько дохнул — "
     "и зажёг огонь в каждом доме, не обжёг ни одного цветка. С тех пор его называли Хранителем тепла, а дети приносили ему "
     "в подарок семена самых красивых цветов. Спи сладко."),
    ("о маленьком роботе",
     "На одной кухне жил маленький робот, который умел только мигать лампочкой. Он очень хотел быть полезным. Ночью, когда "
     "все спали, он мигал так, чтобы котёнок не боялся темноты, а потерянная бабушкина пуговица блеснула и нашлась. Утром "
     "все удивлялись: кто же навёл порядок? А робот просто тихо мигал — ведь делать добро можно и без слов. Добрых снов."),
]


def last_letter(city: str) -> str:
    c = clean(city).replace("ё", "е")
    for ch in reversed(c):
        if ch.isalpha() and ch not in "ьъый":
            return ch
    return c[-1] if c else ""


class Games(Skill):
    name = "games"

    def __init__(self, a):
        super().__init__(a)
        path = DATA / "cities_ru.txt"
        self.cities = [x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] \
            if path.exists() else ["Москва", "Анапа", "Астрахань"]
        self._norm_cities = {clean(c).replace("ё", "е"): c for c in self.cities}
        self.state: dict = {}

    # ---------------------------------------------------------------- города --
    @intent(r"\b(?:давай |сыграем |поиграем |играть |игра )?(?:в )?города\b(?!.*\b(?:погод|пробк)\w*)", priority=60,
            fun=True)
    def cities_start(self, ctx):
        if not re.search(r"\b(?:игра\w*|сыгра\w*|поигра\w*|давай)\b", ctx.norm) and ctx.norm.strip() != "города":
            return None
        first = random.choice(self.cities)
        self.state = {"game": "cities", "used": {clean(first).replace("ё", "е")}, "need": last_letter(first)}
        self.a.start_session(self, self._cities_turn, "города")
        return Reply(f"Давай! Я начинаю: {first}. Тебе на букву «{self.state['need'].upper()}».",
                     emotion="joy", expect_reply=True)

    def _city_known(self, name: str) -> str | None:
        n = clean(name).replace("ё", "е")
        if n in self._norm_cities:
            return self._norm_cities[n]
        try:  # проверяем по геокодеру — вдруг такой город есть, но его нет в моём списке
            d = self.a.get_json("https://geocoding-api.open-meteo.com/v1/search",
                                params={"name": name, "count": 1, "language": "ru"}, timeout=6, retries=0)
            r = (d.get("results") or [None])[0]
            if r and str(r.get("feature_code", "")).startswith("PPL") and \
                    clean(r.get("name", "")).replace("ё", "е") == n:
                return r["name"]
        except Exception:
            pass
        return None

    def _cities_turn(self, ctx):
        n = ctx.norm
        if re.search(r"\b(?:сдаюсь|не знаю|не помню|пас)\b", n):
            self.a.end_session()
            return Reply("Ура, я победила! Сыграем ещё как-нибудь.", emotion="joy")
        name = re.sub(r"^(?:город|мой город|ну|это)\s+", "", n).strip()
        city = self._norm_cities.get(clean(name).replace("ё", "е"))
        if not city and (len(name.split()) > 3 or self.a.matches_intent(ctx, exclude=self)):
            return None  # «включи музыку» посреди игры — это не город, пусть выполнят
        city = city or self._city_known(name)
        if not city:
            return Reply(f"Не знаю города «{name}». Назови другой на букву «{self.state['need'].upper()}».",
                         emotion="surprise", intensity=0.6, expect_reply=True)
        key = clean(city).replace("ё", "е")
        if key[0] != self.state["need"]:
            return Reply(f"Нужен город на букву «{self.state['need'].upper()}», а «{city}» — на «{key[0].upper()}».",
                         emotion="contempt", intensity=0.4, expect_reply=True)
        if key in self.state["used"]:
            return Reply(f"{city} уже был! Давай другой.", emotion="confidence", intensity=0.6, expect_reply=True)
        self.state["used"].add(key)
        letter = last_letter(city)
        options = [c for k, c in self._norm_cities.items() if k[0] == letter and k not in self.state["used"]]
        if not options:
            self.a.end_session()
            return Reply(f"На букву «{letter.upper()}» я больше не знаю городов. Ты победил! Поздравляю!",
                         emotion="surprise")
        mine = random.choice(options)
        self.state["used"].add(clean(mine).replace("ё", "е"))
        self.state["need"] = last_letter(mine)
        return Reply(f"{mine}. Тебе на «{self.state['need'].upper()}».", emotion="confidence", intensity=0.5,
                     expect_reply=True)

    # ------------------------------------------------------------- викторина --
    def _quiz_question(self):
        if self.a.brain.available:
            try:
                raw = self.a.brain.ask(
                    "Придумай один интересный вопрос для семейной викторины на русском языке с тремя вариантами ответа. "
                    "Ответь строго JSON без пояснений: {\"q\": \"вопрос\", \"options\": [\"…\", \"…\", \"…\"], "
                    "\"answer\": индекс правильного варианта 0-2}", temperature=0.9, max_tokens=300)
                m = re.search(r"\{.*\}", raw, re.S)
                d = json.loads(m.group(0))
                if len(d["options"]) == 3 and 0 <= int(d["answer"]) <= 2:
                    return d["q"], d["options"], int(d["answer"])
            except Exception as e:
                self.log.info("вопрос от GPT не получился: %s", e)
        unused = [q for q in QUIZ if q[0] not in self.state.get("asked", set())] or QUIZ
        return random.choice(unused)

    @intent(r"\b(?:викторин\w*|квиз|задай (?:мне )?вопрос|проверь мои знания)\b", priority=60, fun=True)
    def quiz_start(self, ctx):
        self.state = {"game": "quiz", "score": 0, "n": 0, "asked": set()}
        self.a.start_session(self, self._quiz_answer, "викторина")
        return self._ask_quiz("Начинаем викторину! Пять вопросов. ")

    def _ask_quiz(self, intro=""):
        q, opts, ans = self._quiz_question()
        self.state.update(q=q, opts=opts, ans=ans)
        self.state["asked"].add(q)
        self.state["n"] += 1
        return Reply(f"{intro}Вопрос {self.state['n']}. {q} Варианты: первый — {opts[0]}, второй — {opts[1]}, "
                     f"третий — {opts[2]}.", emotion="interest", expect_reply=True)

    def _quiz_answer(self, ctx):
        n = ctx.norm
        opts, ans = self.state["opts"], self.state["ans"]
        choice = None
        for i, w in enumerate(("перв", "втор", "трет")):
            if re.search(rf"\b{w}\w*", n):
                choice = i
        num = words_to_number(n)
        if choice is None and isinstance(num, int) and 1 <= num <= 3 and len(n.split()) <= 2:
            choice = num - 1
        if choice is None:
            scores = [similarity(n, o) for o in opts]
            if max(scores) >= 0.6:
                choice = scores.index(max(scores))
        if choice is None:
            if len(n.split()) > 5 or self.a.matches_intent(ctx, exclude=self):
                return None  # другая команда — игра подождёт
            return Reply("Скажи номер варианта: первый, второй или третий.", expect_reply=True)
        if choice == ans:
            self.state["score"] += 1
            verdict, emo = random.choice(["Правильно!", "Верно, умница!", "Точно!"]), "joy"
        else:
            verdict, emo = f"Не угадал. Правильный ответ — {opts[ans]}.", "sadness"
        if self.state["n"] >= 5:
            self.a.end_session()
            s = self.state["score"]
            final = "Блестяще!" if s >= 4 else "Неплохо!" if s >= 2 else "В следующий раз получится!"
            return Reply(f"{verdict} Игра окончена: {s} {plural(s, 'правильный ответ', 'правильных ответа', 'правильных ответов')}"
                         f" из 5. {final}", emotion="joy" if s >= 3 else "love")
        r = self._ask_quiz(verdict + " ")
        r.emotion = emo
        return r

    # ---------------------------------------------------------- угадай число --
    @intent(r"\bугадай(?:ка)? число\b|\bзагадай число\b|\bигра (?:в )?числа\b", priority=60, fun=True)
    def guess_start(self, ctx):
        self.state = {"game": "guess", "num": random.randint(1, 100), "tries": 0}
        self.a.start_session(self, self._guess_turn, "угадай число")
        return Reply("Я загадала число от 1 до 100. Попробуй угадать!", emotion="confidence", expect_reply=True)

    def _guess_turn(self, ctx):
        if re.search(r"\b(?:сдаюсь|не знаю)\b", ctx.norm):
            self.a.end_session()
            return Reply(f"Я загадала {self.state['num']}! Ничего, в следующий раз угадаешь.", emotion="joy")
        # ход — это число («50», «может быть 37», «наверное сорок»), а не «поставь будильник на 7»
        guess = re.fullmatch(r"(?:(?:это|может|быть|наверное|давай|число|ну|тогда|а|я думаю|думаю)\s+)*"
                             r"(\d+)(?:\s+(?:наверное|может быть|да))?", ctx.norm)
        val = int(guess.group(1)) if guess else None
        if val is None:
            if self.a.matches_intent(ctx, exclude=self) or len(ctx.norm.split()) > 3:
                return None
            return Reply("Назови число от 1 до 100.", expect_reply=True)
        self.state["tries"] += 1
        num, val = self.state["num"], int(val)
        if val == num:
            self.a.end_session()
            t = self.state["tries"]
            return Reply(f"Угадал! Это {num}. Тебе понадобилось {t} {plural(t, 'попытка', 'попытки', 'попыток')}.",
                         emotion="surprise" if t <= 5 else "joy")
        hint = "больше" if num > val else "меньше"
        close = " Уже очень близко!" if abs(num - val) <= 3 else ""
        return Reply(f"Моё число {hint}.{close}", emotion="interest" if close else "confidence", intensity=0.5,
                     expect_reply=True)

    # --------------------------------------------------------------- загадки --
    @intent(r"\b(?:загадай|загадывай|расскажи)\s+(?:мне\s+)?загадк\w*|\bзагадки\b", priority=59, fun=True)
    def riddle_start(self, ctx):
        q, answers = random.choice(RIDDLES)
        self.state = {"game": "riddle", "q": q, "a": answers, "tries": 0}
        self.a.start_session(self, self._riddle_answer, "загадка")
        return Reply(f"Слушай загадку. {q}", emotion="interest", expect_reply=True)

    def _riddle_answer(self, ctx):
        n = ctx.norm
        ans = self.state["a"]
        if re.search(r"\b(?:сдаюсь|не знаю|подскажи|какой ответ|скажи ответ)\b", n):
            self.a.end_session()
            self.state["ended"] = time.time()
            return Reply(f"Это {ans[0]}! Ещё загадку?", emotion="joy", expect_reply=True)
        words = {stem(w) for w in clean(n).split()}
        if any(stem(clean(a).split()[0]) in words or clean(a) in clean(n) for a in ans):
            self.a.end_session()
            self.state["ended"] = time.time()
            return Reply(random.choice(["Правильно! Ты молодец!", "Угадал! Здорово!", "Верно!"]) + " Ещё загадку?",
                         emotion="joy", expect_reply=True)
        if self.a.matches_intent(ctx, exclude=self):
            return None  # не ответ на загадку, а другая команда
        self.state["tries"] += 1
        if self.state["tries"] >= 3:
            self.a.end_session()
            return Reply(f"Не угадал. Ответ — {ans[0]}.", emotion="confidence")
        return Reply("Нет, подумай ещё.", emotion="contempt", intensity=0.3, expect_reply=True)

    @intent(r"^(?:да|давай|еще|ещё|конечно|хочу)(?: загадку)?$", priority=20)
    def more_riddle(self, ctx):
        if self.state.get("game") == "riddle" and time.time() - self.state.get("ended", 0) < 30:
            return self.riddle_start(ctx)
        return None

    # ---------------------------------------------------- камень, ножницы, бумага --
    @intent(r"\bкамень,? ножницы,? бумага\b|\bцу-е-фа\b", priority=60, fun=True)
    def rps_start(self, ctx):
        self.a.start_session(self, self._rps_turn, "камень-ножницы-бумага")
        return Reply("Давай! Раз, два, три — говори!", emotion="confidence", expect_reply=True)

    def _rps_turn(self, ctx):
        names = {"камен": "камень", "ножниц": "ножницы", "бумаг": "бумага"}
        you = next((v for k, v in names.items() if k in ctx.norm), None)
        if not you:
            self.a.end_session()
            return None
        me = random.choice(list(names.values()))
        beats = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
        if me == you:
            res, emo = "Ничья! Ещё раз?", "surprise"
        elif beats[me] == you:
            res, emo = "Я выиграла! Ещё?", "joy"
        else:
            res, emo = "Ты выиграл! Ещё раз?", "sadness"
        return Reply(f"У меня {me}. {res}", emotion=emo, expect_reply=True)

    # ------------------------------------------------------------- сказки --
    @intent(r"\bрасскажи\s+(?:мне\s+|нам\s+)?(?:сказку|историю на ночь|историю|сказочку)(?:\s+(?:про|о|об)\s+(.+))?$",
            priority=58, fun=True)
    def tale(self, ctx):
        about = ctx.raw_group(1)
        if self.a.brain.available:
            prompt = (f"Расскажи добрую сказку на ночь для ребёнка{' про ' + about if about else ''}, "
                      f"примерно 150–200 слов, спокойным тоном, со счастливым концом.")
            th = self.a.brain.think(prompt, long_form=True, use_history=False, temperature=0.9)
            if th.text:
                return Reply(th.text, emotion="love", intensity=0.6, card=th.text)
        title, text = random.choice(TALES)
        return Reply(f"Сказка {title}. {text}", emotion="love", intensity=0.6)

    @intent(r"\b(?:расскажи|скажи|знаешь)\s+(?:мне\s+)?(?:анекдот\w*|шутк\w*|что-нибудь смешное|прикол)\b|"
            r"\bпошути\b|\bрассмеши\b", priority=58, fun=True)
    def joke(self, ctx):
        if self.a.brain.available and random.random() < 0.5:
            th = self.a.brain.think("Расскажи короткий добрый смешной анекдот или шутку.", use_history=False,
                                    temperature=1.0)
            if th.text:
                return Reply(th.text, emotion="joy")
        return Reply(random.choice(JOKES), emotion="joy")

    @intent(r"\b(?:подбрось|подкинь|брось)\s+монет\w*|\bорел или решка\b", priority=58)
    def coin(self, ctx):
        return Reply(random.choice(["Орёл!", "Решка!"]), emotion="surprise", intensity=0.5)

    @intent(r"\b(?:брось|кинь|подбрось)\s+(?:игральн\w+\s+)?(?:кубик|кости)\b", priority=58)
    def dice(self, ctx):
        return Reply(f"Выпало {random.randint(1, 6)}.", emotion="surprise", intensity=0.4)

    @intent(r"\b(?:во что|давай) (?:поиграем|поиграть|играть)\b|\bсыграем\b|\bмне скучно\b|\bкакие (?:есть )?игры\b",
            priority=55, fun=True)
    def what_games(self, ctx):
        return Reply("Можем сыграть в города, викторину, «угадай число», загадки или «камень, ножницы, бумага». "
                     "А ещё могу рассказать сказку или анекдот. Что выберешь?", emotion="joy", expect_reply=True)
