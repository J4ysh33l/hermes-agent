# Watches (`/watch`)

Tells you on Telegram when a page **adds** something: job openings on a careers page, documents on
a notices page, posts on a blog. You only add pages; you never say what changed. A script reads and
compares, every 30 minutes for whatever is due; it is not an agent running all the time. Gemini writes
a short note on each change (one call, only when something is new); Claude, through your handoff
repo, finds the best way to read a page you add.

```
/watch add https://jobs.lever.co/acme backend roles in India
/watch add https://www.example.gov.in/notices tenders for hospitals
/watch list · check 2 · every 2 6 · match 2 engineer|developer · pause 2 · resume 2 · remove 2
/watch notes 2 off · /watch claude 2 off · /watch ask 2
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

## Notes on changes: Gemini (`watch.notes`, default on)

Each change message ends with Gemini's note: which new items match what you care about and why, with
facts from their pages (location, seniority, deadline as stated). The script opens up to 5 new items'
pages and passes their text (navigation and scripts stripped, 1,500 characters each); Gemini is told to
use only that text and to say "page not read" otherwise. One call per change, none when nothing is new.
`watch.about` tells it who you are. What it sees is public page text plus that line. If every model
fails, the change still goes out with a line saying why there is no note. `/watch notes 2 off` turns it
off for one watch.

## Setup research: Claude (`watch.claude`, default on)

Through the handoff repo and your Claude scheduled task (set up once: `orchestrator/HANDOFF.md`;
the rules Claude follows travel in the issue itself, `claude.SETUP`). When a page you add is read as plain links,
Claude looks for the job board behind it, a feed, or the JSON the page loads, tests it with a fetch,
and writes a spec. Hermes checks the spec, reads it once and switches over ("🔧 Watch 2 set up by
Claude: Keka job feed, 9 roles"); if it's wrong or can't be read, the page keeps being read as before
and you're told why. `/watch ask 2` asks again. A request Claude doesn't answer in 3 days is dropped
and you're told. Without the handoff repo, or with `/watch claude 2 off`, the page is simply read
as links.

## Setup

- `watch:` in `brief.yaml` (see `brief.example.yaml`): `every_hours`, `claude`, `about`, `fail_after`,
  `max_lines`, and `handoff_repo` if not the same as `notes.handoff_repo`.
- `orchestrator/brief/install.sh` writes `$HERMES_HOME/scripts/watch.py`; add the `watch` cron it
  prints (`*/30 * * * *`). State: `$HERMES_HOME/watch/watches.json` (0600).

## Tested

- **Fakes** (`tests/test_watch.py`): board, feed, JSON and link readers; baseline then only new items;
  Gemini's note written from the new item's page text (navigation stripped), no call when nothing is
  new, off per watch; a blocked page reported once and
  never as removals; Claude's setup spec refused when invalid, kept off when unreadable, used when good;
  pause, every, match, remove.
- **Live, 2026-11-24** (public pages, from the build container): a Greenhouse board (630 roles), an
  Ashby board, a Lever board (306 roles; the first try hit a network error, the retry worked), Hacker
  News RSS (30), python.org/jobs as links (140).
- **Not run yet:** the Claude scheduled task end to end (needs your handoff repo), the cron on the host.
