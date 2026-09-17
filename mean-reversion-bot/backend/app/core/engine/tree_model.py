"""Deterministic, exportable decision tree used by Tree Mode."""
from typing import Optional

def classify(z: Optional[float], rsi: Optional[float], atr: float,
             close: float, ema50: float, ema200: float) -> tuple[Optional[str], int]:
    if not atr or atr <= 0: return None, 0
    
    # Trend distance filter (suppress in strong trends)
    trend_dist = abs(ema50 - ema200) / atr
    if trend_dist > 3.0: return None, 0

    # Bullish Mean Reversion (Buy)
    # Price is below EMA50, Z-Score is extreme negative, RSI is oversold
    if z is not None and rsi is not None:
        if z <= -2.0 and rsi <= 30 and close < ema50:
            score = 3 if z <= -3.0 else 2
            return "buy", score
            
    # Bearish Mean Reversion (Sell)
    # Price is above EMA50, Z-Score is extreme positive, RSI is overbought
    if z is not None and rsi is not None:
        if z >= 2.0 and rsi >= 70 and close > ema50:
            score = 3 if z >= 3.0 else 2
            return "sell", score

    return None, 0
