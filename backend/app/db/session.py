"""Async SQLAlchemy engine and session management."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_settings = get_settings()

engine = create_async_engine(
    str(_settings.DATABASE_URL),
    pool_size=_settings.DB_POOL_SIZE,
    max_overflow=_settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    echo=_settings.DB_ECHO,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """FastAPI dependency for code that opens its OWN sessions after the
    request ends (background pipeline). Overridable in tests."""
    return async_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request.

    Services own explicit transaction boundaries (session.commit); the
    dependency guarantees rollback on unhandled errors and always closes.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
