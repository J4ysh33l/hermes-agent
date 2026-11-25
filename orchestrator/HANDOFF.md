# The Claude handoff: one private repo, one Claude scheduled task

Hermes can't call Claude on a Pro plan, so work for Claude goes through a private GitHub repo:
Hermes commits any input files and opens an issue labelled `hermes` whose **body is the whole task**
(what to do, the rules, where to write the answer). Hermes then starts a Claude
scheduled task (claude.ai/code → Routines) through its API trigger; Claude claims the issue, does that one job, commits its
answer and closes the issue; Hermes picks the answer up on its next run. Code: `orchestrator/handoff.py`.

There are no instruction files in the repo to copy or keep up to date: each request carries its own.

Used by:
- **Studio** (`/studio make` without an Anthropic API key): three issues per video, one job each: the
  script, the direction (storyboard), the custom scenes' components (`orchestrator/studio/prompts/`).
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
   - Model: pick it in the task's model selector (applies to every run). Sonnet uses less of your
     plan than Opus.
   - Prompt: paste the one below. **If you set the task up before, replace its prompt:** the old one
     sent Claude to read `HANDOFF.md` files that no longer exist.
5. **Branch:** the prompt says "push to main"; make sure no branch protection blocks your own pushes
   to `main` in this repo.

Runs use your plan's usage like an interactive session. API fires: 100 an hour per account, and
"Run now" plus API fires share 30 an hour per task (a video takes 3–4). GitHub-event runs have their
own unpublished caps. A fire that is refused or dropped is not an error: the issue waits for the next
run (each run takes the oldest waiting issue), or press **Run now**. The fire endpoint is a beta
(`anthropic-beta: experimental-cc-routine-2026-04-01`), so its shape may change.

## The prompt to paste

```
This run started because Hermes has work for you in this repo. Your task is the oldest open issue
labelled "hermes"; its body is the whole task, and nothing else in the repo is part of it.
Use only `gh api` (REST) for GitHub: `gh issue` commands need GraphQL, which is blocked here. If a
`gh api` command itself fails (an error, not an empty list), do the same step with the GitHub tools.

1. Claim it and read it with exactly this one command:
   n=$(gh api "repos/{owner}/{repo}/issues?state=open&labels=hermes&sort=created&direction=asc&per_page=1" --jq '.[0].number // empty'); [ -n "$n" ] && gh api -X DELETE "repos/{owner}/{repo}/issues/$n/labels/hermes" >/dev/null && gh api "repos/{owner}/{repo}/issues/$n" --jq '"ISSUE \(.number)\n\(.body)"' || echo "NOTHING TO DO"
   If it prints NOTHING TO DO, stop.
2. Do the one job the body describes. Everything you need is in the body. Read only the files the
   body names; do not list, open or search anything else, do not look at earlier jobs.
3. Finish with ONE shell command: write every answer file the body names (quoted heredocs), run the
   check command the body gives (if it gives one), then, chained with &&, git add, commit, push to
   main and close the issue with: gh api -X PATCH "repos/{owner}/{repo}/issues/<number>" -f state=closed >/dev/null
   If the check prints problems, fix exactly those and run the same command again.
4. Then delete any __pycache__ folder the check made, and stop. No summary, no comment on the issue.

Never post the job's contents anywhere else. Never write outside the folder the body names.
```
