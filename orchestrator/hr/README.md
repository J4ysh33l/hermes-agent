# HR: payslips, interviews, the HR inbox, replies

Payslips from your monthly salary sheet, emailed from your Outlook after you approve; interviews on
one Teams link; mail to the HR mailbox sorted; replies in the mail's own thread. Scripts do
everything except a `/hr reply` draft you ask Gemini for. **No AI model sees pay or bank details.**
Gemini sees an HR mail only when you ask it to draft a reply, and then only with names, emails,
phone numbers, links, amounts and ID numbers replaced by placeholders (see below).

`/hr list` shows everything pending in HR in one reply: mail waiting for a reply (numbered for
`/hr reply` and `/hr inbox done`), applications of the last 14 days with no answer, and every HR
approval waiting for your yes or expired without it (payslips, interviews, a reply draft).

## Each month

1. Either way works:
   - **Paste the table:** `/hr payslip November 02/12/2026`, then the cells copied from Google
     Sheets or Excel on the next lines. The paste must keep its tabs; if they're lost, it says so.
     Always paste after `/hr payslip`: a table sent as a plain chat message would reach the model.
   - **Send the file** (.xlsx or .csv) and say the month and the pay date: "payslips for November,
     paid 2 Dec". The agent passes only the file path to `$HERMES_HOME/scripts/hr_payslips.py`
     (skill `orchestrator:hr-payslips`).
   - **Month:** `November`, `Nov`, `Nov 2026`, `11/2026` (without a year, the latest November that
     has started), or two dates `01/11/2026 30/11/2026`. The pay date is always dd/mm/yyyy.
   - On the host: `python -m orchestrator.hr payslip ~/nov.xlsx November 02/12/2026`.
2. Before making anything, the script checks the template, the columns and every row. It lists
   **every** problem in one reply: missing columns, missing or `0` values, bad dates and numbers,
   Basic + HRA ≠ Compensation, LOP over the working days, and duplicate emails, one line per
   employee. Nothing is made yet. It also warns about blank bank details and mid-period joiners.
   `/hr payslip check <sheet> <from> <to>` runs only this check.
   - **Only some rows wrong?** The reply offers `/hr payslip skip`: it makes everyone else's slips and
     leaves those employees out. Their names stay listed in `/hr payslip show` until you send a fixed sheet.
     Both rows that share an email are left out. If the sheet changes before `/hr payslip skip`, nothing
     is made and the new list is offered instead. The offer expires with the batch (2 hours).
   - Missing columns or a missing template can't be skipped: fix them and send the sheet again.
3. It makes one PDF per person in `$HERMES_HOME/hr/payslips/<YYYY-MM>/`.
4. It replies with counts only.
5. `/hr payslip show`: name, email and net pay for each person, plus the total.
6. `/hr payslip test`: two sample slips are emailed to **you**. `/hr payslip test all` emails every slip to you.
7. `/hr payslip yes`: each person gets their own slip from your Outlook. `/hr payslip yes 1-10` sends only those.
   `/hr payslip no` cancels. A batch expires after 2 hours. An expired one stays in the 20:00 recap until you make it again or say `no`.

## The sheet

| Column | Needed | Notes |
|---|---|---|
| Employee Name, Position, Email, DOJ | yes | DOJ as dd/mm/yyyy. A designation of `0` counts as missing |
| Compensation, Basic | yes | Basic between 0 and Compensation |
| HRA | no | Default: Compensation − Basic. If given, Basic + HRA must equal Compensation |
| LOP Days | no | Half days allowed (0.5) |
| Reimbursement, Other Deductions | no | Default 0 |
| IFSC, Bank Account, Employment Type | ignored | Never copied anywhere |

## The rules

- **Working days:** the days in the period minus weekly offs and holidays (`hr.weekly_off`, default
  Sunday; `hr.holidays`).
- **Loss of pay:** Compensation ÷ working days × LOP days, rounded to the rupee.
- **Net pay:** Gross − (Loss of pay + Other deductions) + Reimbursement.
- **Paid days:** working days − LOP days.
- **Compensation 0:** the row is skipped and listed.
- **Joined inside the period:** listed as a warning, so you can check their LOP covers it.

## Template

`$HERMES_HOME/hr/templates/payslip.docx` is your Word payslip with `{{fields}}`: `month name
designation doj pay_period paid_days lop_days pay_date basic hra gross lop_amount other_deductions
total_deductions reimbursement net_pay`.

- A field with no value stops the run, so a typo never produces a slip with a blank in it.
- The same filler (`docfill`) will drive offer and termination letters.
- Making PDFs needs LibreOffice (`soffice`) on the host.

## Interviews

