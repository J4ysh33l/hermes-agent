"""The editor: Claude reads your numbered sentences and writes the plan (plan.py), on your Claude plan through
the handoff repo (orchestrator/HANDOFF.md, ``studio.claude_via: handoff``, the default) or over the API
(``api``, ANTHROPIC_API_KEY, paid). Without either, ``plan.basic`` edits on code alone (cuts, captions,
punch-ins, a title from the first sentence).

Through the handoff, Hermes commits the job's words, style and notes to ``edit/<job>/`` with
``tools/check_edit.py`` and ``tools/edit/`` (words.py, cuts.py, plan.py: standard library only), so Claude
runs the same checks before handing in; the queue checks the answer again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orchestrator import llm
from orchestrator.brief.net import Http
from orchestrator.handoff import Handoff

from . import cuts, plan as plans
from .style import Style
from .words import Sentence, Word, numbered

HERE = Path(__file__).parent
TOOLS = ("words.py", "cuts.py", "plan.py")
SCHEMA = plans.__doc__.split("    {", 1)[1].split("\n\n``at``", 1)[0]

CHECK = '''"""Checks an edit plan before it is handed in. Written by Hermes; the rules are tools/edit/plan.py.

    python3 tools/check_edit.py edit/<job>      (reads words.json, style.json, notes.txt, plan.json there)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from edit import cuts, plan, words  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    found = words.sentences(words.load(folder / "words.json"))
    look = json.loads((folder / "style.json").read_text(encoding="utf-8"))
    notes = (folder / "notes.txt").read_text(encoding="utf-8") if (folder / "notes.txt").is_file() else ""
    try:
        chosen = plan.load((folder / "plan.json").read_text(encoding="utf-8"))
        cut = cuts.build(words.load(folder / "words.json"), found, look, chosen.drop, chosen.trim, chosen.keep)
        problems = plan.check(chosen, found, cut, look, notes)
        for tip in plan.advice(chosen, found, cut, look):
            print(f"suggestion (yours to take or leave): {tip}")
    except (OSError, plan.PlanError) as exc:
        problems = [str(exc)]
    print("\\n".join(f"- {p}" for p in problems) if problems else "OK: ready to hand in")
    sys.exit(1 if problems else 0)
'''


@dataclass(frozen=True)
class Brief:
    prompt: str
    files: dict[str, str]  # path in the handoff repo → text


def frames_note(sheets: list[str], folder: str) -> str:
    if not sheets:
        return "(no frame sheets: decide from the words, and don't use \"hide\")"
    return ("Frame sheets, one frame from the middle of each sentence, labelled S<n>; open and look at every one "
            "before deciding (what is on screen, framing, focus, anything private):\n"
            + "\n".join(f"- {folder}/{name}" for name in sheets))


def assets_note(names: list[str]) -> str:
    if not names:
        return "(none: b-roll comes from stock by \"query\"; say in notes which of their own shots would help)"
    return "Use these by \"file\" (they beat stock footage):\n" + "\n".join(f"- {n}" for n in names)


def prompt(job: str, look: Style, words: list[Word], found: list[Sentence], asked: str, folder: str = "",
           sheets: list[str] = (), assets: list[str] = ()) -> str:
    cut = cuts.build(words, found, look)
    style = look.as_dict()
    g, pace, title = style["graphics"], style["pace"], style["title"]
    auto = [f"- S{k}: {v}" for k, v in sorted(cut.dropped.items())] + [f"- filler cut: {f}" for f in cut.fillers]
    from .style import summary
    return (HERE / "prompts" / "plan.md").read_text(encoding="utf-8").format(
        style_name=look.name, style_summary=summary(look), hook=style["plan"]["hook"], ending=style["plan"]["ending"],
        tone=style["plan"]["tone"], avoid=", ".join(style["plan"]["avoid"]) or "nothing listed",
        kinds=", ".join(g["kinds"]), emoji_note="" if "emoji" in g["kinds"] or not g["emoji"] else ", emoji",
        change_every=pace["change_every"], 
        frames_note=frames_note(list(sheets), folder or f"edit/{job}"), assets_note=assets_note(list(assets)), broll_pct=round(pace["broll"] * 100), title_kind=title["kind"],
        subtitle_note=(" with a short subtitle" if title["subtitle"] else "") + (
            "; wrap the 1–2 words that carry the point in *stars* (shown in the brand accent, italic), e.g. "
            "\"Care without *the chaos*\"" if title["accent"] != "none" else ""),
        asked=asked.strip() or "(nothing: edit it the way the style says)",
        seconds=words[-1].end if words else 0, kept=cut.seconds, sentences=numbered(found),
        auto="\n".join(auto) or "- nothing", folder=folder or f"edit/{job}", schema="    {" + SCHEMA)


def files(job: str, look: Style, words_json: str, asked: str, sheets: dict[str, bytes] | None = None
          ) -> dict[str, str | bytes]:
    out = {"tools/check_edit.py": CHECK, "tools/edit/__init__.py": ""}
    out.update({f"tools/edit/{name}": (HERE / name).read_text(encoding="utf-8") for name in TOOLS})
    out[f"edit/{job}/words.json"] = words_json
    out[f"edit/{job}/style.json"] = json.dumps(look.as_dict(), ensure_ascii=False, indent=1)
    out[f"edit/{job}/notes.txt"] = asked
    for name, data in (sheets or {}).items():
        out[f"edit/{job}/{name}"] = data
    return out


def send(hand: Handoff, job: str, look: Style, words_json: str, asked: str, text: str, round_: int = 0,
         sheets: dict[str, bytes] | None = None) -> int:
    return hand.send(files(job, look, words_json, asked, sheets), f"edit {job}: plan" + (f" fix {round_}" if round_ else ""), text)


def answer(hand: Handoff, job: str) -> tuple[plans.Plan | None, str]:
    text = hand.read(f"edit/{job}/plan.json")
    if text is None:
        return None, f"plan.json is missing: write it to edit/{job}/plan.json"
    try:
        return plans.load(text), ""
    except plans.PlanError as exc:
        return None, str(exc)


def fix_request(job: str, problems: list[str]) -> str:
    return (f"The plan in edit/{job}/plan.json does not pass its checks:\n\n" + "\n".join(f"- {p}" for p in problems)
            + f"\n\nFix only these in edit/{job}/plan.json, run `python3 tools/check_edit.py edit/{job}` until it "
            "prints OK, then hand in.")


def by_api(http: Http, key: str, model: str, text: str) -> plans.Plan:
    """One Messages call; the answer is the plan JSON (checked by the caller)."""
    reply = llm.claude(http, key, model, text + "\n\nAnswer with the plan JSON only (no file to write, no check to run).",
                       workflow="edit", step="plan", max_tokens=8000)
    body = reply[reply.find("{"): reply.rfind("}") + 1]
    return plans.load(body)
