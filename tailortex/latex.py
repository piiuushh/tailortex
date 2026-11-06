"""LaTeX resume segmentation and re-rendering.

The LLM never sees or writes the whole .tex file. Instead we:

1. Parse the preamble to learn which macros are *bullets* (e.g. ``\\resumeItem``),
   which open/close lists (e.g. ``\\resumeItemListStart``) and which are headings.
2. Walk the document body and cut out every bullet as an editable :class:`Unit`
   with exact character spans, grouped by the list it lives in and the section
   it belongs to.
3. Re-render by splicing edited text back into those spans only. Everything
   else (preamble, header, headings, spacing, custom macros) is byte-identical.

Rendering with no edits returns the original document exactly; the test suite
asserts this invariant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LIST_ENVS = {"itemize", "enumerate", "description"}

# --------------------------------------------------------------------------- #
# Low-level scanning helpers
# --------------------------------------------------------------------------- #


def mask_comments(src: str) -> str:
    """Replace LaTeX comments with spaces, keeping every character offset."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            j = src.find("\n", i)
            j = n if j == -1 else j
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        i += 1
    return "".join(out)


def match_brace(s: str, i: int) -> int:
    """Given ``s[i] == '{'``, return the index of its matching ``}`` (or -1)."""
    if i >= len(s) or s[i] != "{":
        return -1
    depth = 0
    j = i
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def read_args(s: str, i: int, n_args: int) -> tuple[list[tuple[int, int]], int] | None:
    """Read ``n_args`` mandatory ``{...}`` arguments starting at ``i``.

    Optional ``[...]`` arguments are skipped. Returns the inner spans of each
    argument and the index just after the last one, or ``None`` on failure.
    """
    spans: list[tuple[int, int]] = []
    j = i
    while len(spans) < n_args:
        j = skip_ws(s, j)
        if j < len(s) and s[j] == "[":
            close = s.find("]", j)
            if close == -1:
                return None
            j = close + 1
            continue
        if j >= len(s) or s[j] != "{":
            return None
        end = match_brace(s, j)
        if end == -1:
            return None
        spans.append((j + 1, end))
        j = end + 1
    return spans, j


def braces_balanced(s: str) -> bool:
    depth = 0
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def iter_commands(s: str, start: int = 0, end: int | None = None):
    """Yield ``(start, end, name)`` for every ``\\command`` (letters only)."""
    end = len(s) if end is None else end
    i = start
    while i < end:
        if s[i] == "\\":
            j = i + 1
            while j < end and (s[j].isalpha() or s[j] == "@"):
                j += 1
            if j > i + 1:
                if j < end and s[j] == "*":
                    j += 1
                yield i, j, s[i + 1 : j].rstrip("*")
                i = j
                continue
            i += 2
            continue
        i += 1


# --------------------------------------------------------------------------- #
# Preamble analysis
# --------------------------------------------------------------------------- #

_NEWCMD = re.compile(r"\\(?:re)?newcommand\*?\s*\{?\s*\\([A-Za-z@]+)\s*\}?\s*(?:\[(\d)\])?\s*(?:\[[^\]]*\])?\s*\{")


@dataclass
class MacroInfo:
    bullets: dict[str, int] = field(default_factory=dict)  # name -> n_args
    list_starts: set[str] = field(default_factory=set)
    list_ends: set[str] = field(default_factory=set)
    headings: set[str] = field(default_factory=set)
    defined: set[str] = field(default_factory=set)


