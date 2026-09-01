from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.database.models import BacktestResult, Candle as DbCandle
from app.core.engine.signal_engine import SignalEngine, EngineConfig
from app.backtesting.backtest_engine import BacktestEngine
from app.core.lsl.lsl_detector import Candle as DetectorCandle
from app.data.historical_fetcher import ensure_candles_for_symbols

logger = logging.getLogger(__name__)

router = APIRouter()

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H2": 7200,
    "H4": 14400,
    "H6": 21600,
    "D1": 86400,
}


def timeframe_to_seconds(timeframe: str) -> int:
    value = str(timeframe or "").strip().upper().replace(" ", "")
    if value in TIMEFRAME_SECONDS:
        return TIMEFRAME_SECONDS[value]
    if value.endswith("M") and value[:-1].isdigit():
        return int(value[:-1]) * 60
    if value.endswith("H") and value[:-1].isdigit():
        return int(value[:-1]) * 3600
    raise ValueError(f"Unsupported timeframe: {timeframe}")


def _parse_epoch_timestamp(value: Any) -> int:
    if value is None:
        raise ValueError("Missing timestamp value")
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except Exception:
        try:
            return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").timestamp())
        except Exception as exc:
            raise ValueError(f"Unsupported timestamp format: {value}") from exc


def _safe_float(value: Any) -> float:
    if value in (None, ""):
        raise ValueError("Missing numeric value")
    return float(value)


def parse_csv_rows(csv_text: str) -> list[dict[str, Any]]:
    """Parse historical OHLCV CSV into row dictionaries."""
    text = (csv_text or "").strip()
    if not text:
        raise ValueError("CSV data is empty")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV header is missing")

    normalized = {str(name).strip().lower(): name for name in reader.fieldnames}
    aliases = {
        "timestamp": ["timestamp", "time", "date", "datetime", "ts"],
        "open": ["open", "o"],
        "high": ["high", "h"],
        "low": ["low", "l"],
        "close": ["close", "c"],
        "volume": ["volume", "vol", "v"],
    }
    mapping = {}
    for target, candidates in aliases.items():
        for candidate in candidates:
            if candidate in normalized:
                mapping[target] = normalized[candidate]
                break
    missing = [name for name in ["timestamp", "open", "high", "low", "close"] if name not in mapping]
    if missing:
        raise ValueError(f"CSV is missing required OHLC columns: {', '.join(missing)}")

    rows: list[dict[str, Any]] = []
    for row in reader:
        if row is None:
            continue
        parsed = {
            "timestamp": _parse_epoch_timestamp(row.get(mapping["timestamp"])),
            "open": _safe_float(row.get(mapping["open"])),
            "high": _safe_float(row.get(mapping["high"])),
            "low": _safe_float(row.get(mapping["low"])),
            "close": _safe_float(row.get(mapping["close"])),
            "volume": _safe_float(row.get(mapping.get("volume"), 0) or 0),
        }
        rows.append(parsed)
    if not rows:
        raise ValueError("CSV did not contain any candle rows")
    rows.sort(key=lambda r: r["timestamp"])
    return rows


