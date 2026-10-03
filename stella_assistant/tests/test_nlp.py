from datetime import datetime

import pytest

from stella.nlp.numbers import fmt_num, normalize_numbers, plural, words_to_number
from stella.nlp.text import similarity, stem
from stella.nlp.timeparse import describe_duration, parse_day, parse_duration, parse_when

NOW = datetime(2026, 10, 3, 10, 15)  # суббота


@pytest.mark.parametrize("text,expected", [
    ("разбуди меня в семь тридцать", "разбуди меня в 7 30"),
    ("сколько будет две тысячи двадцать шесть плюс полтора", "сколько будет 2026 плюс 1.5"),
    ("три целых пять десятых", "3.5"),
    ("двадцать пятого октября", "25 октября"),
    ("сто двадцать пятый трек", "125 трек"),
    ("один миллион двести тысяч триста сорок пять", "1200345"),
    ("без пятнадцати восемь", "без 15 8"),
    ("тридцать пять сорок", "35 40"),
    ("пять, шесть, семь!", "5, 6, 7!"),
    ("напомни поздравить семью", "напомни поздравить семью"),
])
def test_normalize_numbers(text, expected):
    assert normalize_numbers(text) == expected


def test_helpers():
    assert words_to_number("двадцать пять") == 25
    assert plural(21, "минута", "минуты", "минут") == "минута"
    assert plural(12, "минута", "минуты", "минут") == "минут"
    assert fmt_num(1234567) == "1 234 567"
    assert fmt_num(2.5) == "2,5"


@pytest.mark.parametrize("text,prefer,expected", [
    ("напомни завтра в семь тридцать позвонить маме", "nearest", "2026-10-04 07:30"),
    ("разбуди меня в семь", "morning", "2026-10-04 07:00"),
    ("напомни в семь купить хлеб", "nearest", "2026-10-03 19:00"),
    ("напомни через двадцать минут", "nearest", "2026-10-03 10:35"),
    ("в пятницу вечером", "nearest", "2026-10-09 19:00"),
    ("без пятнадцати восемь", "morning", "2026-10-04 07:45"),
    ("в половине восьмого вечера", "nearest", "2026-10-03 19:30"),
    ("двадцать пятого октября в восемнадцать ноль ноль", "nearest", "2026-10-25 18:00"),
    ("в 2 часа дня", "nearest", "2026-10-03 14:00"),
    ("в полночь", "nearest", "2026-10-04 00:00"),
])
def test_parse_when(text, prefer, expected):
    w = parse_when(text, now=NOW, prefer=prefer)
    assert w is not None
    assert w.dt.strftime("%Y-%m-%d %H:%M") == expected


def test_parse_when_rest_and_repeat():
    w = parse_when("напомни завтра в 10 позвонить маме", now=NOW)
    assert "позвонить маме" in w.rest
    w = parse_when("по будням в шесть сорок пять", now=NOW, prefer="morning")
    assert w.repeat == [0, 1, 2, 3, 4]
    assert w.dt.weekday() == 0 and (w.dt.hour, w.dt.minute) == (6, 45)
    assert parse_when("поставь таймер на 5 минут", now=NOW) is None


@pytest.mark.parametrize("text,sec", [
    ("на 5 минут", 300), ("на полчаса", 1800), ("на полтора часа", 5400), ("на час двадцать", 4800),
    ("на 2 часа 15", 8100), ("на минуту", 60), ("четверть часа", 900),
])
def test_parse_duration(text, sec):
    assert parse_duration(text)[0] == sec


def test_describe():
    assert describe_duration(5400) == "1 час 30 минут"
    assert describe_duration(45) == "45 секунд"
    assert parse_day("погода завтра", NOW)[1] == 1


def test_stem_and_similarity():
    assert stem("спальне") == stem("спальня")
    assert similarity("свет в спальне", "спальня") > 0.5
    assert similarity("молоко", "хлеб") < 0.5
