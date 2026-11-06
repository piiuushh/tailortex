"""Human-readable change report (Markdown) for a TailorResult."""

from __future__ import annotations

from . import latex
from .engine import TailorResult


def _short(s: str, n: int = 160) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def changes(result: TailorResult) -> list[dict]:
    doc = latex.parse(result.original_tex)
    rows = []
    for v in result.verdicts:
        u = doc.unit(v.uid)
        before = (u.title + ": " if u.title else "") + u.text
        after = ""
        status = v.status
        if v.uid in result.edits.args:
            a = result.edits.args[v.uid]
            after = (a[0] + ": " if u.has_title else "") + a[-1]
        if v.uid in result.reverted_for_compile:
            status = "reverted (compile error)"
        if v.uid in result.dropped_by_llm:
            status = "dropped (irrelevant)"
        if v.uid in result.dropped_for_fit:
            status = "dropped (page fit)"
        rows.append({
            "id": v.uid, "section": u.section, "status": status,
            "before": latex.plain_text(before), "after": latex.plain_text(after) if after else "",
            "reasons": "; ".join(v.reasons + v.warnings),
        })
    return rows


def markdown(result: TailorResult) -> str:
    p = result.plan
    out = [f"# Tailoring report: {p.role} @ {p.company}", ""]
    out.append(f"**Model:** `{result.model}`  ")
    out.append(f"**JD keyword coverage:** {result.coverage_before:.0%} → **{result.coverage_after:.0%}** "
               f"({len(result.matched_after)}/{len(result.keywords)} keywords)")
    if result.compile:
        c = result.compile
        out.append(f"  \n**PDF:** {'OK' if c.ok else 'FAILED'} via `{c.engine}`, {c.pages} page(s)")
    out.append("")
    if p.change_summary:
        out += ["## What changed", *[f"- {s}" for s in p.change_summary], ""]
    if result.missing_after:
        out += ["## Keywords still missing", ""]
        gaps = set(result.unsupported_keywords)
        for k in result.missing_after:
            out.append(f"- {k}" + ("  _(no evidence in your resume - add to facts.md only if true)_" if k in gaps else ""))
        out.append("")
    if p.gaps:
        out += ["## Gaps the JD asks for", *[f"- {g}" for g in p.gaps], ""]
    if result.edits.section_order:
        out += ["## Section order", " → ".join(result.edits.section_order), ""]
    rows = changes(result)
    rejected = [r for r in rows if r["status"] == "rejected"]
    if rejected:
        out += ["## Edits blocked by guardrails", ""]
        for r in rejected:
            out.append(f"- **{r['id']}** ({r['section']}): {r['reasons']}")
        out.append("")
    out += ["## Bullet-by-bullet", ""]
    for r in rows:
        if r["status"] in ("unchanged", "locked"):
            continue
        out.append(f"### {r['id']} · {r['section']} · {r['status']}")
        out.append(f"- **Before:** {_short(r['before'], 400)}")
        if r["after"]:
            out.append(f"- **After:** {_short(r['after'], 400)}")
        out.append("")
    if result.warnings:
        out += ["## Warnings", *[f"- {w}" for w in result.warnings], ""]
    return "\n".join(out)
