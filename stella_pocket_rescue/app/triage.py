import re
from dataclasses import dataclass, field

RED, YELLOW, GREEN, UNKNOWN = "red", "yellow", "green", "unknown"
PRIORITY_RANK = {RED: 0, YELLOW: 1, UNKNOWN: 2, GREEN: 3}

RULES: list[tuple[str, int, str]] = [
    ("не дышит", 10, r"не\s*дыш|не\s+дыхан|нет\s+дыхан|not breathing"),
    ("без сознания", 10, r"без\s+сознан|потерял\w*\s+сознан|не\s+приход\w*\s+в\s+себя|"
                         r"не\s+(отвеча|реагиру)|unconscious"),
    ("сильное кровотечение", 10, r"сильн\w*\s+кровотеч|кровь\s+(хлещ|льет|течет\s+сильно|"
                                 r"не\s+останавл)|много\s+крови|heavy bleeding"),
    ("под завалом", 10, r"под\s+завал|завалил|придавил|зажал\w*|зажат|засыпал\w*|"
                        r"плит\w*\s+(на|упал)|trapped under"),
    ("затруднено дыхание", 10, r"задыха|трудно\s+дыш|тяжело\s+дыш|не\s+могу\s+дыш|"
                               r"can'?t breathe"),
    ("боль в груди", 10, r"боль\w*\s+в\s+груди|сердечн\w*\s+приступ|инфаркт|chest pain"),
    ("судороги", 10, r"судорог|припадок|seizure"),
    ("пожар / газ", 10, r"пожар|горит|горим|дым\w*|запах\s+газа|утечк\w*\s+газа|fire|gas leak"),
    ("роды", 10, r"схватк|рожа|воды\s+отошли|in labor"),

    ("перелом", 5, r"перелом|сломал|сломан|broken"),
    ("не может передвигаться", 5, r"не\s+могу\s+(ходить|идти|встать|двигат|выбрат)|"
                                  r"не\s+(может|могут)\s+(ходить|идти|встать|двигат)|can'?t walk"),
    ("кровотечение", 5, r"кровотеч|кровь|кровит|bleeding"),
    ("травма головы", 5, r"(удар\w*|ушиб\w*|травм\w*|разбил\w*)\s+(по\s+)?голов|сотрясен|head injury"),
    ("ожог", 5, r"ожог|обжег|burn"),
    ("заблокирован", 5, r"застрял|заперт|не\s+могу\s+выйти|заблокир|дверь\s+заклинил|stuck"),

    ("ребёнок", 3, r"реб[её]н|дет[иейя]|младен|малыш|сын|доч[ьк]|child|baby"),
    ("пожилой / инвалид", 3, r"пожил|бабушк|дедушк|инвалид|коляск|elderly"),
    ("беременность", 3, r"беремен|pregnan"),
    ("хронические болезни", 3, r"диабет|инсулин|астм|ингалятор|эпилеп|лекарств|medication"),
    ("переохлаждение", 2, r"замерза|холодн|переохлажд|freezing"),
    ("нет воды", 1, r"нет\s+воды|хочу\s+пить|жажд"),
]

SAFE_RULES = r"(не\s+ранен|без\s+травм|в\s+безопасност|все\s+(хорошо|нормально|в\s+порядке)|" \
             r"я\s+в\s+порядке|мы\s+в\s+порядке|цел[аы]?\b|царапин|i'?m ok|safe)"

NEGATION_BEFORE = re.compile(r"(\bне|\bнет|\bбез|\bno|\bnot)\s+$")

_COMPILED = [(tag, weight, re.compile(pattern)) for tag, weight, pattern in RULES]
_SAFE = re.compile(SAFE_RULES)

FIRST_AID: dict[str, str] = {
    "сильное кровотечение": "Сильно прижмите рану чистой тканью и держите не отпуская. "
                            "Если кровь бьёт из руки или ноги — наложите жгут/закрутку выше раны "
                            "и запомните время.",
    "кровотечение": "Прижмите рану чистой тканью или бинтом.",
    "не дышит": "Если человек не дышит: уложите на спину на твёрдое, давите на центр груди "
                "5–6 см, 100–120 раз в минуту, не останавливайтесь до прихода помощи.",
    "без сознания": "Если дышит, но без сознания — поверните его на бок (устойчивое боковое "
                    "положение), чтобы не захлебнулся.",
    "под завалом": "Не тратьте силы на крик: стучите по трубам или стенам, прикройте рот и нос "
                   "тканью от пыли. Не зажигайте огонь.",
    "пожар / газ": "Не пользуйтесь огнём и выключателями. Прикройте нос и рот мокрой тканью, "
                   "держитесь ниже к полу, двигайтесь к выходу если это безопасно.",
    "затруднено дыхание": "Помогите принять полусидячее положение, ослабьте одежду, обеспечьте "
                          "приток воздуха.",
    "перелом": "Не пытайтесь вправить. Зафиксируйте конечность в том положении, как она есть.",
    "переохлаждение": "Укройтесь чем угодно, изолируйте себя от холодного пола, держитесь вместе.",
}

