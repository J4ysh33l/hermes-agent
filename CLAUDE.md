# Working rules for Claude in this repo

- **Anything that may take over ~15 seconds runs in the background.** Tests (`orchestrator/run_checks.sh`
  or a single slow suite), installs, downloads, renders, transcriptions, CI waits and any long
  processing run as background commands; keep working (or report) while they run and pick up the
  result when it finishes. Never sit waiting on them in the foreground.
- Run `orchestrator/run_checks.sh` without live `GITHUB_HANDOFF_TOKEN` / `CLAUDE_ROUTINE_*` in the
  shell (`env -u GITHUB_HANDOFF_TOKEN -u CLAUDE_ROUTINE_URL -u CLAUDE_ROUTINE_TOKEN ...`): Hermes reads
  the process environment before `.env`, so live values override the tests' fake ones.
- Merge only on the user's word.

## Cloud sessions

The environment's setup script (`orchestrator/studio/cloud-setup.sh`) installs the studio before the
session starts: `HERMES_HOME=/home/user/faceless-home` (voice env, models, brief.yaml) and Remotion
in `/opt/hermes-setup`. At the start of a studio session:
- `export HERMES_HOME=/home/user/faceless-home`
- link Remotion if `orchestrator/studio/remotion/node_modules` is missing:
  `ln -s /opt/hermes-setup/orchestrator/studio/remotion/node_modules orchestrator/studio/remotion/node_modules`
- the voice file: copy the user's approved cloned voice from the private handoff repo if
  `$HERMES_HOME/studio/voices/me.pt` is missing:
  `git -C /home/user/hermes-handoffs pull -q && cp /home/user/hermes-handoffs/voices/me.pt $HERMES_HOME/studio/voices/me.pt`
  (the repo is J4ysh33l/hermes-handoffs; attach it with add_repo if it is not in the session).
- Tokens come from the environment's variables (`GITHUB_HANDOFF_TOKEN`, `CLAUDE_ROUTINE_URL`,
  `CLAUDE_ROUTINE_TOKEN`); nothing to set up by hand.

## HR offer letters in a cloud session

When the user sends offer details ("send them internship offer letters…"), use the `/hr offer` code,
not a one-off script, so every rule applies (unpaid, months, several people, signature, PDF only, cc).
- `export HERMES_HOME=/home/user/brief-test-home` (Outlook login, GEMINI_API_KEY, `hr:` settings incl.
  `cc`). If it is missing, the Outlook login has to be redone (`python -m orchestrator.brief auth microsoft`).
- Templates and saved duties live in the private repo, folder `hr/`: copy them in first:
  `git -C /home/user/hermes-handoffs pull -q && mkdir -p $HERMES_HOME/hr/templates && cp /home/user/hermes-handoffs/hr/templates/*.docx $HERMES_HOME/hr/templates/ && cp /home/user/hermes-handoffs/hr/duties.json $HERMES_HOME/hr/`
- Make: `python -m orchestrator.hr offer internship <the user's lines as sent>` (fte / consultant the same).
  Show the user what it made (names, dates, pay, duties, the PDF). Read the user's format as it is; a
  message the code cannot read goes to Gemma 31B → Gemma 26B → Gemini 3.1 → 3.5 Flash-Lite by itself.
- Send only on the user's word: `offer test` (PDFs to the user only), `offer yes` (each person, from
  hr@medochealth.in, PDF only, `hr.cc` copied on every HR mail).
- After a new position: copy `$HERMES_HOME/hr/duties.json` back to `hermes-handoffs/hr/duties.json`,
  commit and push, so the next session reuses the same duties.
