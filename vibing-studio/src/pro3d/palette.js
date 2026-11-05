// Colour helpers: validate model-provided palettes and keep text readable.

const HEX = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;

export function normHex(v, fallback) {
  if (typeof v !== "string") return fallback;
  let s = v.trim();
  if (!s.startsWith("#")) s = `#${s}`;
  if (!HEX.test(s)) return fallback;
  if (s.length === 4) s = `#${s[1]}${s[1]}${s[2]}${s[2]}${s[3]}${s[3]}`;
  return s.toLowerCase();
}

export function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const toHex = (r, g, b) => `#${[r, g, b].map((x) => Math.max(0, Math.min(255, Math.round(x))).toString(16).padStart(2, "0")).join("")}`;

export function luminance(hex) {
  const [r, g, b] = rgb(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

export function mix(a, b, t) {
  const [r1, g1, b1] = rgb(a);
  const [r2, g2, b2] = rgb(b);
  return toHex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t);
}

/** Move `fg` towards white or black until it reaches `min` contrast against `bg`. */
export function ensureContrast(fg, bg, min) {
  if (contrast(fg, bg) >= min) return fg;
  const target = luminance(bg) > 0.4 ? "#000000" : "#ffffff";
  for (let t = 0.1; t <= 1.001; t += 0.1) {
    const c = mix(fg, target, t);
    if (contrast(c, bg) >= min) return c;
  }
  return target;
}

export const PALETTE_KEYS = ["bg", "surface", "text", "muted", "accent", "accent2"];

/** Fill gaps from the template default and fix unreadable combinations. */
export function normalizePalette(p, fallback) {
  const src = p && typeof p === "object" ? p : {};
  const out = {};
  for (const k of PALETTE_KEYS) out[k] = normHex(src[k], fallback[k]);
  const light = luminance(out.bg) > 0.45;
  if (Math.abs(luminance(out.surface) - luminance(out.bg)) < 0.004) out.surface = mix(out.bg, light ? "#000000" : "#ffffff", 0.05);
  out.text = ensureContrast(out.text, out.bg, 7);
  out.muted = ensureContrast(out.muted, out.bg, 4.5);
  out.accent = ensureContrast(out.accent, out.bg, 2.6);
  out.accent2 = ensureContrast(out.accent2, out.bg, 2);
  // text on accent buttons
  out.onAccent = contrast("#ffffff", out.accent) >= contrast("#0b0b10", out.accent) ? "#ffffff" : "#0b0b10";
  out.light = light;
  return out;
}

/** Ready-made palettes for the one-click switcher. */
export const PALETTES = [
  { id: "cosmos", name: "Космос", bg: "#07060f", surface: "#120f22", text: "#f1efff", muted: "#a3a0c2", accent: "#8b5cf6", accent2: "#22d3ee" },
  { id: "neon", name: "Неон", bg: "#05010d", surface: "#140826", text: "#fdf4ff", muted: "#c4a8d6", accent: "#ff2bd6", accent2: "#00f0ff" },
  { id: "ocean", name: "Океан", bg: "#03111f", surface: "#0a2236", text: "#e8f6ff", muted: "#8fb3c9", accent: "#0ea5e9", accent2: "#2dd4bf" },
  { id: "sunset", name: "Закат", bg: "#140708", surface: "#25110f", text: "#fff3ec", muted: "#d4a99a", accent: "#ff6b35", accent2: "#ffc145" },
  { id: "forest", name: "Лес", bg: "#06120c", surface: "#0e2219", text: "#eefbf3", muted: "#93b9a3", accent: "#22c55e", accent2: "#a3e635" },
  { id: "coffee", name: "Кофе", bg: "#140d09", surface: "#231811", text: "#fbf1e6", muted: "#c7ab92", accent: "#d4a373", accent2: "#f4d6a0" },
  { id: "rose", name: "Роза", bg: "#13060c", surface: "#241019", text: "#fff0f5", muted: "#d6a6b8", accent: "#f43f5e", accent2: "#fb7185" },
  { id: "gold", name: "Золото", bg: "#0c0a06", surface: "#1a160d", text: "#fbf6e8", muted: "#bfb08a", accent: "#e8b84a", accent2: "#fff1b8" },
  { id: "mono", name: "Монохром", bg: "#0a0a0a", surface: "#161616", text: "#fafafa", muted: "#a1a1a1", accent: "#ffffff", accent2: "#8a8a8a" },
  { id: "light", name: "Светлая", bg: "#f7f7fb", surface: "#ffffff", text: "#12121a", muted: "#5b5b6e", accent: "#5b4bff", accent2: "#00a8e8" },
  { id: "cream", name: "Крем", bg: "#faf6ef", surface: "#ffffff", text: "#1f1a14", muted: "#6e6253", accent: "#b5651d", accent2: "#d9a441" },
  { id: "mint", name: "Мята", bg: "#f2fbf7", surface: "#ffffff", text: "#0d1f17", muted: "#4f6b5d", accent: "#059669", accent2: "#0ea5e9" },
];
