#!/usr/bin/env python3
"""imgrender.py - template-driven image renderer (PIL). No LLM at render time.

Claude (or you) writes a TEMPLATE once (JSON). A script then renders one image per data row, every day,
with no model calls. Replaces "the bot regenerates a PIL script every run".

  imgrender.py render  TEMPLATE.json --data rows.csv|rows.json --out DIR [--only N] [--fail-fast]
  imgrender.py render  TEMPLATE.json --set title="Hello" --set price=99 --out DIR     (one image)
  imgrender.py check   TEMPLATE.json [--data rows...]    validate and test-render every row in memory, save nothing
  imgrender.py fonts                                      list font names usable in templates

TEMPLATE (JSON):
{
  "size": [1080, 1080],                    # pixels
  "background": "#101820"                  # colour, or {"gradient": ["#101820", "#2a3b4c"], "angle": 90}
                or {"image": "bg.png", "fit": "cover"},
  "output": "{id}.png",                    # file name pattern; {field} filled from the row
  "layers": [
    {"type": "rect",  "box": [0,0,1080,160], "fill": "#ffcc00", "radius": 0, "opacity": 1.0},
    {"type": "text",  "text": "{title}", "box": [60,40,960,120], "font": "DejaVu Sans Bold", "size": 64,
     "min_size": 28, "color": "#ffffff", "align": "left|center|right", "valign": "top|middle|bottom",
     "max_lines": 3, "line_spacing": 1.1, "stroke": 0, "stroke_color": "#000000", "upper": false},
    {"type": "image", "path": "{logo}", "box": [60,900,200,120], "fit": "contain|cover|stretch",
     "opacity": 1.0, "optional": true}      # optional: skip if file missing or field empty
  ]
}
Text auto-shrinks from "size" down to "min_size" until it fits the box in "max_lines"; if it still does
not fit it is reported as a QC warning (never silently cut). Relative paths resolve next to the template.
Exit codes: 0 all ok, 1 some rows failed or had QC warnings, 2 bad template/usage.
Needs Pillow only.
"""
import argparse, csv, json, os, re, sys, glob
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageColor

FONT_DIRS = ["/usr/share/fonts", os.path.expanduser("~/.fonts"), os.path.expanduser("~/.local/share/fonts"),
             "/Library/Fonts", "/System/Library/Fonts", "C:/Windows/Fonts"]

def font_index():
    idx = {}
    for d in FONT_DIRS:
        for p in glob.glob(os.path.join(d, "**", "*"), recursive=True):
            if p.lower().endswith((".ttf", ".otf", ".ttc")):
                try:
                    f = ImageFont.truetype(p, 20)
                    fam, sty = f.getname()
                    idx.setdefault(f"{fam} {sty}".strip().lower(), p)
                    idx.setdefault(fam.lower() if sty.lower() in ("regular", "book", "roman") else f"{fam} {sty}".lower(), p)
                    idx.setdefault(Path(p).stem.lower(), p)
                except Exception:
                    pass
    return idx

_FONTS = None
def find_font(name, base):
    global _FONTS
    if not name:
        name = "DejaVu Sans"
    cand = (base / name)
    if cand.exists():
        return str(cand)
    if os.path.exists(name):
        return name
    if _FONTS is None:
        _FONTS = font_index()
    k = name.lower()
    if k in _FONTS:
        return _FONTS[k]
    hits = [v for kk, v in _FONTS.items() if k in kk]
    if hits:
        return min(hits, key=len)
    raise ValueError(f"font not found: {name!r} (run: imgrender.py fonts)")

class Missing(KeyError): pass

def fill(s, row):
    if not isinstance(s, str):
        return s
    def sub(m):
        k = m.group(1)
        if k not in row:
            raise Missing(k)
        return str(row[k])
    return re.sub(r"\{(\w+)\}", sub, s)

def color(c, opacity=1.0):
    r, g, b, a = ImageColor.getcolor(c, "RGBA")
    return (r, g, b, int(a * opacity))

