# My day

A gamified day planner in Telegram. Tasks, bills and goals live in **Microsoft To Do** (so the To Do
phone app works too); this adds the morning card, top picks, points, levels, the streak and its
animations. **No model call anywhere**: every command is read by script.

## What you get

| When | What |
|---|---|
| 07:30 | The card: streak and level, today's tasks (overdue first), top-3 prompt, later and next 7 days, today's Outlook meetings, bills due within a week, nearest goals |
| Every 15 min | Tasks ticked in the To Do app score; bill reminders; health nudges (sends nothing when nothing is due) |
| 21:30 | Wrap-up: points today and what is still open, before the day closes at midnight |
| Last task done | 🎉 animation: the flame grows, the streak counts up |
| A day closes with tasks open | 🧊 animation at the next morning card: the streak resets |
| Every reply on Telegram | A badge: `🔥 5 · Lv 3 Doer · 340 pts` |

Commands (each answers `help`): `/day`, `/bills`, `/goals`, `/health`. Examples:

```
/day now                     /day done 1 3       /day add Call Apollo by fri !
/day top 1 2 3               /day snooze 2 fri   /day move all
/bills add HDFC card 5 25 4500   /bills paid 1
/goals add work Sign 3 hospitals by 31 dec   /goals step 1 Apollo   /goals tick 1.1
/health weight 82.4          /health food dal, rice     /health workout 30m walk
```

## Rules of the game

- **Points** (`points:` in `myday.yaml`): task 10, top pick 20, all clear 50, bill on time 15 (late 5),
  snooze −5, health log 5, goal milestone 25, goal reached 100. Each thing scores once.
- **Levels:** level n starts at 50·n·(n−1) points (0, 100, 300, 600, 1000, …), names in `level_names`.
- **Streak:** grows the moment everything due today (and overdue) is done. A day that closes with
  tasks open resets it; a day with nothing due leaves it alone. Snoozing keeps the streak but costs points.

## Bills

Each bill has a generated day and a due day of the month (`/bills add <name> <generated> <due> [amount]`;
a due day before the generated day means the next month). `/bills` shows each cycle as
`gen 5 Nov → due 25 Nov · ⏳ due in 2d`. On the generated day a To Do task `💳 Pay …` appears in your
**Bills** list, due on the due date, with a phone reminder 3 days before at 10:00. Telegram reminds you
3 days before and on the day until it is paid. Ticking it in To Do or `/bills paid` marks it paid.
No bank access: amounts are what you type.

## Data

| Where | What |
|---|---|
| Microsoft To Do | Tasks (default list), Bills, Goals · Work, Goals · Personal (lists created if missing) |
| `$HERMES_HOME/myday/state.json` | Points, streak, top picks, what was last shown (0600) |
| `$HERMES_HOME/myday/bills.json` | Your bills |
| `$HERMES_HOME/myday/health.jsonl` | Health log: on the host only, never sent to To Do or a model |
| `$HERMES_HOME/myday/anim/` | Cached animations |

## Setup

1. **Entra:** App registrations → Morning Brief → API permissions → Microsoft Graph → Delegated →
   **Tasks.ReadWrite** → Grant admin consent. Then sign in again:
   `python -m orchestrator.brief auth microsoft` (an existing login does not pick up new permissions).
2. `orchestrator/brief/install.sh` (copies `myday.example.yaml`, writes the two cron scripts).
3. The two cron jobs it prints (`myday-morning` at 07:30, `myday-tick` every 15 minutes).
4. Animations use Hermes' Telegram bot: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_HOME_CHANNEL` (or
   `TELEGRAM_ALLOWED_USERS`) in `$HERMES_HOME/.env`, which Hermes already has.

Try it on the host without Telegram: `python -m orchestrator.myday morning`, `… tick`, `… day now`.

## Tested

Against a fake To Do, calendar and Telegram (`tests/test_myday.py`): streak growth and reset,
To Do app completions, snooze, bill cycles across months and month ends, reminders once each, goals,
health scoring and nudge windows, the badge on replies and not on help, a calendar failure.
**Not yet run** against real To Do, real Telegram, or inside a running Hermes gateway.
