# Logins for the morning brief: Slack, Gmail (3 accounts), Outlook

Checked against Slack's, Google's and Microsoft's own docs on 2026-11-22. Each fact has its
source link in Part 4. Nothing here has been tried against your real accounts yet.

**Labels used below**
- **Works today:** the current code already does this.
- **Needs a code change:** the step is correct for the API, but our script doesn't do it yet.

**Gemini calls:** every source below feeds into the **same single Gemini call**. Slack, the three
Gmail accounts, Outlook and the news are collected by scripts, merged, filtered, and then ranked
once. Adding more accounts or channels adds API calls to Slack, Google and Microsoft. Those are
free. It never adds Gemini calls.

---

## Part 1: Slack

### 1.1 Why the old setup only got channels, and was slow

I checked our current code (`orchestrator/brief/sources/slack.py`) against Slack's docs. There
are four separate causes.

1. **A bot token can never see your DMs.** A bot (`xoxb-`) reads only the channels it was
   invited to. DMs between you and other people are invisible to it. That is why only channels
   came back. **Fix:** use a *user* token (`xoxp-`). It sees exactly what you see.
2. **Thread replies were never fetched.** `conversations.history` gives the top-level messages
   of a channel. Replies inside a thread need a separate `conversations.replies` call per
   thread. Our bot path never makes that call (`slack.py:95`).
3. **The slowness was probably the app type, not the number of channels.** Since 2025, Slack
   throttles *commercially distributed apps that are not in the Slack Marketplace*:
   `conversations.history` and `conversations.replies` drop to **1 call a minute, 15 messages
   per call**. At that rate, 30 conversations take about 30 minutes. If grokbot used a
   third-party or distributed app, that explains it. **Internal apps are exempt.** An app you
   create inside your own workspace keeps **50+ calls a minute and up to 999 messages per
   call**. Slack's FAQ says: "internal customer-built apps are not impacted and retain their
   current, higher rate limits."
4. **The user-token path uses `search.messages`, which Slack now calls "legacy".** It also
   has a small bug in our code. For a DM, the result has `type: "im"` and the channel "name"
   is the other person's user ID. There is no `is_im` field. Our code checks `is_im`
   (`slack.py:61`), so DMs would show up as `#U0ABC123` instead of "DM: Priya".

### 1.2 How 20 channels + 10 DMs come back: about 35 small calls, under a minute

Use a user token with read scopes and these steps. **Needs a code change:** today the user
token only runs the search path.

| Step | Call | How many | What you get |
|---|---|---|---|
| 1 | `users.conversations` with `types=public_channel,private_channel,mpim,im`, `limit=999` | **1** | Every conversation *you are a member of*: 20 channels, 10 DMs and any group DMs. Each has its **ID**, and channels also have their **name**. A DM has `user` = the other person's ID. |
| 2 | `users.list` (or `users.info` for just the people you DM) | 1–2 | Turns user IDs (`U…`) into names. Cache it in a file and refresh it weekly. |
| 3 | `conversations.history` with `channel=<id>`, `oldest=<last run's time>` | **30** (one per conversation) | Every new top-level message since the last brief. If nothing is new, the reply is tiny. |
| 4 | `conversations.replies` with `channel`, `ts=<thread>`, `oldest=<last run>` | only for messages from step 3 where `reply_count > 0` and `latest_reply` is newer than the last run | The new replies in active threads. Usually 0–10 calls. |
| 5 | `search.messages` with `query="is:thread after:<yesterday>"` | 1–2 | Catches **new replies to threads that started before the last run**. Step 3 cannot see those, because the thread's first message is older than `oldest`. |

- **Total:** about 35–45 calls. All of them are Tier 3 (50+ a minute) except search (Tier 2,
  20 a minute). That's roughly 10–30 seconds with **no fixed sleep**. Only wait when Slack
  answers `429` and says how long in `Retry-After`.
- **The 1.3-second pause can go.** It is in our code today (`slack.py:26`).
- **For step 5, instead of the legacy search:** Slack's Real-time Search API
  (`assistant.search.context`) has been available to internal apps since Feb 2026. But it
  returns only 20 results per call and allows about 10 calls a minute. It's fine as a backup
  for step 5, but too slow to collect everything.

### 1.3 IDs, not names: how to tell #core from #home

Slack stores everything by ID. The first letter tells you what it is:

| Prefix | Meaning |
|---|---|
| `C…` | Channel (public, or private since 2021) |
| `G…` | Private channel created before 2021, or an older group DM |
| `D…` | Direct message with one person |
| `U…` / `W…` | A person (`W` on Enterprise) |
| `B…` | A bot |
| `T…` | The workspace |

How we make sense of the IDs:

1. **Names come free with step 1.** `users.conversations` returns the ID and the current name
   of every channel together. So each run, the script rebuilds an `ID → name` table at no
   extra cost.
2. **A DM has no name.** It carries `user: U0ABC123`. Look that ID up in the `users.list`
   cache (step 2) and you get "DM: Priya Sharma".
3. **A group DM's name** looks like `mpdm-priya--rahul--you-1`. Show the member names
   instead.
4. **You name the groups, by channel name, in `brief.yaml`.** Slack has **no public API for
   your sidebar sections**: `users.channelSections` is not documented and its page returns
   404. So "Core" and "Home" must be written down once in the config. **Needs a code change.**
   Example:

   ```yaml
   slack:
     groups:                       # your words, Slack channel names (no '#')
       Core: [core-team, product, leadership]
       Hospital: [icu-ops, opd-alerts]
       Home: [family, house-admin]
     dm_group: People              # all 1:1 and group DMs land here
     other_group: Other channels   # any channel you didn't list
     weights: {Core: 2, Hospital: 1.5, People: 2, Home: 1, Other channels: 0.5}
   ```

