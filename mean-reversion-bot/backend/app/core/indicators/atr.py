"""
atr.py
────────────────────────────────────────────────────────────────────────────────
ATR — Average True Range
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Computes ATR — the foundational volatility measure used throughout the
    entire bot. ATR is used for:

    1. Position sizing:  risk_amount / ATR × multiplier = lot size
    2. Stop loss:        entry ± (ATR × sl_multiplier)
    3. Take profit:      entry ± (ATR × tp_multiplier)
    4. LSL detection:    proximity threshold = ATR × 0.5
    5. Zone merging:     merge distance = ATR × 0.3
    6. VWAP deviation:   deviation / ATR = normalised distance
    7. Regime filter:    ATR ratio (short/long) detects volatility spikes

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR        = Wilder smoothed average of True Range over N periods

    ATR Ratio  = ATR(fast) / ATR(slow)
        > 1.5  → market is expanding, volatile  — reduce position size
        < 0.7  → market is calm / consolidating — normal position size
        Boom/Crash spike will show ATR ratio >> 2.0

USAGE:
    from app.core.indicators.atr import ATRIndicator

    atr_ind = ATRIndicator(period=14)
    result  = atr_ind.compute(candles)
    print(result.value, result.ratio, result.regime)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.core.lsl.lsl_detector import Candle

logger = logging.getLogger(__name__)


@dataclass
class ATRResult:
    value:       float    # Current ATR (fast period)
    atr_slow:    float    # Slower ATR for ratio comparison
    ratio:       float    # ATR(fast) / ATR(slow)
    period:      int
    period_slow: int

    @property
    def regime(self) -> str:
        """
        Volatility regime classification based on ATR ratio.
        Used by the signal engine to adjust position sizing and thresholds.
        """
        if self.ratio > 2.0:    return "spike"        # Boom/Crash tick or news
        if self.ratio > 1.5:    return "high"         # Elevated volatility
        if self.ratio > 1.2:    return "above_normal"
        if self.ratio < 0.6:    return "squeeze"      # Bollinger squeeze territory
        if self.ratio < 0.8:    return "low"
        return "normal"

    @property
    def position_size_multiplier(self) -> float:
        """
        Adjust position size based on current volatility regime.
        High volatility → smaller size. Low volatility → normal size.
        """
        regime = self.regime
        if regime == "spike":        return 0.25
        if regime == "high":         return 0.60
        if regime == "above_normal": return 0.80
        if regime == "squeeze":      return 1.00   # Normal — breakout expected soon
        if regime == "low":          return 1.00
        return 1.00   # normal

    @property
    def is_elevated(self) -> bool:
        return self.ratio > 1.5

    @property
    def is_spike(self) -> bool:
        return self.ratio > 2.0

    def sl_distance(self, multiplier: float = 1.5) -> float:
        """Calculate stop loss distance from ATR. Default 1.5× ATR."""
        return self.value * multiplier

    def tp_distance(self, rr: float = 2.0) -> float:
        """Calculate take profit distance for a given risk:reward ratio."""
        return self.sl_distance() * rr

    def __repr__(self) -> str:
        return (f"ATR(val={self.value:.5f} | ratio={self.ratio:.2f} | "
                f"regime={self.regime} | size_mult={self.position_size_multiplier}x)")


class ATRIndicator:
    """
    ATR with Wilder smoothing and volatility regime detection.

    Parameters
    ----------
    period      : int   Fast ATR period. Default 14.
    period_slow : int   Slow ATR period for ratio. Default 50.
    smoothing   : str   'wilder' (standard) or 'sma'. Default 'wilder'.
    """

    def __init__(
        self,
        period:      int = 14,
        period_slow: int = 50,
        smoothing:   str = "wilder",
    ) -> None:
        self.period      = period
        self.period_slow = period_slow
        self.smoothing   = smoothing

    def compute(self, candles: list[Candle]) -> Optional[ATRResult]:
        """Compute ATR and volatility regime. Returns None if insufficient data."""
        min_candles = max(self.period, self.period_slow) + 1
        if len(candles) < min_candles:
            logger.debug("ATR: need %d candles, got %d", min_candles, len(candles))
            return None

        trs = self._true_ranges(candles)

        atr_fast = self._smooth(trs, self.period)
        atr_slow = self._smooth(trs, self.period_slow)
        ratio    = atr_fast / max(atr_slow, 1e-10)

        return ATRResult(
            value       = round(atr_fast, 6),
            atr_slow    = round(atr_slow, 6),
            ratio       = round(ratio, 4),
            period      = self.period,
            period_slow = self.period_slow,
        )

    def compute_series(self, candles: list[Candle]) -> list[float]:
        """Full ATR series for backtesting. NaN before window fills."""
        trs    = self._true_ranges(candles)
        n      = len(candles)
        result = [float("nan")] * n

        if len(trs) < self.period:
            return result

        # Seed
        atr = float(np.mean(trs[:self.period]))
        result[self.period] = atr   # offset by 1 (trs starts at index 1)

        alpha = 1.0 / self.period   # Wilder alpha
        for i in range(self.period, len(trs)):
            if self.smoothing == "wilder":
                atr = (atr * (self.period - 1) + trs[i]) / self.period
            else:
                window = trs[max(0, i - self.period + 1): i + 1]
                atr = float(np.mean(window))
            result[i + 1] = atr

        return result

    def _true_ranges(self, candles: list[Candle]) -> list[float]:
        trs = []
        for i in range(1, len(candles)):
            c  = candles[i]
            pc = candles[i - 1].close
            trs.append(max(c.high - c.low, abs(c.high - pc), abs(c.low - pc)))
        return trs

    def _smooth(self, trs: list[float], period: int) -> float:
        if len(trs) < period:
            return float(np.mean(trs)) if trs else 0.0
        atr = float(np.mean(trs[:period]))
        for tr in trs[period:]:
            if self.smoothing == "wilder":
                atr = (atr * (period - 1) + tr) / period
            else:
                pass   # SMA handled below
        if self.smoothing == "sma":
            return float(np.mean(trs[-period:]))
        return atr
