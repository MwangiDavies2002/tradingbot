"""
lsl_detector.py
────────────────────────────────────────────────────────────────────────────────
Liquidity Simulation Logic (LSL) — Core Detection Engine
────────────────────────────────────────────────────────────────────────────────

WHAT THIS MODULE DOES:
    Detects when price has performed a "liquidity grab" — a move engineered to
    trigger stop losses and breakout orders sitting beyond a key level, before
    reversing in the opposite direction.

THE EDGE:
    Most retail traders get trapped entering AFTER a breakout.
    This module detects when that breakout is FAKE — a grab — and signals the
    reversal entry instead.

THE 4 PHASES THIS DETECTS:
    Phase 1 → Setup:    Price approaches a known liquidity zone
    Phase 2 → Buildup:  Consolidation near the zone (stops stacking)
    Phase 3 → Grab:     Price spikes through the zone with a long wick, closes back inside
    Phase 4 → Reversal: Momentum flips — this is the entry signal

INSTRUMENTS:
    Works on all Deriv instruments. Special handling for:
    - Boom 500/1000:  Upward spike ticks = buy-side grab → expect downward reversion
    - Crash 500/1000: Downward spike ticks = sell-side grab → expect upward reversion
    - Volatility 75:  Standard LSL patterns apply fully

USAGE:
    from app.core.lsl.lsl_detector import LSLDetector, LSLSignal
    from app.core.lsl.swing_mapper import SwingMapper

    swing_mapper = SwingMapper(lookback=20)
    detector = LSLDetector(wick_ratio_min=0.6, proximity_atr_mult=0.5)

    swing_map = swing_mapper.build(candles)
    atr = compute_atr(candles, period=14)

    signal = detector.detect(candles, swing_map, atr)

    if signal and signal.is_confirmed:
        print(f"Grab detected: {signal.direction} | Strength: {signal.strength:.2f}")
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ─── Enums ────────────────────────────────────────────────────────────────────


class GrabDirection(str, Enum):
    """Direction of the liquidity grab (and therefore the reversal trade direction)."""
    BUY  = "buy"   # Grab was BELOW a swing low  → price now reverses UP  → go long
    SELL = "sell"  # Grab was ABOVE a swing high → price now reverses DOWN → go short


class GrabPhase(str, Enum):
    """Current phase of the liquidity grab pattern."""
    APPROACHING  = "approaching"   # Price within proximity threshold of a zone
    CONSOLIDATING = "consolidating" # Low-ATR candles near zone (stops stacking)
    GRABBED      = "grabbed"        # Spike through zone detected
    CONFIRMED    = "confirmed"      # Closed back inside zone — entry signal valid
    FAILED       = "failed"         # Setup invalidated (price continued through zone)


class InstrumentType(str, Enum):
    """Instrument type for specialised LSL logic."""
    BOOM_500    = "boom_500"
    BOOM_1000   = "boom_1000"
    CRASH_500   = "crash_500"
    CRASH_1000  = "crash_1000"
    VOLATILITY  = "volatility"   # Vol 10, 25, 50, 75, 100
    FOREX       = "forex"
    INDEX       = "index"


# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass
class Candle:
    """
    A single OHLCV candle.

    All price fields should be in the instrument's native quote currency.
    Timestamp is UTC epoch seconds (matches Deriv API format).
    """
    timestamp: int       # UTC epoch seconds
    open:      float
    high:      float
    low:       float
    close:     float
    volume:    float = 0.0

    @property
    def body_size(self) -> float:
        """Absolute candle body size (close - open)."""
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        """Total candle range high to low."""
        return self.high - self.low + 1e-10   # epsilon prevents division by zero

    @property
    def upper_wick(self) -> float:
        """Size of the upper wick."""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Size of the lower wick (positive value)."""
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    def upper_wick_ratio(self) -> float:
        """Upper wick as a fraction of total range. High = long upper wick (bearish grab)."""
        return self.upper_wick / self.total_range

    def lower_wick_ratio(self) -> float:
        """Lower wick as a fraction of total range. High = long lower wick (bullish grab)."""
        return self.lower_wick / self.total_range


