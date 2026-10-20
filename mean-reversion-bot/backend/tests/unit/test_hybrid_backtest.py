from types import SimpleNamespace
import json
import math

import pytest

from app.backtesting.hybrid import CampaignBacktester, performance
from app.backtesting.backtest_engine import BacktestEngine
from app.core.engine.signal_engine import EngineConfig, SignalEngine
from app.core.hybrid.campaign import InstrumentSpec, Confirmation
from app.core.hybrid.regime import Regime, RegimeConfig, RegimeResult
from app.core.hybrid.strategy import HybridConfig, HybridSetup, HybridStrategy
from app.core.lsl.lsl_detector import Candle


def history(direction="buy", n=50):
    sign = 1 if direction == "buy" else -1
    bars = []
    for i in range(n):
        p = 100 + sign * max(0, i - 31) * 2
        bars.append(Candle(i * 300, p, p + .2, p - .2, p, 10))
    return bars


class ScriptedStrategy(HybridStrategy):
    """Deterministic evidence provider; execution and ledger are the real implementation."""
    direction = "buy"

    def __init__(self, engine_config, config, cb=None):
        super().__init__(engine_config, config, cb)
        self.emitted = False
        self.regime_detector = SimpleNamespace(classify=lambda histories: RegimeResult(Regime.RANGE))

    def analyse(self, candles, histories, symbol, timeframe, base_seconds, baseline=False, **kwargs):
        if self.emitted:
            return None, RegimeResult(Regime.RANGE)
        self.emitted = True
        sign = 1 if self.direction == "buy" else -1
        return HybridSetup(self.direction, 100 - sign * 5, 100 + sign * 45, 8,
                           ("LIQUIDITY_SWEEP",), None, Regime.RANGE), RegimeResult(Regime.RANGE)

    def analyse_add(self, campaign, candles, regime, symbol, timeframe, base_seconds):
        ts = candles[-1].timestamp + base_seconds
        return Confirmation(f"BOS:{ts}", ts, campaign.direction, 8, ("BOS_CONFIRMED",)), campaign.entries[0].stop

    def trail(self, campaign, candles, timestamp):
        return False

    def targets(self, campaign, candles):
        return [(f"TP{i}", 100 + campaign.sign * (5 * i), "SYNTHETIC_OBJECTIVE") for i in range(1, 4)]


class ScriptedShort(ScriptedStrategy):
    direction = "sell"


@pytest.fixture
def simulator():
    cfg = HybridConfig(regime=RegimeConfig(timeframes=(600,), ema_period=10))
    return CampaignBacktester(config=cfg, warmup_bars=30, slippage_pct=0, strategy_factory=ScriptedStrategy)


@pytest.mark.parametrize("variant,count", [("A", 1), ("B", 1), ("C", 4), ("D", 4)])
def test_variants_next_open_campaign_accounting_and_metrics(simulator, variant, count):
    report = simulator.run(history(), InstrumentSpec("TEST", 1, .01, .01), variant=variant)
    trades = [c for c in report["campaigns"] if c["entries"]]
    assert report["metrics"]["total_trades"] == len(trades) == 1
    c = trades[0]
    assert len(c["entries"]) == count
    assert c["entries"][0]["timestamp"] == 31 * 300
    assert c["initial_signal"]["timestamp"] == 31 * 300
    assert c["status"] == "CLOSED"
    assert c["current_open_risk"] == c["total_quantity"] == 0
    assert report["final_balance"] - report["initial_balance"] == pytest.approx(c["realized_pnl"])
    assert report["equity_curve"][-1]["equity"] == pytest.approx(report["final_balance"])
    assert report["metrics"]["maximum_campaign_risk"] <= 100
    assert report["metrics"]["sharpe_ratio"] is None
    assert report["by_regime"]["RANGE"]["total_trades"] == 1
    assert report["by_regime"]["TREND"]["total_trades"] == 0
    if variant == "D":
        assert [p["reason"] for p in c["partial_exits"]] == ["TP1", "TP2", "TP3", "END_OF_DATA"]
        assert any(e["action"] == "RUNNER" for e in c["events"])
        assert sum(p["quantity"] for p in c["partial_exits"]) == pytest.approx(sum(e["quantity"] for e in c["entries"]))
    else:
        assert all(p["reason"] == "END_OF_DATA" for p in c["partial_exits"])
    json.dumps(report, allow_nan=False)


