# Outreach: Slack messages and Outlook meetings

Send Slack messages **as you** and book Outlook meetings (Teams link) from Telegram. Scripts do the
name matching, the time arithmetic and the sending. A model only reads a sentence or writes drafts,
one call per request. Only a command **you** type sends a plan: `/slack yes` or `/meet yes`.

## Commands

| You type | Model calls | What happens |
|---|---|---|
| `/slack send @priya @rahul: <text>` | 0 | Sent at once, your exact words, one DM each (`send group …` for one group DM) |
| `/slack schedule tomorrow 9am @priya: <text>` | 0 | Slack holds it and delivers it then (`chat.scheduleMessage`) |
| `/slack draft @a @b @c: <what each should do>` | 1 | One message per person, in your style → preview → `/slack yes` |
| `/slack <any sentence>` | 1 | "tell Priya and Rahul the review moves to Friday" → drafts → `/slack yes` |
| `/meet 15:00 30m @priya: vendor contract` | 0 | Booked at once if you are free then; otherwise shows the next free slot |
| `/meet 15:00-19:00 15m @a @b … : Q3 reviews` | 0 | 1:1s back to back from 15:00 → preview → `/meet yes` |
| `/meet <any sentence>` | 1 | "1:1s with these 10 people from 3 to 7, 15 min each, 5 min break" → preview |
| `/meet 15:00-17:00` | 1 | Finds who asked you to meet (Slack DMs, Outlook mail, last 3 days) → preview |
| `/meet allhands 16:00 60m #home: Q3 review` | 0 | One invite to everyone in #home + a post there with the Teams link → preview |
| `yes` · `yes 1,3` · `yes 1-4` · `no` · `show` · `/slack edit 2 <text>` | 0 | Approve all or some lines, cancel, show, change a draft |

Hermes' agent can do the same from plain chat through the `orchestrator:outreach` skill. It runs
`$HERMES_HOME/scripts/outreach_draft.py`, which **only saves a plan**. You still type `/slack yes`.

## How meetings are timed

`slots.pack` places meetings **back to back from the start of the window**: each meeting's own
length, then the break (`gap_minutes`, default 5). It does not spread meetings across the window, so
the time after the last meeting stays free. Your Outlook busy events are kept a break away on both
sides. Meetings that don't fit before the window ends are listed as "doesn't fit". Example: 10
people, 15:00–19:00, 15 min each → 15:00, 15:20, … 18:00–18:15.

## Which model

- Fewer than `big_from_people` (4) people: `models_small`, Flash-Lite first, then Gemma 4 (often
  overloaded on the free tier, so it is the backup).
- 4 or more people, or finding meeting requests: `models_big`, Gemini Flash-Lite first.
- A request for 30 people uses about 1–3k tokens, inside Gemma's 16K tokens per minute. Every call
  is logged in `usage/calls.jsonl` (workflow `outreach`).

## Safety

- A name that matches two people stops the whole command. Nothing goes to a guess.
- At most `daily_cap` (50) sends a day: Slack messages, invites and channel posts. A batch over the
  cap is refused whole, never cut off halfway.
- Plans expire after `preview_minutes` (30). A new plan replaces the waiting one of the same kind.
- Every send is logged in `$HERMES_HOME/brief/outreach/sent.jsonl`.
- A failed invite stops its Slack note. The other lines still go.
- Someone found only in your Outlook directory gets the invite email and no Slack note.

## Setup

- **Slack:** the user token (`SLACK_USER_TOKEN`). Its sending scopes are in the manifest in
  `../brief/LOGINS.md` §1.4.
- **Outlook:** the brief's Entra app needs delegated **Calendars.ReadWrite** and
  **User.ReadBasic.All**, with admin consent. Then sign in once more:
  `python -m orchestrator.brief auth microsoft`. The brief itself only ever asks for Mail.Read, so it
  keeps working before this step.
- **Gemini:** `GEMINI_API_KEY`, for drafts and sentences only.
- **Your wording:** `outreach.templates` in `brief.yaml` (see `brief.example.yaml`).
- **Your style:** `$HERMES_HOME/brief/outreach/style.md`, free text the draft model reads on every
  draft: when to write casual Hinglish and when clear English, what never to write, and a few
  example messages. Keep it under 6,000 characters. It stays on the host and out of this repo,
  because its examples are real workplace messages. Without it, drafts are professional and warm.
  The rules to keep every fact, date and deadline and to invent nothing are always added in code,
  so a style file cannot remove them.

## Tested

- **Fakes** (`tests/test_outreach.py`, 18 tests): packing back to back, breaks around busy events,
  overflow, clock words, send, schedule, ambiguous names, drafts with `yes 2`, edit, expiry, daily
  cap, instant booking, busy → next slot, a 5-person sentence on the Gemini chain, all-hands
  invitees and Teams link, an Outlook-only person, missing calendar consent, and that the agent's
  draft never sends. Breaking the packer and the approval guard turned 2 and 6 tests red.
- **Live, 2026-11-22:**
  - `/slack send` and `/slack schedule` to yourself both worked (0.3 s).
  - Before consent, `/meet` named the fix (AADSTS65001) and the brief kept reading mail.
  - After a new sign-in, the meeting scopes were granted: busy times and the directory lookup
    work, and the brief's Mail.Read refresh still works.
  - Not run live yet: drafts and sentences (no Gemini key in this container), and booking.