@dataclass
class LiquidityZone:
    """
    A mapped liquidity zone — a price level where stop orders are clustered.

    Zones are built by SwingMapper from swing highs/lows, round numbers,
    prior session H/L, and order block boundaries.
    """
    price:         float
    zone_type:     str         # "swing_high", "swing_low", "round_number", "order_block"
    timeframe:     str         # "M1", "M5", "M15", "H1", "H4", "D1"
    strength:      float       # 0.0 – 1.0 (how many touches, how clean the level)
    first_seen:    datetime    = field(default_factory=datetime.utcnow)
    test_count:    int         = 0
    last_tested:   Optional[datetime] = None
    invalidated:   bool        = False

    def __repr__(self) -> str:
        return (f"LiquidityZone({self.zone_type} @ {self.price:.5f} | "
                f"strength={self.strength:.2f} | tests={self.test_count})")


@dataclass
class SwingMap:
    """
    Current map of swing highs and swing lows for one instrument.
    Built by SwingMapper and passed to LSLDetector on each candle.
    """
    highs:     list[LiquidityZone] = field(default_factory=list)
    lows:      list[LiquidityZone] = field(default_factory=list)
    symbol:    str = ""
    timeframe: str = ""
    built_at:  Optional[datetime] = None

    @property
    def all_zones(self) -> list[LiquidityZone]:
        return self.highs + self.lows


@dataclass
class LSLSignal:
    """
    Output of the LSL detector when a liquidity grab pattern is identified.

    A signal is only actionable when phase == GrabPhase.CONFIRMED.
    Always combine with confluence scoring before placing an order.
    """
    direction:         GrabDirection        # BUY (long) or SELL (short)
    phase:             GrabPhase            # Current phase of the grab pattern
    zone:              LiquidityZone        # The liquidity zone that was grabbed
    trigger_candle:    Candle               # The candle that triggered this signal
    symbol:            str = ""
    timeframe:         str = ""
    instrument_type:   Optional[InstrumentType] = None

    # ── Strength Metrics ──────────────────────────────────────────────────────
    wick_ratio:        float = 0.0    # Wick-to-range ratio of the grab candle (0–1)
    proximity_atr:     float = 0.0    # How close to zone in ATR units when approached
    zone_strength:     float = 0.0    # Strength of the zone that was grabbed
    consolidation_bars: int  = 0      # Candles spent consolidating near zone

    # ── Computed properties ───────────────────────────────────────────────────
    detected_at:       datetime = field(default_factory=datetime.utcnow)

    @property
    def is_confirmed(self) -> bool:
        """Only CONFIRMED phase signals should trigger entry evaluation."""
        return self.phase == GrabPhase.CONFIRMED

    @property
    def strength_score(self) -> float:
        """
        Composite LSL strength score (0.0 – 1.0).
        Combines wick ratio, zone strength, and consolidation quality.
        Higher = stronger grab, higher reversal probability.
        """
        wick_weight   = 0.50
        zone_weight   = 0.30
        consol_weight = 0.20

        # Normalise consolidation bars: 3–8 bars is ideal
        consol_score = min(self.consolidation_bars / 8.0, 1.0)

        score = (
            self.wick_ratio   * wick_weight  +
            self.zone_strength * zone_weight +
            consol_score       * consol_weight
        )
        return round(min(score, 1.0), 4)

    @property
    def confluence_points(self) -> int:
        """
        Points contributed to the multi-signal confluence scorer.
        +2 for a confirmed grab, +1 bonus for very strong grabs (score > 0.75).
        """
        if not self.is_confirmed:
            return 0
        return 2 + (1 if self.strength_score > 0.75 else 0)

    def __repr__(self) -> str:
        return (
            f"LSLSignal({self.direction.value.upper()} | "
            f"phase={self.phase.value} | "
            f"zone={self.zone.price:.5f} | "
            f"wick={self.wick_ratio:.2f} | "
            f"score={self.strength_score:.2f} | "
            f"pts={self.confluence_points})"
        )


# ─── Main Detector Class ──────────────────────────────────────────────────────


