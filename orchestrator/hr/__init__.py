"""HR: payslips from your monthly salary sheet, emailed from your Outlook after you approve;
interviews on one Teams link; the HR inbox sorted by script; replies in the mail's thread.

Modules:
- ``settings``  the ``hr:`` section of brief.yaml (weekly offs, holidays, mail text, limits).
- ``sheet``     the salary sheet (.xlsx/.csv) → rows; extra columns such as bank details are ignored.
- ``payroll``   rows → slip figures by fixed rules (working-day LOP); bad rows stop the run.
- ``docfill``   fills ``{{field}}`` in a Word template (also for offer and other letters).
- ``pdf``       Word → PDF with LibreOffice.
- ``payslips``  one run: check, fill, convert, save the batch for approval (no amounts in its reply).
- ``inbox``     mail to the HR mailbox: sorted by fixed rules, waiting-for-reply tracking, the sweep.
- ``redact``    hides names, emails, numbers before Gemini sees a mail; checks its draft before putting them back.
- ``reply``     /hr reply: fetch the mail, a Gemini draft or a template, send in the thread From the HR mailbox.
- ``chat``      /hr list · payslip · interview · inbox · reply; /hr payslip (make · check · show · test · yes · no · skip), and the run Hermes' agent starts with your sheet.
- ``cli``       ``python -m orchestrator.hr <words>``: the same commands on the host.
"""
