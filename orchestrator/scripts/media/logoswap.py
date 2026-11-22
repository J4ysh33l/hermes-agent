#!/usr/bin/env python3
"""logoswap.py - replace a logo in images and videos from a JSON manifest, then QC every result. No LLM, no detection.

  logoswap.py preview MANIFEST FILE --out preview.png [--grid 100] [--at 1.0]   draw the manifest boxes (and a pixel grid) on a file/frame
  logoswap.py swap    MANIFEST FILE_OR_DIR... --out DIR [--no-qc]               swap + QC; originals are never touched
  logoswap.py qc      MANIFEST FILE_OR_DIR... --out DIR                         QC results already in DIR against the originals

You find the box yourself (or ask Claude to read it off a `preview --grid` picture): there is no auto-detection.

MANIFEST (JSON):
{ "logo": "new_logo.png",                      # PNG with transparency is best; relative to the manifest
  "rules": [                                   # first rule whose glob matches the file name wins
    {"match": "*.png", "box": [40, 30, 220, 90],          # x, y, w, h in pixels of the OLD logo; must lie inside the frame
     "cover": "auto",                          # auto = median colour around the box | "#rrggbb" | blur | none
     "pad_pct": 0, "opacity": 1.0,             # new logo is fitted inside the box (aspect kept), centred
     "min_change": 8},                         # QC: mean pixel change inside the box must be at least this
    {"match": "ad_*.mp4", "box_pct": [0.04, 0.03, 0.2, 0.08],   # same, as fractions of the frame (for mixed sizes)
     "start": 0, "end": 12.5}                  # videos only: show the swap only in this window (seconds)
  ] }
Files matching no rule, or a box that does not fit the frame, are reported and make the run exit 1 (never left silently old).
Videos: re-encoded with x264 crf 18, audio copied. Images: same format and size. Needs Pillow + ffmpeg/ffprobe.
Limits: one fixed box (a logo that moves needs a window per position); "auto"/colour covers are flat patches, so they show
on busy or gradient backgrounds, and "blur" is cosmetic (the old logo can ghost through); a different-aspect new logo leaves
the rest of the old box covered. QC proves the old area changed and nothing else did: it cannot judge that the result looks good.
Exit codes: 0 all ok, 1 a file failed/skipped/QC fail, 2 usage or tool error.
"""
import argparse, fnmatch, io, json, re, subprocess, sys
from pathlib import Path
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageStat

IMG = {".png", ".jpg", ".jpeg", ".webp"}
VID = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, check=False)
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} failed: " + " | ".join(p.stderr.decode(errors="replace").strip().splitlines()[-3:]))
    return p.stdout

def probe(path):
    d = json.loads(run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]))
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    rot = int(float(v.get("tags", {}).get("rotate", 0) or next((sd["rotation"] for sd in v.get("side_data_list", []) if "rotation" in sd), 0)))
    w, h = (v["height"], v["width"]) if abs(rot) % 180 == 90 else (v["width"], v["height"])   # ffmpeg autorotates
    return {"w": w, "h": h, "dur": float(d["format"]["duration"]), "audio": any(s["codec_type"] == "audio" for s in d["streams"])}

def frame(path, t):
    return Image.open(io.BytesIO(run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]))).convert("RGB")

def load_manifest(path):
    p = Path(path); m = json.loads(p.read_text(encoding="utf-8"))
    logo = Path(m["logo"]); m["_logo"] = logo if logo.is_absolute() else p.parent / logo
    if not m["_logo"].exists(): raise ValueError(f"logo not found: {m['_logo']}")
    for i, r in enumerate(m["rules"]):
        if "match" not in r or ("box" in r) == ("box_pct" in r): raise ValueError(f"rule {i}: needs 'match' and exactly one of 'box' / 'box_pct'")
        c = r.get("cover", "auto")
        if c not in ("auto", "blur", "none") and not re.fullmatch(r"#[0-9a-fA-F]{6}", c): raise ValueError(f"rule {i}: bad cover {c!r}")
    return m

def rule_for(m, name):
    return next((r for r in m["rules"] if fnmatch.fnmatch(name.lower(), r["match"].lower())), None)

def resolve_box(rule, W, H):
    x, y, w, h = [round(v * d) for v, d in zip(rule["box_pct"], (W, H, W, H))] if "box_pct" in rule else [int(v) for v in rule["box"]]
    if x < 0 or y < 0 or w < 4 or h < 4 or x + w > W or y + h > H: raise ValueError(f"box {[x, y, w, h]} does not fit the {W}x{H} frame")
    return x, y, w, h

def fit_logo(logo_path, box, pad_pct):
    lw, lh = Image.open(logo_path).size; x, y, w, h = box
    pad = min(w, h) * pad_pct / 100
    s = min((w - 2 * pad) / lw, (h - 2 * pad) / lh)
    nw, nh = max(1, round(lw * s)), max(1, round(lh * s))
    return nw, nh, x + (w - nw) // 2, y + (h - nh) // 2

