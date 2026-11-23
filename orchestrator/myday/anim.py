"""The two streak animations, drawn frame by frame with Pillow (no assets, no model).

``clear``: a gold ring closes around an ember, a flash ignites a layered, flickering flame with a
glow, confetti bursts out under gravity with spin, sparkles twinkle, and the streak number counts
up with a pop under an "ALL CLEAR" pill.

``broken``: the flame burns over the old streak, frost creeps in from the corners, the flame
gutters, turns blue and dies into smoke and falling embers, the number cracks and its halves fall
away, and a calm "0" rises with "Tomorrow is a fresh start".

Shapes are drawn at ``SS``× the output size and scaled down (smooth edges); glows are blurred at
low resolution and scaled up (cheap). Deterministic: the same streak gives the same frames.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

OUT = 540  # output is OUT × OUT
SS = 2  # supersampling factor
W = OUT * SS
FPS = 25
FRAMES = 70  # 2.8 s
FONT_NAMES = ("Inter-ExtraBold.otf", "Inter-Bold.otf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")
TEXT_NAMES = ("Inter-SemiBold.otf", "Inter-Medium.otf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf")

GOLD = (255, 200, 60)
CONFETTI = [(255, 214, 10), (48, 209, 88), (10, 132, 255), (255, 55, 95), (191, 90, 242), (255, 159, 10),
            (100, 210, 255)]
FIRE = [(255, 59, 48), (255, 120, 20), (255, 190, 40), (255, 244, 200)]  # outer → core
ICE = [(40, 90, 170), (70, 140, 220), (140, 200, 255), (225, 245, 255)]


# ---- helpers ------------------------------------------------------------------------------------


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def phase(t: float, start: float, end: float) -> float:
    """0 before ``start``, 1 after ``end``, linear between."""
    return clamp((t - start) / (end - start))


def ease_out(x: float) -> float:
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    return 3 * x * x - 2 * x * x * x


def ease_back(x: float) -> float:
    c = 1.70158
    return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2


def mix(a: tuple[int, ...], b: tuple[int, ...], k: float) -> tuple[int, ...]:
    return tuple(round(x + (y - x) * k) for x, y in zip(a, b, strict=True))


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in FONT_NAMES if bold else TEXT_NAMES:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def background(inner: tuple[int, int, int], outer: tuple[int, int, int]) -> Image.Image:
    """A radial gradient, centre slightly above the middle."""
    mask = Image.radial_gradient("L").resize((W * 3 // 2, W * 3 // 2))
    mask = mask.crop((W // 4, W // 5, W // 4 + W, W // 5 + W))
    return Image.composite(Image.new("RGB", (W, W), outer), Image.new("RGB", (W, W), inner), mask)


def glow(layer: Image.Image, radius: int, strength: float) -> Image.Image:
    """A soft halo of ``layer`` (RGBA), blurred at quarter size for speed."""
    small = layer.resize((W // 4, W // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius / 4))
    halo = small.resize((W, W), Image.BILINEAR)
    alpha = halo.getchannel("A").point(lambda v: min(255, int(v * strength)))
    halo.putalpha(alpha)
    return halo


def text_center(draw: ImageDraw.ImageDraw, cx: float, cy: float, text: str, fnt, fill, shadow: bool = True) -> None:
    box = draw.textbbox((0, 0), text, font=fnt)
    x, y = cx - (box[0] + box[2]) / 2, cy - (box[1] + box[3]) / 2
    if shadow:
        draw.text((x, y + 4 * SS), text, font=fnt, fill=(0, 0, 0, 120))
    draw.text((x, y), text, font=fnt, fill=fill)


def scaled_text(text: str, fnt, fill, scale: float, alpha: float = 1.0, angle: float = 0.0) -> Image.Image:
    """Text on its own transparent tile, scaled (pop) and rotated about its centre."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    box = probe.textbbox((0, 0), text, font=fnt)
    tw, th = box[2] - box[0] + 40 * SS, box[3] - box[1] + 40 * SS
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.text((20 * SS - box[0], 24 * SS - box[1]), text, font=fnt, fill=(0, 0, 0, 110))
    d.text((20 * SS - box[0], 20 * SS - box[1]), text, font=fnt, fill=fill)
    if scale != 1:
        tile = tile.resize((max(1, int(tw * scale)), max(1, int(th * scale))), Image.BICUBIC)
    if angle:
        tile = tile.rotate(angle, resample=Image.BICUBIC, expand=True)
    if alpha < 1:
        tile.putalpha(tile.getchannel("A").point(lambda v: int(v * alpha)))
    return tile


