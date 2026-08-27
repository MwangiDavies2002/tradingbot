"""
bollinger.py
────────────────────────────────────────────────────────────────────────────────
Bollinger Bands Indicator
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Computes Bollinger Bands — a volatility envelope around a rolling mean.
    When price closes OUTSIDE the bands, it signals a statistically unusual
    deviation that is likely to mean-revert.

    Upper Band = MA(n) + k × σ(n)
    Lower Band = MA(n) - k × σ(n)
    %B         = (price - lower) / (upper - lower)  ← 0=at lower, 1=at upper

    %B > 1.0  → price above upper band → SELL signal (overbought)
    %B < 0.0  → price below lower band → BUY signal  (oversold)
    %B ~ 0.5  → price at middle band   → no signal

    Bandwidth  = (upper - lower) / middle  ← measures current volatility
    Low bandwidth = Bollinger Squeeze → breakout/reversal imminent

USAGE:
    from app.core.indicators.bollinger import BollingerBands

    bb = BollingerBands(period=20, std_dev=2.0)
    result = bb.compute(candles)
    print(result.percent_b, result.position, result.is_squeeze)
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
class BollingerResult:
    upper:      float
    middle:     float    # The moving average (basis)
    lower:      float
    percent_b:  float    # (price - lower) / (upper - lower)
    bandwidth:  float    # (upper - lower) / middle
    price:      float
    period:     int
    std_dev:    float

    @property
    def position(self) -> str:
        """Where is price relative to the bands?"""
        if self.percent_b > 1.0:   return "above_upper"
        if self.percent_b < 0.0:   return "below_lower"
        if self.percent_b > 0.8:   return "near_upper"
        if self.percent_b < 0.2:   return "near_lower"
        return "middle"

    @property
    def is_outside_bands(self) -> bool:
        return self.percent_b > 1.0 or self.percent_b < 0.0

    @property
    def is_squeeze(self) -> bool:
        """
        Bollinger Squeeze: bandwidth is unusually low.
        Indicates compressed volatility — explosive move likely soon.
        Threshold: bandwidth < 0.02 (2% of price) is a common squeeze definition.
        """
        return self.bandwidth < 0.02

    @property
    def direction(self) -> Optional[str]:
        if self.percent_b > 1.0:  return "sell"
        if self.percent_b < 0.0:  return "buy"
        return None

    @property
    def confluence_points(self) -> int:
        return 1 if self.is_outside_bands else 0

    def __repr__(self) -> str:
        return (f"Bollinger(%B={self.percent_b:.3f} | pos={self.position} | "
                f"BW={self.bandwidth:.4f} | squeeze={self.is_squeeze})")


class BollingerBands:
    """
    Standard Bollinger Bands with %B and Bandwidth.

    Parameters
    ----------
    period  : int   MA period. Default 20.
    std_dev : float Standard deviation multiplier. Default 2.0.
                    Use 2.5 for stricter signals on volatile instruments (e.g. Vol 75).
    ma_type : str   'sma' (simple) or 'ema' (exponential). Default 'sma'.
    """

    def __init__(
        self,
        period:  int   = 20,
        std_dev: float = 2.0,
        ma_type: str   = "sma",
    ) -> None:
        self.period  = period
        self.std_dev = std_dev
        self.ma_type = ma_type

    def compute(self, candles: list[Candle]) -> Optional[BollingerResult]:
        """Compute Bollinger Bands for the most recent candle."""
        if len(candles) < self.period:
            return None

        closes = [c.close for c in candles]
        window = closes[-self.period:]
        price  = closes[-1]

        middle = self._ma(window)
        std    = float(np.std(window, ddof=1))
        upper  = middle + self.std_dev * std
        lower  = middle - self.std_dev * std

        band_range  = upper - lower
        percent_b   = (price - lower) / band_range if band_range > 0 else 0.5
        bandwidth   = band_range / middle if middle != 0 else 0.0

        return BollingerResult(
            upper=upper, middle=middle, lower=lower,
            percent_b=round(percent_b, 4),
            bandwidth=round(bandwidth, 6),
            price=price, period=self.period, std_dev=self.std_dev,
        )

    def compute_series(self, candles: list[Candle]) -> dict[str, list[float]]:
        """
        Compute full series for backtesting / charting.
        Returns dict with keys: 'upper', 'middle', 'lower', 'percent_b', 'bandwidth'.
        """
        closes = [c.close for c in candles]
        n = len(closes)
        upper_s = [float("nan")] * n
        mid_s   = [float("nan")] * n
        lower_s = [float("nan")] * n
        pb_s    = [float("nan")] * n
        bw_s    = [float("nan")] * n

        for i in range(self.period - 1, n):
            window = closes[i - self.period + 1 : i + 1]
            mid    = self._ma(window)
            std    = max(float(np.std(window, ddof=1)), 1e-10)
            up     = mid + self.std_dev * std
            lo     = mid - self.std_dev * std
            rng    = up - lo
            upper_s[i] = up
            mid_s[i]   = mid
            lower_s[i] = lo
            pb_s[i]    = (closes[i] - lo) / rng if rng > 0 else 0.5
            bw_s[i]    = rng / mid if mid != 0 else 0.0

        return {"upper": upper_s, "middle": mid_s, "lower": lower_s,
                "percent_b": pb_s, "bandwidth": bw_s}

    def _ma(self, window: list[float]) -> float:
        if self.ma_type == "ema":
            arr   = np.array(window, dtype=float)
            alpha = 2.0 / (len(arr) + 1)
            ema   = arr[0]
            for p in arr[1:]:
                ema = alpha * p + (1 - alpha) * ema
            return float(ema)
        return float(np.mean(window))
