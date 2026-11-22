"""Fills ``{{field}}`` placeholders in a Word file, everywhere: body, tables (nested too), headers
and footers. Word often splits a placeholder over several runs; a paragraph that holds one is
rewritten into its first run, which keeps that run's font. A placeholder with no value stops the
fill and names it, so a typo in the template never produces a document with a blank in it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}")


class TemplateError(Exception):
    pass


def _paragraphs(container) -> Iterator:
    yield from container.paragraphs
    for table in getattr(container, "tables", ()):
        for row in table.rows:
            for cell in row.cells:
                yield from _paragraphs(cell)


def _all_paragraphs(document) -> Iterator:
    yield from _paragraphs(document)
    for section in document.sections:
        for part in (section.header, section.footer, section.first_page_header, section.first_page_footer):
            yield from _paragraphs(part)


def fields(path: Path) -> set[str]:
    """Every placeholder name in the template."""
    import docx

    return {m for p in _all_paragraphs(docx.Document(str(path))) for m in PLACEHOLDER.findall(p.text)}


def fill(template: Path, values: dict[str, str], out: Path) -> None:
    import docx

    document = docx.Document(str(template))
    missing = sorted(fields(template) - values.keys())
    if missing:
        raise TemplateError("The template has fields with no value: " + ", ".join(missing))
    for paragraph in _all_paragraphs(document):
        if "{{" not in paragraph.text:  # also skips a merged cell's paragraph already filled
            continue
        text = PLACEHOLDER.sub(lambda m: values[m.group(1)], paragraph.text)
        runs = paragraph.runs
        runs[0].text = text
        for run in runs[1:]:
            run.text = ""
    out.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out))
