"""Streamlit front end:  streamlit run app.py

Bring-your-own-key: visitors paste their own Gemini API key; it lives only in their
browser session. A server-side key (GEMINI_API_KEY) is used ONLY when the host sets
TAILORTEX_USE_SERVER_KEY=1 (handy for local use) - never by default.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import threading
import time
from pathlib import Path

import streamlit as st

from tailortex import latex
from tailortex.compiler import Compiler
from tailortex.engine import Options, tailor
from tailortex.inputs import slug, text_from_bytes
from tailortex.llm import DEFAULT_MODEL, build_llm
from tailortex.prompts import MAX_INSTRUCTIONS
from tailortex.security import MAX_FACTS_CHARS, MAX_JD_CHARS, MAX_TEX_BYTES, check_tex, redact
from tailortex.report import changes, markdown

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

st.set_page_config(page_title="tailortex · tailor your resume", page_icon="🧵", layout="wide",
                   initial_sidebar_state="collapsed")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"], .stApp { font-family: 'Inter', system-ui, sans-serif; }
#MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }
.stApp {
  background: radial-gradient(900px 500px at 10% -10%, rgba(99,102,241,.22), transparent 60%),
              radial-gradient(800px 500px at 100% 0%, rgba(236,72,153,.16), transparent 55%),
              #0b0d14;
  color: #e6e8f0;
}
.block-container { max-width: 1180px; padding-top: 2.2rem; padding-bottom: 4rem; }

.hero { text-align: center; padding: 1.2rem 0 1.8rem; }
.hero .pill { display:inline-block; padding:.3rem .8rem; border-radius:999px; font-size:.78rem; font-weight:600;
  color:#c7d2fe; background:rgba(99,102,241,.15); border:1px solid rgba(129,140,248,.35); letter-spacing:.02em; }
.hero h1 { font-size: clamp(2.2rem, 5vw, 3.6rem); font-weight: 800; letter-spacing:-.03em; margin:.8rem 0 .4rem;
  background: linear-gradient(90deg,#fff 0%,#a5b4fc 50%,#f9a8d4 100%); -webkit-background-clip:text;
  background-clip:text; color:transparent; }
.hero p { color:#9aa3b8; font-size:1.08rem; max-width:680px; margin:0 auto; line-height:1.6; }
.trust { display:flex; gap:.6rem; justify-content:center; flex-wrap:wrap; margin-top:1.1rem; }
.trust span { font-size:.8rem; color:#b6bfd4; background:rgba(255,255,255,.04);
  border:1px solid rgba(255,255,255,.08); padding:.3rem .7rem; border-radius:8px; }

.step { display:flex; align-items:center; gap:.7rem; margin:.2rem 0 .6rem; }
.step .n { width:28px; height:28px; border-radius:50%; display:grid; place-items:center; font-weight:700;
  font-size:.85rem; color:#fff; background:linear-gradient(135deg,#6366f1,#ec4899); }
.step .t { font-size:1.05rem; font-weight:650; color:#f1f3fa; }

div[data-testid="stVerticalBlockBorderWrapper"] {
  background: rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.09) !important;
  border-radius: 16px; backdrop-filter: blur(6px); }
div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input {
  background: rgba(8,10,18,.7) !important; border:1px solid rgba(255,255,255,.12) !important;
  border-radius:10px !important; color:#e6e8f0 !important; }
div[data-testid="stTextInput"] input:focus, div[data-testid="stTextArea"] textarea:focus {
  border-color:#818cf8 !important; box-shadow:0 0 0 3px rgba(99,102,241,.25) !important; }
div[data-baseweb="textarea"], div[data-baseweb="input"], div[data-baseweb="base-input"] {
  background: rgba(8,10,18,.7) !important; border-radius:10px !important; }
div[data-testid="stTextArea"] > div, div[data-testid="stTextInput"] > div > div,
div[data-testid="stNumberInput"] > div > div { background: rgba(8,10,18,.7) !important;
  border:1px solid rgba(255,255,255,.12) !important; border-radius:10px !important; }
div[data-testid="stTextArea"] textarea, div[data-testid="stTextInput"] input {
  background: transparent !important; border:0 !important; box-shadow:none !important; }
div[data-testid="stTextArea"] > div:focus-within, div[data-testid="stTextInput"] > div > div:focus-within {
  border-color:#818cf8 !important; box-shadow:0 0 0 3px rgba(99,102,241,.25) !important; }
div[data-testid="stTextArea"] textarea { -webkit-text-fill-color:#e6e8f0 !important; }
::placeholder { color:#6b7389 !important; -webkit-text-fill-color:#6b7389 !important; opacity:1 !important; }
section[data-testid="stFileUploaderDropzone"] { background: rgba(8,10,18,.55) !important;
  border:1.5px dashed rgba(129,140,248,.45) !important; border-radius:12px; }
section[data-testid="stFileUploaderDropzone"] button { background: rgba(99,102,241,.18) !important;
  color:#e0e7ff !important; border:1px solid rgba(129,140,248,.5) !important; border-radius:9px; }
section[data-testid="stFileUploaderDropzone"] button *, section[data-testid="stFileUploaderDropzone"] small,
section[data-testid="stFileUploaderDropzone"] span { color:#b6bfd4 !important; }
a[data-testid="stBaseLinkButton-secondary"], .stLinkButton a { background: rgba(255,255,255,.06) !important;
  color:#e6e8f0 !important; border:1px solid rgba(255,255,255,.14) !important; border-radius:10px !important; }
.stLinkButton a:hover { border-color:#818cf8 !important; }
div[data-testid="stExpander"] { background: rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.08);
  border-radius:12px; }
label, .stMarkdown p, .stCaption, [data-testid="stWidgetLabel"] p { color:#b6bfd4; }

.stButton > button[kind="primary"], .stDownloadButton > button {
  border-radius: 12px; font-weight:650; padding:.7rem 1.2rem; border:0; }
.stButton > button[kind="primary"] { background: linear-gradient(90deg,#6366f1,#ec4899); color:#fff;
  box-shadow:0 8px 28px rgba(99,102,241,.35); transition: transform .12s ease, box-shadow .12s ease; }
.stButton > button[kind="primary"]:hover:not(:disabled) { transform: translateY(-1px);
  box-shadow:0 12px 34px rgba(236,72,153,.35); }
.stButton > button[kind="primary"]:disabled { opacity:.35; }
.stDownloadButton > button { background: rgba(255,255,255,.06); color:#e6e8f0; border:1px solid rgba(255,255,255,.12); }
.stDownloadButton > button:hover { border-color:#818cf8; color:#fff; }

div[data-testid="stMetric"] { background: rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.09);
  border-radius:14px; padding:1rem 1.1rem; }
div[data-testid="stMetricValue"] { font-weight:800; letter-spacing:-.02em; }
.stTabs [data-baseweb="tab-list"] { gap:.25rem; border-bottom:1px solid rgba(255,255,255,.08); }
.stTabs [data-baseweb="tab"] { border-radius:10px 10px 0 0; padding:.6rem 1rem; color:#9aa3b8; }
.stTabs [aria-selected="true"] { color:#fff; }
details { border-radius:12px !important; }

.diff { border-radius:12px; padding:.8rem 1rem; margin:.35rem 0; font-size:.93rem; line-height:1.55; }
.diff.b { background:rgba(239,68,68,.09); border-left:3px solid #ef4444; color:#f3c9c9; }
.diff.a { background:rgba(34,197,94,.09); border-left:3px solid #22c55e; color:#c9f1d6; }
.chip { display:inline-block; margin:.15rem .25rem .15rem 0; padding:.2rem .6rem; border-radius:999px; font-size:.8rem; }
.chip.ok { background:rgba(34,197,94,.14); color:#86efac; border:1px solid rgba(34,197,94,.3); }
.chip.no { background:rgba(245,158,11,.12); color:#fcd34d; border:1px solid rgba(245,158,11,.3); }
.privacy { font-size:.8rem; color:#8b94a9; margin-top:.4rem; }
.foot { text-align:center; color:#6b7389; font-size:.8rem; margin-top:3rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


ORDER_CHOICES = {
    "Experience first (recommended): Experience → Projects → Skills → Education": "experience",
    "Education first (students / freshers): Education → Projects → Skills → Experience": "education",
    "Keep my original order": "keep",
    "Let the AI decide per job": "ai",
}


def session_memo(bucket: str, key, fn):
    """Per-visitor memo. Streamlit reruns the script on every click, so slow steps (PDF extraction, parsing)
    are remembered - but only inside this visitor's session, never in a cache shared between users."""
    store = st.session_state.setdefault(bucket, {})
    if key not in store:
        store.clear()  # keep only the latest input
        store[key] = fn()
    return store[key]


