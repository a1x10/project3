"""Проверка «вживую»: подключается к запущенному серверу по WebSocket, включает x10, через половину времени
нажимает «Рыночный шок» и в конце печатает итоги. Использование:  python live_check.py --minutes 5 [--port 8000]"""

import sys as _sys
for _s in (_sys.stdout, _sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass
import argparse, asyncio, json, time, urllib.request

import websockets


async def main(port: int, minutes: float):
    url = f"ws://localhost:{port}/ws"
    t_end = time.time() + minutes * 60
    t_shock = time.time() + minutes * 30
    shocked = False
    ticks = 0
    first = last = None
    shock_seen = {}
    modes = {}
    prices = []
    async with websockets.connect(url, max_size=None) as ws:
        init = json.loads(await ws.recv())
        assert init["type"] == "init"
        await ws.send(json.dumps({"cmd": "speed", "value": 10}))
        while time.time() < t_end:
            if not shocked and time.time() >= t_shock:
                await ws.send(json.dumps({"cmd": "shock"}))
                shocked = True
                shock_seen = {"t": time.time(), "pos": last["ai"]["pos"], "price": last["price"]}
            m = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if m["type"] != "tick":
                continue
            ticks += 1
            first = first or m
            last = m
            prices.append(m["price"])
            modes[m["ai"]["mode"]] = modes.get(m["ai"]["mode"], 0) + 1
            if shocked and "min_after" not in shock_seen:
                shock_seen["min_after"] = m["price"]
            if shocked:
                shock_seen["min_after"] = min(shock_seen["min_after"], m["price"])
                shock_seen["max_half"] = max(shock_seen.get("max_half", 0), m["ai"]["half_bps"])
                shock_seen["min_pos"] = min(shock_seen.get("min_pos", 9), m["ai"]["pos"])
    summ = json.loads(urllib.request.urlopen(f"http://localhost:{port}/api/summary").read())
    a = summ["ai"]
    print(f"Сообщений: {ticks} за {minutes:g} мин (≈{ticks / (minutes * 60):.1f}/с), ошибок сервера: {summ['errors']}")
    print(f"Время симуляции: {summ['sim_time'] / 60:.0f} мин; цена {first['price']:.0f} → {last['price']:.0f}")
    print(f"ИИ: {a['profit_pct']:+.2f}%  Buy&Hold: {a['bh_pct']:+.2f}%  разница: {a['edge_pct']:+.2f}%  "
          f"сделок: {a['fills']}  прибыльных: {a['win_rate']:.0f}%  макс. просадка: {a['max_dd']:.2f}%")
    if shock_seen:
        print(f"Шок: цена {shock_seen['price']:.0f} → минимум {shock_seen['min_after']:.0f} "
              f"({(shock_seen['min_after'] / shock_seen['price'] - 1) * 100:+.1f}%), позиция ИИ {shock_seen['pos']:.3f} → "
              f"{shock_seen['min_pos']:.3f} BTC, макс. спред ИИ {2 * shock_seen['max_half']:.0f} б.п.")
    print("Режимы ИИ (число сообщений):", modes)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--minutes", type=float, default=5)
    a = ap.parse_args()
    asyncio.run(main(a.port, a.minutes))
