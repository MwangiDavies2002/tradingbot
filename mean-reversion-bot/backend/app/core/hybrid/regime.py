"""Causal higher-timeframe classification using completed candles only."""
from dataclasses import dataclass
from enum import Enum
import math

from app.core.lsl.lsl_detector import Candle
from app.core.smc.bos_choch import BOSCHoCHDetector


class Regime(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


def ema(values, period):
    value = sum(values[:period]) / period
    for item in values[period:]:
        value += 2 / (period + 1) * (item - value)
    return value


@dataclass(frozen=True)
class RegimeConfig:
    timeframes: tuple[int, ...] = (3600, 14400)
    ema_period: int = 200
    swing_lookback: int = 3
    range_band_pct: float = 0.002
    use_vwap: bool = False

    def __post_init__(self):
        if (not self.timeframes or any(t <= 0 for t in self.timeframes)
                or self.ema_period < 2 or self.swing_lookback < 1
                or not math.isfinite(self.range_band_pct) or self.range_band_pct < 0):
            raise ValueError("Invalid regime configuration")


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    strong: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def direction(self):
        return {Regime.BULLISH: "buy", Regime.BEARISH: "sell"}.get(self.regime)


def completed_bars(candles: list[Candle], seconds: int, base_seconds: int,
                   as_of: int) -> list[Candle]:
    """Open timestamps; require every constituent bar, exclude incomplete/gapped buckets."""
    if seconds < base_seconds or seconds % base_seconds:
        raise ValueError("HTF must be an integer multiple of the base timeframe")
    groups = {}
    for c in candles:
        if c.timestamp + base_seconds <= as_of:
            groups.setdefault(c.timestamp // seconds * seconds, []).append(c)
    result = []
    for start, bars in sorted(groups.items()):
        expected = list(range(start, start + seconds, base_seconds))
        if start + seconds <= as_of and [c.timestamp for c in bars] == expected:
            result.append(Candle(start, bars[0].open, max(c.high for c in bars),
                                 min(c.low for c in bars), bars[-1].close,
                                 sum(c.volume for c in bars)))
    return result


class MarketRegime:
    def __init__(self, config=None):
        self.cfg = config or RegimeConfig()

    def classify(self, histories: dict[int, list[Candle]]) -> RegimeResult:
        votes = []
        for tf in self.cfg.timeframes:
            bars = histories.get(tf, [])
            if len(bars) < max(self.cfg.ema_period + 1, 4 * self.cfg.swing_lookback + 2):
                return RegimeResult(Regime.UNKNOWN, reasons=("HTF_WARMUP",))
            prices = [b.close for b in bars]
            mean = ema(prices, self.cfg.ema_period)
            previous = ema(prices[:-1], self.cfg.ema_period)
            structure = BOSCHoCHDetector(lookback=self.cfg.swing_lookback).detect(bars)
            highs, lows = structure.swing_highs, structure.swing_lows
            up = len(highs) >= 2 and len(lows) >= 2 and highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price
            down = len(highs) >= 2 and len(lows) >= 2 and highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price
            vwap = None
            if self.cfg.use_vwap:
                session = [b for b in bars if b.timestamp // 86400 == bars[-1].timestamp // 86400]
                volume = sum(b.volume for b in session)
                if volume <= 0:
                    return RegimeResult(Regime.UNKNOWN, reasons=("VWAP_VOLUME_UNAVAILABLE",))
                vwap = sum((b.high + b.low + b.close) / 3 * b.volume for b in session) / volume
            if up and prices[-1] > mean > previous and (vwap is None or prices[-1] > vwap):
                votes.append(Regime.BULLISH)
            elif down and prices[-1] < mean < previous and (vwap is None or prices[-1] < vwap):
                votes.append(Regime.BEARISH)
            elif abs(prices[-1] / mean - 1) <= self.cfg.range_band_pct and not up and not down:
                votes.append(Regime.RANGE)
            else:
                votes.append(Regime.UNKNOWN)
        if len(set(votes)) != 1:
            return RegimeResult(Regime.UNKNOWN, reasons=("HTF_DISAGREEMENT",))
        regime = votes[0]
        return RegimeResult(regime, regime in (Regime.BULLISH, Regime.BEARISH),
                            (f"HTF_TREND_{regime.value}",))
