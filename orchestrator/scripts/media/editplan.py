#!/usr/bin/env python3
"""editplan.py - transcript -> edit plan -> ffmpeg render -> QC. The LLM step is only "write the plan JSON".

  editplan.py transcribe VIDEO --out transcript.json [--model base] [--language en]    (local faster-whisper, CPU int8)
  editplan.py brief      transcript.json [--from S] [--to S] [--max-chars 6000]        (compact text for Claude to read)
  editplan.py validate   plan.json [--video VIDEO]                                      (schema + bounds, no render)
  editplan.py render     plan.json --out out.mp4 [--transcript transcript.json] [--keep-tmp]
  editplan.py qc         out.mp4 [--plan plan.json] [--tolerance 0.4] [--max-silence 2.5] [--max-freeze 3.0] [--max-av-offset 0.1]

Flow: transcribe (Whisper, free) -> brief (a few thousand tokens, not the whole transcript) -> Claude writes plan.json
-> validate -> render (ffmpeg, no LLM) -> qc (no LLM) -> deliver. Only the plan step uses a model.

PLAN (JSON):
{
  "source": "input.mp4",                       # relative to the plan file
  "output": {"width": 1080, "height": 1920, "fps": 30, "fit": "crop|pad",   # omit width/height to keep source size
             "crf": 23, "preset": "veryfast", "loudnorm": true},
  "segments": [ {"start": 12.0, "end": 18.5, "speed": 1.0, "note": "hook"}, ... ],   # any order; speed 0.5..2.0
  "captions": {"enabled": true, "words_per_line": 6, "size_pct": 6.0, "font": "DejaVu Sans", "margin_pct": 8},
  "music": {"path": "bed.mp3", "gain_db": -18, "duck": true}      # optional looped music bed; duck = dips under speech; loudnorm runs after the mix
}
Memory-safe on a 2 GB host: each segment is encoded on its own, then joined with a stream copy.
Exit codes: 0 ok, 1 QC/validation failure, 2 usage or tool error.
"""
import argparse, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
import itertools

def run(cmd, cwd=None, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", check=False)
    if check and p.returncode != 0:
        tail = "\n".join((p.stderr or "").strip().splitlines()[-6:])
        raise RuntimeError(f"{cmd[0]} failed (rc={p.returncode}):\n{tail}")
    return p

def probe(path):
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    d = json.loads(p.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    return {"duration": float(d["format"].get("duration", 0)), "video": v, "audio": a}

# ---------- transcribe ----------
def cmd_transcribe(a):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed: pip install faster-whisper (Hermes already depends on it)", file=sys.stderr); return 2
    model = WhisperModel(a.model, device="cpu", compute_type="int8")
    segs, info = model.transcribe(a.video, language=a.language, word_timestamps=True, vad_filter=True, beam_size=1)
    out = {"language": info.language, "duration": info.duration, "model": a.model, "segments": []}
    for s in segs:
        out["segments"].append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                                "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()} for w in (s.words or [])]})
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out['segments'])} segments, {out['duration']:.1f}s, language {out['language']} -> {a.out}")
    return 0

# ---------- brief ----------
def cmd_brief(a):
    t = json.loads(Path(a.transcript).read_text(encoding="utf-8"))
    lo, hi = (a.from_ or 0), (a.to or 1e12)
    lines = [f"# duration {t.get('duration', 0):.1f}s, language {t.get('language', '?')}. Format: start-end text (seconds)"]
    used = len(lines[0]); cut_at = None
    for s in t["segments"]:
        if s["end"] < lo or s["start"] > hi: continue
        line = f"{s['start']:.1f}-{s['end']:.1f} {s['text']}"
        if used + len(line) + 1 > a.max_chars:
            cut_at = s["start"]; break
        lines.append(line); used += len(line) + 1
    if cut_at is not None:
        lines.append(f"# truncated at {cut_at:.1f}s - rerun with --from {cut_at:.0f} for the rest")
    print("\n".join(lines))
    return 0

# ---------- validate ----------
def load_plan(path):
    p = Path(path); plan = json.loads(p.read_text(encoding="utf-8")); plan["_dir"] = p.parent; return plan