class LSLDetector:
    """
    Liquidity Simulation Logic Detector.

    Scans the most recent candles against a swing map to detect when price
    has performed a liquidity grab — spiked through a key level and closed
    back inside. This is the entry trigger for mean reversion trades.

    Parameters
    ----------
    wick_ratio_min : float
        Minimum wick-to-range ratio for the grab candle to qualify.
        Default 0.60 — wick must be ≥ 60% of the candle's total range.
        Increase to 0.70 for stricter / higher quality signals.

    proximity_atr_mult : float
        How close (in ATR units) price must be to a zone to enter
        "approaching" phase. Default 0.5 = within half an ATR.

    consolidation_atr_mult : float
        ATR multiplier for detecting consolidation — candles with range
        smaller than this × ATR are considered "inside" / low volatility.
        Default 0.7.

    min_consolidation_bars : int
        Minimum candles consolidating near a zone before a grab is expected.
        Default 2. Increase for cleaner setups.

    lookback : int
        How many candles back to check for context (consolidation count, etc.)
        Default 10.

    instrument_type : InstrumentType or None
        When set to BOOM_* or CRASH_*, activates spike-tick logic for
        synthetic indices. None = standard LSL logic for all others.
    """

    def __init__(
        self,
        wick_ratio_min:          float = 0.60,
        proximity_atr_mult:      float = 0.50,
        consolidation_atr_mult:  float = 0.70,
        min_consolidation_bars:  int   = 2,
        lookback:                int   = 10,
        instrument_type:         Optional[InstrumentType] = None,
    ) -> None:
        self.wick_ratio_min         = wick_ratio_min
        self.proximity_atr_mult     = proximity_atr_mult
        self.consolidation_atr_mult = consolidation_atr_mult
        self.min_consolidation_bars = min_consolidation_bars
        self.lookback               = lookback
        self.instrument_type        = instrument_type

        logger.info(
            "LSLDetector initialised | wick_min=%.2f | proximity=%.2f ATR | "
            "instrument=%s",
            wick_ratio_min,
            proximity_atr_mult,
            instrument_type.value if instrument_type else "standard",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def detect(
        self,
        candles:    list[Candle],
        swing_map:  SwingMap,
        atr:        float,
        symbol:     str = "",
        timeframe:  str = "",
    ) -> Optional[LSLSignal]:
        """
        Main detection method. Call on every new closed candle.

        Checks the latest candle against all mapped liquidity zones for
        evidence of a grab pattern. Returns the highest-quality signal found,
        or None if no grab is detected.

        Parameters
        ----------
        candles   : list[Candle]   Recent candles, newest LAST. Min 3 required.
        swing_map : SwingMap       Current liquidity zone map from SwingMapper.
        atr       : float          Current ATR value (14-period recommended).
        symbol    : str            Instrument symbol for logging.
        timeframe : str            Timeframe string for logging.

        Returns
        -------
        LSLSignal or None
        """
        if len(candles) < 3:
            logger.debug("LSLDetector: need at least 3 candles, got %d", len(candles))
            return None

        if atr <= 0:
            logger.warning("LSLDetector: invalid ATR value %.6f — skipping", atr)
            return None

        last = candles[-1]
        recent = candles[-self.lookback:] if len(candles) >= self.lookback else candles

        # Use spike-tick logic for synthetic indices (Boom/Crash)
        if self.instrument_type in (
            InstrumentType.BOOM_500, InstrumentType.BOOM_1000,
            InstrumentType.CRASH_500, InstrumentType.CRASH_1000,
        ):
            return self._detect_synthetic_spike(last, recent, swing_map, atr, symbol, timeframe)

        # Standard grab detection for Forex, Vol indices, real instruments
        sell_signal = self._check_sell_side_grab(last, recent, swing_map.highs, atr, symbol, timeframe)
        buy_signal  = self._check_buy_side_grab(last, recent, swing_map.lows,  atr, symbol, timeframe)

        # Return the stronger signal if both detected (rare but possible near confluence)
        signals = [s for s in [sell_signal, buy_signal] if s is not None]
        if not signals:
            return None

        best = max(signals, key=lambda s: s.strength_score)
        logger.info("LSL %s | %s", symbol, best)
        return best

    def scan_approaching(
        self,
        candles:   list[Candle],
        swing_map: SwingMap,
        atr:       float,
    ) -> list[LSLSignal]:
        """
        Returns early-phase (APPROACHING / CONSOLIDATING) signals.
        Useful for pre-alerting the dashboard before the grab fires.
        Does NOT represent a tradeable signal — confirmation still required.
        """
        if not candles or atr <= 0:
            return []

        last = candles[-1]
        signals: list[LSLSignal] = []

        for zone in swing_map.highs:
            proximity = (last.high - zone.price) / atr
            if abs(proximity) < self.proximity_atr_mult:
                phase = self._get_approach_phase(candles, atr)
                signals.append(LSLSignal(
                    direction=GrabDirection.SELL,
                    phase=phase,
                    zone=zone,
                    trigger_candle=last,
                    proximity_atr=abs(proximity),
                    zone_strength=zone.strength,
                ))

        for zone in swing_map.lows:
            proximity = (zone.price - last.low) / atr
            if abs(proximity) < self.proximity_atr_mult:
                phase = self._get_approach_phase(candles, atr)
                signals.append(LSLSignal(
                    direction=GrabDirection.BUY,
                    phase=phase,
                    zone=zone,
                    trigger_candle=last,
                    proximity_atr=abs(proximity),
                    zone_strength=zone.strength,
                ))

        return signals

    # ── Internal: Sell-Side Grab (above swing high) ───────────────────────────

    def _check_sell_side_grab(
        self,
        last:      Candle,
        recent:    list[Candle],
        zones:     list[LiquidityZone],
        atr:       float,
        symbol:    str,
        timeframe: str,
    ) -> Optional[LSLSignal]:
        """
        Detects a sell-side liquidity grab:
            - Price spiked ABOVE a swing high (grabbed buy stops)
            - Candle CLOSED back BELOW the zone
            - Reversal DOWN expected → SELL signal

        Pattern:
            ──────────  ← zone (swing high)
                  │ ← long upper wick above zone
            ██████   ← bearish candle body closes below zone
        """
        for zone in zones:
            if zone.invalidated:
                continue

            # 1. Did the candle high exceed the zone?
            if last.high <= zone.price:
                continue

            # 2. Did it close BACK BELOW the zone? (the key confirmation)
            if last.close >= zone.price:
                logger.debug(
                    "Sell-side: price pierced %.5f but closed above — no grab (breakout)",
                    zone.price,
                )
                continue

            # 3. Was the upper wick long enough? (filters noise)
            upper_wick_ratio = last.upper_wick_ratio()
            if upper_wick_ratio < self.wick_ratio_min:
                logger.debug(
                    "Sell-side: wick ratio %.2f < min %.2f at zone %.5f — skipping",
                    upper_wick_ratio, self.wick_ratio_min, zone.price,
                )
                continue

            # 4. How far did it grab beyond the zone?
            grab_distance = last.high - zone.price
            proximity_before = self._estimate_proximity_before_grab(recent, zone, is_high=True)

            # 5. Count consolidation bars near the zone before the grab
            consol_count = self._count_consolidation_bars(recent[:-1], atr, near_price=zone.price)

            logger.debug(
                "✅ SELL grab confirmed | zone=%.5f | wick=%.2f | consol=%d | dist=%.5f",
                zone.price, upper_wick_ratio, consol_count, grab_distance,
            )

            return LSLSignal(
                direction          = GrabDirection.SELL,
                phase              = GrabPhase.CONFIRMED,
                zone               = zone,
                trigger_candle     = last,
                symbol             = symbol,
                timeframe          = timeframe,
                instrument_type    = self.instrument_type,
                wick_ratio         = upper_wick_ratio,
                proximity_atr      = proximity_before,
                zone_strength      = zone.strength,
                consolidation_bars = consol_count,
            )

        return None

    # ── Internal: Buy-Side Grab (below swing low) ─────────────────────────────

    def _check_buy_side_grab(
        self,
        last:      Candle,
        recent:    list[Candle],
        zones:     list[LiquidityZone],
        atr:       float,
        symbol:    str,
        timeframe: str,
    ) -> Optional[LSLSignal]:
        """
        Detects a buy-side liquidity grab:
            - Price spiked BELOW a swing low (grabbed sell stops)
            - Candle CLOSED back ABOVE the zone
            - Reversal UP expected → BUY signal

        Pattern:
            ██████   ← bullish candle body closes above zone
                  │ ← long lower wick below zone
            ──────────  ← zone (swing low)
        """
        for zone in zones:
            if zone.invalidated:
                continue

            # 1. Did the candle low breach the zone?
            if last.low >= zone.price:
                continue

            # 2. Did it close BACK ABOVE the zone?
            if last.close <= zone.price:
                logger.debug(
                    "Buy-side: price pierced %.5f but closed below — no grab (breakdown)",
                    zone.price,
                )
                continue

            # 3. Was the lower wick long enough?
            lower_wick_ratio = last.lower_wick_ratio()
            if lower_wick_ratio < self.wick_ratio_min:
                logger.debug(
                    "Buy-side: wick ratio %.2f < min %.2f at zone %.5f — skipping",
                    lower_wick_ratio, self.wick_ratio_min, zone.price,
                )
                continue

            # 4. Distance grabbed below zone
            grab_distance = zone.price - last.low
            proximity_before = self._estimate_proximity_before_grab(recent, zone, is_high=False)

            # 5. Consolidation bars
            consol_count = self._count_consolidation_bars(recent[:-1], atr, near_price=zone.price)

            logger.debug(
                "✅ BUY grab confirmed | zone=%.5f | wick=%.2f | consol=%d | dist=%.5f",
                zone.price, lower_wick_ratio, consol_count, grab_distance,
            )

            return LSLSignal(
                direction          = GrabDirection.BUY,
                phase              = GrabPhase.CONFIRMED,
                zone               = zone,
                trigger_candle     = last,
                symbol             = symbol,
                timeframe          = timeframe,
                instrument_type    = self.instrument_type,
                wick_ratio         = lower_wick_ratio,
                proximity_atr      = proximity_before,
                zone_strength      = zone.strength,
                consolidation_bars = consol_count,
            )

        return None

    # ── Internal: Synthetic Indices (Boom/Crash spike logic) ──────────────────

    def _detect_synthetic_spike(
        self,
        last:      Candle,
        recent:    list[Candle],
        swing_map: SwingMap,
        atr:       float,
        symbol:    str,
        timeframe: str,
    ) -> Optional[LSLSignal]:
        """
        Special LSL logic for Boom/Crash synthetic indices.

        On Boom indices:  The spike IS upward. A spike candle with an extreme
                          upper wick signals that buy-side liquidity was grabbed.
                          Reversion DOWNWARD is the trade (SELL).

        On Crash indices: The spike IS downward. A spike candle with an extreme
                          lower wick signals that sell-side liquidity was grabbed.
                          Reversion UPWARD is the trade (BUY).

        The wick ratio threshold is higher here (default 0.80) because Boom/Crash
        spikes are more extreme and distinctive than standard grabs.
        """
        synthetic_wick_min = max(self.wick_ratio_min, 0.80)

        is_boom  = self.instrument_type in (InstrumentType.BOOM_500,  InstrumentType.BOOM_1000)
        is_crash = self.instrument_type in (InstrumentType.CRASH_500, InstrumentType.CRASH_1000)

        if is_boom:
            # Boom spike: look for extreme upper wick
            wr = last.upper_wick_ratio()
            if wr >= synthetic_wick_min:
                # Find nearest high zone that was grabbed, or create a synthetic one
                zone = self._nearest_zone(last.high, swing_map.highs) or LiquidityZone(
                    price=last.high, zone_type="boom_spike",
                    timeframe=timeframe, strength=wr,
                )
                consol = self._count_consolidation_bars(recent[:-1], atr, near_price=last.high)
                logger.info("🔴 BOOM SPIKE detected | %s | wick=%.2f", symbol, wr)
                return LSLSignal(
                    direction=GrabDirection.SELL,
                    phase=GrabPhase.CONFIRMED,
                    zone=zone,
                    trigger_candle=last,
                    symbol=symbol,
                    timeframe=timeframe,
                    instrument_type=self.instrument_type,
                    wick_ratio=wr,
                    zone_strength=wr,
                    consolidation_bars=consol,
                )

        if is_crash:
            # Crash spike: look for extreme lower wick
            wr = last.lower_wick_ratio()
            if wr >= synthetic_wick_min:
                zone = self._nearest_zone(last.low, swing_map.lows) or LiquidityZone(
                    price=last.low, zone_type="crash_spike",
                    timeframe=timeframe, strength=wr,
                )
                consol = self._count_consolidation_bars(recent[:-1], atr, near_price=last.low)
                logger.info("🟢 CRASH SPIKE detected | %s | wick=%.2f", symbol, wr)
                return LSLSignal(
                    direction=GrabDirection.BUY,
                    phase=GrabPhase.CONFIRMED,
                    zone=zone,
                    trigger_candle=last,
                    symbol=symbol,
                    timeframe=timeframe,
                    instrument_type=self.instrument_type,
                    wick_ratio=wr,
                    zone_strength=wr,
                    consolidation_bars=consol,
                )

        return None

    # ── Internal: Helpers ─────────────────────────────────────────────────────

    def _count_consolidation_bars(
        self,
        candles:    list[Candle],
        atr:        float,
        near_price: float,
    ) -> int:
        """
        Count how many recent candles were consolidating near a given price level.
        A candle is "consolidating" if:
          - Its total range is less than (consolidation_atr_mult × ATR)
          - Its midpoint is within 1 ATR of the target price
        """
        count = 0
        atr_threshold = self.consolidation_atr_mult * atr
        proximity_threshold = atr

        for candle in reversed(candles):
            midpoint = (candle.high + candle.low) / 2
            is_narrow   = candle.total_range < atr_threshold
            is_near     = abs(midpoint - near_price) < proximity_threshold
            if is_narrow and is_near:
                count += 1
            else:
                break   # Stop at the first non-consolidating candle (looking back)

        return count

    def _estimate_proximity_before_grab(
        self,
        recent:   list[Candle],
        zone:     LiquidityZone,
        is_high:  bool,
    ) -> float:
        """
        Estimate how close price was to the zone in the candles BEFORE the grab.
        Returns the minimum distance (in price units) observed.
        Used as a quality signal — closer approach = cleaner setup.
        """
        if len(recent) < 2:
            return 0.0

        distances = []
        for c in recent[:-1]:   # Exclude the grab candle itself
            ref_price = c.high if is_high else c.low
            distances.append(abs(ref_price - zone.price))

        return min(distances) if distances else 0.0

    def _get_approach_phase(
        self,
        candles: list[Candle],
        atr:     float,
    ) -> GrabPhase:
        """Determine if we're in APPROACHING or CONSOLIDATING phase."""
        if len(candles) < 2:
            return GrabPhase.APPROACHING

        # Check if last few candles are narrow (consolidation)
        narrow_count = sum(
            1 for c in candles[-3:]
            if c.total_range < self.consolidation_atr_mult * atr
        )
        if narrow_count >= self.min_consolidation_bars:
            return GrabPhase.CONSOLIDATING

        return GrabPhase.APPROACHING

    def _nearest_zone(
        self,
        price:  float,
        zones:  list[LiquidityZone],
        max_distance: float = 1e9,
    ) -> Optional[LiquidityZone]:
        """Find the nearest liquidity zone to a given price."""
        if not zones:
            return None
        closest = min(zones, key=lambda z: abs(z.price - price))
        if abs(closest.price - price) <= max_distance:
            return closest
        return None


# ─── Convenience Functions ────────────────────────────────────────────────────


def compute_atr(candles: list[Candle], period: int = 14) -> float:
    """
    Compute Average True Range (ATR) for a list of candles.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = rolling mean of True Range over `period` candles.

    This is used as the volatility normaliser throughout LSL detection.
    """
    if len(candles) < period + 1:
        # Fallback: simple average range if not enough data
        ranges = [c.total_range for c in candles]
        return float(np.mean(ranges)) if ranges else 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        curr = candles[i]
        prev_close = candles[i - 1].close
        tr = max(
            curr.high - curr.low,
            abs(curr.high - prev_close),
            abs(curr.low  - prev_close),
        )
        true_ranges.append(tr)

    # Use last `period` true ranges for ATR
    atr_values = true_ranges[-period:]
    return float(np.mean(atr_values))


def candles_from_dict(data: list[dict]) -> list[Candle]:
    """
    Convert a list of raw OHLCV dicts (e.g. from Deriv API) into Candle objects.

    Expected dict keys: epoch (or timestamp), open, high, low, close, volume (optional)
    """
    result = []
    for d in data:
        result.append(Candle(
            timestamp = int(d.get("epoch", d.get("timestamp", 0))),
            open      = float(d["open"]),
            high      = float(d["high"]),
            low       = float(d["low"]),
            close     = float(d["close"]),
            volume    = float(d.get("volume", 0.0)),
        ))
    return result
