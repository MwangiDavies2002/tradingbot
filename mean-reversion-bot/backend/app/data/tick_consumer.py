"""
tick_consumer.py
────────────────────────────────────────────────────────────────────────────────
Tick Consumer — Live Data Pipeline
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Receives raw tick and candle messages from DerivClient subscriptions,
    maintains a live rolling candle buffer per instrument/timeframe, and
    fires the signal engine on every completed candle close.

    DATA FLOW:
        Deriv WS → DerivClient → TickConsumer → CandleBuffer → SignalEngine
                                              ↓
                                         Redis cache (latest candles)
                                              ↓
                                         OrderManager (if signal fires)

    CANDLE BUFFER:
        Holds the last N candles per (symbol, timeframe) pair.
        New candles appended, oldest dropped when buffer exceeds max_size.
        Thread-safe via asyncio — no locks needed.

    SUPPORTED TIMEFRAMES:
        60   → M1    300  → M5    900 → M15
        3600 → H1   14400 → H4  86400 → D1

    ON EVERY CANDLE CLOSE:
        1. Append new candle to buffer
        2. Call signal_engine.evaluate(candles, symbol, timeframe)
        3. If decision.should_trade → call order_manager.execute(decision)
        4. Publish signal snapshot to Redis for dashboard

USAGE:
    consumer = TickConsumer(
        client         = deriv_client,
        signal_engine  = engine,
        order_manager  = manager,
        redis_client   = redis,
    )
    await consumer.subscribe("R_75", timeframe_seconds=300)
    await consumer.subscribe("BOOM500", timeframe_seconds=60)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.core.engine.signal_engine import SignalEngine, TradeDecision
from app.core.lsl.lsl_detector import Candle, InstrumentType, candles_from_dict
from app.execution.deriv_client import DerivClient
from app.execution.order_manager import OrderManager

logger = logging.getLogger(__name__)

# Timeframe seconds → human label
TIMEFRAME_LABELS: dict[int, str] = {
    60:    "M1",
    300:   "M5",
    900:   "M15",
    3600:  "H1",
    14400: "H4",
    86400: "D1",
}

# Deriv symbol → InstrumentType mapping
INSTRUMENT_MAP: dict[str, InstrumentType] = {
    "BOOM500":  InstrumentType.BOOM_500,
    "BOOM1000": InstrumentType.BOOM_1000,
    "CRASH500": InstrumentType.CRASH_500,
    "CRASH1000":InstrumentType.CRASH_1000,
    "R_10":     InstrumentType.VOLATILITY,
    "R_25":     InstrumentType.VOLATILITY,
    "R_50":     InstrumentType.VOLATILITY,
    "R_75":     InstrumentType.VOLATILITY,
    "R_100":    InstrumentType.VOLATILITY,
}


@dataclass
class SubscriptionInfo:
    """Tracks one active symbol/timeframe subscription."""
    symbol:           str
    timeframe:        int          # Seconds
    subscription_id:  str          # Deriv sub_id
    instrument_type:  Optional[InstrumentType]
    htf_bias:         Optional[str]  # "buy", "sell", None
    candles_received: int  = 0
    last_signal_at:   Optional[datetime] = None
    last_candle_ts:   Optional[int] = None

    @property
    def tf_label(self) -> str:
        return TIMEFRAME_LABELS.get(self.timeframe, f"{self.timeframe}s")


class TickConsumer:
    """
    Manages live data subscriptions and drives the signal engine.

    Parameters
    ----------
    client        : DerivClient    Authenticated Deriv client.
    signal_engine : SignalEngine   Initialised signal engine.
    order_manager : OrderManager   For executing valid signals.
    redis_client  : optional       Redis client for caching candles/signals.
    buffer_size   : int            Max candles kept per symbol/tf. Default 500.
    min_candles   : int            Min candles before evaluating signals. Default 60.
    cooldown_bars : int            Min candles between signals per instrument. Default 3.
    """

    def __init__(
        self,
        client:         DerivClient,
        signal_engine:  SignalEngine,
        order_manager:  OrderManager,
        redis_client:   Optional[object] = None,
        buffer_size:    int = 500,
        min_candles:    int = 60,
        cooldown_bars:  int = 3,
    ) -> None:
        self.client        = client
        self.engine        = signal_engine
        self.manager       = order_manager
        self.redis         = redis_client
        self.buffer_size   = buffer_size
        self.min_candles   = min_candles
        self.cooldown_bars = cooldown_bars

        # (symbol, timeframe) → deque of Candle
        self._buffers:       dict[tuple, deque] = {}
        # (symbol, timeframe) → SubscriptionInfo
        self._subscriptions: dict[tuple, SubscriptionInfo] = {}
        # (symbol, timeframe) → bars since last signal (for cooldown)
        self._cooldown:      dict[tuple, int] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    async def bootstrap(
        self,
        symbol:     str,
        timeframe:  int,
        count:      int = 500,
        htf_bias:   Optional[str] = None,
    ) -> None:
        """
        Load historical candles to pre-fill the buffer before subscribing.
        Call this before subscribe() to ensure indicators have enough data.
        """
        logger.info("Bootstrapping %s %ds — loading %d candles...",
                    symbol, timeframe, count)
        raw = await self.client.get_candles(symbol, timeframe, count=count)
        if not raw:
            logger.warning("Bootstrap: no candles returned for %s", symbol)
            return

        candles = candles_from_dict(raw)
        key     = (symbol, timeframe)
        self._buffers[key] = deque(candles, maxlen=self.buffer_size)
        logger.info("Bootstrap complete: %d candles loaded for %s %s",
                    len(candles), symbol, TIMEFRAME_LABELS.get(timeframe, f"{timeframe}s"))

        # Cache to Redis if available
        await self._cache_candles(symbol, timeframe, candles[-50:])

    async def subscribe(
        self,
        symbol:     str,
        timeframe:  int,
        htf_bias:   Optional[str] = None,
    ) -> None:
        """
        Subscribe to live candle stream for a symbol/timeframe pair.
        Bootstrap should be called first for a warm buffer.

        Parameters
        ----------
        symbol    : str   Deriv symbol e.g. "R_75", "BOOM500", "frxEURUSD"
        timeframe : int   Candle size in seconds
        htf_bias  : str   Optional HTF trend bias ("buy"/"sell") from HTF analysis
        """
        key           = (symbol, timeframe)
        instrument_type = INSTRUMENT_MAP.get(symbol.upper())

        # Initialise buffer if not bootstrapped
        if key not in self._buffers:
            self._buffers[key] = deque(maxlen=self.buffer_size)

        # Build the message handler closure
        async def on_candle(msg: dict) -> None:
            await self._handle_candle_message(msg, symbol, timeframe)

        sub_id = await self.client.subscribe_candles(symbol, timeframe, on_candle)

        self._subscriptions[key] = SubscriptionInfo(
            symbol          = symbol,
            timeframe       = timeframe,
            subscription_id = sub_id,
            instrument_type = instrument_type,
            htf_bias        = htf_bias,
        )
        self._cooldown[key] = 0

        logger.info("Subscribed: %s %s (sub_id=%s | htf_bias=%s)",
                    symbol, TIMEFRAME_LABELS.get(timeframe, "?"), sub_id, htf_bias)

    async def unsubscribe(self, symbol: str, timeframe: int) -> None:
        """Remove a subscription and clean up its buffer."""
        key  = (symbol, timeframe)
        info = self._subscriptions.pop(key, None)
        if info:
            await self.client.forget_subscription(info.subscription_id)
        self._buffers.pop(key, None)
        self._cooldown.pop(key, None)
        logger.info("Unsubscribed: %s %s", symbol, timeframe)

    async def unsubscribe_all(self) -> None:
        """Unsubscribe from everything — called on bot shutdown."""
        keys = list(self._subscriptions.keys())
        for symbol, timeframe in keys:
            await self.unsubscribe(symbol, timeframe)

    def get_buffer(self, symbol: str, timeframe: int) -> list[Candle]:
        """Return current candle buffer as a list (copy). Newest last."""
        key = (symbol, timeframe)
        return list(self._buffers.get(key, []))

    def get_subscription_info(self, symbol: str, timeframe: int) -> Optional[SubscriptionInfo]:
        return self._subscriptions.get((symbol, timeframe))

    def status(self) -> dict:
        """Summary of all active subscriptions for dashboard/logging."""
        return {
            f"{s}/{TIMEFRAME_LABELS.get(tf, tf)}": {
                "candles_in_buffer": len(self._buffers.get((s, tf), [])),
                "candles_received":  info.candles_received,
                "last_candle":       info.last_candle_ts,
                "cooldown_bars":     self._cooldown.get((s, tf), 0),
            }
            for (s, tf), info in self._subscriptions.items()
        }

    # ── Internal: Message Handling ────────────────────────────────────────────

    async def _handle_candle_message(
        self, msg: dict, symbol: str, timeframe: int
    ) -> None:
        """
        Called on every candle update from Deriv.
        Deriv sends both in-progress and completed candles.
        We only act on COMPLETED candles (epoch advances).
        """
        ohlc = msg.get("ohlc") or msg.get("candles", [{}])[-1] if "candles" in msg else None
        if not ohlc:
            return

        # Deriv sends the candle's open epoch; a new epoch = new completed candle
        candle_epoch = int(ohlc.get("epoch", 0))
        key          = (symbol, timeframe)
        info         = self._subscriptions.get(key)
        if not info:
            return

        # Skip if same candle (still forming — not yet closed)
        if candle_epoch == info.last_candle_ts:
            return

        # Build Candle object
        new_candle = Candle(
            timestamp = candle_epoch,
            open      = float(ohlc.get("open",  0)),
            high      = float(ohlc.get("high",  0)),
            low       = float(ohlc.get("low",   0)),
            close     = float(ohlc.get("close", 0)),
            volume    = float(ohlc.get("volume", 0)),
        )

        # Append to rolling buffer
        self._buffers[key].append(new_candle)
        info.last_candle_ts   = candle_epoch
        info.candles_received += 1

        # Cooldown tracking
        self._cooldown[key] = max(0, self._cooldown.get(key, 0) - 1)

        logger.debug("Candle closed: %s %s | O=%.5f H=%.5f L=%.5f C=%.5f",
                     symbol, info.tf_label,
                     new_candle.open, new_candle.high,
                     new_candle.low,  new_candle.close)

        # Cache latest candles to Redis
        await self._cache_candles(symbol, timeframe, [new_candle])

        # Evaluate signal if enough candles and cooldown expired
        candle_list = list(self._buffers[key])
        if len(candle_list) < self.min_candles:
            logger.debug("Buffer warming up: %d/%d candles",
                         len(candle_list), self.min_candles)
            return

        if self._cooldown.get(key, 0) > 0:
            logger.debug("Cooldown active: %d bars remaining", self._cooldown[key])
            return

        await self._evaluate_and_act(candle_list, info)

    async def _evaluate_and_act(
        self, candles: list[Candle], info: SubscriptionInfo
    ) -> None:
        """Run the signal engine and execute if a valid trade decision is returned."""
        try:
            decision: TradeDecision = self.engine.evaluate(
                candles         = candles,
                symbol          = info.symbol,
                timeframe       = info.tf_label,
                instrument_type = info.instrument_type,
                htf_bias        = info.htf_bias,
            )
        except Exception as exc:
            logger.error("Signal engine error for %s: %s", info.symbol, exc, exc_info=True)
            return

        # Publish signal snapshot to Redis regardless of trade decision
        await self._publish_signal(info.symbol, info.tf_label, decision)

        if decision.should_trade:
            info.last_signal_at = datetime.utcnow()
            key = (info.symbol, info.timeframe)
            self._cooldown[key] = self.cooldown_bars  # Reset cooldown

            logger.info("🔔 SIGNAL: %s", decision.log_summary())
            await self.manager.execute(decision)
        else:
            logger.debug("No trade: %s %s — %s",
                         info.symbol, info.tf_label, decision.reason)

    # ── Internal: Caching ─────────────────────────────────────────────────────

    async def _cache_candles(
        self, symbol: str, timeframe: int, candles: list[Candle]
    ) -> None:
        """Push latest candles to Redis for dashboard consumption."""
        if not self.redis:
            return
        try:
            key  = f"candle:{symbol}:{timeframe}"
            data = json.dumps([{
                "timestamp": c.timestamp, "open": c.open,
                "high": c.high, "low": c.low, "close": c.close,
            } for c in candles])
            await self.redis.setex(key, 60, data)
        except Exception as exc:
            logger.debug("Redis cache write failed: %s", exc)

    async def _publish_signal(
        self, symbol: str, timeframe: str, decision: TradeDecision
    ) -> None:
        """Publish signal state to Redis for real-time dashboard feed."""
        if not self.redis:
            return
        try:
            key  = f"signal:{symbol}:{timeframe}"
            data = json.dumps({
                "symbol":        symbol,
                "timeframe":     timeframe,
                "should_trade":  decision.should_trade,
                "direction":     decision.direction,
                "score":         decision.confluence_score,
                "reason":        decision.reason,
                "timestamp":     datetime.utcnow().isoformat(),
                "indicators": {
                    "z_score":  decision.zscore.value    if decision.zscore   else None,
                    "rsi":      decision.rsi.value       if decision.rsi      else None,
                    "bb_pos":   decision.bollinger.position if decision.bollinger else None,
                    "hurst":    decision.hurst.value     if decision.hurst    else None,
                    "lsl":      decision.lsl_signal.direction.value
                                if decision.lsl_signal else None,
                },
            })
            await self.redis.setex(key, 30, data)
        except Exception as exc:
            logger.debug("Redis signal publish failed: %s", exc)
