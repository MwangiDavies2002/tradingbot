"""
drawdown_monitor.py
────────────────────────────────────────────────────────────────────────────────
Drawdown Monitor — Real-Time Equity & Drawdown Tracking
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Tracks account equity in real-time, computes rolling drawdown metrics,
    and maintains a high-water mark to measure peak-to-trough drawdowns.
    Works alongside the CircuitBreaker — the monitor measures, the CB acts.

    METRICS TRACKED:
        High-water mark      Peak equity ever reached this session
        Current drawdown     (HWM - current) / HWM  as a percentage
        Max drawdown         Worst drawdown seen this session
        Daily drawdown       (day_start - current) / day_start
        Weekly drawdown      (week_start - current) / week_start
        Drawdown duration    How many minutes in the current drawdown

    EQUITY CURVE:
        Stores a rolling window of (timestamp, balance) points.
        Used by the dashboard equity chart and performance reports.

    RECOVERY FACTOR:
        total_pnl / max_drawdown_amount — measures return vs worst loss.
        Recovery factor > 2.0 = good risk-adjusted returns.

USAGE:
    monitor = DrawdownMonitor(initial_balance=500.0)
    monitor.update(balance=485.0)   # call after every balance change
    print(monitor.status())
    print(monitor.current_drawdown_pct)   # 0.03 = 3%
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class EquityPoint:
    """One point on the equity curve."""
    ts:      datetime
    balance: float
    note:    str = ""


@dataclass
class DrawdownSnapshot:
    """Complete drawdown state at a point in time."""
    current_balance:        float
    high_water_mark:        float
    session_start_balance:  float
    day_start_balance:      float
    week_start_balance:     float

    current_drawdown_pct:   float   # (HWM - current) / HWM
    daily_drawdown_pct:     float   # (day_start - current) / day_start
    weekly_drawdown_pct:    float   # (week_start - current) / week_start
    max_drawdown_pct:       float   # Worst seen this session
    max_drawdown_amount:    float   # Dollar amount of worst drawdown

    drawdown_duration_mins: float   # Minutes since drawdown started
    in_drawdown:            bool    # True if below HWM
    recovery_factor:        float   # total_pnl / max_drawdown_amount

    total_pnl:              float
    total_pnl_pct:          float
    equity_points:          int     # Points in the equity curve

    timestamp:              datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "current_balance":        round(self.current_balance, 2),
            "high_water_mark":        round(self.high_water_mark, 2),
            "current_drawdown_pct":   round(self.current_drawdown_pct * 100, 2),
            "daily_drawdown_pct":     round(self.daily_drawdown_pct * 100, 2),
            "weekly_drawdown_pct":    round(self.weekly_drawdown_pct * 100, 2),
            "max_drawdown_pct":       round(self.max_drawdown_pct * 100, 2),
            "max_drawdown_amount":    round(self.max_drawdown_amount, 2),
            "drawdown_duration_mins": round(self.drawdown_duration_mins, 1),
            "in_drawdown":            self.in_drawdown,
            "recovery_factor":        round(self.recovery_factor, 3),
            "total_pnl":              round(self.total_pnl, 2),
            "total_pnl_pct":          round(self.total_pnl_pct * 100, 2),
            "timestamp":              self.timestamp.isoformat(),
        }


class DrawdownMonitor:
    """
    Real-time equity and drawdown monitor.

    Parameters
    ----------
    initial_balance  : float  Starting account balance.
    curve_max_points : int    Max equity curve points to keep in memory.
                              Default 1000 (~16 hours of 1-min snapshots).
    """

    def __init__(
        self,
        initial_balance:  float = 0.0,
        curve_max_points: int   = 1000,
    ) -> None:
        now = datetime.now(tz=timezone.utc)

        self._session_start  = initial_balance
        self._day_start      = initial_balance
        self._week_start     = initial_balance
        self._current        = initial_balance
        self._hwm            = initial_balance          # High-water mark
        self._max_dd_pct     = 0.0
        self._max_dd_amount  = 0.0
        self._dd_start_time: Optional[datetime] = None  # When current DD began
        self._day_reset_at   = now
        self._week_reset_at  = now
        self._curve: deque[EquityPoint] = deque(maxlen=curve_max_points)

        if initial_balance > 0:
            self._curve.append(EquityPoint(ts=now, balance=initial_balance, note="init"))

        logger.info("DrawdownMonitor initialised | balance=$%.2f", initial_balance)

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, balance: float, note: str = "") -> DrawdownSnapshot:
        """
        Update with the latest account balance.
        Call after every trade close and on the balance subscription callback.
        Returns a full DrawdownSnapshot with all current metrics.
        """
        self._check_day_week_reset(balance)
        self._current = balance

        now = datetime.now(tz=timezone.utc)
        self._curve.append(EquityPoint(ts=now, balance=balance, note=note))

        # Update high-water mark
        if balance > self._hwm:
            self._hwm           = balance
            self._dd_start_time = None    # Reset DD duration tracker on new HWM

        # Current drawdown from HWM
        curr_dd_pct    = max((self._hwm - balance) / self._hwm, 0.0) if self._hwm > 0 else 0.0
        curr_dd_amount = max(self._hwm - balance, 0.0)

        # Track drawdown start time
        if curr_dd_pct > 0 and self._dd_start_time is None:
            self._dd_start_time = now
        elif curr_dd_pct == 0:
            self._dd_start_time = None

        # Update max drawdown
        if curr_dd_pct > self._max_dd_pct:
            self._max_dd_pct    = curr_dd_pct
            self._max_dd_amount = curr_dd_amount
            logger.info("New max drawdown: %.2f%% ($%.2f)", curr_dd_pct * 100, curr_dd_amount)

        dd_duration = 0.0
        if self._dd_start_time:
            dd_duration = (now - self._dd_start_time).total_seconds() / 60

        daily_dd  = max((self._day_start  - balance) / max(self._day_start,  1), 0.0)
        weekly_dd = max((self._week_start - balance) / max(self._week_start, 1), 0.0)
        total_pnl = balance - self._session_start
        total_pnl_pct = total_pnl / self._session_start if self._session_start > 0 else 0.0
        recovery  = (total_pnl / self._max_dd_amount
                     if self._max_dd_amount > 0 else 0.0)

        snap = DrawdownSnapshot(
            current_balance        = balance,
            high_water_mark        = self._hwm,
            session_start_balance  = self._session_start,
            day_start_balance      = self._day_start,
            week_start_balance     = self._week_start,
            current_drawdown_pct   = curr_dd_pct,
            daily_drawdown_pct     = daily_dd,
            weekly_drawdown_pct    = weekly_dd,
            max_drawdown_pct       = self._max_dd_pct,
            max_drawdown_amount    = self._max_dd_amount,
            drawdown_duration_mins = dd_duration,
            in_drawdown            = curr_dd_pct > 0,
            recovery_factor        = recovery,
            total_pnl              = total_pnl,
            total_pnl_pct          = total_pnl_pct,
            equity_points          = len(self._curve),
        )

        if daily_dd > 0.03:   # Warn at 3% daily DD
            logger.warning("Daily drawdown at %.1f%%", daily_dd * 100)

        return snap

    def reset_day(self, balance: float) -> None:
        """Call at the start of a new trading day."""
        self._day_start   = balance
        self._day_reset_at = datetime.now(tz=timezone.utc)
        logger.info("Day reset | new day_start=$%.2f", balance)

    def reset_week(self, balance: float) -> None:
        """Call at the start of a new trading week."""
        self._week_start   = balance
        self._week_reset_at = datetime.now(tz=timezone.utc)
        logger.info("Week reset | new week_start=$%.2f", balance)

    def equity_curve(self, last_n: int = 200) -> list[dict]:
        """Return the last N equity curve points as a list of dicts."""
        points = list(self._curve)[-last_n:]
        return [{"ts": p.ts.isoformat(), "balance": p.balance} for p in points]

    def status(self) -> str:
        """One-line status string for logging."""
        curr_dd = max((self._hwm - self._current) / self._hwm * 100, 0) if self._hwm > 0 else 0
        return (
            f"Equity=${self._current:.2f} | "
            f"HWM=${self._hwm:.2f} | "
            f"DD={curr_dd:.1f}% | "
            f"MaxDD={self._max_dd_pct*100:.1f}% | "
            f"PnL=${self._current - self._session_start:+.2f}"
        )

    @property
    def current_drawdown_pct(self) -> float:
        return max((self._hwm - self._current) / self._hwm, 0.0) if self._hwm > 0 else 0.0

    @property
    def max_drawdown_pct(self) -> float:
        return self._max_dd_pct

    @property
    def current_balance(self) -> float:
        return self._current

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_day_week_reset(self, balance: float) -> None:
        now = datetime.now(tz=timezone.utc)
        if now.date() > self._day_reset_at.date():
            self.reset_day(balance)
        days_since_week = (now.date() - self._week_reset_at.date()).days
        if days_since_week >= 7:
            self.reset_week(balance)