`/hr interview` books a block of interviews on **one Teams link**, with each candidate invited only
to their own slot. No AI model is used. Send it as one message, one line each:

```
/hr interview
Date: 25/11/2026
Panel: rishabh@medochealth.in, nidhi@medochealth.in
Asha Verma, Backend Engineer, 11:00, 11:30, asha@gmail.com
Rohan Das, Data Analyst, 11:45, 12:15, rohan@gmail.com
```

- **Each line:** Name, Position, Start, End, Email. The position may contain commas
  ("Director, Operations"). Times: `11:00`, `3:30pm`. End is optional: Start + `hr.interview_minutes`
  (30). `Panel:` is optional.
- **Or paste a table** (tabs kept) with a header row: Name, Position, Email, Date, Start, End
  (End optional; Date may be a `Date:` line instead). One day per batch, since it's one link.
- **Candidates get only their own invite.** The Teams meeting itself invites only the panel, so no
  candidate gets the main meeting email or sees anyone else.
- **The check:** every problem is listed at once (bad times or emails, missing fields, overlapping
  slots, past times, the same email twice), and nothing is saved until it's clean. Slots can't
  overlap because everyone shares the link. If your own calendar is busy during a slot, it warns.
- **`/hr interview yes`:**
  1. A Teams event on your calendar spans the whole block; the panel is invited and gets the full
     schedule. This makes the one link.
  2. Each candidate's slot goes on your calendar with that link. With `hr.mailbox` set, the
     candidate gets an email **From that mailbox** (e.g. hr@medochealth.in) with the link and an
     `interview.ics` to add it to their calendar; their reply goes to the mailbox, while the meeting
     and the calendar stay yours. Without it, Outlook sends them the invite from your mailbox.
     Either way they never see each other's names or emails.
- **The lobby:** candidates are outside your company, so Teams holds them in the lobby until
  someone on the panel admits them. An early joiner can't walk into the previous interview.
- `/hr interview show` · `/hr interview no`. A plan expires after `hr.preview_minutes`. An expired one stays in the 20:00 recap until you make it again or say `no`.
- **Wording:** `hr.interview` in `brief.yaml` (company, subjects, HTML bodies); the defaults are in
  `settings.py`. Uses the Outlook login's Calendars.ReadWrite (and Mail.Send for `hr.mailbox`), already granted.

## HR inbox

Mail sent to `hr.mailbox` (a Microsoft 365 group, so it lands in your own Outlook) is read with your
Outlook login (Mail.Read, already granted) and sorted by fixed rules on the subject and sender:

| Kind | Rule (first match wins) |
|---|---|
| 🚨 Urgent | legal, court, advocate, police, labour, harassment, POSH, complaint, grievance, final notice, pending salary/dues/payment, unpaid, urgent; or a `.nic.in` / `.gov.in` sender |
| 👥 People | resignation, relieving, experience certificate, full & final, salary, payslip, leave, notice period, appraisal, reimbursement, offer letter, joining, PF/ESI, form 16, bonus; or anyone at your domain |
| 🎓 Campus | campus, placement, recruitment drive, graduating batch, T&P |
| 📄 Applications | application, resume, CV, opportunity, role, position, job, internship, developer, engineer, fresher, hiring … |
| 📢 Other | everything else (vendors, webinars, newsletters) |

Urgent and people mails wait for a reply until someone else at your domain answers in the same
thread (a colleague's "Re:" counts, the sender's own follow-up does not) or you `/hr inbox done 2`.
Mails you sent yourself are left out.

```
/hr inbox show                 new mail by kind + everything waiting for a reply
/hr inbox list applications    the last 14 days of one kind
/hr inbox done 2               handled outside the thread
```

The `hr-inbox` cron sweeps at 10:00 and 17:00. It messages you only when there is new HR mail; the
day's first sweep also reminds you of urgent mail still unanswered. One Outlook search per sweep,
plus one lookup per mail waiting for a reply. State: `$HERMES_HOME/hr/inbox.json` (subject, sender,
kind; no bodies; forgotten after 30 days unless still waiting).

## Replies

`/hr reply <n>` answers mail `n` of the waiting list (`/hr list` or `/hr inbox show`) in its own
thread, From `hr.mailbox`, only after `/hr reply yes`.

```
/hr reply 2                          Gemini drafts a reply
/hr reply 2 say the letter goes out Friday     …following your instruction
/hr reply 2 ack Backend Engineer     a template, no model (ack · reject · docs · letter · leave · salary)
/hr reply applications ack           every unanswered application of 14 days, one preview, one yes
/hr reply show · yes · no · again <change> · edit <your text>
```

