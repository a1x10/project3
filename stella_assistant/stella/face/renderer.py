"""Отрисовка лица Стеллы средствами pygame.

Глаз строится геометрически: эллипс глазного яблока, срезанный кривыми верхнего и
нижнего века. Внутри — склера с тенью от века, радужка с прожилками, зрачок и блики.
Поверх — обводка века, ресницы, «лучики», брови, рот и эффекты (слёзы, сердечки, Zzz…).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame
import pygame.gfxdraw as gfx

from .emotions import FaceParams


def clamp(x, a=0.0, b=1.0):
    return a if x < a else b if x > b else x


def mix(c1, c2, t):
    t = clamp(t)
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1[:3], c2[:3]))


def desaturate(c, sat):
    g = 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
    return tuple(int(clamp(g + (x - g) * sat, 0, 255)) for x in c[:3])


def _ipts(pts):
    return [(int(round(x)), int(round(y))) for x, y in pts]


def aa_polygon(surf, color, pts):
    if len(pts) < 3:
        return
    ip = _ipts(pts)
    gfx.filled_polygon(surf, ip, color)
    gfx.aapolygon(surf, ip, color)


def aa_circle(surf, color, center, r):
    r = int(round(r))
    if r < 1:
        return
    x, y = int(round(center[0])), int(round(center[1]))
    gfx.filled_circle(surf, x, y, r, color)
    gfx.aacircle(surf, x, y, r, color)


def aa_ellipse(surf, color, center, rx, ry):
    rx, ry = int(round(rx)), int(round(ry))
    if rx < 1 or ry < 1:
        return
    x, y = int(round(center[0])), int(round(center[1]))
    gfx.filled_ellipse(surf, x, y, rx, ry, color)
    gfx.aaellipse(surf, x, y, rx, ry, color)


def bezier(p0, p1, p2, n=16):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                    u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
    return out


def ribbon(points, widths):
    """Полилиния -> многоугольник «ленты» заданной (переменной) толщины."""
    left, right = [], []
    n = len(points)
    for i, (x, y) in enumerate(points):
        x0, y0 = points[max(i - 1, 0)]
        x1, y1 = points[min(i + 1, n - 1)]
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln, dx / ln
        w = widths[i] / 2 if isinstance(widths, (list, tuple)) else widths / 2
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    return left + right[::-1]


def stroke(surf, color, points, width, taper=None, caps=True):
    """Сглаженная толстая линия. taper=(w0, w1) — толщина в начале и в конце."""
    if len(points) < 2 or width <= 0.3:
        return
    if taper:
        n = len(points) - 1
        widths = [taper[0] + (taper[1] - taper[0]) * i / n for i in range(n + 1)]
    else:
        widths = [width] * len(points)
    aa_polygon(surf, color, ribbon(points, widths))
    if caps:
        aa_circle(surf, color, points[0], widths[0] / 2)
        aa_circle(surf, color, points[-1], widths[-1] / 2)


def heart_points(cx, cy, size, n=28):
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * size / 32, cy - y * size / 32))
    return pts


def star_points(cx, cy, r, inner=0.28, rays=4, rot=0.0):
    pts = []
    for i in range(rays * 2):
        ang = rot + math.pi * i / rays
        rr = r if i % 2 == 0 else r * inner
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    return pts


def drop_points(cx, cy, r):
    """Капля (слеза/пот): острый кончик вверху."""
    pts = [(cx, cy - r * 2.1)]
    for i in range(0, 181, 15):
        a = math.radians(i)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


@dataclass
class Particle:
    kind: str
    x: float
    y: float
    vx: float
    vy: float
    life: float
    age: float = 0.0
    size: float = 10.0
    rot: float = 0.0


@dataclass
class AnimState:
    t: float = 0.0
    blink: float = 0.0          # 0..1 текущая фаза моргания
    gaze: tuple = (0.0, 0.0)    # итоговое направление взгляда (с учётом саккад)
    speech: float = 0.0         # громкость речи (рот)
    mic: float = 0.0            # громкость микрофона (индикатор «слушаю»)
    jitter: tuple = (0.0, 0.0)
    yawn: float = 0.0
    subtitle: str = ""
    info: str = ""


SCLERA = (246, 247, 252)
SHADE = (196, 201, 222)
PUPIL = (6, 8, 16)
WHITE = (255, 255, 255)


class FaceRenderer:
    def __init__(self, size=(800, 480), eye_color=(70, 190, 255), bg=(0, 0, 0), supersample: int = 1,
                 show_mouth=True, show_brows=True):
        self.W, self.H = size
        self.eye_color = tuple(eye_color)
        self.bg = tuple(bg)
        self.ss = max(1, int(supersample))
        self.show_mouth = show_mouth
        self.show_brows = show_brows
        s = min(self.W / 800, self.H / 480)
        self.s = s
        self.A = 126 * s       # полуширина глаза
        self.B = 116 * s       # полувысота глаза
        self.spacing = 180 * s
        self.cy = self.H * 0.45
        self.IR = 0.6 * self.B  # радиус радужки
        # буферы для глаз (фиксированный размер — без пересоздания каждый кадр)
        self.pad = int(14 * s)
        bw = int(2 * self.A * 1.15 + 2 * self.pad)
        bh = int(2 * self.B * 1.4 + 2 * self.pad)
        self.buf_size = (bw, bh)
        self.eye_buf = [pygame.Surface((bw * self.ss, bh * self.ss), pygame.SRCALPHA) for _ in range(2)]
        self.mask_buf = [pygame.Surface((bw * self.ss, bh * self.ss), pygame.SRCALPHA) for _ in range(2)]
        self.small_buf = [pygame.Surface((bw, bh), pygame.SRCALPHA) for _ in range(2)] if self.ss > 1 else None
        self.particles: list[Particle] = []
        self._spawn_acc: dict[str, float] = {}
        self._vignette = None
        self._font_cache: dict[int, pygame.font.Font] = {}
        self.last_eye_geom = [None, None]

    # ----------------------------------------------------------- геометрия --
    def eye_shape(self, cx, cy, a, b, upper, tilt, arch, lower, lcurve, inner_sign, closed, n=40):
        """-> (верхняя граница, нижняя граница, линия смыкания) видимой части глаза."""
        tops, bots, meet = [], [], []
        for i in range(n + 1):
            xn = -1 + 2 * i / n
            x = cx + xn * a
            k = max(0.0, 1 - xn * xn)
            eh = b * math.sqrt(k)
            top_e = cy - eh
            bot_e = cy + eh * 0.93
            inner = xn * inner_sign
            y_u = (cy - b) + upper * 2 * b + tilt * b * 0.55 * inner - arch * b * 0.42 * k
            y_l = (cy + b * 0.93) - lower * 2 * b - lcurve * b * 0.75 * k
            top0, bot0 = max(top_e, y_u), min(bot_e, y_l)
            if bot0 < top0:
                mid = (top0 + bot0) / 2
                top0 = bot0 = mid
            y_meet = top0 + 0.78 * (bot0 - top0)
            top = top0 + (y_meet - top0) * closed
            bot = bot0 + (y_meet - bot0) * closed
            meet.append((x, y_meet))
            tops.append((x, top))
            bots.append((x, bot))
        return tops, bots, meet

    # ------------------------------------------------------------- частицы --
    def _spawn(self, kind, rate, dt, factory):
        acc = self._spawn_acc.get(kind, 0.0) + rate * dt
        while acc >= 1.0:
            acc -= 1.0
            self.particles.append(factory())
        self._spawn_acc[kind] = acc

    def update(self, dt: float, p: FaceParams, eyes):
        """Рождение и движение частиц (сердечки, искры, слёзы, Zzz)."""
        s = self.s
        (lcx, lcy, la, lb), (rcx, rcy, ra, rb) = eyes
        if p.hearts > 0.05:
            def mk_heart():
                side = random.choice((-1, 1))
                cx = (lcx if side < 0 else rcx) + side * random.uniform(0.6, 1.1) * la
                return Particle("heart", cx, lcy + random.uniform(-0.2, 0.6) * lb, random.uniform(-10, 10) * s,
                                random.uniform(-55, -35) * s, random.uniform(1.6, 2.6), size=random.uniform(18, 32) * s)
            self._spawn("heart", 1.6 * p.hearts, dt, mk_heart)
        if p.sparkle > 0.05:
            def mk_star():
                side = random.choice((-1, 1))
                cx, cy, a, b = (lcx, lcy, la, lb) if side < 0 else (rcx, rcy, ra, rb)
                ang = random.uniform(math.pi * 0.9, math.pi * 2.1)
                return Particle("star", cx + math.cos(ang) * a * 1.25, cy + math.sin(ang) * b * 1.15, 0, 0,
                                random.uniform(0.5, 0.9), size=random.uniform(8, 15) * s, rot=random.uniform(0, 1))
            self._spawn("star", 2.2 * p.sparkle, dt, mk_star)
        if p.tears > 0.45:
            def mk_tear():
                side = random.choice((-1, 1))
                cx, cy, a, b = (lcx, lcy, la, lb) if side < 0 else (rcx, rcy, ra, rb)
                return Particle("tear", cx - side * a * 0.55 * -1, cy + b * 0.75, 0, 20 * s, 2.4, size=7 * s)
            self._spawn("tear", 0.35 * (p.tears - 0.4), dt, mk_tear)
        if p.zzz > 0.05:
            def mk_z():
                return Particle("z", rcx + ra * 0.95, rcy - rb * 0.8, 24 * s, -28 * s, 3.0, size=26 * s)
            self._spawn("z", 0.6 * p.zzz, dt, mk_z)
        alive = []
        for pt in self.particles:
            pt.age += dt
            if pt.age >= pt.life:
                continue
            if pt.kind == "tear":
                pt.vy += 120 * s * dt
            elif pt.kind == "heart":
                pt.vx += math.sin(pt.age * 3 + pt.y * 0.01) * 6 * s * dt
            elif pt.kind == "z":
                pt.size += 8 * s * dt
            pt.x += pt.vx * dt
            pt.y += pt.vy * dt
            alive.append(pt)
        self.particles = alive[-80:]

    # ------------------------------------------------------------- рендер --
    def eye_positions(self, p: FaceParams, st: AnimState):
        s = self.s
        bob = p.bob * 7 * s * math.sin(2 * math.pi * p.bob_speed * st.t)
        breath = 1.6 * s * math.sin(2 * math.pi * 0.22 * st.t)
        jx, jy = st.jitter
        cx0 = self.W / 2 + jx
        cy0 = self.cy + bob + breath + jy
        tilt = p.tilt * 16 * s
        a = self.A * p.eye_w
        b = self.B * p.eye_h
        # левый на экране глаз — правый глаз Стеллы; внутренний угол у него справа
        return [(cx0 - self.spacing, cy0 + tilt, a, b), (cx0 + self.spacing, cy0 - tilt, a, b)]

    def render(self, screen: pygame.Surface, p: FaceParams, st: AnimState):
        ec = self.eye_color
        bg = self.bg
        screen.fill(bg)
        if p.glow > 0.02:
            self._draw_vignette(screen, p.glow * (0.78 + 0.22 * math.sin(st.t * 4.5)))
        eyes = self.eye_positions(p, st)
        rim = mix(ec, WHITE, 0.15)
        if p.tint_amt > 0.4:
            rim = mix(rim, p.tint, (p.tint_amt - 0.4) * 0.8)
        closed = clamp(max(p.closed, st.blink))
        # румянец под глазами
        if p.blush > 0.02:
            for i, (cx, cy, a, b) in enumerate(eyes):
                inner = 1 if i == 0 else -1
                self._draw_blush(screen, (cx - inner * a * 0.1, cy + self.B * 1.02), a * 0.55, self.B * 0.2, p.blush)
        for i, (cx, cy, a, b) in enumerate(eyes):
            side = -1 if i == 0 else 1      # -1 левый на экране
            inner = -side                   # направление к переносице
            sq = p.squint_asym * side * 0.5
            upper = clamp(p.upper + max(0.0, sq) * 0.6 + st.yawn * 0.25, 0, 1.1)
            lower = clamp(p.lower + max(0.0, sq) * 0.5 + st.yawn * 0.2, 0, 1.0)
            tops, bots, meet = self.eye_shape(cx, cy, a, b, upper, p.upper_tilt, p.upper_arch, lower,
                                              p.lower_curve, inner, closed)
            self.last_eye_geom[i] = (tops, bots)
            gx = clamp(st.gaze[0] + p.converge * 0.32 * inner, -1.2, 1.2)
            gy = clamp(st.gaze[1], -1.2, 1.2)
            visible = [(x, t) for (x, t), (_, bb) in zip(tops, bots) if bb - t > 0.6]
            if closed < 0.97 and len(visible) >= 3:
                self._draw_eye_body(screen, i, cx, cy, a, b, tops, bots, gx, gy, p, st)
                self._draw_rim(screen, tops, bots, rim, inner, a, p)
            else:
                pts = meet if p.closed > 0.5 else [(x, (t + bb) / 2) for (x, t), (_, bb) in zip(tops, bots)]
                pts = pts[2:-2]
                stroke(screen, rim, pts, 5 * self.s)
                self._draw_lashes(screen, pts, rim, inner, a, closed=True)
            if p.crow > 0.03:
                self._draw_crow_feet(screen, tops, bots, inner, a, mix(bg, rim, p.crow * 0.9))
            if self.show_brows and p.brow_alpha > 0.02:
                self._draw_brow(screen, cx, cy, a, b, inner, side, p, mix(bg, ec, p.brow_alpha))
        if self.show_mouth:
            self._draw_mouth(screen, eyes, p, st)
        self.update_effects(screen, p, st, eyes)
        self._draw_particles(screen, rim)
        if st.subtitle:
            self._draw_text(screen, st.subtitle, (self.W / 2, self.H - 14 * self.s), 20, mix(bg, ec, 0.6))
        if st.info:
            self._draw_text(screen, st.info, (self.W / 2, 16 * self.s), 22, mix(bg, ec, 0.75))

    # ---------------------------------------------------------------- глаз --
    def _iris_color(self, p: FaceParams):
        c = mix(self.eye_color, p.tint, p.tint_amt)
        return desaturate(c, p.saturation)

    def _draw_eye_body(self, screen, idx, cx, cy, a, b, tops, bots, gx, gy, p, st):
        ss = self.ss
        bw, bh = self.buf_size
        ox, oy = cx - bw / 2, cy - bh / 2          # левый верхний угол буфера на экране
        surf = self.eye_buf[idx]
        mask = self.mask_buf[idx]

        def L(pt):
            return ((pt[0] - ox) * ss, (pt[1] - oy) * ss)

        surf.fill(SCLERA + (255,))
        # радужка
        ir = self.IR * p.iris * ss
        ix = (cx - ox) * ss + gx * max(0.0, a * ss - ir * 0.9) * 0.85
        iy = (cy - oy) * ss + gy * max(0.0, b * ss - ir * 0.75) * 0.8
        ci = self._iris_color(p)
        dark = mix(ci, (0, 0, 0), 0.55)
        light = mix(ci, WHITE, 0.32)
        pygame.draw.circle(surf, dark, (ix, iy), ir)
        pygame.draw.circle(surf, ci, (ix, iy), ir * 0.9)
        pygame.draw.circle(surf, mix(ci, light, 0.55), (ix, iy), ir * 0.68)
        hippus = 1 + 0.025 * math.sin(st.t * 1.7) + 0.015 * math.sin(st.t * 4.1)
        pr = ir * clamp(p.pupil * hippus, 0.12, 0.9)
        streak = mix(ci, dark, 0.45)
        for k in range(18):
            ang = k * math.pi * 2 / 18 + 0.2
            r0, r1 = pr * 1.08, ir * (0.84 if k % 2 else 0.74)
            pygame.draw.line(surf, streak, (ix + math.cos(ang) * r0, iy + math.sin(ang) * r0),
                             (ix + math.cos(ang) * r1, iy + math.sin(ang) * r1), max(1, ss))
        pygame.draw.circle(surf, mix(ci, (0, 0, 0), 0.7), (ix, iy), pr * 1.1)
        pygame.draw.circle(surf, PUPIL, (ix, iy), pr)
        if p.tears > 0.05:  # влажный блеск по нижнему краю радужки
            rect = pygame.Rect(0, 0, ir * 1.7, ir * 1.7)
            rect.center = (ix, iy)
            pygame.draw.arc(surf, mix(ci, WHITE, 0.4 + 0.5 * p.tears), rect, math.pi * 1.15, math.pi * 1.85,
                            max(1, int(3 * ss * p.tears)))
        # блики — «блеск в глазах»
        sh = clamp(p.shine)
        if sh > 0.03:
            hc = mix(ci, WHITE, 0.35 + 0.65 * sh)
            if p.hearts > 0.5:  # влюблённость: блики-сердечки
                pygame.draw.polygon(surf, hc, heart_points(ix - ir * 0.3, iy - ir * 0.32, ir * 0.42 * sh))
            else:
                pygame.draw.circle(surf, hc, (ix - ir * 0.36, iy - ir * 0.4), ir * (0.1 + 0.15 * sh))
            pygame.draw.circle(surf, hc, (ix + ir * 0.34, iy + ir * 0.3), ir * (0.04 + 0.06 * sh))
        if p.sparkle > 0.05:
            tw = 0.75 + 0.25 * math.sin(st.t * 6 + idx)
            pygame.draw.polygon(surf, WHITE, star_points(ix + ir * 0.18, iy - ir * 0.5, ir * 0.24 * p.sparkle * tw,
                                                         0.25, 4, st.t * 0.6))
        # маска видимой части + тень от верхнего века
        mask.fill((0, 0, 0, 0))
        poly = [L(pt) for pt in tops] + [L(pt) for pt in reversed(bots)]
        pygame.draw.polygon(mask, (255, 255, 255, 255), poly)
        depth = b * 0.16 * ss
        band = [L(pt) for pt in tops] + [(L(t)[0], min(L(t)[1] + depth, L(bb)[1])) for t, bb in
                                          zip(reversed(tops), reversed(bots))]
        pygame.draw.polygon(mask, SHADE + (255,), band)
        if p.tears > 0.05:  # «стоящие» слёзы над нижним веком
            wet = [(L(bb)[0], L(bb)[1] - 3 * ss) for bb in bots]
            wet_band = wet + [L(bb) for bb in reversed(bots)]
            pygame.draw.polygon(mask, (255, 255, 255, 255), wet_band)
        surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        if p.tears > 0.05:
            line = [L((x, y - 2.5)) for x, y in bots[3:-3]]
            if len(line) > 1:
                pygame.draw.lines(surf, mix(SCLERA, (120, 190, 255), 0.6 * p.tears) + (255,), False, line,
                                  max(1, int(2 * ss)))
        if ss > 1:
            pygame.transform.smoothscale(surf, (bw, bh), self.small_buf[idx])
            screen.blit(self.small_buf[idx], (ox, oy))
        else:
            screen.blit(surf, (ox, oy))

    def _draw_rim(self, screen, tops, bots, rim, inner, a, p):
        s = self.s
        idx = [i for i, (t, bb) in enumerate(zip(tops, bots)) if bb[1] - t[1] > 0.6]
        if len(idx) < 3:
            return
        i0, i1 = max(0, idx[0] - 1), min(len(tops) - 1, idx[-1] + 1)  # захватываем уголки глаза
        vis = list(zip(tops[i0:i1 + 1], bots[i0:i1 + 1]))
        top_line = [t for t, _ in vis]
        bot_line = [bb for _, bb in vis]
        # верхнее веко — толще (линия ресниц), нижнее — тоньше
        stroke(screen, rim, top_line, 5.5 * s, taper=(3.5 * s, 3.5 * s) if False else None)
        stroke(screen, mix(self.bg, rim, 0.75), bot_line, 2.6 * s)
        stroke(screen, rim, [top_line[0], bot_line[0]], 2.6 * s)
        stroke(screen, rim, [top_line[-1], bot_line[-1]], 2.6 * s)
        self._draw_lashes(screen, top_line, rim, inner, a)

    def _draw_lashes(self, screen, top_line, rim, inner, a, closed=False):
        s = self.s
        n = len(top_line)
        if n < 6:
            return
        # внешний край века — со стороны, противоположной переносице
        idxs = [0, 2, 4] if inner > 0 else [n - 1, n - 3, n - 5]
        for k, j in enumerate(idxs):
            x, y = top_line[j]
            out = -inner
            if closed:  # у закрытых глаз ресницы смотрят вниз-наружу
                ang = math.radians(25 + 22 * k)
                dx, dy = out * math.cos(ang), math.sin(ang)
            else:
                ang = math.radians(35 + 18 * k)
                dx, dy = out * math.cos(ang), -math.sin(ang)
            ln = a * (0.16 - 0.035 * k)
            p0 = (x, y)
            p2 = (x + dx * ln, y + dy * ln)
            p1 = (x + dx * ln * 0.6, y + dy * ln * 0.3)
            stroke(screen, rim, bezier(p0, p1, p2, 6), 3 * s, taper=(3.2 * s, 1.0 * s))

    def _draw_crow_feet(self, screen, tops, bots, inner, a, color):
        s = self.s
        j = 0 if inner > 0 else len(tops) - 1
        x = tops[j][0]
        y = (tops[j][1] + bots[j][1]) / 2
        out = -inner
        for k, ang_deg in enumerate((-34, -5, 24)):
            ang = math.radians(ang_deg)
            r0 = a * 0.1
            ln = a * (0.22 if k == 1 else 0.18)
            sx, sy = x + out * r0 * math.cos(ang), y + r0 * math.sin(ang)
            ex, ey = x + out * (r0 + ln) * math.cos(ang), y + (r0 + ln) * math.sin(ang)
            cx, cy = (sx + ex) / 2 - out * 3 * s, (sy + ey) / 2 + 2 * s
            stroke(screen, color, bezier((sx, sy), (cx, cy), (ex, ey), 6), 3.6 * s, taper=(4.2 * s, 1.4 * s))

    def _draw_brow(self, screen, cx, cy, a, b, inner, side, p, color):
        s, B = self.s, self.B
        base = cy - B * 1.22 - (b - B) * 0.55 - p.brow_y * 0.42 * B
        base -= p.brow_asym * side * 0.18 * B
        xi = cx + inner * a * (0.8 - 0.16 * p.brow_in)
        xo = cx - inner * a * 0.88
        yi = base - p.brow_angle * 0.3 * B + p.brow_in * 0.08 * B
        yo = base + p.brow_angle * 0.08 * B + 0.04 * B
        ctrl = ((xi + xo) / 2, (yi + yo) / 2 - p.brow_curve * 0.22 * B - 0.03 * B)
        top_limit = 12 * s  # брови не должны уходить за верхний край экрана
        pts = [(x, max(top_limit, y)) for x, y in bezier((xi, yi), ctrl, (xo, yo), 18)]
        stroke(screen, color, pts, 12 * s, taper=(14 * s, 6.5 * s))

    def _draw_blush(self, screen, center, rx, ry, amount):
        pink = (255, 110, 150)
        for k in range(4, 0, -1):
            f = k / 4
            aa_ellipse(screen, mix(self.bg, pink, amount * (1.05 - f) * 0.95), center, rx * f, ry * f)
        s = self.s
        for k in (-1, 0, 1):
            x = center[0] + k * rx * 0.38
            y = center[1]
            stroke(screen, mix(self.bg, pink, amount * 0.9), [(x + 5 * s, y - 6 * s), (x - 5 * s, y + 6 * s)], 2.4 * s)

    def _draw_mouth(self, screen, eyes, p, st):
        s = self.s
        ec = self.eye_color
        mx = self.W / 2 + st.jitter[0]
        my = (eyes[0][1] + eyes[1][1]) / 2 + self.B * 1.48
        speak = clamp(st.speech)
        opn = clamp(p.mouth_open + speak * 0.75 + st.yawn * 0.9)
        mw = 72 * s * p.mouth_w * (1 - 0.18 * speak) * (1 - 0.35 * st.yawn)
        curve = p.mouth_curve
        ly = my - curve * 0.32 * mw + p.mouth_asym * 0.1 * mw
        ry = my - curve * 0.32 * mw - p.mouth_asym * 0.38 * mw
        cyy = my + curve * 0.42 * mw
        left, right = (mx - mw, ly), (mx + mw, ry)
        upper = bezier(left, (mx, cyy - opn * 0.35 * mw), right, 22)
        lower = bezier(left, (mx, cyy + opn * 1.45 * mw), right, 22)
        if p.mouth_w < 0.7 and opn > 0.3:  # «О» — округлый рот (удивление)
            k = clamp((0.7 - p.mouth_w) / 0.2) * clamp((opn - 0.3) / 0.3)
            ry_o = opn * mw * 0.8
            ccy = (cyy - opn * 0.17 * mw + cyy + opn * 0.72 * mw) / 2
            n = len(upper) - 1
            ell_u = [(mx - mw * math.cos(math.pi * i / n), ccy - ry_o * math.sin(math.pi * i / n)) for i in range(n + 1)]
            ell_l = [(mx - mw * math.cos(math.pi * i / n), ccy + ry_o * math.sin(math.pi * i / n)) for i in range(n + 1)]
            upper = [(x1 + (x2 - x1) * k, y1 + (y2 - y1) * k) for (x1, y1), (x2, y2) in zip(upper, ell_u)]
            lower = [(x1 + (x2 - x1) * k, y1 + (y2 - y1) * k) for (x1, y1), (x2, y2) in zip(lower, ell_l)]
        if p.tremble > 0.15:  # дрожащие губы
            wob = lambda pts: [(x, y + math.sin((x - mx) / mw * math.pi * 3 + st.t * 9) * p.tremble * 3.5 * s)
                               for x, y in pts]
            upper, lower = wob(upper), wob(lower)
        col = mix(self.bg, ec, 0.95)
        if opn > 0.04:
            poly = upper + lower[::-1]
            aa_polygon(screen, (70, 18, 34), poly)
            top_mid, bot_mid = upper[len(upper) // 2], lower[len(lower) // 2]
            depth = bot_mid[1] - top_mid[1]
            if opn > 0.3 and depth > 8 * s:  # язычок внутри рта
                tongue_c = (mx, top_mid[1] + depth * 0.7)
                aa_ellipse(screen, (190, 70, 95), tongue_c, mw * 0.27, depth * 0.18)
                aa_polygon(screen, (70, 18, 34), upper + [(x, y + 2 * s) for x, y in upper[::-1]])
            stroke(screen, col, upper, 4.5 * s)
            stroke(screen, col, lower, 4 * s)
        else:
            stroke(screen, col, upper, 5.5 * s, taper=(4 * s, 4 * s))

    # ------------------------------------------------------------ эффекты --
    def update_effects(self, screen, p, st, eyes):
        s = self.s
        ec = self.eye_color
        (lcx, lcy, la, lb), (rcx, rcy, ra, rb) = eyes
        if p.anger_mark > 0.05:
            c = (rcx + ra * 0.92, rcy - rb * 1.55)
            sz = 20 * s * (1 + 0.14 * math.sin(st.t * 11)) * p.anger_mark
            red = mix(self.bg, (255, 45, 45), min(1.0, p.anger_mark * 1.3))
            for qx, qy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                p0 = (c[0] + qx * sz * 0.35, c[1] + qy * sz * 1.05)
                p1 = (c[0] + qx * sz * 0.35, c[1] + qy * sz * 0.35)
                p2 = (c[0] + qx * sz * 1.05, c[1] + qy * sz * 0.35)
                stroke(screen, red, bezier(p0, p1, p2, 8), 5 * s)
        if p.sweat > 0.1:
            k = (st.t * 0.35) % 1.0
            x = lcx - la * 1.05
            y = lcy - lb * 0.9 + k * lb * 0.8
            col = mix(self.bg, (140, 205, 255), p.sweat * (1 - k * 0.6))
            aa_polygon(screen, col, drop_points(x, y, 9 * s))
            aa_circle(screen, mix(col, WHITE, 0.6), (x - 3 * s, y - 2 * s), 2.2 * s)
        if p.dots > 0.05:
            for k in range(3):
                ph = (st.t * 2.2 - k * 0.35) % 2.0
                alpha = p.dots * (0.35 + 0.65 * clamp(1 - abs(ph - 0.5) * 1.4))
                aa_circle(screen, mix(self.bg, ec, alpha),
                          (rcx + ra * (0.85 + 0.32 * k), rcy - rb * (1.3 + 0.28 * k)), (5 + 3 * k) * s)
        if p.ring > 0.05:
            n = 7
            for k in range(n):
                lvl = clamp(st.mic * 1.6)
                h = (7 + 26 * lvl * (0.55 + 0.45 * math.sin(st.t * 9 + k * 1.3))) * s * p.ring
                x = self.W / 2 + (k - (n - 1) / 2) * 16 * s
                y = self.H - 24 * s
                stroke(screen, mix(self.bg, ec, 0.4 + 0.6 * p.ring), [(x, y - h / 2), (x, y + h / 2)], 7 * s)

    def _draw_particles(self, screen, rim):
        for pt in self.particles:
            f = 1 - pt.age / pt.life
            if pt.kind == "heart":
                col = mix(self.bg, (255, 80, 130), min(1.0, f * 1.6))
                aa_polygon(screen, col, heart_points(pt.x, pt.y, pt.size * (0.7 + 0.3 * f)))
            elif pt.kind == "star":
                k = math.sin(math.pi * pt.age / pt.life)
                aa_polygon(screen, mix(self.bg, WHITE, k), star_points(pt.x, pt.y, pt.size * k, 0.22, 4, pt.rot))
            elif pt.kind == "tear":
                col = mix(self.bg, (130, 195, 255), min(1.0, f * 1.4))
                aa_polygon(screen, col, drop_points(pt.x, pt.y, pt.size))
            elif pt.kind == "z":
                self._draw_text(screen, "Z", (pt.x, pt.y), int(pt.size), mix(self.bg, rim, min(1.0, f * 1.5)))

    def _draw_vignette(self, screen, strength):
        if self._vignette is None:
            try:
                import numpy as np
                w, h = self.W, self.H
                yy, xx = np.mgrid[0:h, 0:w]
                dx = (xx - w / 2) / (w / 2)
                dy = (yy - h / 2) / (h / 2)
                d = np.sqrt(dx * dx * 0.8 + dy * dy * 1.1)
                alpha = np.clip((d - 0.55) / 0.75, 0, 1) ** 1.6 * 255
                v = pygame.Surface((w, h), pygame.SRCALPHA)
                v.fill((255, 25, 10, 0))
                pygame.surfarray.pixels_alpha(v)[:] = alpha.T.astype("uint8")
                self._vignette = v
            except Exception:
                self._vignette = False
        if self._vignette:
            self._vignette.set_alpha(int(clamp(strength) * 255))
            screen.blit(self._vignette, (0, 0))

    def _draw_text(self, screen, text, center, size, color):
        size = max(8, int(size * self.s)) if size < 60 else int(size)
        font = self._font_cache.get(size)
        if font is None:
            if not pygame.font.get_init():
                pygame.font.init()
            font = pygame.font.Font(None, size)
            self._font_cache[size] = font
        img = font.render(text, True, color)
        r = img.get_rect(center=(int(center[0]), int(center[1])))
        screen.blit(img, r)
