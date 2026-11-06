# Production image for Render / Fly.io / Railway / Hugging Face Spaces / any container host.
FROM python:3.12-slim

# LaTeX for PDF builds (same packages as packages.txt for Streamlit Community Cloud)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TAILORTEX_ENGINE=pdflatex \
    # kpathsea: LaTeX may only read/write inside its own temp working dir, never shell out
    openin_any=p \
    openout_any=p \
    shell_escape=f

# run as an unprivileged user that owns nothing but its home directory
RUN useradd --create-home --uid 10001 app
WORKDIR /home/app/src

COPY pyproject.toml README.md ./
COPY tailortex ./tailortex
RUN pip install --upgrade pip && pip install ".[web]"

COPY app.py ./
COPY .streamlit ./.streamlit
RUN chown -R root:root /home/app/src && chmod -R a-w /home/app/src

USER app
EXPOSE 8501
# Render/Fly/Railway inject $PORT; default to 8501 locally
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0"]
