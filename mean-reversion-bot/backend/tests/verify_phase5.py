import sys
import os
from datetime import datetime

# Add current directory to path
sys.path.append(os.getcwd() + "/mean-reversion-bot/backend")

from app.core.engine.signal_engine import SignalEngine, EngineConfig
from app.core.lsl.lsl_detector import Candle
from app.execution.order_manager import Position, PositionStatus, OrderManager, CloseReason
from app.core.risk.circuit_breaker import CircuitBreaker

def test_trailing_stop():
    print("Testing Phase 5 Trailing Stop Logic...")
    
    class MockSettings:
        def __init__(self):
            self.use_trailing_stop = True
            self.trailing_stop_atr = 1.5
            self.current_atr = 1.0

    settings = MockSettings()
    cb = CircuitBreaker()
    manager = OrderManager(client=None, circuit_breaker=cb, settings=settings)
    
    # Create an open BUY position
    pos = Position(
        trade_id="trail_test", contract_id=123, symbol="R_75", timeframe="M1",
        direction="buy", contract_type="MULTUP", entry_price=100.0,
        stop_loss=95.0, take_profit=110.0, stake=10.0, status=PositionStatus.OPEN
    )
    manager._positions[pos.trade_id] = pos
    
    # 1. Price moves up to 105.0. 
    # Trail distance = 1.5 * 1.0 = 1.5. 
    # New SL = 105.0 - 1.5 = 103.5.
    # 103.5 > 95.0, so SL should update.
    import asyncio
    async def run_test():
        await manager.monitor_tick("R_75", 105.0)
        print(f"New SL after price move to 105.0: {pos.stop_loss}")
        assert pos.stop_loss == 103.5
        
        # 2. Price moves down to 104.0. SL should NOT move down.
        await manager.monitor_tick("R_75", 104.0)
        print(f"SL after price drop to 104.0: {pos.stop_loss}")
        assert pos.stop_loss == 103.5
        
        # 3. Price moves up to 110.0. 
        # New SL = 110.0 - 1.5 = 108.5.
        await manager.monitor_tick("R_75", 110.0)
        print(f"New SL after price move to 110.0: {pos.stop_loss}")
        assert pos.stop_loss == 108.5

    asyncio.run(run_test())
    print("DONE: Trailing Stop verified!")

def test_multi_symbol_guards():
    print("\nTesting Phase 5 Multi-Symbol Guards...")
    config = EngineConfig(
        max_concurrent_trades=2,
        max_total_exposure=0.04, # 4%
        min_confluence=1
    )
    engine = SignalEngine(config=config)
    engine.initialise(1000.0)
    
    candles = [Candle(timestamp=i*60, open=100.0, high=101.0, low=99.0, close=100.0, volume=100.0) for i in range(100)]
    
    # 1. Current state: 2 positions open (limit reached)
    decision = engine.evaluate(
        candles, symbol="R_100", timeframe="M1",
        total_open_positions=2, total_open_risk_pct=0.02
    )
    print(f"Decision with 2 positions: {decision.reason}")
    assert decision.should_trade == False
    assert decision.reason == "max_concurrent_trades_exceeded"
    
    # 2. Current state: 1 position open but risk is 5% (limit reached)
    decision = engine.evaluate(
        candles, symbol="R_100", timeframe="M1",
        total_open_positions=1, total_open_risk_pct=0.05
    )
    print(f"Decision with 5% risk: {decision.reason}")
    assert decision.should_trade == False
    assert decision.reason == "max_total_exposure_exceeded"
    
    # 3. Scaling order for existing position should bypass limits
    pos = Position(
        trade_id="scale_test", contract_id=456, symbol="R_75", timeframe="M1",
        direction="buy", contract_type="MULTUP", entry_price=100.0,
        stop_loss=90.0, take_profit=110.0, stake=10.0, status=PositionStatus.OPEN
    )
    # Force safety order evaluation by moving price away
    candles_scale = candles + [Candle(timestamp=200*60, open=98.0, high=98.0, low=98.0, close=98.0, volume=100.0)]
    engine.cfg.use_safety_orders = True
    
    decision = engine.evaluate(
        candles_scale, symbol="R_75", timeframe="M1",
        active_position=pos,
        total_open_positions=5, total_open_risk_pct=0.20 # Extreme limits
    )
    print(f"Decision for scaling with 5 positions: {decision.reason}")
    # It might still be False if confluence is low, but should NOT be blocked by multi-symbol guards
    assert decision.reason != "max_concurrent_trades_exceeded"
    assert decision.reason != "max_total_exposure_exceeded"

    print("DONE: Multi-Symbol Guards verified!")

if __name__ == "__main__":
    try:
        test_trailing_stop()
        test_multi_symbol_guards()
        print("\nAll Phase 5 logic tests passed!")
    except Exception as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
