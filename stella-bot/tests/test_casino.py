import random
from datetime import timedelta

import pytest

from bot.casino import Bet, Casino, parse_bet
from bot.db import DB
from bot.util import utcnow


@pytest.mark.parametrize(
    "text,expected",
    [
        ("красное 2000", ("roulette", "red", 2000, False)),
        ("на черное 1к", ("roulette", "black", 1000, False)),
        ("ставлю 500 на красное", ("roulette", "red", 500, False)),
        ("зеро 100", ("roulette", "zero", 100, False)),
        ("нечет 50", ("roulette", "odd", 50, False)),
        ("17 100", ("roulette", "17", 100, False)),
        ("рулетка число 7 200", ("roulette", "7", 200, False)),
        ("слоты 300", ("slots", None, 300, False)),
        ("монетка решка 50", ("coin", "tails", 50, False)),
        ("кинь монетку 100", ("coin", None, 100, False)),
        ("кости все", ("dice", None, None, True)),
        ("красное ва-банк", ("roulette", "red", None, True)),
    ],
)
def test_parse_bet(text, expected):
    bet = parse_bet(text)
    assert bet is not None
    assert (bet.game, bet.choice, bet.amount, bet.all_in) == expected


@pytest.mark.parametrize(
    "text",
    ["ты любишь красное вино 2000 года", "привет", "как дела", "17", "на", "орел или решка?", "красное и черное 5"],
)
def test_parse_bet_ignores_normal_talk(text):
    assert parse_bet(text) is None


@pytest.fixture
async def casino(tmp_path):
    db = DB(f"sqlite:///{tmp_path}/c.db")
    await db.init()
    yield Casino(db, start_balance=2000, bonus=500, bonus_hours=12, min_bet=10, rng=random.Random(7)), db
    await db.close()


async def test_wallet_auto_created_and_bets_change_balance(casino):
    c, db = casino
    p = await db.upsert_person("1@s.whatsapp.net", "Вася", "1")
    assert await c.balance(1, p) == 2000
    res = await c.play(1, p, Bet("roulette", "red", 500))
    assert res.balance in (1500, 2500)
    assert res.lines[0] and "выпало" in res.lines[1]
    assert await c.balance(1, p) == res.balance


async def test_bet_validation(casino):
    c, db = casino
    p = await db.upsert_person("2@s.whatsapp.net", "Петя", "2")
    assert "всего" in (await c.play(1, p, Bet("slots", None, 999999))).lines[0]
    assert "минималка" in (await c.play(1, p, Bet("slots", None, 1))).lines[0]
    assert "на что" in (await c.play(1, p, Bet("roulette", None, 100))).lines[0]
    res = await c.play(1, p, Bet("dice", None, None, all_in=True))
    assert res.balance in (0, 2000, 4000)


async def test_bonus_cooldown_and_transfer(casino):
    c, db = casino
    a = await db.upsert_person("3@s.whatsapp.net", "Аня", "3")
    b = await db.upsert_person("4@s.whatsapp.net", "Боря", "4")
    assert (await c.bonus(1, a)).balance == 2500
    assert "следующий" in (await c.bonus(1, a)).lines[0]
    await db.update_wallet(1, a.id, last_bonus_at=utcnow() - timedelta(hours=13))
    assert (await c.bonus(1, a)).balance == 3000
    await c.transfer(1, a, b, 1000)
    assert await c.balance(1, a) == 2000 and await c.balance(1, b) == 3000
    assert "только" in (await c.transfer(1, a, b, 10**6)).lines[0]
    top = await c.top(1)
    assert "Боря" in top.lines[1].split("\n")[0]


async def test_slots_rtp_is_below_one():
    c = Casino(None, 0, 0, 0, 0, rng=random.Random(42))  # type: ignore[arg-type]
    n = 200_000
    total = sum(c._spin(Bet("slots", None, 1))[0] for _ in range(n))
    assert 0.9 < total / n < 1.0