def validate_plan(plan, video=None):
    errs, warns = [], []
    segs = plan.get("segments")
    if not isinstance(segs, list) or not segs:
        return ["no segments"], warns
    dur = probe(video)["duration"] if video else None
    for i, s in enumerate(segs):
        try:
            st, en, sp = float(s["start"]), float(s["end"]), float(s.get("speed", 1.0))
        except Exception:
            errs.append(f"segment {i}: start/end must be numbers"); continue
        if st < 0 or en <= st: errs.append(f"segment {i}: need 0 <= start < end (got {st}, {en})")
        if not 0.5 <= sp <= 2.0: errs.append(f"segment {i}: speed must be 0.5..2.0 (got {sp})")
        if en - st < 0.3: warns.append(f"segment {i}: shorter than 0.3 s")
        if dur is not None and en > dur + 0.05: errs.append(f"segment {i}: end {en} beyond video length {dur:.2f}")
    ss = sorted((float(s["start"]), float(s["end"]), i) for i, s in enumerate(segs) if isinstance(s.get("start"), (int, float)) and isinstance(s.get("end"), (int, float)))
    for (a0, a1, i), (b0, b1, j) in itertools.pairwise(ss):
        if b0 < a1: warns.append(f"segments {i} and {j} overlap ({b0:.1f} < {a1:.1f}) - repeated footage?")
    m = plan.get("music")
    if m:
        mp = Path(m.get("path", "")); mp = mp if mp.is_absolute() else plan["_dir"] / mp
        if not mp.is_file(): errs.append(f"music.path not found: {mp}")
        if not -40 <= float(m.get("gain_db", -18)) <= 0: errs.append("music.gain_db must be -40..0")
    o = plan.get("output", {})
    for k in ("width", "height"):
        if k in o and (not isinstance(o[k], int) or o[k] % 2 or not 16 <= o[k] <= 4320): errs.append(f"output.{k} must be an even integer 16..4320")
    if ("width" in o) != ("height" in o): errs.append("give both output.width and output.height, or neither")
    if o.get("fit", "crop") not in ("crop", "pad"): errs.append("output.fit must be crop or pad")
    if not 1 <= int(o.get("fps", 30)) <= 60: errs.append("output.fps must be 1..60")
    return errs, warns

def cmd_validate(a):
    plan = load_plan(a.plan)
    video = a.video or (plan["_dir"] / plan["source"] if plan.get("source") else None)
    errs, warns = validate_plan(plan, video if video and Path(video).exists() else None)
    for w in warns: print("warn:", w)
    for e in errs: print("ERROR:", e)
    exp = expected_duration(plan)
    print(f"{len(plan.get('segments', []))} segment(s), expected output {exp:.1f}s" + (" - INVALID" if errs else " - ok"))
    return 1 if errs else 0

def expected_duration(plan):
    return sum((float(s["end"]) - float(s["start"])) / float(s.get("speed", 1.0)) for s in plan.get("segments", []) if "start" in s and "end" in s)

# ---------- render ----------
def srt_time(t):
    t = max(0, t); h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{round((s - int(s)) * 1000):03d}".replace(",1000", ",999")

def caption_cues(transcript, start, end, speed, words_per_line):
    """Cues for one segment, in segment-local output time."""
    cues = []
    for seg in transcript["segments"]:
        if seg["end"] <= start or seg["start"] >= end: continue
        words = [w for w in seg.get("words", []) if w["end"] > start and w["start"] < end]
        if not words:
            cues.append((max(seg["start"], start), min(seg["end"], end), seg["text"])); continue
        for i in range(0, len(words), words_per_line):
            ch = words[i:i + words_per_line]
            cues.append((max(ch[0]["start"], start), min(ch[-1]["end"], end), " ".join(w["word"] for w in ch)))
    return [((c0 - start) / speed, (c1 - start) / speed, tx) for c0, c1, tx in cues if c1 > c0]