def rows_to_candles(rows: list[dict[str, Any]]) -> List[DetectorCandle]:
    candles: List[DetectorCandle] = []
    for row in rows:
        candles.append(
            DetectorCandle(
                timestamp=int(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )
    if len(candles) < 20:
        raise ValueError("At least 20 candles are required for a valid backtest")
    return candles


def generate_mock_candles(symbol: str, timeframe: str, days: int) -> List[DetectorCandle]:
    """Fallback generator for backtesting if no real data is available."""
    import random
    import time

    candles = []
    now = int(time.time())
    interval = timeframe_to_seconds(timeframe)
    start_ts = now - (days * 24 * 3600)
    price = 1000.0 if "100" in symbol else 500.0

    for i in range(max(60, days * 24 * 60 // int(interval / 60))):
        ts = start_ts + (i * interval)
        change = price * random.uniform(-0.015, 0.015)
        open_p = price
        high_p = price + abs(price * random.uniform(0, 0.02))
        low_p = price - abs(price * random.uniform(0, 0.02))
        close_p = price + change
        vol = random.uniform(500, 5000)
        candles.append(
            DetectorCandle(
                timestamp=ts,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=vol,
            )
        )
        price = close_p
    return candles


async def load_candles_for_symbol(
    db: AsyncSession,
    symbol: str,
    timeframe: str,
    days: int,
    csv_payload: Optional[str] = None,
) -> List[DetectorCandle]:
    if csv_payload:
        rows = parse_csv_rows(csv_payload)
        return rows_to_candles(rows)

    tf_seconds = timeframe_to_seconds(timeframe)
    cutoff = datetime.utcnow() - timedelta(days=days)
    stmt = (
        select(DbCandle)
        .where(DbCandle.symbol == symbol, DbCandle.timeframe == tf_seconds, DbCandle.ts >= cutoff)
        .order_by(DbCandle.ts.asc())
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()

    if not rows:
        logger.warning("No historical candles found in DB for %s %s. Falling back to synthetic data.", symbol, timeframe)
        return generate_mock_candles(symbol, timeframe, days)

    return [
        DetectorCandle(
            timestamp=int(row.ts.timestamp()),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in rows
    ]


class BacktestRequest(BaseModel):
    symbols: List[str]
    timeframe: str = "M5"
    days: int = 7
    initial_balance: float = 10000.0
    csv_data: Optional[str] = None

    # Strategy selection
    use_zscore: bool = True
    use_bb: bool = True
    use_rsi: bool = True
    use_vwap: bool = True
    use_stoch: bool = True
    use_lsl: bool = True
    use_smc: bool = True
    use_volume: bool = True
    use_hurst: bool = True

    min_confluence: int = 6


class BacktestReportResponse(BaseModel):
    run_id: str
    symbol: str
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    total_pnl: float
    total_pnl_pct: float
    equity_curve: List[dict]


@router.post("/run")
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    """Run a backtest for the selected symbols and strategy configuration."""
    results = []

    try:
        # Fetch real historical data from Deriv and cache it, unless CSV was provided
        if not req.csv_data:
            tf_seconds = timeframe_to_seconds(req.timeframe)
            await ensure_candles_for_symbols(req.symbols, tf_seconds, req.days)

        for symbol in req.symbols:
            candles = await load_candles_for_symbol(db, symbol, req.timeframe, req.days, req.csv_data)
            config = EngineConfig(
                use_zscore=req.use_zscore,
                use_bb=req.use_bb,
                use_rsi=req.use_rsi,
                use_vwap=req.use_vwap,
                use_stoch=req.use_stoch,
                use_lsl=req.use_lsl,
                use_smc=req.use_smc,
                use_volume=req.use_volume,
                use_hurst=req.use_hurst,
                min_confluence=req.min_confluence,
            )

            signal_engine = SignalEngine(config=config)
            signal_engine.initialise(req.initial_balance)

            bt_engine = BacktestEngine(
                signal_engine=signal_engine,
                initial_balance=req.initial_balance,
            )

            report = bt_engine.run(candles, symbol=symbol, timeframe=req.timeframe)

            run_id = str(uuid.uuid4())[:8]
            db_res = BacktestResult(
                run_id=run_id,
                symbol=symbol,
                timeframe=req.timeframe,
                date_from=datetime.fromtimestamp(candles[0].timestamp),
                date_to=datetime.fromtimestamp(candles[-1].timestamp),
                total_trades=len(report.trades),
                winning_trades=len([t for t in report.trades if t.won]),
                losing_trades=len([t for t in report.trades if not t.won]),
                win_rate=report.win_rate,
                profit_factor=report.profit_factor,
                sharpe_ratio=report.sharpe_ratio,
                max_drawdown=report.max_drawdown_pct,
                total_pnl=report.total_pnl,
                total_pnl_pct=report.total_pnl_pct,
                params_json=req.dict(),
                equity_curve_json=report.equity_curve,
                trades_json=[
                    {
                        "id": t.trade_id,
                        "dir": t.direction,
                        "entry": t.entry_price,
                        "exit": t.exit_price,
                        "pnl": t.pnl,
                        "reason": t.close_reason,
                    }
                    for t in report.trades
                ],
            )
            db.add(db_res)

            candle_data = [{"ts": c.timestamp, "open": c.open, "high": c.high, "low": c.low, "close": c.close, "volume": c.volume} for c in candles]
            results.append(
                {
                    "run_id": run_id,
                    "symbol": symbol,
                    "total_trades": len(report.trades),
                    "win_rate": report.win_rate,
                    "profit_factor": report.profit_factor,
                    "sharpe_ratio": report.sharpe_ratio,
                    "max_drawdown": report.max_drawdown_pct,
                    "total_pnl": report.total_pnl,
                    "total_pnl_pct": report.total_pnl_pct,
                    "equity_curve": report.equity_curve,
                    "candles": candle_data[-200:],
                    "trades": [{"id": t.trade_id, "direction": t.direction, "entry": t.entry_price, "exit": t.exit_price, "pnl": t.pnl, "reason": t.close_reason} for t in report.trades],
                }
            )

        await db.commit()
        return results
    except Exception as exc:
        await db.rollback()
        logger.exception("Backtest failed | symbols=%s | timeframe=%s", req.symbols, req.timeframe)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}") from exc


@router.post("/import")
async def import_backtest_csv(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    """Accept raw CSV import data and run a backtest using it."""
    if not req.csv_data:
        raise HTTPException(status_code=400, detail="CSV data is required for import mode")
    return await run_backtest(req, db)


@router.get("/results")
async def get_backtest_results(db: AsyncSession = Depends(get_db)):
    """Fetch recent backtest runs."""
    stmt = select(BacktestResult).order_by(desc(BacktestResult.run_at)).limit(10)
    res = await db.execute(stmt)
    items = res.scalars().all()
    return [
        {
            "run_id": item.run_id,
            "symbol": item.symbol,
            "timeframe": item.timeframe,
            "run_at": item.run_at.isoformat() if item.run_at else None,
            "total_pnl": item.total_pnl,
            "total_pnl_pct": item.total_pnl_pct,
            "win_rate": item.win_rate,
            "sharpe_ratio": item.sharpe_ratio,
            "max_drawdown": item.max_drawdown,
            "total_trades": item.total_trades,
            "equity_curve": item.equity_curve_json or [],
        }
        for item in items
    ]