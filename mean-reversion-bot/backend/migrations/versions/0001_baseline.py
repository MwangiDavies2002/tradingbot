"""Frozen schema baseline; adopts matching existing tables without deleting data."""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

def create_table(name, *columns, **kwargs):
    if not sa.inspect(op.get_bind()).has_table(name):
        op.create_table(name, *columns, **kwargs)

def create_index(name, table, columns, **kwargs):
    existing = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, **kwargs)

def upgrade():
    create_table('backtest_results',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.String(length=32), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('date_from', sa.DateTime(), nullable=False),
    sa.Column('date_to', sa.DateTime(), nullable=False),
    sa.Column('total_trades', sa.Integer(), nullable=False),
    sa.Column('winning_trades', sa.Integer(), nullable=False),
    sa.Column('losing_trades', sa.Integer(), nullable=False),
    sa.Column('win_rate', sa.Float(), nullable=True),
    sa.Column('avg_rr', sa.Float(), nullable=True),
    sa.Column('profit_factor', sa.Float(), nullable=True),
    sa.Column('sharpe_ratio', sa.Float(), nullable=True),
    sa.Column('max_drawdown', sa.Float(), nullable=True),
    sa.Column('total_pnl', sa.Float(), nullable=True),
    sa.Column('total_pnl_pct', sa.Float(), nullable=True),
    sa.Column('params_json', sa.JSON(), nullable=True),
    sa.Column('equity_curve_json', sa.JSON(), nullable=True),
    sa.Column('trades_json', sa.JSON(), nullable=True),
    sa.Column('run_at', sa.DateTime(), nullable=False),
    sa.Column('duration_seconds', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_backtest_results_run_at'), 'backtest_results', ['run_at'], unique=False)
    create_index(op.f('ix_backtest_results_run_id'), 'backtest_results', ['run_id'], unique=True)
    create_table('bot_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('event_type', sa.String(length=48), nullable=False),
    sa.Column('severity', sa.String(length=12), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('details_json', sa.JSON(), nullable=True),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_bot_events_event_type'), 'bot_events', ['event_type'], unique=False)
    create_index('ix_bot_events_severity_ts', 'bot_events', ['severity', 'ts'], unique=False)
    create_index(op.f('ix_bot_events_ts'), 'bot_events', ['ts'], unique=False)
    create_index('ix_bot_events_type_ts', 'bot_events', ['event_type', 'ts'], unique=False)
    create_table('candles',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.Integer(), nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('open', sa.Float(), nullable=False),
    sa.Column('high', sa.Float(), nullable=False),
    sa.Column('low', sa.Float(), nullable=False),
    sa.Column('close', sa.Float(), nullable=False),
    sa.Column('volume', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol', 'timeframe', 'ts', name='uq_candle_symbol_tf_ts')
    )
    create_index(op.f('ix_candles_symbol'), 'candles', ['symbol'], unique=False)
    create_index('ix_candles_symbol_tf_ts', 'candles', ['symbol', 'timeframe', 'ts'], unique=False)
    create_index(op.f('ix_candles_ts'), 'candles', ['ts'], unique=False)
    create_table('config',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('value_type', sa.String(length=12), nullable=False),
    sa.Column('description', sa.String(length=256), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_config_key'), 'config', ['key'], unique=True)
    create_table('decision_receipts',
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('trade_id', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('fingerprint'),
    sa.UniqueConstraint('trade_id')
    )
    create_table('equity_snapshots',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ts', sa.DateTime(), nullable=False),
    sa.Column('balance', sa.Float(), nullable=False),
    sa.Column('open_equity', sa.Float(), nullable=True),
    sa.Column('daily_pnl', sa.Float(), nullable=True),
    sa.Column('open_trades', sa.Integer(), nullable=False),
    sa.Column('note', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_equity_snapshots_ts'), 'equity_snapshots', ['ts'], unique=False)
    create_table('execution_records',
    sa.Column('trade_id', sa.String(length=32), nullable=False),
    sa.Column('scope', sa.String(length=96), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('trade_id')
    )
    create_index(op.f('ix_execution_records_scope'), 'execution_records', ['scope'], unique=False)
    create_table('liquidity_zones',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('price', sa.Float(), nullable=False),
    sa.Column('zone_type', sa.String(length=32), nullable=False),
    sa.Column('strength', sa.Float(), nullable=False),
    sa.Column('test_count', sa.Integer(), nullable=False),
    sa.Column('invalidated', sa.Boolean(), nullable=False),
    sa.Column('first_seen', sa.DateTime(), nullable=False),
    sa.Column('last_tested', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_liquidity_zones_invalidated'), 'liquidity_zones', ['invalidated'], unique=False)
    create_index(op.f('ix_liquidity_zones_symbol'), 'liquidity_zones', ['symbol'], unique=False)
    create_index('ix_lz_symbol_tf_valid', 'liquidity_zones', ['symbol', 'timeframe', 'invalidated'], unique=False)
    create_table('news_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('event_id', sa.String(length=128), nullable=False),
    sa.Column('title', sa.String(length=256), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=True),
    sa.Column('impact', sa.String(length=16), nullable=False),
    sa.Column('event_at', sa.DateTime(), nullable=False),
    sa.Column('actual', sa.Float(), nullable=True),
    sa.Column('forecast', sa.Float(), nullable=True),
    sa.Column('previous', sa.Float(), nullable=True),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('raw_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_news_events_currency'), 'news_events', ['currency'], unique=False)
    create_index(op.f('ix_news_events_event_at'), 'news_events', ['event_at'], unique=False)
    create_index(op.f('ix_news_events_event_id'), 'news_events', ['event_id'], unique=True)
    create_index(op.f('ix_news_events_impact'), 'news_events', ['impact'], unique=False)
    create_table('signals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('direction', sa.String(length=8), nullable=True),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('fired', sa.Boolean(), nullable=False),
    sa.Column('reason', sa.String(length=128), nullable=False),
    sa.Column('z_score', sa.Float(), nullable=True),
    sa.Column('rsi', sa.Float(), nullable=True),
    sa.Column('bb_position', sa.String(length=16), nullable=True),
    sa.Column('vwap_dev_atr', sa.Float(), nullable=True),
    sa.Column('stoch_k', sa.Float(), nullable=True),
    sa.Column('hurst', sa.Float(), nullable=True),
    sa.Column('atr', sa.Float(), nullable=True),
    sa.Column('lsl_grab', sa.Boolean(), nullable=False),
    sa.Column('lsl_wick_ratio', sa.Float(), nullable=True),
    sa.Column('bos_choch', sa.Boolean(), nullable=False),
    sa.Column('order_block', sa.Boolean(), nullable=False),
    sa.Column('htf_aligned', sa.Boolean(), nullable=False),
    sa.Column('volume_ratio', sa.Float(), nullable=True),
    sa.Column('breakdown_json', sa.JSON(), nullable=True),
    sa.Column('evaluated_at', sa.DateTime(), nullable=False),
    sa.Column('eval_ms', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_signals_evaluated_at'), 'signals', ['evaluated_at'], unique=False)
    create_index(op.f('ix_signals_fired'), 'signals', ['fired'], unique=False)
    create_index('ix_signals_fired_evaluated', 'signals', ['fired', 'evaluated_at'], unique=False)
    create_index(op.f('ix_signals_symbol'), 'signals', ['symbol'], unique=False)
    create_index('ix_signals_symbol_evaluated', 'signals', ['symbol', 'evaluated_at'], unique=False)
    create_table('trades',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('trade_id', sa.String(length=32), nullable=False),
    sa.Column('contract_id', sa.BigInteger(), nullable=True),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('direction', sa.String(length=8), nullable=False),
    sa.Column('contract_type', sa.String(length=16), nullable=False),
    sa.Column('instrument_type', sa.String(length=16), nullable=True),
    sa.Column('entry_price', sa.Float(), nullable=False),
    sa.Column('exit_price', sa.Float(), nullable=True),
    sa.Column('stop_loss', sa.Float(), nullable=False),
    sa.Column('take_profit', sa.Float(), nullable=False),
    sa.Column('stake', sa.Float(), nullable=False),
    sa.Column('pnl', sa.Float(), nullable=True),
    sa.Column('pnl_pct', sa.Float(), nullable=True),
    sa.Column('confluence_score', sa.Integer(), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=False),
    sa.Column('breakdown_json', sa.JSON(), nullable=True),
    sa.Column('z_score', sa.Float(), nullable=True),
    sa.Column('rsi_value', sa.Float(), nullable=True),
    sa.Column('bb_position', sa.String(length=16), nullable=True),
    sa.Column('vwap_dev', sa.Float(), nullable=True),
    sa.Column('stoch_k', sa.Float(), nullable=True),
    sa.Column('hurst_value', sa.Float(), nullable=True),
    sa.Column('atr_value', sa.Float(), nullable=True),
    sa.Column('lsl_wick_ratio', sa.Float(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('close_reason', sa.String(length=24), nullable=True),
    sa.Column('opened_at', sa.DateTime(), nullable=False),
    sa.Column('closed_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    create_index(op.f('ix_trades_contract_id'), 'trades', ['contract_id'], unique=False)
    create_index(op.f('ix_trades_opened_at'), 'trades', ['opened_at'], unique=False)
    create_index(op.f('ix_trades_status'), 'trades', ['status'], unique=False)
    create_index('ix_trades_status_opened', 'trades', ['status', 'opened_at'], unique=False)
    create_index(op.f('ix_trades_symbol'), 'trades', ['symbol'], unique=False)
    create_index('ix_trades_symbol_opened', 'trades', ['symbol', 'opened_at'], unique=False)
    create_index(op.f('ix_trades_trade_id'), 'trades', ['trade_id'], unique=True)
    create_table('trading_control',
    sa.Column('scope', sa.String(length=96), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('reset_version', sa.Integer(), nullable=False),
    sa.Column('reset_applied', sa.Integer(), nullable=False),
    sa.Column('heartbeat', sa.DateTime(), nullable=True),
    sa.Column('recovery_error', sa.Text(), nullable=True),
    sa.Column('risk_state', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('scope')
    )

    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("trades", "contract_id", type_=sa.BigInteger())

def downgrade():
    raise RuntimeError("Destructive downgrade disabled; restore a tested backup")

