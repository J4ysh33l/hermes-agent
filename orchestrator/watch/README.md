# Watches (`/watch`)

Tells you on Telegram when a page **adds** something: job openings on a careers page, documents on
a notices page, posts on a blog. You only add pages; you never say what changed. A script reads and
compares, every 30 minutes for whatever is due; it is not an agent running all the time and it uses
no model. Claude (the default helper, through your handoff repo) does the judgment: it finds the best
way to read a new page and writes a short note on each change.

```
/watch add https://jobs.lever.co/acme backend roles in India
/watch add https://www.example.gov.in/notices tenders for hospitals
/watch list · check 2 · every 2 6 · match 2 engineer|developer · pause 2 · resume 2 · remove 2
/watch claude 2 off · /watch ask 2
```

## How a page is read

| The address | Read from | Why |
|---|---|---|
| Greenhouse, Lever, Ashby, SmartRecruiters, Workable careers pages | the board's public JSON feed | every opening with its title and link, unaffected by redesigns |
| A feed (`/feed`, `/rss`, `.xml`), or a page that answers with RSS/Atom | the feed | the site's own list of new items |
| Anything else | every link on the page (text + address) | works on most pages; Claude then looks for something steadier |

- **Items** are keyed by their link, so a renamed job with the same link is not "new".
- **The first read is the baseline:** "12 items now". After that you hear only about new ones;
  removals are counted in the same message, never sent alone.
- **A page that fails** (HTTP error, network, or suddenly no items where there were some, which is
  what a block or a redesign looks like) keeps its last list; after `watch.fail_after` failures in a
  row you're told once. It never reports "everything was removed".
- **`match`** keeps only items whose title or link match a pattern (`/watch match 2 \.pdf$`); the
  next read starts a fresh baseline, so nothing already there is announced.
- Pages that need a login, or that draw their list with JavaScript, show few or no links. Claude's
  setup usually finds the JSON the page loads; otherwise such a page can't be watched yet.

## What Claude does (default on; `watch.claude`)

Through the handoff repo and your Claude scheduled task (set up once: `orchestrator/HANDOFF.md`).
The contract Claude follows, with its rules, is `HANDOFF.md` in this folder.

1. **Setup research**, when a page is read as plain links: Claude looks for the job board behind it,
   a feed, or the JSON the page loads, tests it with a fetch, and writes a spec. Hermes checks the
   spec, reads it once and switches over ("🔧 Watch 2 set up by Claude: Keka job feed, 9 roles"); if
   it's wrong or can't be read, the page keeps being read as before and you're told why.
   `/watch ask 2` asks again.
2. **A note on each change:** the script's list goes out at once; Claude opens the new items' pages
   and writes which matter to you and why (location, seniority, deadline as stated), in up to 10
   lines. `watch.about` tells it who you are. A request Claude doesn't answer in 3 days is dropped
   and you're told.

Without the handoff repo, or with `/watch claude 2 off`, you still get every change, just no note.

## Setup

- `watch:` in `brief.yaml` (see `brief.example.yaml`): `every_hours`, `claude`, `about`, `fail_after`,
  `max_lines`, and `handoff_repo` if not the same as `notes.handoff_repo`.
- `orchestrator/brief/install.sh` writes `$HERMES_HOME/scripts/watch.py`; add the `watch` cron it
  prints (`*/30 * * * *`). State: `$HERMES_HOME/watch/watches.json` (0600).

## Tested

- **Fakes** (`tests/test_watch.py`): board, feed, JSON and link readers; baseline then only new items;
  the change note asked of Claude and delivered once on a later run; a blocked page reported once and
  never as removals; Claude's setup spec refused when invalid, kept off when unreadable, used when good;
  pause, every, match, remove.
- **Live, 2026-11-24** (public pages, from the build container): a Greenhouse board (630 roles), an
  Ashby board, a Lever board (306 roles; the first try hit a network error, the retry worked), Hacker
  News RSS (30), python.org/jobs as links (140).
- **Not run yet:** the Claude scheduled task end to end (needs your handoff repo), the cron on the host.
