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
- **Every model call is logged, one line each** (`$HERMES_HOME/usage/calls.jsonl`: time, workflow,
  step, provider, model, input/output/cached/thinking tokens, ok, duration). Workflows call models
  only through `llm.py`, which logs from the counts the model returns (no extra call);
  `tests/test_rules.py` fails if any other file calls a model endpoint. Hermes' own agent turns and
  side calls are logged by the plugin's hooks. `/usage [today|week|month]` reports the split,
  free-tier headroom, paid-tier cost (`prices.yaml`) and what to trim, with no model call.
- **Every Telegram command answers `help`, `-help`, `--help`, `-h` and `?`** with its own usage,
  and is listed by `/menu` (Hermes keeps `/help` for its own commands). Add a command by adding a
  row to `commands.py`; `tests/test_commands.py` checks the rule for every row. A command calls a
  model only when you ask it to read a sentence or write drafts (`/slack draft`, `/meet <sentence>`),
  one call, through `llm.py`.
- **Before every push:** `orchestrator/run_checks.sh` (all tests here + the secret scan). CI runs
  the same on every PR touching this folder (`.github/workflows/orchestrator-checks.yml`).

## Layout

| Path | What |
|---|---|
| `scripts/` | Stage 1 control scripts (pause switch, status, ticket queue, Telegram control bot, usage tier, dashboard, change gate, big-file trim, output cap) and `media/`. See `scripts/README.md`. |
| `scripts/hermes_config_snippet.yaml` | Tested Hermes config additions: no-LLM quick commands, context budget, aux-model pinning. |
| `checks/secretscan.py` | Standard-library secret scanner (tokens, keys, credential file names). `secretscan: allow` on a line skips it. |
| `llm.py`, `usage.py`, `prices.yaml` | The one logged model client; the usage log and `/usage` report; prices and free limits. |
| `commands.py`, `plugin/` | The table of our Telegram commands and the one Hermes plugin that registers them plus `/menu`. |
| `brief/` | The morning brief (first workflow). Setup, flow and Telegram commands: `brief/README.md`. |
| `hr/` | Payslips from the monthly salary sheet, emailed from Outlook after `/hr payslip yes`; no model sees pay. `hr/README.md`. |
| `recap/` | The 20:00 deadline recap (`/recap now`): approvals waiting or expired unapproved (until redone or dropped; `/resume 2` brings one back after a safety check), HR mail with no reply, To Do tasks and bills due, calendar deadlines. No model. |
| `outreach/` | Slack messages sent as you and Outlook meetings (`/slack`, `/meet`), approved in Telegram. `outreach/README.md`. |
| `run_checks.sh` | Every `test_*.py` under this folder, then the secret scan. Exit non-zero on any failure. |

Each workflow will get its own folder here and ship as a Hermes profile distribution.

## Checklist for a new workflow

1. Scripts do everything with a fixed answer; the model only judges, once per job, only on new input.
2. Model calls go through `orchestrator.llm` with `workflow=` and `step=` set (logged automatically).
3. Its Telegram command is a row in `commands.py` with a one-line summary and a full help text
   (then `help`/`-help`, `/menu` and the no-model rule are checked by the tests).
4. Its tests run against fakes and are picked up by `run_checks.sh` (any `test_*.py`).
5. Credentials only in `$HERMES_HOME/.env`; the secret scan passes.

## Running the checks

```bash
orchestrator/run_checks.sh                 # diff base defaults to origin/main
orchestrator/run_checks.sh --base upstream/main
```

The media tests need `ffmpeg` and Pillow.
