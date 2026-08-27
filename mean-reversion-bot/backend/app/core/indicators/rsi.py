"""
rsi.py
────────────────────────────────────────────────────────────────────────────────
RSI — Relative Strength Index
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Measures the speed and magnitude of recent price changes to identify
    overbought and oversold conditions.

    RSI = 100 - (100 / (1 + RS))
    RS  = avg_gain / avg_loss  over N periods (Wilder smoothing)

    RSI < 25  → oversold  → BUY signal  → +2 confluence points
    RSI > 75  → overbought → SELL signal → +2 confluence points
    RSI = 50  → neutral

    Divergence detection:
        Bullish divergence: price makes lower low, RSI makes higher low → BUY
        Bearish divergence: price makes higher high, RSI makes lower high → SELL
        Divergence adds +1 extra confluence point when detected.

USAGE:
    from app.core.indicators.rsi import RSIIndicator

    rsi = RSIIndicator(period=14)
    result = rsi.compute(candles)
    print(result.value, result.direction, result.divergence)
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
class RSIResult:
    value:       float         # RSI value 0–100
    period:      int
    avg_gain:    float
    avg_loss:    float
    divergence:  Optional[str] = None   # "bullish", "bearish", or None

    @property
    def direction(self) -> Optional[str]:
        """Trade direction implied by RSI level."""
        if self.value < 30:   return "buy"
        if self.value > 70:   return "sell"
        return None

    @property
    def is_oversold(self) -> bool:
        return self.value < 30

    @property
    def is_overbought(self) -> bool:
        return self.value > 70

    @property
    def is_extreme_oversold(self) -> bool:
        return self.value < 25

    @property
    def is_extreme_overbought(self) -> bool:
        return self.value > 75

    @property
    def confluence_points(self) -> int:
        """Points for confluence scorer. Extreme levels earn +2, divergence adds +1."""
        pts = 0
        if self.is_extreme_oversold or self.is_extreme_overbought:
            pts += 2
        elif self.is_oversold or self.is_overbought:
            pts += 1
        if self.divergence:
            pts += 1
        return pts

    @property
    def strength_label(self) -> str:
        v = self.value
        if v < 20 or v > 80:  return "extreme"
        if v < 25 or v > 75:  return "very_strong"
        if v < 30 or v > 70:  return "strong"
        if v < 40 or v > 60:  return "moderate"
        return "neutral"

    def __repr__(self) -> str:
        div = f" | div={self.divergence}" if self.divergence else ""
        return (f"RSI(val={self.value:.2f} | dir={self.direction} | "
                f"{self.strength_label}{div} | pts={self.confluence_points})")


class RSIIndicator:
    """
    RSI with Wilder smoothing and optional divergence detection.

    Parameters
    ----------
    period           : int   RSI lookback period. Default 14.
    oversold         : float RSI below this = oversold. Default 30.
    overbought       : float RSI above this = overbought. Default 70.
    extreme_oversold : float Threshold for extreme oversold (more points). Default 25.
    extreme_overbought: float Threshold for extreme overbought. Default 75.
    divergence_lookback: int Candles back to check for divergence. Default 10.
    detect_divergence: bool  Enable divergence detection. Default True.
    """

    def __init__(
        self,
        period:             int   = 14,
        oversold:           float = 30.0,
        overbought:         float = 70.0,
        extreme_oversold:   float = 25.0,
        extreme_overbought: float = 75.0,
        divergence_lookback: int  = 10,
        detect_divergence:  bool  = True,
    ) -> None:
        self.period              = period
        self.oversold            = oversold
        self.overbought          = overbought
        self.extreme_oversold    = extreme_oversold
        self.extreme_overbought  = extreme_overbought
        self.divergence_lookback = divergence_lookback
        self.detect_divergence   = detect_divergence

    def compute(self, candles: list[Candle]) -> Optional[RSIResult]:
        """Compute RSI for the most recent candle. Returns None if insufficient data."""
        if len(candles) < self.period + 1:
            return None

        closes  = [c.close for c in candles]
        rsi_val, avg_gain, avg_loss = self._calculate_rsi(closes)

        # Divergence detection
        divergence = None
        if self.detect_divergence and len(candles) >= self.period + self.divergence_lookback:
            rsi_series = self.compute_series(candles)
            divergence = self._detect_divergence(closes, rsi_series)

        return RSIResult(
            value=round(rsi_val, 2),
            period=self.period,
            avg_gain=round(avg_gain, 6),
            avg_loss=round(avg_loss, 6),
            divergence=divergence,
        )

    def compute_series(self, candles: list[Candle]) -> list[float]:
        """
        Compute RSI for every candle. NaN before window fills.
        Used for divergence detection and backtesting.
        """
        closes = [c.close for c in candles]
        n      = len(closes)
        result = [float("nan")] * n

        if n < self.period + 1:
            return result

        # Seed with simple averages for first window
        diffs     = [closes[i] - closes[i - 1] for i in range(1, n)]
        gains     = [max(d, 0) for d in diffs]
        losses    = [abs(min(d, 0)) for d in diffs]

        avg_gain  = float(np.mean(gains[:self.period]))
        avg_loss  = float(np.mean(losses[:self.period]))

        def _rsi(ag, al):
            if al == 0:
                return 100.0
            rs = ag / al
            return 100 - (100 / (1 + rs))

        result[self.period] = _rsi(avg_gain, avg_loss)

        # Wilder smoothing for subsequent values
        for i in range(self.period + 1, n):
            idx      = i - 1    # index into diffs/gains/losses
            avg_gain = (avg_gain * (self.period - 1) + gains[idx])  / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[idx]) / self.period
            result[i] = _rsi(avg_gain, avg_loss)

        return result

    def _calculate_rsi(self, closes: list[float]) -> tuple[float, float, float]:
        """Compute final RSI value using Wilder smoothing."""
        diffs  = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [max(d, 0)        for d in diffs]
        losses = [abs(min(d, 0))   for d in diffs]

        # Seed averages with simple mean over first period
        avg_gain = float(np.mean(gains[:self.period]))
        avg_loss = float(np.mean(losses[:self.period]))

        # Apply Wilder smoothing for remaining values
        for i in range(self.period, len(diffs)):
            avg_gain = (avg_gain * (self.period - 1) + gains[i])  / self.period
            avg_loss = (avg_loss * (self.period - 1) + losses[i]) / self.period

        if avg_loss == 0:
            return 100.0, avg_gain, avg_loss
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs)), avg_gain, avg_loss

    def _detect_divergence(
        self, closes: list[float], rsi_series: list[float]
    ) -> Optional[str]:
        """
        Detect classic RSI divergence in the recent lookback window.

        BULLISH divergence: price lower low + RSI higher low → BUY
        BEARISH divergence: price higher high + RSI lower high → SELL
        """
        lb   = self.divergence_lookback
        p    = closes[-lb:]
        r    = rsi_series[-lb:]

        # Filter out NaN in RSI series
        valid = [(pr, rs) for pr, rs in zip(p, r) if not np.isnan(rs)]
        if len(valid) < 4:
            return None

        prices_v = [v[0] for v in valid]
        rsi_v    = [v[1] for v in valid]

        price_low_now   = prices_v[-1] < min(prices_v[:-1])
        rsi_low_higher  = rsi_v[-1]    > min(rsi_v[:-1])
        if price_low_now and rsi_low_higher:
            logger.debug("Bullish RSI divergence detected")
            return "bullish"

        price_high_now  = prices_v[-1] > max(prices_v[:-1])
        rsi_high_lower  = rsi_v[-1]    < max(rsi_v[:-1])
        if price_high_now and rsi_high_lower:
            logger.debug("Bearish RSI divergence detected")
            return "bearish"

        return None
