import json
import math
import threading
import time
from datetime import datetime
from statistics import stdev
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pytest
from app.core.lsl.lsl_detector import Candle
from app.core.engine.signal_engine import EngineConfig, TradeDecision
from app.core.risk.position_sizer import PositionSizer
from app.backtesting.backtest_engine import BacktestEngine, BTTrade
from app.backtesting.research import monte_carlo, walk_forward
from app.data.validation import validate_candles
from app.quant.schemas import AnalysisRequest, Asset, Bar, ResearchScope, Session, SessionHours
from app.quant.jobs import AnalysisJobs
from app.quant.research_sessions import market_is_open
from app.quant.statistics import audit, market_behavior
from app.quant.sources import mt5_snapshot
from app.quant.instruments import classify_instrument, timeframe_seconds


def candles(n=100):
    return [Candle(1700000000 + i * 300, 100, 101, 99, 100, 100) for i in range(n)]


class FixedSignal:
    def __init__(self, config):
        self.cfg = config
        self.sizer = PositionSizer(1000)
        self.called = False
    def initialise(self, balance):
        self.sizer.update_balance(balance)
    def evaluate(self, candles, **kwargs):
        trade = not self.called
        self.called = True
        sizing = self.sizer.calculate(100, 1, "buy", stop_loss=95, take_profit=110)
        return TradeDecision("R_75", "M5", "buy", trade, "fixture", sizing=sizing, entry_price=100)


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr("app.backtesting.backtest_engine.SignalEngine", FixedSignal)
    return BacktestEngine(FixedSignal(EngineConfig()), slippage_pct=0, warmup_bars=30)


def test_end_of_data_trade_count_and_next_open(engine):
    data = candles(40)
    data[31] = Candle(data[31].timestamp, 102, 103, 99, 100, 100)
    report = engine.run(data)
    assert len(report.trades) == report.total_trades == 1
    trade = report.trades[0]
    assert trade.entry_price == 102
    assert trade.entry_bar == 31 and trade.exit_bar == 39
    assert report.final_balance - report.initial_balance == pytest.approx(report.total_pnl)
    assert report.equity_curve[-1]["equity"] == report.final_balance
    assert report.max_drawdown_pct > 0
    json.dumps(report.to_dict(), allow_nan=False)


def test_costs_and_gap_stops_are_adverse(engine):
    t = BTTrade("test", "R_75", "buy", 100, 95, 110, 1, 0)
    closed, pnl = engine._check_exit(t, Candle(1, 90, 111, 89, 100, 1))
    assert closed and t.exit_price == 90 and t.close_reason == "stop_loss"
    assert pnl == -1  # multiplier's maximum cash stake loss
    engine.spread_pips = 2
    engine.commission = .2
    assert engine._apply_slippage(100, "buy") == 101
    assert engine._apply_slippage(100, "buy", closing=True) == 99
    assert engine._compute_pnl(t, 90) == -1.2


def test_reproducible_runs(engine):
    first = engine.run(candles()).to_dict()
    second = engine.run(candles()).to_dict()
    assert first == second


@pytest.mark.parametrize("bad", [
    [Candle(1, 100, 90, 99, 100, 1)],
    [Candle(1, 100, 101, 99, float('nan'), 1)],
    [Candle(1, 100, 101, 99, 100, 1), Candle(1, 100, 101, 99, 100, 1)],
])
def test_invalid_data_rejected(bad):
    with pytest.raises(ValueError): validate_candles(bad)


def test_monte_carlo_is_seeded_and_reports_empty_data():
    assert monte_carlo([], 1000)["status"] == "insufficient_trades"
    assert monte_carlo([10, -5, 2], 1000, 100, 7) == monte_carlo([10, -5, 2], 1000, 100, 7)


def test_audit_reports_stale_closes_and_spread_outliers():
    bars = [Bar(timestamp=i * 300, open=100, high=101, low=99, close=100,
                volume=10, spread=spread) for i, spread in enumerate((1, 1, 4, 1))]
    report = audit(bars, 300, Session(weekdays=list(range(7)), source='test fixture', confirmed=True), 0, 1200)
    assert report['stale_close_run_bars'] == 4
    assert report['stale_close_warning'] is True
    assert report['median_spread'] == 1
    assert report['spread_outlier_bars'] == 1


