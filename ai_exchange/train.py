"""Обучение ML-модели ИИ-трейдера (LightGBM) на данных, сгенерированных симуляцией.

Что делает:
  1. Запускает N независимых симуляций рынка (разные seed, толпа ботов, редкие шоки) — параллельно.
     В каждой торгует ИИ в базовом режиме (Avellaneda–Stoikov без ML), так что данные
     соответствуют реальным условиям работы (в стакане есть котировки ИИ, но признаки считаются без них).
  2. В каждый момент t записывает признаки (только публичные данные до t) и метку:
     изменение средней цены за ближайшие HORIZON секунд (б.п.) — то, что станет известно позже.
  3. Обучает LightGBM, проверяет на отдельных симуляциях (другие seed), печатает метрики, сохраняет модель.

Запуск:  python train.py            (по умолчанию ~5–10 минут на ноутбуке)
         python train.py --quick    (около 1–2 минут, для проверки)
"""
from __future__ import annotations

import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np

from exchange.features import FEATURES, WARMUP_TICKS
from exchange.sim import Simulation

HORIZON_SEC = 3.0
HORIZON = int(HORIZON_SEC * 10)
STRIDE = 2  # берём каждый 2-й тик, чтобы соседние строки были менее похожи
ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(ROOT, "models")
LOGS_DIR = os.path.join(ROOT, "logs")


def gen_episode(args):
    seed, sim_minutes = args
    sim = Simulation(seed=seed, ai_mode="baseline", random_shocks_per_hour=2.0, whale_gap=90.0)
    sim.run(WARMUP_TICKS)
    sim.start_ai()
    ai = sim.ai
    X, mids = [], []
    total = int(sim_minutes * 600)
    for i in range(total):
        sim.step()
        if ai.last_x is not None and ai.fb.ready:
            X.append(ai.last_x)
            mids.append(ai.mid)
        else:
            X.append(None)
            mids.append(ai.mid if ai.mid else sim.ref_price())
    # метки: будущая средняя цена (с точки зрения признаков — это ЦЕЛЬ, а не вход)
    rows, ys = [], []
    n = len(mids)
    for i in range(0, n - HORIZON, STRIDE):
        if X[i] is None:
            continue
        rows.append(X[i])
        ys.append((mids[i + HORIZON] / mids[i] - 1) * 1e4)
    return np.asarray(rows, dtype=np.float32), np.asarray(ys, dtype=np.float32), seed


