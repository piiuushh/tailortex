import pytest

from tailortex import latex


def test_bajaj_parse(bajaj):
    doc = latex.parse(bajaj)
    assert set(doc.macros.bullets) == {"resumeItem", "resumeSubItem"}
    assert "resumeSubheading" in doc.macros.headings
    assert [s.name for s in doc.sections] == ["Skills Summary", "Education", "Experience", "Projects"]
    assert len(doc.units) == 4 + 4 + 2 + 2
    assert doc.unit("u01").title == "Languages"
    assert all(u.has_title for u in doc.units)


def test_commented_bullet_is_ignored(bajaj):
    doc = latex.parse(bajaj)
    assert not any("Commented Out" in u.title for u in doc.units)


def test_jake_parse(jake):
    doc = latex.parse(jake)
    assert doc.macros.bullets == {"resumeItem": 1, "resumeSubItem": 1}
    assert "resumeProjectHeading" in doc.macros.headings
    kinds = [u.kind for u in doc.units]
    assert kinds.count("item") == 1  # the skills block is a plain \item
    skills = doc.units[-1]
    assert skills.section == "Technical Skills"
    assert skills.text.startswith("{") and skills.text.endswith("}")


@pytest.mark.parametrize("name", ["bajaj", "jake"])
def test_round_trip_is_byte_identical(name, request):
    src = request.getfixturevalue(name)
    assert latex.render(latex.parse(src)) == src


def test_edit_only_touches_the_arg(bajaj):
    doc = latex.parse(bajaj)
    u = doc.unit("u05")
    edits = latex.EditSet(args={"u05": ["Reporting & BI", "NEW TEXT"]})
    out = latex.render(doc, edits)
    assert "\\resumeItem{Reporting & BI}" in out
    assert "{NEW TEXT}" in out
    assert u.text not in out
    # everything outside the unit is unchanged
    assert out.replace("{Reporting & BI}\n          {NEW TEXT}", "") == bajaj.replace(
        bajaj[u.span[0] + len("\\resumeItem"):u.span[1]], "")


def test_group_reorder_and_drop(bajaj):
    doc = latex.parse(bajaj)
    g = doc.unit("u05").group
    assert g in latex.reorderable_groups(doc)
    out = latex.render(doc, latex.EditSet(group_orders={g: ["u06", "u05", "u07", "u08"]}, dropped={"u08"}))
    assert out.index("3M+ rows") < out.index("12 regional managers") < out.index("A/B tests")
    assert "offsite logistics" not in out
    assert out.count("\\resumeItemListStart") == bajaj.count("\\resumeItemListStart")


def test_bad_group_order_raises(bajaj):
    doc = latex.parse(bajaj)
    g = doc.unit("u05").group
    with pytest.raises(ValueError):
        latex.render(doc, latex.EditSet(group_orders={g: ["u05"]}))


def test_section_reorder(bajaj):
    doc = latex.parse(bajaj)
    assert latex.sections_reorderable(doc)
    order = ["Experience", "Projects", "Skills Summary", "Education"]
    out = latex.render(doc, latex.EditSet(section_order=order))
    pos = [out.index("\\section{" + n) for n in ["Experience", "Projects", "Skills Summary", "Education"]]
    assert pos == sorted(pos)
    assert out.rstrip().endswith("\\end{document}")
    assert latex.braces_balanced(latex.mask_comments(out))


def test_plain_text():
    assert latex.plain_text(r"Cut cost by 15\% \& \textbf{won} \href{http://x.y}{link}") == "Cut cost by 15% & won link"


def test_match_brace_handles_escapes():
    s = r"{a \{ b \} c}"
    assert latex.match_brace(s, 0) == len(s) - 1


def test_no_document_raises():
    with pytest.raises(ValueError):
        latex.parse("hello")