def analyse_preamble(preamble: str) -> MacroInfo:
    masked = mask_comments(preamble)
    defs: dict[str, tuple[int, str]] = {}
    for m in _NEWCMD.finditer(masked):
        name = m.group(1)
        n_args = int(m.group(2) or 0)
        body_start = m.end() - 1
        body_end = match_brace(masked, body_start)
        if body_end == -1:
            continue
        defs[name] = (n_args, masked[body_start + 1 : body_end])

    info = MacroInfo(defined=set(defs))
    for name, (n, body) in defs.items():
        if re.search(r"\\begin\s*\{(itemize|enumerate|description)\}", body):
            info.list_starts.add(name)
        if re.search(r"\\end\s*\{(itemize|enumerate|description)\}", body):
            info.list_ends.add(name)

    # Bullet = has args, emits \item (directly or via another bullet), no tabular.
    changed = True
    while changed:
        changed = False
        for name, (n, body) in defs.items():
            if name in info.bullets or name in info.headings or n == 0:
                continue
            if "tabular" in body:
                if re.search(r"\\item\b", body):
                    info.headings.add(name)
                continue
            emits_item = re.search(r"\\item(?![A-Za-z])", body) is not None
            calls_bullet = any(re.search(r"\\" + re.escape(b) + r"(?![A-Za-z])", body) for b in info.bullets)
            if emits_item or calls_bullet:
                info.bullets[name] = n
                changed = True
    return info


# --------------------------------------------------------------------------- #
# Document model
# --------------------------------------------------------------------------- #


@dataclass
class Unit:
    id: str
    kind: str  # "macro" | "item"
    macro: str | None
    section: str
    group: int | None
    span: tuple[int, int]  # whole unit, absolute offsets
    arg_spans: list[tuple[int, int]]  # editable arg inner spans, absolute
    original_args: list[str]

    @property
    def has_title(self) -> bool:
        return self.kind == "macro" and len(self.arg_spans) >= 2

    @property
    def title(self) -> str:
        return self.original_args[0] if self.has_title else ""

    @property
    def text(self) -> str:
        return self.original_args[-1]


@dataclass
class Section:
    name: str
    span: tuple[int, int]  # \section ... up to next \section / \end{document}


@dataclass
class ResumeDoc:
    source: str
    body_start: int
    body_end: int  # index of \end{document} (or len)
    macros: MacroInfo
    sections: list[Section]
    units: list[Unit]

    def unit(self, uid: str) -> Unit:
        for u in self.units:
            if u.id == uid:
                return u
        raise KeyError(uid)

    def groups(self) -> dict[int, list[Unit]]:
        out: dict[int, list[Unit]] = {}
        for u in self.units:
            if u.group is not None:
                out.setdefault(u.group, []).append(u)
        return out

    def section_of_offset(self, pos: int) -> str:
        for s in self.sections:
            if s.span[0] <= pos < s.span[1]:
                return s.name
        return "_header"


_SECTION_RE = re.compile(r"\\section\*?\s*\{")


def _section_name(raw: str) -> str:
    return plain_text(raw).strip()


