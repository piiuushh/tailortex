"""Compile .tex -> PDF with Tectonic (preferred), latexmk or pdflatex."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

ENGINES = ("tectonic", "latexmk", "pdflatex", "xelatex")


@dataclass
class CompileResult:
    ok: bool
    pdf: bytes | None
    pages: int
    log: str
    engine: str


def find_engine(preferred: str | None = None) -> str | None:
    preferred = preferred or os.getenv("TAILORTEX_ENGINE")
    order = [preferred] if preferred else []
    order += [e for e in ENGINES if e != preferred]
    for e in order:
        if e == "latexmk" and not shutil.which("perl"):
            continue  # latexmk is a Perl script; without perl it can't run
        if e and shutil.which(e):
            return e
    return None


def count_pages(pdf: bytes) -> int:
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf)) as p:
            return len(p.pages)
    except Exception:
        return len(re.findall(rb"/Type\s*/Page(?!s)", pdf))


def _is_miktex(engine: str) -> bool:
    try:
        out = subprocess.run([engine, "--version"], capture_output=True, text=True, timeout=20,
                             stdin=subprocess.DEVNULL).stdout
        return "MiKTeX" in out
    except Exception:
        return False


def _no_shell(miktex: bool) -> str:
    return "-disable-write18" if miktex else "-no-shell-escape"


def _cmd(engine: str, tex: str, outdir: str, miktex: bool = False) -> list[str]:
    if engine == "tectonic":  # tectonic never shell-escapes unless -Z shell-escape is passed
        return ["tectonic", "--outdir", outdir, "--keep-logs", tex]
    if engine == "latexmk":
        return ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", f"-outdir={outdir}",
                f"-pdflatex=pdflatex {_no_shell(miktex)} %O %S", tex]
    return [engine, "-interaction=nonstopmode", "-halt-on-error", _no_shell(miktex),
            f"-output-directory={outdir}", tex]


# Only these variables reach the LaTeX process, so a malicious document can't read secrets
# (API keys, cloud credentials) out of its own environment (/proc/self/environ).
_ENV_ALLOW = ("PATH", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
              "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "LANG", "LC_ALL", "TEXMFHOME", "TEXMFVAR", "TEXMFCONFIG",
              "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS", "OS", "PROCESSOR_ARCHITECTURE")


def _sandbox_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() in _ENV_ALLOW}
    # TeX Live / kpathsea: no reading or writing outside the working dir, no shell escape
    env.update(openin_any="p", openout_any="p", shell_escape="f")
    return env


class Compiler:
    """``strict=True`` (web app) scans every source with ``security.check_tex`` and refuses unsafe ones."""

    def __init__(self, engine: str | None = None, assets_dir: str | Path | None = None, timeout: int = 180,
                 strict: bool = False):
        self.engine = find_engine(engine)
        self.assets_dir = Path(assets_dir) if assets_dir else None
        self.timeout = timeout
        self.strict = strict
        self.miktex = bool(self.engine) and self.engine != "tectonic" and _is_miktex(
            "pdflatex" if self.engine == "latexmk" else self.engine)

    @property
    def available(self) -> bool:
        return self.engine is not None

    def compile(self, tex_source: str, jobname: str = "resume") -> CompileResult:
        if not self.engine:
            return CompileResult(False, None, 0, "No LaTeX engine found (install tectonic: https://tectonic-typesetting.github.io)", "none")
        if self.strict:
            from .security import check_tex

            problems = check_tex(tex_source)
            if problems:
                return CompileResult(False, None, 0, "Refused to compile: " + "; ".join(problems), self.engine)
        with tempfile.TemporaryDirectory() as d:
            # copy class/style/image files that sit next to the resume
            if self.assets_dir and self.assets_dir.is_dir():
                for f in self.assets_dir.iterdir():
                    if f.is_file() and f.suffix.lower() in {".cls", ".sty", ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".bib", ".otf", ".ttf"}:
                        shutil.copy(f, d)
            tex_path = Path(d) / f"{jobname}.tex"
            tex_path.write_text(tex_source, encoding="utf-8")
            try:
                proc = subprocess.run(_cmd(self.engine, tex_path.name, d, self.miktex), cwd=d, capture_output=True,
                                      text=True, timeout=self.timeout, stdin=subprocess.DEVNULL,
                                      env=_sandbox_env(), errors="replace")
                log = (proc.stdout or "") + (proc.stderr or "")
            except subprocess.TimeoutExpired:
                return CompileResult(False, None, 0, "LaTeX compilation timed out", self.engine)
            pdf_path = Path(d) / f"{jobname}.pdf"
            if proc.returncode != 0 or not pdf_path.exists():
                return CompileResult(False, None, 0, _error_excerpt(log), self.engine)
            pdf = pdf_path.read_bytes()
            return CompileResult(True, pdf, count_pages(pdf), _error_excerpt(log, errors_only=False), self.engine)


def _error_excerpt(log: str, errors_only: bool = True, max_lines: int = 25) -> str:
    lines = log.splitlines()
    idx = [i for i, l in enumerate(lines) if l.startswith("!") or "error:" in l.lower()]
    if idx:
        i = idx[0]
        return "\n".join(lines[i : i + max_lines])
    return "" if not errors_only else "\n".join(lines[-max_lines:])