5. **The script stores the IDs.** On every run it matches these names to IDs and saves the
   pairs. If someone **renames** `#core-team` to `#core`, the ID doesn't change. The script
   then notices that the name it knows (`core-team`) now points to an ID whose name is `core`,
   and warns you in the brief: "Slack: #core-team is now #core, update brief.yaml". Nothing is
   silently lost.
6. **What goes to Gemini** is one compact block per conversation, already labelled:
   `[Core] #product — 7 new (Rahul ×4, Priya ×3): …`. The model never sees an ID.

### 1.4 Step by step: create the Slack app and get the user token

1. Open **https://api.slack.com/apps** in a browser where you're signed in to the right
   workspace.
2. Click **Create New App**, then **From a manifest**.
3. Pick your workspace, then **Next**.
4. Choose the **YAML** tab, delete what's there, and paste this:

   ```yaml
   display_information:
     name: Morning Brief (personal)
     description: Reads my channels and DMs once a day for my own summary
   oauth_config:
     scopes:
       user:
         - channels:read
         - channels:history
         - groups:read
         - groups:history
         - im:read
         - im:history
         - mpim:read
         - mpim:history
         - users:read
         - users:read.email
         - search:read
         - chat:write
         - im:write
         - mpim:write
   settings:
     org_deploy_enabled: false
     socket_mode_enabled: false
     token_rotation_enabled: false
   ```

   - These are all **user** scopes and there is no bot user, so the app reads *as you*.
   - `search:read` is only for step 5.
   - The last four scopes are for **sending** messages as you (Part 5):
     - `users:read.email`: find a colleague by email
     - `chat:write`: post and schedule messages
     - `im:write`: open a 1:1 DM
     - `mpim:write`: open a group DM
   - If you already installed the app without them, add them under **OAuth & Permissions →
     User Token Scopes**. Then click **Reinstall to <workspace>** and copy the new `xoxp-`
     token.
   - `token_rotation_enabled: false` keeps the token from expiring every 12 hours.
5. Click **Next**, check the summary, then **Create**.
6. In the left menu, open **OAuth & Permissions** and click **Install to <workspace>**.
   - If your workspace requires approval, it shows **Request to Install**. As an admin you
     approve it yourself under *Manage apps*.
7. Slack shows a permission screen listing what the app can read. Click **Allow**.
8. Back on **OAuth & Permissions**, copy the **User OAuth Token**. It starts with `xoxp-`.
   - **Do not paste it into chat.**
9. On the host, add it to `$HERMES_HOME/.env`:
   ```
   SLACK_USER_TOKEN=xoxp-...
   ```
   Remove any `SLACK_BOT_TOKEN` line. If both are set, our code uses the bot token.
10. Check that the token works. Both commands read the token from `.env`, so it never appears
    on screen:
    ```bash
    set -a; . "$HERMES_HOME/.env"; set +a
    curl -s -H "Authorization: Bearer $SLACK_USER_TOKEN" https://slack.com/api/auth.test
    ```
    You should see `"ok":true` with your user and team name. Then:
    ```bash
    curl -s -H "Authorization: Bearer $SLACK_USER_TOKEN" \
      "https://slack.com/api/users.conversations?types=public_channel,private_channel,mpim,im&limit=999" \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error') or len(d['channels']), 'conversations')"
    ```
    It should print about 30.

**Don't use:**
- **Admin tokens.** The Admin and Discovery APIs need an Enterprise plan, and Discovery is
  only allowed for compliance work (eDiscovery, archiving, DLP).
- **The old bot token** for this job. It can't see DMs.
- **The Slack CLI** (`slack login`, `slack create`, `slack run`) and the Bolt starter
  templates. They build a Socket Mode bot that runs on your PC. That bot crashes without an
  app-level token, and `slack run` **replaces the app's manifest** with the template's. Our
  script calls the Web API with the `xoxp-` token and needs none of that.
- **The only value our script needs** is the **User OAuth Token** (`xoxp-…`), shown under
  **OAuth & Permissions** after installing. These are *not* needed:
  - Client ID and Client Secret
  - Signing Secret
  - Verification Token
  - App-level tokens

**Slack's terms (Oct 2025):** they ban training models on API data and bulk export. They also
stop *third-party providers* from building lasting archives of *other organizations'* data.
Reading your own workspace with your own internal app and sending a daily summary to an LLM is
not banned by any clause I found. That is my reading, not Slack's statement. Also, the hospital
channel text still goes to the Gemini free tier, as you already accepted.

---

## Part 2: Gmail, three personal accounts

### 2.1 Pick one of three routes

| Route | Setup | Read-only? | Token life | Recommended |
|---|---|---|---|---|
| **A. One Google Cloud app, "In production", 3 logins** | 1 project, 1 client, 3 sign-ins | Yes (`gmail.readonly`) | Until you revoke it, change the password, or don't use it for 6 months | **Yes** |
| B. "Personal mode" app | 3 projects (each works only for the account that made it) | Yes | No 7-day limit, no warning screen | Only if route A's warning screen bothers you. Google lists a Developer Preview requirement, which is unconfirmed. |
| C. Forward accounts 2 and 3 into account 1 | Gmail settings only, 1 login | Yes | Same as A | Simplest. But tabs (Primary/Promotions) are recalculated, and links open the forwarded copy. |

Two routes are ruled out:
- **IMAP with app passwords:** an app password gives *full* access to the mailbox, not
  read-only.
