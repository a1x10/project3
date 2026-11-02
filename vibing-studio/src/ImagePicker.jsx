import React, { useEffect, useRef, useState } from "react";
import Icon from "./Icons.jsx";

const KEY = "vc-unsplash-key";

function loadKey() {
  try {
    return localStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

/** Search photos: Unsplash API when a key is set, keyless loremflickr otherwise. */
async function searchPhotos(q, key) {
  if (key) {
    const r = await fetch(
      `https://api.unsplash.com/search/photos?query=${encodeURIComponent(q)}&per_page=12&client_id=${encodeURIComponent(key)}`
    );
    if (!r.ok) throw new Error(`Unsplash ${r.status}`);
    const j = await r.json();
    return j.results.map((p) => ({
      id: p.id,
      thumb: p.urls.small,
      url: p.urls.regular,
      alt: p.alt_description || q,
    }));
  }
  // no key: each ?lock=N is a different, stable photo for the keyword
  const kw = encodeURIComponent(q.trim().split(/\s+/)[0] || "nature");
  return Array.from({ length: 12 }, (_, i) => ({
    id: `${kw}-${i + 1}`,
    thumb: `https://loremflickr.com/320/240/${kw}?lock=${i + 1}`,
    url: `https://loremflickr.com/1200/800/${kw}?lock=${i + 1}`,
    alt: q,
  }));
}

export default function ImagePicker({ images, onChange, onClose }) {
  const [q, setQ] = useState("");
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [key, setKey] = useState(loadKey);
  const ref = useRef(null);

  useEffect(() => {
    const onDown = (e) => {
      if (ref.current && !ref.current.contains(e.target) && !e.target.closest("[data-photo-btn]")) onClose();
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [onClose]);

  const saveKey = (v) => {
    setKey(v);
    try {
      localStorage.setItem(KEY, v);
    } catch {
      /* ignore */
    }
  };

  const run = async () => {
    if (!q.trim() || busy) return;
    setBusy(true);
    setErr("");
    try {
      setItems(await searchPhotos(q, key.trim()));
    } catch (e) {
      setErr(`Поиск не удался: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  const has = (id) => images.some((i) => i.id === id);
  const toggle = (it) =>
    onChange(has(it.id) ? images.filter((i) => i.id !== it.id) : [...images, { id: it.id, url: it.url, alt: it.alt }]);

  return (
    <div className="imgpick" ref={ref}>
      <div className="imgpick-head">
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="Что искать? по-английски: coffee, office, mountain"
          spellCheck={false}
        />
        <button onClick={run} disabled={busy || !q.trim()}>{busy ? "…" : "Найти"}</button>
      </div>
      {err && <div className="imgpick-err">{err}</div>}
      <div className="imgpick-grid">
        {items.map((it) => (
          <button key={it.id} className={has(it.id) ? "on" : ""} onClick={() => toggle(it)} title={it.alt}>
            <img src={it.thumb} alt={it.alt} loading="lazy" />
            {has(it.id) && <span className="imgpick-ok"><Icon name="check" size={14} /></span>}
          </button>
        ))}
        {!items.length && !busy && <p className="imgpick-empty">Выбери фото — модель вставит их адреса в <code>&lt;img&gt;</code>.</p>}
      </div>
      <details className="imgpick-key">
        <summary>Unsplash API key (необязательно)</summary>
        <input
          value={key}
          onChange={(e) => saveKey(e.target.value)}
          placeholder="Access Key — без него берутся фото loremflickr"
          spellCheck={false}
        />
      </details>
    </div>
  );
}