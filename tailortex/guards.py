"""Guardrails applied to every LLM edit before it touches the .tex file.

An edit is rejected (and the original bullet kept) when it:

* breaks LaTeX structure (unbalanced braces),
* introduces a LaTeX command the resume never used,
* introduces a number/metric that wasn't in that bullet (or your facts file),
* claims a JD *tool* (named technology) that appears nowhere in your resume or facts file
  (new skill/domain phrasing is allowed but flagged for you to double-check),
* adds a skill to the Skills section that you never listed.

Unescaped ``% & # _ $`` and Markdown bold are repaired automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .latex import Unit, braces_balanced, iter_commands, plain_text

SAFE_COMMANDS = {
    "textbf", "textit", "emph", "underline", "href", "url", "small", "footnotesize",
    "textsc", "texttt", "hfill", "quad", "ldots", "textasciitilde", "LaTeX", "TeX",
}

_UNICODE = {
    "\u201c": "``", "\u201d": "''", "\u2018": "`", "\u2019": "'", "\u2013": "--", "\u2014": "---",
    "\u2192": "$\\rightarrow$", "\u2022": "", "\u00a0": " ", "\u2026": "\\ldots{}", "\u00d7": "$\\times$",
    "\u2248": "$\\approx$", "\u20b9": "INR ",
}

_NUM = re.compile(r"\d+(?:[.,]\d+)*")


def numbers(s: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(s)}


def _unescaped(s: str, ch: str) -> list[int]:
    out = []
    for m in re.finditer(re.escape(ch), s):
        i = m.start()
        bs = 0
        j = i - 1
        while j >= 0 and s[j] == "\\":
            bs += 1
            j -= 1
        if bs % 2 == 0:
            out.append(i)
    return out


def repair(new: str, original: str) -> str:
    """Fix the mistakes LLMs routinely make in LaTeX fragments."""
    s = new.strip()
    for k, v in _UNICODE.items():
        s = s.replace(k, v)
    # Markdown bold/italics -> LaTeX
    s = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\\textit{\1}", s)
    # Escape specials that the original never used unescaped
    for ch in "%&#_$":
        if _unescaped(original, ch):
            continue
        for i in reversed(_unescaped(s, ch)):
            s = s[:i] + "\\" + s[i:]
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s


def commands_in(s: str) -> set[str]:
    return {name for _, _, name in iter_commands(s)}


def contains_term(haystack_lower: str, term: str) -> bool:
    """Whole-word, case-insensitive match that tolerates simple plurals (stakeholder/stakeholders)."""
    t = term.lower().strip()
    if not t:
        return True
    if re.fullmatch(r"[a-z]{6,}", t):
        # single plain word: light stemming so automate~automated~automation, testing~tests
        stem = re.sub(r"(ation|ing|ed|es|e|s)$", "", t)
        pat = r"(?<![a-z0-9])" + re.escape(stem) + r"[a-z]{0,5}(?![a-z0-9])"
        return re.search(pat, haystack_lower) is not None
    stem = re.sub(r"(es|s)$", "", t) if len(t) > 4 and t[-1] == "s" else t
    pat = r"(?<![a-z0-9])" + re.escape(stem) + r"(?:s|es)?(?![a-z0-9])"
    return re.search(pat, haystack_lower) is not None


def is_tool_like(term: str) -> bool:
    """'Airflow', 'Power BI', 'dbt', 'C++', 'S3' are hard claims; 'stakeholder management' is phrasing.

    Heuristic: single words, or phrases containing a capital letter / digit / symbol,
    as spelled in the JD.
    """
    t = term.strip()
    if " " not in t:
        return True
    return bool(re.search(r"[A-Z0-9+#./]", t))


@dataclass
class GuardContext:
    allowed_commands: set[str]
    resume_text: str  # lower-cased plain text of the original resume
    facts_text: str = ""  # lower-cased plain text of the facts file
    jd_keywords: list[str] = field(default_factory=list)
    keyword_kinds: dict[str, str] = field(default_factory=dict)  # term -> tool|skill|domain|soft
    skills_sections: set[str] = field(default_factory=set)
    max_growth: float = 1.25

    @property
    def evidence(self) -> str:
        return self.resume_text + "\n" + self.facts_text


@dataclass
class Verdict:
    uid: str
    status: str  # "unchanged" | "accepted" | "rejected" | "locked"
    new_args: list[str] | None = None
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_edit(unit: Unit, title: str, text: str, ctx: GuardContext) -> Verdict:
    v = Verdict(unit.id, "unchanged")
    new_title = repair(title, unit.title) if unit.has_title else ""
    new_text = repair(text, unit.text)
    if not unit.has_title or not new_title:
        new_title = unit.title
    def norm(x: str) -> str:
        return " ".join(x.split())

    if norm(new_title) == norm(unit.title) and norm(new_text) == norm(unit.text):
        return v

    reasons: list[str] = []
    for label, frag in (("title", new_title), ("text", new_text)):
        if not braces_balanced(frag):
            reasons.append(f"unbalanced braces in {label}")
    unknown = commands_in(new_title + " " + new_text) - ctx.allowed_commands
    if unknown:
        reasons.append("uses LaTeX commands not in your resume: " + ", ".join(sorted(unknown)))

    allowed_nums = numbers(unit.title + " " + unit.text) | numbers(ctx.facts_text)
    invented = numbers(plain_text(new_title + " " + new_text)) - allowed_nums
    if invented:
        reasons.append("introduces numbers not in the original bullet: " + ", ".join(sorted(invented)))

    old_plain = plain_text(unit.title + " " + unit.text).lower()
    new_plain = plain_text(new_title + " " + new_text).lower()
    unsupported = [
        kw for kw in ctx.jd_keywords
        if contains_term(new_plain, kw) and not contains_term(old_plain, kw) and not contains_term(ctx.evidence, kw)
    ]
    hard = [kw for kw in unsupported if ctx.keyword_kinds.get(kw, "tool" if is_tool_like(kw) else "skill") == "tool"]
    soft = [kw for kw in unsupported if kw not in hard]
    if hard:
        reasons.append("claims JD tools/skills with no evidence in your resume/facts: " + ", ".join(hard))

    if unit.section in ctx.skills_sections:
        items = [t.strip() for t in re.split(r"[,;:/\n()]|\band\b", plain_text(new_text)) if t.strip()]
        added = [t for t in items if not contains_term(ctx.evidence, t)]
        if added:
            reasons.append("adds skills you never listed: " + ", ".join(added))

    if reasons:
        v.status = "rejected"
        v.reasons = reasons
        return v

    if soft:
        v.warnings.append("new JD phrasing - double-check it's accurate: " + ", ".join(soft))

    if len(plain_text(new_text)) > ctx.max_growth * len(plain_text(unit.text)) + 30:
        v.warnings.append("bullet grew noticeably longer")

    args = list(unit.original_args)
    if unit.has_title:
        args[0] = new_title
    # keep the original's leading/trailing whitespace so layout is unchanged
    lead = unit.text[: len(unit.text) - len(unit.text.lstrip())]
    trail = unit.text[len(unit.text.rstrip()) :]
    args[-1] = lead + new_text + trail
    v.status = "accepted"
    v.new_args = args
    return v