def parse(source: str) -> ResumeDoc:
    masked = mask_comments(source)
    m = re.search(r"\\begin\s*\{document\}", masked)
    if not m:
        raise ValueError("No \\begin{document} found - is this a LaTeX resume?")
    body_start = m.end()
    m_end = re.search(r"\\end\s*\{document\}", masked)
    body_end = m_end.start() if m_end else len(source)
    macros = analyse_preamble(source[: m.start()])

    # Sections
    heads: list[tuple[int, str]] = []
    for sm in _SECTION_RE.finditer(masked, body_start, body_end):
        close = match_brace(masked, sm.end() - 1)
        if close == -1:
            continue
        heads.append((sm.start(), _section_name(source[sm.end() : close])))
    sections = [
        Section(name, (pos, heads[k + 1][0] if k + 1 < len(heads) else body_end))
        for k, (pos, name) in enumerate(heads)
    ]

    doc = ResumeDoc(source, body_start, body_end, macros, sections, [])

    stack: list[int] = []
    terminators = macros.list_starts | macros.list_ends | set(macros.bullets) | macros.headings | {"item", "begin", "end", "section"}
    counter = 0
    i = body_start
    while i < body_end:
        nxt = next(iter_commands(masked, i, body_end), None)
        if nxt is None:
            break
        cs, ce, name = nxt
        i = ce
        if name in ("begin", "end"):
            got = read_args(masked, ce, 1)
            if not got:
                continue
            (a0, a1), after = got[0][0], got[1]
            env = masked[a0:a1].strip()
            if env in LIST_ENVS:
                if name == "begin":
                    stack.append(cs)
                elif stack:
                    stack.pop()
            continue
        if name in macros.list_starts and name not in macros.list_ends:
            stack.append(cs)
            continue
        if name in macros.list_ends and name not in macros.list_starts:
            if stack:
                stack.pop()
            continue
        if name in macros.bullets:
            n_args = macros.bullets[name]
            got = read_args(masked, ce, n_args)
            if not got:
                continue
            spans, after = got
            counter += 1
            doc.units.append(
                Unit(
                    id=f"u{counter:02d}",
                    kind="macro",
                    macro=name,
                    section=doc.section_of_offset(cs),
                    group=stack[-1] if stack else None,
                    span=(cs, after),
                    arg_spans=spans,
                    original_args=[source[a:b] for a, b in spans],
                )
            )
            i = after
            continue
        if name == "item" and stack:
            # Plain \item: content runs until a terminator command at depth 0,
            # or until a '}' that closes an enclosing group.
            j = ce
            # optional [label]
            k = skip_ws(masked, j)
            if k < body_end and masked[k] == "[":
                close = masked.find("]", k)
                j = close + 1 if close != -1 else j
            depth = 0
            p = j
            stop = body_end
            while p < body_end:
                c = masked[p]
                if c == "\\":
                    q = p + 1
                    while q < body_end and masked[q].isalpha():
                        q += 1
                    cmd = masked[p + 1 : q]
                    if depth == 0 and cmd in terminators:
                        stop = p
                        break
                    p = max(q, p + 2)
                    continue
                if c == "{":
                    depth += 1
                elif c == "}":
                    if depth == 0:
                        stop = p
                        break
                    depth -= 1
                p += 1
            # trim whitespace
            a, b = j, stop
            while a < b and source[a] in " \t\r\n":
                a += 1
            while b > a and source[b - 1] in " \t\r\n":
                b -= 1
            if b > a and braces_balanced(masked[a:b]):
                counter += 1
                doc.units.append(
                    Unit(
                        id=f"u{counter:02d}",
                        kind="item",
                        macro=None,
                        section=doc.section_of_offset(cs),
                        group=stack[-1],
                        span=(cs, b),
                        arg_spans=[(a, b)],
                        original_args=[source[a:b]],
                    )
                )
            i = max(stop, ce)
            continue
    return doc


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


@dataclass
class EditSet:
    """Everything the engine may change. Empty EditSet == original document."""

    args: dict[str, list[str]] = field(default_factory=dict)  # uid -> new arg contents
    dropped: set[str] = field(default_factory=set)
    group_orders: dict[int, list[str]] = field(default_factory=dict)  # group -> uid order
    section_order: list[str] | None = None


def _render_unit(doc: ResumeDoc, u: Unit, edits: EditSet) -> str:
    if u.id in edits.dropped:
        return ""
    new_args = edits.args.get(u.id)
    raw = doc.source[u.span[0] : u.span[1]]
    if not new_args:
        return raw
    out = raw
    base = u.span[0]
    for (a, b), new in sorted(zip(u.arg_spans, new_args), key=lambda t: -t[0][0]):
        out = out[: a - base] + new + out[b - base :]
    return out


def reorderable_groups(doc: ResumeDoc) -> set[int]:
    """Groups whose bullets are separated only by whitespace / spacing commands."""
    ok: set[int] = set()
    filler = re.compile(r"^(\s|\\vspace\*?\{[^}]*\}|\\smallskip|\\medskip)*$")
    masked = mask_comments(doc.source)
    for gid, units in doc.groups().items():
        units = sorted(units, key=lambda u: u.span[0])
        if len(units) < 2:
            continue
        if all(filler.match(masked[a.span[1] : b.span[0]]) for a, b in zip(units, units[1:])):
            ok.add(gid)
    return ok


