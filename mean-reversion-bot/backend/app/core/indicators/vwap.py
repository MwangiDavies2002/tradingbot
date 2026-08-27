"""
vwap.py
────────────────────────────────────────────────────────────────────────────────
VWAP — Volume Weighted Average Price
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Computes VWAP — the average price weighted by volume. It is the single
    most important intraday reference level used by institutional traders.

    VWAP = Σ(typical_price × volume) / Σ(volume)
    Typical price = (high + low + close) / 3

    Deviation = (price - VWAP) / ATR

    |deviation| > 1.5 ATR → statistically far from institutional average
        deviation < -1.5  → price far BELOW VWAP → BUY signal → +1 confluence pt
        deviation > +1.5  → price far ABOVE VWAP → SELL signal → +1 confluence pt

    VWAP Standard Deviation Bands:
        VWAP ± 1σ  → 68% of volume traded in this range
        VWAP ± 2σ  → 95% of volume traded in this range
        Price outside ±2σ band → strong mean reversion signal

    SESSION RESET:
        VWAP resets at the start of each trading session (midnight UTC by default).
        For synthetic indices (24/7), use rolling_period instead of session reset.

USAGE:
    from app.core.indicators.vwap import VWAPIndicator

    vwap = VWAPIndicator(use_session_reset=True)
    result = vwap.compute(candles, atr=1.5)
    print(result.value, result.deviation_atr, result.band_position)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.core.lsl.lsl_detector import Candle

logger = logging.getLogger(__name__)


@dataclass
class VWAPResult:
    value:           float          # VWAP price
    deviation:       float          # price - VWAP (raw)
    deviation_atr:   float          # deviation / ATR (normalised)
    upper_1:         float          # VWAP + 1σ
    lower_1:         float          # VWAP - 1σ
    upper_2:         float          # VWAP + 2σ
    lower_2:         float          # VWAP - 2σ
    price:           float
    candles_used:    int

    @property
    def direction(self) -> Optional[str]:
        if self.deviation < 0:  return "buy"
        if self.deviation > 0:  return "sell"
        return None

    @property
    def band_position(self) -> str:
        """Where is price relative to VWAP standard deviation bands?"""
        p = self.price
        if p > self.upper_2:   return "above_2sd"
        if p > self.upper_1:   return "above_1sd"
        if p < self.lower_2:   return "below_2sd"
        if p < self.lower_1:   return "below_1sd"
        return "inside_1sd"

    @property
    def is_extreme_deviation(self) -> bool:
        """True if deviation exceeds 1.5 ATR (default threshold)."""
        return abs(self.deviation_atr) >= 1.5

    @property
    def confluence_points(self) -> int:
        return 1 if self.is_extreme_deviation else 0

    def __repr__(self) -> str:
        return (f"VWAP(val={self.value:.5f} | dev={self.deviation:.5f} | "
                f"dev_atr={self.deviation_atr:.2f} | band={self.band_position})")


class VWAPIndicator:
    """
    VWAP with standard deviation bands.

    Parameters
    ----------
    use_session_reset : bool
        If True, reset VWAP at midnight UTC (standard for forex/indices).
        If False, use rolling_period candles (for 24/7 synthetic indices).

    rolling_period : int
        Candles to use when session reset is disabled. Default 96 (1 day of M15).

    dev_threshold_atr : float
        ATR multiplier for extreme deviation signal. Default 1.5.

    sd_multipliers : tuple
        Standard deviation multipliers for the bands. Default (1.0, 2.0).
    """

    def __init__(
        self,
        use_session_reset: bool  = True,
        rolling_period:    int   = 96,
        dev_threshold_atr: float = 1.5,
        sd_multipliers:    tuple = (1.0, 2.0),
    ) -> None:
        self.use_session_reset = use_session_reset
        self.rolling_period    = rolling_period
        self.dev_threshold_atr = dev_threshold_atr
        self.sd_multipliers    = sd_multipliers

    def compute(
        self,
        candles: list[Candle],
        atr:     float = 1.0,
    ) -> Optional[VWAPResult]:
        """
        Compute VWAP and deviation for the most recent candle.
        Returns None if fewer than 2 candles available.
        """
        if len(candles) < 2:
            return None

        session_candles = self._get_session_candles(candles)
        if not session_candles:
            return None

        typical_prices = [(c.high + c.low + c.close) / 3 for c in session_candles]
        volumes        = [max(c.volume, 1e-10) for c in session_candles]

        cum_tpv  = float(np.sum([tp * v for tp, v in zip(typical_prices, volumes)]))
        cum_vol  = float(np.sum(volumes))
        vwap_val = cum_tpv / cum_vol

        # Standard deviation bands using volume-weighted variance
        vw_variance = float(np.sum([
            v * (tp - vwap_val) ** 2
            for tp, v in zip(typical_prices, volumes)
        ])) / cum_vol
        vwap_sd = float(np.sqrt(vw_variance)) if vw_variance > 0 else 1e-8

        sd1, sd2   = self.sd_multipliers
        price      = candles[-1].close
        deviation  = price - vwap_val
        dev_atr    = deviation / max(atr, 1e-10)

        return VWAPResult(
            value         = round(vwap_val, 6),
            deviation     = round(deviation, 6),
            deviation_atr = round(dev_atr, 4),
            upper_1       = round(vwap_val + sd1 * vwap_sd, 6),
            lower_1       = round(vwap_val - sd1 * vwap_sd, 6),
            upper_2       = round(vwap_val + sd2 * vwap_sd, 6),
            lower_2       = round(vwap_val - sd2 * vwap_sd, 6),
            price         = price,
            candles_used  = len(session_candles),
        )

    def _get_session_candles(self, candles: list[Candle]) -> list[Candle]:
        """
        Return the candles for the current session.
        Session = same UTC day when use_session_reset=True,
        otherwise last `rolling_period` candles.
        """
        if not self.use_session_reset:
            return candles[-self.rolling_period:] if len(candles) > self.rolling_period else candles

        if not candles:
            return []

        last_ts      = candles[-1].timestamp
        last_dt      = datetime.fromtimestamp(last_ts, tz=timezone.utc)
        session_start = last_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        session_ts   = int(session_start.timestamp())

        session = [c for c in candles if c.timestamp >= session_ts]
        return session if session else candles[-1:]
