# --- builder: install deps into a venv ---
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml ./
# Install runtime deps only (project itself copied below in final stage)
RUN pip install .

# --- runtime ---
FROM python:3.11-slim

# libgomp1: required by onnxruntime (CPU) from Module 4 onward
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser
WORKDIR /srv/app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

RUN mkdir -p /srv/app/media /srv/app/models && chown -R appuser:appuser /srv/app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Railway/Render inject PORT; default 8000 for local/compose.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
