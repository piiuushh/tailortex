"""Real LaTeX compilation - skipped automatically when no engine is installed."""

import pytest

from tailortex import latex
from tailortex.cli import main
from tailortex.compiler import Compiler
from tailortex.engine import Options, tailor
from tailortex.llm import FakeLLM

from .test_engine import plan_from_prompt

comp = Compiler()
needs_tex = pytest.mark.skipif(not comp.available, reason="no LaTeX engine installed")


@needs_tex
@pytest.mark.parametrize("name", ["bajaj", "jake"])
def test_fixtures_compile_to_one_page(name, request):
    res = comp.compile(request.getfixturevalue(name))
    assert res.ok, res.log
    assert res.pages == 1


@needs_tex
def test_tailored_resume_compiles(bajaj, jd):
    res = tailor(bajaj, jd, FakeLLM(plan_from_prompt), opts=Options(), compiler=comp)
    assert res.compile.ok, res.compile.log
    assert res.compile.pages == 1
    assert res.pdf.startswith(b"%PDF")


def test_cli_inspect(tmp_path, bajaj, capsys):
    f = tmp_path / "r.tex"
    f.write_text(bajaj)
    assert main(["inspect", str(f)]) == 0
    assert "Round-trip check" in capsys.readouterr().out


def test_render_reorder_compiles_structurally(bajaj):
    doc = latex.parse(bajaj)
    out = latex.render(doc, latex.EditSet(section_order=["Projects", "Experience", "Education", "Skills Summary"]))
    assert out.count("\\begin{") == bajaj.count("\\begin{") - bajaj.count("% \\begin{")
