from types import SimpleNamespace
import json
import pytest
from app.core.lsl.lsl_detector import Candle
from app.core.engine.signal_engine import EngineConfig, TradeDecision
from app.core.risk.position_sizer import PositionSizer
from app.backtesting.backtest_engine import BacktestEngine, BTTrade
from app.backtesting.research import monte_carlo, walk_forward
from app.data.validation import validate_candles


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
