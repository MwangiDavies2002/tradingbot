"""
historical_fetcher.py
────────────────────────────────────────────────────────────────────────────────
Backfills the `candles` table from Deriv so backtests use real historical
data instead of falling back to synthetic candles.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Candle as DbCandle
from app.database.session import get_session
from app.execution.deriv_client import DerivClient, DerivConfig

logger = logging.getLogger(__name__)


async def fetch_and_cache_symbol(
    db: AsyncSession, symbol: str, timeframe_seconds: int, days: int
) -> int:
    """Pull candles from Deriv for one symbol and upsert into the candles table."""
    count = max(200, (days * 86400) // timeframe_seconds)

    client = DerivClient(config=DerivConfig(
        app_id=settings.DERIV_APP_ID,
        api_token=settings.DERIV_API_TOKEN,
    ))
    try:
        await client.connect()
        raw = await client.get_candles(symbol, timeframe_seconds, count=count)
    finally:
        await client.disconnect()

    if not raw:
        logger.warning("Deriv returned no candles for %s %ss", symbol, timeframe_seconds)
        return 0

    rows = [{
        "symbol": symbol,
        "timeframe": timeframe_seconds,
        "ts": datetime.utcfromtimestamp(int(c["epoch"])),
        "open": float(c["open"]), "high": float(c["high"]),
        "low": float(c["low"]), "close": float(c["close"]),
        "volume": float(c.get("volume", 0) or 0),
    } for c in raw]

    stmt = pg_insert(DbCandle).values(rows).on_conflict_do_nothing(
        index_elements=["symbol", "timeframe", "ts"]
    )
    await db.execute(stmt)
    await db.commit()
    logger.info("Cached %d candles for %s %ss from Deriv", len(rows), symbol, timeframe_seconds)
    return len(rows)


async def ensure_candles_cached(
    db: AsyncSession, symbol: str, timeframe_seconds: int, days: int, min_coverage: float = 0.9
) -> None:
    """Only hit Deriv if the DB doesn't already have enough recent candles."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(func.count()).select_from(DbCandle).where(
            DbCandle.symbol == symbol,
            DbCandle.timeframe == timeframe_seconds,
            DbCandle.ts >= cutoff,
        )
    )
    existing = result.scalar_one()
    expected_min = int((days * 86400 / timeframe_seconds) * min_coverage)
    if existing >= expected_min:
        return
    await fetch_and_cache_symbol(db, symbol, timeframe_seconds, days)


async def ensure_candles_for_symbols(symbols: list[str], timeframe_seconds: int, days: int) -> None:
    """
    Backfill multiple symbols concurrently. Each task opens its own DB session —
    AsyncSession isn't safe to share across concurrent coroutines.
    """
    async def _one(symbol: str) -> None:
        async with get_session() as db:
            await ensure_candles_cached(db, symbol, timeframe_seconds, days)

    await asyncio.gather(*[_one(s) for s in symbols])