def write_srt(path, cues):
    Path(path).write_text("".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{t}\n\n" for i, (a, b, t) in enumerate(cues, 1)), encoding="utf-8")

def cmd_render(a):
    plan = load_plan(a.plan)
    src = Path(plan["source"]); src = src if src.is_absolute() else plan["_dir"] / src
    errs, _warns = validate_plan(plan, src)
    if errs:
        print("plan invalid:\n  " + "\n  ".join(errs), file=sys.stderr); return 1
    info = probe(src); has_audio = info["audio"] is not None
    o = plan.get("output", {}); cap = plan.get("captions", {})
    caps_on = bool(cap.get("enabled")) and a.transcript
    transcript = json.loads(Path(a.transcript).read_text(encoding="utf-8")) if caps_on else None
    if cap.get("enabled") and not a.transcript:
        print("warn: captions enabled but no --transcript given; rendering without captions", file=sys.stderr)
    W, H = o.get("width"), o.get("height"); fps = int(o.get("fps", 30))
    tmp = Path(a.tmp or tempfile.mkdtemp(prefix="editplan-")); tmp.mkdir(parents=True, exist_ok=True)
    segfiles = []
    try:
        for i, s in enumerate(plan["segments"]):
            st, en, sp = float(s["start"]), float(s["end"]), float(s.get("speed", 1.0))
            vf = []
            if W and H:
                if o.get("fit", "crop") == "crop":
                    vf.append(f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}")
                else:
                    vf.append(f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2")
            else:
                vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
            if sp != 1.0: vf.append(f"setpts=PTS/{sp}")
            vf.append(f"fps={fps}")
            if caps_on:
                cues = caption_cues(transcript, st, en, sp, int(cap.get("words_per_line", 6)))
                if cues:
                    write_srt(tmp / f"cap_{i}.srt", cues)
                    fs = float(cap.get("size_pct", 6.0)) / 100 * 288   # libass script height for SRT is 288
                    style = f"FontName={cap.get('font', 'DejaVu Sans')},FontSize={fs:.1f},Bold=1,Outline=2.5,Shadow=0,Alignment=2,MarginV={float(cap.get('margin_pct', 8)) / 100 * 288:.0f}"
                    vf.append(f"subtitles=cap_{i}.srt:force_style='{style}'")
            cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{st}", "-t", f"{en - st}", "-i", str(src.resolve())]
            if not has_audio:
                cmd += ["-f", "lavfi", "-t", f"{(en - st) / sp}", "-i", "anullsrc=r=48000:cl=stereo"]
            cmd += ["-vf", ",".join(vf)]
            if has_audio:
                cmd += ["-af", (f"atempo={sp}," if sp != 1.0 else "") + "aresample=48000", "-ac", "2"]
            else:
                cmd += ["-map", "0:v:0", "-map", "1:a:0"]
            cmd += ["-c:v", "libx264", "-preset", o.get("preset", "veryfast"), "-crf", str(o.get("crf", 23)), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000", f"seg_{i}.mp4"]
            run(cmd, cwd=tmp)
            segfiles.append(f"seg_{i}.mp4")
            print(f"segment {i + 1}/{len(plan['segments'])} done", flush=True)
        (tmp / "list.txt").write_text("".join(f"file '{f}'\n" for f in segfiles))
        out = Path(a.out).resolve(); out.parent.mkdir(parents=True, exist_ok=True)
        ln = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"; music = plan.get("music")
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", "list.txt"]
        if music:   # looped music bed under the voice; "duck" lowers it while the voice is speaking
            mp = Path(music["path"]); cmd += ["-stream_loop", "-1", "-i", str(mp if mp.is_absolute() else (plan["_dir"] / mp).resolve())]
            bed = f"[1:a]volume={float(music.get('gain_db', -18))}dB[m];"
            duck = ("[0:a]asplit[v][sc];" + bed + "[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=400[d];[v][d]") if music.get("duck", True) else (bed + "[0:a][m]")
            cmd += ["-filter_complex", duck + "amix=inputs=2:duration=first:normalize=0" + (f",{ln}" if o.get("loudnorm", True) else "") + "[a]", "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k"]
        else:
            cmd += ["-c:v", "copy"] + (["-af", ln, "-c:a", "aac", "-b:a", "160k"] if o.get("loudnorm", True) else ["-c:a", "copy"])
        cmd += ["-movflags", "+faststart", str(out)]
        run(cmd, cwd=tmp)
        print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB), expected {expected_duration(plan):.1f}s")
    finally:
        if not a.keep_tmp and not a.tmp: shutil.rmtree(tmp, ignore_errors=True)
    return 0

# ---------- qc ----------
def cmd_qc(a):
    res = []
    def check(name, ok, detail): res.append(ok); print(("PASS " if ok else "FAIL ") + f"{name}: {detail}")
    info = probe(a.video); v, au = info["video"], info["audio"]
    check("video stream", v is not None, f"{v['width']}x{v['height']} {v.get('codec_name')}" if v else "missing")
    check("audio stream", au is not None, au.get("codec_name") if au else "missing")
    if a.plan:
        plan = load_plan(a.plan); exp = expected_duration(plan)
        check("duration", abs(info["duration"] - exp) <= a.tolerance, f"{info['duration']:.2f}s vs expected {exp:.2f}s (tolerance {a.tolerance}s)")
        o = plan.get("output", {})
        if v and o.get("width"): check("resolution", (v["width"], v["height"]) == (o["width"], o["height"]), f"{v['width']}x{v['height']} vs {o['width']}x{o['height']}")
    p = run(["ffmpeg", "-hide_banner", "-nostats", "-i", a.video, "-vf", f"blackdetect=d=1.0:pix_th=0.10,freezedetect=n=-60dB:d={a.max_freeze}", "-af",
             f"silencedetect=noise=-35dB:d={a.max_silence},ebur128=peak=true", "-f", "null", "-"], check=False)
    err = p.stderr
    black = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)
    check("black frames", not black, "none >= 1 s" if not black else "; ".join(f"{s}-{e}s" for s, e in black[:5]))
    fz = re.findall(r"freeze_start: ([\d.]+)", err)
    check("frozen picture", not fz, f"none >= {a.max_freeze}s" if not fz else f"{len(fz)} still stretch(es) >= {a.max_freeze}s, first at {float(fz[0]):.1f}s")
    av_sync(v, au, a, check)
    sil = re.findall(r"silence_start: ([\d.]+)", err)
    check("dead air", not sil, f"none >= {a.max_silence}s" if not sil else f"{len(sil)} gap(s) >= {a.max_silence}s, first at {sil[0]}s")
    m = re.findall(r"\n\s+I:\s+(-?[\d.]+) LUFS", err)
    if m and plan_loud(a):
        lu = float(m[-1]); check("loudness", -19 <= lu <= -13, f"{lu:.1f} LUFS (target about -16)")
    return 0 if all(res) else 1

def av_sync(v, au, a, check):
    """Container-level sync only: do audio and video start together and end together? Lip-sync drift inside the content is not measured."""
    def num(s, k):
        try: return float(s[k])
        except (KeyError, TypeError, ValueError): return None
    if not (v and au): return
    vs, as_, vd, ad = num(v, "start_time"), num(au, "start_time"), num(v, "duration"), num(au, "duration")
    if None in (vs, as_):
        print("SKIP audio/video start: container gives no stream start times")
    else:
        check("a/v start offset", abs(vs - as_) <= a.max_av_offset, f"audio starts {as_ - vs:+.3f}s vs video (max {a.max_av_offset}s)")
    if None in (vd, ad):
        print("SKIP audio/video length: container gives no stream durations")
    else:
        check("a/v length", abs(vd - ad) <= max(0.25, a.max_av_offset), f"video {vd:.2f}s, audio {ad:.2f}s")

def plan_loud(a):
    return (not a.plan) or load_plan(a.plan).get("output", {}).get("loudnorm", True)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("transcribe"); s.add_argument("video"); s.add_argument("--out", required=True); s.add_argument("--model", default="base"); s.add_argument("--language")
    s = sub.add_parser("brief"); s.add_argument("transcript"); s.add_argument("--from", dest="from_", type=float); s.add_argument("--to", type=float); s.add_argument("--max-chars", type=int, default=6000)
    s = sub.add_parser("validate"); s.add_argument("plan"); s.add_argument("--video")
    s = sub.add_parser("render"); s.add_argument("plan"); s.add_argument("--out", required=True); s.add_argument("--transcript"); s.add_argument("--tmp"); s.add_argument("--keep-tmp", action="store_true")
    s = sub.add_parser("qc"); s.add_argument("video"); s.add_argument("--plan"); s.add_argument("--tolerance", type=float, default=0.4); s.add_argument("--max-silence", type=float, default=2.5); s.add_argument("--max-freeze", type=float, default=3.0); s.add_argument("--max-av-offset", type=float, default=0.1)
    a = ap.parse_args(argv)
    try:
        return {"transcribe": cmd_transcribe, "brief": cmd_brief, "validate": cmd_validate, "render": cmd_render, "qc": cmd_qc}[a.cmd](a)
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr); return 2

if __name__ == "__main__":
    sys.exit(main())