def fit_image(im, w, h, mode):
    if mode == "stretch":
        return im.resize((w, h), Image.LANCZOS)
    sw, sh = im.size
    k = max(w / sw, h / sh) if mode == "cover" else min(w / sw, h / sh)
    nw, nh = max(1, round(sw * k)), max(1, round(sh * k))
    r = im.resize((nw, nh), Image.LANCZOS)
    if mode == "cover":
        x, y = (nw - w) // 2, (nh - h) // 2
        return r.crop((x, y, x + w, y + h))
    return r

def wrap(draw, text, font, width, stroke):
    lines = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            t = (cur + " " + word).strip()
            if draw.textlength(t, font=font) <= width or not cur:
                cur = t
            else:
                lines.append(cur); cur = word
        lines.append(cur)
    return lines

def draw_text(img, layer, row, base, warns):
    text = fill(layer["text"], row)
    if layer.get("upper"):
        text = text.upper()
    x, y, w, h = layer["box"]
    path = find_font(layer.get("font"), base)
    size = int(layer.get("size", 48)); lo = int(layer.get("min_size", max(10, size // 2)))
    max_lines = int(layer.get("max_lines", 99)); ls = float(layer.get("line_spacing", 1.15))
    stroke = int(layer.get("stroke", 0))
    d = ImageDraw.Draw(img)
    while True:
        font = ImageFont.truetype(path, size)
        lines = wrap(d, text, font, w, stroke)
        lh = round(size * ls)
        total = lh * (len(lines) - 1) + size
        widest = max((d.textlength(l, font=font) for l in lines), default=0)
        ok = len(lines) <= max_lines and total <= h and widest <= w + 0.5
        if ok or size <= lo:
            break
        size -= 2
    if not ok:
        warns.append(f"text does not fit box at min_size {lo}: {text[:40]!r}")
    va = layer.get("valign", "top")
    y0 = y + (0 if va == "top" else (h - total) // 2 if va == "middle" else h - total)
    layer_im = Image.new("RGBA", img.size, (0, 0, 0, 0)); ld = ImageDraw.Draw(layer_im)
    col = color(layer.get("color", "#ffffff"), float(layer.get("opacity", 1.0)))
    sc = color(layer.get("stroke_color", "#000000"))
    for i, line in enumerate(lines):
        lw = ld.textlength(line, font=font)
        al = layer.get("align", "left")
        xx = x if al == "left" else x + (w - lw) / 2 if al == "center" else x + w - lw
        ld.text((xx, y0 + i * lh), line, font=font, fill=col, stroke_width=stroke, stroke_fill=sc)
    img.alpha_composite(layer_im)

def background(spec, size, base):
    W, H = size
    if isinstance(spec, str):
        return Image.new("RGBA", size, color(spec))
    if "gradient" in spec:
        c0, c1 = (ImageColor.getrgb(c) for c in spec["gradient"][:2])
        ang = spec.get("angle", 90)
        g = Image.linear_gradient("L")  # 256x256 black->white, top->bottom
        g = g.rotate(ang - 90, expand=False, resample=Image.BICUBIC).resize(size)
        return Image.composite(Image.new("RGB", size, c1), Image.new("RGB", size, c0), g).convert("RGBA")
    if "image" in spec:
        im = Image.open(base / spec["image"]).convert("RGBA")
        return fit_image(im, W, H, spec.get("fit", "cover"))
    raise ValueError("bad background")

def render_one(tpl, row, base):
    warns = []
    W, H = tpl["size"]
    img = background(tpl.get("background", "#000000"), (W, H), base)
    for i, layer in enumerate(tpl["layers"]):
        t = layer.get("type")
        try:
            if t == "rect":
                x, y, w, h = layer["box"]
                ov = Image.new("RGBA", img.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
                od.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=int(layer.get("radius", 0)),
                                     fill=color(layer.get("fill", "#000000"), float(layer.get("opacity", 1.0))))
                img.alpha_composite(ov)
            elif t == "text":
                draw_text(img, layer, row, base, warns)
            elif t == "image":
                try:
                    p = fill(layer["path"], row)
                except Missing:
                    if layer.get("optional"): continue
                    raise
                pp = Path(p) if os.path.isabs(p) else base / p
                if not p or not pp.exists():
                    if layer.get("optional"): continue
                    raise FileNotFoundError(str(pp))
                x, y, w, h = layer["box"]
                im = fit_image(Image.open(pp).convert("RGBA"), w, h, layer.get("fit", "contain"))
                if layer.get("opacity", 1.0) < 1:
                    a = im.getchannel("A").point(lambda v: int(v * layer["opacity"])); im.putalpha(a)
                img.alpha_composite(im, (x + (w - im.size[0]) // 2, y + (h - im.size[1]) // 2) if layer.get("fit", "contain") == "contain" else (x, y))
            else:
                raise ValueError(f"unknown layer type {t!r}")
        except Missing as e:
            raise ValueError(f"layer {i} ({t}): data field {e.args[0]!r} missing") from None
    return img.convert("RGB"), warns

def load_rows(path):
    p = Path(path)
    if p.suffix.lower() == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, list) else d.get("rows", [d])
    with open(p, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def validate(tpl):
    errs = []
    if not (isinstance(tpl.get("size"), list) and len(tpl["size"]) == 2 and all(isinstance(v, int) and 0 < v <= 8000 for v in tpl["size"])):
        errs.append("size must be [width, height] in 1..8000")
    if not tpl.get("layers"):
        errs.append("no layers")
    for i, l in enumerate(tpl.get("layers", [])):
        if l.get("type") not in ("rect", "text", "image"): errs.append(f"layer {i}: bad type")
        elif "box" not in l or len(l["box"]) != 4: errs.append(f"layer {i}: box must be [x,y,w,h]")
        elif l["type"] == "text" and "text" not in l: errs.append(f"layer {i}: text missing")
        elif l["type"] == "image" and "path" not in l: errs.append(f"layer {i}: path missing")
    return errs

def safe_name(s):
    s = re.sub(r"[^\w.\- ]+", "_", s).strip(" .")
    return s or "image"

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("render", "check"):
        s = sub.add_parser(name); s.add_argument("template"); s.add_argument("--data"); s.add_argument("--set", action="append", default=[])
        if name == "render":
            s.add_argument("--out", required=True); s.add_argument("--only", type=int); s.add_argument("--fail-fast", action="store_true")
    sub.add_parser("fonts")
    a = ap.parse_args(argv)
    if a.cmd == "fonts":
        for k in sorted(font_index()): print(k)
        return 0
    tp = Path(a.template)
    try:
        tpl = json.loads(tp.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"template unreadable: {e}", file=sys.stderr); return 2
    errs = validate(tpl)
    if errs:
        print("template errors:\n  " + "\n  ".join(errs), file=sys.stderr); return 2
    rows = load_rows(a.data) if a.data else [{}]
    if a.set:
        extra = dict(s.split("=", 1) for s in a.set)
        rows = [{**r, **extra} for r in rows]
    if a.cmd == "render" and a.only is not None:
        rows = rows[a.only:a.only + 1]
    base = tp.parent
    out = Path(a.out) if a.cmd == "render" else None
    if out: out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for n, row in enumerate(rows):
        try:
            img, warns = render_one(tpl, row, base)
            name = safe_name(fill(tpl.get("output", "{id}.png"), {"id": n, **row})) if "{" in tpl.get("output", "{id}.png") else tpl.get("output")
            if out:
                img.save(out / name)
            print(f"ok   {n} {name if out else ''}" + (f"  WARN: {'; '.join(warns)}" if warns else ""))
            bad += bool(warns)
        except Exception as e:
            print(f"FAIL {n}: {e}", file=sys.stderr); bad += 1
            if getattr(a, "fail_fast", False): return 1
    print(f"{len(rows)} row(s), {bad} problem(s)")
    return 1 if bad else 0

if __name__ == "__main__":
    sys.exit(main())