WORD_NUMBERS = {
    "двое": 2, "двоих": 2, "трое": 3, "троих": 3, "четверо": 4, "четверых": 4,
    "пятеро": 5, "пятерых": 5, "шестеро": 6, "семеро": 7,
}
PEOPLE_RE = re.compile(r"(\d{1,3})\s*(человек|чел\b|людей|взросл|people|persons)")
PEOPLE_WORD_RE = re.compile(r"\b(" + "|".join(WORD_NUMBERS) + r")\b")
COORDS_RE = re.compile(r"(-?\d{1,2}[.,]\d{3,})\s*[,;\s]\s*(-?\d{1,3}[.,]\d{3,})")
LOCATION_HINT_RE = re.compile(
    r"(ул\.|улиц|проспект|пр-т|переул|дом\b|д\.\s*\d|подъезд|этаж|квартир|кв\.|школ|больниц|"
    r"магазин|рядом\s+с|возле|около|напротив|во\s+дворе|подвал|крыш|парк|остановк)"
)


@dataclass
class TriageResult:
    priority: str = UNKNOWN
    score: int = 0
    tags: list[str] = field(default_factory=list)
    people: int | None = None
    coords: tuple[float, float] | None = None
    location_text: str | None = None
    address: dict = field(default_factory=dict)
    panic: bool = False
    safe: bool = False

    @property
    def missing(self) -> list[str]:
        need = []
        if not self.location_text and not self.coords:
            need.append("location")
        if not self.tags and not self.safe:
            need.append("condition")
        if self.people is None:
            need.append("people")
        return need


def normalize(text: str) -> str:
    return text.lower().replace("ё", "е")


def _matches(regex: re.Pattern, text: str) -> bool:
    for m in regex.finditer(text):
        if m.group(0).startswith(("не", "нет", "без", "no", "not")):
            return True
        if not NEGATION_BEFORE.search(text[max(0, m.start() - 8):m.start()]):
            return True
    return False