def test_audit_groups_missing_candles_into_ranges():
    bars = [Bar(timestamp=i * 300, open=100, high=101, low=99, close=100)
            for i in (0, 1, 4, 5)]
    report = audit(bars, 300, Session(weekdays=list(range(7)), source='test fixture', confirmed=True), 0, 1800)
    assert report['missing_ranges'] == [{'start': 600, 'end': 900, 'bars': 2}]


def test_audit_uses_broker_candle_phase_for_daily_timeframes():
    interval = 86400
    phase = 2 * 3600
    bars = [Bar(timestamp=phase + index * interval, open=100, high=101, low=99, close=100)
            for index in (0, 1, 3)]
    calendar = Session(weekdays=list(range(7)), source='test broker schedule', confirmed=True)
    report = audit(bars, interval, calendar, 0, phase + 4 * interval)
    assert report['expected_bars'] == 4
    assert report['missing_ranges'] == [{'start': phase + 2 * interval,
                                         'end': phase + 2 * interval, 'bars': 1}]


def test_daily_audit_tracks_local_candle_phase_across_daylight_saving():
    zone = ZoneInfo('America/New_York')
    days = [datetime(2026, 3, day, 0, 0, tzinfo=zone) for day in (6, 7, 9, 10)]
    bars = [Bar(timestamp=int(day.timestamp()), open=100, high=101, low=99, close=100)
            for day in days]
    calendar = Session(timezone='America/New_York', weekdays=list(range(7)),
                       source='test broker schedule', confirmed=True)
    start = int(datetime(2026, 3, 6, 0, 0, tzinfo=zone).timestamp())
    end = int(datetime(2026, 3, 11, 0, 0, tzinfo=zone).timestamp())
    report = audit(bars, 86400, calendar, start, end)
    missing = int(datetime(2026, 3, 8, 0, 0, tzinfo=zone).timestamp())
    assert report['expected_bars'] == 5
    assert report['missing_ranges'] == [{'start': missing, 'end': missing, 'bars': 1}]


def test_confirmed_session_requires_provenance():
    with pytest.raises(ValueError, match='source or broker schedule'):
        Session(weekdays=list(range(7)), confirmed=True)


def test_unverified_calendar_does_not_claim_completeness():
    bars = [Bar(timestamp=i * 300, open=100, high=101, low=99, close=100)
            for i in range(100)]
    result = audit(bars, 300, Session(), 0, 100 * 300)
    assert result['coverage'] is None
    assert result['expected_bars'] == 0
    assert result['passed'] is False
    assert 'calendar is unverified' in result['note']


@pytest.mark.parametrize(('path', 'calc_mode', 'expected'), [
    ('Forex\\Majors', 0, 'forex'),
    ('CFD\\Indices', 1, 'index'),
    ('CFD\\Metals', 1, 'metal'),
    ('Metals\\XAUUSD', 0, 'metal'),
    ('Commodities\\Energy', 1, 'commodity'),
    ('Derived\\Synthetic Indices', 1, 'synthetic'),
    ('Volatility Indices\\Volatility 75 Index', 4, 'synthetic'),
    ('Equities\\NASDAQ\\AAPL.OQ', 0, 'equity'),
    ('', 1, 'unknown'),
])
def test_asset_class_comes_from_broker_metadata(path, calc_mode, expected):
    info = SimpleNamespace(path=path, trade_calc_mode=calc_mode,
                           currency_base='EUR' if expected == 'forex' else '')
    terminal = SimpleNamespace(SYMBOL_CALC_MODE_FOREX=0)
    assert classify_instrument(info, terminal) == expected


