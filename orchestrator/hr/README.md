# HR: payslips

Payslips from your monthly salary sheet, emailed from your Outlook after you approve. Scripts do
everything. **No AI model sees pay or bank details.**

## Each month

1. Send Hermes the sheet (.xlsx or .csv) and say the period and the pay date: "payslips for
   1–30 Nov, paid 2 Dec". The agent passes only the file path to
   `$HERMES_HOME/scripts/hr_payslips.py` (skill `orchestrator:hr-payslips`).
   On the host you can also run `python -m orchestrator.hr payslips <sheet> 01/11/2026 30/11/2026 02/12/2026`.
2. Before making anything, the script checks the template, the columns and every row. It lists
   **every** problem in one reply: missing columns, missing or `0` values, bad dates and numbers,
   Basic + HRA ≠ Compensation, LOP over the working days, and duplicate emails, one line per
   employee. Nothing is made yet. It also warns about blank bank details and mid-period joiners.
   `/hr check <sheet> <from> <to>` runs only this check.
   - **Only some rows wrong?** The reply offers `/hr skip`: it makes everyone else's slips and
     leaves those employees out. Their names stay listed in `/hr show` until you send a fixed sheet.
     Both rows that share an email are left out. If the sheet changes before `/hr skip`, nothing
     is made and the new list is offered instead. The offer expires with the batch (2 hours).
   - Missing columns or a missing template can't be skipped: fix them and send the sheet again.
3. It makes one PDF per person in `$HERMES_HOME/hr/payslips/<YYYY-MM>/`.
4. It replies with counts only.
5. `/hr show`: name, email and net pay for each person, plus the total.
6. `/hr test`: two sample slips are emailed to **you**. `/hr test all` emails every slip to you.
7. `/hr yes`: each person gets their own slip from your Outlook. `/hr yes 1-10` sends only those.
   `/hr no` cancels. A batch expires after 2 hours.

## The sheet

| Column | Needed | Notes |
|---|---|---|
| Employee Name, Position, DOJ, Email | yes | DOJ as dd/mm/yyyy. A designation of `0` counts as missing |
| Compensation, Basic, HRA | yes | Basic + HRA must equal Compensation |
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

## Setup

- **Outlook:** the Entra app needs delegated **Mail.Send** with admin consent. Then sign in once
  more: `python -m orchestrator.brief auth microsoft`.
- **Install:** `orchestrator/brief/install.sh` writes the launcher and creates `$HERMES_HOME/hr/templates/`.
- **Libraries:** python-docx and openpyxl, from the `documents` extra.

## Tested

- **Fakes plus real LibreOffice** (`tests/test_hr.py`, 13 tests):
  - working-day LOP
  - every bad row listed, and nothing made
  - `/hr skip` makes only the good rows; a changed sheet or a missing column makes nothing
  - placeholders split across runs
  - PDFs made, and the agent's reply carries no figures
  - `test` emails only you, `yes` emails each person their own PDF
  - no pay or bank numbers in the log
  - expiry
- Breaking the LOP rule or the test-mail target turns tests red.
- **Live, 2026-11-22:** your template, converted, rendered correctly with 3 sample rows. After
  Mail.Send was granted, `/hr test` emailed two sample slips to you from Outlook.
