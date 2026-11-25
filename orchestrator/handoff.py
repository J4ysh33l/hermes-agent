"""Handing work to Claude through your private GitHub repo (the "handoff repo").

Hermes commits any input files under a folder, then opens an issue labelled ``hermes`` whose body is
the whole task: what to do, the rules, where to write the answer. The issue-opened event starts your
Claude scheduled task (the Claude GitHub App must be installed on the repo); its prompt
(``orchestrator/HANDOFF.md``) only says to take the oldest open ``hermes`` issue (removing the label
claims it), do what its body says and close it. Hermes reads the answer files on its next run.

Token: ``GITHUB_HANDOFF_TOKEN`` in ``$HERMES_HOME/.env``, fine-grained, that repo only, Contents and
Issues read/write.

Issues opened with the Claude GitHub App's own credentials don't start the task (seen 2026-11-24), so
after opening an issue Hermes also fires the task through its API trigger when ``CLAUDE_ROUTINE_URL``
(the task's Fire URL) and ``CLAUDE_ROUTINE_TOKEN`` are in ``.env``. A failed fire is not an error: the
issue waits for the next run (any fire or issue-opened event takes the oldest waiting issue).
"""

from __future__ import annotations

import base64
import json

from orchestrator.brief.creds import Secrets
from orchestrator.brief.net import Http, HttpError

