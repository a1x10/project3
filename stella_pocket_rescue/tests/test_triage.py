from app.triage import GREEN, RED, UNKNOWN, YELLOW, assess, extract_coords, fallback_reply, first_aid


def test_trapped_is_red():
    r = assess(["Меня придавило плитой, ногу не чувствую"])
    assert r.priority == RED
    assert "под завалом" in r.tags


def test_unconscious_is_red():
    assert assess(["мама без сознания"]).priority == RED


def test_fracture_is_yellow():
    r = assess(["кажется сломал руку, но могу идти"])
    assert r.priority == YELLOW


def test_safe_is_green():
    assert assess(["Мы в порядке, не ранены, стоим во дворе"]).priority == GREEN


def test_no_info_is_unknown():
    assert assess(["алло"]).priority == UNKNOWN


def test_negation_is_respected():
    r = assess(["кровотечения нет, нет перелома"])
    assert "перелом" not in r.tags


def test_panic_does_not_raise_priority():
    calm = assess(["у отца сильное кровотечение из ноги"])
    loud = assess(["ПОМОГИТЕ ПОМОГИТЕ!!! МЫ ТУТ!!!"])
    assert calm.priority == RED
    assert loud.priority == UNKNOWN and loud.panic


def test_facts_accumulate_across_messages():
    r = assess(["ул. Абая 10, 3 этаж", "нас трое", "у ребенка перелом"])
    assert r.priority == YELLOW
    assert r.people == 3
    assert "ребёнок" in r.tags
    assert r.location_text.startswith("ул. Абая")
    assert r.missing == []


def test_coords_from_text():
    assert extract_coords("я тут 43,2389 76,8897") == (43.2389, 76.8897)
    assert extract_coords("дом 12 кв 5") is None


def test_fallback_asks_for_location_first():
    assert "Где вы" in fallback_reply(assess(["помогите"]))


def test_first_aid_for_bleeding():
    tips = first_aid(assess(["сильное кровотечение"]).tags)
    assert any("прижмите" in t.lower() for t in tips)