- **The shape is the script's:** "Hi <first name>," and "Regards, <hr.sender_name>" are added by the
  script; Gemini writes only the paragraphs in between, as JSON (`{"paragraphs": [...]}`), so it
  can't change the layout. A greeting or sign-off it writes anyway, as its own paragraph or inside
  one ("Hi [NAME_1], thank you…", "…by Friday. Warm regards, HR Team"), is cut and shown as a fix.
- **The subject is the thread's:** Graph's reply action keeps the original subject as "Re: …";
  the model never writes one.
- **What Gemini sees:** only the mail's new text (not the quoted thread) and your instruction, with
  every name in the headers (sender, To, Cc), the signed name, `hr.redact_names`, emails (also
  spelt out: `asha [at] gmail [dot] com`), phone
  numbers, links, amounts (₹, Rs, INR, lakh, LPA, k, /-), PAN, IFSC, Aadhaar and long ID or account
  numbers replaced by `[NAME_1]`, `[EMAIL_1]`, `[AMOUNT_1]`… The table to put them back stays on
  the host. A name written in the body that is none of those can still reach it.
- **The check before anything is put back** (`redact.restore`):
  - a placeholder written slightly wrong (`[name_1]`, `{NAME_1}`, `NAME_1`) is rewritten to its
    exact form and listed under "Fixed in its answer";
  - a placeholder the mail never had (`[NAME_7]`), or an email, phone, link, amount or ID number
    written out, means the model made it up: the draft is refused and asked for once more with the
    problem named, then the next model is tried (3.1 Flash-Lite, 3.5 Flash-Lite, Gemma 4);
  - if none passes, nothing is drafted and you see every reason, with the template as a way out.
- **Templates:** `hr.replies` in `brief.yaml` changes or adds them; the words after the name fill
  `{for_role}` (" for the X role"), `{by_when}` (" by X", else " shortly"), `{for_when}`, `{arg}`.
- **Sending:** Graph's reply action (Mail.Send, already granted), so the answer joins the thread.
  A sent reply clears the mail from the waiting list. A draft expires after `hr.preview_minutes`;
  an expired one stays in the 20:00 recap until `/resume` or `/hr reply no`.

## Setup

- **Outlook:** the Entra app needs delegated **Mail.Send** with admin consent. Then sign in once
  more: `python -m orchestrator.brief auth microsoft`.
- **HR mailbox:** `hr.mailbox` in `brief.yaml` (e.g. `hr@medochealth.in`) sends payslips From that
  address instead of yours; your account needs **Send As** on it (an Exchange admin grants it). A
  refused send says so. `hr.sender_name` is the sign-off. Interview mails to candidates use it too;
  the Teams meeting and the slots stay on your calendar.
- **Install:** `orchestrator/brief/install.sh` writes the launchers (`hr_payslips.py`, `hr_inbox.py`)
  and creates `$HERMES_HOME/hr/templates/`; add the `hr-inbox` cron it prints.
- **Libraries:** python-docx and openpyxl, from the `documents` extra.

## Tested

- **Fakes plus real LibreOffice** (`tests/test_hr.py`, 25 tests):
  - working-day LOP
  - every bad row listed, and nothing made
  - `/hr payslip skip` makes only the good rows; a changed sheet or a missing column makes nothing
  - interviews: one Teams link, each candidate only on their own slot, overlaps and past times refused
  - with `hr.mailbox`, candidates are mailed From it with an .ics; the slots stay on your calendar
  - placeholders split across runs
  - PDFs made, and the agent's reply carries no figures
  - `test` emails only you, `yes` emails each person their own PDF
  - with `hr.mailbox` set, every slip goes out From it
  - no pay or bank numbers in the log
  - expiry
- Breaking the LOP rule or the test-mail target turns tests red.
- **HR inbox** (fakes): sorting rules, a colleague's reply clears a waiting mail but the sender's
  follow-up does not, your own sent mail left out, a quiet sweep says nothing, the morning reminder
  once a day, `done` and `list`.
- **Replies** (fakes, `tests/test_reply.py`): Gemini's request carries no name, email, phone, amount
  or ID from the mail; 19 Indian formats hidden while dates and times stay; near-miss placeholders
  fixed; an invented placeholder is asked again, an invented amount on every model refuses the draft;
  templates and the applications batch make no model call; one yes sends once, in the thread, From
  the HR mailbox; `/hr list` with waiting, expired and answered items. **Not run live yet.**
- **Live, 2026-11-23:** `/hr inbox show` on your mailbox: 21 HR mails of the last 14 days sorted
  (1 urgent, 4 people, 3 campus, 10 applications, 3 other); 2 waiting for a reply; a second sweep
  printed nothing.
- **Live, 2026-11-22:** your template, converted, rendered correctly with 3 sample rows. After
  Mail.Send was granted, `/hr payslip test` emailed two sample slips to you from Outlook.
