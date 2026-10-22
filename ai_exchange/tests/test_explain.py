import csv
import json
import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from exchange.ai_trader import IDX, PriceModel  # noqa: E402
from exchange.explain import CSV_COLUMNS, NEUTRAL_BPS, ExplainTracker  # noqa: E402
from exchange.features import FEATURES  # noqa: E402
from exchange.server import create_app, make_sim  # noqa: E402
from exchange.sim import Simulation, WARMUP_TICKS  # noqa: E402

OUTCOME = ["mid_after", "actual_move_bps", "direction_hit"]


class StubModel:
    """Детерминированная «модель» без файла: прогноз зависит только от текущих признаков."""
    meta = {"horizon_sec": 3.0, "features": FEATURES, "metrics_valid": {"corr": 0.3, "dir_acc": 0.6, "mae": 5.0}}

    def predict(self, x):
        return float(x[IDX["imb5"]]) * 6.0 - float(x[IDX["ret_1s"]]) * 0.3

    def feature_importance(self):
        w = {n: float(i + 1) for i, n in enumerate(FEATURES)}
        tot = sum(w.values())
        return {n: v / tot for n, v in w.items()}


def run_session(tmp_path, seed=5, ticks=1500, cls=Simulation, explain=True, name="p.csv"):
    path = str(tmp_path / name)
    s = cls(seed=seed, ai_mode="ml", model=StubModel(), explain=explain, log_path=path if explain else None,
            wall_t0=1_700_000_000)
    s.run(WARMUP_TICKS)
    s.start_ai()
    s.run(ticks)
    if s.explain:
        s.explain.flush()
    return s, path


def read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    return run_session(tmp_path_factory.mktemp("log"))


def test_csv_columns_and_row_count(session):
    sim, path = session
    with open(path, encoding="utf-8-sig") as f:
        header = f.readline().strip().split(",")
    assert header == CSV_COLUMNS
    for needed in FEATURES + ["pred_model_bps", "bid", "ask", "actual_move_bps", "direction_hit"]:
        assert needed in header
    rows = read_csv(path)
    # строка попадает в журнал только после того, как прошёл горизонт (30 шагов)
    assert 1500 - 32 <= len(rows) <= 1500 - 28


def test_outcome_is_the_real_future_mid(session):
    _, path = session
    rows = read_csv(path)
    for i in range(0, len(rows) - 30, 37):
        assert float(rows[i]["mid_after"]) == pytest.approx(float(rows[i + 30]["mid"]), abs=0.011)
        expect = (float(rows[i]["mid_after"]) / float(rows[i]["mid"]) - 1) * 1e4
        assert float(rows[i]["actual_move_bps"]) == pytest.approx(expect, abs=1e-3)


def test_direction_hit_definition(session):
    _, path = session
    seen = {"hit": 0, "miss": 0, "neutral": 0}
    for r in read_csv(path):
        p, a = float(r["pred_model_bps"]), float(r["actual_move_bps"])
        if abs(p) < NEUTRAL_BPS or a == 0:
            assert r["direction_hit"] == ""
            seen["neutral"] += 1
        else:
            assert r["direction_hit"] == ("1" if (p > 0) == (a > 0) else "0")
            seen["hit" if r["direction_hit"] == "1" else "miss"] += 1
    assert seen["hit"] > 0 and seen["miss"] > 0 and seen["neutral"] > 0


def test_live_accuracy_equals_csv(session):
    sim, path = session
    rows = read_csv(path)
    hits = sum(r["direction_hit"] == "1" for r in rows)
    n_dir = sum(r["direction_hit"] in ("0", "1") for r in rows)
    acc = sim.explain.accuracy()
    assert (acc["hits"], acc["n_dir"]) == (hits, n_dir)
    assert acc["pct"] == pytest.approx(hits / n_dir * 100)
    assert acc["neutral"] == sum(r["direction_hit"] == "" for r in rows)
    assert acc["corr"] is not None and -1 <= acc["corr"] <= 1
    assert acc["mae"] > 0 and acc["mae_zero"] > 0


