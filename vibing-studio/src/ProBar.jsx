import React from "react";
import { FONTS, normalizeSpec } from "./pro3d/render.js";
import { PALETTES } from "./pro3d/palette.js";
import { templateById } from "./pro3d/templates3d.js";

/** One-click colour and font switches for a 3D Pro site (the template itself is always chosen by the AI). */
export default function ProBar({ spec, disabled, onChange, onNewSite }) {
  const apply = (patch) => onChange(normalizeSpec({ ...spec, ...patch }, { demo: false }));
  const current = PALETTES.find((p) => p.bg === spec.palette.bg && p.accent === spec.palette.accent)?.id;
  return (
    <div className="probar" aria-label="Дизайн 3D Pro">
      <div className="probar-row">
        <span className="probar-badge">3D Pro</span>
        <span className="probar-tpl" title="Шаблон выбирает ИИ">{templateById(spec.template)?.name}</span>
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
      <div className="probar-hint">Шаблон подбирает ИИ. Пишите в чат: «смени цвета на зелёные», «добавь тарифы», «сделай стиль строже» — ИИ всё изменит сам.</div>
    </div>
  );
}
