// Панель «Внутри модели»: признаки, прогноз, сдвиг котировок, «прогноз vs факт», точность, важность признаков.
(() => {
  const $ = (id) => document.getElementById(id);
  const TZ = new Date().getTimezoneOffset() * 60;
  const T = (t) => t - TZ;
  const ru = (v, d) => v.toFixed(d).replace('.', ',');
  const sg = (v, d = 1) => (v >= 0 ? '+' : '−') + ru(Math.abs(v), d);
  const col = (v) => (v > 0.05 ? '#0ECB81' : v < -0.05 ? '#F6465D' : '#E8EAED');

  // имя, короткое имя, формат, группа
  const F = {
    imb1: ['Дисбаланс 1-го уровня стакана', 'Дисбаланс 1 ур.', 'pct', 'book'],
    imb5: ['Дисбаланс стакана (5 уровней)', 'Дисбаланс 5 ур.', 'pct', 'book'],
    imb10: ['Дисбаланс стакана (10 уровней)', 'Дисбаланс 10 ур.', 'pct', 'book'],
    micro_bps: ['Микроцена − середина, б.п.', 'Микроцена', 'bps', 'book'],
    spread_bps: ['Спред рынка, б.п.', 'Спред рынка', 'abs', 'book'],
    depth_log: ['Глубина стакана (логарифм)', 'Глубина стакана', 'abs', 'book'],
    flow_1s: ['Поток сделок за 1 с (покупки − продажи)', 'Поток 1 с', 'pct', 'flow'],
    flow_3s: ['Поток сделок за 3 с', 'Поток 3 с', 'pct', 'flow'],
    flow_10s: ['Поток сделок за 10 с', 'Поток 10 с', 'pct', 'flow'],
    signed_vol_3s: ['Чистый объём за 3 с, BTC', 'Объём 3 с', 'btc', 'flow'],
    trade_rate_3s: ['Число сделок за 3 с', 'Сделок за 3 с', 'int', 'flow'],
    ret_1s: ['Изменение цены за 1 с, б.п.', 'Цена 1 с', 'bps', 'price'],
    ret_3s: ['Изменение цены за 3 с, б.п.', 'Цена 3 с', 'bps', 'price'],
    ret_10s: ['Изменение цены за 10 с, б.п.', 'Цена 10 с', 'bps', 'price'],
    ret_30s: ['Изменение цены за 30 с, б.п.', 'Цена 30 с', 'bps', 'price'],
    vol_10s: ['Волатильность за 10 с, б.п.', 'Волатильн. 10 с', 'abs', 'vol'],
    vol_60s: ['Волатильность за 60 с, б.п.', 'Волатильн. 60 с', 'abs', 'vol'],
    vol_ratio: ['Волатильность: 10 с к 60 с', 'Волат. 10с/60с', 'abs', 'vol'],
    pos_norm: ['Позиция ИИ / лимит 0,5 BTC', 'Позиция ИИ', 'pct', 'pos'],
  };
  const ORDER = Object.keys(F);
  const fmtVal = (k, v) => {
    const t = F[k][2];
    if (t === 'pct') return sg(v * 100, 0) + '%';
    if (t === 'bps') return sg(v, 1);
    if (t === 'btc') return sg(v, 3);
    if (t === 'int') return String(Math.round(v));
    return ru(v, 2);
  };

  let built = false, opened = false, chart = null, predS = null, actS = null, lastT = null;
  const pts = new Map();    // время бакета -> {pred, actual}
  let impData = null, horizon = 3, neutral = 0.5, last = null, hasLog = true;

  function buildFeatures() {
    $('xp-features').innerHTML = ORDER.map((k) =>
      `<div class="xf g-${F[k][3]}"><span>${F[k][0]}</span><span class="v" id="xf-${k}">—</span><div class="bar"><i id="xb-${k}"></i></div></div>`).join('');
    built = true;
  }

  function buildImportance() {
    const box = $('xp-imp');
    if (!impData) { box.innerHTML = '<div class="xp-none">Модель не загружена: запустите train.py</div>'; return; }
    const max = Math.max(...impData.map((d) => d.share), 1e-9);
    box.innerHTML = impData.map((d) =>
      `<div class="imp"><span class="nm" title="${F[d.name] ? F[d.name][0] : d.name}">${F[d.name] ? F[d.name][1] : d.name}</span>` +
      `<div class="tr"><i style="width:${(d.share / max * 100).toFixed(1)}%"></i></div><span class="pc">${ru(d.share * 100, 1)}%</span></div>`).join('');
  }

  function ensureChart() {
    if (chart) return;
    const opts = {
      autoSize: true,
      layout: { background: { color: '#161a1f' }, textColor: '#b7bdc6', fontSize: 15 },
      grid: { vertLines: { color: '#232a31' }, horzLines: { color: '#232a31' } },
      rightPriceScale: { borderColor: '#2b3139', minimumWidth: 80 },
      timeScale: { borderColor: '#2b3139', timeVisible: true, secondsVisible: true, rightOffset: 3, barSpacing: 12 },
    };
    chart = LightweightCharts.createChart($('xp-chart'), opts);
    const pf = { type: 'custom', minMove: 0.01, formatter: (v) => v.toFixed(1) };
    actS = chart.addLineSeries({ color: '#f0b90b', lineWidth: 3, priceFormat: pf });
    predS = chart.addLineSeries({ color: '#38BDF8', lineWidth: 4, priceFormat: pf });
    redrawChart();
  }

  function sortedPts() {
    return [...pts.entries()].sort((a, b) => a[0] - b[0]);
  }
  function redrawChart() {
    if (!chart) return;
    const s = sortedPts();
    predS.setData(s.map(([t, p]) => ({ time: T(t), value: p.pred })));
    actS.setData(s.map(([t, p]) => ({ time: T(t), value: p.actual })));
    lastT = s.length ? s[s.length - 1][0] : null;
  }
  function addPoints(list) {
    if (!list || !list.length) return;
    let newBucket = false;
    for (const p of list) {
      if (lastT !== null && p.time > lastT) newBucket = true;
      pts.set(p.time, { pred: p.pred, actual: p.actual });
    }
    while (pts.size > 130) pts.delete(Math.min(...pts.keys()));
    if (!chart) return;
    if (newBucket || lastT === null) { redrawChart(); return; }
    const p = list[list.length - 1];
    if (p.time === lastT) { predS.update({ time: T(p.time), value: p.pred }); actS.update({ time: T(p.time), value: p.actual }); }
  }

  function row(k, v, cls = '') { return `<div class="${cls}"><span class="k">${k}</span><span class="val">${v}</span></div>`; }
  const orDash = (v, f) => (v === null || v === undefined ? '—' : f(v));

  function renderPred(e) {
    const pm = e.pred_model;
    const el = $('xp-pred');
    if (pm === null || pm === undefined) {
      el.textContent = '—'; el.style.color = '#8A94A3';
      $('xp-dir').textContent = e.pred_model === undefined ? '' : 'модель не загружена или копит историю';
    } else {
      el.textContent = sg(pm, 1) + ' б.п.'; el.style.color = col(pm);
      $('xp-dir').textContent = Math.abs(pm) < neutral ? 'нейтрально: движения не ждём' : (pm > 0 ? '▲ ждём рост за ' : '▼ ждём падение за ') + horizon + ' с';
    }
    const mid = (e.bid_off !== null && e.ask_off !== null);
    const centre = (e.shift !== null && e.skew !== null) ? e.shift - e.skew : null;
    let rows = '';
    rows += row('Прогноз модели (сырой)', orDash(pm, (v) => sg(v, 2) + ' б.п.'));
    rows += row('Прогноз, который использует ИИ (сглаженный)', orDash(e.pred_used, (v) => sg(v, 2) + ' б.п.'));
    rows += row('→ сдвиг котировок из-за прогноза', orDash(e.shift, (v) => sg(v, 2) + ' б.п. ' + (v > 0.05 ? '(вверх)' : v < -0.05 ? '(вниз)' : '')));
    rows += row('Поправка за позицию (Avellaneda–Stoikov)', orDash(e.skew, (v) => sg(-v, 2) + ' б.п.'));
    rows += row('Итоговый сдвиг центра котировок', orDash(centre, (v) => sg(v, 2) + ' б.п.'), 'total');
    rows += row('Ширина спреда ИИ', orDash(e.spread, (v) => ru(v, 1) + ' б.п.' + (e.widen_pct > 0.5 ? ` (+${ru(e.widen_pct, 0)}% из-за прогноза)` : '')));
    rows += row('Заявка на покупку (bid)', e.bid ? `${ru(e.bid, 1)} (${sg(e.bid_off, 1)} б.п.)` : 'снята');
    rows += row('Заявка на продажу (ask)', e.ask ? `${ru(e.ask, 1)} (${sg(e.ask_off, 1)} б.п.)` : 'снята');
    $('xp-rows').innerHTML = rows;
  }

  function renderAcc(a) {
    const el = $('xp-acc');
    if (a.pct === null) { el.textContent = '—'; el.style.color = '#8A94A3'; }
    else { el.textContent = Math.round(a.pct) + '%'; el.style.color = a.pct >= 50 ? '#0ECB81' : '#F6465D'; }
    $('xp-acc-sub').textContent = a.n_dir ? `угадано ${a.hits} из ${a.n_dir} прогнозов направления` : 'ждём первые прогнозы…';
    let r = '';
    r += row('За последние 100 прогнозов', orDash(a.recent_pct, (v) => Math.round(v) + '%'));
    r += row('Случайное угадывание', '50%');
    r += row('Нейтральных (|прогноз| < ' + ru(neutral, 1) + ' б.п.), не считаем', String(a.neutral));
    r += row('Корреляция прогноза и факта', orDash(a.corr, (v) => ru(v, 2)));
    r += row('Ошибка модели MAE', orDash(a.mae, (v) => ru(v, 2) + ' б.п.'));
    r += row('Ошибка без модели (прогноз «0»)', orDash(a.mae_zero, (v) => ru(v, 2) + ' б.п.'));
    $('xp-acc-rows').innerHTML = r;
  }

  function renderFeatures(f) {
    for (const k of ORDER) {
      const v = f[k]; if (v === undefined) continue;
      $('xf-' + k).textContent = fmtVal(k, v);
      const t = F[k][2], bar = $('xb-' + k);
      if (t === 'pct' || t === 'bps') {
        const scale = t === 'pct' ? 1 : 12;
        const w = Math.max(-1, Math.min(1, v / scale)) * 50;
        bar.style.width = Math.abs(w) + '%'; bar.style.left = w >= 0 ? '50%' : (50 + w) + '%';
        bar.style.background = w >= 0 ? '#0ECB81' : '#F6465D';
      } else bar.style.width = '0';
    }
  }

  function render() {
    if (!opened || !last) return;
    renderFeatures(last.features); renderPred(last); renderAcc(last.acc);
  }

  function open(v) {
    opened = v;
    $('xp').hidden = !v;
    if (v) { ensureChart(); render(); }
  }

  window.Explain = {
    init(m) {
      const x = m.explain;
      if (!built) buildFeatures();
      if (!x) return;
      impData = x.importance; horizon = x.horizon; neutral = x.neutral_bps; hasLog = x.log;
      $('xp-h').textContent = $('xp-h2').textContent = String(horizon).replace('.', ',');
      pts.clear(); lastT = null;
      addPoints(x.chart);
      buildImportance();
      $('btn-dl').style.display = $('xp-dl').style.display = hasLog ? '' : 'none';
    },
    tick(m) {
      const e = m.explain;
      if (!e) return;
      last = e;
      addPoints(e.chart);
      render();
    },
  };

  $('btn-xp').onclick = () => open(true);
  $('xp-close').onclick = () => open(false);
  document.addEventListener('keydown', (ev) => {
    if (ev.code === 'KeyM') open(!opened);
    if (ev.code === 'Escape' && opened) open(false);
  });
  buildFeatures();
})();
