import pytest

from app.core.engine.signal_engine import EngineConfig
from app.core.hybrid.strategy import HybridConfig, HybridStrategy
from app.core.hybrid.regime import ema
from app.core.lsl.lsl_detector import Candle


@pytest.mark.parametrize("direction,sign", [("buy", 1), ("sell", -1)])
def test_expansion_then_value_pullback_is_scored_symmetrically(direction, sign):
    strategy = HybridStrategy()
    prior = [Candle(i * 300, p, p + .1, p - .1, p, 10)
             for i, p in enumerate([100] * 60 + [100 + sign * 4] * 20)]
    mean = ema([c.close for c in prior], 50)
    close = mean + sign * .1
    current = Candle(80 * 300, 100 + sign * 4, max(100 + sign * 4, close) + .2,
                     min(100 + sign * 4, close) - .2, close, 10)
    levels, touched = strategy.value_levels(prior + [current], direction, 1)
    assert "EMA_PULLBACK" in touched
    assert levels["EMA_PULLBACK"] == pytest.approx(mean)
    extended = 100 + sign * 20
    _, touched = strategy.value_levels(prior + [Candle(80 * 300, extended, extended + .1, extended - .1, extended, 10)], direction, 1)
    assert not touched


def test_hybrid_does_not_mutate_live_config_or_enable_safety_orders():
    cfg = EngineConfig(use_hurst=True, use_safety_orders=True)
    strategy = HybridStrategy(cfg)
    assert cfg.use_safety_orders and cfg.use_hurst
    assert not strategy.trend.cfg.use_safety_orders
    assert not strategy.trend.cfg.use_hurst
    assert strategy.mr.cfg.use_hurst


@pytest.mark.parametrize("kwargs", [
    {"tranches": (.5, .6)}, {"exit_allocations": (.5, .5)},
    {"trail_mode": "breakeven"}, {"max_trade_risk_percent": float("nan")},
])
def test_invalid_hybrid_configuration(kwargs):
    with pytest.raises(ValueError):
        HybridConfig(**kwargs)


@pytest.mark.parametrize("direction,sign", [("buy", 1), ("sell", -1)])
@pytest.mark.parametrize("mode", ["structure", "atr", "ema", "vwap", "vwma"])
def test_runner_trails_never_increase_risk(mode, direction, sign):
    import math
    from app.core.hybrid.campaign import TradeCampaign, InstrumentSpec
    from app.core.hybrid.regime import Regime
    strategy = HybridStrategy(config=HybridConfig(trail_mode=mode, value_period=20))
    c = TradeCampaign("test", "TEST", direction, Regime.BULLISH, {}, InstrumentSpec("TEST", 1, .01, .01), 10000)
    c.setup(0, 100)
    c.open_probe("probe", 0, 100, 100 - sign * 5)
    c.start_runner(1, 100)
    bars = []
    tightened = False
    for i in range(1, 100):
        p = 100 + sign * (.1 * i + .7 * math.sin(i * math.pi / 6))
        bars.append(Candle(i * 300, p - sign * .1, p + .2, p - .2, p, 10))
        if len(bars) > 60:
            before, old_stop = c.current_open_risk, c.entries[0].stop
            tightened |= strategy.trail(c, bars, i * 300 + 300)
            assert c.current_open_risk <= before + 1e-9
            assert sign * (c.entries[0].stop - old_stop) >= -1e-9
    assert tightened
