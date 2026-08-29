"""
session.py
────────────────────────────────────────────────────────────────────────────────
Database Session Management
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Creates and manages SQLAlchemy async database sessions.
    Provides a context manager for safe session lifecycle (commit/rollback).
    Exports get_db() for FastAPI dependency injection.

    Uses async SQLAlchemy (asyncpg driver) for non-blocking Supabase Postgres
    operations that don't stall the asyncio event loop during trading.

SETUP:
    Set DATABASE_URL in your .env file:
    DATABASE_URL=postgresql+asyncpg://postgres:password@db.<project-ref>.supabase.co:5432/postgres

    For local dev with Docker:
    Use Supabase's Session Pooler connection string in serverless environments.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.database.models import Base

logger = logging.getLogger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────

database_url = settings.DATABASE_URL
if database_url.startswith("postgresql://"):
    database_url = "postgresql+asyncpg://" + database_url[len("postgresql://"):]

engine = create_async_engine(
    database_url,
    echo=settings.DB_ECHO,            # Log SQL in debug mode only
    pool_size=10,                     # Connections kept open
    max_overflow=20,                  # Extra connections allowed under load
    pool_pre_ping=True,
    pool_recycle=3600,                # Recycle connections every hour
)

# ── Session Factory ───────────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,           # Keep objects usable after commit
    autocommit=False,
    autoflush=False,
)


# ── Context Manager ───────────────────────────────────────────────────────────

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Async context manager for database sessions.

    Usage:
        async with get_session() as db:
            db.add(trade)
            await db.commit()

    Automatically rolls back on exception, always closes session.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── FastAPI Dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency injection for database sessions.

    Usage in route:
        @router.get("/trades")
        async def get_trades(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Table Creation ────────────────────────────────────────────────────────────

async def create_tables() -> None:
    """
    Create all tables defined in models.py.
    Called once on startup if tables don't exist.
    In production, use Alembic migrations instead.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified")


async def drop_tables() -> None:
    """Drop all tables. DESTRUCTIVE — dev/test use only."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    logger.warning("All database tables dropped")


async def check_connection() -> bool:
    """Health check — returns True if DB is reachable."""
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("DB health check failed: %s", exc)
        return False
