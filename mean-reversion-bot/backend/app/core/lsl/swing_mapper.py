"""
swing_mapper.py
────────────────────────────────────────────────────────────────────────────────
Swing High / Low Mapper — Liquidity Zone Builder
────────────────────────────────────────────────────────────────────────────────

WHAT THIS MODULE DOES:
    Scans historical candles to identify significant swing highs and swing lows.
    These are the price levels where stop-loss orders cluster — the "liquidity"
    that the LSL detector watches for grabs.

    A swing high = a candle whose high is higher than N candles on both sides.
    A swing low  = a candle whose low  is lower  than N candles on both sides.

    Each swing point becomes a LiquidityZone with a strength score based on:
    - How many times the level has been tested (more = stronger)
    - How cleanly price bounced from it (wick quality)
    - How recently it was formed (recent = more relevant)
    - Whether it aligns with a round number (psychological level)

ZONE STRENGTH SCORING (0.0 – 1.0):
    Base score      = 0.4   (for being a valid swing)
    +0.15           for each additional test/touch (max 3 bonus)
    +0.10           for round number alignment (e.g. 1950.00, 1.3000)
    +0.10           for clean wick bounce quality
    -0.10 per bar   age decay (older zones lose relevance, minimum 0.20)

USAGE:
    from app.core.lsl.swing_mapper import SwingMapper
    from app.core.lsl.lsl_detector import Candle

    mapper = SwingMapper(lookback=5, max_zones=10)
    swing_map = mapper.build(candles, symbol="XAUUSD", timeframe="M5")

    # Pass swing_map to LSLDetector each candle close
    signal = detector.detect(candles, swing_map, atr)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from .lsl_detector import Candle, LiquidityZone, SwingMap

logger = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────────────


@dataclass
class SwingMapperConfig:
    """
    Configuration for SwingMapper.

    Attributes
    ----------
    lookback : int
        Number of candles on EACH SIDE of a pivot to confirm a swing.
        lookback=5 means a swing high must be the highest of 5 candles
        before AND 5 candles after it. Higher = stronger, fewer swings.
        Recommended: 3 (scalping M1/M5), 5 (M15/H1), 8 (H4/D1).

    max_zones : int
        Maximum swing zones to keep per side (highs / lows separately).
        Keeps only the N strongest/most-recent zones to avoid clutter.

    merge_atr_mult : float
        Zones within this × ATR of each other are merged into one.
        Prevents duplicate zones at the same price area.

    min_strength : float
        Zones below this strength score are dropped from the map.

    round_number_pips : float
        Within this distance (in price units) of a round number, a zone
        gets a +0.10 strength bonus. Default 0.5 for forex, adjust for indices.

    age_decay_per_bar : float
        Strength reduction per candle of age. Default 0.01 = 1% per bar.
        Zone disappears from map below min_strength threshold.
    """
    lookback:            int   = 5
    max_zones:           int   = 10
    merge_atr_mult:      float = 0.30
    min_strength:        float = 0.20
    round_number_pips:   float = 0.50
    age_decay_per_bar:   float = 0.01


# ─── SwingMapper ──────────────────────────────────────────────────────────────


class SwingMapper:
    """
    Builds and maintains a SwingMap from OHLCV candle data.

    Identifies swing highs and swing lows using a pivot-point algorithm,
    scores each zone for strength, merges nearby zones, and returns a
    clean SwingMap ready for the LSL detector.

    The mapper is stateful — call update() on each new candle to maintain
    a live zone map, or call build() to recompute from scratch.
    """

    def __init__(self, config: Optional[SwingMapperConfig] = None, **kwargs) -> None:
        """
        Parameters
        ----------
        config : SwingMapperConfig, optional
            Full config object. If None, built from kwargs or defaults.
        **kwargs
            Shorthand: SwingMapper(lookback=5, max_zones=8) — passed to config.
        """
        if config is None:
            config = SwingMapperConfig(**{
                k: v for k, v in kwargs.items()
                if k in SwingMapperConfig.__dataclass_fields__
            })
        self.cfg = config
        self._cached_map: Optional[SwingMap] = None

        logger.info(
            "SwingMapper init | lookback=%d | max_zones=%d | merge=%.2f ATR",
            config.lookback, config.max_zones, config.merge_atr_mult,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def build(
        self,
        candles:   list[Candle],
        symbol:    str = "",
        timeframe: str = "",
        atr:       Optional[float] = None,
    ) -> SwingMap:
        """
        Build a full SwingMap from scratch from a list of candles.
        Call this on startup or when switching instruments/timeframes.

        Parameters
        ----------
        candles   : list[Candle]   Full candle history, oldest FIRST.
        symbol    : str            Instrument name for logging.
        timeframe : str            Timeframe string for zone metadata.
        atr       : float, optional  Current ATR for merge distance.
                                     Auto-computed from candles if not provided.

        Returns
        -------
        SwingMap with populated highs and lows lists.
        """
        if len(candles) < (self.cfg.lookback * 2 + 1):
            logger.warning(
                "SwingMapper.build: need %d candles minimum, got %d",
                self.cfg.lookback * 2 + 1, len(candles),
            )
            return SwingMap(symbol=symbol, timeframe=timeframe, built_at=datetime.utcnow())

        if atr is None:
            atr = self._compute_simple_atr(candles)

        # 1. Find raw pivot points
        raw_highs = self._find_swing_highs(candles)
        raw_lows  = self._find_swing_lows(candles)

        # 2. Convert to LiquidityZone objects with strength scores
        high_zones = [self._to_zone(c, candles, is_high=True,  timeframe=timeframe) for c in raw_highs]
        low_zones  = [self._to_zone(c, candles, is_high=False, timeframe=timeframe) for c in raw_lows]

        # 3. Merge nearby zones
        high_zones = self._merge_zones(high_zones, atr)
        low_zones  = self._merge_zones(low_zones,  atr)

        # 4. Filter by minimum strength
        high_zones = [z for z in high_zones if z.strength >= self.cfg.min_strength]
        low_zones  = [z for z in low_zones  if z.strength >= self.cfg.min_strength]

        # 5. Keep only the strongest N zones
        high_zones = sorted(high_zones, key=lambda z: z.strength, reverse=True)[:self.cfg.max_zones]
        low_zones  = sorted(low_zones,  key=lambda z: z.strength, reverse=True)[:self.cfg.max_zones]

        swing_map = SwingMap(
            highs=high_zones,
            lows=low_zones,
            symbol=symbol,
            timeframe=timeframe,
            built_at=datetime.utcnow(),
        )

        self._cached_map = swing_map
        logger.info(
            "SwingMap built | %s %s | highs=%d | lows=%d | ATR=%.5f",
            symbol, timeframe, len(high_zones), len(low_zones), atr,
        )
        return swing_map

    def update(
        self,
        new_candle: Candle,
        candles:    list[Candle],
        symbol:     str = "",
        timeframe:  str = "",
        atr:        Optional[float] = None,
    ) -> SwingMap:
        """
        Incremental update — add a new closed candle and refresh the map.
        More efficient than full rebuild on every tick.

        Rebuilds from scratch every 50 candles for accuracy,
        otherwise does a lightweight update.
        """
        # Full rebuild every 50 candles to catch new pivots cleanly
        if len(candles) % 50 == 0 or self._cached_map is None:
            return self.build(candles, symbol=symbol, timeframe=timeframe, atr=atr)

        # Lightweight: apply age decay to existing zones
        if self._cached_map:
            self._apply_age_decay(self._cached_map)
            self._remove_invalidated(self._cached_map, new_candle)

        return self._cached_map or self.build(candles, symbol=symbol, timeframe=timeframe, atr=atr)

    def mark_grabbed(self, swing_map: SwingMap, price: float, tolerance: float = 0.001) -> None:
        """
        After LSLDetector confirms a grab, mark the zone as tested.
        Increments test_count and updates last_tested timestamp.
        Zones tested 3+ times gain strength (they're well-known levels).
        """
        for zone in swing_map.all_zones:
            if abs(zone.price - price) <= tolerance:
                zone.test_count  += 1
                zone.last_tested  = datetime.utcnow()
                # Bonus strength for multiple tests (institutional level)
                if zone.test_count <= 3:
                    zone.strength = min(zone.strength + 0.10, 1.0)
                logger.debug("Zone %.5f marked grabbed | tests=%d | strength=%.2f",
                             zone.price, zone.test_count, zone.strength)

    def invalidate_zone(self, swing_map: SwingMap, price: float, tolerance: float = 0.001) -> None:
        """
        Mark a zone as invalidated — price broke through and closed beyond it.
        Invalidated zones are excluded from future grab detection.
        """
        for zone in swing_map.all_zones:
            if abs(zone.price - price) <= tolerance:
                zone.invalidated = True
                logger.info("Zone %.5f INVALIDATED (price closed through)", zone.price)

    # ── Internal: Pivot Detection ─────────────────────────────────────────────

    def _find_swing_highs(self, candles: list[Candle]) -> list[Candle]:
        """
        Find swing high candles: candles whose high is the highest
        within `lookback` candles on each side.

        Uses a simple rolling-max comparison for efficiency.
        """
        lb = self.cfg.lookback
        highs: list[Candle] = []

        for i in range(lb, len(candles) - lb):
            pivot = candles[i]
            left  = candles[i - lb : i]
            right = candles[i + 1 : i + lb + 1]

            is_highest_left  = all(pivot.high > c.high for c in left)
            is_highest_right = all(pivot.high > c.high for c in right)

            if is_highest_left and is_highest_right:
                highs.append(pivot)

        return highs

    def _find_swing_lows(self, candles: list[Candle]) -> list[Candle]:
        """
        Find swing low candles: candles whose low is the lowest
        within `lookback` candles on each side.
        """
        lb = self.cfg.lookback
        lows: list[Candle] = []

        for i in range(lb, len(candles) - lb):
            pivot = candles[i]
            left  = candles[i - lb : i]
            right = candles[i + 1 : i + lb + 1]

            is_lowest_left  = all(pivot.low < c.low for c in left)
            is_lowest_right = all(pivot.low < c.low for c in right)

            if is_lowest_left and is_lowest_right:
                lows.append(pivot)

        return lows

    # ── Internal: Zone Building ───────────────────────────────────────────────

    def _to_zone(
        self,
        pivot:     Candle,
        candles:   list[Candle],
        is_high:   bool,
        timeframe: str,
    ) -> LiquidityZone:
        """
        Convert a pivot candle into a LiquidityZone with a strength score.
        """
        price      = pivot.high if is_high else pivot.low
        zone_type  = "swing_high" if is_high else "swing_low"
        strength   = self._score_zone(pivot, candles, price, is_high)

        return LiquidityZone(
            price      = round(price, 6),
            zone_type  = zone_type,
            timeframe  = timeframe,
            strength   = strength,
            first_seen = datetime.utcfromtimestamp(pivot.timestamp),
        )

    def _score_zone(
        self,
        pivot:    Candle,
        candles:  list[Candle],
        price:    float,
        is_high:  bool,
    ) -> float:
        """
        Score a swing zone from 0.0 to 1.0.

        Scoring breakdown:
        - Base:              0.40  (valid pivot confirmed)
        - Touch count bonus: up to +0.30 (0.10 per extra touch, max 3)
        - Round number:      +0.10 if within pip threshold of round number
        - Wick quality:      +0.10 if pivot has a clean rejection wick
        - Age decay:         -0.01 per bar of age from end of candles
        """
        score = 0.40

        # Count additional touches (same price ± small tolerance)
        touch_count = self._count_touches(candles, price, tolerance_pct=0.001)
        score += min(touch_count * 0.10, 0.30)

        # Round number bonus
        if self._is_near_round_number(price):
            score += 0.10

        # Wick quality — clean rejection at level
        wick_ratio = pivot.upper_wick_ratio() if is_high else pivot.lower_wick_ratio()
        if wick_ratio > 0.50:
            score += 0.10

        # Age decay — how far from end of candles was this pivot?
        pivot_idx = next(
            (i for i, c in enumerate(candles) if c.timestamp == pivot.timestamp),
            len(candles) - 1,
        )
        age_bars = len(candles) - 1 - pivot_idx
        score -= age_bars * self.cfg.age_decay_per_bar

        return round(max(score, self.cfg.min_strength), 4)

    def _count_touches(
        self,
        candles:       list[Candle],
        price:         float,
        tolerance_pct: float = 0.001,
    ) -> int:
        """
        Count candles that came within tolerance% of a price level.
        Each touch = additional evidence stops are clustered there.
        """
        tolerance = price * tolerance_pct
        count = 0
        for c in candles:
            if abs(c.high - price) <= tolerance or abs(c.low - price) <= tolerance:
                count += 1
        return max(count - 1, 0)   # Subtract 1 (the pivot itself)

    def _is_near_round_number(self, price: float) -> bool:
        """
        Check if price is near a round number (psychological level).
        Examples: 1950.00, 1.3000, 150.00, 50000.00

        Rounds to the nearest significant figure and checks distance.
        """
        # Try different round number magnitudes
        for magnitude in [0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0]:
            rounded = round(price / magnitude) * magnitude
            if abs(price - rounded) <= self.cfg.round_number_pips:
                return True
        return False

    # ── Internal: Zone Maintenance ────────────────────────────────────────────

    def _merge_zones(self, zones: list[LiquidityZone], atr: float) -> list[LiquidityZone]:
        """
        Merge zones that are within merge_atr_mult × ATR of each other.
        Keeps the stronger zone and adds touch count from the weaker one.

        This prevents the map from cluttering with duplicate zones at the
        same price area (e.g. two swing highs 0.1 pip apart).
        """
        if not zones:
            return zones

        merge_distance = self.cfg.merge_atr_mult * atr
        zones_sorted   = sorted(zones, key=lambda z: z.price)
        merged: list[LiquidityZone] = [zones_sorted[0]]

        for zone in zones_sorted[1:]:
            last = merged[-1]
            if abs(zone.price - last.price) <= merge_distance:
                # Keep the stronger zone, absorb touch count
                if zone.strength > last.strength:
                    merged[-1] = zone
                merged[-1].test_count  += zone.test_count
                merged[-1].strength     = min(merged[-1].strength + 0.05, 1.0)
                logger.debug("Merged zone %.5f into %.5f", zone.price, last.price)
            else:
                merged.append(zone)

        return merged

    def _apply_age_decay(self, swing_map: SwingMap) -> None:
        """Apply per-bar age decay to all zones in a cached map."""
        decay = self.cfg.age_decay_per_bar
        for zone in swing_map.all_zones:
            zone.strength = max(zone.strength - decay, self.cfg.min_strength)

    def _remove_invalidated(self, swing_map: SwingMap, new_candle: Candle) -> None:
        """
        Auto-invalidate zones that price has clearly closed through.

        A high zone is invalidated if a candle CLOSES above it (breakout confirmed).
        A low  zone is invalidated if a candle CLOSES below it (breakdown confirmed).
        """
        for zone in swing_map.highs:
            if new_candle.close > zone.price and not zone.invalidated:
                zone.invalidated = True
                logger.info("High zone %.5f auto-invalidated (close above)", zone.price)

        for zone in swing_map.lows:
            if new_candle.close < zone.price and not zone.invalidated:
                zone.invalidated = True
                logger.info("Low zone %.5f auto-invalidated (close below)", zone.price)

        # Remove invalidated zones from the list
        swing_map.highs = [z for z in swing_map.highs if not z.invalidated]
        swing_map.lows  = [z for z in swing_map.lows  if not z.invalidated]

    # ── Internal: Utilities ───────────────────────────────────────────────────

    def _compute_simple_atr(self, candles: list[Candle], period: int = 14) -> float:
        """Compute ATR without importing from lsl_detector to avoid circular import."""
        if len(candles) < 2:
            return 1.0
        trs = []
        for i in range(1, len(candles)):
            c = candles[i]
            p = candles[i - 1].close
            trs.append(max(c.high - c.low, abs(c.high - p), abs(c.low - p)))
        recent = trs[-period:] if len(trs) >= period else trs
        return float(np.mean(recent)) if recent else 1.0

    def summary(self, swing_map: SwingMap) -> str:
        """Return a human-readable summary of the current swing map."""
        lines = [
            f"SwingMap [{swing_map.symbol} {swing_map.timeframe}]",
            f"  Built : {swing_map.built_at}",
            f"  Highs : {len(swing_map.highs)}",
        ]
        for z in sorted(swing_map.highs, key=lambda z: z.price, reverse=True):
            lines.append(f"    ↑ {z.price:.5f}  str={z.strength:.2f}  tests={z.test_count}  {z.zone_type}")
        lines.append(f"  Lows  : {len(swing_map.lows)}")
        for z in sorted(swing_map.lows, key=lambda z: z.price, reverse=True):
            lines.append(f"    ↓ {z.price:.5f}  str={z.strength:.2f}  tests={z.test_count}  {z.zone_type}")
        return "\n".join(lines)
