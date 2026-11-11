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


def test_address_is_extracted_from_mixed_message():
    r = assess(["Нас двое, у мамы кровь из ноги, мы на 3 этаже, дом 12 по улице Абая"])
    assert r.location_text == "ул. Абая, д. 12 · этаж 3"
    assert r.address == {"street": "ул. Абая", "house": "12", "floor": 3}


def test_address_parts_collected_across_messages():
    r = assess(["помогите", "я на Абая 12", "третий этаж, второй подъезд"])
    assert r.location_text == "Абая, д. 12 · подъезд 2 · этаж 3"


def test_address_street_forms_and_landmarks():
    assert assess(["пр. Абылай хана 10 кв. 7"]).location_text == "пр. Абылай хана, д. 10 · кв. 7"
    assert assess(["мкр Самал-2, дом 33, 5-й этаж"]).location_text == "мкр. Самал-2, д. 33 · этаж 5"
    assert assess(["мы в подвале возле школы №5 на улице ленина"]).location_text == \
        "ул. Ленина · в подвале · возле школы №5"


def test_no_address_from_unrelated_numbers():
    assert assess(["у меня нога сломана, за 5 минут стало хуже"]).location_text is None
    assert assess(["ждем на Сейфуллина 5 минут"]).address == {}
