# Watches → Claude (copy this file to `watch/HANDOFF.md` in your handoff repo)

Hermes watches web pages with a script and tells its owner on Telegram when something is added (with a
note written by Gemini). It asks you for one kind of help: finding the best way to read a new page.
Each issue names a folder `watch/<n>-setup-<time>/` holding `request.md`. Write exactly one file in
that folder, `spec.json`, commit it to `main`, close the issue.

General rules:
- Use only what you can see on the pages. Never invent a job, a date, a salary, a location or a
  deadline. If a page won't open, say so.
- Public pages only: don't sign in anywhere, don't submit forms.
- Read `request.md` for the page and what the owner cares about.

## Setup (`…-setup-…/request.md` → write `spec.json`)

The script reads the page as plain links, which is noisy and breaks when the page is redesigned.
Find the **steadiest machine-readable source** for what the owner cares about, in this order:

1. **The site's job board API**, if the careers page is hosted by one. Look at the page source and
   network calls (`curl -sL`): links or scripts mentioning greenhouse, lever, ashbyhq, smartrecruiters,
   workable, keka, darwinbox, zohorecruit, freshteam, recruitee, bamboohr, personio, teamtailor,
   workday. Use its public, unauthenticated JSON endpoint for this company.
2. **An RSS/Atom feed** (`<link rel="alternate" type="application/rss+xml">`, `/feed`, `/rss`).
3. **A JSON endpoint the page itself loads** (no login, no cookies, a stable URL).
4. **The page's links**, with a `match` pattern so only the relevant links count (e.g. `/jobs/|/careers/`
   or `\.pdf$` for uploads).

**Test before you write it:** fetch your URL with `curl -sL` and check that it returns the items
(count them). Write nothing you haven't fetched successfully.

`spec.json` is one JSON object:

```json
{"kind": "json", "url": "https://api.lever.co/v0/postings/acme?mode=json",
 "items": "", "title": "text", "link": "hostedUrl",
 "note": "Lever job feed: 14 open roles, steadier than the careers page"}
```

- `kind`: `json`, `feed` (RSS/Atom) or `html` (the page's links).
- `url`: what to fetch (http or https).
- For `json`: `items` is the dot path to the list of items (`""` when the answer itself is the
  list, `jobs`, `data.postings`); `title` is the field holding the item's name (a dot path is fine);
  then either `link` (the field with the item's public URL) or `link_template` (built from the
  item's top-level fields: `"https://jobs.example.com/{id}"`).
- `match` (optional): a regular expression; only items whose title or link match are kept. Use it to
  cut noise, not to guess the owner's preferences: a wider watch is better than a missed opening.
- `note`: one line for the owner: what source you chose and why, with the item count you saw.

If nothing beats the page's links, write `{"kind": "html", "url": "<the page>", "match": "…", "note": "…"}`
with a `match` that keeps the relevant links. If the page can't be read at all, write
`{"kind": "html", "url": "<the page>", "note": "Couldn't open it: <why>"}`.

Hermes checks the spec (kind, url, a valid `match`), reads it once and keeps the old way if it fails.
