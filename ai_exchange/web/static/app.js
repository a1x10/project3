(() => {
  const $ = (id) => document.getElementById(id);
  const TZ = new Date().getTimezoneOffset() * 60;           // график показывает UTC — сдвигаем в местное время
  const T = (t) => t - TZ;
  const fmt = (v, d = 2) => Number(v).toLocaleString('ru-RU', { minimumFractionDigits: d, maximumFractionDigits: d });
  const sign = (v, d = 2) => (v >= 0 ? '+' : '') + fmt(v, d);
  const clock = (t) => new Date(t * 1000).toLocaleTimeString('ru-RU');
  const cls = (el, v) => { el.classList.toggle('up', v > 0.0005); el.classList.toggle('down', v < -0.0005); };

  // ---------- графики ----------
  const baseOpts = {
    autoSize: true,
    layout: { background: { color: '#161a1f' }, textColor: '#b7bdc6', fontSize: 15 },
    grid: { vertLines: { color: '#232a31' }, horzLines: { color: '#232a31' } },
    rightPriceScale: { borderColor: '#2b3139', minimumWidth: 96 },
    timeScale: { borderColor: '#2b3139', timeVisible: true, secondsVisible: true, rightOffset: 4, barSpacing: 9, minBarSpacing: 3 },
    crosshair: { mode: 0 },
  };
  const chart = LightweightCharts.createChart($('chart'), baseOpts);
  const candles = chart.addCandlestickSeries({
    upColor: '#0ecb81', downColor: '#f6465d', borderUpColor: '#0ecb81', borderDownColor: '#f6465d',
    wickUpColor: '#0ecb81', wickDownColor: '#f6465d',
    priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
  });
  const eqChart = LightweightCharts.createChart($('eqchart'), baseOpts);
  const pf = { type: 'custom', minMove: 0.01, formatter: (v) => v.toFixed(2) + '%' };
  const bhLine = eqChart.addLineSeries({ color: '#f0b90b', lineWidth: 3, priceFormat: pf, title: 'Buy&Hold' });
  const aiLine = eqChart.addLineSeries({ color: '#38bdf8', lineWidth: 4, priceFormat: pf, title: 'ИИ' });
  let syncing = false;
  const link = (a, b) => a.timeScale().subscribeVisibleLogicalRangeChange((r) => {
    if (syncing || !r) return; syncing = true; b.timeScale().setVisibleLogicalRange(r); syncing = false;
  });
  link(chart, eqChart); link(eqChart, chart);

  let marks = new Map();        // время свечи -> агрегированные сделки ИИ
  let shockTimes = [];
  let lastShockCount = 0;
  let firstEq = null;

  const BUCKET = 15;            // стрелки ИИ агрегируются по 15 с (3 свечи), чтобы график не превращался в кашу
  function renderMarkers() {
    const t0 = window.__t0 || 0, agg = new Map();
    for (const m of marks.values()) {
      const k = t0 + Math.floor((m.time - t0) / BUCKET) * BUCKET;
      const a = agg.get(k) || { bq: 0, sq: 0 };
      a.bq += m.bq; a.sq += m.sq; agg.set(k, a);
    }
    const out = [];
    for (const [t, m] of agg) {
      if (m.bq > 0) out.push({ time: T(t), position: 'belowBar', color: '#0ecb81', shape: 'arrowUp', size: m.bq > 0.08 ? 2 : 1 });
      if (m.sq > 0) out.push({ time: T(t), position: 'aboveBar', color: '#f6465d', shape: 'arrowDown', size: m.sq > 0.08 ? 2 : 1 });
    }
    for (const t of shockTimes) out.push({ time: T(t0 + Math.floor((t - t0) / 5) * 5), position: 'aboveBar', color: '#f0b90b', shape: 'circle', text: 'ШОК' });
    out.sort((a, b) => a.time - b.time);
    candles.setMarkers(out);
  }

  // ---------- состояние ----------
  let ws, paused = false, speed = 1, maxPos = 0.5, prevPrice = null;
  const send = (cmd, value) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ cmd, value })); };
  $('btn-pause').onclick = () => send('toggle_pause');
  $('btn-x1').onclick = () => send('speed', 1);
  $('btn-x10').onclick = () => send('speed', 10);
  $('btn-shock').onclick = () => send('shock');
  // «Полная мощность»: активное охлаждение Windows (вкл/выкл)
  let coolOn = false, toastTimer = null;
  const toast = (msg, err) => {
    const t = $('toast'); t.textContent = msg; t.className = 'toast' + (err ? ' err' : ''); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, err ? 9000 : 12000);
  };
  const paintCool = () => {
    const b = $('btn-cool'); b.classList.toggle('on', coolOn);
    b.textContent = coolOn ? '🌀 Полная мощность: ВКЛ' : '🌀 Полная мощность';
  };
  fetch('/api/cooling').then((r) => r.json()).then((s) => { coolOn = !!s.active; paintCool(); }).catch(() => {});
  $('btn-cool').onclick = async () => {
    try {
      const r = await fetch('/api/cooling/' + (coolOn ? 'restore' : 'max'), { method: 'POST' });
      const d = await r.json();
      if (r.ok && d.ok) { coolOn = !!d.active; paintCool(); toast(d.message, false); }
      else toast(d.message || d.detail || 'Не удалось изменить охлаждение', true);
    } catch (e) { toast('Нет связи с сервером', true); }
  };
  document.addEventListener('keydown', (e) => {
    if (e.code === 'Space') { e.preventDefault(); send('toggle_pause'); }
    if (e.key === '1') send('speed', 1);
    if (e.key === '0' || e.key === '2') send('speed', 10);
  });

  function onInit(m) {
    candles.setData(m.candles.map((c) => ({ ...c, time: T(c.time) })));
    const eqMap = new Map(m.equity.map((p) => [p.time, p]));
    firstEq = m.equity.length ? m.equity[0].time : null;
    const ai = [], bh = [];
    for (const c of m.candles) {   // до старта ИИ — нули, чтобы шкалы времени обоих графиков совпадали
      const p = eqMap.get(c.time) || { ai: 0, bh: 0 };
      ai.push({ time: T(c.time), value: p.ai }); bh.push({ time: T(c.time), value: p.bh });
    }
    aiLine.setData(ai); bhLine.setData(bh);
    marks = new Map(m.marks.map((x) => [x.time, x]));
    shockTimes = m.shocks || [];
    renderMarkers();
    chart.timeScale().scrollToPosition(4, false);
    $('tape').innerHTML = ''; $('thoughts').innerHTML = '';
    m.trades.forEach(addTrade); m.thoughts.forEach(addThought);
    if (m.model) $('model-info').textContent = `LightGBM: корреляция прогноза с реальностью ${m.model.corr.toFixed(2)}, ` +
      `направление угадано в ${(m.model.dir_acc * 100).toFixed(0)}% (проверка на новых данных)`;
    else $('model-info').textContent = 'Модель не загружена — работает базовая логика Avellaneda–Stoikov (запустите train.py)';
    if (window.Explain) window.Explain.init(m);
  }

  function addTrade(t) {
    const row = document.createElement('div');
    row.className = `tape-row ${t.s}${t.ai ? ' mine' : ''}`;
    row.innerHTML = `<span class="t">${clock(t.t)}</span><span>${fmt(t.p, 1)}</span><span>${t.q.toFixed(4)}</span>`;
    const tape = $('tape');
    tape.insertBefore(row, tape.firstChild);
    while (tape.children.length > 40) tape.removeChild(tape.lastChild);
  }
  function addThought(t) {
    const div = document.createElement('div');
    div.className = `thought ${t.tag}`;
    div.innerHTML = `<span class="t">${clock(t.t + (window.__t0 || 0))}</span>`;
    div.appendChild(document.createTextNode(t.text.replace(/(\d)\.(\d)/g, '$1,$2')));
    const box = $('thoughts');
    box.insertBefore(div, box.firstChild);
    while (box.children.length > 14) box.removeChild(box.lastChild);
  }

  let rowH = 26;
  function renderBook(book) {
    const fitN = (el) => Math.max(3, Math.floor(el.clientHeight / rowH));
    const na = Math.min(12, fitN($('asks'))), nb = Math.min(12, fitN($('bids')));
    book = { asks: book.asks.slice(0, na), bids: book.bids.slice(0, nb) };
    const maxq = Math.max(1e-9, ...book.bids.map((l) => l[1]), ...book.asks.map((l) => l[1]));
    const mk = (l, side) => `<div class="row-b ${side}${l[2] > 0 ? ' mine' : ''}"><div class="bar" style="width:${(l[1] / maxq * 100).toFixed(0)}%"></div>` +
      `<span>${fmt(l[0], 1)}</span><span>${l[1].toFixed(4)}</span></div>`;
    $('asks').innerHTML = book.asks.map((l) => mk(l, 'ask')).join('');
    $('bids').innerHTML = book.bids.map((l) => mk(l, 'bid')).join('');
    const r0 = $('bids').firstElementChild; if (r0 && r0.offsetHeight > 10) rowH = r0.offsetHeight;
    if (book.bids.length && book.asks.length) {
      const b = book.bids[0][0], a = book.asks[0][0];
      $('spread').innerHTML = `${fmt((a + b) / 2, 1)}<small>спред ${fmt(a - b, 1)} (${((a - b) / b * 1e4).toFixed(1)} б.п.)</small>`;
    }
  }

  const MODES = {
    warmup: ['Изучает рынок', 'chip-wait'], quoting: ['Котирует', 'chip-ok'], caution: ['Осторожно', 'chip-warn'],
    emergency: ['АВАРИЙНЫЙ РЕЖИМ', 'chip-alarm'], recovery: ['Восстановление', 'chip-warn'],
  };

  function onTick(m) {
    // шапка
    const pe = $('price');
    pe.textContent = fmt(m.price, 1);
    if (prevPrice !== null && m.price !== prevPrice) { pe.classList.remove('up', 'down'); pe.classList.add(m.price > prevPrice ? 'up' : 'down'); }
    prevPrice = m.price;
    $('change').textContent = sign(m.change_pct) + '%'; cls($('change'), m.change_pct);
    const s = Math.floor(m.sim_t), hh = Math.floor(s / 3600), mm = Math.floor(s % 3600 / 60), ss = s % 60;
    $('clock').textContent = (hh ? hh + ':' : '') + String(mm).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
    paused = m.paused; speed = m.speed;
    const bp = $('btn-pause'); bp.textContent = paused ? '▶ Продолжить' : '⏸ Пауза'; bp.classList.toggle('paused', paused);
    $('btn-x1').classList.toggle('active', speed === 1); $('btn-x10').classList.toggle('active', speed === 10);

    // график
    if (m.candle) candles.update({ ...m.candle, time: T(m.candle.time) });
    if (m.eq) { aiLine.update({ time: T(m.eq.time), value: m.eq.ai }); bhLine.update({ time: T(m.eq.time), value: m.eq.bh }); }
    if (m.marks && m.marks.length) { m.marks.forEach((x) => marks.set(x.time, x)); renderMarkers(); }
    if (m.shocks > lastShockCount) {
      lastShockCount = m.shocks;
      const b = $('shock-banner'); b.classList.remove('show'); void b.offsetWidth; b.classList.add('show');
      if (m.candle) { shockTimes.push(m.candle.time); renderMarkers(); }
    }

    renderBook(m.book);
    if (window.Explain) window.Explain.tick(m);
    m.trades.forEach(addTrade);
    (m.thoughts || []).forEach(addThought);

    // панель ИИ
    const a = m.ai;
    if (a) {
      const [txt, c] = paused ? ['Пауза', 'chip-wait'] : (MODES[a.mode] || ['—', 'chip-wait']);
      const chip = $('ai-status'); chip.textContent = txt; chip.className = 'chip ' + c;
      if (a.equity !== undefined) {
        $('m-equity').textContent = fmt(a.equity);
        const p = $('m-profit'); p.textContent = sign(a.profit_pct) + '%'; cls(p, a.profit_pct);
        const b = $('m-bh'); b.textContent = sign(a.bh_pct) + '%'; cls(b, a.bh_pct);
        const e = $('m-edge'); e.textContent = sign(a.edge_pct) + '%'; cls(e, a.edge_pct);
        $('m-fills').textContent = a.fills;
        $('m-win').textContent = a.win_rate == null ? '—' : a.win_rate.toFixed(0) + '%';
        $('m-dd').textContent = a.max_dd.toFixed(2) + '%';
      }
      $('m-spread').textContent = a.bid && a.ask ? ((a.ask - a.bid) / m.price * 1e4).toFixed(0) + ' б.п.' : '—';
      maxPos = a.max_pos || 0.5;
      const pos = Math.abs(a.pos) < 5e-5 ? 0 : a.pos;
      $('m-pos').textContent = pos.toFixed(4) + ' BTC';
      $('pos-fill').style.width = Math.min(100, pos / maxPos * 100) + '%';
      $('pos-target').style.left = Math.min(99, a.target / maxPos * 100) + '%';
      const pr = a.ml ? a.pred : 0;
      $('m-pred').textContent = a.ml ? `${sign(pr, 1)} б.п. ${pr > 0.3 ? '▲' : pr < -0.3 ? '▼' : '•'}` : 'нет модели';
      cls($('m-pred'), pr);
      const pf = $('pred-fill'), w = Math.min(50, Math.abs(pr) / 8 * 50);
      pf.style.width = w + '%'; pf.style.left = pr >= 0 ? '50%' : (50 - w) + '%'; pf.style.background = pr >= 0 ? '#0ecb81' : '#f6465d';
      $('m-imb').textContent = sign(a.imb5 * 100, 0) + '%'; cls($('m-imb'), a.imb5);
    }
    const an = $('analyst');
    if (m.analyst && m.analyst.enabled && m.analyst.text) { an.hidden = false; $('analyst-text').textContent = m.analyst.text; }
    else an.hidden = true;
  }

  function connect() {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    ws.onopen = () => { $('offline').hidden = true; };
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.type === 'init') { window.__t0 = m.t0; onInit(m); } else onTick(m);
    };
    ws.onclose = () => { $('offline').hidden = false; setTimeout(connect, 1000); };
    ws.onerror = () => ws.close();
  }
  connect();
})();
