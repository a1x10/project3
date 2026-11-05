import { describe, expect, it } from "vitest";
import { contrast, normalizePalette, PALETTES } from "../src/pro3d/palette.js";
import { extractJson, specFromAnswer, buildProCreatePrompt, buildProEditPrompt, commentAfterJson } from "../src/pro3d/prompt.js";
import { normalizeSpec, renderSite } from "../src/pro3d/render.js";
import { SCENES } from "../src/pro3d/scenes.js";
import { TEMPLATES_3D } from "../src/pro3d/templates3d.js";

describe("3D Pro templates", () => {
  it("every template has a scene, a readable palette and renders a full page", () => {
    expect(TEMPLATES_3D.length).toBeGreaterThanOrEqual(14);
    const ids = new Set();
    for (const t of TEMPLATES_3D) {
      expect(ids.has(t.id)).toBe(false);
      ids.add(t.id);
      expect(SCENES[t.scene]).toBeTruthy();
      const html = renderSite({ template: t.id });
      expect(html.startsWith("<!DOCTYPE html>")).toBe(true);
      expect(html).toContain('<canvas id="hero3d"');
      expect(html).toContain('"three":"https://cdn.jsdelivr.net/npm/three@');
      expect(html).toContain(t.demo.brand.replace(/&/g, "&amp;"));
      const p = normalizePalette(t.palette, t.palette);
      expect(contrast(p.text, p.bg)).toBeGreaterThanOrEqual(7);
    }
  });

  it("escapes model text so it cannot inject markup", () => {
    const html = renderSite({ template: "orbit-ai", brand: "<script>alert(1)</script>", hero: { title: 'Hi "<img src=x onerror=alert(1)>"' } }, { demo: false });
    expect(html).not.toContain("<script>alert(1)</script>");
    expect(html).not.toContain("<img src=x");
    expect(html).toContain("&lt;script&gt;alert(1)&lt;/script&gt;");
  });

  it("normalizes specs: unknown template/icon, broken colours, low contrast, no demo text for AI specs", () => {
    const s = normalizeSpec(
      { template: "nope", palette: { bg: "#ffffff", text: "#fefefe", accent: "zzz" }, brand: "Кофе", hero: { title: "Привет" }, features: { items: [{ icon: "unknown-icon", title: "A", text: "B" }] } },
      { demo: false }
    );
    expect(s.template).toBe(TEMPLATES_3D[0].id);
    expect(s.features.items[0].icon).toBe("sparkles");
    expect(contrast(s.palette.text, s.palette.bg)).toBeGreaterThanOrEqual(7);
    expect(s.palette.accent).toMatch(/^#[0-9a-f]{6}$/);
    expect(s.palette.light).toBe(true);
    expect(s.sections).toEqual(["features"]); // nothing borrowed from the demo
    expect(s.pricing).toBeNull();
  });

  it("palette presets are all valid", () => {
    for (const p of PALETTES) {
      const n = normalizePalette(p, p);
      expect(contrast(n.text, n.bg)).toBeGreaterThanOrEqual(7);
    }
  });
});

describe("3D Pro prompts and parsing", () => {
  it("prompts list every template and carry the current spec for edits", () => {
    const create = buildProCreatePrompt();
    for (const t of TEMPLATES_3D) expect(create).toContain(t.id);
    const spec = normalizeSpec({ template: "warm-bistro" });
    const edit = buildProEditPrompt(spec);
    expect(edit).toContain("ТЕКУЩИЙ JSON САЙТА");
    expect(edit).toContain('"template": "warm-bistro"');
    expect(edit).not.toContain('"onAccent"');
  });

  it("extracts JSON from fences, bare text, think blocks and trailing commas", () => {
    expect(extractJson('Вот:\n```json\n{"brand":"A",}\n```\nГотово.')).toEqual({ brand: "A" });
    expect(extractJson('<think>{"x":1}</think> ответ {"brand":"B","hero":{"title":"T"}}')).toEqual({ brand: "B", hero: { title: "T" } });
    expect(extractJson("нет json")).toBeNull();
    expect(commentAfterJson('```json\n{}\n```\nСделал сайт кофейни.')).toBe("Сделал сайт кофейни.");
  });

  it("specFromAnswer builds a renderable spec", () => {
    const spec = specFromAnswer('```json\n{"template":"kinetic-fit","brand":"IRON","hero":{"title":"Сильнее","cta":"Записаться"},"stats":[{"value":"24/7","label":"открыто"}]}\n```');
    expect(spec.template).toBe("kinetic-fit");
    expect(spec.sections).toEqual(["stats"]);
    expect(renderSite(spec, { demo: false })).toContain("IRON");
    expect(specFromAnswer("просто текст")).toBeNull();
  });
});
