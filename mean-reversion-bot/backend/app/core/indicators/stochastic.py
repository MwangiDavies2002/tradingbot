"""
stochastic.py
────────────────────────────────────────────────────────────────────────────────
Stochastic Oscillator — Secondary Momentum Exhaustion Detector
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Measures where the current close sits within the recent high-low range,
    normalised to 0–100. Extreme readings signal momentum exhaustion and
    probable mean reversion.

    %K = (close - lowest_low(n)) / (highest_high(n) - lowest_low(n)) × 100
    %D = SMA(%K, smooth_k)   ← signal line

    %K < 15  → oversold  → BUY signal  → +1 confluence point
    %K > 85  → overbought → SELL signal → +1 confluence point

    %K/%D Crossover in extreme zone:
        %K crosses above %D while both < 20 → bullish crossover → +1 extra pt
        %K crosses below %D while both > 80 → bearish crossover → +1 extra pt

    Works best COMBINED with Z-Score and RSI to confirm momentum exhaustion
    before the mean reversion move begins.

USAGE:
    from app.core.indicators.stochastic import StochasticIndicator

    stoch = StochasticIndicator(k_period=14, d_period=3, smooth_k=3)
    result = stoch.compute(candles)
    print(result.k, result.d, result.direction, result.crossover)
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
class StochasticResult:
    k:           float    # Raw (smoothed) %K value  0–100
    d:           float    # Signal line %D  0–100
    k_period:    int
    d_period:    int
    crossover:   Optional[str] = None   # "bullish", "bearish", or None

    @property
    def direction(self) -> Optional[str]:
        if self.k < 20:   return "buy"
        if self.k > 80:   return "sell"
        return None

    @property
    def is_oversold(self) -> bool:
        return self.k < 20

    @property
    def is_overbought(self) -> bool:
        return self.k > 80

    @property
    def is_extreme_oversold(self) -> bool:
        return self.k < 15

    @property
    def is_extreme_overbought(self) -> bool:
        return self.k > 85

    @property
    def confluence_points(self) -> int:
        pts = 0
        if self.is_extreme_oversold or self.is_extreme_overbought:
            pts += 1
        if self.crossover:
            pts += 1
        return pts

    @property
    def strength_label(self) -> str:
        k = self.k
        if k < 10 or k > 90:  return "extreme"
        if k < 15 or k > 85:  return "very_strong"
        if k < 20 or k > 80:  return "strong"
        if k < 30 or k > 70:  return "moderate"
        return "neutral"

    def __repr__(self) -> str:
        cross = f" | cross={self.crossover}" if self.crossover else ""
        return (f"Stochastic(%K={self.k:.2f} | %D={self.d:.2f} | "
                f"dir={self.direction} | {self.strength_label}{cross} | "
                f"pts={self.confluence_points})")


class StochasticIndicator:
    """
    Full Stochastic Oscillator (%K, %D) with crossover detection.

    Parameters
    ----------
    k_period  : int   Lookback for highest high / lowest low. Default 14.
    smooth_k  : int   Smoothing for raw %K (1 = no smoothing = Fast Stoch). Default 3.
    d_period  : int   SMA period for %D signal line. Default 3.
    oversold  : float %K below this = oversold. Default 20.
    overbought: float %K above this = overbought. Default 80.
    """

    def __init__(
        self,
        k_period:   int   = 14,
        smooth_k:   int   = 3,
        d_period:   int   = 3,
        oversold:   float = 20.0,
        overbought: float = 80.0,
    ) -> None:
        self.k_period   = k_period
        self.smooth_k   = smooth_k
        self.d_period   = d_period
        self.oversold   = oversold
        self.overbought = overbought

    def compute(self, candles: list[Candle]) -> Optional[StochasticResult]:
        """Compute %K and %D for the most recent candle."""
        min_len = self.k_period + self.smooth_k + self.d_period
        if len(candles) < min_len:
            logger.debug("Stochastic: need %d candles, got %d", min_len, len(candles))
            return None

        k_series = self._raw_k_series(candles)
        if len(k_series) < self.smooth_k + self.d_period:
            return None

        # Smooth %K
        smoothed_k = self._sma(k_series, self.smooth_k)
        if len(smoothed_k) < self.d_period:
            return None

        # %D = SMA of smoothed %K
        d_series = self._sma(smoothed_k, self.d_period)
        if not d_series:
            return None

        k_val = smoothed_k[-1]
        d_val = d_series[-1]

        # Crossover detection (compare last two %K and %D values)
        crossover = None
        if len(smoothed_k) >= 2 and len(d_series) >= 2:
            crossover = self._detect_crossover(
                smoothed_k[-2], smoothed_k[-1],
                d_series[-2],   d_series[-1],
            )

        return StochasticResult(
            k=round(k_val, 2),
            d=round(d_val, 2),
            k_period=self.k_period,
            d_period=self.d_period,
            crossover=crossover,
        )

    def compute_series(self, candles: list[Candle]) -> dict[str, list[float]]:
        """Full %K and %D series for backtesting / charting."""
        k_series   = self._raw_k_series(candles)
        smoothed_k = self._sma(k_series, self.smooth_k)
        d_series   = self._sma(smoothed_k, self.d_period)

        # Pad with NaN to match original candle length
        pad_k = self.k_period - 1 + self.smooth_k - 1
        pad_d = pad_k + self.d_period - 1

        k_out = [float("nan")] * pad_k + smoothed_k
        d_out = [float("nan")] * pad_d + d_series

        # Trim or pad to match candle length
        n = len(candles)
        k_out = (k_out + [float("nan")] * n)[:n]
        d_out = (d_out + [float("nan")] * n)[:n]

        return {"k": k_out, "d": d_out}

    def _raw_k_series(self, candles: list[Candle]) -> list[float]:
        """Compute raw Fast %K for each candle from k_period onwards."""
        result = []
        for i in range(self.k_period - 1, len(candles)):
            window       = candles[i - self.k_period + 1 : i + 1]
            highest_high = max(c.high for c in window)
            lowest_low   = min(c.low  for c in window)
            price_range  = highest_high - lowest_low
            close        = candles[i].close
            if price_range == 0:
                result.append(50.0)   # Flat market: put in middle
            else:
                result.append((close - lowest_low) / price_range * 100)
        return result

    def _sma(self, series: list[float], period: int) -> list[float]:
        """Simple moving average of a series."""
        if len(series) < period:
            return []
        result = []
        for i in range(period - 1, len(series)):
            result.append(float(np.mean(series[i - period + 1: i + 1])))
        return result

    def _detect_crossover(
        self,
        k_prev: float, k_curr: float,
        d_prev: float, d_curr: float,
    ) -> Optional[str]:
        """
        Detect %K/%D crossover in oversold/overbought zones.
        Only meaningful when both lines are in extreme territory.
        """
        k_crossed_above = k_prev < d_prev and k_curr > d_curr
        k_crossed_below = k_prev > d_prev and k_curr < d_curr

        in_oversold    = k_curr < self.oversold  and d_curr < self.oversold
        in_overbought  = k_curr > self.overbought and d_curr > self.overbought

        if k_crossed_above and in_oversold:
            logger.debug("Stochastic bullish crossover in oversold zone")
            return "bullish"
        if k_crossed_below and in_overbought:
            logger.debug("Stochastic bearish crossover in overbought zone")
            return "bearish"
        return None
