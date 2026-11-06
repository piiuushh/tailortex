"""Read job descriptions / facts from text, .md, .pdf or .docx."""

from __future__ import annotations

import io
import re
from pathlib import Path


def text_from_bytes(data: bytes, filename: str, max_pages: int = 10) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:  # a JD is 1-3 pages; cap to bound CPU on hostile PDFs
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:max_pages])
    elif suffix == ".docx":
        import docx

        d = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in d.paragraphs)
    else:
        text = data.decode("utf-8", errors="replace")
    return clean(text)


def read_text(path: str | Path) -> str:
    p = Path(path)
    return text_from_bytes(p.read_bytes(), p.name)


def clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("(cid:", "(")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def slug(*parts: str) -> str:
    s = "_".join(p for p in parts if p and p.lower() != "unknown")
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s[:60] or "tailored"
