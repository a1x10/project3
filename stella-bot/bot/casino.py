"""Стелла-казино: игрушечные бананы 🍌. Никаких настоящих денег — только цифры в базе.

Ставки разбираются кодом (без модели): «стелла красное 2000», «стелла слоты 300»,
«стелла 17 100», «стелла монетка решка 50», «стелла кости все». Рандом — тоже код.
"""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass, field
from datetime import timedelta

from .db import DB, Person
from .util import money, norm, utcnow

RED = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
SLOT_SYMBOLS = ["🍒", "🍋", "🍌", "🍇", "🔔", "💎", "7️⃣"]
SLOT_TRIPLE = {"🍒": 5, "🍋": 6, "🍌": 8, "🍇": 10, "🔔": 12, "💎": 15, "7️⃣": 20}
SLOT_PAIR = 2  # два одинаковых — ставка х2. RTP ~95.6%

_FILLER = {
    "ставлю", "ставка", "ставку", "поставь", "поставлю", "поставим", "на", "го", "давай", "плиз", "пж",
    "bet", "крути", "крутани", "кручу", "сыграем", "играю", "играем", "в", "за", "мне", "сыграть", "бросай",
    "брось", "кинь", "подкинь", "бананов", "банана", "банан", "🍌",
}
_ALL_IN = {"все", "всё", "вабанк", "ва-банк", "олл-ин", "оллин", "allin", "all-in", "all"}

HELP = [
    "🎰 казино стеллы, бананы игрушечные 🍌",
    "рулетка: «стелла красное 500», «стелла черное 1к», «стелла зеро 100», «стелла чет 200», «стелла 17 100» (на число)",
    "ещё: «стелла слоты 300», «стелла монетка орел 100», «стелла кости 200», можно «все» вместо суммы",
    "«стелла баланс», «стелла бонус», «стелла топ», «стелла переведи @имя 500»",
]


@dataclass
class Bet:
    game: str  # roulette | slots | coin | dice
    choice: str | None  # red/black/zero/even/odd/<num> | heads/tails
    amount: int | None  # None = не указали
    all_in: bool = False


@dataclass
class CasinoResult:
    lines: list[str]
    mood: str | None = None  # для стикера: победа / проигрыш
    delta: int = 0
    balance: int | None = None
    pause_after_first: bool = False  # «кручу…» — пауза — результат
    extra: dict = field(default_factory=dict)


def _amount(token: str) -> int | None:
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)(к|k|тыс|тысяч|тыщ)?", token)
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    if m.group(2):
        value *= 1000
    return int(value)


def _choice(token: str) -> tuple[str, str] | None:
    """-> (игра, выбор)"""
    if re.match(r"^(нечет|odd$)", token):
        return "roulette", "odd"
    if re.match(r"^(чет(н\w*)?$|even$)", token):
        return "roulette", "even"
    if re.match(r"^(красн|red$)", token):
        return "roulette", "red"
    if re.match(r"^(черн|black$)", token):
        return "roulette", "black"
    if re.match(r"^(зеро$|зелен|zero$)", token):
        return "roulette", "zero"
    if re.match(r"^(орел|орла|heads$)", token):
        return "coin", "heads"
    if re.match(r"^(решк|tails$)", token):
        return "coin", "tails"
    return None


def _game(token: str) -> str | None:
    if re.match(r"^(рулетк|roulette$)", token):
        return "roulette"
    if re.match(r"^(слот|автомат|однорук|slots?$)", token):
        return "slots"
    if re.match(r"^(монетк|монет|coin$|флип)", token):
        return "coin"
    if re.match(r"^(кост|кубик|dice$)", token):
        return "dice"
    return None