- **Gmail's "Check mail from other accounts" (POP):** Google is removing it, completely by
  January 2027.

### 2.2 Route A: step by step

Do steps 1–9 once, signed in as **the account you want to own the project** (say account 1).

1. Go to **https://console.cloud.google.com**.
2. Open the project picker at the top, then **New project**. Name it `morning-brief`, then
   **Create**. Make sure it is selected at the top.
3. Go to **☰ Menu → APIs & Services → Library**. Search **Gmail API**, open it, and click
   **Enable**.
4. Go to **☰ Menu → Google Auth platform → Branding**. If you see *"Google Auth platform not
   configured yet"*, click **Get started** and fill in:
   - **App information:** app name `Morning Brief`, user support email = your address. Click
     **Next**.
   - **Audience:** **External** (Internal is only for Google Workspace companies). Click
     **Next**.
   - **Contact information:** your email. Click **Next**.
   - On **Branding** afterwards:
     - **Developer contact information → Email addresses** must be filled in. If it's empty,
       **Publish app** stays greyed out with "complete your configuration on the Branding
       page".
     - **Do not upload a logo.** A logo forces Google verification.
     - Click **Save** at the bottom of Branding, then reload **Audience**.
     - If **Publish app** is still grey, hover over it. Google's tooltip may ask for an
       **Application home page** and an **Application privacy policy link** before an External
       app can go to production. These must be real public pages on a domain you add under
       **Authorised domains**.
     - Several developers report that placeholder links don't work.
     - Options for the pages:
       - two plain pages on a domain you control
       - GitHub Pages on your account
   - **Finish:** tick the box agreeing to the Google API Services User Data Policy, then
     **Continue → Create**.
5. Go to **Google Auth platform → Data Access**.
   - Click **Add or remove scopes** and search `gmail.readonly`.
   - Tick `https://www.googleapis.com/auth/gmail.readonly`, then **Update → Save**.
   - It will be listed under *Restricted scopes*. That's expected.
6. Go to **Google Auth platform → Audience → Test users → Add users**. Add all three Gmail
   addresses, then **Save**. Test users only matter while the app is in Testing, but adding them
   does no harm.
7. Go to **Google Auth platform → Clients → Create client**.
   - **Application type:** **Desktop app**.
   - **Name:** `morning-brief-host`.
   - Click **Create**.
   - **Copy the Client ID and Client secret now**, or download the JSON. Google shows the full
     secret only once. Afterwards it shows just the last 4 characters, and you'd have to add a
     new secret.
8. Go to **Google Auth platform → Audience** and under *Publishing status* click
   **Publish app → Confirm**.
   - The status becomes **In production**.
   - Google says *verification needed*. **Do not submit for verification.** Google's own
     guidance says apps used only by you, or by a few people you know, can skip it.
   - What you accept instead: a "Google hasn't verified this app" screen at each sign-in, and
     a lifetime cap of 100 users. You need 3.
   - **Why this step matters:** if you leave it in *Testing*, every login dies after **7 days**.
     That is the expiry problem from last time.
   - **Only one account does steps 1–8:** the one that owns the project. The other two Gmail
     accounts never open the Cloud console. Each just signs in once (steps 10–16).
9. On the host, add to `$HERMES_HOME/.env`:
   ```
   GOOGLE_CLIENT_ID=....apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=GOCSPX-...
   ```

Then sign in **once per account**.
- **Works today for one account only:** `auth google` saves to a single file,
  `tokens/google.json`. A second run overwrites the first.
- **Needs a code change for 3 accounts:** the command would take a label, for example
  `auth google --account personal`. It would send Google `login_hint=<email>` so the right
  account is preselected, and save to `tokens/google-personal.json`.

Each sign-in goes like this:

10. On the host, run the auth command. It prints a long link.
11. Open the link in a **private/incognito window**, or one where only that account is signed
    in. That way you can't approve with the wrong account.
12. Sign in to that Gmail account.
13. Google warns **"Google hasn't verified this app"**. Click **Advanced**, then **Go to
    Morning Brief (unsafe)**. It's your own app.
14. On the permissions screen, **tick the box "View your email messages and settings"**. Google
    shows each permission as a separate checkbox. If you skip it, the login "works" but every
    read fails with `403 insufficient permissions`. Then click **Continue**.
15. The browser lands on a page that fails to load (`localhost:8765/?code=…`). That's
    expected. Copy the **whole address** from the address bar and paste it into the host's
    prompt.
16. The host prints "Gmail login saved". Repeat steps 10–15 for accounts 2 and 3.

**What ends a login:**
- You remove the app at myaccount.google.com → Security → Third-party connections.
- You **change that account's password**. Gmail logins die on a password change.
- 6 months with no use.
- The app is put back into *Testing*.
- An unused client is deleted after 6 months, with an email 30 days before. Not an issue for a
  daily job.

When a login ends, the brief already says "🔑 Gmail needs a new login".

### 2.3 Fetching three inboxes with the fewest calls

- **Works today:** 1 list call, then **1 call per email** (`gmail.py:44-46`). That is the N+1
  pattern: 50 emails means 51 calls per account.
- **Better (needs a code change):** for each account:
  1. 1 token refresh.
  2. 1 `messages.list` with `q="after:<epoch> -category:promotions -category:social
     -category:forums"`. It returns only IDs.
  3. **1 batch request** to `https://www.googleapis.com/batch/gmail/v1` holding up to 50
     `messages.get?format=metadata` calls. Google: max 100 per batch, recommends ≤50.
  4. That's **3 HTTP requests per account, 9 for all three.** Each still counts as separate
     calls against quota, but the quota is very large: 6,000 units a minute per account,
     against 5 per list and 20 per get.
