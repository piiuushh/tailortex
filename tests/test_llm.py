from pathlib import Path

import pytest

from tailortex.llm import CachedLLM, DiskStore, FakeLLM, FallbackLLM, parse_plan

PLAN = parse_plan((Path(__file__).parent.parent / "examples" / "sample_plan.json").read_text("utf-8"))


class Boom:
    name = "boom"

    def __init__(self):
        self.calls = 0

    def plan(self, system, prompt):
        self.calls += 1
        raise RuntimeError("503 overloaded")


def test_fallback_uses_next_provider():
    bad, good = Boom(), FakeLLM(PLAN)
    llm = FallbackLLM([bad, good])
    assert llm.plan("s", "p") == PLAN
    assert bad.calls == 1 and llm.name == "fake"


def test_fallback_all_fail_lists_errors():
    llm = FallbackLLM([Boom(), Boom()])
    with pytest.raises(RuntimeError, match="All providers failed"):
        llm.plan("s", "p")


def test_cache_hits_skip_the_model():
    inner = FakeLLM(PLAN)
    store: dict = {}
    llm = CachedLLM(inner, store)
    llm.plan("s", "p")
    assert llm.hit is False
    out = llm.plan("s", "p")
    assert llm.hit is True and out == PLAN and len(inner.calls) == 1
    llm.plan("s", "different prompt")
    assert len(inner.calls) == 2


def test_disk_store_roundtrip(tmp_path):
    inner = FakeLLM(PLAN)
    llm = CachedLLM(inner, DiskStore(str(tmp_path)))
    llm.plan("s", "p")
    llm2 = CachedLLM(FakeLLM(PLAN), DiskStore(str(tmp_path)))
    llm2.plan("s", "p")
    assert llm2.hit is True


def test_build_llm_tries_openai_first():
    from tailortex.llm import build_llm

    llm = build_llm(gemini_key="g-test", openai_key="sk-test", cache=False)
    assert [b.name.split(":")[0] for b in llm.backends] == ["openai", "gemini"]
