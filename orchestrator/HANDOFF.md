# The Claude handoff: one private repo, one Claude scheduled task

Hermes can't call Claude on a Pro plan, so work for Claude goes through a private GitHub repo:
Hermes commits any input files and opens an issue labelled `hermes` whose **body is the whole task**
(what to do, the rules, where to write the answer). Hermes then starts a Claude
scheduled task (claude.ai/code → Routines) through its API trigger; Claude claims the issue, does that one job, commits its
answer and closes the issue; Hermes picks the answer up on its next run. Code: `orchestrator/handoff.py`.

There are no instruction files in the repo to copy or keep up to date: each request carries its own.
Hermes also keeps `tools/claim.sh` and `tools/close.sh` there (claim the oldest waiting issue; hand
one in: push, retrying when main moved, then close), so the prompt below has no commands to retype. They use `gh api` (REST) only: `gh issue`
needs GitHub's GraphQL API, which the task's sessions block.

Used by:
- **Studio** (`/studio make` without an Anthropic API key): two issues per video: the script and the
  direction (storyboard) in one run (Claude checks the script before it starts the storyboard; first,
  a Sonnet subagent does the web research from `research-brief.md`, so its long search results stay in
  the subagent's context; `studio.research_claude`, `studio.researcher`), then
  the custom scenes' components (`orchestrator/studio/prompts/`). Fixes come back as their own issues.
  Hermes also keeps `tools/check.py` and `tools/studio/` in the repo: the same checks Hermes runs, so
  Claude checks its own answer before handing it in.
- **Smriti** (`/notes … claude`): a document from a meeting transcript (`smriti/<id>/transcript.md`).
- **Watches** (`/watch` setup research for a new page): `watch/<n>-setup-<time>/spec.json`.

Facts below are from the Claude Code docs (code.claude.com/docs/en/routines, checked 2026-11-24; the
feature is a research preview, so recheck if something doesn't match). The docs don't say that a
GitHub-triggered session receives the issue's text, so the prompt fetches it with one command.

## Set it up once

1. **Repo:** create a private repo (e.g. `you/hermes-handoff`). Nothing to copy into it.
2. **Token for Hermes:** a fine-grained GitHub token for that repo only, with Contents and Issues
   read/write → `GITHUB_HANDOFF_TOKEN=…` in `$HERMES_HOME/.env`. Then `notes.handoff_repo: you/hermes-handoff`
   in `brief.yaml` (Watches and the Studio use the same repo unless `watch.handoff_repo` /
   `studio.handoff_repo` say otherwise).
3. **Claude GitHub App** installed on the repo (GitHub triggers need it, private repos included).
4. **The scheduled task** at claude.ai/code → Routines → New:
   - Repository: the handoff repo.
   - Trigger: **API** (Trigger → + → API → Generate token). Copy the token at once (it is shown
     only once) and put both into `$HERMES_HOME/.env`:
     `CLAUDE_ROUTINE_URL=<the Fire URL>` and `CLAUDE_ROUTINE_TOKEN=<the token>`. Hermes calls it right
     after opening each issue. **Why not only "GitHub → Issues → opened":** issues opened with the
     Claude GitHub App's own credentials never started the task (2026-11-24/25); an issue opened with
     your own fine-grained token may, but the API trigger works either way. Keeping the GitHub trigger
     too does no harm: an extra run finds nothing to do and stops. If the token leaks, Regenerate it.
   - Environment network access: **Full**, or Limited plus the sites you watch. The default Limited
     list covers GitHub and package registries, not ordinary websites, and Watches' setup research
     opens the pages you add. Smriti and the Studio need no web access.
   - Connectors: **remove them all**. Every connector's tools are sent on every step of every run;
     none of these jobs uses one.
   - Model: **Opus** for this task, picked in its model selector (leaving it on the default lets
     Claude choose; one test run on 2026-11-25 came back on Sonnet). Sonnet steps: see below.
   - Prompt: paste the one below. **If you set the task up before, replace its prompt:** the old one
     sent Claude to read `HANDOFF.md` files that no longer exist.
5. **Branch:** the prompt says "push to main"; make sure no branch protection blocks your own pushes
   to `main` in this repo.

Runs use your plan's usage like an interactive session. API fires: 100 an hour per account, and
"Run now" plus API fires share 30 an hour per task (a video takes 2–3). GitHub-event runs have their
own unpublished caps. A fire that is refused or dropped is not an error: the issue waits for the next
run (each run takes the oldest waiting issue), or press **Run now**. The fire endpoint is a beta
(`anthropic-beta: experimental-cc-routine-2026-04-01`), so its shape may change.

## What a run can see (keep sessions small)

Every model call in a run re-sends Claude Code's instructions plus the definitions of every tool the
session loads, so that fixed part is paid on every call of every run. Hermes writes
`.claude/settings.json` in the repo with each request (`SETTINGS` in `orchestrator/handoff.py`): a
`permissions.deny` list that takes out the tools no Hermes job uses (other agents, web search/fetch,
skills, scheduling, messaging, artifacts, connectors, the session tools, most GitHub tools), the
GitHub plugin and auto memory, plus the Stop hook that reports tokens. Kept: shell, file tools, and
GitHub's issue and file tools (the prompt's fallback). A bare tool name in `deny` removes the tool
from Claude's context (code.claude.com/docs/en/permissions). Measured on the same one-line test
issue: the first call went from ~46.8k to 13.7k tokens (2026-11-25; that run was served by Sonnet,
so part of the drop may be the model). A new kind of job that needs a removed tool: take it out of
`DENY` there; it applies to every job.

## Claude Sonnet for some steps

Sonnet uses less of your plan and is faster. A scheduled task has one model, so Sonnet steps go to a
second task:
1. claude.ai/code → Routines → New, same repo, environment and settings as the first, model
   **Sonnet**, API trigger → `CLAUDE_ROUTINE_SONNET_URL=` and `CLAUDE_ROUTINE_SONNET_TOKEN=` in `.env`.
2. Its prompt: the one below with step 1 changed to `sh tools/claim.sh hermes-sonnet` (and "labelled
   hermes-sonnet" in the GITHUB ERROR line). Its issues carry the label `hermes-sonnet`, so neither
   task takes the other's work.
3. `studio.claude_sonnet_steps: [animation]` (any of research, "script + direction", animation;
   fix rounds of a failed storyboard are "direction") in
   `brief.yaml`. Without the second task those steps go to the main one. Switch a step only after a
   side-by-side run shows the same quality (same checks passed, no extra fix rounds).

## The prompt to paste

```
This run started because Hermes has work for you in this repo.

1. Run: sh tools/claim.sh
   If it prints NOTHING TO DO, stop.
   If it prints GITHUB ERROR, use the GitHub tools instead: take the oldest open issue labelled
   hermes, remove that label, and read its body.
   Otherwise it prints ISSUE and a number, then the issue body. The body is your whole task.
2. Do the one job the body describes. Everything you need is in the body. Read only the files the
   body names. Do not list, open or search anything else, and do not look at earlier jobs.
3. Finish with ONE shell command: write every answer file the body names (quoted heredocs), run the
   check command the body gives (if it gives one), then, chained with &&, git add, commit, and run:
   sh tools/close.sh NUMBER (the issue number; it pushes to main, pulling first if main moved, then
   closes the issue). If the check prints problems, fix exactly those and run the same command again.
   If close.sh prints PUSH FAILED, fix that and run sh tools/close.sh NUMBER again.
4. Delete any __pycache__ folder the check made. Then stop: no summary, no comment on the issue.

Never post the job's contents anywhere else. Never write outside the folder the body names.
```