def test_quotes_in_log_are_real_orders(session):
    _, path = session
    rows = [r for r in read_csv(path) if r["mode"] == "quoting" and r["bid"] and r["ask"]]
    assert len(rows) > 1000
    for r in rows[::50]:
        mid, bid, ask = float(r["mid"]), float(r["bid"]), float(r["ask"])
        assert bid < ask
        assert float(r["bid_offset_bps"]) == pytest.approx((bid / mid - 1) * 1e4, abs=1e-3)
        assert float(r["ask_offset_bps"]) == pytest.approx((ask / mid - 1) * 1e4, abs=1e-3)
        assert float(r["ai_spread_bps"]) == pytest.approx(2 * float(r["half_bps"]), abs=1e-3)
        assert float(r["shift_bps"]) == pytest.approx(float(r["pred_used_bps"]), abs=1e-3)  # pred_gain = 1.0


def test_view_has_everything_for_the_panel(session):
    sim, _ = session
    v = sim.explain.view()
    assert list(v["features"]) == FEATURES
    for k in ("pred_model", "pred_used", "shift", "skew", "half", "spread", "bid", "ask", "acc", "chart", "rows"):
        assert k in v
    assert v["chart"] and set(v["chart"][-1]) == {"time", "pred", "actual"}
    assert len(sim.explain.chart_points()) <= 120


def test_logging_does_not_change_trading(tmp_path):
    a, _ = run_session(tmp_path, seed=9, ticks=900, explain=True, name="a.csv")
    b, _ = run_session(tmp_path, seed=9, ticks=900, explain=False)
    assert [(t.id, t.price, t.qty, t.buyer, t.seller) for t in a.ex.trades] == \
           [(t.id, t.price, t.qty, t.buyer, t.seller) for t in b.ex.trades]
    assert (a.eq, a.ai.fills) == (b.eq, b.ai.fills)


def test_log_has_no_lookahead(tmp_path):
    """Если после момента T «изменить будущее», признаки и прогнозы до T остаются теми же,
    а факт появляется в строках только если T его уже «видел»."""
    T = 1700

    class Altered(Simulation):
        def _advance_fundamental(self):
            super()._advance_fundamental()
            if self.tick_i > T:
                self._F *= 0.96 if self.tick_i % 2 else 1.03

    _, pa = run_session(tmp_path, seed=21, ticks=1600, name="a.csv")
    _, pb = run_session(tmp_path, seed=21, ticks=1600, cls=Altered, name="b.csv")
    ra, rb = read_csv(pa), read_csv(pb)
    t_end = T * 0.1
    inputs = [c for c in CSV_COLUMNS if c not in OUTCOME]
    n_in = n_full = 0
    for x, y in zip(ra, rb):
        s = float(x["sim_time_s"])
        if s <= t_end:
            assert [x[c] for c in inputs] == [y[c] for c in inputs]
            n_in += 1
        if s <= t_end - 3.0:
            assert [x[c] for c in OUTCOME] == [y[c] for c in OUTCOME]
            n_full += 1
    assert n_in > 1000 and n_full > 950


def test_previous_log_is_archived(tmp_path):
    path = tmp_path / "predictions.csv"
    path.write_text("x" * 500, encoding="utf-8")
    t = ExplainTracker(log_path=str(path))
    t.close()
    names = sorted(os.listdir(tmp_path))
    assert len(names) == 2 and any(n.startswith("predictions_") for n in names)
    assert open(path, encoding="utf-8-sig").read().startswith("time_utc")


def test_no_model_logs_features_but_no_predictions(tmp_path):
    path = str(tmp_path / "nm.csv")
    s = Simulation(seed=2, ai_mode="baseline", explain=True, log_path=path)
    s.run(WARMUP_TICKS)
    s.start_ai()
    s.run(200)
    s.explain.flush()
    rows = read_csv(path)
    assert rows and all(r["pred_model_bps"] == "" and r["direction_hit"] == "" for r in rows)
    assert all(r["imb5"] != "" for r in rows)
    assert s.explain.accuracy()["pct"] is None


