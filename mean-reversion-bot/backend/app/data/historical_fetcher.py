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
import json
import time

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatusCode
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Candle as DbCandle
from app.database.session import get_session

logger = logging.getLogger(__name__)


PUBLIC_HISTORY_ENDPOINT = "wss://api.derivws.com/trading/v1/options/ws/public"


async def _history_page(symbol, timeframe_seconds, count, end):
    # Public market data needs neither an account token nor trading authentication.
    for attempt in range(3):
        try:
            async with websockets.connect(PUBLIC_HISTORY_ENDPOINT, open_timeout=10,
                                          close_timeout=2, max_size=4 * 1024 * 1024) as ws:
                await ws.send(json.dumps(dict(ticks_history=symbol, style='candles',
                                             granularity=timeframe_seconds, count=count,
                                             end=end, req_id=1)))
                response = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
                if response.get('error'):
                    error = response['error']
                    raise ValueError(f"Deriv history: {error.get('message', error.get('code', 'request rejected'))}")
                candles = response.get('candles')
                if not isinstance(candles, list):
                    raise ValueError('Deriv history returned an invalid candle response')
                return candles
        except (OSError, TimeoutError, ConnectionClosed, InvalidStatusCode) as exc:
            status = getattr(exc, 'status_code', None)
            if status is not None and status != 429 and not 500 <= status <= 599:
                raise ValueError(f'Deriv history connection rejected (HTTP {status}). Use Connected MT5 history or import candles.') from exc
            if attempt == 2:
                detail = f'HTTP {status}' if status else type(exc).__name__
                raise ValueError(f'Deriv history unavailable after 3 attempts ({detail}). Retry later, select Connected MT5 history and its broker pair, or import candles.') from exc
            await asyncio.sleep(2 ** attempt)


async def fetch_public_candles(symbol, timeframe_seconds, count):
    # Exclude the forming candle and page within the provider's 5,000-row limit.
    end = int(time.time() // timeframe_seconds) * timeframe_seconds - 1
    rows = {}
    while len(rows) < count:
        page = await _history_page(symbol, timeframe_seconds, min(5000, count - len(rows)), end)
        if not page:
            break
        previous_count = len(rows)
        for candle in page:
            epoch = int(candle['epoch'])
            if epoch <= end:
                rows[epoch] = candle
        if len(rows) == previous_count:
            raise ValueError('Deriv history pagination made no progress; retry or import candles')
        end = min(rows) - 1
    return [rows[epoch] for epoch in sorted(rows)]


async def fetch_and_cache_symbol(
    db: AsyncSession, symbol: str, timeframe_seconds: int, days: int
) -> int:
    """Pull candles from Deriv for one symbol and upsert into the candles table."""
    count = max(200, (days * 86400) // timeframe_seconds)

    raw = await fetch_public_candles(symbol, timeframe_seconds, count)

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

    for offset in range(0, len(rows), 100):
        stmt = pg_insert(DbCandle).values(rows[offset:offset + 100]).on_conflict_do_nothing(
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