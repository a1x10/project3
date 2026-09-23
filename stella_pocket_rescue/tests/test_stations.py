from app import stations

DUMP = """Station 0c:1d:af:11:22:33 (on wlan0)
	inactive time:	120 ms
	rx bytes:	40960
	tx bytes:	81920
	signal:  	-52 dBm
	connected time:	345 seconds
Station aa:bb:cc:44:55:66 (on wlan0)
	inactive time:	8000 ms
	rx bytes:	1024
	tx bytes:	2048
	signal:  	-84 dBm
	connected time:	30 seconds
"""


def test_parse_station_dump():
    st = stations._parse(DUMP)
    assert [s["mac"] for s in st] == ["0c:1d:af:11:22:33", "aa:bb:cc:44:55:66"]
    assert st[0]["signal"] == -52 and st[0]["connected_s"] == 345
    assert st[1]["inactive_ms"] == 8000


def test_proximity_buckets():
    assert stations.proximity(-50) == "рядом"
    assert stations.proximity(-65) == "близко"
    assert stations.proximity(-80) == "далеко"
    assert stations.proximity(-90) == "на пределе"


def test_distance_grows_as_signal_weakens():
    near = stations.distance_m(-50)
    far = stations.distance_m(-85)
    assert 0 < near < far


def test_connected_is_empty_without_iw(monkeypatch):
    # на машине разработки команды iw нет -> честный пустой список, без падения
    monkeypatch.setattr(stations, "_station_dump", lambda: "")
    monkeypatch.setattr(stations, "_read_leases", lambda: {})
    assert stations.connected() == []
