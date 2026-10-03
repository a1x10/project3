"""Калькулятор, конвертер единиц и валют (курсы ЦБ РФ, криптовалюты)."""
from __future__ import annotations

import ast
import math
import operator
import re
import time

from ..nlp.numbers import fmt_num, plural
from .base import Reply, Skill, intent

# ------------------------------------------------------------ калькулятор --
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos,
        ast.FloorDiv: operator.floordiv}
_FUNCS = {"sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x), "sin": lambda x: math.sin(math.radians(x)),
          "cos": lambda x: math.cos(math.radians(x)), "tan": lambda x: math.tan(math.radians(x)),
          "ln": math.log, "log": math.log10, "fact": lambda x: math.factorial(int(x)), "abs": abs}
_CONST = {"pi": math.pi, "e": math.e}


def safe_eval(expr: str) -> float:
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name) and node.id in _CONST:
            return _CONST[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("слишком большая степень")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS \
                and len(node.args) == 1:
            arg = ev(node.args[0])
            if node.func.id == "fact" and arg > 170:
                raise ValueError("слишком большой факториал")
            return _FUNCS[node.func.id](arg)
        raise ValueError("недопустимое выражение")
    return ev(ast.parse(expr, mode="eval"))


_WORD_OPS = [
    (r"квадратный корень из", " sqrt "), (r"кубический корень из", " cbrt "), (r"корень (?:квадратный )?из", " sqrt "),
    (r"натуральный логарифм(?: от| из)?", " ln "), (r"(?:десятичный )?логарифм(?: от| из)?", " log "),
    (r"синус(?: от)?", " sin "), (r"косинус(?: от)?", " cos "), (r"тангенс(?: от)?", " tan "),
    (r"факториал(?: от| из)?", " fact "), (r"открыть скобку|открывается скобка|скобка открывается", " ( "),
    (r"закрыть скобку|закрывается скобка|скобка закрывается", " ) "),
    (r"умножить на|умножь на|помножить на|умноженное на|умножая на|помножь на|умножено на", " * "),
    (r"разделить на|делить на|поделить на|деленное на|поделенное на|подели на|раздели на|разделенное на", " / "),
    (r"в степени", " ** "), (r"в квадрате", " ** 2 "), (r"в кубе", " ** 3 "), (r"плюс|прибавить|сложить с", " + "),
    (r"минус|отнять|вычесть", " - "), (r"по модулю|остаток от деления на", " % "), (r"\bпи\b", " pi "),
    (r"(?<=\d)\s*[xх×]\s*(?=\d)", " * "), (r"(?<=\d)\s*:\s*(?=\d)", " / "), (r"градус\w*", " "),
]


def to_expression(text: str) -> str | None:
    t = " " + text + " "
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:процент\w*|%)\s*(?:от|из)\s*(\d+(?:\.\d+)?)", t)
    if m:
        return f"{m.group(1)} / 100 * {m.group(2)}"
    for pat, rep in _WORD_OPS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s+fact\b", r" fact(\1) ", t)  # «5 факториал»
    t = re.sub(r"\b(sqrt|cbrt|sin|cos|tan|ln|log|fact)\s+(\d+(?:\.\d+)?|pi|\([^()]*\))", r"\1(\2)", t)
    t = re.sub(r"\b(?:сколько будет|сколько|посчитай|вычисли|подсчитай|реши|будет|равно|чему равно|это|"
               r"пожалуйста|а|ну|стелла)\b", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not re.fullmatch(r"[\d\s.+\-*/%()a-z]+", t) or not re.search(r"\d|pi", t):
        return None
    if not re.search(r"[+\-*/%]|sqrt|cbrt|sin|cos|tan|ln|log|fact", t):
        return None
    return t


# ---------------------------------------------------------------- единицы --
# (основы для поиска, (1, 2, 5) формы, величина, множитель к базовой единице)
UNITS = [
    (("миллиметр ртутн", "мм рт"), ("миллиметр ртутного столба", "миллиметра ртутного столба",
                                     "миллиметров ртутного столба"), "pressure", 133.322),
    (("квадратн километр", "кв км"), ("квадратный километр", "квадратных километра", "квадратных километров"),
     "area", 1e6),
    (("квадратн метр", "кв м"), ("квадратный метр", "квадратных метра", "квадратных метров"), "area", 1.0),
    (("квадратн сантиметр",), ("квадратный сантиметр", "квадратных сантиметра", "квадратных сантиметров"), "area", 1e-4),
    (("квадратн фут",), ("квадратный фут", "квадратных фута", "квадратных футов"), "area", 0.092903),
    (("километр в час", "км в час", "км ч"), ("километр в час", "километра в час", "километров в час"), "speed", 1 / 3.6),
    (("метр в секунд", "м с"), ("метр в секунду", "метра в секунду", "метров в секунду"), "speed", 1.0),
    (("мил в час", "миль в час"), ("миля в час", "мили в час", "миль в час"), "speed", 0.44704),
    (("морск мил", "морских мил"), ("морская миля", "морские мили", "морских миль"), "length", 1852.0),
    (("лошадин сил",), ("лошадиная сила", "лошадиные силы", "лошадиных сил"), "power", 735.49875),
    (("столов ложк",), ("столовая ложка", "столовые ложки", "столовых ложек"), "volume", 0.015),
    (("чайн ложк",), ("чайная ложка", "чайные ложки", "чайных ложек"), "volume", 0.005),
    (("кубическ метр", "кубометр", "куб"), ("кубометр", "кубометра", "кубометров"), "volume", 1000.0),
    (("киловатт час", "квт ч"), ("киловатт-час", "киловатт-часа", "киловатт-часов"), "energy", 3.6e6),
    (("миллиметр", "мм"), ("миллиметр", "миллиметра", "миллиметров"), "length", 0.001),
    (("сантиметр", "см"), ("сантиметр", "сантиметра", "сантиметров"), "length", 0.01),
    (("дециметр",), ("дециметр", "дециметра", "дециметров"), "length", 0.1),
    (("километр", "км"), ("километр", "километра", "километров"), "length", 1000.0),
    (("метр", "м"), ("метр", "метра", "метров"), "length", 1.0),
    (("дюйм",), ("дюйм", "дюйма", "дюймов"), "length", 0.0254),
    (("фут",), ("фут", "фута", "футов"), "length", 0.3048),
    (("ярд",), ("ярд", "ярда", "ярдов"), "length", 0.9144),
    (("мил",), ("миля", "мили", "миль"), "length", 1609.344),
    (("верст",), ("верста", "версты", "вёрст"), "length", 1066.8),
    (("аршин",), ("аршин", "аршина", "аршин"), "length", 0.7112),
    (("саж",), ("сажень", "сажени", "саженей"), "length", 2.1336),
    (("миллиграмм", "мг"), ("миллиграмм", "миллиграмма", "миллиграммов"), "mass", 1e-6),
    (("килограмм", "кило", "кг"), ("килограмм", "килограмма", "килограммов"), "mass", 1.0),
    (("грамм", "гр", "г"), ("грамм", "грамма", "граммов"), "mass", 0.001),
    (("центнер",), ("центнер", "центнера", "центнеров"), "mass", 100.0),
    (("тонн", "т"), ("тонна", "тонны", "тонн"), "mass", 1000.0),
    (("фунт",), ("фунт", "фунта", "фунтов"), "mass", 0.45359237),
    (("унци",), ("унция", "унции", "унций"), "mass", 0.0283495),
    (("карат",), ("карат", "карата", "карат"), "mass", 0.0002),
    (("пуд",), ("пуд", "пуда", "пудов"), "mass", 16.38),
    (("миллилитр", "мл"), ("миллилитр", "миллилитра", "миллилитров"), "volume", 0.001),
    (("литр", "л"), ("литр", "литра", "литров"), "volume", 1.0),
    (("галлон",), ("галлон", "галлона", "галлонов"), "volume", 3.78541),
    (("пинт",), ("пинта", "пинты", "пинт"), "volume", 0.473176),
    (("баррел",), ("баррель", "барреля", "баррелей"), "volume", 158.987),
    (("стакан",), ("стакан", "стакана", "стаканов"), "volume", 0.25),
    (("узл", "узел"), ("узел", "узла", "узлов"), "speed", 0.514444),
    (("миллисекунд",), ("миллисекунда", "миллисекунды", "миллисекунд"), "time", 0.001),
    (("секунд", "сек"), ("секунда", "секунды", "секунд"), "time", 1.0),
    (("минут", "мин"), ("минута", "минуты", "минут"), "time", 60.0),
    (("час",), ("час", "часа", "часов"), "time", 3600.0),
    (("сут", "дн", "день"), ("день", "дня", "дней"), "time", 86400.0),
    (("недел",), ("неделя", "недели", "недель"), "time", 604800.0),
    (("месяц",), ("месяц", "месяца", "месяцев"), "time", 2629800.0),
    (("год", "лет"), ("год", "года", "лет"), "time", 31557600.0),
    (("век", "столет"), ("век", "века", "веков"), "time", 3155760000.0),
    (("гектар", "га"), ("гектар", "гектара", "гектаров"), "area", 1e4),
    (("сот", "ар"), ("сотка", "сотки", "соток"), "area", 100.0),
    (("акр",), ("акр", "акра", "акров"), "area", 4046.86),
    (("терабайт", "тб"), ("терабайт", "терабайта", "терабайт"), "data", 1024 ** 4),
    (("гигабайт", "гб"), ("гигабайт", "гигабайта", "гигабайт"), "data", 1024 ** 3),
    (("мегабайт", "мб"), ("мегабайт", "мегабайта", "мегабайт"), "data", 1024 ** 2),
    (("килобайт", "кб"), ("килобайт", "килобайта", "килобайт"), "data", 1024.0),
    (("байт",), ("байт", "байта", "байт"), "data", 1.0),
    (("бит",), ("бит", "бита", "бит"), "data", 0.125),
    (("килокалори", "ккал"), ("килокалория", "килокалории", "килокалорий"), "energy", 4184.0),
    (("калори", "кал"), ("калория", "калории", "калорий"), "energy", 4.184),
    (("килоджоул", "кдж"), ("килоджоуль", "килоджоуля", "килоджоулей"), "energy", 1000.0),
    (("джоул", "дж"), ("джоуль", "джоуля", "джоулей"), "energy", 1.0),
    (("киловатт", "квт"), ("киловатт", "киловатта", "киловатт"), "power", 1000.0),
    (("ватт", "вт"), ("ватт", "ватта", "ватт"), "power", 1.0),
    (("атмосфер", "атм"), ("атмосфера", "атмосферы", "атмосфер"), "pressure", 101325.0),
    (("килопаскал", "кпа"), ("килопаскаль", "килопаскаля", "килопаскалей"), "pressure", 1000.0),
    (("паскал", "па"), ("паскаль", "паскаля", "паскалей"), "pressure", 1.0),
    (("бар",), ("бар", "бара", "бар"), "pressure", 1e5),
    (("градус цельси", "цельси", "градус"), ("градус Цельсия", "градуса Цельсия", "градусов Цельсия"), "temp", "c"),
    (("градус фаренгейт", "фаренгейт"), ("градус Фаренгейта", "градуса Фаренгейта", "градусов Фаренгейта"), "temp", "f"),
    (("кельвин",), ("кельвин", "кельвина", "кельвинов"), "temp", "k"),
]
_ABBR = {"м", "км", "см", "мм", "дм", "кг", "г", "гр", "т", "мг", "л", "мл", "га", "ар", "тб", "гб", "мб", "кб",
         "вт", "квт", "дж", "кдж", "кал", "ккал", "атм", "па", "кпа", "сек", "мин", "ч", "с", "кв", "куб", "рт"}
_TO_C = {"c": lambda c: c, "f": lambda f: (f - 32) * 5 / 9, "k": lambda k: k - 273.15}
_FROM_C = {"c": lambda c: c, "f": lambda c: c * 9 / 5 + 32, "k": lambda c: c + 273.15}


def find_unit(phrase: str):
    """Единица в начале фразы -> (unit, сколько слов заняла) или (None, 0).
    Длинные основы важнее коротких: «квадратных метров» — не «метры»."""
    pw = phrase.strip().split()
    best, best_score, best_words = None, 0, 0
    for u in UNITS:
        for st in u[0]:
            sw = st.split()
            if len(pw) < len(sw):
                continue
            ok = True
            for i, w in enumerate(sw):
                word = pw[i]
                if w in _ABBR or len(w) <= 2:         # сокращения («м», «км», «кг», «м с») — только точно
                    ok = word == w
                else:
                    ok = word.startswith(w)
                if not ok:
                    break
            if ok and len(st) > best_score:
                best, best_score, best_words = u, len(st), len(sw)
    return best, best_words


def unit_form(u, value) -> str:
    one, few, many = u[1]
    if isinstance(value, float) and not float(value).is_integer():
        return few
    return plural(int(value), one, few, many)


def _convert(val, u1, u2):
    if u1[2] == "temp":
        return _FROM_C[u2[3]](_TO_C[u1[3]](val))
    return val * u1[3] / u2[3]


def convert_units(text: str):
    """«5 миль в километрах» / «сколько метров в 3 футах» / «30 км в час в метрах в секунду»
    -> (значение, from_unit, to_unit, результат) или None."""
    t = text
    m = re.search(r"(-?\d+(?:\.\d+)?)\s+(.+)$", t)
    if m:
        val, rest = float(m.group(1)), m.group(2)
        for sep in re.finditer(r"\s(?:в|во|это сколько)\s", rest):
            src, dst = rest[:sep.start()], rest[sep.end():]
            u1, n1 = find_unit(src)
            u2, _ = find_unit(dst)
            if u1 and u2 and u1 is not u2 and u1[2] == u2[2] and n1 == len(src.split()):
                return val, u1, u2, _convert(val, u1, u2)
    m2 = re.search(r"сколько\s+(.+?)\s+(?:в|во)\s+(-?\d+(?:\.\d+)?)\s+(.+)$", t)
    if m2:
        u2, n2 = find_unit(m2.group(1))
        u1, _ = find_unit(m2.group(3))
        if u1 and u2 and u1 is not u2 and u1[2] == u2[2] and n2 == len(m2.group(1).split()):
            val = float(m2.group(2))
            return val, u1, u2, _convert(val, u1, u2)
    return None


# ----------------------------------------------------------------- валюты --
CURRENCIES = [
    (("доллар сша", "американск доллар", "доллар", "бакс", "usd"), "USD", ("доллар", "доллара", "долларов")),
    (("евро", "eur"), "EUR", ("евро", "евро", "евро")),
    (("юан", "cny"), "CNY", ("юань", "юаня", "юаней")),
    (("фунт стерлинг", "британск фунт", "gbp"), "GBP", ("фунт стерлингов", "фунта стерлингов", "фунтов стерлингов")),
    (("иен", "йен", "jpy"), "JPY", ("иена", "иены", "иен")),
    (("тенге", "kzt"), "KZT", ("тенге", "тенге", "тенге")),
    (("белорусск рубл", "byn"), "BYN", ("белорусский рубль", "белорусских рубля", "белорусских рублей")),
    (("гривн", "uah"), "UAH", ("гривна", "гривны", "гривен")),
    (("лир", "try"), "TRY", ("лира", "лиры", "лир")),
    (("франк", "chf"), "CHF", ("франк", "франка", "франков")),
    (("злот", "pln"), "PLN", ("злотый", "злотых", "злотых")),
    (("вон", "krw"), "KRW", ("вона", "воны", "вон")),
    (("рупи", "inr"), "INR", ("рупия", "рупии", "рупий")),
    (("дирхам", "aed"), "AED", ("дирхам", "дирхама", "дирхамов")),
    (("драм", "amd"), "AMD", ("драм", "драма", "драмов")),
    (("сом", "kgs"), "KGS", ("сом", "сома", "сомов")),
    (("сум", "uzs"), "UZS", ("сум", "сума", "сумов")),
    (("лари", "gel"), "GEL", ("лари", "лари", "лари")),
    (("манат", "azn"), "AZN", ("манат", "маната", "манатов")),
    (("бат", "thb"), "THB", ("бат", "бата", "батов")),
    (("канадск доллар", "cad"), "CAD", ("канадский доллар", "канадских доллара", "канадских долларов")),
    (("австралийск доллар", "aud"), "AUD", ("австралийский доллар", "австралийских доллара", "австралийских долларов")),
    (("чешск крон", "czk"), "CZK", ("чешская крона", "чешские кроны", "чешских крон")),
    (("шведск крон", "sek"), "SEK", ("шведская крона", "шведские кроны", "шведских крон")),
    (("норвежск крон", "nok"), "NOK", ("норвежская крона", "норвежские кроны", "норвежских крон")),
    (("рубл", "руб", "rub", "деревянн"), "RUB", ("рубль", "рубля", "рублей")),
    (("биткоин", "биткойн", "btc"), "BTC", ("биткоин", "биткоина", "биткоинов")),
    (("эфириум", "эфир", "eth"), "ETH", ("эфир", "эфира", "эфиров")),
]
_CRYPTO_IDS = {"BTC": "bitcoin", "ETH": "ethereum"}


def find_currency(phrase: str):
    p = " " + phrase.strip() + " "
    best = None
    for stems, code, forms in CURRENCIES:
        for st in stems:
            words = st.split()
            pat = r"\b" + r"\w*\s+".join(re.escape(w) for w in words) + r"\w*"
            m = re.search(pat, p)
            if m and (best is None or len(st) > best[2]):
                best = (code, forms, len(st), m.start())
    return (best[0], best[1]) if best else (None, None)


class Calc(Skill):
    name = "calc"

    def __init__(self, a):
        super().__init__(a)
        self._rates = None
        self._rates_ts = 0.0

    # ------------------------------------------------------------ валюты --
    def rates(self) -> dict:
        """RUB за 1 единицу валюты."""
        if self._rates and time.time() - self._rates_ts < 3600:
            return self._rates
        data = self.a.get_json("https://www.cbr-xml-daily.ru/daily_json.js")
        rates = {"RUB": 1.0}
        for code, v in data.get("Valute", {}).items():
            rates[code] = float(v["Value"]) / float(v.get("Nominal", 1) or 1)
        self._rates, self._rates_ts = rates, time.time()
        return rates

    def crypto(self, code: str) -> float | None:
        cid = _CRYPTO_IDS.get(code)
        try:
            d = self.a.get_json("https://api.coingecko.com/api/v3/simple/price",
                                params={"ids": cid, "vs_currencies": "rub"})
            return float(d[cid]["rub"])
        except Exception:
            try:
                d = self.a.get_json(f"https://api.coinbase.com/v2/prices/{code}-RUB/spot")
                return float(d["data"]["amount"])
            except Exception as e:
                self.log.warning("курс %s: %s", code, e)
                return None

    def rub_per(self, code: str) -> float | None:
        if code in _CRYPTO_IDS:
            return self.crypto(code)
        return self.rates().get(code)

    @intent(r"\bкурс\w*\s+(.+)$|\bсколько (?:стоит|стоят)\s+(?:1\s+)?(доллар\w*|евро|юан\w*|биткоин\w*|биткойн\w*|"
            r"эфир\w*|фунт\w* стерлинг\w*|тенге|лир\w*|иен\w*|гривн\w*|белорусск\w* рубл\w*)\b", priority=61)
    def rate(self, ctx):
        what = ctx.match.group(1) or ctx.match.group(2)
        code, forms = find_currency(what)
        if not code:
            return None
        if code == "RUB":
            code, forms = "USD", CURRENCIES[0][2]
        try:
            rub = self.rub_per(code)
        except Exception as e:
            self.log.warning("курсы: %s", e)
            return Reply("Не получилось узнать курс — нет связи с банком.", emotion="sadness")
        if rub is None:
            return Reply("Не знаю такой валюты.")
        trend = ""
        return Reply(f"Курс {forms[1] if code not in ('EUR',) else 'евро'}: {fmt_num(rub, 2)} "
                     f"{plural(int(rub), 'рубль', 'рубля', 'рублей') if float(rub).is_integer() else 'рубля'}{trend}.")

    @intent(r"(\d+(?:\.\d+)?)\s+(.+?)\s+(?:в|во|на)\s+(.+?)$", priority=59)
    def convert(self, ctx):
        n = ctx.norm
        n = re.sub(r"^(?:сколько будет|сколько это|переведи|конвертируй|сколько|посчитай)\s+", "", n)
        m = re.search(r"(\d+(?:\.\d+)?)\s+(.+?)\s+(?:в|во|на)\s+(.+?)$", n)
        if not m:
            return None
        val = float(m.group(1))
        c1, f1 = find_currency(m.group(2))
        c2, f2 = find_currency(m.group(3))
        if c1 and c2 and c1 != c2:
            try:
                r1, r2 = self.rub_per(c1), self.rub_per(c2)
            except Exception:
                return Reply("Не получилось узнать курс — нет связи.", emotion="sadness")
            if not r1 or not r2:
                return Reply("Не знаю курс одной из валют.")
            res = val * r1 / r2
            v_s = fmt_num(val if not float(val).is_integer() else int(val))
            r_s = fmt_num(res, 2)
            return Reply(f"{v_s} {_cur_form(f1, val)} — это {r_s} {_cur_form(f2, res)}.")
        conv = convert_units(n)
        if conv:
            v, u1, u2, res = conv
            v_disp = int(v) if float(v).is_integer() else v
            digits = 2 if abs(res) >= 1 else 4
            res_r = round(res, digits)
            return Reply(f"{fmt_num(v_disp)} {unit_form(u1, v_disp)} — это {fmt_num(res_r, digits)} "
                         f"{unit_form(u2, res_r)}.")
        return None

    @intent(r"\bсколько\s+(.+?)\s+(?:в|во)\s+(\d+(?:\.\d+)?)\s+(.+)$", priority=58)
    def how_many_in(self, ctx):
        conv = convert_units(ctx.norm)
        if not conv:
            return None
        v, u1, u2, res = conv
        v_disp = int(v) if float(v).is_integer() else v
        digits = 2 if abs(res) >= 1 else 4
        res_r = round(res, digits)
        return Reply(f"В {fmt_num(v_disp)} {unit_form(u1, v_disp)} — {fmt_num(res_r, digits)} {unit_form(u2, res_r)}.")

    # ------------------------------------------------------- арифметика --
    @intent(r"\b(?:сколько будет|посчитай|вычисли|подсчитай|реши|чему равно)\b|"
            r"\d\s*(?:\+|-|\*|/|плюс|минус|умножить|разделить|делить|в степени|в квадрате|в кубе|процент)|"
            r"\b(?:корень|факториал|синус|косинус|тангенс|логарифм)\b", priority=57)
    def calculate(self, ctx):
        expr = to_expression(ctx.norm)
        if not expr:
            return None
        try:
            res = safe_eval(expr)
        except ZeroDivisionError:
            return Reply("На ноль делить нельзя! Даже мне.", emotion="surprise")
        except (ValueError, SyntaxError, OverflowError, TypeError):
            return None
        if isinstance(res, complex):
            return None
        if isinstance(res, float) and res.is_integer() and abs(res) < 1e15:
            res = int(res)
        return Reply(f"Будет {fmt_num(res, 4)}.", emotion="confidence", intensity=0.4, card=f"{expr} = {res}")


def _cur_form(forms, value) -> str:
    if forms is None:
        return ""
    if isinstance(value, float) and not value.is_integer():
        return forms[1]
    return plural(int(value), *forms)
