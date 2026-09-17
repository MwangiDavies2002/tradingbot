# Phase 3: Advanced Execution & Scale-Out (DCA)

> Experimental feature overview. The risk-bypass and unrestricted martingale behavior described below is not supported: all entries face execution risk caps and scaling size is bounded. Scaling/backtest parity remains unvalidated. See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).

## Overview
Phase 3 transitions the bot from simple single-entry mean reversion to a professional-grade execution system capable of scaling into positions during extreme volatility. It also fully integrates the Liquidity Simulation Logic (LSL) as the primary confirmation for reversals.

## Key Components

### 1. Liquidity Simulation Logic (LSL) - Phases 3 & 4
- **Phase 3 (Grab)**: Price spikes through a mapped liquidity zone (Swing H/L, Order Block, etc.) to trigger stops.
- **Phase 4 (Reversal)**: Price closes back inside the zone, signaling a confirmed grab and reversal entry.
- **Priority**: LSL signals now take highest priority in the `SignalEngine` direction determination.
- **Dashboard Support**: The engine now emits early LSL phases (Approaching/Grab) to allow for preemptive dashboard alerts.

### 2. Multi-Entry Scaling (Safety Orders / DCA)
- **Mechanism**: If a trade is active but price continues to deviate from the mean (moving into drawdown), the bot can now place "Safety Orders" to improve the average entry price.
- **Configuration**:
  - `max_safety_orders`: Limits the number of additional entries (default 3).
  - `safety_order_step_atr`: ATR-based distance between entries (default 1.0 ATR).
  - `safety_order_volume_mult`: Multiplier for each subsequent stake (e.g., 2.0 for Martingale scaling).
- **Execution Flow**:
  - `TickConsumer` identifies active positions per symbol.
  - `SignalEngine` evaluates the distance from the initial entry.
  - `OrderManager` executes the scaling order, bypassing the global max position limit for existing trades.

### 3. Execution Safety Gates (Scale-Out)
- **Breakeven Management**: Safety orders improve the average price, allowing the `PositionSizer` to adjust the Take Profit (TP) level to the new aggregate mean.
- **Risk Control**: Each safety order is snapshotted in the `execution_records` database table, maintaining full journal transparency.

## Verification
- [x] LSL Phase 3/4 Transitions (Verified via `verify_phase3.py`)
- [x] Safety Order Distance Detection (Verified via `verify_phase3.py`)
- [x] Martingale Stake Scaling (Verified)
- [x] Tick Consumer Scaling Bridge (Verified)

## Operational Usage
To enable Safety Orders:
1. Set `use_safety_orders = True` in `EngineConfig` (or via API/Dashboard).
2. Configure `max_safety_orders` and `safety_order_step_atr` based on instrument volatility.
3. The bot will automatically manage entries for active positions without requiring manual intervention.
