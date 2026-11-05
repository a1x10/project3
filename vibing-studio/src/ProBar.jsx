import React from "react";
import { FONTS, normalizeSpec } from "./pro3d/render.js";
import { PALETTES } from "./pro3d/palette.js";
import { TEMPLATES_3D } from "./pro3d/templates3d.js";

/** One-click design switches for a 3D Pro site: template, palette, fonts. No AI call needed. */
export default function ProBar({ spec, disabled, onChange, onNewSite }) {
  const apply = (patch) => onChange(normalizeSpec({ ...spec, ...patch }, { demo: false }));
  const current = PALETTES.find((p) => p.bg === spec.palette.bg && p.accent === spec.palette.accent)?.id;
  return (
    <div className="probar" aria-label="Дизайн 3D Pro">
      <div className="probar-row">
        <span className="probar-badge">3D Pro</span>
        <select value={spec.template} disabled={disabled} onChange={(e) => apply({ template: e.target.value })} title="Шаблон (тексты сохранятся)">
          {TEMPLATES_3D.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name} · {t.category}
            </option>
          ))}
        </select>
        <select value={spec.font} disabled={disabled} onChange={(e) => apply({ font: e.target.value })} title="Шрифты">
          {Object.entries(FONTS).map(([id, f]) => (
            <option key={id} value={id}>
              {f.name}
            </option>
          ))}
        </select>
        <button className="probar-new" onClick={onNewSite} disabled={disabled}>
          Новый сайт
        </button>
      </div>
      <div className="probar-swatches">
        {PALETTES.map((p) => (
          <button
            key={p.id}
            className={`swatch ${current === p.id ? "on" : ""}`}
            disabled={disabled}
            title={p.name}
            aria-label={`Палитра ${p.name}`}
            style={{ background: `linear-gradient(135deg, ${p.bg} 0 45%, ${p.accent} 45% 75%, ${p.accent2} 75%)` }}
            onClick={() => apply({ palette: p })}
          />
        ))}
      </div>
      <div className="probar-hint">Пишите в чат: «смени цвета на зелёные», «добавь тарифы», «другой стиль» — ИИ поменяет только содержимое.</div>
    </div>
  );
}
