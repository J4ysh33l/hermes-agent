# Morning brief

One Telegram message at 8:15 IST: yesterday's markets and gold, then the top items from Slack,
Gmail, Outlook and news, ranked by **one** Gemini call. `/brief more` lists everything else.

## How a run works

```
08:15 IST  Hermes cron (no-agent mode) runs $HERMES_HOME/scripts/morning_brief.py
  1. collect   Slack (your conversations), Gmail ×N, Outlook, news (each since its last good run) scripts
               Yahoo Finance: indices, India VIX, US 10Y, USD/INR, gold; IBJA India gold scripts
  2. filter    drop seen, newsletters, one-time codes, muted; money/HR mail listed, not sent;  scripts
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
Gemini free tier, which may use them to improve Google's products. Money and HR mail (receipts,
payments, payslips… by subject word or sender, `mail.private_*` in `brief.yaml`) is never sent:
the script lists its sender and subject under "💳 Money & HR". One-time codes and sign-in links
(`mail.noise_subject_patterns`) are dropped entirely.

## Telegram commands (`/brief …`, never a model call)

`/menu` lists every command this fork adds; `/brief help` (or `-help`, `--help`) lists these.

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
hermes plugins enable orchestrator
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
| Slack (user, preferred) | api.slack.com/apps → Create New App → **From a manifest** (YAML in `LOGINS.md` §1.4) → Install → copy the **User OAuth Token**. Reads every channel, DM and thread you are in: `users.conversations` + `users.list` + `search.messages` (live, 61 conversations: 4 requests, 1.2 s). | `SLACK_USER_TOKEN` (xoxp-…) |
| Slack (bot, alternative) | Same app, **Bot** token scopes `channels:read`, `groups:read`, `channels:history`, `groups:history`, `users:read`; `/invite @yourbot` per channel. Never sees DMs. Used only when no user token is set. | `SLACK_BOT_TOKEN` (xoxb-…) |
| Gmail (one or more accounts) | Google Cloud console → enable Gmail API → Google Auth Platform: External, **Publish app** (Testing logins expire in 7 days; publishing needs a home page and privacy policy URL) → Client, type **Desktop app**. Then once per account: `python -m orchestrator.brief auth google [--account work]` in a private window, paste back the address. Each account: 3 requests a run (token, list, one batch per 25 mails). | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Outlook | Entra admin center → App registrations → new (single tenant) → API permissions: Microsoft Graph **delegated** `Mail.Read` + `offline_access` → Authentication: **Allow public client flows = Yes**. Then `python -m orchestrator.brief auth microsoft` then open the printed link, sign in, and paste back the address the browser lands on. Redirect URI `http://localhost:8765/` under **Mobile and desktop applications**. Device code is not used, because security defaults block it. | `MS_CLIENT_ID`, `MS_TENANT_ID` |
| News, markets | nothing | none |

Delegated `Mail.Read` reads only your own mailbox. (An application permission would let the app
read every mailbox in the tenant; not used here.)

## Tested here vs not yet

- **Tested (fakes, `tests/test_brief.py` 23 tests + `orchestrator/tests/test_commands.py` 3):** every command answers every help word with no network; `/menu` lists them; Slack bot token reads only channels it was invited to, resolves names, skips join messages, reports a missing scope by name; IBJA history and its fallback; full run with one model call; newsletters,
  payslips and old news never reach the model; no model call when nothing is new; expired Gmail
  login is named while the rest still arrives; a failed source is re-read next run; Outlook
  token rotation is saved; model fallback on 429; unranked brief when every model fails; markets
  failure only removes markets; every `/brief` command; Indian digit grouping; US close day in
  New York time; the plugin registers `/brief`. Two guards were broken on purpose and their
  tests went red.
- **Tested live from the cloud container (2026-11-22):** Yahoo chart data for every default
  symbol, India VIX and gold; the IBJA India gold rate; all ten default news feeds; Google News RSS; Hacker News; installer, cron
  launcher and the `/brief` handler in a throwaway Hermes home.
- **Tested live with real logins (2026-11-22):** Slack user token, 61 conversations: 4 requests, 1.2 s (history per conversation was 62 calls, 7.5 s, and missed replies to older threads); Gmail paste-back login and 24 h read: 3 requests, 0.6 s (was 9, 1.8 s); filters on real mail: 9 one-time codes dropped, 3 payment/receipt mails listed without the model; Outlook paste-back login under security defaults, token rotation, and 24 h read with `internetMessageHeaders` on the list call (15 mails, 2 calls).
- **Not tested yet:** Gemini (no key here); the exact
  Gemini/Gemma model IDs (`models` command checks them); the plugin inside a running Hermes
  gateway; real Telegram rendering; Yahoo from the AWS IP.
