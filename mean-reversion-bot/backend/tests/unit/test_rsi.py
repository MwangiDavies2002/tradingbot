import pytest
from app.core.indicators.rsi import RSIIndicator
from app.core.lsl.lsl_detector import Candle

def test_rsi_oversold():
    # RSI period 14, 15 candles to have 1 RSI value
    # Prices going down to trigger oversold
    prices = [100.0, 98.0, 96.0, 94.0, 92.0, 90.0, 88.0, 86.0, 84.0, 82.0, 80.0, 78.0, 76.0, 74.0, 72.0]
    candles = [Candle(timestamp=i*60, open=p, high=p+1, low=p-1, close=p, volume=100) for i, p in enumerate(prices)]
    
    rsi = RSIIndicator(period=14)
    result = rsi.compute(candles)
    
    assert result is not None
    assert result.value < 30
    assert result.direction == "buy"
    assert result.is_oversold is True

def test_rsi_overbought():
    # Prices going up to trigger overbought
    prices = [100.0, 102.0, 104.0, 106.0, 108.0, 110.0, 112.0, 114.0, 116.0, 118.0, 120.0, 122.0, 124.0, 126.0, 128.0]
    candles = [Candle(timestamp=i*60, open=p, high=p+1, low=p-1, close=p, volume=100) for i, p in enumerate(prices)]
    
    rsi = RSIIndicator(period=14)
    result = rsi.compute(candles)
    
    assert result is not None
    assert result.value > 70
    assert result.direction == "sell"
    assert result.is_overbought is True

def test_rsi_insufficient_data():
    candles = [Candle(timestamp=i*60, open=100, high=101, low=99, close=100, volume=100) for i in range(5)]
    rsi = RSIIndicator(period=14)
    result = rsi.compute(candles)
    assert result is None
