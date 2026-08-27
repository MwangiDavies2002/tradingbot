"""
hurst.py
────────────────────────────────────────────────────────────────────────────────
Hurst Exponent — Mean-Reverting Regime Detector
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    The Hurst exponent (H) measures whether a time series is trending,
    random, or mean-reverting. It is the only indicator that tells you
    WHETHER mean reversion trading is appropriate right now.

    H < 0.5  → mean-reverting  (anti-persistent) → trade mean reversion ✅
    H = 0.5  → random walk     (no edge)          → stay flat
    H > 0.5  → trending        (persistent)       → do NOT mean-revert ❌

    Trading rule:
        H < 0.45  → confirmed mean-reverting regime → +1 confluence point
        H > 0.55  → trending regime → SUPPRESS mean-reversion signals entirely

    HOW IT'S COMPUTED (Rescaled Range / R/S method):
        For each sub-period of length n in the series:
            1. Compute cumulative deviations from mean
            2. R = max(cumdev) - min(cumdev)   [range]
            3. S = std(series)                  [scale]
            4. R/S ratio for this sub-period
        Regress log(R/S) vs log(n) → slope = H

    PRACTICAL NOTES:
        - Requires at least 50–100 candles for a reliable estimate
        - Recompute every 20–50 candles (changes slowly)
        - Synthetic indices (Vol 75) typically have H closer to 0.5
        - Boom/Crash behave differently — spike candles distort H
        - Forex majors often show H < 0.5 during ranging sessions

USAGE:
    from app.core.indicators.hurst import HurstIndicator

    hurst = HurstIndicator(min_period=8, max_period=100)
    result = hurst.compute(candles)
    print(result.value, result.regime, result.should_trade_mr)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.core.lsl.lsl_detector import Candle

logger = logging.getLogger(__name__)


@dataclass
class HurstResult:
    value:       float         # Hurst exponent estimate (0.0 – 1.0)
    candles_used: int
    method:      str           # "rs" (Rescaled Range) or "variance" (fallback)

    @property
    def regime(self) -> str:
        """Trading regime classification."""
        if self.value < 0.40:   return "strongly_mean_reverting"
        if self.value < 0.45:   return "mean_reverting"
        if self.value < 0.55:   return "random_walk"
        if self.value < 0.65:   return "trending"
        return "strongly_trending"

    @property
    def should_trade_mr(self) -> bool:
        """True if the regime supports mean-reversion trading."""
        return self.value < 0.50

    @property
    def should_suppress_mr(self) -> bool:
        """True if the regime is strongly trending — suppress MR signals."""
        return self.value > 0.55

    @property
    def confidence(self) -> str:
        """Confidence in the H estimate based on candles used."""
        n = self.candles_used
        if n >= 200:  return "high"
        if n >= 100:  return "medium"
        if n >= 50:   return "low"
        return "very_low"

    @property
    def confluence_points(self) -> int:
        """
        +1 if confirmed mean-reverting regime.
        0  if random walk.
        -99 as sentinel if trending (caller should suppress trade).
        """
        if self.value < 0.45:   return 1
        if self.value > 0.55:   return -99   # Suppress signal upstream
        return 0

    def __repr__(self) -> str:
        return (f"Hurst(H={self.value:.4f} | regime={self.regime} | "
                f"mr={self.should_trade_mr} | conf={self.confidence})")


class HurstIndicator:
    """
    Hurst Exponent calculator using the Rescaled Range (R/S) method
    with a variance method fallback for short series.

    Parameters
    ----------
    min_period   : int   Smallest sub-period for R/S calculation. Default 8.
    max_period   : int   Largest sub-period. Uses min(this, len(candles)//2). Default 100.
    price_src    : str   'close', 'returns', or 'log_returns'. Default 'log_returns'.
                         log_returns is most statistically appropriate.
    use_variance : bool  Fall back to variance method if series too short. Default True.
    """

    def __init__(
        self,
        min_period:   int  = 8,
        max_period:   int  = 100,
        price_src:    str  = "log_returns",
        use_variance: bool = True,
    ) -> None:
        self.min_period   = min_period
        self.max_period   = max_period
        self.price_src    = price_src
        self.use_variance = use_variance

    def compute(self, candles: list[Candle]) -> Optional[HurstResult]:
        """
        Compute Hurst exponent from candle data.
        Returns None if fewer than 50 candles provided (estimate unreliable).
        """
        if len(candles) < 50:
            logger.debug("Hurst: need ≥50 candles, got %d", len(candles))
            return None

        series = self._extract_series(candles)

        # Try R/S method first
        h, method = self._rs_hurst(series)

        if h is None and self.use_variance:
            h, method = self._variance_hurst(series)

        if h is None:
            logger.warning("Hurst: could not compute estimate")
            return None

        # Clamp to valid range (numerical issues can push outside 0–1)
        h = max(0.01, min(h, 0.99))

        return HurstResult(value=round(h, 4), candles_used=len(candles), method=method)

    def _rs_hurst(self, series: list[float]) -> tuple[Optional[float], str]:
        """
        Rescaled Range (R/S) analysis.
        Computes log(R/S) vs log(n) across multiple sub-period lengths,
        then fits a regression line. Slope = Hurst exponent.
        """
        n         = len(series)
        max_n     = min(self.max_period, n // 2)
        if max_n < self.min_period:
            return None, "rs"

        # Build sub-period lengths as powers of 2 between min and max
        periods = []
        p = self.min_period
        while p <= max_n:
            periods.append(p)
            p = int(p * 1.5)
        if not periods:
            return None, "rs"

        log_n    = []
        log_rs   = []
        arr      = np.array(series, dtype=float)

        for period in periods:
            rs_vals = []
            # Divide series into non-overlapping chunks of `period` length
            n_chunks = n // period
            if n_chunks < 1:
                continue
            for i in range(n_chunks):
                chunk = arr[i * period : (i + 1) * period]
                if len(chunk) < 2:
                    continue
                mean_c = np.mean(chunk)
                deviations = np.cumsum(chunk - mean_c)
                R = np.max(deviations) - np.min(deviations)
                S = np.std(chunk, ddof=1)
                if S > 0 and R > 0:
                    rs_vals.append(R / S)

            if rs_vals:
                avg_rs = float(np.mean(rs_vals))
                if avg_rs > 0:
                    log_n.append(math.log(period))
                    log_rs.append(math.log(avg_rs))

        if len(log_n) < 3:
            return None, "rs"

        # Linear regression: slope = H
        x = np.array(log_n)
        y = np.array(log_rs)
        slope = float(np.polyfit(x, y, 1)[0])
        return slope, "rs"

    def _variance_hurst(self, series: list[float]) -> tuple[Optional[float], str]:
        """
        Variance method (simpler, less accurate but works on shorter series).
        Variance of sub-series scales as n^(2H).
        """
        arr = np.array(series, dtype=float)
        n   = len(arr)
        if n < 20:
            return None, "variance"

        max_lag  = min(n // 4, 50)
        lags     = range(2, max_lag)
        log_lags = []
        log_vars = []

        for lag in lags:
            # Sub-series of length lag
            sub_vars = []
            for start in range(0, n - lag, lag):
                chunk = arr[start : start + lag]
                sub_vars.append(float(np.var(chunk, ddof=1)))
            if sub_vars:
                avg_var = float(np.mean(sub_vars))
                if avg_var > 0:
                    log_lags.append(math.log(lag))
                    log_vars.append(math.log(avg_var))

        if len(log_lags) < 3:
            return None, "variance"

        slope = float(np.polyfit(log_lags, log_vars, 1)[0])
        h     = slope / 2.0   # variance scales as n^(2H)
        return h, "variance"

    def _extract_series(self, candles: list[Candle]) -> list[float]:
        """Extract the time series used for H computation."""
        closes = [c.close for c in candles]
        if self.price_src == "close":
            return closes
        if self.price_src == "returns":
            return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        # log_returns (default — most statistically sound)
        return [math.log(closes[i] / closes[i - 1])
                for i in range(1, len(closes))
                if closes[i - 1] > 0 and closes[i] > 0]
