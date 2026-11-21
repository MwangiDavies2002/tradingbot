import pytest


pytestmark = pytest.mark.skipif(
    pytest.importorskip("MetaTrader5", reason="MetaTrader5 package unavailable") is None,
    reason="MetaTrader5 package unavailable",
)


@pytest.fixture
def mt5():
    import MetaTrader5 as terminal
    assert terminal.initialize()
    yield terminal
    terminal.shutdown()


@pytest.mark.parametrize("symbol", [
    "EURUSD", "GBPUSD", "XAUUSD", "Germany 40", "US 500",
    "Volatility 75 Index", "Volatility 100 Index", "Crash 1000 Index", "Step Index",
])
def test_instrument_matrix_is_read_only(mt5, monkeypatch, symbol):
    info = mt5.symbol_info(symbol)
    if info is None:
        pytest.skip(f"{symbol} unavailable on this broker")
    monkeypatch.setattr(mt5, "order_send", lambda *args, **kwargs:
                        pytest.fail("instrument audit attempted order_send"))
    mt5.symbol_select(symbol, True)
    tick = mt5.symbol_info_tick(symbol)
    assert tick is not None
    assert info.trade_contract_size > 0
    assert info.trade_tick_size > 0
    assert info.volume_min > 0
    assert info.volume_min <= info.volume_max
    assert info.volume_step > 0
    for timeframe in ("M1", "M5", "M15", "H1"):
        period = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
        if period is not None:
            bars = mt5.copy_rates_from_pos(symbol, period, 0, 100)
            assert bars is not None