def ring_color(img, box, g=6):
    x, y, w, h = box; ex = (max(0, x - g), max(0, y - g), min(img.width, x + w + g), min(img.height, y + h + g))
    c = img.crop(ex).convert("RGB"); px = c.load(); ox, oy = x - ex[0], y - ex[1]
    ring = [px[i, j] for j in range(c.height) for i in range(c.width) if not (ox <= i < ox + w and oy <= j < oy + h)]
    if not ring: raise ValueError("box covers the whole frame")
    return tuple(sorted(ch)[len(ch) // 2] for ch in zip(*ring))

# ---------- swap ----------
def swap_image(src, dst, rule, logo):
    im = Image.open(src).convert("RGBA"); box = resolve_box(rule, *im.size); x, y, w, h = box
    cover = rule.get("cover", "auto")
    if cover == "blur": im.paste(im.crop((x, y, x + w, y + h)).filter(ImageFilter.GaussianBlur(max(w, h) / 4)), (x, y))
    elif cover != "none": im.paste((*(ring_color(im, box) if cover == "auto" else ImageColor.getrgb(cover)), 255), (x, y, x + w, y + h))
    nw, nh, px, py = fit_logo(logo, box, rule.get("pad_pct", 0))
    lg = Image.open(logo).convert("RGBA").resize((nw, nh), Image.LANCZOS)
    op = float(rule.get("opacity", 1.0))
    if op < 1: lg.putalpha(lg.getchannel("A").point(lambda v: round(v * op)))
    im.alpha_composite(lg, (px, py))
    if dst.suffix.lower() in (".jpg", ".jpeg"): im.convert("RGB").save(dst, quality=95, subsampling=0)
    elif dst.suffix.lower() == ".webp": im.save(dst, quality=95)
    else: im.save(dst)

def swap_video(src, dst, rule, logo):
    info = probe(src); box = resolve_box(rule, info["w"], info["h"]); x, y, w, h = box
    s, e = rule.get("start"), rule.get("end")
    en = f":enable='between(t,{0 if s is None else s},{1e9 if e is None else e})'" if (s is not None or e is not None) else ""
    cover = rule.get("cover", "auto")
    if cover == "auto": cover = "#{:02x}{:02x}{:02x}".format(*ring_color(frame(src, s or 0), box))
    if cover == "none": bg = "[0:v]null[bg]"
    elif cover == "blur": bg = f"[0:v]split[a][b];[b]crop={w}:{h}:{x}:{y},boxblur={max(1, min(w, h) // 4)}:3[c];[a][c]overlay={x}:{y}{en}[bg]"
    else: bg = f"[0:v]drawbox=x={x}:y={y}:w={w}:h={h}:color={cover}:t=fill{en}[bg]"
    nw, nh, px, py = fit_logo(logo, box, rule.get("pad_pct", 0)); op = float(rule.get("opacity", 1.0))
    fg = f"[1:v]format=rgba,scale={nw}:{nh}" + (f",colorchannelmixer=aa={op}" if op < 1 else "") + f"[lg];[bg][lg]overlay={px}:{py}{en}[v]"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(logo), "-filter_complex", bg + ";" + fg, "-map", "[v]", "-map", "0:a?",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(dst)])

# ---------- qc ----------
def change(a, b, box):
    """(mean abs pixel change inside box, mean abs change outside box) between two same-size RGB images."""
    d = ImageChops.difference(a, b).convert("L"); x, y, w, h = box
    ins = ImageStat.Stat(d.crop((x, y, x + w, y + h))).sum[0]; tot = ImageStat.Stat(d).sum[0]
    return ins / (w * h), (tot - ins) / max(1, d.width * d.height - w * h)