API = "https://api.github.com"
LABEL = "hermes"  # open + labelled = waiting for Claude; the scheduled task removes it when it starts
MAX_BODY = 65_000  # GitHub refuses issue bodies over 65,536 characters
# Kept in the repo with every request, so the task's prompt can stay plain English (nothing to retype).
# `gh api` only: the task's sessions block GitHub's GraphQL API, which `gh issue` needs.
CLAIM = """#!/bin/sh
# Claims the oldest open issue labelled $1 (default "{label}") and prints it. Written by Hermes; do not edit.
R={repo}
L=${{1:-{label}}}
n=$(gh api "repos/$R/issues?state=open&labels=$L&sort=created&direction=asc&per_page=1" --jq '.[0].number // empty') || {{ echo "GITHUB ERROR: listing issues failed"; exit 1; }}
[ -n "$n" ] || {{ echo "NOTHING TO DO"; exit 0; }}
gh api -X DELETE "repos/$R/issues/$n/labels/$L" >/dev/null || {{ echo "GITHUB ERROR: claiming issue $n failed"; exit 1; }}
echo "$n" > "$(git rev-parse --git-dir)/hermes-issue"  # for tools/usage_hook.py: whose tokens this run reports
gh api "repos/$R/issues/$n" --jq '"ISSUE \\(.number)\\n\\(.body)"'
"""
CLOSE = """#!/bin/sh
# Closes issue $1 once its answer is pushed. Written by Hermes; do not edit.
gh api -X PATCH "repos/{repo}/issues/$1" -f state=closed >/dev/null && echo "CLOSED $1"
"""
# A Stop hook in the repo (.claude/settings.json runs it when a run ends): sums the run's tokens from
# its own transcript and posts them on the issue it claimed, as a comment Hermes reads for its report.
USAGE_MARK = "<!-- hermes-usage -->"
USAGE_HOOK = r'''"""Posts this run's token use on the issue it claimed. Written by Hermes; do not edit.
Runs as a Stop hook; never blocks the run (always exits 0)."""
import json
import os
import subprocess
import sys

REPO = "{repo}"
KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def main():
    hook = json.load(sys.stdin)
    try:
        claimed = os.path.join(os.environ.get("CLAUDE_PROJECT_DIR") or ".", ".git", "hermes-issue")
        issue = open(claimed, encoding="utf-8").read().strip()
    except OSError:
        return  # this run claimed nothing
    if not issue.isdigit():
        return
    calls, model, first, last = {{}}, "", "", ""
    with open(hook["transcript_path"], encoding="utf-8") as fh:
        for raw in fh:
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            stamp = entry.get("timestamp") or ""
            if stamp:
                first, last = first or stamp, stamp
            message = entry.get("message") or {{}}
            if entry.get("type") == "assistant" and isinstance(message.get("usage"), dict):
                calls[message.get("id") or len(calls)] = message["usage"]  # one id = one call, logged per block
                model = message.get("model") or model
    totals = {{k: sum(int(u.get(k) or 0) for u in calls.values()) for k in KEYS}}
    body = {{"issue": int(issue), "session": hook.get("session_id", ""), "model": model, "calls": len(calls),
            "first": first, "last": last, **totals}}
    subprocess.run(["gh", "api", "-X", "POST", f"repos/{{REPO}}/issues/{{issue}}/comments",
                    "-f", "body={mark}\n" + json.dumps(body)], capture_output=True, timeout=60)


try:
    main()
except Exception:  # noqa: BLE001 - reporting must never break the run
    pass
'''
# What every Claude run in the handoff repo may use. Each tool a session loads is sent again on every model
# call of the run (~47k tokens before the issue is read), so the repo's settings remove what no Hermes job
# needs. Generous on purpose: kept are the file tools, the shell, web search and fetch (research), and
# GitHub's issue/file tools (the prompt's fallback when `gh api` fails). A bare name in "deny" takes the tool out of Claude's context entirely
# (code.claude.com/docs/en/permissions). Applies to every job, now and future, sent through Handoff.
KEEP = ("Bash", "Read", "Write", "Edit", "Glob", "Grep", "ToolSearch", "TodoWrite")
DENY = (
    # other agents, notebooks, skills, scheduling, messaging, artifacts, connectors, plugins
    # (web search and fetch stay: Claude researches through the handoff, research.py)
    "Agent", "Task", "NotebookEdit", "Skill", "Workflow", "Monitor",
    "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "TaskStop", "CronCreate", "CronDelete", "CronList",
    "ScheduleWakeup", "SendMessage", "ListAgents", "PushNotification", "ReadNotifications", "SendUserFile",
    "Artifact", "ArtifactComments", "ArtifactData", "DesignSync", "EnterWorktree", "ExitWorktree",
    "SearchMcpRegistry", "SuggestConnectors", "ListConnectors", "ListMcpResourcesTool", "ReadMcpResourceTool",
    "ReadMcpResourceDirTool", "ListPlugins", "SearchPlugins", "SuggestPluginInstall", "PublishPlugin",
    "ListSkills", "SearchSkills", "SuggestSkills", "ReportFindings", "ShareOnboardingGuide",
    "ShowOnboardingRolePicker", "EnterPlanMode", "ExitPlanMode", "AskUserQuestion",
    # session/scheduling tools of the cloud environment
    "mcp__claude-code-remote", "mcp__claude-code-remote__*",
    # GitHub tools no job needs (kept: issue_read/issue_write/list_issues/add_issue_comment,
    # get_file_contents/create_or_update_file/push_files, list_commits/get_commit)
    *(f"mcp__github__{t}" for t in (
        "actions_get", "actions_list", "actions_run_trigger", "add_comment_to_pending_review",
        "add_reply_to_pull_request_comment", "create_branch", "create_pull_request", "create_repository",
        "delete_file", "disable_pr_auto_merge", "enable_pr_auto_merge", "fork_repository", "get_check_run",
        "get_job_logs", "get_label", "get_latest_release", "get_me", "get_release_by_tag", "get_tag",
        "get_team_members", "get_teams", "list_branches", "list_issue_fields", "list_issue_types",
        "list_pull_requests", "list_releases", "list_repository_collaborators", "list_tags",
        "merge_pull_request", "pull_request_read", "pull_request_review_write", "request_copilot_review",
        "resolve_review_thread", "run_secret_scanning", "sub_issue_write", "unresolve_review_thread",
        "update_issue_comment", "update_pull_request", "update_pull_request_branch")),
)
SETTINGS = json.dumps({
    "permissions": {"deny": list(DENY)},
    "enabledPlugins": {"github@synced": False},  # its GitHub tools duplicate the environment's own
    "autoMemoryEnabled": False,
    "includeGitInstructions": False,  # the prompt gives the exact git command
    "hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/tools/usage_hook.py"', "timeout": 60}]}]},
}, indent=1) + "\n"
# Steps Hermes sends to Claude Sonnet go to a second scheduled task (same repo, same prompt but
# `sh tools/claim.sh hermes-sonnet`), started by its own API trigger; without one they go to the main task.
SONNET = "sonnet"
FIRE_HEADERS = {"anthropic-version": "2023-06-01", "anthropic-beta": "experimental-cc-routine-2026-04-01"}


class HandoffError(Exception):
    """Shown as it is; the work stays queued."""


