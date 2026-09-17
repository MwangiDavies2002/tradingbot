# Phase 6: Advanced Analytics & Automated Recovery

> Corrections: recent-trade cash P&L alone cannot establish annualized Sharpe or account drawdown. The API now returns unavailable values for those metrics instead of assuming a starting balance. See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for verification and operational boundaries.

## Overview
Phase 6 enhances the bot's operational robustness and provides deeper insights into strategy performance. It introduces an automated "Recovery Mode" to handle process crashes and advanced risk-adjusted metrics to the dashboard.

## Key Components

### 1. Advanced Analytics Engine
- **Sharpe Ratio**: Annualized risk-adjusted return calculation based on trade-by-trade P&L volatility.
- **Max Drawdown (MDD)**: Historical peak-to-valley drawdown percentage, providing a clear view of the strategy's risk profile.
- **Efficiency Metrics**: Profit Factor and Win Rate are now augmented with Average Win/Loss ratios in the real-time dashboard.
- **Implementation**: Handled via the `/api/bot/performance` endpoint in `bot_control.py` using `numpy`.

### 2. Automated Recovery Mode
- **Fault Tolerance**: The bot runner (`bot.py`) now includes a supervised retry loop.
- **Mechanism**:
  - Automatically attempts to restart the trading loop after fatal errors (e.g., websocket disconnects, API timeouts).
  - Implements a progressive retry strategy (5 attempts with 10s cooling period).
  - Sends "Recovery Mode" alerts via Telegram/AlertManager when an automated restart is triggered.
- **Safety**: If the maximum retry count is reached, the bot halts and requires manual operator intervention, preventing infinite crash loops.

### 3. Dashboard Integration
- **Real-Time Stats**: A new analytics row in the `Dashboard.tsx` displays Sharpe Ratio and Max Drawdown.
- **API Bridging**: The TypeScript client now supports the expanded performance metrics.

## Verification
- [x] Sharpe Ratio & MDD Logic (Integrated into `bot_control.py`)
- [x] Recovery Mode Loop (Integrated into `bot.py`)
- [x] Frontend Visualization (Integrated into `Dashboard.tsx`)

## Operational Usage
1. The bot will automatically use Recovery Mode upon startup via `python -m app.bot`.
2. Monitor the new "Sharpe Ratio" and "Max Drawdown" metrics on the main dashboard to evaluate strategy performance over time.
3. If the bot enters Recovery Mode, check the logs in the "Logs" tab to identify the root cause of the restart.