def sections_reorderable(doc: ResumeDoc) -> bool:
    if len(doc.sections) < 2:
        return False
    masked = mask_comments(doc.source)
    for s in doc.sections:
        chunk = masked[s.span[0] : s.span[1]]
        if not braces_balanced(chunk):
            return False
        begins = len(re.findall(r"\\begin\s*\{", chunk))
        ends = len(re.findall(r"\\end\s*\{", chunk))
        if begins != ends:
            return False
        opens = sum(len(re.findall(r"\\" + re.escape(n) + r"(?![A-Za-z])", chunk)) for n in doc.macros.list_starts)
        closes = sum(len(re.findall(r"\\" + re.escape(n) + r"(?![A-Za-z])", chunk)) for n in doc.macros.list_ends)
        if opens != closes:
            return False
    return True


def render(doc: ResumeDoc, edits: EditSet | None = None) -> str:
    edits = edits or EditSet()
    src = doc.source

    # slot assignment: unit span -> rendered text of (possibly another) unit
    slot_content: dict[str, str] = {u.id: _render_unit(doc, u, edits) for u in doc.units}
    by_group = doc.groups()
    for gid, order in edits.group_orders.items():
        members = sorted(by_group.get(gid, []), key=lambda u: u.span[0])
        if sorted(order) != sorted(u.id for u in members):
            raise ValueError(f"group order for {gid} is not a permutation")
        # slot k (k-th bullet position in the list) receives the k-th unit of `order`
        rendered = [slot_content[uid] for uid in order]
        slot_content.update({u.id: rendered[k] for k, u in enumerate(members)})

    def splice(start: int, end: int) -> str:
        pieces = []
        pos = start
        for u in sorted(doc.units, key=lambda u: u.span[0]):
            if u.span[0] < start or u.span[1] > end:
                continue
            pieces.append(src[pos : u.span[0]])
            pieces.append(slot_content[u.id])
            pos = u.span[1]
        pieces.append(src[pos:end])
        return "".join(pieces)

    if not doc.sections:
        return splice(0, len(src))

    first = doc.sections[0].span[0]
    last = doc.sections[-1].span[1]
    head = splice(0, first)
    tail = splice(last, len(src))
    chunks = {s.name: splice(*s.span) for s in doc.sections}
    order = [s.name for s in doc.sections]
    if edits.section_order:
        if sorted(edits.section_order) != sorted(order):
            raise ValueError("section order is not a permutation of existing sections")
        order = edits.section_order
    # the last chunk may lack a trailing newline before \end{document}
    body = []
    for name in order:
        c = chunks[name]
        if body and not body[-1].endswith("\n"):
            body[-1] += "\n"
        body.append(c)
    if body and not body[-1].endswith("\n") and order != [s.name for s in doc.sections]:
        body[-1] += "\n"
    return head + "".join(body) + tail


# --------------------------------------------------------------------------- #
# Plain-text conversion (for keyword scoring / LLM context)
# --------------------------------------------------------------------------- #

_HREF = re.compile(r"\\href\s*\{[^{}]*\}\s*\{")


def plain_text(tex: str) -> str:
    s = mask_comments(tex)
    s = _HREF.sub("{", s)
    s = s.replace("\\\\", "\n")
    s = re.sub(r"\\(begin|end)\s*\{[^}]*\}", " ", s)
    s = re.sub(r"\\(vspace|hspace)\*?\s*\{[^}]*\}", " ", s)
    s = re.sub(r"\\([%&#_$])", r"\1", s)
    s = re.sub(r"\\[A-Za-z@]+\*?", " ", s)
    s = re.sub(r"\}\s*\{", "} {", s)  # \macro{Title}{Body} -> "Title Body", not "TitleBody"
    s = re.sub(r"[{}]", "", s)
    s = re.sub(r" +([:,.;])", r"\1", s)
    s = s.replace("~", " ").replace("--", "-")
    s = re.sub(r"\$\\(\w+)\$", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def body_plain_text(doc: ResumeDoc, tex: str | None = None) -> str:
    tex = doc.source if tex is None else tex
    m = re.search(r"\\begin\s*\{document\}", tex)
    return plain_text(tex[m.end() :] if m else tex)
