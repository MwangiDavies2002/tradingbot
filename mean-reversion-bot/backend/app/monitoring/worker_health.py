"""Container healthcheck: verifies durable worker heartbeat without broker access."""
import asyncio
from datetime import datetime
from app.config import settings
from app.database.session import AsyncSessionLocal
from app.database.models import TradingControl
from app.execution.safety import account_scope


async def check():
    async with AsyncSessionLocal() as db:
        row = await db.get(TradingControl, account_scope(settings))
        return bool(row and row.heartbeat and (datetime.utcnow() - row.heartbeat).total_seconds() < 30)


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(check()) else 1)
