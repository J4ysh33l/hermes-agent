# Bot team scripts (stage 1: fix waste in place)

Both scripts use only the Python 3 standard library and make no LLM calls.
State goes in `$AGENT_STATE_DIR` (default `~/.agent-state`).

| Script | Replaces | Task # in `Bot task assignment.md` |
|---|---|---|
| `pausectl.py` | ~20-bot pause/resume broadcasts, usage-mode restore | 2, 4 |
| `statusupdate.py` | fresh Python for the status file after every run, status lines, nightly report | 7, 8 |

## Pause switch
```bash
pausectl.py pause --for 6h --reason "saving credits"   # everything, auto-lifts
pausectl.py pause --bot kabir                          # one bot, open-ended
pausectl.py resume                                     # clears the global pause
pausectl.py resume --all                               # clears every pause
pausectl.py status
```
First line of every scheduled routine: `pausectl.py check --bot NAME || exit 0` (exit code 10 = paused).
Optional Telegram notices: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

## Status updates
```bash
statusupdate.py kabir x-reply-drafts ok --count drafted=45
statusupdate.py --summary --since 24h    # nightly team report
statusupdate.py --line kabir             # one fixed-format line for Donna
```

Tested locally on Python 3.13 (pause, bot-scoped pause, resume, resume --all, auto-expiry, bad input, status, summary). Not tested: the Telegram notice (needs real credentials), or running from the bots' real schedulers.

## Added in the second pass
| Script | Job | Task # |
|---|---|---|
| `queuectl.py` | File-based ticket queue (pending/approved/claimed/done/rejected/failed). A ticket is a small JSON header plus a path. `claim --lane claude` exits 3 when empty, so a scheduled Claude run can stop in one cheap turn. | 6, 12, 15 |
| `telegram_control.py` | Zero-LLM Telegram control bot on a second bot token. Chat-id allowlist, exact command list, no shell. Commands: /status /pause /resume /summary /line /queue /approve /reject | 4, 6, 39 |
| `weekly_digest.py` | One compact page for the weekly Claude review, replacing the 20-transcript review | 13 |
| `hermes_config_snippet.yaml` | Hermes `quick_commands` (no LLM) and context-budget settings. Quick commands, a chat turn, delegate_task and aux pinning were run on a real gateway against fake Telegram and fake models; see the file for what was not tested. | |

Tested with a fake Telegram server: allowed chat answered, stranger ignored, injection-style arguments rejected, token never printed. Not tested against real Telegram.

## Added in the third pass (2026-11-21)
| Script | Job | Task |
|---|---|---|
| `capout.py` | Runs a command and caps what it prints (default 3000 chars), saving the full text to `$AGENT_STATE_DIR/spill`. Run every command Hermes executes through it, or keep script output compact. Measured: without it one large tool result pushed a request to 28k tokens; with it the same workload peaked at 16.5k. | context budget |
| `media/imgrender.py` | Template-driven PIL image renderer: JSON template once, then one image per CSV/JSON row with no model calls. Text auto-shrinks to fit; text that cannot fit is reported, never cut. Needs Pillow only. Example in `media/examples/`. | images |
| `media/editplan.py` | `transcribe` (local faster-whisper) -> `brief` (compact text for Claude) -> Claude writes plan JSON -> `validate` -> `render` (ffmpeg, captions, loudness, vertical crop) -> `qc`. Encodes one segment at a time so it fits a 2 GB host. | video edits |

Written from scratch: the bots' own scripts zip was not available. When it arrives, compare against these and keep what the bots already do well.

Tested here: `imgrender.py` (4 sample rows, missing field, optional logo, auto-shrink, checked visually); `editplan.py` on synthetic media (reorder, speed change, vertical crop, burned captions checked on a frame, loudness -16 LUFS, QC pass and fail cases, no-audio source, invalid plan). NOT tested: real Whisper transcription (the model host was blocked here; the transcribe step was checked only against a stub of the faster-whisper API), speed on a 2-core 2 GB host, real footage with speech.

See `hermes_config_snippet.yaml` for the Hermes budget settings and exactly what was and was not tested.

## Added in the fourth pass (2026-11-21): stage 1, "stop re-reading and re-running"
Python 3 standard library, no LLM. Linux or macOS (they use `fcntl`). All state under `$AGENT_STATE_DIR` (default `~/.agent-state`), so they run unchanged in a bot's `/workspace` or on the AWS host.

| Script | Job | Fixes (from the audit) |
|---|---|---|
| `changed.py` | `check KEY --file F` / `--dir D` / `-- COMMAND`: exit 0 = changed, 3 = unchanged, 2 = could not read (never reported as unchanged). Gate with `...; [ $? = 3 ] && exit 0`, not `|| exit 0`. `peek` then `mark` lets the work succeed before the change is recorded. | Routines that run an LLM turn when nothing is new: Range sales asks and status, Donna check-in, background watches. |
| `bigfile.py` | `new` = only rows added since this consumer last read (CSV aware: quoted multi-line cells, half-written last row left alone). `view --where date>=... --tail N` = filtered stateless look. `trim --keep-rows N --apply` = move old rows to an archive, never delete (dry run by default). | Teenzyn's 450k-character calendar CSV, Vivek's 148k queue and 345k claim log. |
| `test_stage1.py` | Self-check for both: `python3 test_stage1.py` | |

