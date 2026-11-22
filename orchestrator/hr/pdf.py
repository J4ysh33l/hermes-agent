"""Word → PDF with LibreOffice (``soffice``), all files of a batch in one run. Each batch uses its
own LibreOffice profile folder, so a running LibreOffice never blocks it."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from hermes_platform.resolver import locate_command

TIMEOUT = 300


class PdfError(Exception):
    pass


def convert(docs: list[Path], out_dir: Path) -> list[Path]:
    found = locate_command("soffice")
    if not found.found:
        raise PdfError("LibreOffice (soffice) is not installed on this machine; install it to make PDFs.")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        cmd = [*found.command, f"-env:UserInstallation=file://{profile}", "--headless", "--convert-to", "pdf",
               "--outdir", str(out_dir), *map(str, docs)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    pdfs = [out_dir / (d.stem + ".pdf") for d in docs]
    missing = [p.name for p in pdfs if not p.is_file()]
    if done.returncode or missing:
        raise PdfError(f"LibreOffice could not convert {', '.join(missing) or 'the files'}: {done.stderr[-300:]}")
    return pdfs
