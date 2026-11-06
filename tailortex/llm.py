"""LLM backends. Gemini is the real one; FakeLLM powers the offline test suite."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Callable, Protocol

from .schema import TailorPlan

# gemini-3.1-flash-lite was the only free-tier model answering reliably in testing (Nov 2026)
DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_FALLBACKS = ["gemini-flash-latest", "gemini-flash-lite-latest"]


class LLM(Protocol):
    name: str

    def plan(self, system: str, prompt: str) -> TailorPlan: ...


def parse_plan(raw: str) -> TailorPlan:
    """Parse model output into a TailorPlan, tolerating code fences / chatter."""
    raw = raw.strip()
    try:
        return TailorPlan.model_validate_json(raw)
    except Exception:
        pass
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("LLM response contained no JSON object")
    return TailorPlan.model_validate(json.loads(m.group(0)))


class GeminiLLM:
    """Google Gemini via the official ``google-genai`` SDK with JSON-schema output.

    ``GEMINI_MODEL`` picks the model; ``GEMINI_FALLBACK_MODELS`` (comma separated)
    is tried in order if the primary model is retired or unavailable.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 fallbacks: list[str] | None = None, temperature: float = 0.3, retries: int = 3):
        from google import genai  # imported lazily so tests don't need the SDK

        key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("No Gemini API key. Set GEMINI_API_KEY (free key: https://aistudio.google.com/apikey).")
        from google.genai import types

        # without a timeout one stalled request can hang the whole run for minutes
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60_000))
        self.model = model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL
        env_fb = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "").split(",") if m.strip()]
        self.fallbacks = fallbacks if fallbacks is not None else (env_fb or DEFAULT_FALLBACKS)
        self.temperature = temperature
        self.retries = retries
        self.name = f"gemini:{self.model}"

    def _call(self, model: str, system: str, prompt: str) -> str:
        from google.genai import types

        resp = self.client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=self.temperature,
                response_mime_type="application/json",
                response_schema=TailorPlan,
            ),
        )
        if not resp.text:
            raise RuntimeError(f"Empty response from {model} (possibly blocked by safety filters)")
        return resp.text

    def plan(self, system: str, prompt: str) -> TailorPlan:
        last: Exception | None = None
        for model in [self.model, *self.fallbacks]:
            for attempt in range(self.retries):
                try:
                    out = parse_plan(self._call(model, system, prompt))
                    self.name = f"gemini:{model}"
                    return out
                except Exception as e:  # noqa: BLE001 - classify below
                    last = e
                    code = getattr(e, "code", None)
                    msg = str(e)
                    if code == 404 or "NOT_FOUND" in msg:
                        break  # model retired/unknown -> next fallback
                    if code in (400, 401, 403):
                        raise
                    if code in (429, 503, 504) or any(s in msg for s in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE")):
                        break  # overloaded / quota / timeout -> fail over to the next model right away
                    time.sleep(2 ** attempt)
        raise RuntimeError(f"Gemini request failed: {last}")


def list_gemini_models(api_key: str | None = None) -> list[str]:
    from google import genai

    client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    names = []
    for m in client.models.list():
        actions = getattr(m, "supported_actions", None) or []
        if not actions or "generateContent" in actions:
            names.append(m.name.removeprefix("models/"))
    return sorted(names)


DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class OpenAILLM:
    """OpenAI chat completions in JSON mode; the plan schema is appended to the system prompt."""

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 fallbacks: list[str] | None = None, temperature: float = 0.3, retries: int = 2):
        from openai import OpenAI  # imported lazily

        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("No OpenAI API key. Set OPENAI_API_KEY.")
        self.client = OpenAI(api_key=key, max_retries=0, timeout=90)
        self.model = model or os.getenv("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL
        self.fallbacks = fallbacks if fallbacks is not None else []
        self.temperature = temperature
        self.retries = retries
        self.name = f"openai:{self.model}"

    def _call(self, model: str, system: str, prompt: str) -> str:
        schema = json.dumps(TailorPlan.model_json_schema())
        resp = self.client.chat.completions.create(
            model=model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": f"{system}\n\nReturn ONLY a JSON object matching this JSON schema:\n{schema}"},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.choices[0].message.content
        if not text:
            raise RuntimeError(f"Empty response from {model}")
        return text

    def plan(self, system: str, prompt: str) -> TailorPlan:
        last: Exception | None = None
        for model in [self.model, *self.fallbacks]:
            for attempt in range(self.retries):
                try:
                    out = parse_plan(self._call(model, system, prompt))
                    self.name = f"openai:{model}"
                    return out
                except Exception as e:  # noqa: BLE001
                    last = e
                    code = getattr(e, "status_code", None)
                    if code in (400, 401, 403, 404):
                        raise
                    time.sleep(2 ** attempt * (5 if code == 429 else 1))
        raise RuntimeError(f"OpenAI request failed: {last}")


class FallbackLLM:
    """Try each backend in order; the first one that returns a plan wins."""

    def __init__(self, backends: list[LLM]):
        if not backends:
            raise RuntimeError("No LLM backends configured.")
        self.backends = backends
        self.name = backends[0].name
        self.errors: list[str] = []

    def plan(self, system: str, prompt: str) -> TailorPlan:
        self.errors = []
        for b in self.backends:
            try:
                out = b.plan(system, prompt)
                self.name = b.name
                return out
            except Exception as e:  # noqa: BLE001 - any failure -> next provider
                self.errors.append(f"{b.name}: {str(e)[:200]}")
        raise RuntimeError("All providers failed. " + " | ".join(self.errors))


class CachedLLM:
    """Memoise plans by hash(prompt + provider names). Identical resume+JD+facts => instant, free result.

    ``store`` is any dict-like (default: JSON files in ``$TAILORTEX_CACHE_DIR`` or ``.tailortex_cache``).
    API keys are never part of the cache key or the stored data.
    """

    def __init__(self, inner: LLM, store=None):
        self.inner = inner
        self.store = store if store is not None else DiskStore()
        self.name = inner.name
        self.hit = False

    def _key(self, system: str, prompt: str) -> str:
        ident = "|".join(getattr(b, "name", "") for b in getattr(self.inner, "backends", [self.inner]))
        return hashlib.sha256(f"{ident}\0{system}\0{prompt}".encode()).hexdigest()

    def plan(self, system: str, prompt: str) -> TailorPlan:
        k = self._key(system, prompt)
        raw = self.store.get(k)
        if raw:
            try:
                self.hit = True
                self.name = f"cache ({self.inner.name})"
                return TailorPlan.model_validate_json(raw)
            except Exception:  # corrupt entry -> recompute
                pass
        self.hit = False
        out = self.inner.plan(system, prompt)
        self.name = self.inner.name
        self.store[k] = out.model_dump_json()
        return out


class DiskStore:
    def __init__(self, path: str | None = None):
        self.dir = Path(path or os.getenv("TAILORTEX_CACHE_DIR") or ".tailortex_cache")

    def get(self, k: str) -> str | None:
        f = self.dir / f"{k}.json"
        return f.read_text(encoding="utf-8") if f.exists() else None

    def __setitem__(self, k: str, v: str) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{k}.json").write_text(v, encoding="utf-8")
        except OSError:
            pass  # caching is best-effort


def build_llm(gemini_key: str = "", openai_key: str = "", gemini_model: str | None = None,
              openai_model: str | None = None, cache_store=None, cache: bool = True) -> LLM:
    """Combine whichever keys are present into one fallback chain (OpenAI first, then Gemini)."""
    backends: list[LLM] = []
    if openai_key:
        backends.append(OpenAILLM(api_key=openai_key, model=openai_model))
    if gemini_key:
        backends.append(GeminiLLM(api_key=gemini_key, model=gemini_model))
    if not backends:
        raise RuntimeError("Add a Gemini or OpenAI API key.")
    llm: LLM = backends[0] if len(backends) == 1 else FallbackLLM(backends)
    return CachedLLM(llm, cache_store) if cache else llm


class FakeLLM:
    """Deterministic backend for tests and demos: returns a fixed plan or calls a function."""

    name = "fake"

    def __init__(self, plan: TailorPlan | Callable[[str, str], TailorPlan]):
        self._plan = plan
        self.calls: list[tuple[str, str]] = []

    def plan(self, system: str, prompt: str) -> TailorPlan:
        self.calls.append((system, prompt))
        return self._plan(system, prompt) if callable(self._plan) else self._plan
