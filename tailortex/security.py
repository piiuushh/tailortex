"""Hardening for running tailortex as a public web app.

Anyone can upload a .tex file, and LaTeX is a programming language that can read files
(``\\verbatiminput{/app/.env}``), run shell commands (``\\write18``) and hide what it is doing
(``\\csname``, ``^^`` escapes, ``\\catcode``). Uploaded sources are scanned here before they are
compiled; the compiler adds a second layer (no shell escape, scrubbed environment, paranoid file access).
"""

from __future__ import annotations

import re

MAX_TEX_BYTES = 200_000      # a real resume is ~5-30 KB
MAX_JD_CHARS = 30_000
MAX_FACTS_CHARS = 5_000

# control sequences that read/write files, run code, or let an attacker build other commands at runtime
BLOCKED = (
    "openin", "openout", "read", "readline", "write", "immediate", "closein", "closeout", "newread", "newwrite",
    "write18", "ShellEscape", "directlua", "luaexec", "luadirect", "latelua",
    "catcode", "lccode", "uccode", "csname", "scantokens", "everyeof", "endlinechar", "string",
    "verbatiminput", "VerbatimInput", "BVerbatimInput", "LVerbatimInput", "lstinputlisting", "inputminted",
    "includepdf", "CatchFileDef", "CatchFileEdef", "filecontents", "IfFileExists", "InputIfFileExists",
    "pdffiledump", "pdfmdfivesum", "filedump", "filemdfivesum", "pdffilesize", "filesize", "pdffilemoddate",
    "filemoddate", "special", "pdfliteral", "import", "subimport", "inputfrom", "includefrom", "subinputfrom",
    "jobname", "detokenize", "unexpanded",
)
BLOCKED_PACKAGES = {"shellesc", "pythontex", "minted", "luacode", "bashful", "catchfile", "verbatimbox",
                    "fancyvrb", "listings", "filecontents", "pdfpages", "import", "standalone", "currfile",
                    "write18", "luatextra", "markdown", "gnuplottex", "sagetex", "embedfile", "attachfile"}
# file-taking commands are allowed only with a bare file name (no paths), e.g. \input{glyphtounicode}
FILE_COMMANDS = ("input", "include", "includeonly", "includegraphics", "bibliography", "addbibresource")
SAFE_NAME = r"[A-Za-z0-9][A-Za-z0-9_\-]*(?:\.(?:tex|png|jpe?g|pdf|bib))?"

_blocked_re = re.compile(r"\\(" + "|".join(sorted(BLOCKED, key=len, reverse=True)) + r")(?![A-Za-z])")
_file_re = re.compile(r"\\(" + "|".join(FILE_COMMANDS) + r")(?![A-Za-z])")
_file_ok = re.compile(r"\\(?:" + "|".join(FILE_COMMANDS) + r")\s*(?:\[[^\]\n]{0,200}\])?\s*\{\s*" + SAFE_NAME
                      + r"(?:\s*,\s*" + SAFE_NAME + r")*\s*\}")
_pkg_re = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}")


def check_tex(src: str) -> list[str]:
    """Return the reasons an uploaded .tex is unsafe to compile on a shared server ([] = OK)."""
    problems: list[str] = []
    if len(src.encode("utf-8", "ignore")) > MAX_TEX_BYTES:
        problems.append(f"file is larger than {MAX_TEX_BYTES // 1000} KB")
    if "^^" in src:
        problems.append("'^^' character escapes are not allowed")
    if "\x00" in src:
        problems.append("binary content is not allowed")
    for name in sorted({m.group(1) for m in _blocked_re.finditer(src)}):
        problems.append(f"\\{name} is not allowed (file access / code execution)")
    for m in _file_re.finditer(src):
        if not _file_ok.match(src, m.start()):
            problems.append(f"\\{m.group(1)} may only take a plain file name (no paths or macros)")
            break
    for m in _pkg_re.finditer(src):
        for pkg in (p.strip() for p in m.group(1).split(",")):
            if pkg in BLOCKED_PACKAGES:
                problems.append(f"package '{pkg}' is not allowed")
    # aliases such as \let\x\input or \def\x#1{\input{#1}} are caught above: every file command
    # must be directly followed by a plain {name}
    return problems


_KEY_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{10,}"),                 # Google
    re.compile(r"sk-(?:proj-|svcacct-|admin-)?[0-9A-Za-z_\-*]{6,}"),  # OpenAI (also masked forms)
    re.compile(r"(?i)(api[_-]?key|authorization)\s*[:=]\s*(bearer\s+)?\S+"),
    re.compile(r"(?i)\bbearer\s+\S+"),
]


def redact(text: str) -> str:
    """Remove anything that looks like an API key before showing or logging a message."""
    for p in _KEY_PATTERNS:
        text = p.sub("[redacted]", text)
    return text
