"""Campaign ledger and hard risk budget for linear-instrument simulation."""
from dataclasses import dataclass, field, asdict
from enum import Enum
import math

from app.core.hybrid.regime import Regime
from app.core.hybrid.risk import CampaignRiskEngine


def finite_positive(*values):
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("Expected finite positive numbers")


@dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    point_value: float  # account currency / price unit / quantity unit
    quantity_step: float
    min_quantity: float
    max_quantity: float = 1e9
    commission: float = 0.0  # per quantity, per side

    def __post_init__(self):
        finite_positive(self.point_value, self.quantity_step, self.min_quantity, self.max_quantity)
        if self.max_quantity < self.min_quantity or not math.isfinite(self.commission) or self.commission < 0:
            raise ValueError("Invalid instrument specification")

    def floor_quantity(self, value):
        finite_positive(value)
        quantity = math.floor(min(value, self.max_quantity) / self.quantity_step + 1e-10) * self.quantity_step
        return quantity if quantity >= self.min_quantity - 1e-10 else 0.0


class CampaignStatus(str, Enum):
    WAITING = "WAITING"
    PROBE = "PROBE"
    CONFIRMED = "CONFIRMED"
    PYRAMIDING = "PYRAMIDING"
    MANAGING = "MANAGING"
    RUNNER = "RUNNER"
    CLOSED = "CLOSED"
    INVALIDATED = "INVALIDATED"


class CampaignState(str, Enum):
    NO_POSITION = "NO_POSITION"
    SETUP_DETECTED = "SETUP_DETECTED"
    PROBE_ENTRY = "PROBE_ENTRY"
    CONFIRMATION = "CONFIRMATION"
    ADD_POSITION = "ADD_POSITION"
    MANAGE_POSITION = "MANAGE_POSITION"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    RUNNER = "RUNNER"
    CLOSED = "CLOSED"
    INVALIDATION = "INVALIDATION"


@dataclass
class CampaignEntry:
    event_id: str
    reason: tuple[str, ...]
    timestamp: int
    price: float
    quantity: float
    remaining: float
    stop: float
    incremental_risk: float
    total_position_risk: float
    confirmation_score: float


@dataclass(frozen=True)
class Confirmation:
    event_id: str
    timestamp: int
    direction: str
    score: float
    reasons: tuple[str, ...]
    invalidated: bool = False


CONFIRMATION_REASONS = frozenset({
    "BULLISH_DISPLACEMENT", "BEARISH_DISPLACEMENT", "BOS_CONFIRMED",
    "VWAP_RECLAIM", "VWAP_REJECTION", "SUCCESSFUL_RETEST", "NEW_HIGHER_LOW",
    "NEW_LOWER_HIGH", "LIQUIDITY_SWEEP", "CONFLUENCE_CONFIRMED",
})


