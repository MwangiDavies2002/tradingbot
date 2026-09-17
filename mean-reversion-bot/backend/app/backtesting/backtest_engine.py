"""
backtest_engine.py
────────────────────────────────────────────────────────────────────────────────
Backtest Engine — Historical Strategy Validation
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Runs the complete signal engine against historical OHLCV data and
    produces a full performance report. Identical logic to live trading —
    the same SignalEngine, ConfluenceScorer, PositionSizer, and CircuitBreaker
    are used, just fed historical candles instead of live ones.

    WHAT GETS TESTED:
        - Every candle in the date range is fed to the signal engine
        - Valid trade signals open virtual positions
        - SL/TP hits are detected on subsequent candles (bar-by-bar)
        - Circuit breaker triggers exactly as in live trading
        - Full trade log, equity curve, and performance metrics produced

    SLIPPAGE & SPREAD:
        slippage_pct:  Applied to entry and exit prices (default 0.0005 = 0.05%)
        spread_pips:   Fixed spread added to entry cost (default 0.0)
        These make backtest results conservative / realistic.

    PERFORMANCE METRICS:
        total_trades, win_rate, profit_factor, sharpe_ratio,
        max_drawdown, avg_rr, total_pnl, total_pnl_pct,
        avg_trade_duration_mins, best_trade, worst_trade,
        consecutive_wins, consecutive_losses

    WALK-FORWARD VALIDATION (basic):
        Call run_walk_forward(candles, n_splits=5) to split the data into
        in-sample / out-of-sample folds and measure strategy stability.

USAGE:
    engine  = SignalEngine(config)
    bt      = BacktestEngine(signal_engine=engine, initial_balance=1000.0)
    report  = bt.run(candles, symbol="R_75", timeframe="M5")
    print(report.summary())
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from dataclasses import asdict
import hashlib
import json
import math
from typing import Optional

import numpy as np

from app.core.engine.signal_engine import SignalEngine, TradeDecision
from app.core.lsl.lsl_detector import Candle, InstrumentType
from app.core.risk.circuit_breaker import CircuitBreaker
from app.core.risk.drawdown_monitor import DrawdownMonitor
from app.data.validation import validate_candles

logger = logging.getLogger(__name__)


# ─── Backtest Trade ───────────────────────────────────────────────────────────

@dataclass
class BTTrade:
    """One simulated trade in a backtest."""
    trade_id:      str
    symbol:        str
    direction:     str
    entry_price:   float
    stop_loss:     float
    take_profit:   float
    stake:         float
    entry_bar:     int           # Index of entry candle
    exit_bar:      Optional[int] = None
    exit_price:    Optional[float] = None
    pnl:           Optional[float] = None
    close_reason:  str = ""
    confluence_score: int = 0
    reason_code:   str = ""
    entry_ts:      Optional[int] = None
    exit_ts:       Optional[int] = None
    regime: str = "unknown"

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    @property
    def won(self) -> bool:
        return (self.pnl or 0) > 0

    @property
    def duration_bars(self) -> Optional[int]:
        if self.exit_bar is not None:
            return self.exit_bar - self.entry_bar
        return None


# ─── Backtest Report ──────────────────────────────────────────────────────────

@dataclass
class BacktestReport:
    symbol:          str
    timeframe:       str
    initial_balance: float
    final_balance:   float
    date_from:       Optional[datetime]
    date_to:         Optional[datetime]

    trades:          list[BTTrade] = field(default_factory=list)
    equity_curve:    list[dict]    = field(default_factory=list)

    # Computed metrics (filled by _compute_metrics)
    total_trades:    int   = 0
    winning_trades:  int   = 0
    losing_trades:   int   = 0
    win_rate:        float = 0.0
    profit_factor:   float = 0.0
    sharpe_ratio:    float = 0.0
    max_drawdown_pct: float = 0.0
    total_pnl:       float = 0.0
    total_pnl_pct:   float = 0.0
    avg_rr:          float = 0.0
    avg_win:         float = 0.0
    avg_loss:        float = 0.0
    avg_duration_bars: float = 0.0
    best_trade_pnl:  float = 0.0
    worst_trade_pnl: float = 0.0
    max_consec_wins:  int  = 0
    max_consec_losses: int = 0
    run_duration_sec: float = 0.0
    sortino_ratio: float = 0.0
    expectancy: float = 0.0
    metadata: dict = field(default_factory=dict)
    attribution: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"╔══ BACKTEST REPORT ══════════════════════════════════",
            f"║  Symbol:        {self.symbol} {self.timeframe}",
            f"║  Period:        {self.date_from} → {self.date_to}",
            f"║  Balance:       ${self.initial_balance:.2f} → ${self.final_balance:.2f}",
            f"╠══ PERFORMANCE ══════════════════════════════════════",
            f"║  Total trades:  {self.total_trades}",
            f"║  Win rate:      {self.win_rate:.1%}",
            f"║  Profit factor: {self.profit_factor:.2f}",
            f"║  Sharpe ratio:  {self.sharpe_ratio:.2f}",
            f"║  Total P&L:     ${self.total_pnl:+.2f}  ({self.total_pnl_pct:+.1%})",
            f"║  Max drawdown:  {self.max_drawdown_pct:.1%}",
            f"║  Avg R:R:       1:{self.avg_rr:.2f}",
            f"╠══ TRADE STATS ══════════════════════════════════════",
            f"║  Avg win:       ${self.avg_win:.2f}",
            f"║  Avg loss:      ${self.avg_loss:.2f}",
            f"║  Best trade:    ${self.best_trade_pnl:+.2f}",
            f"║  Worst trade:   ${self.worst_trade_pnl:+.2f}",
            f"║  Max consec W:  {self.max_consec_wins}",
            f"║  Max consec L:  {self.max_consec_losses}",
            f"║  Avg duration:  {self.avg_duration_bars:.1f} bars",
            f"║  Run time:      {self.run_duration_sec:.1f}s",
            f"╚════════════════════════════════════════════════════",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol":          self.symbol,
            "timeframe":       self.timeframe,
            "initial_balance": self.initial_balance,
            "final_balance":   round(self.final_balance, 2),
            "total_trades":    self.total_trades,
            "winning_trades":  self.winning_trades,
            "losing_trades":   self.losing_trades,
            "win_rate":        round(self.win_rate, 4),
            "profit_factor":   round(self.profit_factor, 3),
            "sharpe_ratio":    round(self.sharpe_ratio, 3),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "total_pnl":       round(self.total_pnl, 2),
            "total_pnl_pct":   round(self.total_pnl_pct, 4),
            "avg_rr":          round(self.avg_rr, 3),
            "avg_win":         round(self.avg_win, 2),
            "avg_loss":        round(self.avg_loss, 2),
            "best_trade":      round(self.best_trade_pnl, 2),
            "worst_trade":     round(self.worst_trade_pnl, 2),
            "max_consec_wins":  self.max_consec_wins,
            "max_consec_losses": self.max_consec_losses,
            "equity_curve":    self.equity_curve,
            "sortino_ratio": self.sortino_ratio,
            "expectancy": self.expectancy,
            "metadata": self.metadata,
            "attribution": self.attribution,
        }


# ─── Backtest Engine ──────────────────────────────────────────────────────────

class BacktestEngine:
    """
    Simulates live trading against historical candle data.

    Parameters
    ----------
    signal_engine    : SignalEngine   Pre-configured signal engine.
    initial_balance  : float          Starting virtual account balance.
    slippage_pct     : float          Price slippage on entries/exits. Default 0.0005.
    spread_pips      : float          Fixed spread cost per trade. Default 0.0.
    warmup_bars      : int            Candles to skip at start (indicator warmup). Default 60.
    max_open         : int            Max simultaneous positions. Default 3.
    instrument_type  : InstrumentType Optional instrument type for LSL specialisation.
    """

    def __init__(
        self,
        signal_engine:   SignalEngine,
        initial_balance: float = 1000.0,
        slippage_pct:    float = 0.0005,
        spread_pips:     float = 0.0,
        warmup_bars:     int   = 60,
        max_open:        int   = 3,
        instrument_type: Optional[InstrumentType] = None,
        commission: float = 0.0,
    ) -> None:
        self.engine          = signal_engine
        self.initial_balance = initial_balance
        self.slippage_pct    = slippage_pct
        self.spread_pips     = spread_pips
        self.warmup_bars     = warmup_bars
        self.max_open        = max_open
        self.instrument_type = instrument_type
        self.commission = commission
        self.multiplier = signal_engine.cfg.deriv_multiplier
        if initial_balance <= 0 or warmup_bars < 1 or max_open < 1:
            raise ValueError("Invalid simulation limits")
        if not all(math.isfinite(x) and x >= 0 for x in (initial_balance, slippage_pct, spread_pips, commission)):
            raise ValueError("Invalid costs or balance")

    def run(
        self,
        candles:   list[Candle],
        symbol:    str = "",
        timeframe: str = "",
        htf_bias:  Optional[str] = None,
    ) -> BacktestReport:
        """
        Run the full backtest over the provided candle series.

        Parameters
        ----------
        candles   : Full OHLCV history, oldest first.
        symbol    : Instrument name for reporting.
        timeframe : Timeframe label for reporting.
        htf_bias  : Optional fixed HTF bias ("buy"/"sell") for the run.

        Returns
        -------
        BacktestReport with full trade log and performance metrics.
        """
        t_start = time.perf_counter()
        validate_candles(candles)
        if len(candles) <= self.warmup_bars:
            raise ValueError("Insufficient candles after warmup")
        if self.engine.cfg.deriv_product != "multiplier":
            raise ValueError("Simulation currently models multipliers only")
        if self.engine.cfg.use_safety_orders or self.engine.cfg.use_trailing_stop:
            raise ValueError("Scaling/trailing simulation is not validated")
        self.engine = SignalEngine(self.engine.cfg)
        self.engine.initialise(self.initial_balance)
        logger.info("Backtest starting | %s %s | %d candles | balance=$%.2f",
                    symbol, timeframe, len(candles), self.initial_balance)

        balance      = self.initial_balance
        open_trades: list[BTTrade] = []
        all_trades:  list[BTTrade] = []
        equity_curve: list[dict]  = [{"ts": candles[self.warmup_bars - 1].timestamp,
                                    "balance": balance, "equity": balance}]
        dd_monitor   = DrawdownMonitor(initial_balance=balance)

        # Re-initialise the circuit breaker fresh for this run
        simulated_now = datetime.fromtimestamp(candles[0].timestamp, timezone.utc)
        cb = CircuitBreaker(clock=lambda: simulated_now, max_open_positions=self.max_open,
                            max_consecutive_losses=self.engine.cfg.cb_max_losses,
                            daily_drawdown_pct=self.engine.cfg.cb_daily_dd,
                            weekly_drawdown_pct=self.engine.cfg.cb_weekly_dd)
        cb.initialise(balance)
        self.engine.cb = cb
        self.engine.sizer.update_balance(balance)

        date_from = datetime.utcfromtimestamp(candles[0].timestamp) if candles else None
        date_to   = None

        for i in range(self.warmup_bars, len(candles)):
            current = candles[i]
            simulated_now = datetime.fromtimestamp(current.timestamp, timezone.utc)

            # ── 1. Check SL/TP on open trades (use current candle's OHLC) ────
            just_closed = []
            for trade in open_trades:
                closed, pnl = self._check_exit(trade, current)
                if closed:
                    trade.exit_bar = i
                    trade.exit_ts = current.timestamp
                    balance += pnl
                    trade.pnl = pnl
                    cb.record_trade(pnl=pnl, account_balance=balance)
                    cb.record_trade_close()
                    self.engine.sizer.update_balance(balance)
                    dd_monitor.update(balance, note="trade_close")
                    just_closed.append(trade)
                    logger.debug("BT trade closed | pnl=$%.2f | balance=$%.2f",
                                 pnl, balance)

            open_trades = [t for t in open_trades if t not in just_closed]
            equity = balance + sum(self._compute_pnl(t, current.close) for t in open_trades)
            equity_curve.append({"ts": current.timestamp, "balance": balance, "equity": equity})
            cb.mark_equity(equity)
            self.engine.sizer.update_balance(max(0, equity))

            # ── 2. Evaluate signal on this bar ────────────────────────────────
            if i < len(candles) - 1 and equity > 0 and len(open_trades) < self.max_open and cb.is_trading_allowed():
                window   = candles[max(0, i - 499): i + 1]
                decision = self.engine.evaluate(
                    candles         = window,
                    symbol          = symbol,
                    timeframe       = timeframe,
                    instrument_type = self.instrument_type,
                    htf_bias        = htf_bias,
                )

                if decision.should_trade and decision.sizing and decision.sizing.is_valid:
                    entry = self._apply_slippage(candles[i + 1].open, decision.direction)
                    sizing = decision.sizing
                    valid_stops = (sizing.stop_loss < entry < sizing.take_profit if decision.direction == "buy"
                                   else sizing.take_profit < entry < sizing.stop_loss)
                    if not valid_stops:
                        continue
                    # Size using the actual next-open distance; never increase stake.
                    unit_risk = min(1.0, self.multiplier * abs(entry - sizing.stop_loss) / entry)
                    stake = math.floor(min(sizing.stake, min(sizing.risk_amount, equity * self.engine.cfg.max_risk_pct) /
                                           max(unit_risk, 1e-12)) * 100) / 100
                    if stake < self.engine.sizer.min_stake or sum(t.stake for t in open_trades) + stake > balance:
                        continue

                    trade = BTTrade(
                        trade_id      = f"BT{i + 1:08d}",
                        symbol        = symbol,
                        direction     = decision.direction,
                        entry_price   = entry,
                        stop_loss     = sizing.stop_loss,
                        take_profit   = sizing.take_profit,
                        stake         = stake,
                        entry_bar     = i + 1,
                        entry_ts      = candles[i + 1].timestamp,
                        confluence_score = decision.confluence_score,
                        reason_code   = decision.reason,
                        regime = decision.hurst.regime if decision.hurst else "unknown",
                    )
                    open_trades.append(trade)
                    all_trades.append(trade)
                    cb.record_trade_open()
                    logger.debug("BT trade opened | %s %s @ %.5f | SL=%.5f TP=%.5f",
                                 decision.direction, symbol, entry,
                                 sizing.stop_loss, sizing.take_profit)

        # ── Close any still-open trades at last price ─────────────────────────
        last = candles[-1]
        for trade in open_trades:
            exit_price = self._apply_slippage(last.close, trade.direction, closing=True)
            pnl = self._compute_pnl(trade, exit_price)
            trade.exit_price  = exit_price
            trade.exit_bar    = len(candles) - 1
            trade.exit_ts     = last.timestamp
            trade.pnl         = pnl
            trade.close_reason = "end_of_data"
            balance += pnl
        equity_curve[-1].update(balance=balance, equity=balance)

        date_to = datetime.utcfromtimestamp(last.timestamp)

        # ── Build report ──────────────────────────────────────────────────────
        report = BacktestReport(
            symbol          = symbol,
            timeframe       = timeframe,
            initial_balance = self.initial_balance,
            final_balance   = balance,
            date_from       = date_from,
            date_to         = date_to,
            trades          = all_trades,
            equity_curve    = equity_curve,
            run_duration_sec = time.perf_counter() - t_start,
        )
        self._compute_metrics(report)
        config = asdict(self.engine.cfg)
        report.metadata = {
            "model_version": "multiplier-next-open-v2", "config": config,
            "config_hash": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
            "data_sha256": hashlib.sha256(json.dumps([asdict(c) for c in candles], sort_keys=True).encode()).hexdigest(),
            "slippage_pct": self.slippage_pct, "spread_price": self.spread_pips,
            "commission": self.commission, "intrabar_policy": "stop_first",
            "profit_factor_defined": report.losing_trades > 0,
            "limitations": "OHLC approximation; no liquidity, latency, rejection or order-book model",
        }
        logger.info("Backtest complete | %s", report.summary())
        return report

    def run_walk_forward(
        self,
        candles:   list[Candle],
        n_splits:  int = 5,
        symbol:    str = "",
        timeframe: str = "",
    ) -> list[BacktestReport]:
        """
        Walk-forward validation: split data into n_splits folds.
        Each fold: first 80% in-sample (optimise), last 20% out-of-sample (test).
        Returns a list of out-of-sample BacktestReports.
        Stable OOS metrics across folds = robust, non-overfit strategy.
        """
        from app.backtesting.research import walk_forward
        return walk_forward(candles, [self.engine.cfg], n_splits, symbol, timeframe,
                            initial_balance=self.initial_balance, slippage_pct=self.slippage_pct,
                            spread_pips=self.spread_pips, commission=self.commission,
                            warmup_bars=self.warmup_bars)["reports"]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_exit(self, trade: BTTrade, candle: Candle) -> tuple[bool, float]:
        """
        Check if SL or TP was hit on the given candle.
        Uses the candle's low/high to detect intra-bar hits.
        Returns (closed, pnl).
        """
        if trade.direction == "buy":
            if candle.low <= trade.stop_loss:
                exit_p = self._apply_slippage(min(candle.open, trade.stop_loss), "buy", closing=True)
                trade.exit_price   = exit_p
                trade.exit_bar     = 0
                trade.exit_ts      = candle.timestamp
                trade.close_reason = "stop_loss"
                return True, self._compute_pnl(trade, exit_p)
            if candle.high >= trade.take_profit:
                exit_p = self._apply_slippage(trade.take_profit, "buy", closing=True)
                trade.exit_price   = exit_p
                trade.close_reason = "take_profit"
                return True, self._compute_pnl(trade, exit_p)
        else:
            if candle.high >= trade.stop_loss:
                exit_p = self._apply_slippage(max(candle.open, trade.stop_loss), "sell", closing=True)
                trade.exit_price   = exit_p
                trade.close_reason = "stop_loss"
                return True, self._compute_pnl(trade, exit_p)
            if candle.low <= trade.take_profit:
                exit_p = self._apply_slippage(trade.take_profit, "sell", closing=True)
                trade.exit_price   = exit_p
                trade.close_reason = "take_profit"
                return True, self._compute_pnl(trade, exit_p)
        return False, 0.0

    def _compute_pnl(self, trade: BTTrade, exit_price: float) -> float:
        """Estimate P&L from stake, entry, exit, and multiplier (100 default)."""
        move = exit_price - trade.entry_price
        if trade.direction == "sell":
            move = -move
        if trade.entry_price > 0:
            return max(-trade.stake, (move / trade.entry_price) * trade.stake * self.multiplier) - self.commission
        return move * trade.stake

    def _apply_slippage(self, price: float, direction: str, closing: bool = False) -> float:
        """Apply slippage to simulate real execution costs."""
        slip = price * self.slippage_pct + self.spread_pips / 2
        if not closing:
            return price + slip if direction == "buy" else price - slip
        return price - slip if direction == "buy" else price + slip

    def _compute_metrics(self, report: BacktestReport) -> None:
        """Compute all performance metrics from the trade list and equity curve."""
        trades = [t for t in report.trades if t.pnl is not None]
        if not trades:
            return

        pnls   = [t.pnl for t in trades]
        wins   = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        gross_profit = sum(wins)   if wins   else 0.0
        gross_loss   = abs(sum(losses)) if losses else 0.0

        report.total_trades    = len(trades)
        report.winning_trades  = len(wins)
        report.losing_trades   = len(losses)
        report.win_rate        = len(wins) / len(trades) if trades else 0.0
        # JSON and PostgreSQL JSONB cannot represent Infinity.
        report.profit_factor   = (gross_profit / gross_loss
                      if gross_loss > 0 else 0.0)
        report.total_pnl       = sum(pnls)
        report.expectancy = float(np.mean(pnls))
        report.total_pnl_pct   = report.total_pnl / report.initial_balance
        report.avg_win         = float(np.mean(wins))   if wins   else 0.0
        report.avg_loss        = float(np.mean([abs(l) for l in losses])) if losses else 0.0
        report.avg_rr          = (report.avg_win / report.avg_loss
                                  if report.avg_loss > 0 else 0.0)
        report.best_trade_pnl  = max(pnls)
        report.worst_trade_pnl = min(pnls)

        durations = [t.duration_bars for t in trades if t.duration_bars is not None]
        report.avg_duration_bars = float(np.mean(durations)) if durations else 0.0

        # Daily marked equity returns, annualized for 24/7 synthetic markets.
        daily = {}
        for point in report.equity_curve:
            daily[datetime.fromtimestamp(point["ts"], timezone.utc).date()] = point.get("equity", point["balance"])
        values = np.array(list(daily.values()))
        if len(values) > 2 and np.all(values > 0):
            returns = np.diff(values) / values[:-1]
            std = float(np.std(returns, ddof=1))
            downside = float(np.sqrt(np.mean(np.minimum(returns, 0) ** 2)))
            report.sharpe_ratio = float(np.mean(returns) / std * np.sqrt(365)) if std else 0
            report.sortino_ratio = float(np.mean(returns) / downside * np.sqrt(365)) if downside else 0

        # Max drawdown from equity curve
        if report.equity_curve:
            balances = [report.initial_balance] + [p.get("equity", p["balance"]) for p in report.equity_curve]
            hwm, max_dd = balances[0], 0.0
            for b in balances:
                if b > hwm:
                    hwm = b
                dd = (hwm - b) / hwm if hwm > 0 else 0.0
                max_dd = max(max_dd, dd)
            report.max_drawdown_pct = max_dd

        # Consecutive wins/losses
        streak = 0
        max_w  = 0
        max_l  = 0
        for p in pnls:
            if p > 0:
                streak = max(streak + 1, 1) if streak >= 0 else 1
                max_w  = max(max_w, streak)
            else:
                streak = min(streak - 1, -1) if streak <= 0 else -1
                max_l  = max(max_l, abs(streak))
        report.max_consec_wins   = max_w
        report.max_consec_losses = max_l
        for trade in trades:
            hour = datetime.fromtimestamp(trade.entry_ts, timezone.utc).hour
            weekday = datetime.fromtimestamp(trade.entry_ts, timezone.utc).strftime('%a')
            key = f"{trade.direction}:{trade.regime}:{weekday}:UTC{hour // 6 * 6:02d}:{trade.reason_code}"
            group = report.attribution.setdefault(key, {"trades": 0, "pnl": 0})
            group["trades"] += 1
            group["pnl"] += trade.pnl
