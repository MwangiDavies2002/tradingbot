# Phase 5: Performance Optimization & Adaptive Risk

> Experimental overview. Trailing stops are not wired to validated worker settings or broker stop updates. Portfolio caps apply to scaling orders as well. No performance improvement is established by these descriptions. See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for the actual strategy-validation workflow.

## Overview
Phase 5 elevates the bot to professional-grade status by introducing dynamic profit protection, multi-symbol risk management, and integrated performance analytics. It focuses on maximizing the Sharpe ratio by reducing drawdown and improving execution efficiency.

## Key Components

### 1. Dynamic Trailing Stop (ATR-Based)
- **Mechanism**: Automatically moves the Stop Loss (SL) in favor of the trade as price moves towards the Take Profit (TP).
- **Configuration**:
  - `use_trailing_stop`: Toggles the feature.
  - `trailing_stop_atr`: Distance maintained from the current price (e.g., 1.5 ATR).
- **Implementation**: Handled in `OrderManager.monitor_tick` on every price update, ensuring minimal profit give-back during strong reversals.

### 2. Multi-Symbol Portfolio Risk
- **Exposure Limits**: Prevents the bot from over-leveraging by capping total exposure across all active trades.
- **Constraints**:
  - `max_concurrent_trades`: Maximum number of different symbols traded simultaneously (default 3).
  - `max_total_exposure`: Maximum aggregate risk as a percentage of account equity (default 5%).
- **Safety**: New entries are blocked if either limit is reached, while scaling orders (Phase 3) for existing positions are still permitted to manage drawdown.

### 3. Performance Reporting API
- **Endpoint**: `/api/bot/performance`
- **Metrics**:
  - Win Rate (%)
  - Profit Factor
  - Average Win vs. Average Loss
  - Total P&L
- **Audit Trail**: Provides a real-time summary of the last 100 trades to evaluate strategy efficiency and regime fit.

## Verification
- [x] Trailing Stop Logic (Integrated into `OrderManager`)
- [x] Multi-Symbol Exposure Gates (Integrated into `SignalEngine` & `TickConsumer`)
- [x] Performance Stats Calculation (Integrated into `bot_control.py`)

## Operational Usage
To enable Phase 5 features:
1. Update `EngineConfig` via the dashboard or `.env`.
2. Set `use_trailing_stop = True` for profit protection.
3. Configure `max_concurrent_trades` based on your total account equity and risk tolerance.
4. Monitor performance via the `/performance` endpoint or the upcoming "Analytics" dashboard tab.