@dataclass
class TradeCampaign:
    campaign_id: str
    symbol: str
    direction: str
    market_regime: Regime
    initial_signal: dict
    spec: InstrumentSpec
    equity_at_setup: float
    max_trade_risk_percent: float = 1.0  # percentage units, 1.0 means 1%
    timeframe: str = ""
    exit_slippage_pct: float = 0.0
    half_spread: float = 0.0
    entries: list[CampaignEntry] = field(default_factory=list)
    partial_exits: list[dict] = field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    initial_risk: float = 0.0
    maximum_risk_used: float = 0.0
    status: CampaignStatus = CampaignStatus.WAITING
    state: CampaignState = CampaignState.NO_POSITION
    pending_orders: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    seen_events: set[str] = field(default_factory=set)
    last_price: float = 0.0

    def __post_init__(self):
        finite_positive(self.equity_at_setup, self.max_trade_risk_percent)
        if self.direction not in ("buy", "sell") or self.symbol != self.spec.symbol or self.max_trade_risk_percent > 100:
            raise ValueError("Invalid campaign")
        if any(not math.isfinite(v) or v < 0 for v in (self.exit_slippage_pct, self.half_spread)):
            raise ValueError("Invalid exit friction")

    @property
    def sign(self):
        return 1 if self.direction == "buy" else -1

    @property
    def total_quantity(self):
        return sum(e.remaining for e in self.entries)

    @property
    def average_entry(self):
        return sum(e.price * e.remaining for e in self.entries) / self.total_quantity if self.total_quantity else 0.0

    @property
    def current_open_risk(self):
        return sum(CampaignRiskEngine.open_risk(e.price, e.stop, self.sign, e.remaining,
                   self.spec, self.exit_slippage_pct, self.half_spread) for e in self.entries)

    @property
    def risk_limit(self):
        return self.equity_at_setup * self.max_trade_risk_percent / 100

    @property
    def available_risk(self):
        return max(0, self.risk_limit - self.current_open_risk - max(0, -self.realized_pnl))

    @property
    def R_realized(self):
        return self.realized_pnl / self.initial_risk if self.initial_risk else 0.0

    @property
    def terminal(self):
        return self.status in (CampaignStatus.CLOSED, CampaignStatus.INVALIDATED)

    def mark(self, price):
        finite_positive(price)
        self.last_price = price
        self.unrealized_pnl = sum((self.sign * (price - e.price) * self.spec.point_value
                                   - self.spec.commission) * e.remaining for e in self.entries)

    def log(self, timestamp, action, price, quantity, reasons=(), score=0,
            risk_before=None, stop=None, target=None):
        self.mark(price)
        if stop is None:
            live_stops = [e.stop for e in self.entries if e.remaining]
            stop = (max(live_stops) if self.sign == 1 else min(live_stops)) if live_stops else None
        if target is None:
            target = self.initial_signal.get("target")
        if self.total_quantity:
            self.maximum_risk_used = max(self.maximum_risk_used, self.current_open_risk + max(0, -self.realized_pnl))
        event = dict(timestamp=timestamp, campaign_id=self.campaign_id, symbol=self.symbol,
                     timeframe=self.timeframe, regime=self.market_regime.value, action=action,
                     price=price, quantity=quantity, average_position_price=self.average_entry,
                     stop=stop, target=target, confluence_score=score, reason_codes=list(reasons),
                     risk_before=self.current_open_risk if risk_before is None else risk_before,
                     risk_after=self.current_open_risk, realized_pnl=self.realized_pnl,
                     unrealized_pnl=self.unrealized_pnl, R_multiple=self.R_realized,
                     state=self.state.value, status=self.status.value)
        self.events.append(event)
        return event

    def reject(self, timestamp, price, reason, score=0):
        self.log(timestamp, "REJECT", price, 0, (reason,), score)
        return False

    def setup(self, timestamp, price):
        if self.state != CampaignState.NO_POSITION:
            return False
        self.state = CampaignState.SETUP_DETECTED
        self.log(timestamp, "SETUP", price, 0, tuple(self.initial_signal.get("reasons", ())))
        return True

    def open_probe(self, event_id, timestamp, price, stop, risk_fraction=0.25, score=0, reasons=()):
        if self.entries or self.state != CampaignState.SETUP_DETECTED or self.terminal:
            return self.reject(timestamp, price, "PROBE_STATE_INVALID")
        return self._entry(event_id, timestamp, price, stop, risk_fraction, score, reasons, False)

    def _entry(self, event_id, timestamp, price, stop, risk_fraction, score, reasons, adding):
        finite_positive(price, stop, risk_fraction)
        if risk_fraction > 1 or not math.isfinite(score):
            raise ValueError("Invalid entry configuration")
        if event_id in self.seen_events:
            return self.reject(timestamp, price, "DUPLICATE_EVENT", score)
        if self.sign * (price - stop) <= 0:
            return self.reject(timestamp, price, "INVALID_STOP", score)
        unit_risk = CampaignRiskEngine.entry_unit_risk(price, stop, self.spec, self.exit_slippage_pct, self.half_spread)
        requested_risk = self.risk_limit * risk_fraction
        if requested_risk > self.available_risk + 1e-9:
            return self.reject(timestamp, price, "CAMPAIGN_RISK_LIMIT", score)
        quantity = self.spec.floor_quantity(requested_risk / unit_risk)
        if quantity <= 0:
            return self.reject(timestamp, price, "BELOW_MINIMUM_QUANTITY", score)
        incremental = quantity * unit_risk
        if not CampaignRiskEngine.permits(self.current_open_risk, incremental, self.realized_pnl, self.risk_limit):
            return self.reject(timestamp, price, "CAMPAIGN_RISK_LIMIT", score)
        before = self.current_open_risk
        self.realized_pnl -= quantity * self.spec.commission
        entry = CampaignEntry(event_id, tuple(reasons), timestamp, price, quantity, quantity,
                              stop, incremental, 0, score)
        self.entries.append(entry)
        entry.total_position_risk = self.current_open_risk
        self.seen_events.add(event_id)
        if not adding:
            self.initial_risk = incremental
        self.status = CampaignStatus.PYRAMIDING if adding else CampaignStatus.PROBE
        self.state = CampaignState.ADD_POSITION if adding else CampaignState.PROBE_ENTRY
        self.log(timestamp, "ADD" if adding else "PROBE", price, quantity,
                 tuple(reasons) + (f"SCALE_IN_{len(self.entries)}",), score, before, stop)
        self.state = CampaignState.MANAGE_POSITION
        return True

    def add(self, confirmation: Confirmation, timestamp, price, stop, risk_fraction=.25,
            threshold=6, max_tranches=4):
        if (self.terminal or not self.entries or self.partial_exits
                or len(self.entries) >= max_tranches):
            return self.reject(timestamp, price, "ADD_STATE_INVALID")
        if confirmation.event_id in self.seen_events:
            return self.reject(timestamp, price, "DUPLICATE_EVENT", confirmation.score)
        if (confirmation.invalidated or confirmation.direction != self.direction
                or not math.isfinite(confirmation.score) or confirmation.score < threshold
                or not math.isfinite(confirmation.timestamp)
                or not set(confirmation.reasons) & CONFIRMATION_REASONS
                or confirmation.timestamp <= self.entries[-1].timestamp
                or confirmation.timestamp > timestamp):
            return self.reject(timestamp, price, "CONFIRMATION_REQUIRED", confirmation.score)
        # No averaging down, even if aggregate P&L is positive after an earlier partial exit.
        if (self.sign * (price - self.average_entry) <= 0
                or self.sign * (price - self.entries[-1].price) <= 0
                or any(self.sign * (price - e.stop) <= 0 for e in self.entries if e.remaining)):
            return self.reject(timestamp, price, "AVERAGING_DOWN_OR_INVALIDATED", confirmation.score)
        if any(self.sign * (stop - e.stop) < -1e-10 for e in self.entries if e.remaining):
            return self.reject(timestamp, price, "ADD_STOP_LOOSENS_STRUCTURE", confirmation.score)
        # Confirm only when the subsequent risk/quantity checks can accept the add.
        prior_status, prior_state = self.status, self.state
        self.status, self.state = CampaignStatus.CONFIRMED, CampaignState.CONFIRMATION
        self.log(timestamp, "CONFIRMATION", price, 0, confirmation.reasons, confirmation.score, stop=stop)
        accepted = self._entry(confirmation.event_id, timestamp, price, stop, risk_fraction,
                               confirmation.score, confirmation.reasons, True)
        if not accepted:
            self.status, self.state = prior_status, prior_state
        else:
            # Campaign stops are shared; an accepted add can only tighten older tranches.
            self.move_stop(timestamp, price, stop)
        return accepted

    def move_stop(self, timestamp, price, stop, reason="STRUCTURE_TRAIL"):
        finite_positive(price, stop)
        if self.terminal or not self.total_quantity:
            return False
        if reason not in {"STRUCTURE_TRAIL", "ATR_TRAIL", "EMA_TRAIL", "VWAP_TRAIL", "VWMA_TRAIL"}:
            return self.reject(timestamp, price, "STOP_RULE_REQUIRED")
        live = [e for e in self.entries if e.remaining]
        if self.sign * (price - stop) <= 0 or any(self.sign * (stop - e.stop) < -1e-10 for e in live):
            return self.reject(timestamp, price, "STOP_CANNOT_LOOSEN_OR_CROSS_PRICE")
        if all(abs(e.stop - stop) < 1e-10 for e in live):
            return False
        before = self.current_open_risk
        proposed_risk = sum(CampaignRiskEngine.open_risk(e.price, stop, self.sign, e.remaining,
                            self.spec, self.exit_slippage_pct, self.half_spread) for e in live)
        if proposed_risk > before + 1e-9:
            return self.reject(timestamp, price, "STOP_CANNOT_INCREASE_RISK")
        for e in live:
            e.stop = stop
        self.log(timestamp, "TRAIL", price, self.total_quantity, (reason,), risk_before=before, stop=stop)
        return True

    def partial_exit(self, event_id, timestamp, price, quantity, reason="TP1", target=None):
        finite_positive(price, quantity)
        if self.terminal or not self.total_quantity:
            return False
        if event_id in self.seen_events:
            return self.reject(timestamp, price, "DUPLICATE_EXIT")
        if quantity > self.total_quantity + 1e-9:
            return self.reject(timestamp, price, "EXIT_EXCEEDS_POSITION")
        if quantity < self.total_quantity - 1e-9:
            quantity = math.floor(quantity / self.spec.quantity_step + 1e-10) * self.spec.quantity_step
            if quantity < self.spec.min_quantity - 1e-10 or self.total_quantity - quantity < self.spec.min_quantity - 1e-10:
                return self.reject(timestamp, price, "PARTIAL_BELOW_MINIMUM_QUANTITY")
        before = self.current_open_risk
        remaining, pnl = quantity, 0.0
        closing_all = abs(quantity - self.total_quantity) <= 1e-9
        # FIFO maintains a deterministic cost basis for the remaining tranches.
        for entry in self.entries:
            closed = entry.remaining if closing_all else min(entry.remaining, max(0, remaining))
            pnl += (self.sign * (price - entry.price) * self.spec.point_value - self.spec.commission) * closed
            entry.remaining = 0.0 if closing_all else max(0, entry.remaining - closed)
            remaining -= closed
        self.realized_pnl += pnl
        self.seen_events.add(event_id)
        self.partial_exits.append(dict(event_id=event_id, timestamp=timestamp, price=price,
                                       quantity=quantity, realized_pnl=pnl, reason=reason, target=target))
        self.state = CampaignState.PARTIAL_EXIT
        self.status = CampaignStatus.MANAGING
        self.log(timestamp, "PARTIAL_EXIT", price, quantity, (reason,), risk_before=before, target=target)
        if self.total_quantity <= 1e-9:
            self.pending_orders.clear()
            self.state, self.status = CampaignState.CLOSED, CampaignStatus.CLOSED
            self.log(timestamp, "CLOSED", price, 0, (reason,))
        else:
            self.state = CampaignState.MANAGE_POSITION
        return True

    def start_runner(self, timestamp, price):
        if self.terminal or not self.total_quantity or self.status == CampaignStatus.RUNNER:
            return False
        self.state, self.status = CampaignState.RUNNER, CampaignStatus.RUNNER
        self.log(timestamp, "RUNNER", price, self.total_quantity, ("RUNNER",))
        return True

    def close(self, event_id, timestamp, price, reason="EXIT"):
        if self.terminal:
            return False
        cancelled = list(self.pending_orders)
        self.pending_orders.clear()
        if cancelled:
            self.log(timestamp, "CANCEL", price, 0, tuple(cancelled))
        if self.total_quantity:
            return self.partial_exit(event_id, timestamp, price, self.total_quantity, reason)
        self.state, self.status = CampaignState.CLOSED, CampaignStatus.CLOSED
        self.log(timestamp, "CLOSED", price, 0, (reason,))
        return True

    def invalidate(self, timestamp, price, reason="INVALIDATION"):
        if self.terminal:
            return False
        self.state = CampaignState.INVALIDATION
        self.log(timestamp, "INVALIDATION", price, self.total_quantity, (reason,))
        self.close(f"INVALIDATION:{timestamp}", timestamp, price, reason)
        self.state, self.status = CampaignState.INVALIDATION, CampaignStatus.INVALIDATED
        self.log(timestamp, "INVALIDATED", price, 0, (reason,))
        return True

    def to_dict(self):
        return dict(campaign_id=self.campaign_id, symbol=self.symbol, direction=self.direction,
                    market_regime=self.market_regime.value, initial_signal=self.initial_signal,
                    entries=[asdict(e) for e in self.entries], partial_exits=self.partial_exits,
                    average_entry=self.average_entry, total_quantity=self.total_quantity,
                    realized_pnl=self.realized_pnl, unrealized_pnl=self.unrealized_pnl,
                    initial_risk=self.initial_risk, current_open_risk=self.current_open_risk,
                    equity_at_setup=self.equity_at_setup,
                    maximum_risk_used=self.maximum_risk_used, risk_limit=self.risk_limit,
                    R_realized=self.R_realized, status=self.status.value, state=self.state.value,
                    events=self.events, pending_orders=self.pending_orders)
