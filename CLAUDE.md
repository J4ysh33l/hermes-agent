# Working rules for Claude in this repo

- **Run anything slow in the background.** Tests (`orchestrator/run_checks.sh`), installs, downloads,
  renders and any long processing run as background commands; keep working (or report) while they run
  and pick up the result when it finishes. Never sit waiting on them in the foreground.
- Run `orchestrator/run_checks.sh` without live `GITHUB_HANDOFF_TOKEN` / `CLAUDE_ROUTINE_*` in the
  shell (`env -u GITHUB_HANDOFF_TOKEN -u CLAUDE_ROUTINE_URL -u CLAUDE_ROUTINE_TOKEN ...`): Hermes reads
  the process environment before `.env`, so live values override the tests' fake ones.
- Merge only on the user's word.
