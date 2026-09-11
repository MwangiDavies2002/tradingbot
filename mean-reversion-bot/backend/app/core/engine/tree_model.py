"""Deterministic, exportable decision tree used by Tree Mode."""
from typing import Optional

def classify(z: Optional[float], rsi: Optional[float], atr: float,
             close: float, ema50: float, ema200: float) -> tuple[Optional[str], int]:
    if not atr or atr <= 0: return None, 0
    if abs(ema50 - ema200) / atr > 3.0: return None, 0
    if z is not None and rsi is not None and z <= -1.5 and rsi <= 35 and close < ema50:
        return "buy", 3
    if z is not None and rsi is not None and z >= 1.5 and rsi >= 65 and close > ema50:
        return "sell", 3
    return None, 0