def qc_pair(src, dst, rule):
    res = []
    def chk(name, ok, detail): res.append((name, bool(ok), detail))
    mc = rule.get("min_change", 8); tol = 4.0 if src.suffix.lower() in VID else 2.0   # video is re-encoded, so allow codec noise
    if src.suffix.lower() in IMG:
        a, b = Image.open(src).convert("RGB"), Image.open(dst).convert("RGB")
        chk("size", a.size == b.size, f"{b.size} vs {a.size}")
        if a.size != b.size: return res
        box = resolve_box(rule, *a.size); ins, out = change(a, b, box)
        chk("logo area changed", ins >= mc, f"mean change {ins:.1f} (need >= {mc})"); chk("rest untouched", out <= tol, f"mean change outside box {out:.2f} (max {tol})")
        return res
    i, o = probe(src), probe(dst)
    chk("size", (i["w"], i["h"]) == (o["w"], o["h"]), f"{o['w']}x{o['h']} vs {i['w']}x{i['h']}")
    chk("duration", abs(i["dur"] - o["dur"]) <= 0.15, f"{o['dur']:.2f}s vs {i['dur']:.2f}s")
    chk("audio kept", i["audio"] == o["audio"], f"audio {o['audio']} vs {i['audio']}")
    if (i["w"], i["h"]) != (o["w"], o["h"]): return res
    box = resolve_box(rule, i["w"], i["h"]); s, e = rule.get("start"), rule.get("end")
    s = 0 if s is None else min(s, i["dur"]); e = i["dur"] if e is None else min(e, i["dur"])
    t_in = (s + e) / 2; ins, out = change(frame(src, t_in), frame(dst, t_in), box)
    chk("logo area changed", ins >= mc, f"at {t_in:.1f}s mean change {ins:.1f} (need >= {mc})"); chk("rest untouched", out <= tol, f"at {t_in:.1f}s outside box {out:.2f} (max {tol})")
    t_out = (e + i["dur"]) / 2 if e < i["dur"] - 0.5 else s / 2 if s > 0.5 else None
    if t_out is not None:
        ins, _ = change(frame(src, t_out), frame(dst, t_out), box); chk("outside window untouched", ins <= tol, f"at {t_out:.1f}s inside box {ins:.2f} (max {tol})")
    return res

# ---------- cli ----------
def collect(inputs):
    files = []
    for i in inputs:
        p = Path(i); files += sorted(f for f in p.iterdir() if f.suffix.lower() in IMG | VID) if p.is_dir() else [p]
    return files

def cmd_swap_qc(a, do_swap):
    m = load_manifest(a.manifest); out = Path(a.out); out.mkdir(parents=True, exist_ok=True); report = []; bad = 0
    for f in collect(a.inputs):
        dst = out / f.name; row = {"file": f.name}
        try:
            rule = rule_for(m, f.name)
            if f.suffix.lower() not in IMG | VID: raise ValueError("not a supported image/video type")
            if rule is None: raise ValueError("no rule matches this file")
            if do_swap:
                if dst.resolve() == f.resolve(): raise ValueError("--out must not be the folder of the originals")
                (swap_image if f.suffix.lower() in IMG else swap_video)(f, dst, rule, m["_logo"])
            res = qc_pair(f, dst, rule) if (a.qc if do_swap else True) else []
            row.update(status="FAIL" if any(not ok for _, ok, _ in res) else "ok", checks=[{"check": n, "ok": ok, "detail": d} for n, ok, d in res])
        except Exception as ex:   # one bad file must not stop a batch of 35
            row.update(status="FAIL", error=str(ex))
        bad += row["status"] != "ok"; report.append(row)
        print(f"{row['status']:4} {f.name}" + (f": {row['error']}" if "error" in row else "") + "".join(f"\n       {'ok  ' if c['ok'] else 'FAIL'} {c['check']}: {c['detail']}" for c in row.get("checks", []) if not c["ok"]))
    (out / "logoswap_report.json").write_text(json.dumps(report, indent=1))
    print(f"{len(report) - bad}/{len(report)} ok -> {out}/logoswap_report.json")
    return 1 if bad or not report else 0

def cmd_preview(a):
    m = load_manifest(a.manifest); f = Path(a.file)
    im = Image.open(f).convert("RGB") if f.suffix.lower() in IMG else frame(f, a.at)
    d = ImageDraw.Draw(im)
    if a.grid:
        for gx in range(0, im.width, a.grid): d.line([(gx, 0), (gx, im.height)], fill=(0, 200, 255), width=1); d.text((gx + 2, 2), str(gx), fill=(255, 255, 0))
        for gy in range(0, im.height, a.grid): d.line([(0, gy), (im.width, gy)], fill=(0, 200, 255), width=1); d.text((2, gy + 2), str(gy), fill=(255, 255, 0))
    rule = rule_for(m, f.name)
    if rule:
        x, y, w, h = resolve_box(rule, *im.size); d.rectangle([x, y, x + w, y + h], outline=(255, 0, 0), width=3)
    else:
        print("note: no rule matches this file name; showing the grid only")
    im.save(a.out); print(f"wrote {a.out} ({im.width}x{im.height})")
    return 0

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("preview"); s.add_argument("manifest"); s.add_argument("file"); s.add_argument("--out", required=True); s.add_argument("--grid", type=int, default=0); s.add_argument("--at", type=float, default=1.0)
    for n in ("swap", "qc"):
        s = sub.add_parser(n); s.add_argument("manifest"); s.add_argument("inputs", nargs="+"); s.add_argument("--out", required=True)
        if n == "swap": s.add_argument("--no-qc", dest="qc", action="store_false")
    a = ap.parse_args(argv)
    try:
        return cmd_preview(a) if a.cmd == "preview" else cmd_swap_qc(a, a.cmd == "swap")
    except (RuntimeError, ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr); return 2

if __name__ == "__main__":
    sys.exit(main())