- **Alternative:** `history.list` from a saved `historyId` (2 units). It returns only what's
  new since last time. It needs a fallback to `messages.list` when Google returns `404`, which
  happens if the saved ID is more than about a week old.
- All three accounts merge into the same item list, labelled `Gmail (personal)`,
  `Gmail (work-alias)` and so on. **Still one Gemini call.**
- **Links:** each item needs a link that opens in the right account. `…/mail/u/?authuser=<email>#all/<id>`
  is widely used but not officially documented, so test it once.

---

## Part 3: Outlook (your Microsoft 365 work mailbox)

### 3.0 First, the likely reason you got stuck last time

Our login uses Microsoft's **device code** sign-in: open microsoft.com/devicelogin and type a
code. Microsoft now blocks that sign-in in two ways.

- **Security defaults:** "After security defaults are enabled in your tenant, authentication
  requests that use device code flow are blocked." Every new tenant since 1 July 2026 has
  this.
- **A Microsoft-managed Conditional Access policy, "Block device code flow"**, which Microsoft
  creates in Report-only mode and **switches on by itself after 30 days or more**. It applies
  to tenants with Entra ID P2 or M365 Business Premium.

Check which one applies (2 minutes):
1. Go to **https://entra.microsoft.com → Entra ID → Overview → Properties → Manage security
   defaults**. If it says **Enabled**, device code is blocked.
2. Go to **Entra ID → Conditional Access → Policies**. This is the **Policies** item in the
   left menu, *not* "Policy plans (Preview)". Look for **Block device code flow** with
   **Created by = Microsoft**, and see whether it is **On**.
   - If the list is empty, Conditional Access isn't blocking you.
   - Conditional Access needs Entra ID P1/P2 or Business Premium, and can't be used while
     security defaults are on. In that case step 1 is the one that matters.
3. Sign-in logs: type **Sign-in logs** in the search box at the top of the portal. Or go to
   **Entra ID → Monitoring & health → Sign-in logs**.
   - Free tenants keep only 7 days of logs, so last week's attempt may be gone. The quick
     test below is easier.
   - Add the filter **Authentication protocol = Device code**.
   - Open the failed attempt from last time. The **Conditional Access** tab names the policy
     that blocked it.
   - The error codes are `AADSTS530035` (security defaults) and `AADSTS53003` (Conditional
     Access).

**Quick test from Windows PowerShell (2 minutes, no host needed).**
- Needs the app from 3.1 steps 1–5.
- It tries exactly the sign-in our script uses and prints either "sign-in works" or
  Microsoft's error. It never prints the token.
- Fill in the two IDs from the app's **Overview** page:

```powershell
$tenant = "<Directory (tenant) ID>"
$client = "<Application (client) ID>"
$dc = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/$tenant/oauth2/v2.0/devicecode" -Body @{client_id=$client; scope="offline_access Mail.Read"}
$dc.message
while ($true) {
  Start-Sleep -Seconds $dc.interval
  try {
    $null = Invoke-RestMethod -Method Post -Uri "https://login.microsoftonline.com/$tenant/oauth2/v2.0/token" -Body @{grant_type="urn:ietf:params:oauth:grant-type:device_code"; client_id=$client; device_code=$dc.device_code}
    "OK: device-code sign-in works for this app"; break
  } catch {
    $err = $_.ErrorDetails.Message | ConvertFrom-Json
    if ($err.error -ne "authorization_pending") { $err.error_description; break }
  }
}
```

Reading the result:
- **"OK"**: device code is not blocked. Continue with 3.1 step 8.
- **`AADSTS530035`**: security defaults are blocking it.
- **`AADSTS53003`**: a Conditional Access policy is blocking it.
- **`AADSTS7000218`**: "Allow public client flows" is off (3.1 step 4).
- **`AADSTS700016`** or **`AADSTS90002`**: one of the two IDs is wrong.

**Medoc's tenant (checked 2026-11-22): security defaults are Enabled, so device code is
blocked.** Use the paste-back (authorization code + PKCE) login below.

**What to do about it.** Don't turn security defaults off: that removes MFA protection for
your whole company. Choose one:
- **Recommended (needs a code change):** switch our Outlook login to the same paste-back flow
  Gmail uses. That is "authorization code with PKCE", with redirect `http://localhost:8765/`.
  No policy blocks it.
- **Works today, only if it's a CA policy:** in that policy, under **Users → Exclude**, add
  only yourself. Or exclude just this app under **Target resources**. If it's security
  defaults, this option doesn't exist.

### 3.1 Register the app (step by step)