def paste_center(base: Image.Image, tile: Image.Image, cx: float, cy: float) -> None:
    base.alpha_composite(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))


# ---- the flame ----------------------------------------------------------------------------------


def flame_points(cx: float, base: float, height: float, width: float, t: float, seed: float) -> list[tuple]:
    """A teardrop (tip up) whose sides ripple more toward the tip, like a real flame."""
    pts = []
    sway = math.sin(t * 7.1 + seed) * 0.08 + math.sin(t * 13.3 + seed * 2) * 0.04
    for i in range(72):
        a = 2 * math.pi * i / 72
        k = (1 - math.cos(a)) / 2  # 0 at the tip, 1 at the bottom
        x = width / 2 * math.sin(a) * math.sin(a / 2) ** 1.4
        lift = 1 - k  # 1 at the tip
        x += width * 0.06 * math.sin(lift * 9 + t * 17 + seed) * lift
        x += sway * width * lift ** 2 * 2.2
        y = base - height * (math.cos(a) + 1) / 2
        pts.append((cx + x, y))
    return pts


def draw_flame(canvas: Image.Image, cx: float, base: float, height: float, t: float, colours, alpha: float = 1.0,
               halo: float = 1.0) -> None:
    if height <= 2:
        return
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    flicker = 1 + 0.05 * math.sin(t * 23) + 0.03 * math.sin(t * 37 + 1)
    for i, colour in enumerate(colours):
        k = 1 - i * 0.22
        h, w = height * k * flicker, height * 0.62 * k
        d.polygon(flame_points(cx, base - i * height * 0.025, h, w, t, i * 1.7), fill=(*colour, 255))
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    if halo:
        canvas.alpha_composite(glow(layer, 60 * SS, 0.9 * halo))
    canvas.alpha_composite(layer)


# ---- particles ----------------------------------------------------------------------------------


@dataclass
class Bit:
    x: float
    y: float
    vx: float
    vy: float
    size: float
    colour: tuple[int, int, int]
    spin: float
    turn: float
    shape: int  # 0 ribbon, 1 dot, 2 square


def burst(rng: random.Random, cx: float, cy: float, count: int) -> list[Bit]:
    bits = []
    for _ in range(count):
        a = rng.uniform(0, 2 * math.pi)
        speed = rng.uniform(14, 34) * SS
        bits.append(Bit(cx, cy, math.cos(a) * speed, math.sin(a) * speed - 10 * SS, rng.uniform(7, 13) * SS,
                        rng.choice(CONFETTI), rng.uniform(0, math.pi), rng.uniform(-0.35, 0.35), rng.choice((0, 0, 1, 2))))
    return bits


def step_confetti(bits: list[Bit]) -> None:
    for b in bits:
        b.vx *= 0.93
        b.vy = b.vy * 0.93 + 1.1 * SS
        b.x += b.vx
        b.y += b.vy
        b.spin += b.turn


