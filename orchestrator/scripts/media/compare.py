#!/usr/bin/env python3
"""compare.py - "OLD vs NEW" sign-off sheet: OLD | NEW | DIFF side by side, plus the percentage of pixels that changed. No LLM.

  compare.py OLD NEW --out sheet.png [--at 2,10] [--threshold 12] [--max-diff PCT] [--min-diff PCT] [--labels OLD NEW]
  compare.py OLD_DIR NEW_DIR --out SHEETS_DIR ...        pairs files by name; a name present on one side only is a failure

Images or videos (a video is compared at the --at seconds, default the middle; each time is one row of the sheet).
A pixel counts as changed when any colour channel differs by more than --threshold (0-255, default 12, which ignores
video-codec noise). The DIFF panel shows changed pixels in red over a dimmed NEW. If the sizes differ, NEW is scaled to
OLD's size for the diff and the sheet says so (the percentage is then approximate).
Gates (for scripts): --max-diff X fails when more than X% changed ("should be unchanged"); --min-diff Y fails when less
than Y% changed ("should have changed"). With several --at times the largest percentage is used.
Exit codes: 0 ok, 1 a gate or pairing failed, 2 usage or tool error. Needs Pillow; ffmpeg/ffprobe for videos.
"""
import argparse, io, json, subprocess, sys
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageStat

IMG = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
VID = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
PANEL = 640

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, check=False)
    if p.returncode:
        raise RuntimeError(f"{cmd[0]} failed: " + " | ".join(p.stderr.decode(errors="replace").strip().splitlines()[-3:]))
    return p.stdout

def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))

def grab(path, t=None):
    if path.suffix.lower() in IMG: return Image.open(path).convert("RGB")
    return Image.open(io.BytesIO(run(["ffmpeg", "-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]))).convert("RGB")

def diff(a, b, thr):
    """(percent changed, bbox of changed pixels or None, red-highlight image, size_differs)."""
    same = a.size == b.size
    if not same: b = b.resize(a.size, Image.LANCZOS)
    r, g, bl = ImageChops.difference(a, b).split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), bl).point(lambda v: 255 if v > thr else 0)
    pct = ImageStat.Stat(mask).sum[0] / 255 / (a.width * a.height) * 100
    vis = Image.composite(Image.new("RGB", a.size, (255, 0, 0)), b.point(lambda v: v // 3), mask)
    return pct, mask.getbbox(), vis, not same

def font(size):
    try: return ImageFont.load_default(size=size)
    except TypeError: return ImageFont.load_default()   # Pillow < 10.1

def sheet(rows, labels, thr):
    """rows: [(caption, old_img, new_img)] -> (sheet image, [per-row stats])."""
    ph = round(rows[0][1].height * min(1, PANEL / rows[0][1].width)); F = font(16); gap = 8; head = 52
    cells, stats = [], []
    for cap, a, b in rows:
        pct, bbox, vis, resized = diff(a, b, thr)
        stats.append({"caption": cap, "changed_pct": round(pct, 3), "bbox": bbox, "size_differs": resized, "old_size": a.size, "new_size": b.size})
        cells.append((cap, [im.resize((max(1, round(im.width * ph / im.height)), ph)) for im in (a, b, vis)], stats[-1]))
    width = max(sum(c.width for c in ims) + gap * 4 for _, ims, _ in cells)
    out = Image.new("RGB", (width, head + (ph + head) * len(cells)), (24, 24, 24)); d = ImageDraw.Draw(out)
    d.text((gap, 6), f"OLD: {labels[0]}    NEW: {labels[1]}    (changed = any channel > {thr})", fill=(255, 255, 255), font=F)
    for i, (cap, ims, s) in enumerate(cells):
        y = head + i * (ph + head)
        warn = f"   SIZE DIFFERS old {s['old_size']} new {s['new_size']}: diff approximate" if s["size_differs"] else ""
        bb = f"   changed area x{s['bbox'][0]}-{s['bbox'][2]} y{s['bbox'][1]}-{s['bbox'][3]}" if s["bbox"] else "   no changed pixels"
        d.text((gap, y - 24), f"{cap}   DIFF {s['changed_pct']:.2f}% of pixels{bb}{warn}", fill=(255, 220, 80), font=F)
        x = gap
        for im in ims: out.paste(im, (x, y)); x += im.width + gap
    return out, stats

def compare_pair(old, new, out, a):
    times = [None]
    if old.suffix.lower() in VID or new.suffix.lower() in VID:
        times = [float(t) for t in a.at.split(",")] if a.at else [min(duration(old), duration(new)) / 2]
    rows = [((f"{old.name} @ {t:g}s" if t is not None else old.name), grab(old, t), grab(new, t)) for t in times]
    img, stats = sheet(rows, a.labels or (old.name, new.name), a.threshold)
    out.parent.mkdir(parents=True, exist_ok=True); img.save(out)
    return max(s["changed_pct"] for s in stats), stats

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("old"); ap.add_argument("new"); ap.add_argument("--out", required=True)
    ap.add_argument("--at"); ap.add_argument("--threshold", type=int, default=12); ap.add_argument("--labels", nargs=2)
    ap.add_argument("--max-diff", type=float); ap.add_argument("--min-diff", type=float)
    a = ap.parse_args(argv); old, new, out = Path(a.old), Path(a.new), Path(a.out)
    try:
        if old.is_dir() != new.is_dir(): raise ValueError("give two files or two folders")
        if old.is_dir():
            ok = lambda p: p.suffix.lower() in IMG | VID
            on, nn = {p.name: p for p in old.iterdir() if ok(p)}, {p.name: p for p in new.iterdir() if ok(p)}
            pairs = [(on[n], nn[n], out / (n + ".png")) for n in sorted(on.keys() & nn.keys())]
            missing = [f"only in OLD: {n}" for n in sorted(on.keys() - nn.keys())] + [f"only in NEW: {n}" for n in sorted(nn.keys() - on.keys())]
        else:
            pairs, missing = [(old, new, out)], []
        bad = len(missing); report = []
        for m in missing: print("FAIL", m)
        for o, n, dst in pairs:
            pct, stats = compare_pair(o, n, dst, a)
            why = f"more than {a.max_diff}% changed" if a.max_diff is not None and pct > a.max_diff else f"less than {a.min_diff}% changed" if a.min_diff is not None and pct < a.min_diff else ""
            bad += bool(why); report.append({"file": o.name, "changed_pct": pct, "sheet": str(dst), "fail": why or None, "rows": stats})
            print(f"{'FAIL' if why else 'ok  '} {o.name}: {pct:.2f}% changed -> {dst}" + (f"  ({why})" if why else ""))
        if old.is_dir():
            out.mkdir(parents=True, exist_ok=True); (out / "compare_report.json").write_text(json.dumps({"missing": missing, "pairs": report}, indent=1))
        if not pairs and not missing: raise ValueError("no images or videos to compare")
        return 1 if bad else 0
    except (RuntimeError, ValueError, FileNotFoundError, StopIteration) as e:
        print(f"error: {e}", file=sys.stderr); return 2

if __name__ == "__main__":
    sys.exit(main())
