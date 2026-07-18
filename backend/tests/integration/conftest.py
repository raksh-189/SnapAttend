"""Integration test fixtures.

Creates a dedicated `attendai_test` database on the dev Postgres container,
builds the schema from the ORM metadata, and yields an HTTP client whose
app talks to that database. Tables are truncated between tests.

Requires the compose `db` service to be running (docker compose up -d db).
Tests are skipped automatically if the database is unreachable.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401  — registers every table on Base.metadata
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db

ADMIN_URL = "postgresql+asyncpg://attendai:attendai_dev@localhost:5432/attendai"
TEST_URL = "postgresql+asyncpg://attendai:attendai_dev@localhost:5432/attendai_test"


@pytest.fixture(scope="session")
async def test_engine():
    # Create the test database (idempotent), then the schema.
    try:
        admin_engine = create_async_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = 'attendai_test'")
            )
            if not exists:
                await conn.execute(text("CREATE DATABASE attendai_test"))
        await admin_engine.dispose()
    except Exception as exc:  # DB not running — skip the integration suite
        pytest.skip(f"database unavailable: {exc}")

    engine = create_async_engine(TEST_URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        yield session
    # Reset state between tests.
    async with test_engine.begin() as conn:
        tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
async def client(test_engine, db_session):
    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()

    factory = async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)

    async def _override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
