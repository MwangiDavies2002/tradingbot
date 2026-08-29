"""
main.py
────────────────────────────────────────────────────────────────────────────────
FastAPI Application Entry Point
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Creates the FastAPI application, registers all routers, configures
    middleware (CORS, rate limiting, logging), connects to the database
    and Redis on startup, and exposes health check endpoints.

    This is the file uvicorn runs:
        uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

    Startup sequence:
        1. Validate settings (raises on missing required env vars)
        2. Configure logging
        3. Initialise Sentry (if DSN set)
        4. Connect to database, run health check
        5. Connect to Redis
        6. Register all API routers
        7. Register WebSocket endpoint for dashboard
        8. Start the bot loop in a background task

    Shutdown sequence:
        1. Signal bot loop to stop gracefully
        2. Close all Deriv WebSocket subscriptions
        3. Close database engine / Redis connection pool
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import logging
import logging.config
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.database.session import check_connection, create_tables

logger = logging.getLogger(__name__)
RUNNING_ON_VERCEL = (
    os.getenv("VERCEL") == "1"
    or os.getenv("VERCEL_ENV") is not None
    or os.getenv("VERCEL_SERVERLESS") == "1"
)


# ── Logging Setup ─────────────────────────────────────────────────────────────

def configure_logging() -> None:
    """Configure structured logging for the entire application."""
    logging.config.dictConfig({
        "version":    1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "json": {
                "()":     "pythonjsonlogger.jsonlogger.JsonFormatter",
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class":     "logging.StreamHandler",
                "formatter": "standard",
                "level":     settings.LOG_LEVEL,
            },
        },
        "root": {
            "level":    settings.LOG_LEVEL,
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn":       {"level": "INFO",    "propagate": False, "handlers": ["console"]},
            "sqlalchemy":    {"level": "WARNING", "propagate": False, "handlers": ["console"]},
            "websockets":    {"level": "WARNING", "propagate": False, "handlers": ["console"]},
            "httpx":         {"level": "WARNING", "propagate": False, "handlers": ["console"]},
        },
    })


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    FastAPI lifespan context manager.
    Replaces the deprecated @app.on_event("startup") / ("shutdown") pattern.
    Everything before `yield` runs on startup, everything after on shutdown.
    """
    # ── STARTUP ───────────────────────────────────────────────────────────────
    configure_logging()
    logger.info("=" * 60)
    logger.info("Starting %s v%s [%s]",
                settings.APP_NAME, settings.APP_VERSION, settings.ENVIRONMENT)
    logger.info("=" * 60)

    # Sentry error tracking
    if settings.sentry_enabled:
        try:
            import sentry_sdk
            sentry_sdk.init(dsn=settings.SENTRY_DSN, traces_sample_rate=0.1)
            logger.info("Sentry initialised")
        except ImportError:
            logger.warning("sentry-sdk not installed — error tracking disabled")

    # Database
    logger.info("Connecting to database...")
    db_ok = await check_connection()
    if not db_ok:
        logger.error("Database connection FAILED — check DATABASE_URL in .env")
    elif not RUNNING_ON_VERCEL:
        await create_tables()
        logger.info("Database connected ✓")
    else:
        logger.info("Database connected ✓ (schema managed externally on Vercel)")

    # Redis
    try:
        import redis.asyncio as aioredis
        app.state.redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await app.state.redis.ping()
        logger.info("Redis connected ✓")
    except Exception as exc:
        logger.warning("Redis not available: %s — running without cache", exc)
        app.state.redis = None

    logger.info("API ready — listening on port 8000")
    logger.info("-" * 60)

    yield   # ← App is running here

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    logger.info("Shutting down %s...", settings.APP_NAME)
    if hasattr(app.state, "redis") and app.state.redis:
        await app.state.redis.aclose()
        logger.info("Redis connection closed")
    logger.info("Shutdown complete")


# ── App Creation ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """
    Factory function that creates and configures the FastAPI application.
    Allows easy creation of test instances with different configs.
    """
    app = FastAPI(
        title        = settings.APP_NAME,
        version      = settings.APP_VERSION,
        description  = "Mean Reversion Trading Bot — REST API",
        docs_url     = "/docs"  if not settings.is_production else None,
        redoc_url    = "/redoc" if not settings.is_production else None,
        lifespan     = lifespan,
    )

    # ── Middleware ────────────────────────────────────────────────────────────

    app.add_middleware(
        CORSMiddleware,
        allow_origins     = settings.ALLOWED_ORIGINS,
        allow_credentials = True,
        allow_methods     = ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers     = ["*"],
    )

    # Request timing middleware
    @app.middleware("http")
    async def add_timing_header(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time-Ms"] = f"{ms:.1f}"
        return response

    # ── Routers ───────────────────────────────────────────────────────────────
    # Import here to avoid circular imports at module level
    from app.api.routes import bot_control, config, risk, signals, test, trades

    app.include_router(trades.router,      prefix="/api/trades",   tags=["Trades"])
    app.include_router(signals.router,     prefix="/api/signals",  tags=["Signals"])
    app.include_router(risk.router,        prefix="/api/risk",     tags=["Risk"])
    app.include_router(bot_control.router, prefix="/api/bot",      tags=["Bot Control"])
    app.include_router(config.router,      prefix="/api/config",   tags=["Config"])
    app.include_router(test.router,        prefix="/api",          tags=["Diagnostics"])
    from app.api.routes import backtest

    app.include_router(backtest.router, prefix="/api/backtest", tags=["Backtest"])

    # ── Health & Meta Endpoints ───────────────────────────────────────────────

    @app.get("/health", tags=["Meta"])
    async def health_check(request: Request):
        """
        Health check endpoint.
        Returns 200 if the API is running.
        Used by Docker health checks and load balancers.
        """
        redis_ok = False
        if hasattr(request.app.state, "redis") and request.app.state.redis:
            try:
                await request.app.state.redis.ping()
                redis_ok = True
            except Exception:
                pass

        db_ok = await check_connection()

        # Redis is an optional cache. Vercel/Supabase deployments can run without it.
        status = "healthy" if db_ok else "degraded"
        return JSONResponse(
            status_code = 200 if status == "healthy" else 207,
            content     = {
                "status":      status,
                "version":     settings.APP_VERSION,
                "environment": settings.ENVIRONMENT,
                "database":    "ok" if db_ok else "error",
                "redis":       "ok" if redis_ok else "unavailable",
            },
        )

    @app.get("/", tags=["Meta"])
    async def root():
        return {
            "name":    settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs":    "/docs",
            "health":  "/health",
        }

    # ── Global Exception Handlers ─────────────────────────────────────────────

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        logger.warning("ValueError on %s: %s", request.url, exc)
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception on %s: %s", request.url, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


# ── Module-level app instance (for uvicorn) ───────────────────────────────────
app = create_app()
