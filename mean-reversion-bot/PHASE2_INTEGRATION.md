# Phase 2: Advanced Strategy Integration & Strategy Lab Enhancements

> Historical feature overview, using different numbering from the original roadmap. News scoring exists but is not automatically connected to worker news retrieval. See [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) for verified behavior and research limits.

## Overview
Phase 2 enhances the core `SignalEngine` and `BacktestEngine` by integrating news-driven signals, refining machine-learning-inspired models, and bridging the gap between Python and TradingView strategy definitions.

## Key Enhancements

### 1. News-Volatility Mode
- **Mechanism**: The bot now monitors high-impact news events (via `app.database.models.NewsEvent`) and assigns bonus confluence points to setups occurring during these periods.
- **Scoring**:
  - High Impact: +2 points
  - Medium Impact: +1 point
- **Implementation**:
  - `ConfluenceScorer`: Added `news_points` category.
  - `SignalEngine`: Added `news_impact` parameter to `evaluate()` and `use_news` / `news_mode` to `EngineConfig`.
  - **News-Only Entry**: If `use_news` is enabled and a high-impact event is active, the engine can now evaluate candidate directions even if technical indicators are neutral.

### 2. Refined Decision Tree (Tree Model)
- **File**: `backend/app/core/engine/tree_model.py`
- **Logic**: Replaced the simple placeholder with a multi-factor classification engine:
  - **Bullish (Buy)**: Z-Score ≤ -2.0 AND RSI ≤ 30 AND Price < EMA50.
  - **Bearish (Sell)**: Z-Score ≥ 2.0 AND RSI ≥ 70 AND Price > EMA50.
  - **Trend Guard**: Distance between EMA50 and EMA200 must be ≤ 3.0 ATR to ensure a mean-reverting environment.

### 3. Smart Money Concepts (SMC) Integration
- **Features**: Full support for Break of Structure (BOS) and Change of Character (CHoCH) in the confluence pipeline.
- **Confluence**: CHoCH events (trend reversals) now contribute +1 point to the total score, providing a structural confirmation for mean-reversion wicks.

### 4. Strategy Lab (Backtesting)
- **Walk-Forward Validation**: The `BacktestEngine` now supports `run_walk_forward`, splitting data into in-sample/out-of-sample folds to detect overfitting.
- **Indicator Toggles**: All 17 strategy components (LSL, SMC, Z-Score, RSI, VWAP, Hurst, etc.) are now fully toggleable via `EngineConfig`, allowing for precise strategy optimization.

## Verification Status
- [x] News Confluence Points (Verified via `verify_phase2.py`)
- [x] Tree Model Refinement (Verified via `verify_phase2.py`)
- [x] Signal Engine Integration (Verified)
- [x] Circuit Breaker & Hurst Safety Gates (Verified)

## Operational Usage
To enable News-Volatility mode in the worker:
1. Ensure the news scraper (`app/api/routes/news.py`) is active and populating the `news_events` table.
2. Set `use_news = True` in the `SignalEngine` configuration.
3. The worker will automatically fetch current news impact for the active symbol and apply the confluence bonus.