@st.cache_resource
def get_compiler() -> Compiler:
    # strict: every uploaded source is scanned for file-reading / shell commands before compiling
    return Compiler(strict=True, timeout=60)


@st.cache_resource
def run_slots() -> threading.BoundedSemaphore:
    # at most N tailoring jobs (LLM + LaTeX) at once across all visitors, so one user can't starve the server
    return threading.BoundedSemaphore(int(os.getenv("TAILORTEX_MAX_CONCURRENT", "3")))


RUNS_PER_HOUR = int(os.getenv("TAILORTEX_RUNS_PER_HOUR", "20"))


def rate_limited() -> bool:
    now = time.time()
    hist = [t for t in st.session_state.get("run_times", []) if now - t < 3600]
    st.session_state.run_times = hist
    return len(hist) >= RUNS_PER_HOUR


def esc(s) -> str:
    """Escape text from users / the model / the JD before it goes into HTML."""
    return html.escape(str(s), quote=True)


def plain_error(msg: str) -> str:
    """Provider error -> short, key-free, link-free text safe to show."""
    msg = redact(msg)
    msg = re.sub(r"https?://\S+|www\.\S+", "", msg)  # no auto-linked URLs from third-party error bodies
    return re.sub(r"\s+", " ", msg).strip()[:300]


MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()<>#+\-.!|~])")


def md_esc(s) -> str:
    """Escape Markdown so model output can't render links or remote images (data exfiltration via prompt injection)."""
    return MD_SPECIAL.sub(r"\\\1", str(s))


def server_key() -> str:
    """Server-side key, only when the host explicitly opts in."""
    if os.getenv("TAILORTEX_USE_SERVER_KEY") != "1":
        return ""
    try:
        return st.secrets.get("GEMINI_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    except Exception:
        return os.getenv("GEMINI_API_KEY", "")


def step(n: int, title: str) -> None:
    st.markdown(f'<div class="step"><div class="n">{n}</div><div class="t">{title}</div></div>',
                unsafe_allow_html=True)


# ---------------- hero ----------------
st.markdown("""
<div class="hero">
  <span class="pill">✦ Works with OpenAI or Google Gemini · Gemini free tier works</span>
  <h1>Tailor your resume to any job.<br/>Nothing invented.</h1>
  <p>Upload your LaTeX resume, paste a job description, and get a compile-checked, one-page resume
  in the job's language — with every change explained.</p>
  <div class="trust"><span>🔒 Your key stays in your session</span><span>🧱 Template never touched</span>
  <span>🛡️ Fabrication guardrails</span><span>📄 PDF + .tex + report</span></div>
</div>
""", unsafe_allow_html=True)

compiler = get_compiler()
N = st.session_state.setdefault("_nonce", 0)  # suffix for widget keys; bumped by "Clear my data"

# ---------------- step 1: key ----------------
with st.container(border=True):
    step(1, "Your API key(s)")
    k1, k2 = st.columns([3, 1])
    srv = server_key()
    oai_key = k1.text_input("OpenAI API key", type="password", placeholder="OpenAI key (sk-…) — tried first",
                            key=f"oai_{N}", autocomplete="off",
                            help="Tried first. If it fails or is out of quota, your Gemini key is used.")
    gem_key = k1.text_input("Gemini API key", type="password", placeholder="Gemini key (AIza…) — free backup",
                            key=f"gem_{N}", autocomplete="off",
                            help="Free key from https://aistudio.google.com/apikey. Used if OpenAI fails, "
                                 "or on its own if you leave OpenAI empty.")
    if not gem_key and srv:
        gem_key = srv
        k1.caption("Using the server's Gemini key.")
    k2.link_button("Get an OpenAI key ↗", "https://platform.openai.com/api-keys", width="stretch")
    k2.link_button("Get a free Gemini key ↗", "https://aistudio.google.com/apikey", width="stretch")
    api_key = oai_key or gem_key
    st.markdown('<div class="privacy">🔒 Add one or both. OpenAI is tried first; if it fails or is overloaded, '
                'Gemini takes over automatically. Keys are used only for this session — never saved, logged or shared.</div>',
                unsafe_allow_html=True)
    with st.expander("⚙️ Advanced options"):
        a1, a2 = st.columns(2)
        model = a1.text_input("Gemini model", value=os.getenv("GEMINI_MODEL") or DEFAULT_MODEL)
        max_pages = a2.number_input("Max pages", 0, 3, 1, help="Drop least-relevant bullets until it fits. 0 = off")
        locked = a1.text_input("Locked sections (comma separated)", "Education")
        allow_drops = a2.checkbox("Let the model drop irrelevant bullets", True)
        order_label = st.selectbox(
            "Section order", list(ORDER_CHOICES), index=0,
            help="Experience-first suits most people with work history. Education-first suits students and "
                 "recent graduates. Bullets inside each section are still tailored.")
        section_order = ORDER_CHOICES[order_label]
        st.caption(f"LaTeX engine on this server: `{compiler.engine or 'none — .tex only'}`")

st.write("")

# ---------------- steps 2 & 3: inputs ----------------
c1, c2 = st.columns(2, gap="large")
with c1, st.container(border=True):
    step(2, "Your resume (.tex)")
    default_path = os.getenv("TAILORTEX_RESUME", "")
    up = st.file_uploader("LaTeX resume", type=["tex"], label_visibility="collapsed", key=f"up_{N}")
    resume_tex = ""
    if up:
        data = up.getvalue()
        if len(data) > MAX_TEX_BYTES:
            st.error(f"That file is over {MAX_TEX_BYTES // 1000} KB — a .tex resume is normally under 30 KB.")
        else:
            try:
                resume_tex = data.decode("utf-8")
            except UnicodeDecodeError:
                st.error("That file isn't UTF-8 text. Upload the .tex source, not a PDF.")
    elif default_path and Path(default_path).exists():
        resume_tex = Path(default_path).read_text(encoding="utf-8")
        st.info("Using the default resume configured on this server.")
    if resume_tex:
        problems = check_tex(resume_tex)
        if problems:
            st.error("This file can't be processed for security reasons:\n\n" +
                     "\n".join(f"- {md_esc(p)}" for p in problems[:6]))
            resume_tex = ""
    if resume_tex:
        try:
            doc = session_memo("_parse", hashlib.sha256(resume_tex.encode()).hexdigest(),
                               lambda: latex.parse(resume_tex))
            st.success(f"Parsed {len(doc.units)} editable bullets across {len(doc.sections)} sections.")
            with st.expander("What the tool can edit"):
                for u in doc.units:
                    head = f"**{md_esc(latex.plain_text(u.title))}** — " if u.title else ""
                    st.markdown(f"`{u.id}` *{md_esc(u.section)}* · {head}{md_esc(latex.plain_text(u.text)[:140])}")
        except ValueError as e:
            st.error(md_esc(e))
            resume_tex = ""
    facts = st.text_area("Extra true facts (optional)", height=110, max_chars=MAX_FACTS_CHARS, key=f"facts_{N}",
                         placeholder="Things that are true but not on your resume, e.g.\n- Used Airflow to schedule ETL jobs\n- Familiar with dbt")

with c2, st.container(border=True):
    step(3, "Job description")
    jd_file = st.file_uploader("JD file", type=["txt", "md", "pdf", "docx"], label_visibility="collapsed",
                               key=f"jdf_{N}")
    jd_text = st.text_area("…or paste it", height=250, max_chars=MAX_JD_CHARS, key=f"jd_{N}",
                           placeholder="Paste the full job description here")
    if jd_file:
        data = jd_file.getvalue()
        try:
            jd_text = session_memo("_jd", hashlib.sha256(data).hexdigest(),
                                   lambda: text_from_bytes(data, jd_file.name))[:MAX_JD_CHARS]
            st.caption(f"Loaded {len(jd_text.split())} words from {md_esc(jd_file.name)}")
        except Exception:
            st.error("Couldn't read that file. Paste the job description as text instead.")
            jd_text = ""

st.write("")
with st.container(border=True):
    step(4, "Your instructions (optional)")
    instructions = st.text_area(
        "Tell the AI what to change", height=110, max_chars=MAX_INSTRUCTIONS, label_visibility="collapsed",
        key=f"ins_{N}",
        placeholder="Tell the AI exactly what you want, e.g.\n"
                    "- Emphasise Power BI and stakeholder communication\n"
                    "- Keep bullets short and punchy, don't touch my Projects section\n"
                    "- Make the tone more senior / leadership-focused")
    st.caption("Your instructions guide the rewrite, but the guardrails still apply: nothing new can be "
               "invented (no new tools, skills or numbers).")

st.write("")
missing = [n for n, ok in (("an API key (Gemini or OpenAI)", bool(api_key)), ("resume", bool(resume_tex)),
                           ("job description", bool(jd_text.strip()))) if not ok]
b1, b2, b3 = st.columns([1, 2, 1])
go = b2.button("✨ Tailor my resume", type="primary", width="stretch", disabled=bool(missing))
if missing:
    b2.caption("Still needed: " + ", ".join(missing))

if go:
    opts = Options(
        locked_sections=tuple(s.strip() for s in locked.split(",") if s.strip()),
        allow_drops=allow_drops, allow_section_reorder=section_order == "ai", section_order=section_order,
        max_pages=int(max_pages), compile=compiler.available,
    )
    slots = run_slots()
    if rate_limited():
        st.error(f"You've reached {RUNS_PER_HOUR} runs this hour. Please try again later.")
    elif not slots.acquire(timeout=90):
        st.error("The server is busy right now. Please try again in a minute.")
    else:
        st.session_state.run_times.append(time.time())
        try:
            with st.status("Tailoring your resume…", expanded=True) as status:
                st.write("🤖 Asking the model for a structured edit plan (cached if you've run this exact input before)")
                st.write("🛡️ Checking every edit against the guardrails, then compiling")
                try:
                    # per-visitor in-memory cache: repeat runs are instant and nothing is written to server disk
                    cache = st.session_state.setdefault("plan_cache", {})
                    llm = build_llm(gemini_key=gem_key.strip(), openai_key=oai_key.strip(),
                                    gemini_model=model.strip()[:80], cache_store=cache)
                    st.session_state.result = tailor(resume_tex, jd_text[:MAX_JD_CHARS], llm,
                                                     facts=facts[:MAX_FACTS_CHARS], opts=opts, compiler=compiler,
                                                     instructions=instructions)
                    used = llm.name
                    fails = getattr(getattr(llm, "inner", llm), "errors", [])
                    if fails:
                        st.caption(md_esc("Fell back after: " + plain_error(" | ".join(fails))))
                    status.update(label=f"Done via {used} — scroll down for your results", state="complete",
                                  expanded=False)
                except Exception as e:  # surface API / parse errors to the user - never with a key in them
                    msg = plain_error(str(e))
                    if any(t in msg for t in ("API key", "API_KEY", "401", "403", "PERMISSION", "invalid_api_key")):
                        msg = "A provider rejected the API key. Check your key(s) and try again. (" + msg + ")"
                    status.update(label="Something went wrong", state="error")
                    st.error(md_esc(msg))
        finally:
            slots.release()

# ---------------- results ----------------
res = st.session_state.get("result")
if res:
    st.write("")
    p = res.plan
    st.markdown(f"<h3>{esc(p.role)} <span style='color:#818cf8'>@ {esc(p.company)}</span></h3>",
                unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("JD keyword coverage", f"{res.coverage_after:.0%}", f"{(res.coverage_after - res.coverage_before) * 100:+.0f} pts")
    m2.metric("Bullets rewritten", sum(v.status == "accepted" for v in res.verdicts))
    m3.metric("Blocked by guardrails", sum(v.status == "rejected" for v in res.verdicts))
    m4.metric("Pages", res.compile.pages if res.compile and res.compile.ok else "—")

    st.write("")
    name = slug(p.company, p.role)
    d1, d2, d3 = st.columns(3)
    d1.download_button("⬇  Download .tex", res.tex, f"resume_{name}.tex", width="stretch")
    if res.pdf:
        d2.download_button("⬇  Download PDF", res.pdf, f"resume_{name}.pdf", "application/pdf", width="stretch")
    d3.download_button("⬇  Download report", markdown(res), f"report_{name}.md", width="stretch")
    st.write("")

    tab_changes, tab_kw, tab_pdf, tab_tex = st.tabs(["Changes", "Keywords & gaps", "PDF preview", "LaTeX"])
    with tab_changes:
        for s in p.change_summary:
            st.markdown(f"- {md_esc(s)}")
        if res.edits.section_order:
            st.info(md_esc("Section order: " + " → ".join(res.edits.section_order)))
        for r in changes(res):
            if r["status"] in ("unchanged", "locked"):
                continue
            icon = {"accepted": "✅", "rejected": "🛑"}.get(r["status"], "✂️")
            with st.expander(md_esc(f"{icon} {r['id']} · {r['section']} · {r['status']}"),
                             expanded=r["status"] == "accepted"):
                st.markdown(f'<div class="diff b"><b>Before</b><br/>{esc(r["before"])}</div>', unsafe_allow_html=True)
                if r["after"]:
                    st.markdown(f'<div class="diff a"><b>After</b><br/>{esc(r["after"])}</div>', unsafe_allow_html=True)
                if r["reasons"]:
                    st.caption(md_esc(r["reasons"]))
    with tab_kw:
        gaps = set(res.unsupported_keywords)
        k1, k2 = st.columns(2)
        k1.markdown("**Matched**")
        k1.markdown("".join(f'<span class="chip ok">{esc(k)}</span>' for k in res.matched_after) or "—",
                    unsafe_allow_html=True)
        k2.markdown("**Missing**")
        k2.markdown("".join(f'<span class="chip no">{esc(k)}{" ⚠" if k in gaps else ""}</span>'
                            for k in res.missing_after) or "—", unsafe_allow_html=True)
        if gaps:
            k2.caption("⚠ not on your resume — add to facts only if it's true")
        if p.gaps:
            st.markdown("**Requirements you show no evidence for**")
            for g in p.gaps:
                st.markdown(f"- {md_esc(g)}")
    with tab_pdf:
        if res.pdf:
            b64 = base64.b64encode(res.pdf).decode()
            st.markdown(f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="900" '
                        f'style="border:0;border-radius:12px;background:#fff"></iframe>', unsafe_allow_html=True)
        elif res.compile and not res.compile.ok:
            st.error("Compilation failed")
            st.code(redact(res.compile.log)[:4000])
        else:
            st.info("No LaTeX engine available - download the .tex and compile it in Overleaf.")
    with tab_tex:
        st.code(res.tex, language="latex")
        with st.expander("Raw model plan (JSON)"):
            st.code(json.dumps(p.model_dump(), indent=2, ensure_ascii=False), language="json")
    for w in res.warnings:
        st.warning(md_esc(w))

st.write("")
_, cx, _ = st.columns([1, 2, 1])
if cx.button("🧹 Clear my data from this session", width="stretch",
             help="Wipes your keys, resume, job description and results from server memory now. "
                  "(They are also discarded automatically when you close the tab.)"):
    n = st.session_state.get("_nonce", 0) + 1
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state._nonce = n  # new widget keys -> every input (keys, uploads, text) starts empty
    st.rerun()

st.markdown('<div class="foot">tailortex · open source · read the report before you send anything</div>',
            unsafe_allow_html=True)