def panic_level(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    caps = sum(c.isupper() for c in letters) / len(letters) if len(letters) >= 8 else 0
    return caps > 0.6 or "!!!" in text or normalize(text).count("помог") >= 2


def extract_coords(text: str) -> tuple[float, float] | None:
    for m in COORDS_RE.finditer(text):
        lat, lon = (float(g.replace(",", ".")) for g in m.groups())
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return None


def extract_people(text: str) -> int | None:
    lower = normalize(text)
    m = PEOPLE_RE.search(lower)
    if m:
        return int(m.group(1))
    m = PEOPLE_WORD_RE.search(lower)
    if m:
        return WORD_NUMBERS[m.group(1)]
    if re.search(r"\bя\s+один\b|\bя\s+одна\b|только\s+я|\balone\b", lower):
        return 1
    return None


STREET_KINDS = (
    (r"ул(?:иц\w*|\.)?", "ул."),
    (r"пр(?:оспект\w*|-т|\.)", "пр."),
    (r"пер(?:еул\w*|\.)", "пер."),
    (r"бульвар\w*|б-р", "б-р"),
    (r"шоссе", "ш."),
    (r"площад\w*|пл\.", "пл."),
    (r"микрорайон\w*|мкрн?\.?", "мкр."),
)
STREET_RE = re.compile(
    r"(?<![\w-])(" + "|".join(p for p, _ in STREET_KINDS) + r")\s*[,.]?\s*"
    r"([^\W\d_][\w-]*(?:\s+[^\W\d_][\w-]*)?|\d{1,3}(?:-?[а-я]{1,2})?(?:\s+[^\W\d_][\w-]*)?)",
    re.I,
)
HOUSE_AFTER_RE = re.compile(r"^\s*,?\s*(?:д(?:ом)?\.?\s*)?№?\s*(\d{1,4}[а-яa-z]?(?:/\d{1,4})?)(?![\d])", re.I)
HOUSE_RE = re.compile(r"(?<![\w])(?:дом|д\.)\s*№?\s*(\d{1,4}[а-яa-z]?(?:/\d{1,4})?)(?![\d])", re.I)
NOT_HOUSE_RE = re.compile(r"^\s*(?:-?(?:й|м|ом|ем|ой|я))?\s*(?:этаж|подъезд|челов|раз|мин|час|лет|год)", re.I)
BARE_STREET_RE = re.compile(r"(?<![\w])(?:на|по)\s+([А-ЯЁ][а-яё]+(?:-[А-ЯЁа-яё]+)?)\s*,?\s*(\d{1,4}[а-я]?(?:/\d{1,4})?)(?![\d])")
NAME_TAIL = {"би", "хана", "батыра", "ата", "бия", "хан", "батыр"}
LANDMARK_CUT_RE = re.compile(r"\s+(?:на|по|в)\s+(?=ул|пр|пер|мкр|микро|бульв|шосс|площ|дом\b|д\.)", re.I)
ORDINALS = {"перв": 1, "втор": 2, "трет": 3, "четверт": 4, "пят": 5, "шест": 6, "седьм": 7,
            "восьм": 8, "девят": 9, "десят": 10}
ORDINAL_RE = "(" + "|".join(ORDINALS) + r")\w*"
FLOOR_RE = re.compile(r"(\d{1,3})\s*(?:-?(?:й|м|ом|ем|ой))?\s*этаж|этаж\w*\s*№?\s*(\d{1,3})|" + ORDINAL_RE + r"\s+этаж", re.I)
ENTRANCE_RE = re.compile(r"(\d{1,2})\s*(?:-?(?:й|м|ом|ем|ой))?\s*подъезд|подъезд\w*\s*№?\s*(\d{1,2})|"
                         + ORDINAL_RE + r"\s+подъезд", re.I)
APARTMENT_RE = re.compile(r"(?<![\w])(?:кв\.?|квартир\w*)\s*№?\s*(\d{1,4})", re.I)
LANDMARK_RE = re.compile(
    r"(рядом\s+с|возле|около|напротив|недалеко\s+от|у\s+входа\s+в|за)\s+"
    r"((?:школ|больниц|поликлиник|магазин|остановк|рын|вокзал|парк|мечет|церк|храм|торгов|тц|аптек|"
    r"банк|кафе|садик|детск|университет|колледж|завод|мост|реки|памятник|стадион|дом\s+культур|[А-ЯЁ«\"])"
    r"[^,.!?;\n]{0,40})",
    re.I,
)
PLACE_RE = re.compile(
    r"((?:школ\w*|больниц\w*|поликлиник\w*|детск\w+\s+сад\w*|торгов\w*\s+центр\w*|вокзал\w*|мечет\w*|"
    r"стадион\w*)\s*№?\s*\d{0,4})",
    re.I,
)
SPOT_RE = re.compile(r"(в\s+подвал\w*|на\s+крыш\w*|во\s+дворе|на\s+балкон\w*|в\s+лифт\w*|на\s+лестниц\w*)", re.I)
NAME_STOP = {"дом", "д", "этаж", "подъезд", "кв", "квартира", "у", "мы", "я", "и", "в", "на", "возле", "рядом",
             "около", "напротив", "нас", "под", "за", "по", "с", "там", "тут", "здесь", "уже", "нет", "не"}
ADDRESS_KEYS = ("street", "house", "entrance", "floor", "apartment", "landmark", "spot")


def _ordinal(word: str | None) -> int | None:
    if not word:
        return None
    for stem, n in ORDINALS.items():
        if word.lower().startswith(stem):
            return n
    return None


def _number(m: re.Match | None) -> int | None:
    if not m:
        return None
    for g in m.groups():
        if g and g.isdigit():
            n = int(g)
            return n if 0 < n < 200 else None
        value = _ordinal(g)
        if value:
            return value
    return None


def _street(message: str) -> tuple[str | None, str | None]:
    for m in STREET_RE.finditer(message):
        kind_raw, name = m.group(1), m.group(2)
        words = [w for w in name.split() if w.lower().strip(".") not in NAME_STOP]
        if not words:
            continue
        if len(words) > 1 and words[1].lower() not in NAME_TAIL and (words[1][:1].islower() or len(words[1]) < 3):
            words = words[:1]
        kind = next(label for pattern, label in STREET_KINDS if re.fullmatch(pattern, kind_raw, re.I))
        pretty = " ".join(w if w.lower() in NAME_TAIL else w[:1].upper() + w[1:] for w in words)
        house = None
        after = message[m.end():]
        h = HOUSE_AFTER_RE.match(after)
        if h and not NOT_HOUSE_RE.match(after[h.end():]):
            house = h.group(1)
        return f"{kind} {pretty}", house
    for m in BARE_STREET_RE.finditer(message):
        if not NOT_HOUSE_RE.match(message[m.end():]):
            return m.group(1), m.group(2)
    return None, None


def _clean_phrase(text: str) -> str:
    text = LANDMARK_CUT_RE.split(text)[0]
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-—")
    words = text.split()
    while words and words[-1].lower() in NAME_STOP:
        words.pop()
    return " ".join(words)[:48]


def parse_address(message: str) -> dict:
    found: dict = {}
    street, house = _street(message)
    if street:
        found["street"] = street
    if not house:
        h = HOUSE_RE.search(message)
        if h and not NOT_HOUSE_RE.match(message[h.end():]):
            house = h.group(1)
    if house:
        found["house"] = house.lower()
    for key, regex in (("entrance", ENTRANCE_RE), ("floor", FLOOR_RE)):
        value = _number(regex.search(message))
        if value:
            found[key] = value
    a = APARTMENT_RE.search(message)
    if a:
        found["apartment"] = int(a.group(1))
    lm = LANDMARK_RE.search(message)
    if lm:
        phrase = _clean_phrase(lm.group(0))
        if phrase:
            found["landmark"] = phrase[:1].lower() + phrase[1:]
    else:
        p = PLACE_RE.search(message)
        if p:
            found["landmark"] = _clean_phrase(p.group(1)).lower()
    s = SPOT_RE.search(message)
    if s:
        found["spot"] = _clean_phrase(s.group(1)).lower()
    return found


def merge_address(messages: list[str]) -> dict:
    merged: dict = {}
    for msg in messages:
        parts = parse_address(msg)
        if "street" in parts and parts["street"] != merged.get("street"):
            merged.pop("house", None)
        merged.update(parts)
    return {k: merged[k] for k in ADDRESS_KEYS if k in merged}


def format_address(parts: dict) -> str | None:
    head = []
    if parts.get("street"):
        head.append(parts["street"] + (f", д. {parts['house']}" if parts.get("house") else ""))
    elif parts.get("house"):
        head.append(f"д. {parts['house']}")
    if parts.get("entrance"):
        head.append(f"подъезд {parts['entrance']}")
    if parts.get("floor"):
        head.append(f"этаж {parts['floor']}")
    if parts.get("apartment"):
        head.append(f"кв. {parts['apartment']}")
    if parts.get("spot"):
        head.append(parts["spot"])
    if parts.get("landmark"):
        head.append(parts["landmark"])
    return " · ".join(head) or None


def extract_location(message: str) -> str | None:
    if not LOCATION_HINT_RE.search(normalize(message)):
        return None
    return format_address(parse_address(message)) or message.strip()[:200]


def assess(user_messages: list[str]) -> TriageResult:
    result = TriageResult()
    full = normalize(" \n ".join(user_messages))

    for tag, weight, regex in _COMPILED:
        if _matches(regex, full):
            result.tags.append(tag)
            result.score += weight
    if "сильное кровотечение" in result.tags and "кровотечение" in result.tags:
        result.tags.remove("кровотечение")
        result.score -= 5

    result.safe = bool(_SAFE.search(full))
    for msg in user_messages:
        result.coords = extract_coords(msg) or result.coords
        result.people = extract_people(msg) or result.people
        result.location_text = extract_location(msg) or result.location_text
    result.address = merge_address(user_messages)
    result.location_text = format_address(result.address) or result.location_text
    result.panic = any(panic_level(m) for m in user_messages[-3:])

    if any(w >= 10 for tag, w, _ in RULES if tag in result.tags):
        result.priority = RED
    elif result.score >= 5:
        result.priority = YELLOW
    elif result.safe or result.score > 0:
        result.priority = GREEN
    else:
        result.priority = UNKNOWN

    if result.priority == YELLOW and (result.people or 0) >= 5:
        result.score += 3
    return result


def first_aid(tags: list[str]) -> list[str]:
    return [FIRST_AID[t] for t in tags if t in FIRST_AID]


QUESTIONS = {
    "location": "Где вы находитесь? Назовите адрес, номер дома, подъезд и этаж, или ориентир "
                "рядом (школа, магазин, остановка). Если есть координаты из приложения карт — "
                "пришлите их.",
    "condition": "Есть ли раненые? Опишите коротко: кровотечение, переломы, кто-то без сознания, "
                 "кого-то придавило?",
    "people": "Сколько человек рядом с вами, есть ли дети или пожилые?",
}


def fallback_reply(result: TriageResult) -> str:
    if result.missing:
        return QUESTIONS[result.missing[0]]
    if result.priority == RED:
        return ("Ваш запрос отмечен как КРИТИЧЕСКИЙ и передан спасателям первым. "
                "Оставайтесь на месте, если это безопасно, и не выключайте телефон. "
                "Пишите сюда, если состояние изменится.")
    if result.priority == YELLOW:
        return ("Спасатели получили ваши данные. Оставайтесь на месте, если это безопасно, "
                "берегите заряд телефона. Сообщите, если кому-то станет хуже.")
    return ("Спасибо, ваши данные переданы спасателям. Если можете безопасно двигаться — "
            "следуйте объявлениям на этой странице. Сообщите, если ситуация изменится.")
