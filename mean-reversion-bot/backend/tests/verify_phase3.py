import sys
import os
from datetime import datetime
from collections import deque

# Add current directory to path
sys.path.append(os.getcwd() + "/mean-reversion-bot/backend")

from app.core.engine.signal_engine import SignalEngine, EngineConfig
from app.core.lsl.lsl_detector import Candle, LiquidityZone, SwingMap, GrabPhase, GrabDirection, LSLSignal
from app.execution.order_manager import Position, PositionStatus

def test_lsl_phase_3_4_transitions():
    print("Testing LSL Phase 3 (Grab) & Phase 4 (Reversal) Transitions...")
    config = EngineConfig(use_lsl=True, use_hurst=False, min_confluence=1)
    engine = SignalEngine(config=config)
    
    # Create candles approaching a high zone
    zone_price = 100.0
    candles = []
    for i in range(50):
        price = 95.0 + (i * 0.05)
        candles.append(Candle(timestamp=i*60, open=price, high=price+0.1, low=price-0.1, close=price+0.05, volume=100.0))
    
    # 1. Simulate Phase 3: Grab (spike through zone, close above/below depending on type)
    # For sell-side grab: spike ABOVE, close BELOW
    grab_candle = Candle(timestamp=50*60, open=98.0, high=102.0, low=97.5, close=99.0, volume=500.0)
    candles.append(grab_candle)
    
    decision = engine.evaluate(candles, symbol="TEST", timeframe="M1")
    print(f"Decision after Grab: {decision.reason} | Score: {decision.confluence_score}")
    
    # LSL confirmed grab should trigger a SELL signal
    assert decision.direction == "sell"
    assert decision.should_trade == True
    assert "lsl" in decision.reason or "grab" in decision.reason.lower()
    print("DONE: Phase 3/4 LSL entry verified!")

def test_safety_order_scaling():
    print("\nTesting Phase 3 Safety Order Scaling...")
    config = EngineConfig(
        use_safety_orders=True,
        max_safety_orders=3,
        safety_order_step_atr=1.0,
        safety_order_volume_mult=2.0, # Martingale
        min_confluence=1
    )
    engine = SignalEngine(config=config)
    
    # ATR will be around 1.0
    candles = [Candle(timestamp=i*60, open=100.0, high=101.0, low=99.0, close=100.0, volume=100.0) for i in range(100)]
    
    # Active BUY position at 100.0
    pos = Position(
        trade_id="test_trade", contract_id=123, symbol="TEST", timeframe="M1",
        direction="buy", contract_type="MULTUP", entry_price=100.0,
        stop_loss=90.0, take_profit=110.0, stake=10.0, status=PositionStatus.OPEN,
        order_index=0
    )
    
    # 1. Price is still 100.0 -> No safety order
    decision = engine.evaluate(candles, symbol="TEST", timeframe="M1", active_position=pos)
    print(f"Decision at entry price: {decision.reason}")
    assert decision.should_trade == False
    
    # 2. Price drops to 98.9 (1.1 ATR away) -> Safety Order #1
    candles.append(Candle(timestamp=101*60, open=99.0, high=99.0, low=98.5, close=98.9, volume=100.0))
    decision = engine.evaluate(candles, symbol="TEST", timeframe="M1", active_position=pos)
    print(f"Decision at 98.9 (-1.1 ATR): {decision.reason} | Stake: {decision.stake}")
    
    assert decision.should_trade == True
    assert decision.is_safety_order == True
    assert decision.order_index == 1
    assert decision.stake == 20.0 # Martingale multiplier applied
    
    print("DONE: Phase 3 Safety Order scaling verified!")

if __name__ == "__main__":
    try:
        test_lsl_phase_3_4_transitions()
        test_safety_order_scaling()
        print("\nAll Phase 3 logic tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
