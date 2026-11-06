from tailortex import latex
from tailortex.engine import build_context
from tailortex.guards import repair, validate_edit


def ctx_for(src, keywords=(), facts=""):
    doc = latex.parse(src)
    return doc, build_context(doc, facts, list(keywords))


def test_repair_escapes_and_markdown():
    assert repair("Cut 70% of **manual** work & more", "plain") == r"Cut 70\% of \textbf{manual} work \& more"
    assert repair(r"already 70\%", "x") == r"already 70\%"
    assert repair("a – b ’s", "x") == "a -- b 's"


def test_accepts_truthful_rephrase(bajaj):
    doc, ctx = ctx_for(bajaj, ["Power BI", "stakeholders"])
    u = doc.unit("u05")
    v = validate_edit(u, "Self-Serve BI", "Built weekly Power BI dashboards for 12 regional business stakeholders on loan disbursal and collections, replacing manual Excel reporting.", ctx)
    assert v.status == "accepted", v.reasons
    assert v.new_args[0] == "Self-Serve BI"


def test_rejects_invented_number(bajaj):
    doc, ctx = ctx_for(bajaj)
    v = validate_edit(doc.unit("u05"), "Reporting", "Built Power BI dashboards for 25 managers, saving 10 hours/week.", ctx)
    assert v.status == "rejected"
    assert "25" in v.reasons[0] and "10" in v.reasons[0]


def test_numbers_from_facts_are_allowed(bajaj):
    doc, ctx = ctx_for(bajaj, facts="Dashboards saved the team 10 hours a week.")
    v = validate_edit(doc.unit("u05"), "Reporting", "Built weekly Power BI dashboards for 12 regional managers, saving 10 hours a week.", ctx)
    assert v.status == "accepted", v.reasons


def test_rejects_unknown_command(bajaj):
    doc, ctx = ctx_for(bajaj)
    v = validate_edit(doc.unit("u05"), "Reporting", r"Built \input{/etc/passwd} dashboards", ctx)
    assert v.status == "rejected"
    assert any("input" in r for r in v.reasons)


def test_rejects_unbalanced_braces(bajaj):
    doc, ctx = ctx_for(bajaj)
    v = validate_edit(doc.unit("u05"), "Reporting", r"Built \textbf{dashboards", ctx)
    assert v.status == "rejected"


def test_rejects_jd_keyword_without_evidence(bajaj):
    doc, ctx = ctx_for(bajaj, ["dbt", "Airflow"])
    u = doc.unit("u06")
    v = validate_edit(u, "Pipelines", "Wrote SQL, Python and dbt jobs on AWS Athena that refresh 3M+ rows nightly, cutting report preparation time by 70\\%.", ctx)
    assert v.status == "rejected"
    assert "dbt" in v.reasons[0]


def test_jd_keyword_with_evidence_elsewhere_is_ok(bajaj):
    # Airflow appears in another bullet / skills, so mentioning it is supported
    doc, ctx = ctx_for(bajaj, ["Airflow"])
    v = validate_edit(doc.unit("u06"), "Pipelines", "Wrote SQL and Python jobs orchestrated with Airflow on AWS Athena that refresh 3M+ rows nightly, cutting report preparation time by 70\\%.", ctx)
    assert v.status == "accepted", v.reasons


def test_skills_cannot_gain_new_skills(bajaj):
    doc, ctx = ctx_for(bajaj)
    v = validate_edit(doc.unit("u01"), "Languages", "SQL, Python, Pandas, Rust", ctx)
    assert v.status == "rejected"
    assert "Rust" in v.reasons[0]
    v2 = validate_edit(doc.unit("u01"), "Programming", "SQL, Python, Pandas, NumPy", ctx)
    assert v2.status == "accepted", v2.reasons


def test_unchanged_is_unchanged(bajaj):
    doc, ctx = ctx_for(bajaj)
    u = doc.unit("u05")
    assert validate_edit(u, u.title, u.text, ctx).status == "unchanged"


def test_whitespace_of_original_arg_is_preserved(jake):
    doc, ctx = ctx_for(jake)
    u = doc.unit("u02")
    v = validate_edit(u, "", "Cut CI build time by 40\\% by caching Docker layers", ctx)
    assert v.status == "accepted"
    assert latex.braces_balanced(v.new_args[0])


def test_soft_phrase_is_a_warning_not_a_rejection(bajaj):
    doc, ctx = ctx_for(bajaj, ["self-serve dashboards", "Redshift"])
    u = doc.unit("u05")
    v = validate_edit(u, "Reporting", "Built weekly self-serve dashboards in Power BI on loan disbursal and collections for 12 regional managers, replacing a manual Excel process.", ctx)
    assert v.status == "accepted"
    assert any("self-serve" in w for w in v.warnings)
    v2 = validate_edit(u, "Reporting", "Built weekly Power BI dashboards on Redshift for 12 regional managers.", ctx)
    assert v2.status == "rejected"
