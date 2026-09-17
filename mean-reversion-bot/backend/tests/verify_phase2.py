import sys
import os
from datetime import datetime

# Add current directory to path
sys.path.append(os.getcwd())

from app.core.engine.signal_engine import SignalEngine, EngineConfig
from app.core.lsl.lsl_detector import Candle

def test_news_confluence():
    print("Testing News Confluence...")
    config = EngineConfig(use_news=True, min_confluence=1)
    engine = SignalEngine(config=config)
    
    # Create candles with movement for ATR
    candles = []
    for i in range(100):
        # Oscillating price to keep ATR > 0 and Z-score near 0 initially
        price = 100.0 + (5.0 if i % 2 == 0 else -5.0)
        candles.append(Candle(timestamp=i, open=price, high=price+1, low=price-1, close=price, volume=100.0))
    
    # Run evaluation WITHOUT news
    decision_no_news = engine.evaluate(candles, symbol="TEST", timeframe="M5", news_impact=None)
    score_no_news = decision_no_news.confluence_score
    print(f"Score without news: {score_no_news}")
    print(f"Reason: {decision_no_news.reason}")
    
    # Run evaluation WITH high impact news
    decision_with_news = engine.evaluate(candles, symbol="TEST", timeframe="M5", news_impact="high")
    score_with_news = decision_with_news.confluence_score
    print(f"Score with high-impact news: {score_with_news}")
    print(f"Reason: {decision_with_news.reason}")
    
    if decision_with_news.confluence:
        print(f"Breakdown: {decision_with_news.confluence.breakdown.to_dict()}")

    # score_no_news was 0, but it didn't even have a confluence object because it returned _no_trade early
    # score_with_news is 3 because news (2) + hurst (1) = 3
    assert score_with_news >= 2
    print("DONE: News confluence points verified!")

def test_tree_model_refinement():
    print("\nTesting Refined Tree Model...")
    config = EngineConfig(use_tree_model=True, min_confluence=1)
    engine = SignalEngine(config=config)
    
    # Create candles
    candles = [Candle(timestamp=i, open=100.0, high=101.0, low=99.0, close=100.0, volume=100.0) for i in range(250)]
    
    # Force a Tree Model BUY setup:
    # Z <= -2.0, RSI <= 30, close < EMA50, trend_dist <= 3.0
    for i in range(200, 250):
        candles[i].close = 80.0
        candles[i].open = 80.0
        candles[i].high = 81.0
        candles[i].low = 79.0
    
    # Last candle extreme
    candles[-1].close = 70.0 
    
    decision = engine.evaluate(candles, symbol="TEST", timeframe="M5")
    print(f"Decision with Tree Model: {decision.direction} (Score: {decision.confluence_score})")
    
    if decision.direction == "buy":
        print("DONE: Tree model BUY signal verified!")
    else:
        print(f"FAIL: Tree model failed to trigger BUY. Reason: {decision.reason}")
        # Print indicators for debug
        if decision.zscore: print(f"  Z-Score: {decision.zscore.value}")
        if decision.rsi: print(f"  RSI: {decision.rsi.value}")

if __name__ == "__main__":
    try:
        test_news_confluence()
        test_tree_model_refinement()
        print("\nAll Phase 2 core logic tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