def test_weekly_session_windows_follow_dst_and_daily_breaks():
    calendar = Session(
        timezone='America/New_York',
        source='Deriv Germany 40 schedule',
        confirmed=True,
        weekly_hours={
            6: [SessionHours(open_minute=1080, close_minute=1440)],
            0: [SessionHours(open_minute=0, close_minute=1020), SessionHours(open_minute=1080, close_minute=1440)],
            1: [SessionHours(open_minute=0, close_minute=1020), SessionHours(open_minute=1080, close_minute=1440)],
            2: [SessionHours(open_minute=0, close_minute=1020), SessionHours(open_minute=1080, close_minute=1440)],
            3: [SessionHours(open_minute=0, close_minute=1020), SessionHours(open_minute=1080, close_minute=1440)],
            4: [SessionHours(open_minute=0, close_minute=1020)],
        },
    )
    def timestamp(local_time):
        return int(datetime.fromisoformat(local_time).replace(tzinfo=ZoneInfo('America/New_York')).timestamp())
    assert market_is_open(timestamp('2026-10-25T18:00:00'), calendar) is True
    assert market_is_open(timestamp('2026-11-01T18:00:00'), calendar) is True
    assert market_is_open(timestamp('2026-11-02T17:00:00'), calendar) is False
    assert market_is_open(timestamp('2026-11-02T18:00:00'), calendar) is True


def test_analysis_strategy_identity_matches_selected_asset_and_timeframe():
    request = AnalysisRequest(
        assets=[Asset(symbol='Germany 40')],
        timeframe='M30',
    )
    assert request.strategy.symbol == 'Germany 40'
    assert request.strategy.timeframe == 'M30'


@pytest.mark.parametrize(('timeframe', 'seconds'), [
    ('M1', 60), ('M5', 300), ('H1', 3600), ('D1', 86400), ('W1', 604800),
])
def test_timeframe_seconds_match_supported_broker_periods(timeframe, seconds):
    assert timeframe_seconds(timeframe) == seconds


def test_calendar_month_timeframe_is_not_misrepresented_as_thirty_days():
    with pytest.raises(ValueError, match='timeframe'):
        AnalysisRequest(assets=[Asset(symbol='EURUSD.a')], timeframe='MN1')


def test_weekly_research_allows_enough_history_for_100_candles():
    request = AnalysisRequest(assets=[Asset(symbol='EURUSD.a', timeframe='W1')], days=800)
    assert request.days == 800
    with pytest.raises(ValueError, match='10,000-candle limit'):
        AnalysisRequest(assets=[Asset(symbol='EURUSD.a', timeframe='M5')], days=35)


def test_mt5_snapshot_uses_broker_rollover_day_and_flags_unpriced_swap_mode():
    request = AnalysisRequest(assets=[Asset(symbol='Germany 40')], timeframe='M30')
    asset = request.assets[0]
    account = SimpleNamespace(login=1, server='demo', currency='USD')
    info = SimpleNamespace(
        trade_contract_size=1, trade_tick_size=.01, volume_min=.1, volume_max=100,
        volume_step=.1, currency_profit='USD', trade_stops_level=0, trade_mode=4,
        currency_base='EUR', currency_margin='USD', trade_calc_mode=4, point=.01,
        digits=2, spread=150, trade_tick_value=.01, trade_tick_value_profit=.01,
        trade_tick_value_loss=.01, order_mode=49, trade_exemode=2, trade_freeze_level=0,
        swap_mode=5, swap_long=-4.49, swap_short=.53, swap_rollover3days=5,
    )
    history_start = 1_700_000_000
    rates = [{'time': history_start + index * request.interval, 'open': 100, 'high': 101, 'low': 99,
              'close': 100, 'tick_volume': 10, 'spread': 50} for index in range(101)]
    terminal = SimpleNamespace(
        TIMEFRAME_M30=30,
        SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT=4,
        SYMBOL_SWAP_MODE_INTEREST_CURRENT=5,
        copy_rates_range=lambda *args: rates,
        copy_rates_from_pos=lambda *args: [{'time': history_start + request.interval * 100}],
        positions_get=lambda: [],
    )
    runner = SimpleNamespace(
        lock=threading.RLock(),
        mt5=terminal,
        _require_connection=lambda: (account, None, None),
        _market_info=lambda symbol: info,
    )

    bars, profile, snapshot, _ = mt5_snapshot(runner, asset, request)

    assert len(bars) == 100 and bars[-1].timestamp == history_start + 99 * request.interval
    assert profile.rollover_weights == [1, 1, 1, 1, 3, 1, 1]
    assert snapshot['swap_rollover3days'] == 5
    assert snapshot['swap_mode_name'] == 'SYMBOL_SWAP_MODE_INTEREST_CURRENT'
    assert snapshot['spread_price_at_snapshot'] == 1.5
    assert profile.specification_confirmed is True
    assert snapshot['asset_class'] == 'unknown'
    assert any('fixed per-lot financing model cannot price it' in warning for warning in snapshot['warnings'])


