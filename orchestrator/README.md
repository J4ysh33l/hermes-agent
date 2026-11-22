# orchestrator/

The workflows that replace the old bot team, built on Hermes. This folder is fork-only: it is
not upstream Hermes code and never touches Hermes' core.

## Rules

- **Scripts first, model last.** Fetching, de-duplication, filtering, formatting, sending and
  scheduling are plain scripts. A model is called only for judgment (rank, summarise), only when
  the scripts found something new, and as one batched call per job (kept under ~12k tokens so the
  Gemma fallback still fits its 16K tokens-per-minute cap).
- **Free Gemini tier only** for Hermes-side calls: Gemini 3.1 Flash-Lite, then 3.5 Flash-Lite,
  then Gemma 4. Creative, judgment-heavy and private work goes to Claude through the handoff repo.
- **Secrets live only in `~/.hermes/.env` on the host.** Never in this repo, never in chat.
- **One branch per build, a PR into the fork's own `main`.** Upstream is pinned and updated on purpose.
- **Before every push:** `orchestrator/run_checks.sh` (all tests here + the secret scan). CI runs
  the same on every PR touching this folder (`.github/workflows/orchestrator-checks.yml`).

## Layout

| Path | What |
|---|---|
| `scripts/` | Stage 1 control scripts (pause switch, status, ticket queue, Telegram control bot, usage tier, dashboard, change gate, big-file trim, output cap) and `media/`. See `scripts/README.md`. |
| `scripts/hermes_config_snippet.yaml` | Tested Hermes config additions: no-LLM quick commands, context budget, aux-model pinning. |
| `checks/secretscan.py` | Standard-library secret scanner (tokens, keys, credential file names). `secretscan: allow` on a line skips it. |
| `run_checks.sh` | Every `test_*.py` under this folder, then the secret scan. Exit non-zero on any failure. |

Each workflow will get its own folder here and ship as a Hermes profile distribution.

## Running the checks

```bash
orchestrator/run_checks.sh                 # diff base defaults to origin/main
orchestrator/run_checks.sh --base upstream/main
```

The media tests need `ffmpeg` and Pillow.
