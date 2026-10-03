import pytest

from stella.nlp.text import norm
from stella.skills.calc import convert_units, find_currency, safe_eval, to_expression


@pytest.mark.parametrize("text,value", [
    ("сколько будет двадцать пять умножить на четыре", 100),
    ("посчитай 2 плюс 2 умножить на 2", 6),
    ("корень из 144", 12),
    ("5 факториал", 120),
    ("сколько будет 15 процентов от 200", 30),
    ("два в степени десять", 1024),
    ("открыть скобку 2 плюс 3 закрыть скобку умножить на 4", 20),
])
def test_calc(text, value):
    assert safe_eval(to_expression(norm(text))) == pytest.approx(value)


def test_not_math():
    assert to_expression(norm("сколько лет моей бабушке")) is None
    with pytest.raises(ValueError):
        safe_eval("__import__('os')")


@pytest.mark.parametrize("text,result", [
    ("сколько будет 5 миль в километрах", 8.0467),
    ("30 километров в час в метрах в секунду", 8.3333),
    ("сколько метров в 3 футах", 0.9144),
    ("100 градусов фаренгейта в цельсиях", 37.7778),
    ("2 гигабайта в мегабайтах", 2048),
    ("10 соток в гектарах", 0.1),
])
def test_units(text, result):
    conv = convert_units(norm(text))
    assert conv is not None
    assert conv[3] == pytest.approx(result, rel=1e-3)


def test_currency_names():
    assert find_currency("100 долларов")[0] == "USD"
    assert find_currency("белорусских рублей")[0] == "BYN"
    assert find_currency("фунтов стерлингов")[0] == "GBP"
    assert find_currency("рублях")[0] == "RUB"
