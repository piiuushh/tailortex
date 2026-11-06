"""Orchestration: parse -> plan (LLM) -> guard -> render -> compile -> fit to page."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import latex
from .compiler import CompileResult, Compiler
from .guards import SAFE_COMMANDS, GuardContext, Verdict, commands_in, contains_term, validate_edit
from .llm import LLM
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schema import TailorPlan

DEFAULT_LOCKED = ("education",)
SKILL_HINT = re.compile(r"skill|technolog|tool|competenc", re.I)


@dataclass
class Options:
    locked_sections: tuple[str, ...] = DEFAULT_LOCKED  # case-insensitive substrings
    allow_drops: bool = True
    allow_section_reorder: bool = True
    # "ai" = model decides | "keep" = original order | "experience" / "education" = fixed presets
    section_order: str = "ai"
    allow_bullet_reorder: bool = True
    max_pages: int = 1
    compile: bool = True


@dataclass
class TailorResult:
    original_tex: str
    tex: str
    plan: TailorPlan
    verdicts: list[Verdict]
    edits: latex.EditSet
    keywords: list[str]
    coverage_before: float
    coverage_after: float
    matched_after: list[str]
    missing_after: list[str]
    unsupported_keywords: list[str]  # JD terms nowhere in resume/facts = real gaps
    dropped_by_llm: list[str] = field(default_factory=list)
    dropped_for_fit: list[str] = field(default_factory=list)
    reverted_for_compile: list[str] = field(default_factory=list)
    compile: CompileResult | None = None
    warnings: list[str] = field(default_factory=list)
    model: str = ""

    @property
    def pdf(self) -> bytes | None:
        return self.compile.pdf if self.compile and self.compile.ok else None


# --------------------------------------------------------------------------- #


def keyword_coverage(text: str, keywords: list[str]) -> tuple[float, list[str], list[str]]:
    low = text.lower()
    hit = [k for k in keywords if contains_term(low, k)]
    miss = [k for k in keywords if k not in hit]
    return (len(hit) / len(keywords) if keywords else 0.0), hit, miss


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for k in items:
        k2 = k.strip()
        if k2 and k2.lower() not in seen:
            seen.add(k2.lower())
            out.append(k2)
    return out


def _is_locked(section: str, opts: Options) -> bool:
    return any(l.lower() in section.lower() for l in opts.locked_sections)


SUMMARY = r"^(professional |career |executive )?(summary|objective|profile)\b"  # not "Skills Summary"
PRESET_ORDERS = {
    # experienced candidates: work history first
    "experience": (SUMMARY, "experience|employment|work", "project", "skill|technolog|competenc",
                   "education|academic", "achiev|award|certif|leadership|extra"),
    # freshers / recent graduates: degree first
    "education": (SUMMARY, "education|academic", "project", "skill|technolog|competenc",
                  "experience|employment|work", "achiev|award|certif|leadership|extra"),
}


def preset_order(names: list[str], mode: str) -> list[str]:
    """Reorder section names by a preset; unmatched sections keep their relative order at the end."""
    pats = PRESET_ORDERS.get(mode)
    if not pats:
        return names

    def rank(n: str) -> int:
        for i, p in enumerate(pats):
            if re.search(p, n, re.I):
                return i
        return len(pats)

    return sorted(names, key=rank)  # sorted() is stable


# words a user might use for each kind of section, checked in this order
SECTION_WORDS = (
    ("experience|employment|work", r"experience|employment|work\s+(?:history|experience)|\bjobs?\b"),
    ("project", r"projects?"),
    ("skill|technolog|competenc", r"skills?|technolog\w*|tech\s+stack|competenc\w*"),
    ("education|academic", r"education|academics?|degree|qualifications?"),
    ("achiev|award|certif|leadership|extra", r"achievements?|awards?|certifications?|leadership|extra-?curricular\w*"),
    (SUMMARY, r"summary|objective|profile"),
)
ORDER_CUE = re.compile(r"\b(first|top|then|followed|before|after|above|below|last|bottom|order|swap|"
                       r"(start|begin|lead|open) with)\b", re.I)
LEADING = re.compile(r"\b(first|top|order|(start|begin|lead|open) with)\b", re.I)


def _mention_pattern(section: str) -> str:
    for name_pat, words in SECTION_WORDS:
        if re.search(name_pat, section, re.I):
            return words
    return re.escape(section.lower())


def order_from_instructions(text: str, base: list[str]) -> list[str]:
    """Apply plain-English order requests ('make education first', 'Education, then Experience, then Skills',
    'Skills before Projects', 'Achievements last') to ``base``. Unmentioned sections keep their base order."""
    order = list(base)
    for clause in re.split(r"[.;\n!]+", text):
        if not ORDER_CUE.search(clause):
            continue
        hits = []
        for s in base:
            m = re.search(r"\b(?:" + _mention_pattern(s) + r")", clause, re.I)
            if m:
                hits.append((m.start(), s))
        seq = [s for _, s in sorted(hits)]
        if not seq:
            continue
        low = clause.lower()
        if re.search(r"\blast\b|\b(at|to) the (bottom|end)\b", low) and len(seq) == 1:
            order = [s for s in order if s != seq[0]] + seq
        elif re.search(r"\b(before|above)\b", low) and len(seq) == 2:
            a, b = seq
            order.remove(a)
            order.insert(order.index(b), a)
        elif re.search(r"\b(after|below)\b", low) and len(seq) == 2:
            a, b = seq
            order.remove(a)
            order.insert(order.index(b) + 1, a)
        elif len(seq) >= 2 or LEADING.search(clause):  # 'X first', 'X on top', 'X, then Y, then Z'
            order = seq + [s for s in order if s not in seq]
    return order


VALID_KINDS = {"tool", "skill", "domain", "soft"}


def keyword_terms(plan: TailorPlan) -> tuple[list[str], dict[str, str]]:
    terms = _dedupe([k.term for k in plan.jd_keywords])
    kinds: dict[str, str] = {}
    for k in plan.jd_keywords:
        kind = k.kind.strip().lower()
        kinds.setdefault(k.term.strip(), kind if kind in VALID_KINDS else "tool")
    return terms, kinds


def build_context(doc: latex.ResumeDoc, facts: str, keywords: list[str],
                  kinds: dict[str, str] | None = None) -> GuardContext:
    body = doc.source[doc.body_start : doc.body_end]
    return GuardContext(
        keyword_kinds=kinds or {},
        allowed_commands=commands_in(body) | SAFE_COMMANDS,
        resume_text=latex.plain_text(body).lower(),
        facts_text=facts.lower(),
        jd_keywords=keywords,
        skills_sections={s.name for s in doc.sections if SKILL_HINT.search(s.name)},
    )


def apply_plan(doc: latex.ResumeDoc, plan: TailorPlan, facts: str, opts: Options,
               group_labels: dict[int, str], instructions: str = "",
               ) -> tuple[latex.EditSet, list[Verdict], dict[str, int], list[str], list[str]]:
    """Turn an LLM plan into a validated EditSet. Returns (edits, verdicts, relevance, dropped, warnings)."""
    keywords, kinds = keyword_terms(plan)
    ctx = build_context(doc, facts, keywords, kinds)
    edits = latex.EditSet()
    verdicts: list[Verdict] = []
    relevance: dict[str, int] = {}
    warnings: list[str] = []
    by_id = {b.id: b for b in plan.bullets}

    for u in doc.units:
        b = by_id.get(u.id)
        if b is None:
            verdicts.append(Verdict(u.id, "unchanged", warnings=["not returned by the model"]))
            continue
        relevance[u.id] = max(0, min(10, b.relevance))
        if _is_locked(u.section, opts):
            verdicts.append(Verdict(u.id, "locked"))
            continue
        v = validate_edit(u, b.title, b.text, ctx)
        verdicts.append(v)
        if v.status == "accepted":
            edits.args[u.id] = v.new_args

    # Drops suggested by the model (conservative)
    dropped: list[str] = []
    if opts.allow_drops:
        groups = doc.groups()
        for u in doc.units:
            b = by_id.get(u.id)
            if not b or b.keep or _is_locked(u.section, opts) or u.section in ctx.skills_sections:
                continue
            if relevance.get(u.id, 10) > 3 or u.group is None:
                continue
            alive = [m for m in groups[u.group] if m.id not in edits.dropped]
            if len(alive) > 1:
                edits.dropped.add(u.id)
                dropped.append(u.id)

    # Bullet order within lists
    if opts.allow_bullet_reorder:
        label_to_gid = {v: k for k, v in group_labels.items()}
        reorderable = latex.reorderable_groups(doc)
        groups = doc.groups()
        for go in plan.group_orders:
            gid = label_to_gid.get(go.group)
            if gid is None or gid not in reorderable:
                continue
            members = [m.id for m in sorted(groups[gid], key=lambda m: m.span[0])]
            if any(_is_locked(m.section, opts) for m in groups[gid]):
                continue
            order = [x for x in _dedupe(go.order) if x in members]
            order += [m for m in members if m not in order]
            if order != members:
                edits.group_orders[gid] = order

    # Section order
    names = [s.name for s in doc.sections]
    if opts.section_order != "ai" and latex.sections_reorderable(doc):
        proposed = preset_order(names, opts.section_order)  # "keep" -> original order
        if instructions:
            proposed = order_from_instructions(instructions, proposed)
        if proposed != names:
            edits.section_order = proposed
    elif opts.section_order == "ai" and opts.allow_section_reorder and plan.section_order and latex.sections_reorderable(doc):
        proposed = [s for s in _dedupe(plan.section_order) if s in names]
        if sorted(proposed) == sorted(names) and proposed != names:
            edits.section_order = proposed
        elif sorted(proposed) != sorted(names):
            warnings.append("model returned an invalid section order; kept the original")
    return edits, verdicts, relevance, dropped, warnings


def _isolate_compile_failures(doc, edits: latex.EditSet, compiler: Compiler) -> list[str]:
    """Re-add text edits one by one, keeping only those that still compile."""
    candidate = dict(edits.args)
    edits.args.clear()
    reverted: list[str] = []
    for uid, args in candidate.items():
        edits.args[uid] = args
        if not compiler.compile(latex.render(doc, edits)).ok:
            del edits.args[uid]
            reverted.append(uid)
    return reverted


def tailor(resume_tex: str, jd_text: str, llm: LLM, facts: str = "", opts: Options | None = None,
           compiler: Compiler | None = None, instructions: str = "") -> TailorResult:
    opts = opts or Options()
    if not jd_text.strip():
        raise ValueError("Job description is empty")
    doc = latex.parse(resume_tex)
    if not doc.units:
        raise ValueError("Couldn't find any bullet points in this resume. Run `tailortex inspect` to debug the parser.")

    group_ids = sorted({u.group for u in doc.units if u.group is not None})
    group_labels = {gid: f"g{i + 1}" for i, gid in enumerate(group_ids)}
    locked = {s.name for s in doc.sections if _is_locked(s.name, opts)}
    # with a fixed preset, section order is applied in code (preset + any order the user's instructions ask for)
    prompt = build_user_prompt(doc, jd_text, facts, locked, group_labels, latex.reorderable_groups(doc),
                               latex.sections_reorderable(doc) and opts.allow_section_reorder
                               and opts.section_order == "ai", instructions)
    plan = llm.plan(SYSTEM_PROMPT, prompt)

    edits, verdicts, relevance, dropped, warnings = apply_plan(doc, plan, facts, opts, group_labels, instructions)
    tex = latex.render(doc, edits)

    keywords, _ = keyword_terms(plan)
    before, _, _ = keyword_coverage(latex.body_plain_text(doc), keywords)
    ctx_evidence = build_context(doc, facts, keywords).evidence

    result = TailorResult(
        original_tex=resume_tex, tex=tex, plan=plan, verdicts=verdicts, edits=edits, keywords=keywords,
        coverage_before=before, coverage_after=0.0, matched_after=[], missing_after=[],
        unsupported_keywords=[k for k in keywords if not contains_term(ctx_evidence, k)],
        dropped_by_llm=dropped, warnings=warnings, model=getattr(llm, "name", ""),
    )

    if opts.compile:
        compiler = compiler or Compiler()
        if not compiler.available:
            result.warnings.append("No LaTeX engine found - skipped PDF build. Install Tectonic to get PDFs.")
        else:
            _compile_and_fit(doc, result, relevance, compiler, opts)

    result.tex = latex.render(doc, result.edits)
    result.coverage_after, result.matched_after, result.missing_after = keyword_coverage(
        latex.body_plain_text(doc, result.tex), keywords)
    return result


def _compile_and_fit(doc, result: TailorResult, relevance: dict[str, int], compiler: Compiler, opts: Options):
    edits = result.edits
    comp = compiler.compile(latex.render(doc, edits))
    if not comp.ok:
        if not compiler.compile(doc.source).ok:
            result.compile = comp
            result.warnings.append(f"Your original resume doesn't compile with {compiler.engine}; check the log.")
            return
        # structural edits are safe by construction; a bad text edit is the usual culprit
        result.reverted_for_compile = _isolate_compile_failures(doc, edits, compiler)
        comp = compiler.compile(latex.render(doc, edits))

    groups = doc.groups()
    skills = build_context(doc, "", []).skills_sections
    for _ in range(12):
        if not comp.ok or opts.max_pages <= 0 or comp.pages <= opts.max_pages:
            break
        candidates = []
        for u in doc.units:
            if u.id in edits.dropped or _is_locked(u.section, opts) or u.section in skills or u.group is None:
                continue
            alive = [m for m in groups[u.group] if m.id not in edits.dropped]
            if len(alive) < 2:
                continue
            text_len = len(latex.plain_text((edits.args.get(u.id) or u.original_args)[-1]))
            candidates.append((relevance.get(u.id, 5), -text_len, u.id))
        if not candidates:
            result.warnings.append(f"Still {comp.pages} pages and nothing left that is safe to drop.")
            break
        _, _, uid = min(candidates)
        edits.dropped.add(uid)
        result.dropped_for_fit.append(uid)
        comp = compiler.compile(latex.render(doc, edits))
    result.compile = comp
