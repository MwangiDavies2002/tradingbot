import pytest
from app.core.engine.signal_engine import EngineConfig, SignalEngine
from app.core.engine.confluence import ConfluenceScorer
from app.core.lsl.lsl_detector import Candle


def config(**changes):
    flags = {name: False for name in EngineConfig.__dataclass_fields__ if name.startswith("use_")}
    return EngineConfig(**{**flags, "use_crt": True, "min_confluence": 1, **changes})


@pytest.mark.parametrize("side,last", [
    ("buy", (100, 101, 98, 100.5)),
    ("sell", (100, 102, 99, 99.5)),
])
def test_crt_supplies_direction_and_audited_point(side, last):
    bars = [Candle(i * 300, 100, 101, 99, 100, 100) for i in range(60)]
    bars[-1] = Candle(59 * 300, *last, 100)
    engine = SignalEngine(config())
    engine.initialise(10000)
    decision = engine.evaluate(bars, symbol="GER40", timeframe="M5")
    assert decision.direction == side
    assert decision.confluence.breakdown.crt_points == 1
    assert decision.confluence.breakdown.to_dict()["crt"] == 1
    assert decision.confluence.score == 1
    disabled = SignalEngine(config(use_crt=False))
    disabled.initialise(10000)
    assert disabled.evaluate(bars).reason == "no_clear_direction"


def test_crt_requires_sweep_and_midpoint_reclaim():
    bars = [Candle(i * 300, 100, 101, 99, 100, 100) for i in range(60)]
    engine = SignalEngine(config())
    engine.initialise(10000)
    assert engine.evaluate(bars).reason == "no_clear_direction"
    bars[-1] = Candle(59 * 300, 100, 101, 98, 99, 100)
    assert engine.evaluate(bars).reason == "no_clear_direction"


def test_crt_scores_only_matching_direction_and_can_reach_four():
    scorer = ConfluenceScorer(threshold_valid=4)
    matched = scorer.score("buy", rsi=20, volume_ratio=2, crt_direction="buy")
    assert matched.score == 4 and matched.is_valid_entry
    opposite = scorer.score("sell", rsi=80, volume_ratio=2, crt_direction="buy")
    assert opposite.score == 3 and not opposite.is_valid_entry


def test_smt_is_rejected_instead_of_silently_ignored():
    with pytest.raises(ValueError, match="comparison-market history"):
        SignalEngine(config(use_smt=True))


@pytest.mark.asyncio
async def test_backtest_rejects_smt_before_history_fetch():
    from fastapi import HTTPException
    from app.api.routes.backtest import BacktestRequest, run_backtest
    with pytest.raises(HTTPException) as caught:
        await run_backtest(BacktestRequest(symbols=["GER40"], use_smt=True), None, None)
    assert caught.value.status_code == 422
    assert "comparison-market history" in caught.value.detail

