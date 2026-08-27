"""
models.py
────────────────────────────────────────────────────────────────────────────────
Database Models — SQLAlchemy ORM
────────────────────────────────────────────────────────────────────────────────

WHAT THIS DOES:
    Defines all database tables as SQLAlchemy ORM models.
    Used by Alembic for migrations and by the app for all DB reads/writes.

    TABLES:
        trades          Full trade ledger — every open/close recorded
        signals         Every signal evaluated (fired or skipped)
        candles         OHLCV price history (TimescaleDB hypertable)
        liquidity_zones Mapped swing/OB/FVG zones per instrument
        equity_snapshots Balance snapshots for equity curve
        bot_events      System events, circuit breaker logs, errors
        config          Key-value bot configuration store
        backtest_results Stored backtest run outputs

    TimescaleDB:
        The `candles` table uses TimescaleDB's create_hypertable() for
        time-series partitioning. Run the migration SQL after table creation:
            SELECT create_hypertable('candles', 'timestamp');
        This gives 10-100× faster range queries on time-series data.
────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Index,
    Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped


class Base(DeclarativeBase):
    pass


# ─── Trades ───────────────────────────────────────────────────────────────────

class Trade(Base):
    """
    Complete record of every trade from signal to close.
    One row per trade — inserted on open, updated on close.
    """
    __tablename__ = "trades"

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    trade_id         = Column(String(32),  unique=True, nullable=False, index=True)
    contract_id      = Column(Integer,  nullable=True,  index=True)

    # Instrument
    symbol           = Column(String(32),  nullable=False, index=True)
    timeframe        = Column(String(8),   nullable=False)
    direction        = Column(String(8),   nullable=False)   # "buy" / "sell"
    contract_type    = Column(String(16),  nullable=False)   # MULTUP / MULTDOWN
    instrument_type  = Column(String(16),  nullable=True)    # volatility / boom_500 / etc.

    # Prices
    entry_price      = Column(Float,    nullable=False)
    exit_price       = Column(Float,    nullable=True)
    stop_loss        = Column(Float,    nullable=False)
    take_profit      = Column(Float,    nullable=False)

    # Money
    stake            = Column(Float,    nullable=False)
    pnl              = Column(Float,    nullable=True)
    pnl_pct          = Column(Float,    nullable=True)

    # Signal quality
    confluence_score = Column(Integer,  nullable=False, default=0)
    reason_code      = Column(String(64), nullable=False, default="")
    breakdown_json   = Column(JSON,     nullable=True)   # Full ScoreBreakdown dict

    # Indicator snapshots at entry
    z_score          = Column(Float,    nullable=True)
    rsi_value        = Column(Float,    nullable=True)
    bb_position      = Column(String(16), nullable=True)
    vwap_dev         = Column(Float,    nullable=True)
    stoch_k          = Column(Float,    nullable=True)
    hurst_value      = Column(Float,    nullable=True)
    atr_value        = Column(Float,    nullable=True)
    lsl_wick_ratio   = Column(Float,    nullable=True)

    # Status
    status           = Column(String(12), nullable=False, default="pending", index=True)
    close_reason     = Column(String(24), nullable=True)

    # Timestamps
    opened_at        = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    closed_at        = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_trades_symbol_opened", "symbol", "opened_at"),
        Index("ix_trades_status_opened", "status", "opened_at"),
    )

    def __repr__(self) -> str:
        return (f"<Trade {self.trade_id} | {self.direction} {self.symbol} | "
                f"pnl={self.pnl} | status={self.status}>")


# ─── Signals ──────────────────────────────────────────────────────────────────

class Signal(Base):
    """
    Log of every signal evaluation — whether it fired or was skipped.
    Invaluable for analysing strategy performance and confluence patterns.
    """
    __tablename__ = "signals"

    id               = Column(Integer,  primary_key=True, autoincrement=True)
    symbol           = Column(String(32),  nullable=False, index=True)
    timeframe        = Column(String(8),   nullable=False)
    direction        = Column(String(8),   nullable=True)
    score            = Column(Integer,  nullable=False, default=0)
    fired            = Column(Boolean,  nullable=False, default=False, index=True)
    reason           = Column(String(128), nullable=False, default="")

    # Full indicator values at evaluation time
    z_score          = Column(Float,    nullable=True)
    rsi              = Column(Float,    nullable=True)
    bb_position      = Column(String(16), nullable=True)
    vwap_dev_atr     = Column(Float,    nullable=True)
    stoch_k          = Column(Float,    nullable=True)
    hurst            = Column(Float,    nullable=True)
    atr              = Column(Float,    nullable=True)
    lsl_grab         = Column(Boolean,  nullable=False, default=False)
    lsl_wick_ratio   = Column(Float,    nullable=True)
    bos_choch        = Column(Boolean,  nullable=False, default=False)
    order_block      = Column(Boolean,  nullable=False, default=False)
    htf_aligned      = Column(Boolean,  nullable=False, default=False)
    volume_ratio     = Column(Float,    nullable=True)
    breakdown_json   = Column(JSON,     nullable=True)

    evaluated_at     = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    eval_ms          = Column(Float,    nullable=True)   # Engine latency ms

    __table_args__ = (
        Index("ix_signals_symbol_evaluated", "symbol", "evaluated_at"),
        Index("ix_signals_fired_evaluated",  "fired",  "evaluated_at"),
    )

    def __repr__(self) -> str:
        return (f"<Signal {self.symbol} {self.timeframe} | "
                f"score={self.score} | fired={self.fired} | {self.reason}>")


# ─── Candles ──────────────────────────────────────────────────────────────────

class Candle(Base):
    """
    OHLCV price history.
    Designed as a TimescaleDB hypertable partitioned on `ts`.
    After table creation run:
        SELECT create_hypertable('candles', 'ts');
    """
    __tablename__ = "candles"

    id        = Column(Integer, primary_key=True, autoincrement=True)
    symbol    = Column(String(32), nullable=False, index=True)
    timeframe = Column(Integer,    nullable=False)          # Seconds: 60, 300, etc.
    ts        = Column(DateTime,   nullable=False, index=True)  # Candle open time UTC
    open      = Column(Float,      nullable=False)
    high      = Column(Float,      nullable=False)
    low       = Column(Float,      nullable=False)
    close     = Column(Float,      nullable=False)
    volume    = Column(Float,      nullable=False, default=0.0)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_candle_symbol_tf_ts"),
        Index("ix_candles_symbol_tf_ts", "symbol", "timeframe", "ts"),
    )

    def __repr__(self) -> str:
        return (f"<Candle {self.symbol} {self.timeframe}s @ {self.ts} | "
                f"O={self.open} H={self.high} L={self.low} C={self.close}>")


# ─── Liquidity Zones ──────────────────────────────────────────────────────────

class LiquidityZone(Base):
    """
    Persisted liquidity zone map. Rebuilt periodically by SwingMapper/ZoneBuilder.
    Stored for dashboard visualisation and historical zone analysis.
    """
    __tablename__ = "liquidity_zones"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    symbol       = Column(String(32), nullable=False, index=True)
    timeframe    = Column(String(8),  nullable=False)
    price        = Column(Float,      nullable=False)
    zone_type    = Column(String(32), nullable=False)   # swing_high, order_block_bearish, etc.
    strength     = Column(Float,      nullable=False, default=0.5)
    test_count   = Column(Integer,    nullable=False, default=0)
    invalidated  = Column(Boolean,    nullable=False, default=False, index=True)
    first_seen   = Column(DateTime,   nullable=False, default=datetime.utcnow)
    last_tested  = Column(DateTime,   nullable=True)
    updated_at   = Column(DateTime,   nullable=False, default=datetime.utcnow,
                          onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_lz_symbol_tf_valid", "symbol", "timeframe", "invalidated"),
    )

    def __repr__(self) -> str:
        return (f"<LiquidityZone {self.zone_type} @ {self.price:.5f} | "
                f"{self.symbol} | str={self.strength:.2f}>")


# ─── Equity Snapshots ─────────────────────────────────────────────────────────

class EquitySnapshot(Base):
    """
    Point-in-time account balance snapshots for the equity curve.
    Written after every trade close and on a scheduled interval.
    """
    __tablename__ = "equity_snapshots"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    ts           = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    balance      = Column(Float,    nullable=False)   # Account balance USD
    open_equity  = Column(Float,    nullable=True)    # Balance + unrealised P&L
    daily_pnl    = Column(Float,    nullable=True)    # P&L since day start
    open_trades  = Column(Integer,  nullable=False, default=0)
    note         = Column(String(64), nullable=True)  # e.g. "trade_close", "scheduled"

    def __repr__(self) -> str:
        return f"<EquitySnapshot ${self.balance:.2f} @ {self.ts}>"


# ─── Bot Events ───────────────────────────────────────────────────────────────

class BotEvent(Base):
    """
    System event log: circuit breaker triggers, bot start/stop,
    API errors, reconnections, config changes — anything significant.
    """
    __tablename__ = "bot_events"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    event_type   = Column(String(48), nullable=False, index=True)
    severity     = Column(String(12), nullable=False, default="info")  # info/warn/error/critical
    message      = Column(Text,       nullable=False)
    details_json = Column(JSON,       nullable=True)
    ts           = Column(DateTime,   nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_bot_events_type_ts", "event_type", "ts"),
        Index("ix_bot_events_severity_ts", "severity", "ts"),
    )

    def __repr__(self) -> str:
        return f"<BotEvent [{self.severity.upper()}] {self.event_type} @ {self.ts}>"


# ─── Config ───────────────────────────────────────────────────────────────────

class ConfigEntry(Base):
    """
    Key-value store for bot configuration.
    Allows runtime config changes without redeployment.
    Dashboard settings panel reads/writes from this table.
    """
    __tablename__ = "config"

    id         = Column(Integer,   primary_key=True, autoincrement=True)
    key        = Column(String(64), unique=True, nullable=False, index=True)
    value      = Column(Text,       nullable=False)
    value_type = Column(String(12), nullable=False, default="str")  # str/int/float/bool/json
    description= Column(String(256), nullable=True)
    updated_at = Column(DateTime,   nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    def get_typed_value(self):
        """Return value cast to its declared type."""
        if self.value_type == "int":
            return int(self.value)
        if self.value_type == "float":
            return float(self.value)
        if self.value_type == "bool":
            return self.value.lower() in ("true", "1", "yes")
        if self.value_type == "json":
            import json
            return json.loads(self.value)
        return self.value

    def __repr__(self) -> str:
        return f"<Config {self.key}={self.value!r}>"


# ─── Backtest Results ─────────────────────────────────────────────────────────

class BacktestResult(Base):
    """
    Stores the output of each backtest run for comparison and review.
    Metrics are stored flat for easy querying; full equity curve in JSON.
    """
    __tablename__ = "backtest_results"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    run_id          = Column(String(32), unique=True, nullable=False, index=True)
    symbol          = Column(String(32), nullable=False)
    timeframe       = Column(String(8),  nullable=False)
    date_from       = Column(DateTime,   nullable=False)
    date_to         = Column(DateTime,   nullable=False)

    # Performance metrics
    total_trades    = Column(Integer, nullable=False, default=0)
    winning_trades  = Column(Integer, nullable=False, default=0)
    losing_trades   = Column(Integer, nullable=False, default=0)
    win_rate        = Column(Float,   nullable=True)
    avg_rr          = Column(Float,   nullable=True)
    profit_factor   = Column(Float,   nullable=True)
    sharpe_ratio    = Column(Float,   nullable=True)
    max_drawdown    = Column(Float,   nullable=True)
    total_pnl       = Column(Float,   nullable=True)
    total_pnl_pct   = Column(Float,   nullable=True)

    # Config snapshot used for this run
    params_json     = Column(JSON, nullable=True)
    # Full equity curve [{ts, balance}] and trade list
    equity_curve_json = Column(JSON, nullable=True)
    trades_json       = Column(JSON, nullable=True)

    run_at          = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    duration_seconds= Column(Float,    nullable=True)

    def __repr__(self) -> str:
        return (f"<BacktestResult {self.run_id} | {self.symbol} | "
                f"trades={self.total_trades} | wr={self.win_rate:.1%} | "
                f"sharpe={self.sharpe_ratio}>")