class Handoff:
    def __init__(self, http: Http, secrets: Secrets, repo: str) -> None:
        self.http = http
        self.repo = repo
        self.token = secrets.get("GITHUB_HANDOFF_TOKEN")
        self.fire_url = secrets.get("CLAUDE_ROUTINE_URL")
        self.fire_token = secrets.get("CLAUDE_ROUTINE_TOKEN")
        self.sonnet_url = secrets.get("CLAUDE_ROUTINE_SONNET_URL")
        self.sonnet_token = secrets.get("CLAUDE_ROUTINE_SONNET_TOKEN")
        self.lane = ""  # SONNET: the next send goes to the Sonnet task (when it is set up)
        self.lane_used = ""  # where the last send went: SONNET or "" (the main task)
        self.fire_error = ""  # why the last fire failed ("" when it worked or was not set up)
        self.session = ""  # the Claude session the last fire started

    @property
    def ready(self) -> bool:
        return bool(self.repo and self.token)

    def _call(self, method: str, path: str, **kw):
        if not self.ready:
            raise HandoffError("Claude handoff is not set up: notes.handoff_repo (or watch.handoff_repo) in "
                               "brief.yaml and GITHUB_HANDOFF_TOKEN in .env")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        return self.http.request(method, f"{API}/repos/{self.repo}/{path}", headers=headers, **kw).json()

    def put(self, path: str, text: str) -> None:
        """Commit ``text`` at ``path`` (creating or replacing it; nothing when it is already the same)."""
        try:
            found = self._call("GET", f"contents/{path}")
        except HttpError as exc:
            if exc.status != 404:
                raise
            found = None
        if found and base64.b64decode(found["content"]).decode("utf-8") == text:
            return
        body = {"message": f"handoff: {path}", "content": base64.b64encode(text.encode()).decode()}
        if found:
            body["sha"] = found["sha"]
        self._call("PUT", f"contents/{path}", json_body=body)

    def send(self, files: dict[str, str], title: str, body: str) -> int:
        """Commit each ``path: text``, then open the issue (``body`` is Claude's whole task); returns its number."""
        if len(body) > MAX_BODY:
            raise HandoffError(f"the request is {len(body):,} characters; GitHub takes at most {MAX_BODY:,}")
        try:
            tools = {"tools/claim.sh": CLAIM.format(repo=self.repo, label=LABEL),
                     "tools/close.sh": CLOSE.format(repo=self.repo),
                     "tools/usage_hook.py": USAGE_HOOK.format(repo=self.repo, mark=USAGE_MARK),
                     ".claude/settings.json": SETTINGS}
            for path, text in {**tools, **files}.items():
                self.put(path, text)
            self.lane_used = SONNET if self.lane == SONNET and self.sonnet_url and self.sonnet_token else ""
            label = f"{LABEL}-{SONNET}" if self.lane_used else LABEL
            self._label(label)
            number = int(self._call("POST", "issues", json_body={"title": title, "body": body, "labels": [label]})["number"])
        except HttpError as exc:
            raise HandoffError(f"GitHub handoff: HTTP {exc.status}") from None
        self.fire(f"Hermes opened issue #{number}: {title}", self.lane_used)
        return number

    def fire(self, text: str = "", lane: str = "") -> bool:
        """Start the Claude task through its API trigger; False when not set up or refused (never raises)."""
        self.fire_error, self.session = "", ""
        url, token = (self.sonnet_url, self.sonnet_token) if lane == SONNET else (self.fire_url, self.fire_token)
        if not (url and token):
            return False
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", **FIRE_HEADERS}
        try:
            done = self.http.request("POST", url, headers=headers, json_body={"text": text[:2000]})
        except HttpError as exc:
            self.fire_error = f"Claude task fire: HTTP {exc.status}"
            return False
        except OSError as exc:  # network down: the issue simply waits
            self.fire_error = f"Claude task fire: {exc.__class__.__name__}"
            return False
        try:
            self.session = str(done.json().get("claude_code_session_id") or "")
        except (ValueError, AttributeError):
            pass
        return True

    def issue(self, number: int) -> dict:
        """The issue's ``created_at`` / ``closed_at`` (ISO, UTC); {} when GitHub can't be read."""
        try:
            found = self._call("GET", f"issues/{number}")
        except (HttpError, HandoffError, OSError):
            return {}
        return {"created_at": found.get("created_at") or "", "closed_at": found.get("closed_at") or ""}

    def usage(self, number: int) -> dict:
        """The token use the run that answered ``number`` posted (its last report); {} when none."""
        try:
            comments = self._call("GET", f"issues/{number}/comments", params={"per_page": 100})
        except (HttpError, HandoffError, OSError):
            return {}
        for comment in reversed(comments or []):
            body = comment.get("body") or ""
            if body.startswith(USAGE_MARK):
                line = next((x for x in body[len(USAGE_MARK):].splitlines() if x.strip()), "")
                try:  # the JSON line only: the session may append a footer
                    return json.loads(line)
                except ValueError:
                    continue
        return {}

    def _label(self, name: str = LABEL) -> None:
        try:
            self._call("POST", "labels", json_body={"name": name, "color": "5319e7",
                                                    "description": "Waiting for Claude (Hermes handoff)"})
        except HttpError as exc:
            if exc.status != 422:  # 422: it exists already
                raise

    def closed(self, number: int) -> bool:
        """True once Claude has closed the issue (its answer is complete)."""
        try:
            return self._call("GET", f"issues/{number}")["state"] == "closed"
        except HttpError as exc:
            raise HandoffError(f"GitHub handoff: HTTP {exc.status}") from None

    def read(self, path: str) -> str | None:
        """A file Claude committed, or None while it is not there yet."""
        try:
            found = self._call("GET", f"contents/{path}")
        except HttpError as exc:
            if exc.status == 404:
                return None
            raise HandoffError(f"GitHub handoff: HTTP {exc.status}") from None
        return base64.b64decode(found["content"]).decode("utf-8")