def draw_confetti(d: ImageDraw.ImageDraw, bits: list[Bit], alpha: float) -> None:
    for b in bits:
        flip = abs(math.cos(b.spin * 1.7))  # tumbling: the piece narrows as it turns edge-on
        colour = (*mix(b.colour, (255, 255, 255), (1 - flip) * 0.25), int(255 * alpha))
        if b.shape == 1:
            r = b.size * 0.4
            d.ellipse((b.x - r, b.y - r * flip, b.x + r, b.y + r * flip), fill=colour)
            continue
        hw, hh = (b.size * 0.35, b.size) if b.shape == 0 else (b.size * 0.5, b.size * 0.5)
        hh *= max(0.15, flip)
        c, s = math.cos(b.spin), math.sin(b.spin)
        corners = [(b.x + px * c - py * s, b.y + px * s + py * c) for px, py in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
        d.polygon(corners, fill=colour)


def sparkle(d: ImageDraw.ImageDraw, x: float, y: float, r: float, alpha: float) -> None:
    if r <= 0 or alpha <= 0:
        return
    fill = (255, 250, 220, int(255 * alpha))
    t = r * 0.18
    d.polygon([(x, y - r), (x + t, y - t), (x + r, y), (x + t, y + t), (x, y + r), (x - t, y + t), (x - r, y),
               (x - t, y - t)], fill=fill)


def rays(t: float, colour: tuple[int, int, int], alpha: float) -> Image.Image:
    layer = Image.new("RGBA", (W // 4, W // 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = W // 8
    for i in range(12):
        a = t * 0.6 + i * math.pi / 6
        d.polygon([(c, c), (c + math.cos(a - 0.09) * W, c + math.sin(a - 0.09) * W),
                   (c + math.cos(a + 0.09) * W, c + math.sin(a + 0.09) * W)], fill=(*colour, int(40 * alpha)))
    return layer.filter(ImageFilter.GaussianBlur(6)).resize((W, W), Image.BILINEAR)


# ---- clear ----------------------------------------------------------------------------------------


def clear_frames(streak: int) -> list[Image.Image]:
    rng = random.Random(streak)
    cx, base = W / 2, W * 0.50
    big, label, pill_font = font(120 * SS), font(22 * SS, bold=False), font(26 * SS)
    bits: list[Bit] = []
    sparks = [(rng.uniform(0.1, 0.9) * W, rng.uniform(0.08, 0.6) * W, rng.uniform(8, 18) * SS, rng.uniform(0, 6))
              for _ in range(16)]
    bg = background((52, 28, 92), (10, 8, 22))
    frames = []
    for f in range(FRAMES):
        t = f / FPS
        p = f / (FRAMES - 1)
        canvas = bg.convert("RGBA")
        ignite = phase(p, 0.22, 0.42)
        if ignite:
            canvas.alpha_composite(rays(t, GOLD, ignite))
        d = ImageDraw.Draw(canvas)
        # the ring closing around the ember
        ring = ease_in_out(phase(p, 0.02, 0.24))
        fade_ring = 1 - phase(p, 0.26, 0.36)
        if ring and fade_ring:
            r = W * 0.2 * (1 + 0.6 * phase(p, 0.24, 0.45))
            box = (cx - r, base - W * 0.12 - r, cx + r, base - W * 0.12 + r)
            ring_layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
            ImageDraw.Draw(ring_layer).arc(box, -90, -90 + 360 * ring, fill=(*GOLD, int(255 * fade_ring)),
                                           width=int(7 * SS))
            canvas.alpha_composite(glow(ring_layer, 30 * SS, 1.2))
            canvas.alpha_composite(ring_layer)
        # the flame: an ember first, then it ignites with a little overshoot
        height = W * (0.06 + 0.30 * ease_back(ignite)) if ignite else W * 0.06 * (0.8 + 0.2 * math.sin(t * 9))
        draw_flame(canvas, cx, base, height, t, FIRE, halo=0.6 + 0.6 * ignite)
        # flash at ignition
        flash = phase(p, 0.22, 0.25) * (1 - phase(p, 0.25, 0.34))
        if flash:
            canvas.alpha_composite(glow(Image.new("RGBA", (W, W), (255, 210, 120, int(255 * flash))), 10, 0.35))
        # confetti
        if f == int(0.26 * (FRAMES - 1)):
            bits = burst(rng, cx, base - W * 0.15, 140)
        if bits:
            step_confetti(bits)
            draw_confetti(ImageDraw.Draw(canvas), bits, 1 - phase(p, 0.85, 1.0))
        d = ImageDraw.Draw(canvas)
        for x, y, r, off in sparks:
            twinkle = max(0.0, math.sin(t * 6 + off))
            sparkle(d, x, y, r * twinkle * phase(p, 0.3, 0.45), twinkle)
        # the number: counts up with a pop
        shown = streak if p >= 0.5 else max(streak - 1, 0)
        pop = 1.0 + 0.35 * math.sin(math.pi * phase(p, 0.5, 0.62))
        enter = ease_out(phase(p, 0.30, 0.42))
        if enter:
            paste_center(canvas, scaled_text(str(shown), big, (255, 255, 255, 255), pop, enter),
                         cx, W * 0.65 + (1 - enter) * 30 * SS)
            text_center(ImageDraw.Draw(canvas), cx, W * 0.795, "DAY STREAK", label, (255, 220, 150, int(230 * enter)))
        # the pill
        rising = phase(p, 0.58, 0.72)
        rise = ease_back(rising)
        if rising > 0:
            y = W * 0.905 + (1 - rise) * 40 * SS
            pw, ph = 250 * SS, 54 * SS
            pill = Image.new("RGBA", (W, W), (0, 0, 0, 0))
            pd = ImageDraw.Draw(pill)
            pd.rounded_rectangle((cx - pw / 2, y - ph / 2, cx + pw / 2, y + ph / 2), radius=ph / 2,
                                 fill=(*GOLD, int(255 * min(1, rise))))
            canvas.alpha_composite(glow(pill, 24 * SS, 0.8))
            canvas.alpha_composite(pill)
            text_center(ImageDraw.Draw(canvas), cx, y, "ALL CLEAR", pill_font, (40, 20, 0, 255), shadow=False)
        frames.append(canvas.convert("RGB").resize((OUT, OUT), Image.LANCZOS))
    return frames


# ---- broken ---------------------------------------------------------------------------------------


def frost(t: float, rng_seed: int) -> Image.Image:
    """Ice crystals growing in from the four corners; ``t`` 0→1 is how far."""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    if t <= 0:
        return layer
    d = ImageDraw.Draw(layer)
    rng = random.Random(rng_seed)
    corners = [(0, 0, 1, 1), (W, 0, -1, 1), (0, W, 1, -1), (W, W, -1, -1)]
    for x0, y0, sx, sy in corners:
        for _ in range(6):
            a = rng.uniform(0.2, 1.37)
            length = rng.uniform(0.12, 0.26) * W * t
            x1, y1 = x0 + sx * math.cos(a) * length, y0 + sy * math.sin(a) * length
            d.line((x0, y0, x1, y1), fill=(220, 240, 255, 95), width=int(1.5 * SS))
            for j in range(1, 4):
                k = j / 5
                bx, by = x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
                twig = length * 0.18 * (1 - k)
                for side in (-0.6, 0.6):
                    b = a + side
                    d.line((bx, by, bx + sx * math.cos(b) * twig, by + sy * math.sin(b) * twig),
                           fill=(220, 240, 255, 70), width=SS)
    return Image.alpha_composite(glow(layer, 20 * SS, 0.6), layer)


def broken_frames(streak: int) -> list[Image.Image]:
    rng = random.Random(1000 + streak)
    cx, base = W / 2, W * 0.50
    big, small, label = font(120 * SS), font(30 * SS), font(22 * SS, bold=False)
    warm, cold = background((60, 30, 40), (14, 10, 16)), background((26, 52, 84), (6, 12, 24))
    embers = [[cx + rng.uniform(-40, 40) * SS, base - rng.uniform(20, 120) * SS, rng.uniform(-3, 3) * SS,
               rng.uniform(-6, -1) * SS, rng.uniform(3, 6) * SS] for _ in range(36)]
    smoke = [(rng.uniform(-24, 24) * SS, rng.uniform(0, 0.6), rng.uniform(14, 30) * SS, rng.uniform(-1.4, 1.4))
             for _ in range(22)]
    crack = [(cx - 36 * SS + i * 7.2 * SS, W * 0.64 + (7 if i % 2 else -7) * SS + rng.uniform(-3, 3) * SS)
             for i in range(11)]
    frames = []
    for f in range(FRAMES):
        t = f / FPS
        p = f / (FRAMES - 1)
        chill = ease_in_out(phase(p, 0.15, 0.55))
        canvas = Image.blend(warm, cold, chill).convert("RGBA")
        canvas.alpha_composite(frost(ease_out(phase(p, 0.15, 0.6)), streak))
        # the flame gutters, turns blue and dies
        dying = phase(p, 0.25, 0.55)
        gutter = 1 + 0.25 * math.sin(t * 31) * dying
        colours = [mix(a, b, chill) for a, b in zip(FIRE, ICE, strict=True)]
        height = W * 0.36 * (1 - ease_in_out(dying)) * gutter
        draw_flame(canvas, cx, base, height, t, colours, alpha=1 - phase(p, 0.48, 0.56), halo=1 - dying)
        d = ImageDraw.Draw(canvas)
        # embers fall and cool once it dies
        if p > 0.5:
            for e in embers:
                e[3] += 0.9 * SS
                e[0] += e[2]
                e[1] += e[3] * 0.6
                cool = phase(p, 0.5, 0.85)
                colour = mix((255, 150, 40), (120, 130, 140), cool)
                r = e[4] * (1 - 0.5 * cool)
                d.ellipse((e[0] - r, e[1] - r, e[0] + r, e[1] + r), fill=(*colour, int(255 * (1 - phase(p, 0.8, 1)))))
        # smoke rises
        puff_layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
        pd = ImageDraw.Draw(puff_layer)
        for dx, off, r, drift in smoke:
            age = phase(p, 0.48 + off * 0.3, 0.95)
            if not age:
                continue
            y = base - W * 0.05 - age * W * 0.35
            rr = r * (0.6 + age * 1.4)
            x = cx + dx + drift * age * 90 * SS + math.sin(age * 9 + drift * 3) * 10 * SS
            pd.ellipse((x - rr, y - rr, x + rr, y + rr), fill=(190, 205, 220, int(80 * (1 - age) * min(1, age * 5))))
        canvas.alpha_composite(puff_layer.resize((W // 4, W // 4)).filter(ImageFilter.GaussianBlur(5)).resize((W, W)))
        # the old number cracks and falls apart
        number = str(streak)
        split = ease_in_out(phase(p, 0.52, 0.8))
        if split < 1:
            tile = scaled_text(number, big, (255, 255, 255, 255), 1.0)
            if split:
                top = Image.new("RGBA", tile.size, (0, 0, 0, 0))
                mask = Image.new("L", tile.size, 0)
                ImageDraw.Draw(mask).polygon([(0, 0), (tile.width, 0), (tile.width, tile.height * 0.5),
                                              (0, tile.height * 0.58)], fill=255)
                top.paste(tile, (0, 0), mask)
                bottom = tile.copy()
                bottom.putalpha(ImageChops.subtract(bottom.getchannel("A"), mask))
                fade = 1 - phase(split, 0.0, 0.7)
                for half, sign in ((top, -1), (bottom, 1)):
                    moved = half.rotate(sign * 14 * split, resample=Image.BICUBIC, expand=True)
                    moved.putalpha(moved.getchannel("A").point(lambda v, a=fade: int(v * a)))
                    paste_center(canvas, moved, cx + sign * 50 * SS * split,
                                 W * 0.645 - 30 * SS * split + (180 if sign > 0 else 140) * SS * split * split)
            else:
                paste_center(canvas, tile, cx, W * 0.645)
                cracking = phase(p, 0.40, 0.52)
                if cracking:
                    n = max(2, int(len(crack) * cracking))
                    ImageDraw.Draw(canvas).line(crack[:n], fill=(200, 235, 255, 255), width=int(4 * SS), joint="curve")
        # a calm zero rises
        calm = ease_out(phase(p, 0.74, 0.9))
        if calm:
            paste_center(canvas, scaled_text("0", big, (190, 225, 255, 255), 0.8 + 0.2 * calm, calm),
                         cx, W * 0.645 + (1 - calm) * 40 * SS)
        words = ease_out(phase(p, 0.45, 0.6))
        if words:
            text_center(ImageDraw.Draw(canvas), cx, W * 0.815, "STREAK RESET", small, (160, 215, 255, int(255 * words)))
        hope = ease_out(phase(p, 0.82, 0.95))
        if hope:
            text_center(ImageDraw.Draw(canvas), cx, W * 0.885, "Tomorrow is a fresh start", label,
                        (230, 240, 250, int(230 * hope)))
        frames.append(canvas.convert("RGB").resize((OUT, OUT), Image.LANCZOS))
    return frames
