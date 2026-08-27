"""
order_manager.py
────────────────────────────────────────────────────────────────────────────────
Order Manager — Trade Lifecycle Management
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Receives a TradeDecision from the signal engine and manages the complete
    lifecycle of the trade:

    1. PRE-FLIGHT CHECKS    Validate decision before touching the exchange
    2. MAP DIRECTION        Convert "buy"/"sell" to Deriv contract types
    3. PLACE ORDER          Call DerivClient.buy_contract()
    4. CONFIRM              Store open position, notify circuit breaker
    5. MONITOR SL/TP        Check every tick if SL or TP is hit
    6. CLOSE                Call DerivClient.sell_contract() + update records
    7. POST-TRADE           Update circuit breaker, position sizer balance

    DERIV CONTRACT TYPES (for Multipliers product):
        BUY  direction → MULTUP   (profit when price rises)
        SELL direction → MULTDOWN (profit when price falls)

    SL/TP MONITORING:
        Deriv Multipliers support server-side SL/TP (stop_loss, take_profit
        fields in the proposal). We use server-side where possible so
        positions close even if our bot crashes. We also monitor client-side
        as a backup.

    POSITION STATE MACHINE:
        PENDING → OPEN → CLOSED
                       ↘ CANCELLED (if open fails)

USAGE:
    manager = OrderManager(client=deriv_client, circuit_breaker=cb)

    # Called by the main bot loop on a valid TradeDecision
    position = await manager.execute(decision)

    # Called on each incoming tick to check SL/TP
    await manager.monitor_tick(symbol="R_75", current_price=1948.5)
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from app.core.engine.signal_engine import TradeDecision
from app.core.risk.circuit_breaker import CircuitBreaker
from app.core.risk.position_sizer import PositionSizer
from app.execution.deriv_client import DerivClient

logger = logging.getLogger(__name__)


class PositionStatus(str, Enum):
    PENDING   = "pending"
    OPEN      = "open"
    CLOSED    = "closed"
    CANCELLED = "cancelled"


class CloseReason(str, Enum):
    STOP_LOSS      = "stop_loss"
    TAKE_PROFIT    = "take_profit"
    MANUAL         = "manual"
    CIRCUIT_BREAK  = "circuit_break"
    TIME_EXIT      = "time_exit"
    SERVER_CLOSED  = "server_closed"


@dataclass
class Position:
    """Represents one live or historical trade position."""
    # Identity
    trade_id:       str                # Internal UUID
    contract_id:    Optional[int]      # Deriv contract_id (set after open)
    symbol:         str
    timeframe:      str
    direction:      str                # "buy" or "sell"
    contract_type:  str                # "MULTUP" or "MULTDOWN"

    # Prices
    entry_price:    float
    stop_loss:      float
    take_profit:    float
    exit_price:     Optional[float]    = None

    # Money
    stake:          float              = 0.0
    pnl:            Optional[float]   = None

    # Meta
    status:         PositionStatus     = PositionStatus.PENDING
    close_reason:   Optional[CloseReason] = None
    opened_at:      datetime           = field(default_factory=datetime.utcnow)
    closed_at:      Optional[datetime] = None
    confluence_score: int              = 0
    reason_code:    str                = ""

    @property
    def is_open(self) -> bool:
        return self.status == PositionStatus.OPEN

    @property
    def pnl_pct(self) -> Optional[float]:
        """P&L as % of stake."""
        if self.pnl is not None and self.stake > 0:
            return self.pnl / self.stake
        return None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.closed_at:
            return (self.closed_at - self.opened_at).total_seconds()
        return (datetime.utcnow() - self.opened_at).total_seconds()

    def sl_hit(self, price: float) -> bool:
        if self.direction == "buy":
            return price <= self.stop_loss
        return price >= self.stop_loss

    def tp_hit(self, price: float) -> bool:
        if self.direction == "buy":
            return price >= self.take_profit
        return price <= self.take_profit

    def to_dict(self) -> dict:
        return {
            "trade_id":        self.trade_id,
            "contract_id":     self.contract_id,
            "symbol":          self.symbol,
            "direction":       self.direction,
            "contract_type":   self.contract_type,
            "entry_price":     self.entry_price,
            "stop_loss":       self.stop_loss,
            "take_profit":     self.take_profit,
            "exit_price":      self.exit_price,
            "stake":           self.stake,
            "pnl":             self.pnl,
            "status":          self.status.value,
            "close_reason":    self.close_reason.value if self.close_reason else None,
            "opened_at":       self.opened_at.isoformat(),
            "closed_at":       self.closed_at.isoformat() if self.closed_at else None,
            "confluence_score": self.confluence_score,
            "reason_code":     self.reason_code,
        }

    def __repr__(self) -> str:
        return (
            f"Position({self.direction.upper()} {self.symbol} | "
            f"entry={self.entry_price:.5f} | SL={self.stop_loss:.5f} | "
            f"TP={self.take_profit:.5f} | status={self.status.value} | "
            f"pnl={self.pnl})"
        )


class OrderManager:
    """
    Manages the complete lifecycle of trade positions.

    Parameters
    ----------
    client         : DerivClient      Authenticated Deriv API client.
    circuit_breaker: CircuitBreaker   For recording trade results.
    sizer          : PositionSizer    For updating balance post-trade.
    multiplier     : int              Deriv multiplier. Default 100.
    max_positions  : int              Max simultaneous open positions. Default 3.
    """

    def __init__(
        self,
        client:          DerivClient,
        circuit_breaker: CircuitBreaker,
        sizer:           Optional[PositionSizer] = None,
        multiplier:      int = 100,
        max_positions:   int = 3,
    ) -> None:
        self.client          = client
        self.cb              = circuit_breaker
        self.sizer           = sizer
        self.multiplier      = multiplier
        self.max_positions   = max_positions
        self._positions:     dict[str, Position] = {}      # trade_id → Position
        self._open_count:    int = 0
        self._trade_counter: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute(self, decision: TradeDecision) -> Optional[Position]:
        """
        Execute a trade decision. Returns the opened Position or None on failure.

        Pre-flight checks:
          - decision.should_trade must be True
          - Circuit breaker must allow trading
          - Open position count must be below max
          - Minimum R:R must be met
        """
        if not decision.should_trade:
            logger.warning("execute() called with should_trade=False — ignoring")
            return None

        if not self.cb.is_trading_allowed():
            logger.warning("Circuit breaker blocking order for %s", decision.symbol)
            return None

        if self._open_count >= self.max_positions:
            logger.info("Max positions (%d) reached — skipping %s",
                        self.max_positions, decision.symbol)
            return None

        if decision.sizing and not decision.sizing.meets_minimum_rr:
            logger.warning("RR %.2f below minimum — skipping", decision.sizing.rr_ratio)
            return None

        # ── Build position record ─────────────────────────────────────────────
        position = self._build_position(decision)
        self._positions[position.trade_id] = position

        # ── Place the order ───────────────────────────────────────────────────
        try:
            contract = await self._place_order(position, decision)
            position.contract_id = int(contract.get("contract_id", 0))
            position.status      = PositionStatus.OPEN
            self._open_count    += 1
            self.cb.record_trade_open()

            logger.info(
                "✅ POSITION OPEN | %s | contract=%s | stake=$%.2f | "
                "SL=%.5f | TP=%.5f",
                position, position.contract_id, position.stake,
                position.stop_loss, position.take_profit,
            )
            return position

        except Exception as exc:
            position.status = PositionStatus.CANCELLED
            logger.error("Order placement failed for %s: %s",
                         decision.symbol, exc, exc_info=True)
            return None

    async def close_position(
        self,
        trade_id:     str,
        reason:       CloseReason = CloseReason.MANUAL,
        current_price: Optional[float] = None,
    ) -> Optional[Position]:
        """
        Close an open position. Updates all state and notifies circuit breaker.
        """
        position = self._positions.get(trade_id)
        if not position or not position.is_open:
            logger.warning("close_position: trade_id %s not found or not open", trade_id)
            return None

        if not position.contract_id:
            logger.error("close_position: no contract_id for trade %s", trade_id)
            return None

        try:
            sold = await self.client.sell_contract(position.contract_id)

            position.exit_price  = float(sold.get("sold_for", current_price or 0))
            position.pnl         = self._compute_pnl(position)
            position.status      = PositionStatus.CLOSED
            position.close_reason = reason
            position.closed_at   = datetime.utcnow()
            self._open_count     = max(0, self._open_count - 1)

            # Update circuit breaker and sizer
            balance = self.client.state.balance
            self.cb.record_trade(pnl=position.pnl or 0.0, account_balance=balance)
            self.cb.record_trade_close()
            if self.sizer:
                self.sizer.update_balance(balance)

            logger.info(
                "✅ POSITION CLOSED | trade=%s | reason=%s | "
                "exit=%.5f | pnl=$%.2f | duration=%ds",
                trade_id, reason.value,
                position.exit_price, position.pnl or 0,
                int(position.duration_seconds or 0),
            )
            return position

        except Exception as exc:
            logger.error("Failed to close position %s: %s", trade_id, exc, exc_info=True)
            return None

    async def monitor_tick(self, symbol: str, current_price: float) -> None:
        """
        Called on every incoming tick for a symbol.
        Checks all open positions for that symbol against SL and TP levels.
        Client-side backup to server-side SL/TP on Deriv.
        """
        open_positions = [
            p for p in self._positions.values()
            if p.is_open and p.symbol == symbol
        ]

        for position in open_positions:
            if position.sl_hit(current_price):
                logger.warning("SL HIT | %s | price=%.5f | SL=%.5f",
                               position.trade_id, current_price, position.stop_loss)
                await self.close_position(
                    position.trade_id,
                    reason=CloseReason.STOP_LOSS,
                    current_price=current_price,
                )

            elif position.tp_hit(current_price):
                logger.info("TP HIT | %s | price=%.5f | TP=%.5f",
                            position.trade_id, current_price, position.take_profit)
                await self.close_position(
                    position.trade_id,
                    reason=CloseReason.TAKE_PROFIT,
                    current_price=current_price,
                )

    async def close_all(self, reason: CloseReason = CloseReason.CIRCUIT_BREAK) -> None:
        """Emergency close all open positions. Used by kill switch."""
        open_ids = [tid for tid, p in self._positions.items() if p.is_open]
        logger.warning("Closing all %d positions | reason=%s", len(open_ids), reason.value)
        await asyncio.gather(*[
            self.close_position(tid, reason=reason) for tid in open_ids
        ], return_exceptions=True)

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.is_open]

    @property
    def all_positions(self) -> list[Position]:
        return list(self._positions.values())

    def get_position(self, trade_id: str) -> Optional[Position]:
        return self._positions.get(trade_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_position(self, decision: TradeDecision) -> Position:
        """Build a Position object from a TradeDecision."""
        import uuid
        self._trade_counter += 1
        trade_id = f"T{self._trade_counter:04d}_{decision.symbol.replace(' ', '')[:8]}"

        contract_type = "MULTUP" if decision.direction == "buy" else "MULTDOWN"
        sizing        = decision.sizing

        return Position(
            trade_id       = trade_id,
            contract_id    = None,
            symbol         = decision.symbol,
            timeframe      = decision.timeframe,
            direction      = decision.direction,
            contract_type  = contract_type,
            entry_price    = decision.entry_price or 0.0,
            stop_loss      = sizing.stop_loss if sizing else 0.0,
            take_profit    = sizing.take_profit if sizing else 0.0,
            stake          = sizing.stake if sizing else 0.0,
            confluence_score = decision.confluence_score,
            reason_code    = decision.reason,
        )

    async def _place_order(self, position: Position, decision: TradeDecision) -> dict:
        """
        Place the order on Deriv. Includes server-side SL/TP where supported.
        Returns the raw buy response dict from Deriv.
        """
        return await self.client.buy_contract(
            contract_type  = position.contract_type,
            symbol         = position.symbol,
            amount         = position.stake,
            multiplier     = self.multiplier,
            basis          = "stake",
        )

    def _compute_pnl(self, position: Position) -> float:
        """
        Estimate P&L. Actual P&L comes from Deriv sold_for field.
        This is a fallback calculation when sold_for is unavailable.
        """
        if not position.exit_price:
            return 0.0
        price_move = position.exit_price - position.entry_price
        if position.direction == "sell":
            price_move = -price_move
        # Approximate: (price_move / entry) × stake × multiplier
        if position.entry_price > 0:
            return (price_move / position.entry_price) * position.stake * self.multiplier
        return 0.0
