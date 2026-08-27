"""
zscore.py
────────────────────────────────────────────────────────────────────────────────
Z-Score Indicator — Primary Mean Reversion Deviation Measure
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Measures how many standard deviations the current price is from its
    rolling mean. It is the single most important signal for mean reversion.

    z = (price - mean(n)) / std(n)

    |z| > 2.0 → price is statistically extreme  → +2 confluence points
    |z| > 2.5 → very extreme                    → +3 confluence points (bonus)
    |z| < 1.0 → price is near mean              → no signal

    Sign of z tells direction:
        z < 0 → price is BELOW mean → BUY signal
        z > 0 → price is ABOVE mean → SELL signal

USAGE:
    from app.core.indicators.zscore import ZScoreIndicator

    zs = ZScoreIndicator(period=20)
    result = zs.compute(candles)
    print(result.value, result.direction, result.bb_position)
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
class ZScoreResult:
    value:        float          # The raw Z-score
    mean:         float          # Rolling mean used
    std:          float          # Rolling std used
    price:        float          # Price that was scored
    period:       int

    @property
    def direction(self) -> Optional[str]:
        """'buy' if below mean, 'sell' if above mean, None if near mean."""
        if self.value < -1.0:
            return "buy"
        if self.value > 1.0:
            return "sell"
        return None

    @property
    def is_extreme(self) -> bool:
        return abs(self.value) >= 2.0

    @property
    def is_very_extreme(self) -> bool:
        return abs(self.value) >= 2.5

    @property
    def confluence_points(self) -> int:
        if self.is_very_extreme:
            return 3
        if self.is_extreme:
            return 2
        return 0

    @property
    def strength_label(self) -> str:
        z = abs(self.value)
        if z >= 3.0:  return "extreme"
        if z >= 2.5:  return "very_strong"
        if z >= 2.0:  return "strong"
        if z >= 1.5:  return "moderate"
        return "weak"

    def __repr__(self) -> str:
        return (f"ZScore(z={self.value:.3f} | dir={self.direction} | "
                f"strength={self.strength_label} | pts={self.confluence_points})")


class ZScoreIndicator:
    """
    Rolling Z-Score calculator.

    Parameters
    ----------
    period    : int   Rolling window for mean and std. Default 20.
    price_src : str   Price source: 'close', 'hl2' (mid), 'hlc3' (typical). Default 'close'.
    min_std   : float Minimum std to prevent division by zero in flat markets. Default 1e-8.
    """

    def __init__(
        self,
        period:    int   = 20,
        price_src: str   = "close",
        min_std:   float = 1e-8,
    ) -> None:
        self.period    = period
        self.price_src = price_src
        self.min_std   = min_std

    def compute(self, candles: list[Candle]) -> Optional[ZScoreResult]:
        """
        Compute Z-score using the most recent `period` candles.
        Returns None if insufficient data.
        """
        if len(candles) < self.period:
            logger.debug("ZScore: need %d candles, got %d", self.period, len(candles))
            return None

        prices = self._extract_prices(candles)
        window = prices[-self.period:]

        mean  = float(np.mean(window))
        std   = float(np.std(window, ddof=1))
        std   = max(std, self.min_std)
        price = prices[-1]
        z     = (price - mean) / std

        return ZScoreResult(value=round(z, 4), mean=mean, std=std,
                            price=price, period=self.period)

    def compute_series(self, candles: list[Candle]) -> list[float]:
        """
        Compute Z-score for every candle in the series (rolling window).
        Returns list of z-values, NaN for candles before window fills.
        Useful for backtesting and charting.
        """
        prices = self._extract_prices(candles)
        result = [float("nan")] * len(prices)

        for i in range(self.period - 1, len(prices)):
            window = prices[i - self.period + 1 : i + 1]
            mean   = float(np.mean(window))
            std    = max(float(np.std(window, ddof=1)), self.min_std)
            result[i] = (prices[i] - mean) / std

        return result

    def _extract_prices(self, candles: list[Candle]) -> list[float]:
        if self.price_src == "close":
            return [c.close for c in candles]
        if self.price_src == "hl2":
            return [(c.high + c.low) / 2 for c in candles]
        if self.price_src == "hlc3":
            return [(c.high + c.low + c.close) / 3 for c in candles]
        raise ValueError(f"Unknown price_src: {self.price_src!r}")
