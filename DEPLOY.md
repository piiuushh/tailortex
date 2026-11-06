# Deploying tailortex (beginner guide)

This guide takes you from "it runs on my laptop" to "anyone can use it at a public link" —
no sign-in for visitors, each visitor brings their own API key.

---

## 0. First: why not Vercel?

Vercel runs short-lived **serverless functions** (they start, answer one request, and stop).
tailortex is a **Streamlit** app, which needs:

* a server that **stays running** and keeps a **WebSocket** open to each visitor — Vercel functions can't;
* **LaTeX** (~500 MB) to build PDFs — far over Vercel's 250 MB function limit.

So use a host that runs a normal long-lived server. Two good options:

| | **A. Streamlit Community Cloud** (recommended) | **B. Render** (Docker) |
|---|---|---|
| Cost | Free | Free tier (sleeps when idle) / ~$7 per month always-on |
| Difficulty | Easiest — no Docker | Easy |
| Custom domain | No (`yourapp.streamlit.app`) | Yes |
| Uses | `requirements.txt` + `packages.txt` | `Dockerfile` |

---

## 1. Before you publish anything (do this once)

1. **Rotate your Gemini key.** Your current key was shared in a chat, so treat it as exposed:
   open <https://aistudio.google.com/apikey>, delete the old key, create a new one, and put the new one in your local `.env`.