def test_simulation_long_short_symmetry(simulator):
    spec = InstrumentSpec("TEST", 1, .01, .01)
    long = simulator.run(history(), spec)
    short_sim = CampaignBacktester(config=simulator.cfg, warmup_bars=30, slippage_pct=0, strategy_factory=ScriptedShort)
    short = short_sim.run(history("sell"), spec)
    assert long["metrics"] == short["metrics"]


def test_stop_first_and_gap_fill(simulator):
    bars = history()
    bars[32] = Candle(32 * 300, 90, 151, 89, 100, 10)
    report = simulator.run(bars, InstrumentSpec("TEST", 1, .01, .01), variant="D")
    c = report["campaigns"][0]
    assert c["status"] == "INVALIDATED"
    assert c["partial_exits"][0]["price"] == 90
    assert c["partial_exits"][0]["reason"] == "STOP_LOSS"
    assert c["realized_pnl"] == -50
    assert c["maximum_risk_used"] == 25
    assert not any(p["reason"] == "TP1" for p in c["partial_exits"])


def test_gap_invalidated_probe_never_opens(simulator):
    bars = history()
    bars[31] = Candle(31 * 300, 90, 91, 89, 90, 10)
    report = simulator.run(bars, InstrumentSpec("TEST", 1, .01, .01), variant="B")
    assert report["metrics"]["total_trades"] == 0
    assert report["final_balance"] == report["initial_balance"]
    assert report["campaigns"][0]["status"] == "INVALIDATED"


def test_different_instruments_explicit_values_and_costs_reconcile(simulator):
    reports = simulator.compare({"XAUUSD": history(), "GER40": history()}, {
        "XAUUSD": InstrumentSpec("XAUUSD", 100, .01, .01, commission=.1),
        "GER40": InstrumentSpec("GER40", 10, .01, .01, commission=.1),
    })
    assert set(reports["variants"]) == {"A", "B", "C", "D"}
    for group in reports["variants"].values():
        for symbol, report in group.items():
            assert symbol in report["by_instrument"]
            assert report["metrics"]["maximum_campaign_risk_percent"] <= 1.0 + 1e-9
            assert report["final_balance"] - report["initial_balance"] == pytest.approx(report["metrics"]["total_pnl"])
    assert reports["variants"]["B"]["XAUUSD"]["campaigns"][0]["entries"][0]["quantity"] < reports["variants"]["B"]["GER40"]["campaigns"][0]["entries"][0]["quantity"]


def test_reproducible_and_prefix_causal(simulator):
    spec = InstrumentSpec("TEST", 1, .01, .01)
    data = history()
    first = simulator.run(data, spec)
    assert first == simulator.run(data, spec)
    altered = data[:40] + [Candle(c.timestamp, 150, 151, 149, 150, 10) for c in data[40:]]
    second = simulator.run(altered, spec)
    cutoff = data[40].timestamp
    events1 = [e for e in first["campaigns"][0]["events"] if e["timestamp"] < cutoff]
    events2 = [e for e in second["campaigns"][0]["events"] if e["timestamp"] < cutoff]
    assert events1 == events2


def test_sharpe_requires_sufficient_daily_data():
    cfg = HybridConfig(min_sharpe_days=30)
    curve = [dict(ts=i * 86400, equity=10000 + 10 * i + 3 * math.sin(i)) for i in range(40)]
    assert performance([], curve, 10000, cfg)["sharpe_ratio"] is not None
    assert performance([], curve[:10], 10000, cfg)["sharpe_ratio"] is None
    flat = [dict(ts=i * 86400, equity=10000) for i in range(40)]
    assert performance([], flat, 10000, cfg)["sharpe_ratio"] is None


def test_original_backtester_exposes_comparison_and_does_not_mutate_config(monkeypatch):
    captured = {}
    monkeypatch.setattr(CampaignBacktester, "compare", lambda self, datasets, specs, *args: captured.update(datasets=datasets) or {"ok": True})
    cfg = EngineConfig()
    bt = BacktestEngine(SignalEngine(cfg))
    assert bt.run_comparison({"TEST": history()}, {"TEST": InstrumentSpec("TEST", 1, .01, .01)}) == {"ok": True}
    assert cfg == EngineConfig()
    assert "TEST" in captured["datasets"]


