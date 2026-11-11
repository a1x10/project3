"""Тестовая версия на сервере (STELLA_DEMO=1): учебные вызовы и плашка «это не служба спасения».

Все данные здесь выдуманы для показа и помечены как учебные. Служба на сервере каждые сутки
перезапускается с чистой базой, так что то, что напишут посетители, тоже исчезает.
"""
import re

BAR_TEXT = "Тестовая версия. Это не служба спасения: звоните 112"
BAR = ('<div id="stellaDemoBar" role="note" style="position:fixed;top:0;left:0;right:0;z-index:2147483000;'
       'height:28px;display:flex;align-items:center;justify-content:center;padding:0 10px;background:#ffcc00;'
       'color:#1c1c1e;font:600 12.5px/1.2 -apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,Arial,sans-serif;'
       'text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + BAR_TEXT + '</div>')
# Страницы по-разному занимают экран: чат во всю высоту, остальные прокручиваются
SHIFT = {
    "index.html": ".app{margin-top:28px!important;height:calc(100vh - 28px)!important;height:calc(100dvh - 28px)!important}",
}
SHIFT_DEFAULT = "body{padding-top:28px!important}header{top:28px!important}"

# (сколько минут назад, устройство, заряд, сообщения пострадавшего, сдвиг координат в метрах или None)
SCENARIOS = (
    (24, "Samsung SM-A515F", 0.18,
     ("Помогите, нас завалило в подъезде, у брата сильно идет кровь из ноги",
      "Мы на 3 этаже, дом 12 по улице Абая, нас трое"), (60, -40)),
    (17, "iPhone", 0.54,
     ("У бабушки болит рука, похоже перелом, мы вышли во двор",
      "Мы во дворе дома 30 по улице Сатпаева, нас двое, бабушке 78 лет"), (-120, 90)),
    (9, "Xiaomi Redmi Note 10", 0.81,
     ("Мы в порядке, никто не ранен",
      "Стоим у дома 5 по улице Жандосова, нас 5 человек, есть дети"), (200, 150)),
    (3, "Android-телефон", 0.07,
     ("Алло, вы меня слышите?",), None),
)


def inject_bar(name: str, html: str) -> str:
    style = "<style>" + SHIFT.get(name, SHIFT_DEFAULT) + "</style>"
    match = re.search(r"<body[^>]*>", html, re.I)
    if not match:
        return BAR + html
    return html[:match.end()] + style + BAR + html[match.end():]


def offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    return lat + north_m / 111_320, lon + east_m / 78_000