def metrics(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    rmse = float(np.sqrt(np.mean((y - p) ** 2)))
    base = float(np.sqrt(np.mean((y - y.mean()) ** 2)))
    corr = float(np.corrcoef(y, p)[0, 1]) if p.std() > 0 else 0.0
    nz = (y != 0) & (p != 0)
    acc = float(np.mean(np.sign(y[nz]) == np.sign(p[nz]))) if nz.any() else 0.0
    thr = np.quantile(np.abs(p), 0.8)
    conf = (np.abs(p) >= thr) & (y != 0)
    acc_conf = float(np.mean(np.sign(y[conf]) == np.sign(p[conf]))) if conf.any() else 0.0
    return {"rmse": rmse, "rmse_baseline": base, "r2": 1 - (rmse / base) ** 2, "corr": corr,
            "dir_acc": acc, "dir_acc_top20": acc_conf,
            "mae": float(np.mean(np.abs(y - p))), "mae_baseline": float(np.mean(np.abs(y - y.mean())))}


def _pct(v):
    return f"{v * 100:.1f}%"


def render_report_txt(r: dict) -> str:
    """Человекочитаемый отчёт об обучении (на русском)."""
    d, v, t, m = r["data"], r["metrics_valid"], r["metrics_train"], r["timing_sec"]
    L = ["ОТЧЁТ ОБ ОБУЧЕНИИ ML-МОДЕЛИ ИИ-ТРЕЙДЕРА", "=" * 48, f"Дата: {r['trained_at']}", "",
         "ВЫБОРКА",
         f"  Симуляций: {d['episodes']} × {d['minutes_per_episode']:g} мин (процессов: {d['workers']})",
         f"  Всего строк: {d['rows_total']:,} (обучение {d['rows_train']:,}, проверка {d['rows_valid']:,})".replace(",", " "),
         "  Проверка идёт на отдельных симуляциях, которых модель не видела при обучении.",
         f"  Цель: изменение средней цены за {d['horizon_sec']:g} с вперёд, б.п. "
         f"(обрезка выбросов ±{d['label_clip_bps']:.1f} б.п.)", "",
         "МЕТРИКИ НА ПРОВЕРКЕ (новые симуляции)",
         f"  Корреляция прогноза с фактом: {v['corr']:.3f}",
         f"  Точность направления: {_pct(v['dir_acc'])} (на 20% самых уверенных прогнозов: {_pct(v['dir_acc_top20'])})",
         f"  MAE: {v['mae']:.3f} б.п. (если всегда прогнозировать среднее: {v['mae_baseline']:.3f} б.п.)",
         f"  RMSE: {v['rmse']:.3f} б.п. (без модели {v['rmse_baseline']:.3f}), R²: {v['r2'] * 100:.2f}%",
         f"  Для сравнения, на обучающих данных: корреляция {t['corr']:.3f}, точность направления {_pct(t['dir_acc'])}",
         "", "ВАЖНОСТЬ ПРИЗНАКОВ (доля вклада по gain)"]
    for row in r["feature_importance"]:
        L.append(f"  {row['feature']:<15} {row['gain_share'] * 100:5.1f}%  {'█' * int(round(row['gain_share'] * 60))}")
    p = r["model_params"]
    L += ["", "ПАРАМЕТРЫ МОДЕЛИ (LightGBM)"]
    L += [f"  {k}: {val}" for k, val in p["lightgbm"].items()]
    L += [f"  максимум раундов: {p['max_rounds']}, остановка по проверке через {p['early_stopping_rounds']} раундов",
          f"  итоговое число деревьев: {p['best_iteration']}", f"  время одного прогноза: {p['predict_latency_ms']:.3f} мс",
          "", "ВРЕМЯ",
          f"  генерация данных: {m['data']:.0f} с, обучение: {m['fit']:.0f} с, всего: {m['total']:.0f} с ({m['total'] / 60:.1f} мин)",
          "", "ОКРУЖЕНИЕ", f"  Python {r['env']['python']}, LightGBM {r['env']['lightgbm']}, NumPy {r['env']['numpy']}", ""]
    return "\n".join(L)


def write_report(logs_dir: str, report: dict) -> tuple[str, str]:
    os.makedirs(logs_dir, exist_ok=True)
    pj, pt = os.path.join(logs_dir, "train_report.json"), os.path.join(logs_dir, "train_report.txt")
    with open(pj, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(pt, "w", encoding="utf-8") as f:
        f.write(render_report_txt(report))
    return pj, pt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=100, help="число симуляций")
    ap.add_argument("--minutes", type=float, default=30, help="длина каждой симуляции, мин")
    ap.add_argument("--workers", type=int, default=max(1, min(4, (os.cpu_count() or 2) - 0)))
    ap.add_argument("--quick", action="store_true", help="быстрый режим (~1–2 минуты)")
    ap.add_argument("--rounds", type=int, default=600)
    ap.add_argument("--model-dir", default=MODEL_DIR, help="куда сохранить модель (по умолчанию models/)")
    ap.add_argument("--logs-dir", default=LOGS_DIR, help="куда сохранить отчёт (по умолчанию logs/)")
    args = ap.parse_args()
    if args.quick:
        args.episodes, args.minutes, args.rounds = 8, 15, 200
    import lightgbm as lgb

    t0 = time.time()
    print(f"[1/3] Генерация данных: {args.episodes} симуляций × {args.minutes:g} мин, процессов: {args.workers}")
    jobs = [(1000 + i, args.minutes) for i in range(args.episodes)]
    results = []
    if args.workers > 1:
        ctx = mp.get_context("spawn")
        with ctx.Pool(args.workers) as pool:
            for k, r in enumerate(pool.imap_unordered(gen_episode, jobs), 1):
                results.append(r)
                print(f"   готово {k}/{len(jobs)}  ({time.time() - t0:.0f} с)", flush=True)
    else:
        for k, j in enumerate(jobs, 1):
            results.append(gen_episode(j))
            print(f"   готово {k}/{len(jobs)}  ({time.time() - t0:.0f} с)", flush=True)
    t_data = time.time() - t0
    results.sort(key=lambda r: r[2])
    n_val = max(2, len(results) // 5)
    tr, va = results[:-n_val], results[-n_val:]
    Xtr = np.vstack([r[0] for r in tr]); ytr = np.concatenate([r[1] for r in tr])
    Xva = np.vstack([r[0] for r in va]); yva = np.concatenate([r[1] for r in va])
    print(f"   строк: обучение {len(ytr):,}, проверка {len(yva):,} (проверка — отдельные симуляции)".replace(",", " "))

    print("[2/3] Обучение LightGBM")
    t_fit0 = time.time()
    clip = float(np.quantile(np.abs(ytr), 0.995))
    params = dict(objective="regression", learning_rate=0.04, num_leaves=24, min_data_in_leaf=300,
                  feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1, lambda_l2=10.0,
                  num_threads=max(1, os.cpu_count() or 1), verbose=-1, seed=7)
    dtr = lgb.Dataset(Xtr, np.clip(ytr, -clip, clip), feature_name=FEATURES)
    dva = lgb.Dataset(Xva, np.clip(yva, -clip, clip), reference=dtr)
    booster = lgb.train(params, dtr, num_boost_round=args.rounds, valid_sets=[dva],
                        callbacks=[lgb.early_stopping(40, verbose=False), lgb.log_evaluation(50)])
    best = booster.best_iteration or booster.current_iteration()
    pva = booster.predict(Xva, num_iteration=best)
    ptr = booster.predict(Xtr, num_iteration=best)
    m_tr, m_va = metrics(ytr, ptr), metrics(yva, pva)
    t_fit = time.time() - t_fit0

    print("[3/3] Сохранение")
    os.makedirs(args.model_dir, exist_ok=True)
    booster.save_model(os.path.join(args.model_dir, "model.txt"), num_iteration=best)
    imp = sorted(zip(FEATURES, booster.feature_importance("gain")), key=lambda t: -t[1])
    tot = sum(v for _, v in imp) or 1
    # скорость одного прогноза (как в живой работе)
    x = Xva[:1].astype(np.float64)
    t1 = time.perf_counter()
    for _ in range(300):
        booster.predict(x, num_iteration=best, num_threads=1)
    lat_ms = (time.perf_counter() - t1) / 300 * 1000
    meta = {"features": FEATURES, "horizon_sec": HORIZON_SEC, "best_iteration": best, "label_clip_bps": clip,
            "metrics_train": m_tr, "metrics_valid": m_va, "rows_train": int(len(ytr)), "rows_valid": int(len(yva)),
            "importance": {k: v / tot for k, v in imp}, "predict_latency_ms": lat_ms,
            "trained_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(args.model_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    split = booster.feature_importance("split")
    gain = booster.feature_importance("gain")
    gtot = float(sum(gain)) or 1.0
    report = {
        "trained_at": meta["trained_at"],
        "data": {"episodes": args.episodes, "minutes_per_episode": args.minutes, "workers": args.workers,
                 "episodes_train": len(tr), "episodes_valid": len(va), "stride_ticks": STRIDE,
                 "rows_total": int(len(ytr) + len(yva)), "rows_train": int(len(ytr)), "rows_valid": int(len(yva)),
                 "horizon_sec": HORIZON_SEC, "label_clip_bps": clip, "features": FEATURES},
        "metrics_valid": m_va, "metrics_train": m_tr,
        "feature_importance": [{"feature": FEATURES[i], "gain_share": float(gain[i]) / gtot, "splits": int(split[i])}
                               for i in sorted(range(len(FEATURES)), key=lambda i: -gain[i])],
        "model_params": {"lightgbm": {k: v for k, v in params.items() if k not in ("verbose",)},
                         "max_rounds": args.rounds, "early_stopping_rounds": 40, "best_iteration": int(best),
                         "predict_latency_ms": lat_ms},
        "timing_sec": {"data": t_data, "fit": t_fit, "total": time.time() - t0},
        "env": {"python": sys.version.split()[0], "lightgbm": lgb.__version__, "numpy": np.__version__},
    }
    p_json, p_txt = write_report(args.logs_dir, report)

    print("\n=== МЕТРИКИ (горизонт прогноза %.0f с, цель — изменение цены в б.п.) ===" % HORIZON_SEC)
    for name, m in (("обучение", m_tr), ("ПРОВЕРКА ", m_va)):
        print(f"{name}: RMSE {m['rmse']:.3f} (без модели {m['rmse_baseline']:.3f}), R² {m['r2'] * 100:.2f}%, "
              f"корреляция {m['corr']:.3f}, точность направления {m['dir_acc'] * 100:.1f}% "
              f"(на 20% самых уверенных прогнозов: {m['dir_acc_top20'] * 100:.1f}%)")
    print("Важность признаков:", ", ".join(f"{k} {v / tot * 100:.0f}%" for k, v in imp[:6]))
    print(f"Деревьев: {best}, время одного прогноза: {lat_ms:.2f} мс")
    print(f"Модель сохранена в {os.path.join(args.model_dir, 'model.txt')}. Всего времени: {(time.time() - t0) / 60:.1f} мин")
    print(f"Отчёт: {p_json} и {p_txt}")


if __name__ == "__main__":
    main()
