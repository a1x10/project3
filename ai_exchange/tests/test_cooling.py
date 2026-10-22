import json
import os
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exchange.cooling import Cooling  # noqa: E402
from exchange.server import create_app, make_sim  # noqa: E402


class FakePowercfg:
    """Имитация powercfg с русским выводом: проверяем разбор по hex и порядок команд."""

    def __init__(self, ac=0, dc=0, fail_on=None):
        self.ac, self.dc, self.calls, self.fail_on = ac, dc, [], fail_on

    def __call__(self, args):
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            return 1, "Отказано в доступе."
        if args[1] == "/query":
            return 0, ("GUID подгруппы: 54533251-82be-4824-96c1-47b60b740d00  (Управление питанием процессора)\n"
                       "  Индекс возможного параметра: 000\n  Понятное имя возможного параметра: Пассивное\n"
                       "  Индекс возможного параметра: 001\n  Понятное имя возможного параметра: Активное\n"
                       f"  Текущий индекс параметра питания переменного тока: 0x{self.ac:08x}\n"
                       f"  Текущий индекс параметра питания постоянного тока: 0x{self.dc:08x}\n")
        if args[1] == "/setacvalueindex":
            self.ac = int(args[-1])
        if args[1] == "/setdcvalueindex":
            self.dc = int(args[-1])
        return 0, ""


def make(tmp_path, **kw):
    f = FakePowercfg(**kw)
    return Cooling(runner=f, windows=True, prev_path=str(tmp_path / "prev.json")), f


def test_enable_sets_active_and_remembers_previous(tmp_path):
    c, f = make(tmp_path, ac=0, dc=0)
    assert c.status()["active"] is False
    r = c.enable()
    assert r["ok"] and r["active"] and (f.ac, f.dc) == (1, 1)
    assert "MyASUS" in r["message"]
    assert f.calls[-1][:2] == ["powercfg", "/setactive"]  # применить схему
    assert json.load(open(tmp_path / "prev.json")) == {"ac": 0, "dc": 0}
    assert c.status()["active"] is True


def test_restore_returns_original_values(tmp_path):
    c, f = make(tmp_path, ac=1, dc=0)
    c.enable()
    assert (f.ac, f.dc) == (1, 1)
    r = c.restore()
    assert r["ok"] and (f.ac, f.dc) == (1, 0) and r["active"] is False


def test_enable_twice_is_harmless(tmp_path):
    c, f = make(tmp_path, ac=0, dc=0)
    c.enable()
    n = len(f.calls)
    r = c.enable()
    assert r["ok"] and "уже" in r["message"] and len(f.calls) == n + 1  # только запрос состояния
    c.restore()
    assert (f.ac, f.dc) == (0, 0)  # исходное не затёрто повторным нажатием


def test_failure_is_reported(tmp_path):
    c, _ = make(tmp_path, fail_on="/setacvalueindex")
    r = c.enable()
    assert r["ok"] is False and "Отказано" in r["message"]


def test_not_windows_does_nothing(tmp_path):
    c = Cooling(runner=lambda a: (_ for _ in ()).throw(AssertionError("не должно вызываться")), windows=False,
                prev_path=str(tmp_path / "p.json"))
    assert c.status()["supported"] is False
    assert c.enable()["ok"] is False and c.restore()["ok"] is False


def test_endpoints(tmp_path):
    app = create_app(make_sim(seed=3, model=None), autostart=False)
    fake = FakePowercfg()
    app.state.ctx.cooling = Cooling(runner=fake, windows=True, prev_path=str(tmp_path / "p.json"))
    c = TestClient(app)
    assert c.get("/api/cooling").json()["active"] is False
    r = c.post("/api/cooling/max").json()
    assert r["ok"] and r["active"] and (fake.ac, fake.dc) == (1, 1)
    assert c.get("/api/cooling").json()["active"] is True
    assert c.post("/api/cooling/restore").json()["active"] is False
    assert c.post("/api/cooling/boom").status_code == 404


def test_remote_clients_are_refused(tmp_path):
    app = create_app(make_sim(seed=3, model=None), autostart=False)
    app.state.ctx.cooling = Cooling(runner=FakePowercfg(), windows=True, prev_path=str(tmp_path / "p.json"))
    c = TestClient(app, client=("192.168.1.50", 5000))
    assert c.post("/api/cooling/max").status_code == 403
    assert c.get("/api/cooling").status_code == 403
