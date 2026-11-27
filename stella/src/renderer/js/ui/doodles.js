// Меловые рисунки для фона (собственный набор, генерируется как SVG-плитка).
const S = (d, x, y, r = 0, s = 1) => `<path d="${d}" transform="translate(${x} ${y}) rotate(${r}) scale(${s})"/>`;
const T = (txt, x, y, r = 0, size = 22) => `<text x="${x}" y="${y}" transform="rotate(${r} ${x} ${y})" font-size="${size}">${txt}</text>`;

const star = 'M0-34 L9-10 L34-8 L14 8 L21 33 L0 18 L-21 33 L-14 8 L-34-8 L-9-10Z';
const sparkle = 'M0-26 C3-6 6-3 26 0 C6 3 3 6 0 26 C-3 6-6 3-26 0 C-6-3-3-6 0-26Z';
const heart = 'M0 26 C-30 4-34-16-20-24 C-10-30-2-22 0-14 C2-22 10-30 20-24 C34-16 30 4 0 26Z';
const spiral = 'M0 0 C4-4 10 0 8 6 C6 14-6 14-10 6 C-16-6-4-18 8-16 C22-14 26 4 18 14 C8 28-16 26-24 12 C-32-4-22-26-2-28';
const question = 'M-10-14 C-10-28 14-30 14-14 C14-4 0-2 0 10 M0 22 L0 23';
const note = 'M-8 18 C-8 26-22 26-22 18 C-22 10-8 10-8 18 L-8-22 L14-28 L14 12 C14 20 0 20 0 12 C0 4 14 4 14 12';
const cloud = 'M-30 8 C-40 8-40-8-28-8 C-28-22-8-24-4-12 C2-24 22-20 20-6 C32-6 32 10 20 10Z M-20 14 L-26 24 M0 14 L-4 26 M18 14 L14 24';
const cup = 'M-18-10 L18-10 L14 18 L-14 18Z M18-4 C30-4 30 10 16 10 M-8-18 C-4-24-10-28-6-34 M4-18 C8-24 2-28 6-34';
const hatch = 'M0 0 L-6 34 M8 0 L2 34 M16 0 L10 34 M24 0 L18 34 M32 0 L26 34';
const xx = 'M0 0 L18 18 M18 0 L0 18 M28 0 L46 18 M46 0 L28 18 M56 0 L74 18 M74 0 L56 18';
const squiggle = 'M0 0 C10-12 20 12 30 0 C40-12 50 12 60 0';

export function doodleTile(dark = false) {
  const c = dark ? 'rgba(255,255,255,0.075)' : 'rgba(0,0,0,0.085)';
  const items = [
    S(star, 120, 110, 12), S(sparkle, 420, 70, 0, 0.9), S(heart, 690, 150, -8), S(spiral, 260, 330, 20, 1.2), S(question, 560, 270, 10, 1.3),
    S(note, 820, 390, -10), S(cloud, 120, 480, 0, 1.1), S(cup, 470, 560, 0, 1.1), S(hatch, 760, 600, 0), S(xx, 330, 180, 0),
    S(squiggle, 600, 470, -5), S(star, 900, 120, -14, 0.7), S(heart, 340, 640, 12, 0.7), S(question, 60, 260, -12, 1.1), S(sparkle, 690, 360, 0, 0.6),
    S(spiral, 940, 560, 0, 0.9), S(hatch, 40, 640, 0, 0.8), S(star, 610, 650, 25, 0.8),
    T('hmm...', 830, 260, -8), T('ok', 220, 220, -20, 26), T('zzz', 50, 380, -14, 24), T('?!', 400, 420, 8, 28), T('✓', 900, 470, 0, 26),
  ];
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="720" viewBox="0 0 1000 720"><g fill="none" stroke="${c}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" font-family="Segoe Print, Bradley Hand, cursive" >${items.join('')}</g><style>text{fill:${c};stroke:none}</style></svg>`;
  return `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`;
}
