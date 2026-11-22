---
name: outreach
description: "Draft Slack messages and Outlook meetings for the user; they approve in Telegram."
version: 1.0.0
author: orchestrator (fork-only)
---

# Outreach: Slack messages and meetings (draft only)

Use this when the user asks you to message people on Slack ("tell Priya and Rahul the review moves
to Friday"), to set up one-on-ones ("1:1s with these 10 people from 3 to 7, 15 minutes each"), or to
schedule an all-hands in a channel.

You can only **draft**. Run, with the user's request in their own words:

```bash
python3 "${HERMES_HOME:-$HOME/.hermes}/scripts/outreach_draft.py" "<the user's request, verbatim>"
```

It prints a numbered plan. Show that plan to the user exactly as printed and tell them to approve
it with `/slack yes` (messages) or `/meet yes` (meetings), pick lines with `yes 1,3`, or cancel with
`no`. Do not rewrite the plan, do not claim anything was sent, and never try to send any other way.

- Pass names exactly as the user said them; the script matches them and stops on unclear names.
- If it prints a problem (a name that fits two people, no start time), ask the user and run it again.
- Times, slots, breaks and the Teams link are worked out by the script, not by you.
- Fixed forms the user can type themselves: `/slack help`, `/meet help`.