# ---------- сервер ----------
def test_download_endpoint_and_websocket_payload(tmp_path):
    sim = make_sim(seed=4, model=StubModel(), log_path=str(tmp_path / "predictions.csv"))
    app = create_app(sim, autostart=True)
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            init = ws.receive_json()
            ex = init["explain"]
            assert ex["ml"] and ex["log"] and ex["horizon"] == 3.0
            assert [d["name"] for d in ex["importance"]][0] == "pos_norm"  # у заглушки самый большой вес
            assert sum(d["share"] for d in ex["importance"]) == pytest.approx(1.0)
            assert [d["share"] for d in ex["importance"]] == sorted((d["share"] for d in ex["importance"]), reverse=True)
            ws.send_json({"cmd": "speed", "value": 10})
            for _ in range(12):
                tick = ws.receive_json()
            e = tick["explain"]
            assert list(e["features"]) == FEATURES and e["acc"]["total"] > 0
        r = c.get("/api/predictions.csv")
        assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
        assert "predictions.csv" in r.headers["content-disposition"]
        body = r.content.decode("utf-8-sig")
        assert body.splitlines()[0].split(",") == CSV_COLUMNS and len(body.splitlines()) > 50
        assert c.get("/api/explain").json()["now"]["acc"]["total"] > 0
    assert app.state.ctx.errors == 0


def test_download_404_when_log_disabled():
    app = create_app(make_sim(seed=3, model=None), autostart=False)
    assert TestClient(app).get("/api/predictions.csv").status_code == 404


@pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, "models", "model.txt")), reason="нет обученной модели")
def test_real_model_importance_matches_features():
    m = PriceModel.load_default()
    imp = m.feature_importance()
    assert list(imp) == FEATURES and sum(imp.values()) == pytest.approx(1.0) and min(imp.values()) >= 0


# ---------- отчёт обучения ----------
def test_train_writes_report(tmp_path):
    mdir, ldir = tmp_path / "models", tmp_path / "logs"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "train.py"), "--episodes", "4", "--minutes", "3",
                        "--workers", "1", "--rounds", "25", "--model-dir", str(mdir), "--logs-dir", str(ldir)],
                       cwd=ROOT, capture_output=True, text=True, timeout=300, encoding="utf-8")
    assert r.returncode == 0, r.stderr[-800:]
    rep = json.loads((ldir / "train_report.json").read_text(encoding="utf-8"))
    d = rep["data"]
    assert d["rows_total"] == d["rows_train"] + d["rows_valid"] > 1000 and d["episodes"] == 4
    v = rep["metrics_valid"]
    for k in ("corr", "dir_acc", "mae", "rmse", "r2", "dir_acc_top20"):
        assert isinstance(v[k], float)
    assert [f["feature"] for f in rep["feature_importance"]].count("imb5") == 1
    assert sum(f["gain_share"] for f in rep["feature_importance"]) == pytest.approx(1.0)
    shares = [f["gain_share"] for f in rep["feature_importance"]]
    assert shares == sorted(shares, reverse=True)
    assert rep["model_params"]["lightgbm"]["num_leaves"] == 24 and rep["model_params"]["best_iteration"] >= 1
    assert rep["timing_sec"]["total"] >= rep["timing_sec"]["fit"] > 0
    txt = (ldir / "train_report.txt").read_text(encoding="utf-8")
    for needle in ("ВЫБОРКА", "МЕТРИКИ НА ПРОВЕРКЕ", "ВАЖНОСТЬ ПРИЗНАКОВ", "ПАРАМЕТРЫ МОДЕЛИ", "ВРЕМЯ"):
        assert needle in txt
    assert (mdir / "model.txt").exists() and (mdir / "meta.json").exists()
