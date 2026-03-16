FROM python:3.11-slim

# ── System deps ───────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        graphviz \
        libgraphviz-dev \
    && rm -rf /var/lib/apt/lists/*

# ── App user (never run as root) ─────────────────────────────────────────────
RUN useradd --create-home --shell /bin/bash appuser
WORKDIR /home/appuser/app
RUN chown appuser:appuser /home/appuser/app

# ── Python deps ───────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── App source ────────────────────────────────────────────────────────────────
COPY --chown=appuser:appuser . .

USER appuser

# ── Runtime ───────────────────────────────────────────────────────────────────
EXPOSE 8000

# Use 2 workers on Railway starter (1 vCPU); increase for bigger instances.
# --no-access-log: we produce our own structured access log in middleware.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--no-access-log"]
