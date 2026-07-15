"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.core.config import get_settings
from app.core.exceptions import DomainError, domain_error_handler
from app.core.logging import configure_logging, get_logger
from app.db.session import engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("startup", app=settings.APP_NAME, env=settings.ENVIRONMENT)
    # Fail fast if the database is unreachable.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("database_connected")
    # Module 4 will load the InsightFace model here (once, before serving).
    yield
    await engine.dispose()
    logger.info("shutdown")


def create_app() -> FastAPI:
    configure_logging()
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_exception_handler(DomainError, domain_error_handler)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        """Liveness + DB reachability. Used by Docker healthcheck and Railway/Render."""
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "app": settings.APP_NAME}

    # API v1 routers are mounted here as modules land (Module 2+):
    # app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

    return app


app = create_app()
