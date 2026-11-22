---
name: hr-payslips
description: "Make monthly payslips from the salary sheet the user sends; they approve sending with /hr."
version: 1.0.0
author: orchestrator (fork-only)
---

# Payslips from a salary sheet (prepare only)

Use this when the user sends a salary sheet (.xlsx or .csv) and asks for payslips. You need the
file's path, the pay period and the pay date. Ask for any you don't have; dates are dd/mm/yyyy.

```bash
python3 "${HERMES_HOME:-$HOME/.hermes}/scripts/hr_payslips.py" "<sheet path>" <from> <to> <pay date>
```

Example: `... hr_payslips.py /path/nov.xlsx 01/11/2026 30/11/2026 02/12/2026`

It checks every row, makes one PDF per employee and prints counts and problems only. Show its
output to the user as printed. It cannot email anyone: the user reviews with `/hr show`, gets
samples with `/hr test` and sends with `/hr yes`.

- Never open, read, summarise or repeat the sheet's contents yourself: salary and bank details
  must not pass through you. Only pass the file path to the script.
- If it lists problems, tell the user to fix those rows and send the sheet again.
- Never compute pay, LOP or totals yourself, and never try to send the slips another way.
