"""
zone_builder.py
────────────────────────────────────────────────────────────────────────────────
Liquidity Zone Builder — Extended Zone Detection
────────────────────────────────────────────────────────────────────────────────

WHAT THIS MODULE DOES:
    SwingMapper finds swing highs and lows (stop cluster zones).
    ZoneBuilder finds ADDITIONAL liquidity zones from:

    1. Order Blocks (OB)
        The last bullish/bearish candle before a strong impulsive move away.
        When price returns to an OB zone, it's a high-probability reversal area
        because institutional orders likely remain unfilled there.

    2. Fair Value Gaps (FVG)
        Three-candle imbalance patterns where the wicks of candles 1 and 3
        do not overlap. Price is "magnetically" attracted back to fill the gap.
        Acts as both a target (mean reversion TO the gap) and an entry zone.

    3. Round Numbers / Psychological Levels
        00s, 000s, 0000s — retail stop orders cluster heavily here.
        e.g. XAUUSD: 1900, 1950, 2000 / EURUSD: 1.1000, 1.1500

    4. Previous Session High/Low (PDH/PDL)
        Prior day's high and low are extremely well-known liquidity zones.
        Widely targeted by institutional players during opening sessions.

ALL ZONES are returned as LiquidityZone objects compatible with LSLDetector.
This means the full LSL grab detection logic works on ALL zone types — not just
swing highs and lows.

USAGE:
    from app.core.lsl.zone_builder import ZoneBuilder
    from app.core.lsl.lsl_detector import Candle

    builder = ZoneBuilder()
    extra_zones = builder.build_all(candles, timeframe="M15")

    # Merge with SwingMapper zones
    swing_map.highs += extra_zones.highs
    swing_map.lows  += extra_zones.lows
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from .lsl_detector import Candle, LiquidityZone, SwingMap

logger = logging.getLogger(__name__)


# ─── Config ───────────────────────────────────────────────────────────────────


@dataclass
class ZoneBuilderConfig:
    """
    Configuration for ZoneBuilder.

    Attributes
    ----------
    impulse_atr_mult : float
        Minimum move (in ATR units) after an OB candle to qualify it as
        an Order Block. Default 2.0 — the impulse must be 2× ATR or more.

    fvg_min_gap_atr : float
        Minimum FVG gap size as a multiple of ATR to be considered significant.
        Filters tiny gaps that are just noise. Default 0.3.

    ob_strength : float
        Base strength for Order Block zones (0.0–1.0). Default 0.75.
        OBs are strong zones — institutional unfilled orders likely remain.

    fvg_strength : float
        Base strength for Fair Value Gap zones. Default 0.65.

    round_num_strength : float
        Base strength for psychological round number zones. Default 0.60.

    pdh_pdl_strength : float
        Base strength for previous day high/low zones. Default 0.80.
        PDH/PDL are extremely well-watched by professionals.

    ob_lookback : int
        How many candles back to scan for Order Blocks. Default 50.

    round_number_levels : list[float]
        Specific round number multiples to check for. Auto-built if empty.
    """
    impulse_atr_mult:    float = 2.0
    fvg_min_gap_atr:     float = 0.3
    ob_strength:         float = 0.75
    fvg_strength:        float = 0.65
    round_num_strength:  float = 0.60
    pdh_pdl_strength:    float = 0.80
    ob_lookback:         int   = 50


# ─── FVG Data Class ───────────────────────────────────────────────────────────


@dataclass
class FairValueGap:
    """
    A detected Fair Value Gap — an imbalance between candle 1 and candle 3.

    For a BULLISH FVG (gap above):
        candle_1.high < candle_3.low   → gap is between those two prices
        Price is expected to be drawn UP to fill the gap

    For a BEARISH FVG (gap below):
        candle_1.low > candle_3.high   → gap is between those two prices
        Price is expected to be drawn DOWN to fill the gap
    """
    top:       float          # Upper boundary of the gap
    bottom:    float          # Lower boundary of the gap
    direction: str            # "bullish" or "bearish"
    midpoint:  float          # (top + bottom) / 2
    size:      float          # top - bottom
    candle:    Candle         # The middle candle (candle 2) of the 3-candle pattern
    filled:    bool = False   # True once price has traded through the gap

    @property
    def as_zone(self) -> LiquidityZone:
        """Convert to a LiquidityZone at the midpoint for LSL integration."""
        zone_type = "fvg_bullish" if self.direction == "bullish" else "fvg_bearish"
        return LiquidityZone(
            price      = self.midpoint,
            zone_type  = zone_type,
            timeframe  = "",
            strength   = 0.65,
            first_seen = datetime.utcfromtimestamp(self.candle.timestamp),
        )


# ─── ZoneBuilder ─────────────────────────────────────────────────────────────


class ZoneBuilder:
    """
    Builds extended liquidity zones beyond basic swing highs/lows.

    Detects Order Blocks, Fair Value Gaps, Round Numbers, and PDH/PDL.
    All zones integrate seamlessly with LSLDetector via LiquidityZone objects.
    """

    def __init__(self, config: Optional[ZoneBuilderConfig] = None, **kwargs) -> None:
        if config is None:
            config = ZoneBuilderConfig(**{
                k: v for k, v in kwargs.items()
                if k in ZoneBuilderConfig.__dataclass_fields__
            })
        self.cfg = config
        logger.info("ZoneBuilder initialised | OB ATR mult=%.1f | FVG ATR min=%.2f",
                    config.impulse_atr_mult, config.fvg_min_gap_atr)

    # ── Public API ────────────────────────────────────────────────────────────

    def build_all(
        self,
        candles:   list[Candle],
        timeframe: str = "",
        atr:       Optional[float] = None,
        symbol:    str = "",
    ) -> SwingMap:
        """
        Build all extended zone types from candle data.
        Returns a SwingMap containing all detected zones as highs/lows.

        Merge the result with SwingMapper output to get the full zone picture:

            swing_map = swing_mapper.build(candles)
            extra     = zone_builder.build_all(candles)
            swing_map.highs += extra.highs
            swing_map.lows  += extra.lows
        """
        if len(candles) < 5:
            return SwingMap(symbol=symbol, timeframe=timeframe)

        if atr is None:
            atr = self._compute_atr(candles)

        all_highs: list[LiquidityZone] = []
        all_lows:  list[LiquidityZone] = []

        # Order Blocks
        ob_high, ob_low = self.find_order_blocks(candles, atr, timeframe)
        all_highs.extend(ob_high)
        all_lows.extend(ob_low)
        logger.debug("%s: OBs found — highs=%d lows=%d", symbol, len(ob_high), len(ob_low))

        # Fair Value Gaps
        fvg_high, fvg_low = self.find_fvg_zones(candles, atr, timeframe)
        all_highs.extend(fvg_high)
        all_lows.extend(fvg_low)
        logger.debug("%s: FVGs found — highs=%d lows=%d", symbol, len(fvg_high), len(fvg_low))

        # Round Numbers (based on current price range)
        rn_zones = self.find_round_number_zones(candles, timeframe)
        # Split round numbers into high/low based on relation to current price
        current_price = candles[-1].close
        all_highs.extend([z for z in rn_zones if z.price >= current_price])
        all_lows.extend( [z for z in rn_zones if z.price <  current_price])
        logger.debug("%s: Round numbers found — %d", symbol, len(rn_zones))

        # Previous Session High/Low
        pdh, pdl = self.find_previous_session_levels(candles, timeframe)
        if pdh:
            all_highs.append(pdh)
        if pdl:
            all_lows.append(pdl)

        return SwingMap(
            highs=all_highs,
            lows=all_lows,
            symbol=symbol,
            timeframe=timeframe,
            built_at=datetime.utcnow(),
        )

    # ── Order Block Detection ─────────────────────────────────────────────────

    def find_order_blocks(
        self,
        candles:   list[Candle],
        atr:       float,
        timeframe: str = "",
    ) -> tuple[list[LiquidityZone], list[LiquidityZone]]:
        """
        Detect Order Blocks — the last candle before a strong impulsive move.

        BEARISH OB (resistance zone / sell OB):
            Last BULLISH candle before a strong DOWNWARD impulse.
            When price returns to the body of this candle → sell.

        BULLISH OB (support zone / buy OB):
            Last BEARISH candle before a strong UPWARD impulse.
            When price returns to the body of this candle → buy.

        The OB candle's high/low become the zone boundaries.
        """
        lb = self.cfg.ob_lookback
        candles_to_scan = candles[-lb:] if len(candles) > lb else candles

        bearish_obs: list[LiquidityZone] = []   # Sell zones (resistance OBs)
        bullish_obs: list[LiquidityZone] = []   # Buy zones (support OBs)

        impulse_threshold = self.cfg.impulse_atr_mult * atr

        for i in range(1, len(candles_to_scan) - 1):
            ob_candle  = candles_to_scan[i]
            next_candle = candles_to_scan[i + 1]

            # ── Bearish OB: last bullish candle before downward impulse ──────
            if ob_candle.is_bullish:
                # Check if the NEXT move was a strong downward impulse
                downward_move = ob_candle.high - next_candle.close
                if downward_move >= impulse_threshold and next_candle.is_bearish:
                    strength = self._score_ob_strength(ob_candle, downward_move, atr)
                    zone = LiquidityZone(
                        price      = (ob_candle.high + ob_candle.open) / 2,   # OB midpoint
                        zone_type  = "order_block_bearish",
                        timeframe  = timeframe,
                        strength   = strength,
                        first_seen = datetime.utcfromtimestamp(ob_candle.timestamp),
                    )
                    bearish_obs.append(zone)
                    logger.debug("Bearish OB at %.5f | impulse=%.5f | str=%.2f",
                                 zone.price, downward_move, strength)

            # ── Bullish OB: last bearish candle before upward impulse ────────
            elif ob_candle.is_bearish:
                # Check if the NEXT move was a strong upward impulse
                upward_move = next_candle.close - ob_candle.low
                if upward_move >= impulse_threshold and next_candle.is_bullish:
                    strength = self._score_ob_strength(ob_candle, upward_move, atr)
                    zone = LiquidityZone(
                        price      = (ob_candle.low + ob_candle.close) / 2,   # OB midpoint
                        zone_type  = "order_block_bullish",
                        timeframe  = timeframe,
                        strength   = strength,
                        first_seen = datetime.utcfromtimestamp(ob_candle.timestamp),
                    )
                    bullish_obs.append(zone)
                    logger.debug("Bullish OB at %.5f | impulse=%.5f | str=%.2f",
                                 zone.price, upward_move, strength)

        # Keep only the 3 most recent (and strongest) OBs per side
        bearish_obs = sorted(bearish_obs, key=lambda z: z.first_seen, reverse=True)[:3]
        bullish_obs = sorted(bullish_obs, key=lambda z: z.first_seen, reverse=True)[:3]

        return bearish_obs, bullish_obs

    def _score_ob_strength(self, ob_candle: Candle, impulse: float, atr: float) -> float:
        """
        Score an Order Block zone's strength.
        Stronger impulse away from the OB = more likely institutional origin.
        """
        base = self.cfg.ob_strength
        # Impulse bonus: stronger impulse = more institutional conviction
        impulse_ratio = min(impulse / (atr * 4.0), 1.0)
        bonus = impulse_ratio * 0.20
        return round(min(base + bonus, 1.0), 4)

    # ── Fair Value Gap Detection ──────────────────────────────────────────────

    def find_fvgs(
        self,
        candles: list[Candle],
        atr:     float,
    ) -> list[FairValueGap]:
        """
        Detect all unfilled Fair Value Gaps in a candle series.

        A FVG exists when the wick of candle[i-1] and the wick of candle[i+1]
        do NOT overlap — creating a price zone candle[i] didn't cover.

        BULLISH FVG: candle[i-1].high < candle[i+1].low  (gap above)
        BEARISH FVG: candle[i-1].low  > candle[i+1].high (gap below)
        """
        fvgs: list[FairValueGap] = []
        min_gap = self.cfg.fvg_min_gap_atr * atr

        for i in range(1, len(candles) - 1):
            c1 = candles[i - 1]   # candle before
            c2 = candles[i]       # middle candle
            c3 = candles[i + 1]   # candle after

            # Bullish FVG — gap is ABOVE, price should be drawn up to fill
            if c1.high < c3.low:
                gap_size = c3.low - c1.high
                if gap_size >= min_gap:
                    fvg = FairValueGap(
                        top       = c3.low,
                        bottom    = c1.high,
                        direction = "bullish",
                        midpoint  = (c3.low + c1.high) / 2,
                        size      = gap_size,
                        candle    = c2,
                    )
                    fvgs.append(fvg)

            # Bearish FVG — gap is BELOW, price should be drawn down to fill
            elif c1.low > c3.high:
                gap_size = c1.low - c3.high
                if gap_size >= min_gap:
                    fvg = FairValueGap(
                        top       = c1.low,
                        bottom    = c3.high,
                        direction = "bearish",
                        midpoint  = (c1.low + c3.high) / 2,
                        size      = gap_size,
                        candle    = c2,
                    )
                    fvgs.append(fvg)

        # Mark filled gaps (price has since traded through the gap)
        current_price = candles[-1].close
        for fvg in fvgs:
            if fvg.direction == "bullish" and current_price > fvg.top:
                fvg.filled = True
            elif fvg.direction == "bearish" and current_price < fvg.bottom:
                fvg.filled = True

        return [f for f in fvgs if not f.filled]

    def find_fvg_zones(
        self,
        candles:   list[Candle],
        atr:       float,
        timeframe: str = "",
    ) -> tuple[list[LiquidityZone], list[LiquidityZone]]:
        """
        Convert unfilled FVGs to LiquidityZone objects split by direction.
        Returns (zones_above_price, zones_below_price).
        """
        fvgs = self.find_fvgs(candles, atr)
        current = candles[-1].close

        above: list[LiquidityZone] = []   # Bearish FVGs above price (sell magnet)
        below: list[LiquidityZone] = []   # Bullish FVGs below price (buy magnet)

        for fvg in fvgs:
            zone = LiquidityZone(
                price      = fvg.midpoint,
                zone_type  = f"fvg_{fvg.direction}",
                timeframe  = timeframe,
                strength   = self.cfg.fvg_strength,
                first_seen = datetime.utcfromtimestamp(fvg.candle.timestamp),
            )
            if fvg.midpoint >= current:
                above.append(zone)
            else:
                below.append(zone)

        # Keep only the 5 closest FVGs per side
        above = sorted(above, key=lambda z: z.price)[:5]
        below = sorted(below, key=lambda z: z.price, reverse=True)[:5]

        return above, below

    # ── Round Number Zones ────────────────────────────────────────────────────

    def find_round_number_zones(
        self,
        candles:   list[Candle],
        timeframe: str = "",
        range_atr_mult: float = 10.0,
    ) -> list[LiquidityZone]:
        """
        Find round number (psychological level) zones within the current
        price range of the candle series.

        Automatically determines the appropriate rounding magnitude based
        on the instrument's price level:
        - Price > 1000:  round to nearest 50 and 100
        - Price 10-1000: round to nearest 5 and 10
        - Price 1-10:    round to nearest 0.05 and 0.1
        - Price < 1:     round to nearest 0.001 and 0.005
        """
        if not candles:
            return []

        current   = candles[-1].close
        atr       = self._compute_atr(candles)
        price_range = range_atr_mult * atr

        # Determine rounding levels appropriate for this instrument
        round_levels = self._get_round_levels(current)

        zones: list[LiquidityZone] = []
        seen_prices: set[float] = set()

        for level in round_levels:
            # Find all round numbers within range of current price
            lower_bound = current - price_range
            upper_bound = current + price_range

            n_low  = int(lower_bound / level)
            n_high = int(upper_bound / level) + 1

            for n in range(n_low, n_high + 1):
                round_price = round(n * level, 8)
                if lower_bound <= round_price <= upper_bound:
                    # Avoid duplicate prices
                    key = round(round_price, 5)
                    if key not in seen_prices:
                        seen_prices.add(key)
                        zones.append(LiquidityZone(
                            price      = round_price,
                            zone_type  = "round_number",
                            timeframe  = timeframe,
                            strength   = self.cfg.round_num_strength,
                            first_seen = datetime.utcnow(),
                        ))

        logger.debug("Round number zones in range: %d", len(zones))
        return zones

    def _get_round_levels(self, price: float) -> list[float]:
        """Return appropriate round number levels for the given price magnitude."""
        if price > 10_000:
            return [1000.0, 500.0, 100.0]
        elif price > 1_000:
            return [100.0, 50.0, 10.0]
        elif price > 100:
            return [10.0, 5.0, 1.0]
        elif price > 10:
            return [1.0, 0.5, 0.1]
        elif price > 1:
            return [0.1, 0.05, 0.01]
        elif price > 0.1:
            return [0.01, 0.005, 0.001]
        else:
            return [0.001, 0.0005]

    # ── Previous Session High / Low ───────────────────────────────────────────

    def find_previous_session_levels(
        self,
        candles:              list[Candle],
        timeframe:            str = "",
        session_candle_count: int = 96,     # ~1 day of M15 candles; adjust for TF
    ) -> tuple[Optional[LiquidityZone], Optional[LiquidityZone]]:
        """
        Identify the previous session's high and low as liquidity zones.

        PDH (Previous Day High) and PDL (Previous Day Low) are among the
        most-watched levels by professional traders. Stop orders cluster
        heavily just above PDH and just below PDL.

        Parameters
        ----------
        candles              : Full candle history
        session_candle_count : Number of candles in one "session".
                               Default 96 assumes M15 timeframe (96 × 15min = 1 day).
                               Adjust for other timeframes:
                               - M5:  288 candles/day
                               - M1:  1440 candles/day
                               - H1:  24 candles/day

        Returns
        -------
        (PDH zone, PDL zone) — either can be None if not enough history.
        """
        if len(candles) < session_candle_count * 2:
            return None, None

        # The "previous session" is the session before the most recent one
        prev_session = candles[-(session_candle_count * 2) : -session_candle_count]

        if not prev_session:
            return None, None

        pdh_price = max(c.high  for c in prev_session)
        pdl_price = min(c.low   for c in prev_session)
        session_start = datetime.utcfromtimestamp(prev_session[0].timestamp)

        pdh_zone = LiquidityZone(
            price      = pdh_price,
            zone_type  = "previous_day_high",
            timeframe  = timeframe,
            strength   = self.cfg.pdh_pdl_strength,
            first_seen = session_start,
        )
        pdl_zone = LiquidityZone(
            price      = pdl_price,
            zone_type  = "previous_day_low",
            timeframe  = timeframe,
            strength   = self.cfg.pdh_pdl_strength,
            first_seen = session_start,
        )

        logger.info("PDH=%.5f | PDL=%.5f | session_start=%s",
                    pdh_price, pdl_price, session_start.strftime("%Y-%m-%d %H:%M"))
        return pdh_zone, pdl_zone

    # ── Internal: Utilities ───────────────────────────────────────────────────

    def _compute_atr(self, candles: list[Candle], period: int = 14) -> float:
        """Compute ATR without circular import."""
        if len(candles) < 2:
            return 1.0
        trs = []
        for i in range(1, len(candles)):
            c, p = candles[i], candles[i - 1].close
            trs.append(max(c.high - c.low, abs(c.high - p), abs(c.low - p)))
        recent = trs[-period:] if len(trs) >= period else trs
        return float(np.mean(recent)) if recent else 1.0
