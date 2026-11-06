import json
import re
from pathlib import Path

from tailortex import latex
from tailortex.engine import Options, tailor
from tailortex.llm import FakeLLM, parse_plan
from tailortex.report import markdown
from tailortex.schema import BulletEdit, GroupOrder, Keyword, TailorPlan

TOOLS = ["Power BI", "SQL", "Python", "Airflow", "AWS", "dbt"]
KEYWORDS = [Keyword(term=t, kind="tool") for t in TOOLS] + [
    Keyword(term="A/B tests", kind="skill"), Keyword(term="stakeholder management", kind="soft"),
    Keyword(term="data quality", kind="skill"), Keyword(term="lending", kind="domain"),
    Keyword(term="self-serve dashboards", kind="skill")]


def plan_from_prompt(_system, prompt):
    """A deterministic 'LLM' that reads the structured prompt like Gemini would."""
    payload = json.loads(prompt.split("RESUME (structured):\n", 1)[1].split("\n\nReturn", 1)[0])
    edits = []
    for b in payload["bullets"]:
        text, title, rel, keep = b["text"], b["title"], 6, True
        if "dashboards on loan" in text:
            title = "Self-Serve Dashboards"
            text = text.replace("Built weekly Power BI dashboards", "Built self-serve Power BI dashboards") \
                       .replace("regional managers", "regional business stakeholders")
        if "3M+ rows" in text:
            text = text + " Used dbt models."  # unsupported claim -> must be blocked
        if "data-validation" in text:
            text = "Ensured data quality by building automated data-validation checks in Airflow that caught pipeline breaks before they reached business users."
            rel = 9
        if "offsite" in text:
            rel, keep = 1, False
        if b["section"] == "Education":
            text = "HACKED"  # locked: must be ignored
        edits.append(BulletEdit(id=b["id"], title=title, text=text, relevance=rel, keep=keep))
    groups = [GroupOrder(group=g["group"], order=list(reversed(g["bullets"]))) for g in payload["groups"]]
    return TailorPlan(company="FinServe Technologies", role="Senior Data Analyst", jd_keywords=KEYWORDS,
                      section_order=["Experience", "Skills Summary", "Projects", "Education"], bullets=edits,
                      group_orders=groups, gaps=["dbt", "Redshift"], change_summary=["Led with lending dashboards"])


def test_end_to_end_with_fake_llm(bajaj, jd, fake_compiler):
    llm = FakeLLM(plan_from_prompt)
    res = tailor(bajaj, jd, llm, opts=Options(), compiler=fake_compiler())
    verdict = {v.uid: v for v in res.verdicts}

    assert verdict["u05"].status == "accepted"
    assert verdict["u06"].status == "rejected" and "dbt" in verdict["u06"].reasons[0]
    assert "u08" in res.dropped_by_llm and "offsite" not in res.tex
    assert "HACKED" not in res.tex
    assert res.edits.section_order[0] == "Experience"
    assert res.coverage_after > res.coverage_before
    assert "dbt" in res.unsupported_keywords
    assert latex.render(latex.parse(res.tex)) == res.tex  # output is itself parseable
    md = markdown(res)
    assert "Edits blocked by guardrails" in md and "u06" in md


def test_prompt_never_contains_preamble(bajaj, jd):
    llm = FakeLLM(plan_from_prompt)
    tailor(bajaj, jd, llm, opts=Options(compile=False))
    _, prompt = llm.calls[0]
    assert "\\newcommand" not in prompt and "\\documentclass" not in prompt
    assert "Education" in prompt


def test_invalid_section_order_is_ignored(bajaj, jd):
    def bad(s, p):
        plan = plan_from_prompt(s, p)
        plan.section_order = ["Experience", "Made Up"]
        return plan

    res = tailor(bajaj, jd, FakeLLM(bad), opts=Options(compile=False))
    assert res.edits.section_order is None
    assert any("section order" in w for w in res.warnings)


def test_page_fit_drops_least_relevant(bajaj, jd, fake_compiler):
    # pretend each bullet adds height: > 9 bullets -> 2 pages
    def pages(tex):
        return 2 if len(latex.parse(tex).units) > 9 else 1

    comp = fake_compiler(pages_fn=pages)
    res = tailor(bajaj, jd, FakeLLM(plan_from_prompt), opts=Options(allow_drops=False), compiler=comp)
    assert res.compile.pages == 1
    assert res.dropped_for_fit, "should have dropped something to fit"
    doc = latex.parse(bajaj)
    for uid in res.dropped_for_fit:
        assert "Skill" not in doc.unit(uid).section and doc.unit(uid).section != "Education"


