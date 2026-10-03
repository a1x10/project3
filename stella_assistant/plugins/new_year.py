"""Пример своего навыка: «Стелла, сколько дней до Нового года?»

Положите .py-файл в папку plugins/ — Стелла подхватит его при запуске.
Шаблоны (регулярные выражения) проверяются на тексте в нижнем регистре, где числа уже записаны цифрами.
"""
from datetime import date

from stella.nlp.numbers import plural
from stella.skills.base import Reply, Skill, intent


class NewYear(Skill):
    name = "new_year"

    @intent(r"\bсколько (?:дней )?(?:осталось )?до нового года\b", priority=60)
    def days_left(self, ctx):
        today = date.today()
        ny = date(today.year + 1, 1, 1)
        n = (ny - today).days
        return Reply(f"До Нового года {n} {plural(n, 'день', 'дня', 'дней')}! Уже чувствую запах мандаринов.",
                     emotion="joy")
