"""Детерминированный триаж по мотивам START.

Приоритет НЕ зависит от нейросети: маленькая модель может ошибиться или
не ответить, а сортировка пострадавших должна быть объяснимой и
воспроизводимой. Нейросеть отвечает только за диалог.

Категории:
  red     — помощь нужна немедленно (угроза жизни)
  yellow  — срочно, но состояние стабильное
  green   — лёгкие травмы / в безопасности
  unknown — данных пока недостаточно
"""
import re
from dataclasses import dataclass, field

RED, YELLOW, GREEN, UNKNOWN = "red", "yellow", "green", "unknown"
PRIORITY_RANK = {RED: 0, YELLOW: 1, UNKNOWN: 2, GREEN: 3}

# (тег, вес, регулярное выражение). Вес >= 10 — сразу "red".
# Шаблоны пишем по основам слов, текст заранее приводится к нижнему регистру, ё -> е.
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

# Отрицание перед симптомом ("нет кровотечения", "не сломал") гасит правило.
# Правила, которые сами начинаются с отрицания ("не дышит"), не затрагиваются.
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
    panic: bool = False
    safe: bool = False

    @property
    def missing(self) -> list[str]:
        """Какие данные диспетчеру ещё нужно выяснить (в порядке важности)."""
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
    """Признаки паники: капс, "!!!", повторы "помогите". На приоритет НЕ влияют —
    громкий крик не должен отодвигать тихого пострадавшего с кровотечением."""
    letters = [c for c in text if c.isalpha()]
    caps = sum(c.isupper() for c in letters) / len(letters) if len(letters) >= 8 else 0
    lower = normalize(text)
    return caps > 0.6 or "!!!" in text or lower.count("помог") >= 2


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


def extract_location(message: str) -> str | None:
    if LOCATION_HINT_RE.search(normalize(message)):
        return message.strip()[:200]
    return None


def assess(user_messages: list[str]) -> TriageResult:
    """Оценка по всем сообщениям пострадавшего (факты накапливаются)."""
    result = TriageResult()
    full = normalize(" \n ".join(user_messages))

    for tag, weight, regex in _COMPILED:
        if _matches(regex, full):
            result.tags.append(tag)
            result.score += weight
    # Сильное кровотечение включает обычное — не считаем дважды
    if "сильное кровотечение" in result.tags and "кровотечение" in result.tags:
        result.tags.remove("кровотечение")
        result.score -= 5

    result.safe = bool(_SAFE.search(full))
    for msg in user_messages:  # последнее упоминание важнее первого
        result.coords = extract_coords(msg) or result.coords
        result.people = extract_people(msg) or result.people
        result.location_text = extract_location(msg) or result.location_text
    result.panic = any(panic_level(m) for m in user_messages[-3:])

    if any(w >= 10 for tag, w, _ in RULES if tag in result.tags):
        result.priority = RED
    elif result.score >= 5:
        result.priority = YELLOW
    elif result.safe or result.score > 0:
        result.priority = GREEN
    else:
        result.priority = UNKNOWN

    # Группа из многих людей с травмами — повышаем внимание
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
    """Ответ диспетчера без нейросети: спокойный, по делу, заполняет недостающие данные."""
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