def parse_bet(text: str) -> Bet | None:
    """Строгий разбор: каждое слово должно быть «казиношным», иначе это обычный разговор."""
    tokens = re.findall(r"[a-zа-я0-9🍌][a-zа-я0-9.,\-]*", norm(text))
    if not tokens:
        return None
    game: str | None = None
    choice: str | None = None
    numbers: list[tuple[int, bool]] = []  # (значение, «помечено как число»)
    all_in = False
    mark_number = False
    for tok in tokens:
        if tok in ("число", "номер", "num"):
            mark_number = True
            continue
        if tok in _ALL_IN:
            all_in = True
            continue
        if (g := _game(tok)) is not None:
            if game and game != g:
                return None
            game = g
            continue
        if (c := _choice(tok)) is not None:
            if (game and game != c[0]) or (choice and choice != c[1]):
                return None
            game, choice = c
            continue
        if (n := _amount(tok)) is not None:
            numbers.append((n, mark_number))
            mark_number = False
            continue
        if tok in _FILLER:
            continue
        return None  # незнакомое слово — не ставка
    if game is None:
        # «стелла 17 100» — рулетка на число
        if len(numbers) == 2 and numbers[0][0] <= 36:
            return Bet("roulette", str(numbers[0][0]), numbers[1][0])
        return None
    if game == "roulette" and choice is None:
        marked = [n for n, m in numbers if m]
        if marked and marked[0] <= 36:
            choice = str(marked[0])
            numbers = [x for x in numbers if not x[1]]
        elif len(numbers) == 2 and numbers[0][0] <= 36:
            choice = str(numbers[0][0])
            numbers = numbers[1:]
    if len(numbers) > 1:
        return None
    amount = numbers[0][0] if numbers else None
    return Bet(game, choice, amount, all_in=all_in and amount is None)


