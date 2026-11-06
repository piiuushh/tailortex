"""Command-line interface.

    tailortex tailor resume.tex --jd job.txt [--facts facts.md] [--out out/]
    tailortex inspect resume.tex          # see how your resume was parsed (offline)
    tailortex models                      # list Gemini models your key can use
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import __version__, latex
from .compiler import Compiler
from .engine import DEFAULT_LOCKED, Options, tailor
from .inputs import read_text, slug


def _load_env():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def cmd_inspect(args) -> int:
    src = Path(args.resume).read_text(encoding="utf-8")
    doc = latex.parse(src)
    m = doc.macros
    bullets = ", ".join(f"{k}[{v}]" for k, v in m.bullets.items()) or "(none, using plain \\item)"
    print(f"Bullet macros : {bullets}")
    print(f"List macros   : {', '.join(sorted(m.list_starts | m.list_ends)) or '-'}")
    print(f"Sections      : {' | '.join(s.name for s in doc.sections)}")
    print(f"Sections movable: {latex.sections_reorderable(doc)}")
    reorder = latex.reorderable_groups(doc)
    labels = {g: f"g{i + 1}" for i, g in enumerate(sorted({u.group for u in doc.units if u.group is not None}))}
    print(f"\n{len(doc.units)} editable bullets:\n")
    for u in doc.units:
        g = labels.get(u.group, "-")
        flag = "*" if u.group in reorder else " "
        head = f"[{u.title.strip()}] " if u.title else ""
        text = " ".join(latex.plain_text(head + u.text).split())
        print(f"  {u.id} {g:>4}{flag} {u.section[:22]:<22} {text[:90]}")
    print("\n(* = bullets in this list can be reordered)")
    ok = latex.render(doc) == src
    print(f"Round-trip check (render with no edits == original): {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def cmd_models(args) -> int:
    from .llm import list_gemini_models

    for name in list_gemini_models():
        print(name)
    return 0


def cmd_tailor(args) -> int:
    from .llm import build_llm
    from .report import markdown

    resume_path = Path(args.resume)
    resume = resume_path.read_text(encoding="utf-8")
    if args.jd == "-":
        jd = sys.stdin.read()
    elif Path(args.jd).exists():
        jd = read_text(args.jd)
    else:
        jd = args.jd  # treat as literal text
    facts = read_text(args.facts) if args.facts and Path(args.facts).exists() else ""

    opts = Options(
        locked_sections=tuple(args.lock) if args.lock else DEFAULT_LOCKED,
        allow_drops=not args.no_drop,
        allow_section_reorder=not args.keep_section_order,
        section_order="keep" if args.keep_section_order else args.section_order,
        max_pages=args.max_pages,
        compile=not args.no_pdf,
    )
    if args.plan:
        from .llm import FakeLLM, parse_plan

        llm = FakeLLM(parse_plan(Path(args.plan).read_text(encoding="utf-8")))
        llm.name = f"replay:{Path(args.plan).name}"
    else:
        llm = build_llm(gemini_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "",
                        openai_key=os.getenv("OPENAI_API_KEY", ""), gemini_model=args.model,
                        cache=not args.no_cache)
    print(f"Tailoring with {llm.name} ...", file=sys.stderr)
    res = tailor(resume, jd, llm, facts=facts, opts=opts,
                 compiler=Compiler(engine=args.engine, assets_dir=resume_path.parent),
                 instructions=args.instructions or "")

    name = args.name or slug(res.plan.company, res.plan.role)
    out = Path(args.out) / f"{dt.date.today():%Y%m%d}_{name}"
    out.mkdir(parents=True, exist_ok=True)
    stem = args.stem or resume_path.stem
    (out / f"{stem}.tex").write_text(res.tex, encoding="utf-8")
    (out / "report.md").write_text(markdown(res), encoding="utf-8")
    (out / "plan.json").write_text(json.dumps(res.plan.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "job_description.txt").write_text(jd, encoding="utf-8")
    if res.pdf:
        (out / f"{stem}.pdf").write_bytes(res.pdf)

    accepted = sum(v.status == "accepted" for v in res.verdicts)
    rejected = sum(v.status == "rejected" for v in res.verdicts)
    print(f"\n{res.plan.role} @ {res.plan.company}")
    print(f"  keyword coverage : {res.coverage_before:.0%} -> {res.coverage_after:.0%}")
    print(f"  bullets rewritten: {accepted}   blocked by guardrails: {rejected}")
    if res.dropped_by_llm or res.dropped_for_fit:
        print(f"  bullets dropped  : {len(res.dropped_by_llm) + len(res.dropped_for_fit)}")
    if res.compile:
        print(f"  pdf              : {'OK' if res.compile.ok else 'FAILED'} ({res.compile.pages} page(s), {res.compile.engine})")
        if not res.compile.ok:
            print(res.compile.log, file=sys.stderr)
    for w in res.warnings:
        print(f"  ! {w}")
    print(f"\nOutput: {out}/")
    return 0 if (res.compile is None or res.compile.ok) else 2


def main(argv: list[str] | None = None) -> int:
    _load_env()
    p = argparse.ArgumentParser(prog="tailortex", description="Tailor a LaTeX resume to a job description with Gemini.")
    p.add_argument("--version", action="version", version=f"tailortex {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("tailor", help="tailor a resume to a JD")
    t.add_argument("resume", help="path to your .tex resume")
    t.add_argument("--jd", required=True, help="JD file (.txt/.md/.pdf/.docx), '-' for stdin, or literal text")
    t.add_argument("--facts", default=os.getenv("TAILORTEX_FACTS", "facts.md"),
                   help="optional file of true facts not on your resume (default: facts.md if present)")
    t.add_argument("--out", default="output", help="output directory (default: output/)")
    t.add_argument("--name", help="output folder name (default: company_role)")
    t.add_argument("--stem", help="output file name stem (default: same as input)")
    t.add_argument("--model", help="Gemini model id (default: $GEMINI_MODEL or gemini-3.1-flash-lite)")
    t.add_argument("--engine", help="tectonic | latexmk | pdflatex | xelatex (default: auto)")
    t.add_argument("--max-pages", type=int, default=1, help="drop least-relevant bullets until it fits (0 = off)")
    t.add_argument("--lock", action="append", help="section to never edit (repeatable; default: Education)")
    t.add_argument("--no-drop", action="store_true", help="never let the model remove bullets")
    t.add_argument("--keep-section-order", action="store_true", help="don't reorder sections")
    t.add_argument("--section-order", choices=["ai", "keep", "experience", "education"], default="ai",
                   help="ai (model decides, default) | keep | experience (work first) | education (degree first)")
    t.add_argument("--no-pdf", action="store_true", help="skip PDF compilation")
    t.add_argument("--no-cache", action="store_true", help="always call the model (ignore the plan cache)")
    t.add_argument("--instructions", "-i", help='your own guidance for the rewrite, e.g. "keep bullets short"')
    t.add_argument("--plan", help="replay a saved plan.json instead of calling Gemini (e.g. after hand-editing it)")
    t.set_defaults(func=cmd_tailor)

    i = sub.add_parser("inspect", help="show how a resume is parsed (no API call)")
    i.add_argument("resume")
    i.set_defaults(func=cmd_inspect)

    m = sub.add_parser("models", help="list Gemini models available to your key")
    m.set_defaults(func=cmd_models)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
