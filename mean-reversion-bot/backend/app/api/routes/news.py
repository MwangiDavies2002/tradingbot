"""News-event ingestion and deterministic news-volatility signal generation."""
from datetime import datetime, timedelta, timezone
import os, re, hashlib
import httpx
import xml.etree.ElementTree as ET
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import NewsEvent
from app.database.session import get_db

router = APIRouter()
SUPPORTED = {"UK100", "NAS100", "SP500", "GER40", "FRA40", "XAUUSD", "GOLD"}
MAP = {"USD": {"NAS100", "SP500", "XAUUSD", "GOLD"}, "GBP": {"UK100"}, "EUR": {"GER40", "FRA40"}}

class NewsIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    title: str
    currency: Optional[str] = None
    impact: str = "high"
    event_at: datetime
    actual: Optional[float] = None
    forecast: Optional[float] = None
    previous: Optional[float] = None
    source: str = "manual"
    raw_json: Optional[dict[str, Any]] = None

def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value

def _direction(event: NewsEvent) -> Optional[str]:
    if event.actual is None or event.forecast is None or event.actual == event.forecast:
        return None
    return "buy" if event.actual > event.forecast else "sell"

@router.get("/events")
async def events(limit: int = Query(50, ge=1, le=500), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(NewsEvent).order_by(desc(NewsEvent.event_at)).limit(limit))).scalars().all()
    return [{"id": x.id, "event_id": x.event_id, "title": x.title, "currency": x.currency,
             "impact": x.impact, "event_at": x.event_at, "actual": x.actual, "forecast": x.forecast,
             "previous": x.previous, "source": x.source} for x in rows]

@router.post("/events", status_code=201)
async def ingest(payload: NewsIn, db: AsyncSession = Depends(get_db)):
    existing = (await db.execute(select(NewsEvent).where(NewsEvent.event_id == payload.event_id))).scalar_one_or_none()
    if existing:
        for key, value in payload.model_dump().items(): setattr(existing, key, value)
        return {"id": existing.id, "updated": True}
    row = NewsEvent(**payload.model_dump())
    db.add(row); await db.flush()
    return {"id": row.id, "created": True}

@router.post("/sync/forex-factory")
async def sync_forex_factory(db: AsyncSession = Depends(get_db)):
    """Import the public Forex Factory calendar RSS feed.

    This uses the published RSS endpoint, not HTML scraping. Feed availability,
    timestamps and licensing remain subject to Forex Factory's terms.
    """
    url = os.getenv("FOREX_FACTORY_RSS_URL", "https://www.forexfactory.com/calendar/rss")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": "StrategyLab/1.0"}) as client:
            response = await client.get(url); response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:
        raise HTTPException(502, f"Forex Factory feed unavailable: {exc}")
    imported = 0
    for item in root.findall(".//item"):
        text = lambda tag: (item.findtext(tag) or "").strip()
        title, pub = text("title"), text("pubDate")
        if not title or not pub: continue
        try: event_at = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %z").astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError: continue
        description = text("description")
        # Stable identity lets later RSS updates enrich the same stored event.
        blob = f"{title}|{pub}"
        event_id = "ff-" + hashlib.sha256(blob.encode()).hexdigest()[:32]
        currency = next((c for c in ("USD", "GBP", "EUR") if re.search(rf"\b{c}\b", blob, re.I)), None)
        impact = "high" if re.search(r"high impact|red", blob, re.I) else "medium"
        existing = (await db.execute(select(NewsEvent).where(NewsEvent.event_id == event_id))).scalar_one_or_none()
        if existing:
            existing.title, existing.currency, existing.impact = title, currency, impact
            existing.raw_json = {"description": description}
            continue
        db.add(NewsEvent(event_id=event_id, title=title, currency=currency, impact=impact,
                         event_at=event_at, source="forex_factory_rss", raw_json={"description": description}))
        imported += 1
    await db.commit()
    return {"source": "forex_factory_rss", "imported": imported}

@router.get("/signals")
async def news_signals(symbol: str = Query(...), window_minutes: int = Query(30, ge=1, le=240), db: AsyncSession = Depends(get_db)):
    symbol = symbol.upper()
    if symbol not in SUPPORTED: raise HTTPException(400, f"Unsupported news instrument: {symbol}")
    now = datetime.utcnow(); lo = now - timedelta(minutes=window_minutes); hi = now + timedelta(minutes=window_minutes)
    rows = (await db.execute(select(NewsEvent).where(NewsEvent.impact == "high", NewsEvent.event_at >= lo, NewsEvent.event_at <= hi).order_by(desc(NewsEvent.event_at)))).scalars().all()
    matched = [x for x in rows if not x.currency or symbol in MAP.get(x.currency.upper(), set())]
    out = []
    for x in matched:
        direction = _direction(x)
        out.append({"event_id": x.event_id, "symbol": symbol, "title": x.title, "impact": x.impact,
                    "event_at": x.event_at, "direction": direction, "actionable": direction is not None,
                    "reason": "actual_vs_forecast" if direction else "awaiting_actual_or_no_surprise"})
    return {"symbol": symbol, "news_mode": "high_impact_only", "signals": out}
