"""Prompt construction. The LLM sees bullets as JSON, never the raw .tex file."""

from __future__ import annotations

import json

SYSTEM_PROMPT = """You are an expert technical recruiter and resume writer. You tailor an existing \
resume to one job description so it passes ATS keyword screens and convinces a hiring manager, \
WITHOUT inventing anything.

Hard rules (edits that break them are automatically discarded):
1. Truthfulness: never add tools, technologies, employers, responsibilities, numbers or results that \
are not already in that bullet or in the candidate's FACTS. You may rephrase, re-emphasise, reorder \
clauses, and swap in the JD's terminology for things the candidate demonstrably did \
(e.g. "dashboards" -> "BI dashboards", "stakeholders" -> "business stakeholders").
2. Keep every number exactly as written (8+, 15\\%, 100K+ ...). Do not add new ones.
3. Output each `text`/`title` as a LaTeX fragment: keep existing commands such as \\textbf{}, \\textit{}, \\href{}{}, \\\\ \
and \\hfill intact; escape % & # _ as \\% \\& \\# \\_ ; no Markdown, no new LaTeX commands.
4. Keep each bullet about the same length as the original (+/- 15%) so the resume stays on one page. \
Lead with a strong action verb and the result that matters most for THIS job.
5. Skills lines: only reorder or remove items, or rename a category label. Put the JD-relevant skills first. \
Never add a skill the candidate did not list.
6. Bullets marked "locked": true must be returned unchanged.
7. Return EVERY bullet id and EVERY group id exactly once. `keep: false` only for bullets that are clearly \
irrelevant to this role (relevance <= 3) and never for the only bullet in a group.
8. section_order: put the sections that best prove fit for this role first (e.g. Projects before \
Experience only if projects are clearly more relevant); keep the header-adjacent order sensible.
9. jd_keywords: classify each term; 'tool' = a named technology/platform/language/certification.
10. gaps: list important JD requirements the candidate shows no evidence for, so they can address them honestly.
"""


MAX_INSTRUCTIONS = 1500  # chars; keeps the prompt bounded


def build_user_prompt(doc, jd_text: str, facts: str, locked_sections: set[str], group_labels: dict[int, str],
                      reorderable: set[int], sections_movable: bool, instructions: str = "") -> str:
    bullets = []
    for u in doc.units:
        item = {
            "id": u.id,
            "section": u.section,
            "group": group_labels.get(u.group, "") if u.group is not None else "",
            "title": u.title.strip(),
            "text": u.text.strip(),
        }
        if u.section in locked_sections:
            item["locked"] = True
        bullets.append(item)

    groups = []
    for gid, label in group_labels.items():
        members = [u.id for u in doc.units if u.group == gid]
        groups.append({"group": label, "bullets": members, "can_reorder": gid in reorderable})

    payload = {
        "sections": [s.name for s in doc.sections],
        "sections_can_reorder": sections_movable,
        "groups": groups,
        "bullets": bullets,
    }
    facts_block = facts.strip() or "(none provided)"
    extra = ""
    if instructions.strip():
        extra = ("CANDIDATE'S OWN INSTRUCTIONS (follow them unless they conflict with the hard rules, "
                 "which always win):\n<<<\n" + instructions.strip()[:MAX_INSTRUCTIONS] + "\n>>>\n\n")
    return (
        "JOB DESCRIPTION:\n<<<\n" + jd_text.strip() + "\n>>>\n\n"
        "CANDIDATE FACTS (true statements not on the resume; you may draw on these):\n<<<\n" + facts_block + "\n>>>\n\n"
        + extra +
        "RESUME (structured):\n" + json.dumps(payload, indent=1, ensure_ascii=False) + "\n\n"
        "Return the tailoring plan as JSON matching the schema. If a group cannot be reordered, return its "
        "bullets in the original order. If sections cannot be reordered, return them in the original order."
    )
