# Morning brief

One Telegram message at 8:15 IST: yesterday's markets and gold, then the top items from Slack,
Gmail, Outlook and news, ranked by **one** Gemini call. `/brief more` lists everything else.

## How a run works

```
08:15 IST  Hermes cron (no-agent mode) runs $HERMES_HOME/scripts/morning_brief.py
  1. collect   Slack search, Gmail, Outlook, news feeds (each since its last good run)   scripts
               Yahoo Finance: indices, US 10Y, USD/INR, gold                             scripts
  2. filter    drop seen, newsletters, finance/HR mail, muted words/senders;            scripts
               cap news per topic; fit everything into ~11k tokens
  3. rank      ONE call: Gemini 3.1 Flash-Lite → 3.5 Flash-Lite → Gemma 4               model
               (no call at all when nothing new; unranked list if every model fails)
  4. render    markets block + top items + what failed                                  scripts
  5. save      editions/YYYY-MM-DD.{json,txt}; seen ids; per-source watermarks          scripts
  stdout → Hermes delivers it to Telegram
```

A failing source never stops the brief: it is named at the bottom ("🔑 … needs a new login" for
an expired credential, "⚠️ … not included" otherwise) and is read again from its old watermark
next time, so nothing is lost.

**Privacy:** item titles and snippets from Slack (including hospital channels) and mail go to the
Gemini free tier, which may use them to improve Google's products. Finance and HR mail is
filtered out by sender and subject words before the call (`mail.exclude_*` in `brief.yaml`).

## Telegram commands (`/brief …`, never a model call)

| Command | Does |
|---|---|
| `/brief more` | every candidate item from today's brief, grouped by topic |
| `/brief topics` | topics, followed searches, watchlist, mutes |
| `/brief watch NVDA` / `unwatch` | add or remove a stock in the markets block (Yahoo symbol: `RELIANCE.NS`, `TCS.NS`, `AAPL`) |
| `/brief follow electric vehicles` / `unfollow` | add a Google News search as an extra topic |
| `/brief mute cricket` / `unmute` | drop items containing a word |
| `/brief mutesender noreply@x.com` / `unmutesender` | drop a sender |

Telegram changes go to `$HERMES_HOME/brief/prefs.json`; edit `brief.yaml` for everything else
(topic keywords, feeds, weights, markets, mail exclusions, model chain).

## Install on the host

```bash
cd ~/hermes-agent && orchestrator/brief/install.sh
hermes plugins enable brief
hermes cron create "15 8 * * *" --timezone Asia/Kolkata --no-agent \
    --script morning_brief.py --deliver telegram --name morning-brief
python -m orchestrator.brief models          # check the ranking model IDs your key can call
python -m orchestrator.brief run --dry-run   # preview; saves nothing
```

## Credentials (all in `$HERMES_HOME/.env`, never in the repo or chat)

Hermes runs cron scripts with a sanitized environment, so the brief reads `$HERMES_HOME/.env`
itself. Login tokens that the scripts refresh live in `$HERMES_HOME/brief/tokens/` (mode 0600).

| Source | Set up once | .env keys |
|---|---|---|
| Gemini | AI Studio → API key | `GEMINI_API_KEY` |
| Slack | api.slack.com/apps → new app → OAuth → **User** token scope `search:read` → install to workspace | `SLACK_USER_TOKEN` (xoxp-…) |
| Gmail | Google Cloud console → enable Gmail API → OAuth consent screen (**Internal** if the mailbox is Google Workspace; an External app left in "Testing" loses its login every 7 days) → OAuth client, type **Desktop app**. Then `python -m orchestrator.brief auth google` and paste back the address the browser lands on. | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Outlook | Entra admin center → App registrations → new (single tenant) → API permissions: Microsoft Graph **delegated** `Mail.Read` + `offline_access` → Authentication: **Allow public client flows = Yes**. Then `python -m orchestrator.brief auth microsoft` and type the code shown at microsoft.com/devicelogin. | `MS_CLIENT_ID`, `MS_TENANT_ID` |
| News, markets | nothing | none |

Delegated `Mail.Read` reads only your own mailbox. (An application permission would let the app
read every mailbox in the tenant; not used here.)

## Tested here vs not yet

- **Tested (fakes, `tests/test_brief.py`, 21 tests):** full run with one model call; newsletters,
  payslips and old news never reach the model; no model call when nothing is new; expired Gmail
  login is named while the rest still arrives; a failed source is re-read next run; Outlook
  token rotation is saved; model fallback on 429; unranked brief when every model fails; markets
  failure only removes markets; every `/brief` command; Indian digit grouping; US close day in
  New York time; the plugin registers `/brief`. Two guards were broken on purpose and their
  tests went red.
- **Tested live from the cloud container (2026-11-22):** Yahoo chart data for every default
  symbol and gold; all ten default news feeds; Google News RSS; Hacker News; installer, cron
  launcher and the `/brief` handler in a throwaway Hermes home.
- **Not tested yet:** real Slack, Gmail, Outlook and Gemini (no credentials here); the exact
  Gemini/Gemma model IDs (`models` command checks them); the plugin inside a running Hermes
  gateway; real Telegram rendering; Yahoo from the AWS IP; whether Graph returns
  `internetMessageHeaders` on the message list (newsletter detection in Outlook also uses
  Focused/Other, so it still works without it).
