"""
bos_choch.py
────────────────────────────────────────────────────────────────────────────────
BOS / CHoCH — Break of Structure & Change of Character
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Detects the two most important Smart Money Concepts price structure events:

    BOS  (Break of Structure):
        Price breaks a prior swing high in an UPTREND, or a prior swing low
        in a DOWNTREND. Confirms the existing trend is continuing.
        → Used to confirm HTF bias / trade direction.

    CHoCH (Change of Character):
        Price breaks structure in the OPPOSITE direction to the current trend.
        A CHoCH is the FIRST signal that the trend may be reversing.
        → In a downtrend, a CHoCH to the upside = potential BUY setup
        → Adds +1 confluence point to a mean-reversion signal

    INTERNAL vs EXTERNAL STRUCTURE:
        External structure = swing highs/lows on the displayed timeframe
        Internal structure = smaller swings WITHIN the external swing legs
        A CHoCH on internal structure is an earlier (but weaker) signal.

    MARKET STRUCTURE STATES:
        HH + HL = Bullish structure   (higher highs + higher lows)
        LH + LL = Bearish structure   (lower highs + lower lows)
        CHoCH   = Transition between the two

USAGE:
    from app.core.smc.bos_choch import BOSCHoCHDetector

    detector = BOSCHoCHDetector(lookback=5)
    result   = detector.detect(candles)
    print(result.market_structure, result.last_event, result.choch_detected)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from app.core.lsl.lsl_detector import Candle

logger = logging.getLogger(__name__)


class MarketStructure(str, Enum):
    BULLISH   = "bullish"    # HH + HL pattern
    BEARISH   = "bearish"    # LH + LL pattern
    RANGING   = "ranging"    # Mixed / unclear
    UNKNOWN   = "unknown"    # Not enough data


class StructureEvent(str, Enum):
    BOS_UP    = "bos_up"     # Broke above prior swing high (bullish continuation)
    BOS_DOWN  = "bos_down"   # Broke below prior swing low (bearish continuation)
    CHOCH_UP  = "choch_up"   # Broke above in a downtrend → potential bullish reversal
    CHOCH_DOWN = "choch_down" # Broke below in an uptrend → potential bearish reversal


@dataclass
class StructurePoint:
    """A confirmed swing high or low used for structure analysis."""
    price:     float
    kind:      str         # "high" or "low"
    timestamp: int
    broken:    bool = False

    @property
    def dt(self) -> datetime:
        return datetime.utcfromtimestamp(self.timestamp)


@dataclass
class BOSCHoCHResult:
    market_structure:  MarketStructure
    last_event:        Optional[StructureEvent]
    choch_detected:    bool
    bos_detected:      bool
    event_candle:      Optional[Candle]
    swing_highs:       list[StructurePoint] = field(default_factory=list)
    swing_lows:        list[StructurePoint] = field(default_factory=list)
    detected_at:       datetime = field(default_factory=datetime.utcnow)

    @property
    def direction(self) -> Optional[str]:
        """
        Trade direction implied by the last structure event.
        CHoCH events are more significant for mean reversion entries.
        """
        if self.last_event in (StructureEvent.CHOCH_UP, StructureEvent.BOS_UP):
            return "buy"
        if self.last_event in (StructureEvent.CHOCH_DOWN, StructureEvent.BOS_DOWN):
            return "sell"
        return None

    @property
    def confluence_points(self) -> int:
        """CHoCH = +1 point (stronger signal). BOS alone = 0 (just confirms bias)."""
        if self.choch_detected:
            return 1
        return 0

    def __repr__(self) -> str:
        return (f"BOS/CHoCH(struct={self.market_structure.value} | "
                f"event={self.last_event} | choch={self.choch_detected} | "
                f"pts={self.confluence_points})")


class BOSCHoCHDetector:
    """
    Detects Break of Structure and Change of Character events.

    Parameters
    ----------
    lookback : int
        Swing pivot lookback (candles each side). Default 5.
        Matches SwingMapper for consistency.
    history  : int
        How many recent structure points to track. Default 6.
        (3 highs + 3 lows is enough to define structure)
    """

    def __init__(self, lookback: int = 5, history: int = 6) -> None:
        self.lookback = lookback
        self.history  = history

    def detect(self, candles: list[Candle]) -> Optional[BOSCHoCHResult]:
        """
        Analyse candles and return the current market structure + last event.
        Returns None if insufficient candles.
        """
        min_needed = self.lookback * 2 + 2
        if len(candles) < min_needed:
            return None

        highs, lows = self._find_structure_points(candles)

        if len(highs) < 2 or len(lows) < 2:
            return BOSCHoCHResult(
                market_structure=MarketStructure.UNKNOWN,
                last_event=None,
                choch_detected=False,
                bos_detected=False,
                event_candle=None,
                swing_highs=highs,
                swing_lows=lows,
            )

        structure  = self._classify_structure(highs, lows)
        last_event, event_candle = self._detect_last_event(candles, highs, lows, structure)

        choch = last_event in (StructureEvent.CHOCH_UP, StructureEvent.CHOCH_DOWN)
        bos   = last_event in (StructureEvent.BOS_UP,   StructureEvent.BOS_DOWN)

        result = BOSCHoCHResult(
            market_structure=structure,
            last_event=last_event,
            choch_detected=choch,
            bos_detected=bos,
            event_candle=event_candle,
            swing_highs=highs,
            swing_lows=lows,
        )

        if choch:
            logger.info("CHoCH detected: %s | structure was %s", last_event, structure.value)
        elif bos:
            logger.debug("BOS detected: %s | structure: %s", last_event, structure.value)

        return result

    def _find_structure_points(
        self, candles: list[Candle]
    ) -> tuple[list[StructurePoint], list[StructurePoint]]:
        """Find recent swing highs and lows as StructurePoints."""
        lb     = self.lookback
        highs: list[StructurePoint] = []
        lows:  list[StructurePoint] = []

        for i in range(lb, len(candles) - lb):
            c     = candles[i]
            left  = candles[i - lb : i]
            right = candles[i + 1 : i + lb + 1]

            if all(c.high > x.high for x in left) and all(c.high > x.high for x in right):
                highs.append(StructurePoint(price=c.high, kind="high", timestamp=c.timestamp))

            if all(c.low < x.low for x in left) and all(c.low < x.low for x in right):
                lows.append(StructurePoint(price=c.low, kind="low", timestamp=c.timestamp))

        # Keep only most recent N points
        return highs[-self.history:], lows[-self.history:]

    def _classify_structure(
        self,
        highs: list[StructurePoint],
        lows:  list[StructurePoint],
    ) -> MarketStructure:
        """
        Classify overall structure from the last 2 swing highs and lows.
        HH + HL = Bullish | LH + LL = Bearish | Mixed = Ranging
        """
        if len(highs) < 2 or len(lows) < 2:
            return MarketStructure.UNKNOWN

        h1, h2 = highs[-2], highs[-1]   # h2 is more recent
        l1, l2 = lows[-2],  lows[-1]

        hh = h2.price > h1.price   # Higher high
        hl = l2.price > l1.price   # Higher low
        lh = h2.price < h1.price   # Lower high
        ll = l2.price < l1.price   # Lower low

        if hh and hl:   return MarketStructure.BULLISH
        if lh and ll:   return MarketStructure.BEARISH
        return MarketStructure.RANGING

    def _detect_last_event(
        self,
        candles:   list[Candle],
        highs:     list[StructurePoint],
        lows:      list[StructurePoint],
        structure: MarketStructure,
    ) -> tuple[Optional[StructureEvent], Optional[Candle]]:
        """
        Check if the most recent candle(s) have broken any structure points,
        and classify the break as BOS or CHoCH based on current structure.
        """
        last = candles[-1]

        # Check if price closed above the most recent swing high
        if highs:
            most_recent_high = highs[-1]
            if last.close > most_recent_high.price:
                if structure == MarketStructure.BEARISH:
                    return StructureEvent.CHOCH_UP, last   # Reversal signal
                else:
                    return StructureEvent.BOS_UP, last     # Continuation

        # Check if price closed below the most recent swing low
        if lows:
            most_recent_low = lows[-1]
            if last.close < most_recent_low.price:
                if structure == MarketStructure.BULLISH:
                    return StructureEvent.CHOCH_DOWN, last  # Reversal signal
                else:
                    return StructureEvent.BOS_DOWN, last    # Continuation

        return None, None
