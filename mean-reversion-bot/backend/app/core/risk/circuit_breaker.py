"""
circuit_breaker.py
────────────────────────────────────────────────────────────────────────────────
Circuit Breaker — Automated Trading Halt System
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    The circuit breaker is the last line of defence. It monitors live trading
    conditions and automatically halts the bot when predefined loss thresholds
    are hit. This protects the account from runaway losses during system
    failures, unexpected market conditions, or strategy breakdown.

    TRIGGERS (any one halts trading):
    ┌─────────────────────────────────┬──────────────────────┬──────────────┐
    │ Trigger                         │ Default Threshold    │ Pause Length │
    ├─────────────────────────────────┼──────────────────────┼──────────────┤
    │ Consecutive losses              │ 3 in a row           │ 4 hours      │
    │ Daily drawdown                  │ 5% of equity         │ Rest of day  │
    │ Weekly drawdown                 │ 10% of equity        │ Rest of week │
    │ Single trade loss               │ 3% of equity         │ 1 hour       │
    │ Max open positions              │ 3 simultaneous       │ Until closed │
    │ API error streak                │ 5 consecutive errors │ 30 minutes   │
    └─────────────────────────────────┴──────────────────────┴──────────────┘

    STATES:
        ACTIVE       → Bot is running normally
        PAUSED       → Temporarily halted, auto-resumes after pause_until time
        HALTED       → Hard stop, requires manual reset (weekly loss hit)
        COOLDOWN     → Reduced activity after a soft trigger

    The circuit breaker is the ONLY component that can override all other
    signals. A HALTED or PAUSED state means NO orders are placed regardless
    of signal quality.

USAGE:
    from app.core.risk.circuit_breaker import CircuitBreaker, BreakerState

    cb = CircuitBreaker(
        max_consecutive_losses=3,
        daily_drawdown_pct=0.05,
        weekly_drawdown_pct=0.10,
    )

    # After every trade close:
    cb.record_trade(pnl=-25.0, account_balance=475.0)

    # Before placing any order:
    if not cb.is_trading_allowed():
        return   # Do not place order

    print(cb.status())
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class BreakerState(str, Enum):
    ACTIVE   = "active"
    PAUSED   = "paused"
    HALTED   = "halted"
    COOLDOWN = "cooldown"


@dataclass
class BreakerEvent:
    """Record of a circuit breaker trigger event."""
    trigger:     str
    state:       BreakerState
    triggered_at: datetime
    pause_until:  Optional[datetime]
    details:      str


@dataclass
class CircuitBreakerStatus:
    state:               BreakerState
    is_trading_allowed:  bool
    consecutive_losses:  int
    daily_pnl:           float
    weekly_pnl:          float
    daily_drawdown_pct:  float
    weekly_drawdown_pct: float
    open_positions:      int
    api_error_streak:    int
    pause_until:         Optional[datetime]
    last_trigger:        Optional[str]
    session_start_balance: float
    current_balance:     float

    def to_dict(self) -> dict:
        return {
            "state":               self.state.value,
            "is_trading_allowed":  self.is_trading_allowed,
            "consecutive_losses":  self.consecutive_losses,
            "daily_pnl":           round(self.daily_pnl, 4),
            "weekly_pnl":          round(self.weekly_pnl, 4),
            "daily_drawdown_pct":  round(self.daily_drawdown_pct * 100, 2),
            "weekly_drawdown_pct": round(self.weekly_drawdown_pct * 100, 2),
            "open_positions":      self.open_positions,
            "api_error_streak":    self.api_error_streak,
            "pause_until":         self.pause_until.isoformat() if self.pause_until else None,
            "last_trigger":        self.last_trigger,
        }


class CircuitBreaker:
    """
    Automated trading halt system with multiple trigger layers.

    All state is held in memory. For persistence across restarts,
    persist cb.get_status().to_dict() to Redis on every state change.

    Parameters
    ----------
    max_consecutive_losses : int    Losses in a row before pause. Default 3.
    daily_drawdown_pct     : float  Daily loss limit. Default 0.05 (5%).
    weekly_drawdown_pct    : float  Weekly loss limit. Default 0.10 (10%).
    single_trade_loss_pct  : float  Single trade loss limit. Default 0.03 (3%).
    max_open_positions     : int    Max simultaneous trades. Default 3.
    max_api_error_streak   : int    API errors before pause. Default 5.
    pause_hours_losses     : float  Pause after consecutive losses. Default 4.
    pause_hours_api        : float  Pause after API error streak. Default 0.5.
    cooldown_hours         : float  Cooldown after daily limit. Default 24.
    """

    def __init__(
        self,
        max_consecutive_losses: int   = 3,
        daily_drawdown_pct:     float = 0.05,
        weekly_drawdown_pct:    float = 0.10,
        single_trade_loss_pct:  float = 0.03,
        max_open_positions:     int   = 3,
        max_api_error_streak:   int   = 5,
        pause_hours_losses:     float = 4.0,
        pause_hours_api:        float = 0.5,
        cooldown_hours:         float = 24.0,
    ) -> None:
        self.max_consecutive_losses = max_consecutive_losses
        self.daily_drawdown_pct     = daily_drawdown_pct
        self.weekly_drawdown_pct    = weekly_drawdown_pct
        self.single_trade_loss_pct  = single_trade_loss_pct
        self.max_open_positions     = max_open_positions
        self.max_api_error_streak   = max_api_error_streak
        self.pause_hours_losses     = pause_hours_losses
        self.pause_hours_api        = pause_hours_api
        self.cooldown_hours         = cooldown_hours

        # ── Runtime state ─────────────────────────────────────────────────────
        self._state:               BreakerState      = BreakerState.ACTIVE
        self._pause_until:         Optional[datetime] = None
        self._last_trigger:        Optional[str]      = None
        self._consecutive_losses:  int                = 0
        self._open_positions:      int                = 0
        self._api_error_streak:    int                = 0
        self._events:              list[BreakerEvent] = []

        # ── Balance tracking ──────────────────────────────────────────────────
        self._session_start_balance: float = 0.0
        self._week_start_balance:    float = 0.0
        self._day_start_balance:     float = 0.0
        self._current_balance:       float = 0.0
        self._day_reset_at:          Optional[datetime] = None
        self._week_reset_at:         Optional[datetime] = None

        logger.info(
            "CircuitBreaker init | max_losses=%d | daily=%.0f%% | weekly=%.0f%%",
            max_consecutive_losses,
            daily_drawdown_pct * 100,
            weekly_drawdown_pct * 100,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def initialise(self, account_balance: float) -> None:
        """Call once on bot startup with the current account balance."""
        now = datetime.now(tz=timezone.utc)
        self._current_balance      = account_balance
        self._session_start_balance = account_balance
        self._day_start_balance    = account_balance
        self._week_start_balance   = account_balance
        self._day_reset_at         = now
        self._week_reset_at        = now
        logger.info("CircuitBreaker initialised | balance=$%.2f", account_balance)

    def is_trading_allowed(self) -> bool:
        """
        The single check before placing ANY order.
        Returns True only if the bot is ACTIVE and no pause/halt is in effect.
        """
        self._check_auto_resume()

        if self._state == BreakerState.HALTED:
            logger.warning("CB: HALTED — trading blocked | trigger: %s", self._last_trigger)
            return False

        if self._state == BreakerState.PAUSED:
            logger.info("CB: PAUSED until %s", self._pause_until)
            return False

        if self._open_positions >= self.max_open_positions:
            logger.info("CB: Max open positions reached (%d)", self._open_positions)
            return False

        return True

    def record_trade(self, pnl: float, account_balance: float) -> None:
        """
        Call after every trade closes.
        pnl = profit/loss in USD (negative = loss).
        """
        self._check_day_week_reset(account_balance)
        self._current_balance = account_balance

        if pnl < 0:
            self._consecutive_losses += 1
            logger.info("CB: Loss #%d | PnL=$%.2f | balance=$%.2f",
                        self._consecutive_losses, pnl, account_balance)
        else:
            self._consecutive_losses = 0
            logger.debug("CB: Win | PnL=$%.2f | streak reset", pnl)

        self._evaluate_triggers(pnl, account_balance)

    def record_trade_open(self) -> None:
        """Call when a new position is opened."""
        self._open_positions += 1
        logger.debug("CB: position opened | open=%d", self._open_positions)

    def record_trade_close(self) -> None:
        """Call when a position is closed."""
        self._open_positions = max(0, self._open_positions - 1)
        logger.debug("CB: position closed | open=%d", self._open_positions)

    def record_api_error(self) -> None:
        """Call on each consecutive API error."""
        self._api_error_streak += 1
        logger.warning("CB: API error streak=%d", self._api_error_streak)
        if self._api_error_streak >= self.max_api_error_streak:
            self._trigger_pause(
                trigger="api_error_streak",
                hours=self.pause_hours_api,
                details=f"{self._api_error_streak} consecutive API errors",
            )

    def record_api_success(self) -> None:
        """Reset API error streak on successful call."""
        self._api_error_streak = 0

    def manual_reset(self) -> None:
        """
        Manual reset — call from dashboard kill switch or admin command.
        Clears HALTED and PAUSED states. Requires conscious human action.
        """
        logger.warning("CB: Manual reset by operator")
        self._state        = BreakerState.ACTIVE
        self._pause_until  = None
        self._last_trigger = None
        self._consecutive_losses = 0
        self._api_error_streak   = 0

    def get_status(self) -> CircuitBreakerStatus:
        """Return full status snapshot for dashboard/logging."""
        daily_dd  = self._daily_drawdown()
        weekly_dd = self._weekly_drawdown()
        return CircuitBreakerStatus(
            state               = self._state,
            is_trading_allowed  = self.is_trading_allowed(),
            consecutive_losses  = self._consecutive_losses,
            daily_pnl           = self._current_balance - self._day_start_balance,
            weekly_pnl          = self._current_balance - self._week_start_balance,
            daily_drawdown_pct  = daily_dd,
            weekly_drawdown_pct = weekly_dd,
            open_positions      = self._open_positions,
            api_error_streak    = self._api_error_streak,
            pause_until         = self._pause_until,
            last_trigger        = self._last_trigger,
            session_start_balance = self._session_start_balance,
            current_balance     = self._current_balance,
        )

    def status(self) -> str:
        """One-line human-readable status."""
        s = self.get_status()
        return (
            f"CB[{s.state.value.upper()}] | "
            f"losses={s.consecutive_losses} | "
            f"daily_dd={s.daily_drawdown_pct*100:.1f}% | "
            f"weekly_dd={s.weekly_drawdown_pct*100:.1f}% | "
            f"open={s.open_positions}"
        )

    # ── Internal: Trigger Evaluation ──────────────────────────────────────────

    def _evaluate_triggers(self, last_pnl: float, balance: float) -> None:
        """Check all triggers after each trade. Apply most severe matching trigger."""
        if self._state == BreakerState.HALTED:
            return   # Already halted — don't re-evaluate

        # 1. Single trade loss too large
        loss_pct = abs(last_pnl) / max(self._session_start_balance, 1.0)
        if last_pnl < 0 and loss_pct >= self.single_trade_loss_pct:
            self._trigger_pause(
                trigger="single_trade_loss",
                hours=1.0,
                details=f"Single trade loss {loss_pct*100:.1f}% ≥ {self.single_trade_loss_pct*100:.0f}%",
            )
            return

        # 2. Consecutive losses
        if self._consecutive_losses >= self.max_consecutive_losses:
            self._trigger_pause(
                trigger="consecutive_losses",
                hours=self.pause_hours_losses,
                details=f"{self._consecutive_losses} consecutive losses",
            )
            return

        # 3. Daily drawdown limit
        daily_dd = self._daily_drawdown()
        if daily_dd >= self.daily_drawdown_pct:
            self._trigger_pause(
                trigger="daily_drawdown",
                hours=self.cooldown_hours,
                details=f"Daily drawdown {daily_dd*100:.1f}% ≥ {self.daily_drawdown_pct*100:.0f}%",
            )
            return

        # 4. Weekly drawdown limit (HALT — requires manual reset)
        weekly_dd = self._weekly_drawdown()
        if weekly_dd >= self.weekly_drawdown_pct:
            self._trigger_halt(
                trigger="weekly_drawdown",
                details=f"Weekly drawdown {weekly_dd*100:.1f}% ≥ {self.weekly_drawdown_pct*100:.0f}%",
            )

    def _trigger_pause(self, trigger: str, hours: float, details: str) -> None:
        now         = datetime.now(tz=timezone.utc)
        pause_until = now + timedelta(hours=hours)
        self._state        = BreakerState.PAUSED
        self._pause_until  = pause_until
        self._last_trigger = trigger
        event = BreakerEvent(
            trigger=trigger, state=BreakerState.PAUSED,
            triggered_at=now, pause_until=pause_until, details=details,
        )
        self._events.append(event)
        logger.warning("🔴 CB PAUSED | trigger=%s | until=%s | %s",
                       trigger, pause_until.strftime("%H:%M UTC"), details)

    def _trigger_halt(self, trigger: str, details: str) -> None:
        now = datetime.now(tz=timezone.utc)
        self._state        = BreakerState.HALTED
        self._pause_until  = None
        self._last_trigger = trigger
        event = BreakerEvent(
            trigger=trigger, state=BreakerState.HALTED,
            triggered_at=now, pause_until=None, details=details,
        )
        self._events.append(event)
        logger.critical("🛑 CB HALTED | trigger=%s | %s | MANUAL RESET REQUIRED",
                        trigger, details)

    def _check_auto_resume(self) -> None:
        """Auto-resume from PAUSED state once pause_until has passed."""
        if self._state == BreakerState.PAUSED and self._pause_until:
            now = datetime.now(tz=timezone.utc)
            if now >= self._pause_until:
                self._state       = BreakerState.ACTIVE
                self._pause_until = None
                self._consecutive_losses = 0
                logger.info("✅ CB auto-resumed | state=ACTIVE")

    def _check_day_week_reset(self, balance: float) -> None:
        """Reset daily/weekly tracking at UTC midnight / week start."""
        now = datetime.now(tz=timezone.utc)

        if self._day_reset_at:
            if now.date() > self._day_reset_at.date():
                self._day_start_balance = balance
                self._day_reset_at      = now
                self._consecutive_losses = 0   # Reset on new day
                logger.info("CB: New day | day_start_balance=$%.2f", balance)

        if self._week_reset_at:
            days_since = (now.date() - self._week_reset_at.date()).days
            if days_since >= 7:
                self._week_start_balance = balance
                self._week_reset_at      = now
                logger.info("CB: New week | week_start_balance=$%.2f", balance)

    def _daily_drawdown(self) -> float:
        if self._day_start_balance <= 0:
            return 0.0
        loss = self._day_start_balance - self._current_balance
        return max(loss / self._day_start_balance, 0.0)

    def _weekly_drawdown(self) -> float:
        if self._week_start_balance <= 0:
            return 0.0
        loss = self._week_start_balance - self._current_balance
        return max(loss / self._week_start_balance, 0.0)
