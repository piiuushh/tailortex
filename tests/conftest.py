from pathlib import Path

import pytest

from tailortex.compiler import CompileResult

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).parent.parent


@pytest.fixture
def bajaj():
    return (FIX / "bajaj_resume.tex").read_text()


@pytest.fixture
def jake():
    return (FIX / "jake_resume.tex").read_text()


@pytest.fixture
def jd():
    return (ROOT / "examples" / "sample_jd.txt").read_text()


class FakeCompiler:
    """Pretends to compile: pages = f(tex), fails when `bad` substring present."""

    engine = "fake"
    available = True

    def __init__(self, pages_fn=lambda tex: 1, bad: str | None = None):
        self.pages_fn = pages_fn
        self.bad = bad
        self.calls = 0

    def compile(self, tex, jobname="resume"):
        self.calls += 1
        if self.bad and self.bad in tex:
            return CompileResult(False, None, 0, "! Undefined control sequence.", "fake")
        return CompileResult(True, b"%PDF-fake", self.pages_fn(tex), "", "fake")


@pytest.fixture
def fake_compiler():
    return FakeCompiler