class Casino:
    def __init__(self, db: DB, start_balance: int, bonus: int, bonus_hours: float, min_bet: int,
                 rng: random.Random | None = None):
        self.db = db
        self.start_balance = start_balance
        self.bonus_amount = bonus
        self.bonus_hours = bonus_hours
        self.min_bet = min_bet
        self.rng = rng or random.SystemRandom()
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, chat_id: int) -> asyncio.Lock:
        return self._locks.setdefault(chat_id, asyncio.Lock())

    async def balance(self, chat_id: int, person: Person) -> int:
        w = await self.db.get_wallet(chat_id, person.id, self.start_balance)
        return int(w["balance"])

    async def play(self, chat_id: int, person: Person, bet: Bet) -> CasinoResult:
        name = person.name
        if bet.game == "roulette" and bet.choice is None:
            return CasinoResult(["на что ставишь?", "красное / черное / зеро / чет / нечет или число 0-36, например «стелла красное 500»"])
        if bet.game == "coin" and bet.choice is None:
            bet.choice = self.rng.choice(["heads", "tails"])
        async with self._lock(chat_id):
            w = await self.db.get_wallet(chat_id, person.id, self.start_balance)
            bal = int(w["balance"])
            amount = bal if bet.all_in else bet.amount
            if amount is None:
                return CasinoResult(["а сколько ставишь?", f"у тебя {money(bal)}"], balance=bal)
            if bal <= 0:
                return CasinoResult([f"{name}, у тебя 0 🍌", "возьми «стелла бонус» и отыграешься)"], balance=bal)
            if amount < self.min_bet:
                return CasinoResult([f"минималка {money(self.min_bet)}"], balance=bal)
            if amount > bal:
                return CasinoResult([f"у тебя всего {money(bal)}", "ставь меньше или «все»"], balance=bal)

            mult, show = self._spin(bet)
            win = amount * mult - amount if mult else -amount
            new_bal = bal + win
            await self.db.update_wallet(
                chat_id,
                person.id,
                balance=new_bal,
                games=w["games"] + 1,
                won=w["won"] + max(win, 0),
                lost=w["lost"] + max(-win, 0),
            )

        lines = list(show)
        mood = None
        if mult == 1:
            lines.append(f"ничья, ставка вернулась. у {name} {money(new_bal)}")
        elif win > 0:
            cheer = self.rng.choice(["ееее", "красава", "везунчик", "воу", "ну ты даёшь", "лаки"])
            lines.append(f"{cheer} {name} +{money(win)}")
            lines.append(f"теперь {money(new_bal)}")
            if mult >= 10:
                mood = "победа"
        else:
            sad = self.rng.choice(["эх", "мимо 😅", "казино не дремлет", "не повезло", "ну бывает"])
            lines.append(f"{sad}, {name} −{money(amount)}")
            lines.append(f"осталось {money(new_bal)}" if new_bal else "всё, ноль 🫠 бери «стелла бонус»")
            if new_bal == 0 or amount >= 5000:
                mood = "проигрыш"
        return CasinoResult(lines, mood=mood, delta=win, balance=new_bal, pause_after_first=True)

    def _spin(self, bet: Bet) -> tuple[int, list[str]]:
        """-> (множитель выплаты включая ставку; 0 = проигрыш, 1 = возврат), строки «анимации»."""
        if bet.game == "roulette":
            n = self.rng.randint(0, 36)
            emoji = "🟢" if n == 0 else ("🔴" if n in RED else "⚫")
            colour = "зеро" if n == 0 else ("красное" if n in RED else "черное")
            c = bet.choice or ""
            hit = (
                (c == "red" and n in RED)
                or (c == "black" and n != 0 and n not in RED)
                or (c == "even" and n != 0 and n % 2 == 0)
                or (c == "odd" and n % 2 == 1)
            )
            if c == "zero":
                mult = 36 if n == 0 else 0
            elif c.isdigit():
                mult = 36 if n == int(c) else 0
            else:
                mult = 2 if hit else 0
            return mult, [self.rng.choice(["кручу 🎡", "крутим-вертим 🎡", "шарик пошёл 🎡"]), f"выпало {n} {emoji} {colour}"]
        if bet.game == "slots":
            reels = [self.rng.choice(SLOT_SYMBOLS) for _ in range(3)]
            show = [self.rng.choice(["дёргаю рычаг 🎰", "крутим слоты 🎰"]), " | ".join(reels)]
            if reels[0] == reels[1] == reels[2]:
                return SLOT_TRIPLE[reels[0]], show
            if len(set(reels)) == 2:
                return SLOT_PAIR, show
            return 0, show
        if bet.game == "coin":
            side = self.rng.choice(["heads", "tails"])
            label = "орёл 🦅" if side == "heads" else "решка 🪙"
            return (2 if side == bet.choice else 0), ["подкидываю монетку 🪙", f"{label}"]
        if bet.game == "dice":
            you = self.rng.randint(1, 6) + self.rng.randint(1, 6)
            me = self.rng.randint(1, 6) + self.rng.randint(1, 6)
            show = ["кидаем кости 🎲", f"у тебя {you}, у меня {me}"]
            return (2 if you > me else 1 if you == me else 0), show
        raise ValueError(bet.game)

    async def bonus(self, chat_id: int, person: Person) -> CasinoResult:
        async with self._lock(chat_id):
            w = await self.db.get_wallet(chat_id, person.id, self.start_balance)
            now = utcnow()
            last = w.get("last_bonus_at")
            if last and now - last < timedelta(hours=self.bonus_hours):
                left = timedelta(hours=self.bonus_hours) - (now - last)
                h, m = divmod(int(left.total_seconds()) // 60, 60)
                return CasinoResult([f"бонус уже был) следующий через {h}ч {m}м"], balance=int(w["balance"]))
            new_bal = int(w["balance"]) + self.bonus_amount
            await self.db.update_wallet(chat_id, person.id, balance=new_bal, last_bonus_at=now)
        return CasinoResult([f"держи +{money(self.bonus_amount)} 🎁", f"у {person.name} теперь {money(new_bal)}"],
                            delta=self.bonus_amount, balance=new_bal)

    async def top(self, chat_id: int, limit: int = 10) -> CasinoResult:
        rows = await self.db.top_wallets(chat_id, limit)
        if not rows:
            return CasinoResult(["пока никто не играл", "начни: «стелла красное 500»"])
        medals = ["🥇", "🥈", "🥉"]
        lines = ["топ богачей 🍌"]
        lines.append("\n".join(
            f"{medals[i] if i < 3 else f'{i + 1}.'} {p.name} — {money(b)}" for i, (p, b) in enumerate(rows)
        ))
        return CasinoResult(lines)

    async def transfer(self, chat_id: int, src: Person, dst: Person, amount: int) -> CasinoResult:
        if src.id == dst.id:
            return CasinoResult(["самой себе переводить, хитро) нет"])
        if amount <= 0:
            return CasinoResult(["сумма должна быть больше нуля"])
        async with self._lock(chat_id):
            ws = await self.db.get_wallet(chat_id, src.id, self.start_balance)
            if amount > ws["balance"]:
                return CasinoResult([f"у тебя только {money(int(ws['balance']))}"])
            wd = await self.db.get_wallet(chat_id, dst.id, self.start_balance)
            await self.db.update_wallet(chat_id, src.id, balance=int(ws["balance"]) - amount)
            await self.db.update_wallet(chat_id, dst.id, balance=int(wd["balance"]) + amount)
        return CasinoResult([f"перевела {money(amount)} от {src.name} → {dst.name} ✅"], delta=-amount)

    async def grant(self, chat_id: int, dst: Person, amount: int) -> CasinoResult:
        async with self._lock(chat_id):
            w = await self.db.get_wallet(chat_id, dst.id, self.start_balance)
            new_bal = max(0, int(w["balance"]) + amount)
            await self.db.update_wallet(chat_id, dst.id, balance=new_bal)
        sign = "+" if amount >= 0 else "−"
        return CasinoResult([f"{dst.name} {sign}{money(abs(amount))}, теперь {money(new_bal)}"], balance=new_bal)
