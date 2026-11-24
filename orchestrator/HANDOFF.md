# The Claude handoff: one private repo, one Claude scheduled task

Hermes can't call Claude on a Pro plan, so work for Claude goes through a private GitHub repo:
Hermes commits the inputs and opens an issue; the **issue opened** event starts a Claude scheduled
task (claude.ai/code → Routines); Claude commits its answer and closes the issue; Hermes picks the
answer up on its next run and sends it to you on Telegram. Code: `orchestrator/handoff.py`.

Used by: Smriti (`/notes … claude`, contract `notes/HANDOFF.md`) and Watches (`/watch` setup research
for a new page, contract `watch/HANDOFF.md`; notes on changes are Gemini's, not Claude's).

Facts below are from the Claude Code docs (code.claude.com/docs/en/routines, checked 2026-11-24;
the feature is a research preview, so recheck if something doesn't match).

## Set it up once

1. **Repo:** create a private repo (e.g. `you/hermes-handoff`). Copy `notes/HANDOFF.md` to
   `smriti/HANDOFF.md` and `watch/HANDOFF.md` to `watch/HANDOFF.md` in it.
2. **Token for Hermes:** a fine-grained GitHub token for that repo only, with Contents and Issues
   read/write → `GITHUB_HANDOFF_TOKEN=…` in `$HERMES_HOME/.env`. Then `notes.handoff_repo: you/hermes-handoff`
   in `brief.yaml` (Watches use the same repo unless `watch.handoff_repo` says otherwise).
3. **Claude GitHub App** installed on the repo (GitHub triggers need it, private repos included).
4. **The scheduled task** at claude.ai/code → Routines → New:
   - Repository: the handoff repo.
   - Trigger: **GitHub → Issues → opened** on that repo. (No schedule needed.)
   - Environment network access: **Full**, or Limited plus the sites you watch. The default Limited
     list covers GitHub and package registries, not ordinary websites, and Watches' setup research
     opens the pages you add. Smriti alone needs no web access.
   - Model: pick it in the task's model selector (applies to every run). Sonnet is plenty for both
     jobs and uses less of your plan than Opus.
   - Prompt: paste the one below.
5. **Branch:** Claude pushes to `claude/…` branches unless told otherwise, and Hermes reads the
   default branch. The prompt says "commit to main"; make sure no branch protection blocks your
   own pushes to `main` in this repo.

Runs use your plan's usage like an interactive session. Documented caps are hourly (GitHub-event
runs have their own, unpublished cap); Hermes opens one issue per new plain page you watch (or
`/watch ask`) and one per `/notes … claude` request.

## The prompt to paste

```
You are the worker for my Hermes handoff repo. This session was started by a GitHub "issue opened"
event. Read that issue (use the gh CLI or the GitHub API), then:

- If it names a folder under smriti/, follow smriti/HANDOFF.md.
- If it names a folder under watch/, follow watch/HANDOFF.md.
- Anything else: comment "Not a handoff request" on the issue and stop.

Write only the file the contract names, inside that request's folder. Commit it directly to the
main branch (not a claude/ branch: my server reads main), push, then close the issue.
Never change any other file. Never post the request's contents anywhere else.
```

## Alternative trigger: the API

A task can also have an **API trigger**: `POST https://api.anthropic.com/v1/claude_code/routines/<trig_…>/fire`
with `Authorization: Bearer <the task's own token>`, `anthropic-version`, and `{"text": "…"}` (up to
65,536 characters, delivered to the prompt as a `<routine-fire-payload>` block). Hermes doesn't use it
yet: issues need no extra token and leave a visible queue. If GitHub triggers ever stop being
available, the issue body can be sent as the fire text instead.
