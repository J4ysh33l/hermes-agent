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
- the voice file `$HERMES_HOME/studio/voices/me.pt` is not installed by the script; ask the user for it
  if it is missing.
- Tokens come from the environment's variables (`GITHUB_HANDOFF_TOKEN`, `CLAUDE_ROUTINE_URL`,
  `CLAUDE_ROUTINE_TOKEN`); nothing to set up by hand.