1. Go to **https://entra.microsoft.com** and sign in as the admin.
2. Go to **Entra ID → App registrations → New registration**.
   - **Name:** `Morning Brief`.
   - **Supported account types:** **Single tenant only – <your company>**. On the older
     screen this reads "Accounts in this organizational directory only".
   - **Redirect URI:**
     - *Device code (today's code):* leave it **empty**.
     - *Paste-back flow (recommended change):* choose platform **Public client/native (mobile
       & desktop)** and enter `http://localhost:8765/`.
   - Click **Register**.
3. On the **Overview** page, copy:
   - **Application (client) ID**, which goes in `MS_CLIENT_ID`
   - **Directory (tenant) ID**, which goes in `MS_TENANT_ID`. Use this ID, **not**
     "common". A single-tenant app on `/common` fails with `AADSTS50194`.
4. Go to **Authentication** and find **Allow public client flows**. It's on the **Settings**
   tab in the new layout, or under **Advanced settings** in the old one. Set it to
   **Enabled / Yes** and click **Save**.
   - **This is the step most often missed.** Without it, sign-in fails with `AADSTS7000218 …
     must contain 'client_assertion' or 'client_secret'`.
5. Go to **API permissions → Add a permission → Microsoft Graph → Delegated permissions**:
   - Search `Mail.Read` and tick **Mail.Read**. Don't use *Mail.ReadBasic*: it hides the
     message preview we need.
   - Under **OpenId permissions**, tick **offline_access**. That's what gives a login that
     lasts.
   - Click **Add permissions**. `User.Read` is already there; leave it.
6. Click **Grant admin consent for <your company> → Yes**. Neither permission strictly
   requires an admin, but this skips the consent prompt and the "Need admin approval" screen
   (`AADSTS90094`/`90095`).
7. **Do not** add *Application* permissions such as Mail.Read (Application). Those let an app
   read *every* mailbox in the company.
8. On the host, add to `$HERMES_HOME/.env`:
   ```
   MS_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
   MS_TENANT_ID=yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
   ```
9. Sign in:
   - **Works today:** run `python -m orchestrator.brief auth microsoft`. It prints a code.
     On your phone, open **microsoft.com/devicelogin**, type the code, sign in with your work
     account, complete MFA and accept. The host prints "Outlook login saved". If you get
     `AADSTS530035` or `AADSTS53003`, go back to 3.0.
10. Test without saving anything: `python -m orchestrator.brief run --dry-run`.

**Error codes**

| Code | Meaning | Fix |
|---|---|---|
| `AADSTS7000218` | App treated as needing a secret | Step 4: public client flows on |
| `AADSTS700016` | App not found | Wrong client ID or tenant ID |
| `AADSTS90002` / `50059` | Tenant not found | Wrong `MS_TENANT_ID` |
| `AADSTS50194` | `/common` used with a single-tenant app | Put the tenant GUID in `.env` |
| `AADSTS50020` | Signed in with an account outside the tenant | Use your work account |
| `AADSTS65001` | No consent | Step 6, or sign in again |
| `AADSTS50076` / `50079` | MFA needed / MFA not registered | Finish MFA in the browser |
| `AADSTS530035` / `53003` | Blocked by security defaults / Conditional Access | Section 3.0 |
| `AADSTS700082` | Refresh token unused for 90 days | Sign in again |
| `AADSTS70016` | "Authorization pending" | Normal while waiting; ignore |

**How long the login lasts:** the refresh token expires after **90 days of no use** and has
no maximum age. It is **replaced on every use**, and our code saves the new one each run
(`pipeline.py:43`). So a daily brief keeps it alive indefinitely, until a password change or a
policy change.

### 3.2 Calls per run

**Works today:** **2 HTTP requests**, no matter how many emails.
1. One token refresh.
2. One `GET /me/mailFolders/inbox/messages` with:
   - `$filter=receivedDateTime gt …`
   - `$orderby=receivedDateTime desc`, which is allowed because the same property comes first
     in `$filter`
   - `$select=…`, which returns subject, sender, a 255-character preview and the
     Focused/Other tag in the same response
   - `$top=50`

Things to know:
- **More than 50 emails:** follow `@odata.nextLink` (needs a code change: we read only the
  first page).
- **`internetMessageHeaders` in a list call:** Microsoft documents it only on single-message
  GETs. If the first real run returns a `400`, remove it from `$select`. Newsletter detection
  still works through Focused/Other.
- **Alternative:** a **delta query**, `/me/mailFolders/inbox/messages/delta`. It returns
  "what changed since last time" via a saved `@odata.deltaLink`. It needs a fallback when
  Microsoft answers `syncStateNotFound` or `410`. It's not needed at one run a day.
- **`$batch`** (max 20 per batch) is pointless here: we already make one call.
- **Limits** (10,000 requests per 10 minutes per mailbox, 4 at once) are far above our needs.

---

## Part 4: How these APIs work, with references

### 4.1 One run, all sources

| Source | HTTP requests per run | Grows with | Model calls |
|---|---|---|---|
| Slack (user token, design in 1.2) | ~35–45 | number of conversations and active threads | 0 |
| Gmail × 3 (batched) | ~9 | accounts only | 0 |
| Outlook | 2 | nothing | 0 |
| News + markets | ~25 | number of feeds | 0 |
| **Ranking** | **1 Gemini call** | nothing: input capped at ~11–12k tokens | **1** |

Keeping it to one Gemini call when there's a lot of input:
- The scripts compress before the call: one line per conversation or email, threads as
  "parent + N replies + last 2", newsletters and seen items dropped.
- If there's still too much, lower-weight groups get trimmed first.
- The model only ranks and summarises. The full list stays available through `/brief more`
  without a model call.

### 4.2 Slack, the main ideas

- **Token types:**
  - *Bot* (`xoxb`): acts as the app, sees only channels it was invited to.
  - *User* (`xoxp`): acts as you, sees everything you see, DMs included.
  - *Admin*: Enterprise only, and doesn't read messages.
- **Everything is by ID.** Names are display data that can change. Join them yourself:
  `users.conversations` gives channel IDs and names, `users.list`/`users.info` gives people.
- **Rate limits are per method, per workspace, per app.** Tier 2 = 20+ a minute, Tier 3 = 50+,
  Tier 4 = 100+. A `429` comes with `Retry-After` in seconds.
- **Pagination:**
  - `conversations.*` and `users.*` use a cursor: `response_metadata.next_cursor` goes back as
    `cursor`.
  - `search.messages` uses pages: `page` and `count`, each up to 100.
- **Threads:** a message with `thread_ts == ts` is a thread parent. `reply_count` and
  `latest_reply` say whether there's anything new. The replies come from
  `conversations.replies`.
- **Unread:** `conversations.info` returns `last_read` and `unread_count` for **DMs** (it's
  unconfirmed for channels). It could later power "only what you haven't read".
- **Links:** `https://<team>.slack.com/archives/<channelID>/p<ts without the dot>`. For a
  thread reply, add `?thread_ts=<parent ts>&cid=<channelID>`. `chat.getPermalink` returns the
  same thing at one call per message.

References:
- Rate limits: https://docs.slack.dev/apis/web-api/rate-limits
- 2025 throttle for non-Marketplace apps (internal apps exempt): https://docs.slack.dev/changelog/2025/05/29/rate-limit-changes-for-non-marketplace-apps and https://docs.slack.dev/changelog/2025/06/03/rate-limits-clarity/
- users.conversations: https://docs.slack.dev/reference/methods/users.conversations
- conversations.history: https://docs.slack.dev/reference/methods/conversations.history
- conversations.replies: https://docs.slack.dev/reference/methods/conversations.replies
- conversations.info: https://docs.slack.dev/reference/methods/conversations.info
- Threads and message retrieval: https://docs.slack.dev/messaging/retrieving-messages
- Conversation object (IDs, `user` on DMs, `last_read`): https://docs.slack.dev/reference/objects/conversation-object
- search.messages (legacy; DM `channel.name` = user ID): https://docs.slack.dev/reference/methods/search.messages
- Real-time Search API: https://docs.slack.dev/apis/web-api/real-time-search-api/ and https://docs.slack.dev/reference/methods/assistant.search.context/
- Slack MCP server: https://docs.slack.dev/ai/slack-mcp-server/
- Search modifiers (`in:`, `from:`, `is:thread`, `after:`): https://slack.com/help/articles/202528808-Search-in-Slack
- Permalinks: https://docs.slack.dev/reference/methods/chat.getPermalink
- API terms (Oct 2025): https://slack.com/terms-of-service/api
- Discovery API (Enterprise, compliance only): https://slack.com/help/articles/360002079527

### 4.3 Gmail, the main ideas

- **OAuth app states:**
  - *Testing:* 100 named test users, logins die after 7 days.
  - *In production, unverified:* a warning screen and a lifetime cap of 100 users, but logins
    last.
  - *Personal mode:* the creator's account only.
- **One client, many accounts.** Each account gets its own refresh token. A client can hold up
  to 100 per account; beyond that the oldest is silently dropped.
- **No device-code login for Gmail.** Google's device flow excludes Gmail scopes. That's why
  we use the localhost paste-back flow (loopback + PKCE). The old copy-a-code ("OOB") flow is
  dead for production apps.
- **`messages.list` returns only IDs.** Details come from `messages.get`. `format=metadata`
  plus `metadataHeaders` keeps the response small; `snippet` and `internalDate` (in ms) give
  the preview and the time.
- **Batching:** up to 100 calls per HTTP request (≤50 recommended). Each still counts as a
  separate call for quota.
- **Quota units:** list 5, get 20, history.list 2. The limit is 6,000 a minute per account per
  project.
- **Incremental sync:** `history.list` from a saved `historyId`. IDs last "at least a week,
  often longer". A `404` means do a full sync.
- **Search syntax in `q`:** same as the Gmail search box. `after:<epoch seconds>` is exact; a
  plain date means midnight Pacific time. `-category:promotions` excludes a tab.

References:
- OAuth overview (7-day Testing expiry, 100-token limit, what revokes): https://developers.google.com/identity/protocols/oauth2
- Desktop/loopback flow, `login_hint`: https://developers.google.com/identity/protocols/oauth2/native-app
- Device flow allowed scopes (no Gmail): https://developers.google.com/identity/protocols/oauth2/limited-input-device
- OOB deprecation: https://developers.google.com/identity/protocols/oauth2/resources/oob-migration
- Consent screen setup: https://developers.google.com/workspace/guides/configure-oauth-consent
- Create Desktop client: https://developers.google.com/workspace/guides/create-credentials
- Publishing status, user cap, Personal mode: https://support.google.com/cloud/answer/15549945, https://support.google.com/cloud/answer/7454865, https://support.google.com/cloud/answer/13464323
- Client secrets shown once, unused-client deletion: https://support.google.com/cloud/answer/15549257
- Restricted scope verification, personal-use exemption: https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification
- Gmail scopes (readonly and metadata are both Restricted): https://developers.google.com/workspace/gmail/api/auth/scopes
- Batching: https://developers.google.com/workspace/gmail/api/guides/batch
- Quota: https://developers.google.com/workspace/gmail/api/reference/quota
- Sync with history: https://developers.google.com/workspace/gmail/api/guides/sync
- messages.list: https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list
- Search filtering (`after:` epoch): https://developers.google.com/workspace/gmail/api/guides/filtering
- Search operators: https://support.google.com/mail/answer/7190
- POP / Check-mail-from-other-accounts removal: https://support.google.com/mail/answer/17101213
- App passwords: https://support.google.com/accounts/answer/185833
- Forwarding: https://support.google.com/mail/answer/10957

### 4.4 Microsoft Graph, the main ideas

- **Delegated vs application permissions.** Delegated = the app acts as you and sees only
  your mailbox. Application = the app acts as itself, can see the whole tenant, and needs
  admin consent. We use delegated.
- **Public vs confidential client.** A script on a server with no secret is a *public* client,
  so "Allow public client flows" must be on.
- **Sign-in flows:**
  - *Device code:* type a code on another device. It's being blocked by default now.
  - *Authorization code + PKCE:* browser and redirect. This is the recommended replacement.
- **Tokens:** an access token lasts about 1 hour. The refresh token lasts 90 days of
  inactivity, is replaced on each use, and has no maximum age.
- **OData query options:** `$select`, `$filter`, `$orderby`, `$top` and `@odata.nextLink`.
  `$orderby` properties must appear first in `$filter`, otherwise Graph returns
  `InefficientFilter`.
- **Delta query:** one `deltaLink` per folder gives "changes since last time".
- **Throttling:** 10,000 requests per 10 minutes per app per mailbox, 4 at once. `$batch`
  holds up to 20 requests.

References:
- Register an app: https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app
- Desktop/public client config: https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration
- Add redirect URI: https://learn.microsoft.com/en-us/entra/identity-platform/how-to-add-redirect-uri
- Add API permissions / admin consent: https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-configure-app-access-web-apis and https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/grant-admin-consent
- Permissions reference (Mail.Read vs Mail.ReadBasic): https://learn.microsoft.com/en-us/graph/permissions-reference
- Device code flow: https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code
- Auth flows and constraints: https://learn.microsoft.com/en-us/entra/identity-platform/msal-authentication-flows
- Security defaults (blocks device code): https://learn.microsoft.com/en-us/entra/fundamentals/security-defaults
- Microsoft-managed CA policies: https://learn.microsoft.com/en-us/entra/identity/conditional-access/managed-policies
- Blocking auth flows with CA: https://learn.microsoft.com/en-us/entra/identity/conditional-access/policy-block-authentication-flows
- Refresh tokens: https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens
- Error codes: https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes
- List messages ($filter/$orderby rules): https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0
- Message resource (internetMessageHeaders, bodyPreview): https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0
- Delta query for messages: https://learn.microsoft.com/en-us/graph/delta-query-messages
- JSON batching: https://learn.microsoft.com/en-us/graph/json-batching
- Throttling limits: https://learn.microsoft.com/en-us/graph/throttling-limits

### 4.5 Sending messages and calendars, references

- chat.postMessage (about 1 message a second per channel; a user token posts as you): https://docs.slack.dev/reference/methods/chat.postMessage
- conversations.open (1–8 users; 1 = DM, more = group DM): https://docs.slack.dev/reference/methods/conversations.open
- chat.scheduleMessage (up to 120 days ahead, max 30 per 5 minutes per channel): https://docs.slack.dev/reference/methods/chat.scheduleMessage
- users.lookupByEmail: https://docs.slack.dev/reference/methods/users.lookupByEmail
- Token behaviour ("write actions with user tokens are performed as if by the user"): https://docs.slack.dev/authentication/tokens
- Slack developer policy (no impersonation, no spam, minimal scopes): https://docs.slack.dev/developer-policy
- Graph getSchedule (free/busy for up to 20 people, under 62 days): https://learn.microsoft.com/en-us/graph/api/calendar-getschedule?view=graph-rest-1.0 and https://learn.microsoft.com/en-us/graph/outlook-get-free-busy-schedule
- Graph findMeetingTimes: https://learn.microsoft.com/en-us/graph/api/user-findmeetingtimes?view=graph-rest-1.0
- Graph calendarView: https://learn.microsoft.com/en-us/graph/api/user-list-calendarview?view=graph-rest-1.0
- Graph create event (invites go out automatically; Teams link): https://learn.microsoft.com/en-us/graph/api/user-post-events?view=graph-rest-1.0
- Google freebusy.query: https://developers.google.com/workspace/calendar/api/v3/reference/freebusy/query
- Google Calendar scopes: https://developers.google.com/workspace/calendar/api/auth
- Google events.insert (`sendUpdates`, Meet via `conferenceData`): https://developers.google.com/workspace/calendar/api/v3/reference/events/insert and https://developers.google.com/workspace/calendar/api/guides/create-events
- Google calendar sharing (free/busy only if shared): https://developers.google.com/workspace/calendar/api/concepts/sharing

### 4.6 Not confirmed by the docs (find out on the first real run)

- Whether a message sent with the user token shows an "APP" label next to your name. Slack
  says only that it acts "as if by the user".
- Whether `getSchedule` needs `Calendars.Read` or only `Calendars.ReadBasic`. Microsoft's pages
  disagree; `Calendars.ReadWrite` covers both.
- Whether Google marks `calendar.events` and `calendar.events.freebusy` as sensitive. Check the
  **Data Access** page.
- Whether Hermes' Telegram adapter can show Send / Edit / Cancel buttons. If not, use reply
  commands (`/send`, `/cancel`).

- Whether `search.messages` returns bot messages and thread replies, and how far its index
  lags behind.
- Whether `conversations.info` gives `last_read` for channels, not just DMs.
- Whether `authuser=<email>` Gmail links open the right account.
- Whether Graph accepts `internetMessageHeaders` in a list call.
- Whether your tenant shows the new tabbed Authentication screen or the old one.
- Whether "Personal mode" is open to ordinary @gmail.com accounts without the Developer
  Preview.

---

## Part 5: Sending Slack messages and scheduling meetings

**Needs a code change:** none of this is built yet. Part 5 covers the logins it needs and how
it would work. What you chose:
- **Calendars:** check **both** Outlook and Google for busy times.
- **Sending:** Hermes **shows the drafts first**. Nothing is sent until you approve.

### 5.1 What you can ask, and how many Gemini calls each takes

| You say (in Telegram) | What happens | Gemini calls |
|---|---|---|
| `/slack send @priya @rahul: Please send the Q3 numbers by 5` | Names are matched to Slack users, then a preview: "Send to Priya, Rahul (group DM)?" | **0** (a fixed command, read by a script) |
| "Tell Priya, Rahul and Amit that the review moves to Friday" | Hermes understands the sentence and fills in the same `/slack send`, then the preview | **1** (the normal Hermes turn) |
| `/meet 15:00-17:00 today` or "Set up all my meetings between 3 and 5" | Described in 5.2 | **1** |
| `/slack schedule 09:00 tomorrow @priya: …` | Same preview, then Slack sends it at that time | **0** |

### 5.2 "Set up my meetings between 3 and 5", step by step

1. **Who needs you (the 1 Gemini call).**
   - The script collects the last 3 days of Slack DMs and mentions, plus emails, that look
     like meeting requests. A word filter ("call", "meet", "sync", "discuss", "15 min",
     "available?") runs first, so the input is small.
   - Gemini returns a list: person, reason, suggested length (15/30/60 min), urgency, and
     the message link.
2. **Your free time (no model).**
   - Outlook: `calendarView` from 15:00 to 17:00.
   - Google: `freebusy.query` for each Google account whose calendar you want checked.
   - Busy times from all calendars are merged. Anything busy anywhere is off limits.
3. **Their free time (no model, optional).**
   - For colleagues in your company, Outlook `getSchedule` returns their busy times, up to
     20 people at once.
   - Each colleague's own sharing settings decide how much detail is shown. Free/busy is
     always enough to pick a slot.
   - Gmail contacts show free/busy only if they shared their calendar with you. Otherwise
     only your own time is checked.
4. **Slots (no model).**
   - The most urgent request gets the earliest slot. Each person's suggested length is used,
     with a 5-minute gap between meetings.
   - If it doesn't all fit, the overflow is listed as "doesn't fit today".
5. **Preview in Telegram (no model).**
   - Hermes shows one line per meeting, for example:
     `1. Priya — 15:00–15:30 — "Hi Priya, I can do 3:00–3:30 today for the vendor contract. Works?"`
   - The messages come from a template, so writing them doesn't call Gemini.
   - You reply **Send all**, **Send 1,3**, **Edit 2: <new text>**, or **Cancel**.
6. **Send (no model), only after you approve:**
   - **Slack:** `conversations.open` with the person's ID gives the DM channel. Then
     `chat.postMessage` sends the text **as you**.
   - **Calendar (optional, only if you said "and book it"):**
     - Outlook: `POST /me/events` with the attendee and a Teams link. **Outlook sends the
       invite email by itself at that moment** and can't be told not to, which is why it
       waits for your approval.
     - Google: `events.insert` with `sendUpdates=all` and a Meet link.
     - You set the default calendar for booking in `brief.yaml`.
   - Every sent message and invite is written to `$HERMES_HOME/brief/sent.jsonl`, so you can
     see what Hermes sent and when.

**"Send this to X, Y and Z":**
- Slack matches each name using the cached user list: display name, real name or email.
- If a name matches two people, the preview asks which one. Nothing goes to a guess.
- **One message per person (default):** separate DMs. This is safest.
- **One shared group DM:** `conversations.open` with up to 8 people.
- Slack allows about 1 message a second per conversation, so 20 people take about 20 seconds.
- Not allowed: sending in bulk to people you don't normally talk to. Slack's developer
  policy bans spam and can revoke the token.

### 5.3 Extra login steps for this

**Slack:** the four sending scopes are already in the manifest in 1.4. If the app is already
installed, add the scopes, click **Reinstall to <workspace>**, and update `SLACK_USER_TOKEN`.

**Outlook calendar:** same Entra app as in 3.1.
1. Open **Entra ID → App registrations → Morning Brief → API permissions → Add a permission →
   Microsoft Graph → Delegated** and tick:
   - **Calendars.ReadWrite**: read your calendar and create events. It also covers
     `calendarView`.
   - **Calendars.Read.Shared**: needed for `findMeetingTimes` and for colleagues' calendars.
2. Click **Add permissions**, then **Grant admin consent for <company>**.
3. Add the scopes to the login request. **Needs a code change:** `SCOPES` in
   `sources/outlook.py` becomes `offline_access Mail.Read Calendars.ReadWrite
   Calendars.Read.Shared`.
4. Sign in to Outlook again (3.1 step 9). An existing login does not pick up new
   permissions.

**Google calendar:** same Google Cloud project as in 2.2.
1. Go to **☰ Menu → APIs & Services → Library → Google Calendar API → Enable**.
2. Go to **Google Auth platform → Data Access → Add or remove scopes** and add:
   - `https://www.googleapis.com/auth/calendar.events`: create events in your calendars.
   - `https://www.googleapis.com/auth/calendar.events.freebusy`: busy times on calendars
     you can see.
3. Click **Update → Save**. The app stays **In production**, unverified, which is fine for
   personal use.
4. **Needs a code change:** the Google login asks for these scopes next to `gmail.readonly`,
   and you choose per account whether its calendar is included.
5. Sign in again for each account whose calendar you want. Tick **every** checkbox on the
   permission screen. An unticked calendar box gives `403` on calendar calls only.

### 5.4 Safety rules for sending as you

- Nothing is sent and no invite is created without your explicit **Send** in Telegram. A
  preview expires after 30 minutes.
- Every message and invite is logged in `sent.jsonl`.
- A wrong or ambiguous name stops that line. Hermes never guesses who you meant.
- There's a daily cap on messages Hermes sends for you (default 30). Set it in `brief.yaml`.
- The token never appears in chat or logs. It lives only in `$HERMES_HOME/.env`.
