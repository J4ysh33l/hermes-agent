# Handoff: agent-orchestrator project (sanitized, public copy)

Saved 2026-11-21, seventh pass. This is the public copy. It has no names of people, bots, customers or businesses, no tokens and no contact details. The full handoff, with those details, is kept private and is not in this repository.

## What this is
A team of about 20 AI bots runs on a subscription with a usage percent shown and no token counts. The goal is to cut spend and keep automation reliable across Telegram, Slack, email, social platforms and files, without sending private data to free-tier models.

## Structure (decided, do not re-litigate)
- **Scripts** do the deterministic work with no LLM call: counters, status files, sync, scheduled posting, reminders.
- **Hermes** (one orchestrator) is the Telegram front door for small repeatable tasks on cheap models.
- **Claude Pro** does creative and judgment work through its own surfaces. The orchestrator cannot call Claude Pro, so hand-offs go through shared files and a queue.
- **Private lane:** confidential data only on a private profile with a private main model. Never on free-tier models.
- Claude drafts; a script delivers after approval.

## Repository contents for this branch
Only this document. The helper scripts that the team uses live outside the repository, because some of them contain team-specific names and settings, and the repository is public.

## Scripts built (outside the repo, in the private bundle)
| Script | Job | Status |
|---|---|---|
| pausectl | Global and per-bot pause, timed auto-resume, `check` exits 10 when paused | Tested on a temp state dir |
| statusupdate | Shared status file, summary and one-line report | Tested |
| queuectl | File-based ticket queue (pending, approved, claimed, done, rejected, failed) | Tested |
| telegram_control | Zero-LLM control bot: fixed commands, allowlist, no shell | Tested against a fake Telegram server only |
| weekly_digest | One compact page for the weekly review (replaces reading transcripts) | Tested |
| changed | "Nothing changed" gate: exit 0 changed, 3 unchanged, 2 could not read | Tested |
| bigfile | New-rows-only reads, filtered views, trim with archive | Tested |
| capout | Caps command output, saves the full text | Measured |
| usagetier | Percent bands to pause groups of bots, with timed restore; only undoes its own pauses | Tested, including a broken-guard check |
| dashboard | Small text or static HTML summary of our state | Tested |
| plan_coverage | Checks that every task in the build plan is assigned once | Tested |
| imgrender | Template-driven image renderer (Pillow), no model calls | Tested on sample rows |
| logoswap, compare | Logo swap for images and video, before/after comparison | Tested on synthetic media |
| editplan | Transcribe, brief, plan, validate, render, QC for video edits | Tested on synthetic media; Whisper not run |

## Measured with a real Hermes build (fake model, fake Telegram)
- Quick commands ran with zero model calls. Built-in commands win over quick commands of the same name, so custom names must not collide.
- A slim toolset cut fixed cost to about 2.4k tokens from about 8.9k.
- Context compaction kept a tool-heavy run's peak at about 15.8k tokens, against about 49.5k without it.
- No config setting caps one large tool result. A wrapper script (capout) is required.
- A model with a context window under 64,000 tokens is refused at startup. Free-tier models here pass that check.
- Auxiliary tasks (compression, title, background review, approval, vision, curator) can be pinned to another endpoint. A dead pinned endpoint silently falls back to the main model unless a fallback chain is set.
- The main model still sees all raw private text, so private profiles need a private main model.

## Not run
Real Telegram, real Gemini, real Whisper transcription, the AWS installer, a Claude scheduled task reading the queue folder, and a live gateway test of any new slash command.

## Build plan
27 builds plus 3 measurement steps, covering all 66 tasks. Each build lists its tasks, dependencies, what the owner must supply, an acceptance check and a status. Every task is either in a build or explicitly retired, manual or skipped with a reason.

Phases in order:
0. Stage 1 foundations (done here, awaiting adoption on the platform)
1. Small no-LLM scripts (reminders and nudges; wording needed from the owner)
2. Host and Hermes pilot (needs a host, a second Telegram token, and a budget config check on the real host)
3. Measure usage per routine for a week
4. Claude-lane instruction packs (need brand rules)
5. X and sales scripts (need API access and a policy decision)
6. Gemini pilot on public-data flows only
7. Media (image and video done; voice cloning and motion graphics planned for the owner's own machine)
8. Private lane (separate profile, private model)
9. Blind A/B, then a real cost comparison

## Open decisions for the owner
- Host size and where heavier media tools run
- Usage tier bands and which groups each tier pauses
- Policy answer on automated posting and replies on the social platform
- Whether a scheduled usage-window kickoff is still needed
- Wording and times for reminders and nudges

## Rules that carry over
- Do not push team-specific names, business details or tokens to this public fork.
- Tokens and keys go in an environment file on the host, never in chat.
- Do not spawn sub-agents for small questions. Work directly.
- Say what was verified, what was measured and what is inference.

## How to resume
1. Read this file and the build plan in the private bundle.
2. Ask the owner for the private bundle; it holds the full handoff, the scripts and the build plan.
3. Continue from the first build marked "not started" that the owner has unblocked.