def test_real_signal_engine_integration_and_htf_no_lookahead():
    cfg = HybridConfig(value_period=5, regime=RegimeConfig(timeframes=(600, 1200), ema_period=20, swing_lookback=2))
    config = EngineConfig(min_confluence=2, use_hurst=False, use_crt=True, swing_lookback=3)
    candles = []
    for i in range(260):
        p = 100 + .03 * i + 2 * math.sin(i * math.pi / 10)
        prev = candles[-1].close if candles else p
        candles.append(Candle(i * 300, prev, max(prev, p) + .3 + .001 * i, min(prev, p) - .3 + .001 * i, p, 10))
    sim = CampaignBacktester(config, cfg, warmup_bars=60, slippage_pct=0)
    spec = InstrumentSpec("SYNTHETIC", 1, .01, .01)
    report = sim.run(candles, spec)
    assert report["metrics"]["total_trades"] > 0
    cutoff = candles[200].timestamp
    changed = candles[:200] + [Candle(c.timestamp, 150, 151, 149, 150, 10) for c in candles[200:]]
    alternate = sim.run(changed, spec)
    def events(r):
        return [e for c in r["campaigns"] for e in c["events"] if e["timestamp"] < cutoff]
    assert events(report) == events(alternate)
    assert all(c["maximum_risk_used"] <= c["risk_limit"] + 1e-8 for c in report["campaigns"])
    json.dumps(report, allow_nan=False)


def test_stale_confirmation_after_missing_bars_cannot_fill(simulator):
    bars = history()
    bars = bars[:31] + bars[34:]
    report = simulator.run(bars, InstrumentSpec("TEST", 1, .01, .01), variant="B")
    assert report["metrics"]["total_trades"] == 0
    assert any("STALE_CONFIRMATION" in e["reason_codes"] for e in report["campaigns"][0]["events"])


def test_unsupported_safety_orders_and_invalid_history_are_rejected():
    with pytest.raises(ValueError, match="safety orders"):
        CampaignBacktester(EngineConfig(use_safety_orders=True))
    sim = CampaignBacktester()
    with pytest.raises(ValueError):
        sim.run([Candle(0, 100, 90, 99, 100)], InstrumentSpec("TEST", 1, .01, .01))


def test_repeated_confirmations_cannot_duplicate_simulated_orders(simulator):
    class Repeated(ScriptedStrategy):
        def analyse_add(self, campaign, candles, regime, symbol, timeframe, base_seconds):
            ts = candles[-1].timestamp + base_seconds
            return Confirmation("ONE_BOS", ts, campaign.direction, 8, ("BOS_CONFIRMED",)), campaign.entries[0].stop
    simulator.strategy_factory = Repeated
    report = simulator.run(history(), InstrumentSpec("TEST", 1, .01, .01), variant="C")
    assert len(report["campaigns"][0]["entries"]) == 2


def test_trail_becomes_effective_on_following_bar(simulator):
    class Trail(ScriptedStrategy):
        def trail(self, campaign, candles, timestamp):
            if candles[-1].timestamp == 32 * 300:
                return campaign.move_stop(timestamp, candles[-1].close, 101)
            return False
    simulator.strategy_factory = Trail
    bars = history()
    bars[32] = Candle(32 * 300, 102, 103, 99, 102, 10)
    bars[33] = Candle(33 * 300, 104, 105, 100, 104, 10)
    report = simulator.run(bars, InstrumentSpec("TEST", 1, .01, .01), variant="B")
    c = report["campaigns"][0]
    assert c["partial_exits"][0]["timestamp"] == 33 * 300
    assert c["partial_exits"][0]["price"] == 101


def test_confirmed_opposing_regime_invalidates_at_next_open(simulator):
    class TrendFlip(ScriptedStrategy):
        def __init__(self, engine_config, config, cb=None):
            super().__init__(engine_config, config, cb)
            self.flip_calls = 0
            self.regime_detector = SimpleNamespace(classify=self.classify)
        def classify(self, histories):
            self.flip_calls += 1
            return RegimeResult(Regime.RANGE) if self.flip_calls < 5 else RegimeResult(Regime.BEARISH, True)
    simulator.strategy_factory = TrendFlip
    report = simulator.run(history(), InstrumentSpec("TEST", 1, .01, .01), variant="C")
    c = report["campaigns"][0]
    assert c["status"] == "INVALIDATED"
    assert c["partial_exits"][-1]["reason"] == "HTF_INVALIDATION"
    assert not c["pending_orders"]
    queued = next(e for e in c["events"] if e["action"] == "QUEUE_EXIT")
    exit = c["partial_exits"][-1]
    assert exit["timestamp"] >= queued["timestamp"]
    assert c["realized_pnl"] > 0
