from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.database.models import BacktestResult, Candle
from app.core.engine.signal_engine import SignalEngine, EngineConfig
from app.backtesting.backtest_engine import BacktestEngine, Candle as BTCandle
from app.core.lsl.lsl_detector import Candle as DetectorCandle

logger = logging.getLogger(__name__)

router = APIRouter()

class BacktestRequest(BaseModel):
    symbols: List[str]
    timeframe: str = "M5"
    days: int = 7
    initial_balance: float = 10000.0
    
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

def generate_mock_candles(symbol: str, timeframe: str, days: int) -> List[DetectorCandle]:
    """Fallback generator for backtesting if no data in DB."""
    import random
    import time
    
    candles = []
    now = int(time.time())
    interval = 300 if timeframe == "M5" else 900
    start_ts = now - (days * 24 * 3600)
    
    price = 1000.0 if "100" in symbol else 500.0
    
    for i in range(days * 24 * 12): # M5
        ts = start_ts + (i * interval)
        change = price * random.uniform(-0.015, 0.015)
        open_p = price
        high_p = price + abs(price * random.uniform(0, 0.02))
        low_p = price - abs(price * random.uniform(0, 0.02))
        close_p = price + change
        vol = random.uniform(500, 5000)
        
        candles.append(DetectorCandle(
            timestamp=ts,
            open=open_p,
            high=high_p,
            low=low_p,
            close=close_p,
            volume=vol
        ))
        price = close_p
        
    return candles

@router.post("/run")
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    """
    Run a backtest for the selected symbols and strategy configuration.
    """
    results = []
    
    # In a real app, we'd fetch from DB or Deriv API
    # Here we use mock data to ensure the user can "test" immediately
    
    try:
        for symbol in req.symbols:
            candles = generate_mock_candles(symbol, req.timeframe, req.days)
        
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
                min_confluence=req.min_confluence
            )
        
            signal_engine = SignalEngine(config=config)
            signal_engine.initialise(req.initial_balance)
        
            bt_engine = BacktestEngine(
                signal_engine=signal_engine,
                initial_balance=req.initial_balance
            )
        
            report = bt_engine.run(candles, symbol=symbol, timeframe=req.timeframe)
        
            # Save to DB
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
            trades_json=[{
                "id": t.trade_id,
                "dir": t.direction,
                "entry": t.entry_price,
                "exit": t.exit_price,
                "pnl": t.pnl,
                "reason": t.close_reason
            } for t in report.trades]
            )
            db.add(db_res)
        
            results.append({
            "run_id": run_id,
            "symbol": symbol,
            "total_trades": len(report.trades),
            "win_rate": report.win_rate,
            "profit_factor": report.profit_factor,
            "sharpe_ratio": report.sharpe_ratio,
            "max_drawdown": report.max_drawdown_pct,
            "total_pnl": report.total_pnl,
            "total_pnl_pct": report.total_pnl_pct,
            "equity_curve": report.equity_curve
            })
        
        await db.commit()
        return results
    except Exception as exc:
        await db.rollback()
        logger.exception("Backtest failed | symbols=%s | timeframe=%s", req.symbols, req.timeframe)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}") from exc

@router.get("/results")
async def get_backtest_results(db: AsyncSession = Depends(get_db)):
    """Fetch recent backtest runs."""
    from sqlalchemy import select, desc
    stmt = select(BacktestResult).order_by(desc(BacktestResult.run_at)).limit(10)
    res = await db.execute(stmt)
    items = res.scalars().all()
    return items
