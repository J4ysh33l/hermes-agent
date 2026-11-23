# My day

A gamified day planner in Telegram. Tasks, bills and goals live in **Microsoft To Do** (so the To Do
phone app works too); this adds the morning card, top picks, points, levels, the streak and its
animations. **No model call anywhere**: every command is read by script.

## What you get

| When | What |
|---|---|
| 07:30 | The card: new bills found in your Gmail, streak and level, today's tasks (overdue first), top-3 prompt, later and next 7 days, today's Outlook meetings, bills due within a week |
| Every 15 min | Tasks ticked in the To Do app score; bill reminders; Sends nothing when nothing is due |
| 21:30 | Wrap-up: points today and what is still open, before the day closes at midnight |
| Sunday 21:30 | Weekly goals review: every goal with its milestones and progress |
| Last task done | 🎉 animation: a gold ring closes, the flame ignites with a glow, confetti bursts, the streak counts up under an "ALL CLEAR" pill |
| A day closes with tasks open | 🧊 animation at the next morning card: frost creeps in, the flame turns blue and dies into smoke and embers, the number cracks and falls, a calm 0 rises |
| Every reply on Telegram | A badge: `🔥 5 · Lv 3 Doer · 340 pts` |

Commands (each answers `help`): `/day`, `/bills`, `/goals`. Examples:

```
/day now                     /day done 1 3       /day add Call Apollo by fri !
/day top 1 2 3               /day snooze 2 fri   /day move all
/bills add HDFC card 5 25 4500   /bills paid 1
/goals add work Sign 3 hospitals by 31 dec   /goals step 1 Apollo   /goals tick 1.1
```

## Rules of the game

- **Points** (`points:` in `myday.yaml`): task 10, top pick 20, all clear 50, bill on time 15 (late 5),
  snooze −5, goal milestone 25, goal reached 100. Each thing scores once.
- **Levels:** level n starts at 50·n·(n−1) points (0, 100, 300, 600, 1000, …), names in `level_names`.
- **Streak:** grows the moment everything due today (and overdue) is done. A day that closes with
  tasks open resets it; a day with nothing due leaves it alone. Snoozing keeps the streak but costs points.

## Bills

Each bill has a generated day and a due day of the month (`/bills add <name> <generated> <due> [amount]`;
a due day before the generated day means the next month). `/bills` shows each cycle as
`gen 5 Nov → due 25 Nov · ⏳ due in 2d`. On the generated day a To Do task `💳 Pay …` appears in your
**Bills** list, due on the due date, with a phone reminder 3 days before at 10:00. Telegram reminds you
3 days before and on the day until it is paid. Ticking it in To Do or `/bills paid` marks it paid.

**Bills in your Gmail** are added on their own. Once a day, with the 07:30 card, every Gmail account the brief has
logged in is searched for mail of the last 40 days with "statement" or "bill" in the subject. Each
mail is read once, by script: a total amount due above zero and a due date ahead make it a
`💳 Pay …` task in **Bills** with the same reminders and points, and Telegram says
`📬 New bill in Gmail: Example Bank card ₹12,345 due 9 Dec`. The bank's statement and CRED's
mail about the same bill (same due date and amount) are added once, and a mail counts as read only
after its task is in To Do (a To Do failure retries it the next morning). Bank card statements (and
CRED's reminders) and utility bill alerts ("Biller Name: …") are read; a ₹0
statement is skipped. They are listed under `/bills` with 📬; pay with `/bills paid`, `/day done` or
in To Do. The mail text stays on the host: no model, only the task title goes to To Do.

## Data

| Where | What |
|---|---|
| Microsoft To Do | Tasks (default list), Bills, Goals · Work, Goals · Personal (lists created if missing) |
| `$HERMES_HOME/myday/state.json` | Points, streak, top picks, what was last shown, bills found in Gmail (0600) |
| `$HERMES_HOME/myday/bills.json` | Your bills |
| `$HERMES_HOME/myday/anim/` | Cached animations (MP4 with ffmpeg, else GIF) |

## Setup

1. **Entra:** App registrations → Morning Brief → API permissions → Microsoft Graph → Delegated →
   **Tasks.ReadWrite** → Grant admin consent. Then sign in again:
   `python -m orchestrator.brief auth microsoft` (an existing login does not pick up new permissions).
2. `orchestrator/brief/install.sh` (copies `myday.example.yaml`, writes the two cron scripts).
3. The two cron jobs it prints (`myday-morning` at 07:30, `myday-tick` every 15 minutes).
4. Animations use Hermes' Telegram bot: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_HOME_CHANNEL` (or
   `TELEGRAM_ALLOWED_USERS`) in `$HERMES_HOME/.env`, which Hermes already has.

Bills from Gmail use the brief's Gmail logins (`python -m orchestrator.brief auth google`); none
logged in means none read.

Try it on the host without Telegram: `python -m orchestrator.myday morning`, `… tick`, `… day now`.

## Tested

Against a fake To Do, calendar and Telegram (`tests/test_myday.py`): streak growth and reset,
To Do app completions, snooze, bill cycles across months and month ends, reminders once each, goals
and the Sunday review, bills read from Gmail mails (one bill mailed twice added once, ₹0 skipped,
each mail read once, Gmail asked once a day, a To Do failure retried), the badge on replies and not on help, a calendar failure.
Run against real To Do (`/day now`) and, read-only, against real Gmail statements (the parser).
**Not yet run** against real Telegram or inside a running Hermes gateway.
