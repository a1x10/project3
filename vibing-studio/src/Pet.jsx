import React, { useEffect, useId, useState } from "react";

/**
 * Orb companion shown while a site is being generated: a glossy purple ball
 * with two slanted pill eyes that blink, glance around and change with the mood.
 * Pass `mood` to pin one: idle | focus | happy | think | wink | wow
 */
const SEQ = ["idle", "focus", "happy", "idle", "think", "focus", "wink", "wow"];

function useMood(forced) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (forced) return undefined;
    const t = setInterval(() => setI((v) => (v + 1) % SEQ.length), 2600);
    return () => clearInterval(t);
  }, [forced]);
  return forced || SEQ[i];
}

const SPARKS = [[24, 22], [84, 30], [88, 62]];

export function Pet({ size = 44, mood: forced }) {
  const uid = useId().replace(/:/g, "");
  const mood = useMood(forced);
  return (
    <svg className="orb" data-mood={mood} width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <defs>
        <radialGradient id={`${uid}b`} cx="0.66" cy="0.3" r="0.95">
          <stop offset="0" style={{ stopColor: "var(--orb-1)" }} />
          <stop offset="0.45" style={{ stopColor: "var(--orb-2)" }} />
          <stop offset="1" style={{ stopColor: "var(--orb-3)" }} />
        </radialGradient>
        <linearGradient id={`${uid}e`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffffff" />
          <stop offset="1" stopColor="#e4d6ff" />
        </linearGradient>
        <linearGradient id={`${uid}m`} x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" style={{ stopColor: "var(--orb-rim)", stopOpacity: 0.5 }} />
          <stop offset="1" style={{ stopColor: "var(--orb-rim)", stopOpacity: 0 }} />
        </linearGradient>
      </defs>

      <ellipse className="orb-shadow" cx="50" cy="94" rx="24" ry="3.4" />

      <g className="orb-body">
        <circle cx="50" cy="50" r="38" fill={`url(#${uid}b)`} />
        {/* soft rim light on the lower-left edge */}
        <path className="orb-rim" d="M17.5 60 Q21 76 37 85" stroke={`url(#${uid}m)`} />

        {/* face sits up and to the right, like the reference */}
        <g className="orb-look">
          <g className="eyes-pill">
            <g transform="rotate(-16 57.5 33)">
              <rect className="eye eye-l" x="54.3" y="26" width="6.4" height="14" rx="3.2" fill={`url(#${uid}e)`} />
            </g>
            <g transform="rotate(-16 73 32)">
              <rect className="eye eye-r" x="69.8" y="25" width="6.4" height="14" rx="3.2" fill={`url(#${uid}e)`} />
            </g>
          </g>
          <g className="eyes-happy">
            <path d="M53 37.5 Q57.5 30 62 37.5" />
            <path d="M68.5 36.5 Q73 29 77.5 36.5" />
          </g>
          <ellipse className="orb-cheek" cx="52" cy="46" rx="3.6" ry="2" />
          <ellipse className="orb-cheek" cx="79" cy="45" rx="3.6" ry="2" />
          <path className="m-smile" d="M60 46 Q65.5 51.5 71 45.5" />
          <ellipse className="m-o" cx="65.5" cy="48" rx="2.4" ry="3.2" />
        </g>
      </g>

      {/* props */}
      <g className="x-focus">
        <text className="glyph c1" x="14" y="30">{"{ }"}</text>
        <text className="glyph c2" x="78" y="20">{"</>"}</text>
        <text className="glyph c3" x="84" y="50">;</text>
      </g>
      <g className="x-think">
        <text className="q" x="78" y="24">?</text>
      </g>
      <g className="x-happy">
        {SPARKS.map(([x, y], i) => (
          <g key={i} transform={`translate(${x} ${y})`}>
            <path className={`star st${i}`} d="M0 -5.5 Q0.8 -0.8 5.5 0 Q0.8 0.8 0 5.5 Q-0.8 0.8 -5.5 0 Q-0.8 -0.8 0 -5.5Z" />
          </g>
        ))}
      </g>
      <g className="x-wow">
        <text className="bang" x="79" y="24">!</text>
      </g>
    </svg>
  );
}

/** The word "Vibing" with a letter wave and bouncing dots. */
export function VibeWord() {
  return (
    <span className="vw" aria-label="Vibing">
      {"Vibing".split("").map((c, i) => (
        <span key={i} className="vw-c" style={{ animationDelay: `${i * 0.09}s` }}>{c}</span>
      ))}
      <span className="vw-dots"><i /><i /><i /></span>
    </span>
  );
}