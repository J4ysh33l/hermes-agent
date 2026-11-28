"""Word → PDF with LibreOffice (``soffice``), all files of a batch in one run. Each batch uses its
own LibreOffice profile folder, so a running LibreOffice never blocks it.

The letters are set in Poppins (headings) and Segoe UI (text). A machine without them draws the PDF in
some other font, wider or narrower, so parts of the letter look a different size from the Word file.
``fonts/`` carries Poppins and Selawik (Microsoft's free stand-in for Segoe UI, same letter widths; both
under the SIL Open Font License) and LibreOffice is pointed at them, Segoe UI read as Selawik, through
fontconfig (Linux and WSL; a Windows machine has Segoe UI already). The machine's own fonts stay in use.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from hermes_platform.resolver import locate_command

TIMEOUT = 300
FONTS = Path(__file__).parent / "fonts"
FONTS_CONF = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">{system}</include>
  <dir>{fonts}</dir>
  <match target="pattern">
    <test qual="any" name="family"><string>Segoe UI</string></test>
    <edit name="family" mode="assign" binding="strong"><string>Selawik</string></edit>
  </match>
  <match target="pattern">
    <test qual="any" name="family"><string>Segoe UI Semibold</string></test>
    <edit name="family" mode="assign" binding="strong"><string>Selawik</string></edit>
    <edit name="weight" mode="assign" binding="strong"><const>semibold</const></edit>
  </match>
</fontconfig>
"""


def font_env(folder: Path) -> dict[str, str]:
    """The environment for LibreOffice: the machine's own fontconfig setup plus ``fonts/``."""
    env = dict(os.environ)
    if not FONTS.is_dir():
        return env
    system = os.environ.get("FONTCONFIG_FILE") or "/etc/fonts/fonts.conf"
    conf = folder / "fonts.conf"
    conf.write_text(FONTS_CONF.format(system=system, fonts=FONTS.resolve()), encoding="utf-8")
    env["FONTCONFIG_FILE"] = str(conf)
    return env


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
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False,
                              env=font_env(Path(profile)))
    pdfs = [out_dir / (d.stem + ".pdf") for d in docs]
    missing = [p.name for p in pdfs if not p.is_file()]
    if done.returncode or missing:
        raise PdfError(f"LibreOffice could not convert {', '.join(missing) or 'the files'}: {done.stderr[-300:]}")
    return pdfs
