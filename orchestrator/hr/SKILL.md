---
name: hr-payslips
description: "Make monthly payslips from the salary sheet the user sends; they approve sending with /hr."
version: 1.0.0
author: orchestrator (fork-only)
---

# Payslips from a salary sheet (prepare only)

Use this when the user sends a salary sheet FILE (.xlsx or .csv) and asks for payslips. You need
the file's path, the month and the pay date. Ask for any you don't have; the pay date is dd/mm/yyyy.

```bash
python3 "${HERMES_HOME:-$HOME/.hermes}/scripts/hr_payslips.py" "<sheet path>" <month> <pay date>
```

Example: `... hr_payslips.py /path/nov.xlsx November 02/12/2026` (or two dates instead of the month:
`01/11/2026 30/11/2026`). If the user wants to paste the table instead, tell them to paste it after
`/hr payslip November <pay date>` so it goes to the script, not to you.

It first checks the whole sheet (template, missing columns, every row) and, if anything is
wrong, makes nothing and lists every problem at once; otherwise it makes one PDF per employee.
It prints counts and problems only. To only check a sheet, run
`python3 -m orchestrator.hr payslip check "<sheet path>" <from> <to>` from the repository, or ask the user to
type `/hr payslip check <path> <from> <to>`. Show its
output to the user as printed. It cannot email anyone: the user reviews with `/hr payslip show`, gets
samples with `/hr payslip test` and sends with `/hr payslip yes`.

- Never open, read, summarise or repeat the sheet's contents yourself: salary and bank details
  must not pass through you. Only pass the file path to the script.
- If it lists problems, show them as printed. If it offers `/hr payslip skip`, the user decides: they can
  type `/hr payslip skip` to leave those employees out, or fix the rows and send the sheet again. Never
  run skip for them.
- Never compute pay, LOP or totals yourself, and never try to send the slips another way.