def test_compile_failure_reverts_only_the_bad_edit(bajaj, jd, fake_compiler):
    def plan(s, p):
        pl = plan_from_prompt(s, p)
        for b in pl.bullets:
            if b.id == "u12":  # Sales Dashboard project
                b.text = b.text + r" \textbf{BOOM}"
        return pl

    comp = fake_compiler(bad="BOOM")
    res = tailor(bajaj, jd, FakeLLM(plan), opts=Options(), compiler=comp)
    assert res.reverted_for_compile == ["u12"]
    assert "BOOM" not in res.tex
    assert "u05" in res.edits.args  # good edits survive
    assert res.compile.ok


def test_parse_plan_tolerates_fences():
    p = TailorPlan(company="A", role="B", jd_keywords=[], section_order=[], bullets=[], group_orders=[],
                   gaps=[], change_summary=[])
    raw = "```json\n" + p.model_dump_json() + "\n```"
    assert parse_plan(raw).company == "A"


def test_jake_template_end_to_end(jake, fake_compiler):
    def plan(_s, p):
        payload = json.loads(p.split("RESUME (structured):\n", 1)[1].split("\n\nReturn", 1)[0])
        bullets = []
        for b in payload["bullets"]:
            t = b["text"]
            if "REST API" in t:
                t = "Built a high-throughput REST API with FastAPI and PostgreSQL serving 2M requests per day"
            if b["section"] == "Technical Skills":
                t = re.sub(r"Java, ", "", t)  # remove an item: allowed
            bullets.append(BulletEdit(id=b["id"], title="", text=t, relevance=5, keep=True))
        return TailorPlan(company="X", role="Backend Engineer", jd_keywords=[Keyword(term=t, kind="tool") for t in ["FastAPI", "PostgreSQL", "Kubernetes"]],
                          section_order=payload["sections"], bullets=bullets, group_orders=[], gaps=[], change_summary=[])

    res = tailor(jake, "Backend engineer, FastAPI, PostgreSQL, Kubernetes", FakeLLM(plan), compiler=fake_compiler())
    assert "high-throughput REST API" in res.tex
    assert "{: Python, SQL, JavaScript}" in res.tex
    assert "Kubernetes" in res.missing_after and "Kubernetes" in res.unsupported_keywords


def test_section_order_presets():
    from tailortex.engine import preset_order

    names = ["Skills Summary", "Education", "Projects", "Experience", "Achievements & Leadership"]
    assert preset_order(names, "experience") == ["Experience", "Projects", "Skills Summary", "Education", "Achievements & Leadership"]
    assert preset_order(names, "education")[:2] == ["Education", "Projects"]
    assert preset_order(names, "keep") == names
    assert preset_order(["Zeta", "Alpha"], "experience") == ["Zeta", "Alpha"]  # unmatched keep their order


def test_instructions_reach_the_prompt_and_change_cache_key():
    from tailortex.llm import CachedLLM

    resume = (Path(__file__).parent / "fixtures" / "jake_resume.tex").read_text(encoding="utf-8")
    inner = FakeLLM(plan_from_prompt)
    llm = CachedLLM(inner, {})
    tailor(resume, "Data analyst, SQL", llm, opts=Options(compile=False), instructions="Keep bullets short")
    assert "CANDIDATE'S OWN INSTRUCTIONS" in inner.calls[-1][1] and "Keep bullets short" in inner.calls[-1][1]
    tailor(resume, "Data analyst, SQL", llm, opts=Options(compile=False))
    assert len(inner.calls) == 2  # different instructions -> not served from cache
    assert "CANDIDATE'S OWN INSTRUCTIONS" not in inner.calls[-1][1]


def test_order_from_instructions():
    from tailortex.engine import order_from_instructions as o

    base = ["Experience", "Projects", "Skills Summary", "Education", "Achievements & Leadership"]
    first = lambda t: o(t, base)[0]
    assert first("make education section first") == "Education"
    assert first("Put Education on top") == "Education"
    assert first("Please start with my education") == "Education"
    assert o("Education, then Experience, then Skills", base)[:3] == ["Education", "Experience", "Skills Summary"]
    assert o("Put Education on top, then Experience, then Skills.", base)[:3] == ["Education", "Experience", "Skills Summary"]
    assert o("Skills before Projects", base)[:3] == ["Experience", "Skills Summary", "Projects"]
    assert o("Projects after Education", base)[3:] == ["Projects", "Achievements & Leadership"]
    assert o("Experience last", base)[-1] == "Experience"
    assert o("move Experience to the bottom", base)[-1] == "Experience"
    # instructions that are not about order must not move anything
    for t in ["Keep every bullet short.", "Don't touch my Projects section; put more emphasis on Python",
              "Make the tone more senior / leadership-focused", "Emphasise Power BI in my experience",
              "Start each bullet with a strong verb", ""]:
        assert o(t, base) == base, t