def test_session_restricted_research_candidate_carries_execution_scope(tmp_path):
    profile = Asset(symbol='Germany 40').profile.model_copy(update={
        'contract_size': 1, 'tick_size': .01, 'tick_value': .01, 'point': .01,
        'digits': 2, 'volume_min': .1, 'volume_max': 100, 'volume_step': .1,
        'profit_currency': 'USD', 'account_currency': 'USD',
        'calculation_mode': 4, 'order_mode': 49, 'trade_mode': 4,
        'specification_source': 'test fixture',
        'commission_per_lot': 0,
        'financing_long': 0,
        'financing_short': 0,
        'costs_confirmed': True,
        'cost_source': 'test fixture',
        'rollover_confirmed': True,
        'rollover_source': 'test fixture',
        'slippage_confirmed': True,
        'slippage_source': 'test fixture',
        'specification_confirmed': True,
        'session': Session(weekdays=list(range(7)), source='test fixture', confirmed=True),
        'specification_fingerprint': 'a' * 64,
    })
    request = AnalysisRequest(
        assets=[Asset(symbol='Germany 40', profile=profile)],
        days=7,
        research_scope=ResearchScope(sessions=['new_york']),
    )

    def loader(asset, body, runner, start, end):
        bars = []
        for index, ts in enumerate(range(start, end, body.interval)):
            opening = 100 + index * .001
            bars.append(Bar(timestamp=ts, open=opening, high=opening + .01,
                            low=opening - .01, close=opening + .005))
        return bars, asset.profile, {'warnings': [], 'account': 1, 'server': 'demo',
                                    'symbol': asset.symbol, 'asset_class': asset.profile.asset_class,
                                    'broker_group': asset.profile.broker_group,
                                    'specification_fingerprint': asset.profile.specification_fingerprint}, 0

    def validator(bars, body, asset_profile, symbol, progress):
        progress('Fixture validation complete')
        return {
            'passed': True,
            'checks': {'fixture_passed': True},
            'selected_strategy': body.strategy.model_dump(),
            'holdout': {'total_trades': 20, 'total_pnl': 1, 'profit_factor': 1.2},
            'oos_trades': 100,
            'oos_pnl': 1,
        }

    store = AnalysisJobs(tmp_path / 'analysis.sqlite3', loader=loader, validator=validator)
    run = store.create(request, runner=object())
    deadline = time.monotonic() + 5
    while run['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.01)
        run = store.get(run['id'])

    assert run['status'] == 'complete'
    assert run['report']['candidates'][0]['research_scope']['sessions'] == ['new_york']
    candidate = run['report']['candidates'][0]
    assert candidate['configuration']['instrument']['symbol'] == 'Germany 40'
    assert candidate['configuration']['timeframe'] == request.timeframe
    assert candidate['configuration']['strategy']['name'] == request.strategy_name


def test_research_configures_each_instrument_and_timeframe_independently(tmp_path):
    def profile_for(symbol):
        return Asset(symbol=symbol).profile.model_copy(update={
            'commission_per_lot': 0, 'financing_long': 0, 'financing_short': 0,
            'costs_confirmed': True, 'cost_source': 'test fixture',
            'rollover_confirmed': True, 'rollover_source': 'test fixture',
            'slippage_confirmed': True, 'slippage_source': 'test fixture',
            'specification_confirmed': True,
            'specification_source': 'test fixture',
            'contract_size': 1, 'tick_size': .01, 'tick_value': .01, 'point': .01,
            'digits': 2, 'volume_min': .1, 'volume_max': 100, 'volume_step': .1,
            'profit_currency': 'USD', 'account_currency': 'USD',
            'calculation_mode': 4, 'order_mode': 49, 'trade_mode': 4,
            'specification_fingerprint': ('a' if symbol == 'EURUSD.a' else 'b') * 64,
            'session': Session(weekdays=list(range(7)), source='test fixture', confirmed=True),
        })

    request = AnalysisRequest(
        assets=[
            Asset(symbol='EURUSD.a', timeframe='M5', profile=profile_for('EURUSD.a')),
            Asset(symbol='XAUUSD.pro', timeframe='M30', profile=profile_for('XAUUSD.pro')),
        ],
        days=7,
    )
    observed = []

    def loader(asset, body, runner, start, end):
        observed.append((asset.symbol, body.timeframe, body.strategy.symbol, body.strategy.timeframe))
        bars = []
        for index, ts in enumerate(range(start, end, body.interval)):
            opening = 100 + index * .001
            bars.append(Bar(timestamp=ts, open=opening, high=opening + .01, low=opening - .01,
                            close=opening + .005))
        return bars, asset.profile, {
            'warnings': [], 'account': 1, 'server': 'demo', 'symbol': asset.symbol,
            'asset_class': asset.profile.asset_class, 'broker_group': asset.profile.broker_group,
            'specification_fingerprint': asset.profile.specification_fingerprint,
        }, 0

    def validator(bars, body, profile, symbol, progress):
        progress('Fixture validation complete')
        return {'passed': True, 'checks': {'fixture_passed': True},
                'selected_strategy': body.strategy.model_dump(),
                'holdout': {'total_trades': 20, 'total_pnl': 1, 'profit_factor': 1.2},
                'oos_trades': 100, 'oos_pnl': 1}

    store = AnalysisJobs(tmp_path / 'multi-analysis.sqlite3', loader=loader, validator=validator)
    run = store.create(request, runner=object())
    deadline = time.monotonic() + 5
    while run['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.01)
        run = store.get(run['id'])

    assert run['status'] == 'complete'
    assert observed == [
        ('EURUSD.a', 'M5', 'EURUSD.a', 'M5'),
        ('XAUUSD.pro', 'M30', 'XAUUSD.pro', 'M30'),
    ]
    assert {candidate['configuration']['timeframe'] for candidate in run['report']['candidates']} == {'M5', 'M30'}
    assert len(run['report']['relationships']['by_timeframe']) == 2


def test_market_behavior_is_descriptive_and_deterministic():
    bars = [Bar(timestamp=i * 300, open=100 + i * .01, high=101 + i * .01,
                low=99 + i * .01, close=100 + i * .01) for i in range(40)]
    result = market_behavior(bars, 300)
    assert result['status'] == 'ok'
    assert result['regime'] in {'trending', 'mixed', 'mean_reverting'}
    assert result == market_behavior(bars, 300)


def test_weekly_market_behavior_annualizes_over_52_bars():
    bars = [Bar(timestamp=i * 7 * 86400, open=100 + i, high=102 + i,
                low=99 + i, close=100 + i) for i in range(40)]
    log_returns = [math.log(current.close / previous.close)
                   for previous, current in zip(bars, bars[1:])]
    result = market_behavior(bars, 7 * 86400)
    assert result['annualized_volatility'] == pytest.approx(stdev(log_returns) * math.sqrt(52))


def test_walk_forward_selects_only_from_training(monkeypatch):
    calls = []
    def simulate(data, config, symbol, timeframe, **kwargs):
        calls.append((data[0].timestamp, data[-1].timestamp, config.min_confluence))
        return SimpleNamespace(total_trades=5, total_pnl_pct=config.min_confluence,
                               max_drawdown_pct=0, to_dict=lambda: {})
    monkeypatch.setattr("app.backtesting.research.simulate", simulate)
    data = candles(400)
    result = walk_forward(data, [EngineConfig(min_confluence=1), EngineConfig(min_confluence=2)],
                          2, warmup_bars=30)
    assert len(result["reports"]) == 2
    for fold in result["folds"]:
        assert fold["train_end"] < fold["test_start"]
        assert fold["selected_config"]["min_confluence"] == 2
    assert calls[0][1] == data[199].timestamp
    assert calls[2][0] == data[170].timestamp  # history used for warmup only