2. **Set a spending limit** on any OpenAI key you use (<https://platform.openai.com/settings/organization/limits>).
3. **Never** put `GEMINI_API_KEY` / `OPENAI_API_KEY` in the host's settings. The public app doesn't need any
   secret — visitors paste their own key. Also leave these **unset** in production:
   * `TAILORTEX_USE_SERVER_KEY` (would let every visitor spend *your* key)
   * `TAILORTEX_RESUME` (would show *your* resume to every visitor)

---

## 2. Put the code on GitHub

You don't have Git installed, so use **GitHub Desktop** (point-and-click):

1. Create a free account at <https://github.com>.
2. Install GitHub Desktop: <https://desktop.github.com> and sign in.
3. **File → Add local repository…** → choose the inner `tailortex` folder
   (`C:\Users\hp\OneDrive\Desktop\tailortex\tailortex` — the one with `app.py`, **not** the outer folder that holds `my_resume.tex`).
4. Look at the **Changes** list on the left. You must **NOT** see any of these — if you do, stop:
   * `.env` (your key) · `my_resume.tex` · `output/` · `facts.md` · `.tailortex_cache/`

   They're blocked by `.gitignore`, so normally they won't appear.
5. Type a summary such as `Security hardening + deploy config` and click **Commit to master**.
6. Click **Publish repository**. You can keep it **Private** — both hosts below can deploy private repos.

> Double-check on github.com: open the repo, press `t`, type `.env`. Only `.env.example` should exist.

---

## 3A. Deploy on Streamlit Community Cloud (recommended)

1. Go to <https://share.streamlit.io> and **Continue with GitHub**. Allow access to your repo.
2. Click **Create app → Deploy a public app from GitHub**.
3. Fill in:
   * **Repository:** `<your-username>/tailortex`
   * **Branch:** `master` (or `main`)
   * **Main file path:** `app.py`
   * **App URL:** pick a name, e.g. `tailortex`
4. Open **Advanced settings**:
   * **Python version:** `3.12`
   * **Secrets:** paste only this (it's not secret — it just picks the LaTeX engine):
     ```toml
     TAILORTEX_ENGINE = "pdflatex"
     ```
5. Click **Deploy**. The first build takes 5–10 minutes (it installs LaTeX from `packages.txt`).
6. You get a link like `https://tailortex.streamlit.app`. Share it.

Updating later: commit + push in GitHub Desktop → the app redeploys automatically.

## 3B. Deploy on Render (Docker, custom domain possible)

1. Go to <https://render.com> → sign up with GitHub.
2. **New + → Web Service** → pick your `tailortex` repo.
3. Render detects the `Dockerfile`. Set:
   * **Runtime:** Docker
   * **Instance type:** Free (to try) or Starter (always on, faster)
   * **Environment variables:** none needed.
4. **Create Web Service**. The first build takes ~10 minutes. You get `https://tailortex.onrender.com`.
5. Optional: **Settings → Custom Domains** to use your own domain (HTTPS certificate is automatic).

---

## 4. After it's live: 5-minute smoke test

1. Open the link in a private/incognito window — no sign-in should be asked.
2. Paste your (new) Gemini key, upload your `.tex`, paste a JD → **Tailor my resume** → PDF appears.
3. Open the link in a **second** browser: the key field must be **empty** (sessions are separate).
4. Click **🧹 Clear my data** → everything resets.
5. Upload a file containing `\verbatiminput{/etc/passwd}` → it must be **refused** with a security message.

---

## 5. What is protected, and how (plain English)

| Concern | What the app does |
|---|---|
| **Visitors' API keys** | Typed into a password field, held only in that visitor's server memory session, used to call OpenAI/Gemini, and discarded when the tab closes or they click *Clear my data*. Never written to disk, never logged, never put in the cache key, and redacted from every error message. Browser autofill is off. |
| **Can *you* (the operator) see keys?** | Not in logs, files, dashboards or the cache — tested. **Honest limit:** the server must hold the key in memory for a moment to call the API, so someone who changes the app's code on the server could capture keys. That's true of every app where a server calls an API for you. Tell users to use a key with a spending limit and revoke it after use if they're worried. |
| **Encryption of user data** | **In transit:** both hosts serve HTTPS (TLS) automatically, so resume/JD/key are encrypted between browser and server. **At rest:** nothing is stored — uploads live in memory, LaTeX runs in a temporary folder deleted seconds later, results stay in the visitor's session only. With no stored data there is nothing at rest to encrypt (and nothing to leak in a breach). |
| **No sign-in** | None required. Each browser tab is its own isolated session. |
| **Malicious .tex uploads** | LaTeX can read files and run commands. Every upload is scanned and refused if it uses file-reading / shell / obfuscation commands (`\verbatiminput`, `\write18`, `\csname`, `^^` escapes, …). LaTeX then runs with shell-escape off, a scrubbed environment (no secrets visible to it) and, on Linux, `openin_any=p` (can't read files outside its temp folder). |
| **XSS / prompt injection** | Everything from the model, the JD or the resume is HTML-escaped and Markdown-escaped before display — no script, tracking image or `javascript:` link can render. |
| **Hidden env variables** | The app needs none in production. `.env` is git-ignored and Docker-ignored. Tracebacks are hidden from visitors (`showErrorDetails = "none"`). |
| **Abuse / cost** | 1 MB upload limit, text length caps, max 3 jobs at once (`TAILORTEX_MAX_CONCURRENT`), 20 runs per hour per session (`TAILORTEX_RUNS_PER_HOUR`), 60 s LaTeX timeout. Visitors pay for their own API usage. |

---

## 6. Security test results (run before release)

| Test | Result |
|---|---|
| Malicious `.tex` printing the server's `.env` into the PDF | **Was vulnerable** before hardening → now **refused** |
| 23 LaTeX attack variants (abs/relative paths, `\let`/`\def` aliases, `\csname`, `^^` escapes, `\catcode`, `\openin`, `\write18`, `\directlua`, risky packages, oversize) | all blocked; all 5 real resume templates still accepted |
| Uploading the attack through the real web UI | refused with a clear message, nothing leaked |
| XSS via the job description (`<img onerror>`, `<script>`, `javascript:` link, remote-image exfiltration via prompt injection) | the prompt injection *did* fool the model, but the app rendered it as harmless text — no script ran |
| Key typed in one browser visible in another | no |
| Keys or JD text in the server log (verbose logging) | 0 occurrences |
| Keys in error messages | redacted |
| *Clear my data* | wipes keys, uploads, text and results |
| Dependency vulnerability scan (`pip-audit`) | no known vulnerabilities |
| Automated test suite | 75 passed (1 Linux-only test runs in GitHub CI) |

**Not tested locally** (no Docker/Linux on this PC): building the Docker image, and the Linux-only
`openin_any` layer — the GitHub CI workflow runs that test on every push.
