"""Runs an approved plan. The daily cap is checked for the whole selection first, so a batch is
never cut off halfway by it. Inside a line, a failed step stops that line (no Slack note for an
invite that wasn't created); the other lines still go. Every attempt is logged in sent.jsonl."""

from __future__ import annotations

from datetime import datetime

from orchestrator.brief.net import HttpError

from . import graph, slackapi
from .errors import OutreachError
from .plan import Action, Plan
from .session import Session


def _dm(session: Session, action: Action) -> str:
    channel = slackapi.open_dm(session.http, session.slack_token, list(action.user_ids))
    if action.kind == "scheduled":
        slackapi.schedule(session.http, session.slack_token, channel, action.text, action.post_at)
        return channel
    slackapi.send(session.http, session.slack_token, channel, action.text)
    return channel


def _event(session: Session, action: Action) -> str:
    _id, join = graph.create_event(
        session.http, session.graph_token(), subject=action.subject, body_html=action.text,
        start=datetime.fromisoformat(action.start), end=datetime.fromisoformat(action.end),
        attendees=[{"name": n, "email": e} for n, e in action.attendees], teams=action.teams)
    return join


def _post(session: Session, action: Action, join: str) -> None:
    text = action.text.replace("{join}", f" Teams link: {join}" if join else "")
    slackapi.send(session.http, session.slack_token, action.channel_id, text)


def _who(action: Action) -> str:
    if action.kind == "event":
        return ", ".join(e for _n, e in action.attendees[:5]) + (" …" if len(action.attendees) > 5 else "")
    return action.channel_id or ",".join(action.user_ids)


def run(session: Session, plan: Plan, picked: list[int]) -> str:
    cap = session.settings.daily_cap
    used = session.store.sent_today(session.now)
    need = plan.sends(picked)
    if used + need > cap:
        return (f"Not sent: this needs {need} sends and {used} of today's {cap} are used. "
                "Pick fewer lines (yes 1,2) or raise outreach.daily_cap in brief.yaml.")
    done, failed = [], []
    for index in picked:
        line = plan.lines[index]
        join = ""
        for action in line.actions:
            try:
                if action.kind == "event":
                    join = _event(session, action)
                elif action.kind == "channel_post":
                    _post(session, action, join)
                else:
                    _dm(session, action)
            except (OutreachError, HttpError) as exc:
                session.store.log(session.now, action.kind, _who(action), action.subject or action.text, False, str(exc))
                failed.append(f"{index + 1}. {line.label.splitlines()[0]} — {exc}")
                break
            session.store.log(session.now, action.kind, _who(action), action.subject or action.text, True)
        else:
            done.append(index + 1)
    out = [f"✅ Sent: line{'s' if len(done) != 1 else ''} {', '.join(map(str, done))}" if done else "Nothing was sent."]
    if failed:
        out += ["", "❌ Failed (the rest of that line was not sent):"] + failed
    return "\n".join(out)
