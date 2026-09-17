"""Shared OHLCV integrity checks for research and live ingestion."""
import math


def validate_candles(candles, interval=None):
    if not candles:
        raise ValueError("No candles supplied")
    gaps = 0
    previous = None
    for c in candles:
        if not all(math.isfinite(v) for v in
                   (c.timestamp, c.open, c.high, c.low, c.close, c.volume)):
            raise ValueError("Non-finite candle value")
        if min(c.open, c.high, c.low, c.close) <= 0 or c.volume < 0:
            raise ValueError("Prices must be positive and volume nonnegative")
        if not c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high:
            raise ValueError("Invalid OHLC range")
        if previous is not None:
            if c.timestamp <= previous:
                raise ValueError("Candle timestamps must be unique and strictly increasing")
            if interval and c.timestamp - previous != interval:
                gaps += 1
        previous = c.timestamp
    return {"candles": len(candles), "gaps": gaps}
