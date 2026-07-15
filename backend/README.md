# AttendAI Backend

FastAPI · SQLAlchemy 2.0 (async) · PostgreSQL 16 + pgvector · InsightFace (ONNX Runtime, CPU).

## Local development (Windows/macOS/Linux)

```bash
# 1. Start the database (from repo root)
docker compose up -d db

# 2. Create venv + install (Python 3.11)
cd backend
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Windows
# .venv/bin/pip install -e ".[dev]"       # macOS/Linux

# 3. Configure
cp .env.example .env                      # then set a real SECRET_KEY

# 4. Migrate + run
.venv/Scripts/alembic upgrade head
.venv/Scripts/uvicorn app.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/health` → `{"status":"ok","app":"AttendAI"}`.
Interactive docs (non-production only): http://localhost:8000/docs

## Full stack via Docker

```bash
docker compose up --build        # from repo root; backend runs migrations on startup
```

## Tests

```bash
.venv/Scripts/pytest
```

## Migrations

```bash
.venv/Scripts/alembic revision --autogenerate -m "describe change"
.venv/Scripts/alembic upgrade head
```

## Deployment (Railway/Render)

- Deploy `backend/` with its Dockerfile; the container respects `$PORT`.
- Provision a PostgreSQL instance with the `vector` extension (Railway pgvector template / Render PostgreSQL 16 + `CREATE EXTENSION vector`).
- Required env: `DATABASE_URL` (postgresql+asyncpg://…), `SECRET_KEY`, `ENVIRONMENT=production`, `CORS_ORIGINS=["https://<frontend-domain>"]`.
- Migrations run automatically on container start (`alembic upgrade head`).
