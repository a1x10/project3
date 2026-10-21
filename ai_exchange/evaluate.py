"""Быстрая автономная проверка ИИ без сайта: N симуляций подряд, сравнение с Buy&Hold.

    python evaluate.py                    # 6 сид × 30 мин, режимы ml и baseline, шок в середине
    python evaluate.py --minutes 60 --seeds 10 --no-shock
"""
from __future__ import annotations

import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

import argparse
import statistics as st
import time

from exchange.ai_trader import PriceModel
from exchange.sim import Simulation, WARMUP_TICKS


def run_one(seed: int, minutes: float, mode: str, model, shock: bool, shock_at: float = 0.5):
    sim = Simulation(seed=seed, ai_mode=mode, model=model)
    sim.run(WARMUP_TICKS)
    sim.start_ai()
    total = int(minutes * 600)
    shock_tick = int(total * shock_at) if shock else -1
    pre = None
    for i in range(total):
        if i == shock_tick:
            pre = sim.ai_summary()
            p_before = sim.ref_price()
            sim.shock()
        if shock and i == shock_tick + 300:  # через 30 с после шока
            p_after = min(sim.mid_hist[-300:])
            ai_pos_after = sim.ex.wallets["ai"].btc_total
            shock_info = (p_before, p_after, pre["pos"] if pre else 0.0, ai_pos_after)
        sim.step()
    res = sim.ai_summary()
    res["shock_info"] = shock_info if shock else None
    res["thoughts"] = list(sim.ai.thoughts)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--no-shock", action="store_true")
    ap.add_argument("--modes", default="ml,baseline")
    args = ap.parse_args()
    model = PriceModel.load_default()
    if model is None:
        print("Модель не найдена (models/model.txt) — режим ml пропущен. Запустите python train.py")
    for mode in args.modes.split(","):
        if mode == "ml" and model is None:
            continue
        rows = []
        t0 = time.time()
        for s in range(args.seeds):
            r = run_one(500 + s, args.minutes, mode, model, not args.no_shock)
            rows.append(r)
            si = r["shock_info"]
            extra = ""
            if si:
                extra = f" | шок: цена {si[0]:.0f}→{si[1]:.0f} ({(si[1]/si[0]-1)*100:+.1f}%), позиция ИИ {si[2]:.3f}→{si[3]:.3f} BTC"
            print(f"[{mode}] seed {500+s}: ИИ {r['profit_pct']:+.2f}%  B&H {r['bh_pct']:+.2f}%  разница {r['edge_pct']:+.2f}%  "
                  f"просадка {r['max_dd']:.2f}%  сделок {r['fills']}  прибыльных {r['win_rate'] or 0:.0f}%{extra}")
        pr = [r["profit_pct"] for r in rows]; ed = [r["edge_pct"] for r in rows]
        print(f"[{mode}] ИТОГО за {args.seeds}×{args.minutes:g} мин: ИИ в среднем {st.mean(pr):+.2f}% (мин {min(pr):+.2f}%), "
              f"преимущество над B&H {st.mean(ed):+.2f}%, в плюсе относительно B&H в {sum(e > 0 for e in ed)}/{len(ed)} запусков, "
              f"в плюсе по абсолютной прибыли {sum(p > 0 for p in pr)}/{len(pr)}  ({time.time()-t0:.0f} с)\n")


if __name__ == "__main__":
    main()
