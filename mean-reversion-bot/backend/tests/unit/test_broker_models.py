from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.config import Settings, settings
from app.execution.broker_registry import broker_status
from app.execution.safety import account_scope, validate_account
from app.core.engine.ml_model import predict
from app.core.engine.signal_engine import EngineConfig, SignalEngine
from app.core.lsl.lsl_detector import Candle


def candles(count=110):
    return [Candle(i * 60, 100 + i, 102 + i, 99 + i, 101 + i) for i in range(count)]


@pytest.mark.parametrize("broker", ["oanda", "fxcm"])
@pytest.mark.asyncio
async def test_unsupported_broker_cannot_start_or_validate(monkeypatch, broker):
    from app.bot import BotRunner
    from app.api.routes.bot_control import start_bot
    monkeypatch.setattr(settings, "BROKER", broker)
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await start_bot(SimpleNamespace(), db)
    assert exc.value.status_code == 409
    assert not db.mock_calls
    with pytest.raises(ValueError, match="not implemented"):
        await BotRunner()._setup()
    with pytest.raises(ValueError, match="not implemented"):
        validate_account(settings, SimpleNamespace())


def test_broker_normalization_and_configuration():
    cfg = Settings(_env_file=None, BROKER=" Deriv ")
    assert cfg.BROKER == "deriv"
    assert account_scope(cfg) == "deriv:demo:VRTC123"
    cfg = Settings(_env_file=None, BROKER=" OANDA ", OANDA_ACCOUNT_ID="practice-account",
                   OANDA_API_TOKEN="test-token", OANDA_ENVIRONMENT=" Practice ")
    assert account_scope(cfg) == "oanda:practice:practice-account"
    assert broker_status(cfg) == {"broker": "oanda", "environment": "practice",
                                  "configured": True, "execution_ready": False}
    with pytest.raises(ValueError):
        Settings(_env_file=None, BROKER="unknown")


@pytest.mark.parametrize("selection", [
    {"model_strategy": "linear_regression"}, {"model_strategy": "time_series_nn"},
    {"use_linear_regression": True}, {"use_time_series_nn": True},
])
def test_unimplemented_models_rejected_before_execution(selection):
    from app.api.routes.backtest import BacktestRequest
    with pytest.raises(ValueError, match="not implemented"):
        EngineConfig(**selection)
    with pytest.raises(ValueError, match="not implemented"):
        BacktestRequest(symbols=["R_75"], **selection)


def test_classifier_sample_boundary_and_determinism():
    assert predict(candles(100)) == (None, 0.0)
    result = predict(candles(101))
    assert result[0] == "buy"
    assert 0.56 <= result[1] <= 1.0
    assert predict(candles(101)) == result


@pytest.mark.parametrize("bad_close", [0, -1, float("nan"), float("inf")])
def test_classifier_rejects_invalid_data(bad_close):
    data = candles()
    data[-1].close = bad_close
    with pytest.raises(ValueError, match="finite, positive"):
        predict(data)


def test_classifier_rejects_out_of_order_data():
    with pytest.raises(ValueError, match="chronological"):
        predict(list(reversed(candles())))


def test_model_abstention_blocks_indicator_fallback(monkeypatch):
    monkeypatch.setattr("app.core.engine.ml_model.predict", lambda _: (None, 0.51))
    engine = SignalEngine(EngineConfig(model_strategy="logistic_regression", use_hurst=False))
    engine.initialise(1000)
    result = engine.evaluate(candles(), htf_bias="buy")
    assert not result.should_trade
    assert result.reason == "model_abstained"


def test_tree_selection_is_shared_by_all_engine_callers():
    assert EngineConfig(model_strategy="tree").use_tree_model
