from __future__ import annotations
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_db
from app.database.models import StrategyCombination, BacktestResult
from app.core.engine.signal_engine import EngineConfig
from app.quant.optimization.fingerprint import ConfigurationFingerprinter

logger = logging.getLogger(__name__)
router = APIRouter()

class CombinationRegisterRequest(BaseModel):
    strategy_name: str = "MeanReversion"
    instrument: str = "GER40"
    timeframe: str = "M5"
    config: dict # EngineConfig as dict

class CombinationResponse(BaseModel):
    fingerprint: str
    strategy_name: str
    instrument: str
    timeframe: str
    status: str
    created_at: str

@router.post("/register", response_model=CombinationResponse)
async def register_combination(req: CombinationRegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        # Validate config dict by attempting to create EngineConfig
        config_obj = EngineConfig(**req.config)
        fingerprint = ConfigurationFingerprinter.get_fingerprint(config_obj, req.instrument, req.timeframe)
        
        # Check if exists
        stmt = select(StrategyCombination).where(StrategyCombination.fingerprint == fingerprint)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        
        if existing:
            return {
                "fingerprint": existing.fingerprint,
                "strategy_name": existing.strategy_name,
                "instrument": existing.instrument,
                "timeframe": existing.timeframe,
                "status": existing.status,
                "created_at": existing.created_at.isoformat()
            }
            
        new_comb = StrategyCombination(
            fingerprint=fingerprint,
            strategy_name=req.strategy_name,
            instrument=req.instrument,
            timeframe=req.timeframe,
            parameters_json=req.config,
            status="candidate"
        )
        db.add(new_comb)
        await db.commit()
        
        return {
            "fingerprint": new_comb.fingerprint,
            "strategy_name": new_comb.strategy_name,
            "instrument": new_comb.instrument,
            "timeframe": new_comb.timeframe,
            "status": new_comb.status,
            "created_at": new_comb.created_at.isoformat()
        }
    except Exception as e:
        await db.rollback()
        logger.exception("Failed to register combination")
        raise HTTPException(422, f"Invalid configuration or registration failed: {e}")

@router.get("/list", response_model=List[CombinationResponse])
async def list_combinations(instrument: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(StrategyCombination)
    if instrument:
        stmt = stmt.where(StrategyCombination.instrument == instrument)
    stmt = stmt.order_by(desc(StrategyCombination.created_at))
    
    res = await db.execute(stmt)
    combs = res.scalars().all()
    
    return [
        {
            "fingerprint": c.fingerprint,
            "strategy_name": c.strategy_name,
            "instrument": c.instrument,
            "timeframe": c.timeframe,
            "status": c.status,
            "created_at": c.created_at.isoformat()
        } for c in combs
    ]

from app.quant.optimization.scheduler import DiversityScheduler
from app.quant.optimization.feedback import FeedbackEngine

@router.post("/cluster/{strategy_family}")
async def cluster_combinations(strategy_family: str, db: AsyncSession = Depends(get_db)):
    scheduler = DiversityScheduler(db)
    await scheduler.cluster_combinations(strategy_family)
    return {"message": "Clustering complete"}

@router.get("/next-batch/{strategy_family}")
async def get_next_batch(strategy_family: str, batch_size: int = 5, db: AsyncSession = Depends(get_db)):
    scheduler = DiversityScheduler(db)
    combs = await scheduler.get_next_batch(strategy_family, batch_size)
    return [
        {
            "fingerprint": c.fingerprint,
            "params": c.parameters_json,
            "cluster_id": c.cluster_id
        } for c in combs
    ]

@router.get("/leaderboard")
async def get_leaderboard(db: AsyncSession = Depends(get_db)):
    # Select best results based on expectancy_r_lb
    stmt = select(BacktestResult).where(BacktestResult.total_trades >= 30).order_by(desc(BacktestResult.expectancy_r_lb)).limit(20)
    res = await db.execute(stmt)
    results = res.scalars().all()
    
    return [
        {
            "run_id": r.run_id,
            "symbol": r.symbol,
            "win_rate": r.win_rate,
            "expectancy_r": r.expectancy_r,
            "expectancy_r_lb": r.expectancy_r_lb,
            "profit_factor": r.profit_factor,
            "max_drawdown": r.max_drawdown,
            "feedback": r.feedback_json
        } for r in results
    ]