Tested: 4 test groups pass (stray quotes like 6" frame do not swallow later rows; a genuinely unclosed quote exits 2, never "no new rows"; first/unchanged/changed/error/peek/mark/reset, directory hashing, bad key; CSV with multi-line cells, per-consumer places, paging, half-written row, filters, dry-run vs apply, byte-exact archive, reader positions surviving a trim, shrunken file, line mode). Scale: a 426k-character calendar gave 800 characters for one week and 4.3k for a first 50-row batch; a 5 MB, 60,000-line log trimmed in 0.07 s with no byte lost. Not tested: on the bots' own platform, concurrent writers in the last millisecond before a trim swap (see the shortcut note in `bigfile.py`), Windows.

**Instruction line to give each bot (one line in its skill or system text):** "Before reading a big file, run `bigfile.py new FILE --consumer YOURNAME`; before an LLM turn on a schedule, run `changed.py check YOURNAME-job --file ...` and stop only if it exits 3 (on 2, do the work); use the saved scripts in the scripts folder instead of writing new ones." Getting the files onto the bots' platform is a manual step: send them to a bot (e.g. Donna) in chat or put them in the shared folder.

**Savings caveat:** on the bots' own platform the bot has already woken up (one model turn) before it can run `changed.py`, so the gate saves the rest of that turn, not the wake-up. The full saving needs the check to run before any model call: system cron or a Hermes script job (no-agent cron) that runs `changed.py` and only then starts the bot.

## Added in the sixth pass (2026-11-21): our own media scripts (the bots' scripts will not be provided)
Python 3 + Pillow + ffmpeg/ffprobe, no LLM. All fit a 2 GB host (one file at a time). Self-check: `python3 test_media.py` (builds tiny synthetic media, about 10 s).

| Script | Job | Replaces (from the audit) |
|---|---|---|
| `media/logoswap.py` | `preview` (draw the box and a pixel grid so you or Claude can read the coordinates), `swap` (images with PIL, videos with ffmpeg overlay, a whole folder in one run, optional time window per rule), `qc` (checks the old logo area changed and nothing else did). Box comes from a JSON manifest; there is **no auto-detection**. Needs the new logo file and one box per size of ad. Writes `logoswap_report.json`; a file with no matching rule or a box that does not fit is a failure, never left silently old. | `scan.py`, `swap.py`, `qc.py`, `batch.sh` (medoc-logo-swap, 35 ads) |
| `media/compare.py` | OLD / NEW / DIFF sheet as one PNG plus "X% of pixels changed" and the changed area. Files or whole folders (paired by name; a file on one side only is a failure). Videos at chosen seconds. `--max-diff` / `--min-diff` make it a script gate. | "OLD vs NEW sheet" in visual-change-and-rebuild |
| `media/editplan.py qc` (extended) | Two new checks: `frozen picture` (still stretch of `--max-freeze` seconds, default 3) and `a/v start offset` + `a/v length` (`--max-av-offset`, default 0.1 s). | delivery-check-pro "sync, freeze" |
| `media/editplan.py render` (extended) | Optional plan key `"music": {"path", "gain_db": -18, "duck": true}`: a looped music bed under the voice that dips while the voice speaks, loudness-normalised after the mix. | `mix.py` (see decision below) |

**Decision on `mix.py`:** a separate script is not needed. The only mixing job we know of (music bed with ducking under speech) is now one plan key in `editplan render`. If the bots' `mix.py` does something else (several voice tracks, sound effects at timestamps), tell us what and we will add it then.

Tested (synthetic media): logoswap on a PNG, a JPEG (solid colour cover, percent box) and a video (window 1-4 s: swapped inside, original logo left after it, audio kept, duration kept); QC catches an unswapped copy; missing rule, box off the frame and `--out` equal to the originals' folder are refused; checked by eye on frames. compare on same/changed/different-size images, a folder with a missing partner, and two video times (checked by eye). editplan qc on a frozen tail, audio 0.6 s late, audio 1.5 s short, and a normal render (passes everything); music: ducked bed measured 6 dB quieter under speech than in silence, un-ducked equal, 2 s bed looped over 6 s, missing music file rejected by `validate`.
Not tested / known limits: **real footage and the real new logo** (synthetic only); a moving logo needs one window per position; the solid cover shows on busy or gradient backgrounds and `blur` can let the old logo ghost through (QC cannot judge how it looks, so look at `compare.py` sheets before delivery); the a/v check is container-level (do audio and video start and end together), it does not measure lip-sync drift inside the content; freeze detection will flag a deliberate still slide longer than `--max-freeze`; speed on a 2-core host; rotated phone videos are handled by reading the rotation tag but were not tested.
**Brand rules needed from you only when you start using them:** the real box for each ad size and the new logo file (logoswap); nothing for compare/qc/music. Image templates for `imgrender.py` still need your design styles.

## Added in the seventh pass
`media/guides/editplan_guide.md` and `media/guides/imgrender_guide.md`: short Claude-facing guides for writing plan.json and template.json (steps, keys, gotchas, what QC does not check). Their JSON examples were run through the real scripts (validate/render/qc and check/render). Brand rules are left to the user.

| Script | Job | Task |
|---|---|---|
| `usagetier.py` | `init` writes an example `usage_tiers.json` (placeholder bands and bot names: edit them). `set PCT` applies the tier: pauses its bots with a timed restore, resumes only what it paused before, never touches hand-made pauses. `status` shows the current tier. Also `/tier [PCT]` in the control bot. You still read the percentage yourself. | 3 |
| `dashboard.py` | Small summary from our state: pauses, tier, queue, latest routine per bot. `--html FILE` writes a static page. | 9 |
| `plan_coverage.py` | Checks that every task 1 to 66 appears once in `reports/Build runway.md`. | planning |

Tested with temp state dirs (`test_stage1.py`, 7 tests). Not tested: `/tier` through real Telegram, or on the AWS host.
