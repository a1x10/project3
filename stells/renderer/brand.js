// Фирменный знак STELLS: четырёхлучевая звезда в орбите.
let uid = 0;
export function logo(size = 28, { animated = false } = {}) {
  const id = 'lg' + ++uid;
  return `<svg class="logo-mark ${animated ? 'anim' : ''}" width="${size}" height="${size}" viewBox="0 0 64 64" aria-label="STELLS">
    <defs>
      <linearGradient id="${id}a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9CC2FF"/><stop offset=".55" stop-color="#5B8CFF"/><stop offset="1" stop-color="#8B6CFF"/></linearGradient>
      <radialGradient id="${id}b" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
    </defs>
    <circle class="lm-orbit" cx="32" cy="32" r="27" fill="none" stroke="url(#${id}a)" stroke-width="2" stroke-dasharray="150 20" stroke-linecap="round" opacity=".9"/>
    <circle class="lm-sat" cx="57" cy="24" r="2.6" fill="#E6EEFF"/>
    <path class="lm-star" d="M32 10 C33.6 24 40 30.4 54 32 C40 33.6 33.6 40 32 54 C30.4 40 24 33.6 10 32 C24 30.4 30.4 24 32 10Z" fill="url(#${id}a)"/>
    <circle cx="32" cy="32" r="5" fill="url(#${id}b)"/>
  </svg>`;
}
export const wordmark = (cls = '') => `<span class="wordmark ${cls}">STELLS</span>`;
