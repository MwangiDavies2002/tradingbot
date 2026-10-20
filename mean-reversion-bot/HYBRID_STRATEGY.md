# Hybrid strategy: architecture and implementation

## Phase 1: existing architecture

- `backend/app/core/engine/signal_engine.py`: candle-close orchestration, ATR volatility guard, Hurst trend suppression, directional selection, confluence and Deriv sizing. Existing CRT changes are preserved.
- `core/lsl/lsl_detector.py`: confirmed liquidity sweeps, rejection wicks and instrument-specific spike handling.
- `core/lsl/swing_mapper.py`: confirmed pivots, clustered liquidity levels, strength filtering.
- `core/lsl/zone_builder.py`: order blocks, fair value gaps, round numbers and previous session highs/lows.
- `core/engine/confluence.py`: direction-aware weighted indicator scoring and entry thresholds.
- `core/indicators/atr.py`: Wilder or SMA true-range smoothing, fast/slow volatility ratio. LSL also has a simple ATR helper.
- `core/risk/position_sizer.py`: ATR stops and Deriv stake sizing; this is not CFD lot sizing.
- `core/risk/circuit_breaker.py`, `drawdown_monitor.py`: equity drawdown, loss streak and concurrent-position guards.
- `execution/order_manager.py`: persisted order identity, execution safety, recovery, SL/TP monitoring and broker contract closing.
- `execution/deriv_client.py`, `broker_registry.py`, `mt5_demo.py`: broker transport, broker availability checks and isolated MT5 demo handling.
- `backtesting/backtest_engine.py`: validated OHLC, next-open fills, stop-first bars, costs, simulated circuit-breaker clock and attribution. Existing safety-order/trailing simulation is explicitly rejected.
- `tests/unit`, `tests/integration`: signals, execution safety, sizing/broker models, research, feeds and PostgreSQL safety. Frontend has separate unit and visual tests.

Existing safety orders are adverse-distance adds, so they are not reused for hybrid pyramiding. No working live functionality is removed.

## Phase 2: minimal extension

Create `core/hybrid/regime.py`, `campaign.py`, `risk.py`, `strategy.py` and `backtesting/hybrid.py`. Extend the existing confluence scorer with optional value-area points; default scores remain identical. Expose comparison through `BacktestEngine.run_comparison` and a standalone CLI. The hybrid adapter reuses existing signal evaluation and detectors, bypassing Hurst suppression only inside its own trend engine. Live engine defaults, APIs, database and broker execution remain unchanged.

Risk uses explicit instrument specifications: account-currency P&L per one price unit per quantity unit, quantity minimum/step/maximum, and commission per quantity per side. Supply broker-specific XAUUSD/GER40 specifications; there is no universal lot value. This simulation models linear instruments, not Deriv multiplier contract settlement.

Campaign equity is frozen at setup. Open risk sums individual tranche losses at their stops without crediting profitable stops. Realized losses and estimated exit commissions consume available budget. Risk is released only by partial closing or tightening stops. Stops never loosen. R is net realized P&L divided by initial probe risk; report maximum risk separately to avoid hiding deployed capital.

Validation is incremental: baseline, regime/risk, scale-in, scale-out, then comparison/integration. See the completion notes below for actual test results and simulation assumptions.

## Phases 3–5: components and behavior

`MarketRegime` requires agreement across configured completed HTFs. EMA slope/position and confirmed HH/HL or LH/LL establish a strong trend. Flat structure near EMA is RANGE; insufficient history or disagreement is UNKNOWN. Optional volume-backed VWAP can corroborate the classification. The default uses H1/H4 and EMA 200; supply at least 201 completed H4 bars plus sufficient pivot history. Missing constituent candles invalidate an HTF bucket.

`HybridStrategy` reuses the original signals and indicators. RANGE entries retain original MR rules. UNKNOWN blocks new hybrid entries and adds. Trend entries require prior expansion, a pullback to at least one scored value area and a fresh liquidity/structure/retest/reclaim event. A displacement-only setup is marked ADD_ONLY. A counter-trend probe requires the original score above the reversal threshold plus a fresh, aligned confirmed LSL sweep and CHoCH. An opposing strong regime closes an ordinary campaign at the next open; reversal probes retain their protective stop exception.

Value references include EMA, volume-backed VWAP/VWMA, existing order-block zones and previous breakout levels. Causal POC/VAH/VAL/HVN/LVN references may be supplied through `value_levels(..., supplied=...)`; this implementation does not invent volume-profile levels from tick volume. Context scores are capped, copied on each evaluation and do not double-count existing OB/BOS/LSL evidence.

`TradeCampaign` owns entries, FIFO partial exits, pending simulated orders, a deduplication ledger, state/status, risk and P&L. `CampaignRiskEngine` handles account-currency stop risk and entry sizing. Each tranche reserves its configured fraction of the frozen campaign budget, including fees and modeled exit slippage/spread. An add that cannot fit is rejected rather than rounded up or silently enlarged. Maximum trade risk uses percentage units: `max_trade_risk_percent=1.0` means 1%. All quantity units and point values come from `InstrumentSpec`.

Adds require a new event above the confirmation threshold, favorable price relative to both the last entry and remaining average, a noninvalidated stop and available campaign risk. Fresh displacement, BOS/CHoCH, sweep, VWAP reclaim/rejection, successful retest or a newly confirmed HL/LH can qualify. Accepted adds share a stop that can only tighten older entries. Confirmed structural tightening can release risk. Profitable stops never offset another tranche's loss in the risk calculation.

Scale-out begins after all eligible adds that occur before TP1. The exit base quantity is frozen when the first target is reached; adds stop after the first partial exit. TP1 uses nearby opposing mapped liquidity; TP2 uses a valid ordered previous-session high/low; TP3 uses the configured R multiple from the probe. Missing or unordered structural objectives use explicitly logged configurable R fallbacks. The remaining quantity becomes the runner. Sub-minimum partial slices are logged and retained for the runner rather than rounded up. The five trail modes are structure, ATR, EMA, VWAP and VWMA; no fixed-point breakeven rule is used.

States are recorded for setup, probe, confirmation, add, management, partial exit, runner and closure/invalidation. A repeated confirmation/target cannot execute twice. Invalidation closes remaining quantity and clears pending orders. Every action records prices, quantity, remaining average, stop/target, evidence, risk before/after, P&L, R, regime and state.

## Phase 6: offline comparison and usage

`BacktestEngine.run_comparison(datasets, instrument_specs, hybrid_config=..., timeframe=..., base_seconds=...)` is the extension point. `CampaignBacktester` can also run one variant directly or compare a dictionary of histories. All four variants use the same linear instrument specifications, costs, next-open fills and risk ceiling:

| Variant | Entry and management |
| --- | --- |
| A | Original MR signal generation, one entry using full campaign risk, fixed original stop/target |
| B | Hybrid small probe, configured trailing, one full exit, no adds |
| C | B plus fresh-confirmation tranches |
| D | C plus TP1/TP2/TP3 and runner |

The existing Deriv multiplier `BacktestEngine.run()` is unchanged. Its capped-stake settlement is different from linear CFD P&L, so A–D deliberately use a shared linear sizing model. Per-side campaign commission belongs in the instrument spec; the legacy fixed-per-trade commission argument is rejected for comparison. Multiple symbols are independent account runs, not a portfolio allocation simulation.

From `mean-reversion-bot/backend`, run a real-data comparison after creating a JSON instrument-specification file keyed by symbol:

```powershell
.\.venv\Scripts\python.exe hybrid_cli.py --data XAUUSD=gold.csv --data GER40=index.csv --specs my_specs.json --output hybrid-results.json --balance 10000 --base-seconds 300 --timeframe M5
```

Each specification requires `point_value`, `quantity_step` and `min_quantity`; optional fields are `max_quantity` and `commission`. Point value must already be in account currency per one native price unit per quantity unit. Obtain XAUUSD/GER40 values from the actual instrument contract specification; symbol names alone cannot determine lot values.

CSV columns are `timestamp,open,high,low,close,volume`. Timestamps are UTC epoch seconds at candle open, aligned to the base interval. Volume may be zero. Optional `--config` accepts JSON objects named `engine` and `hybrid`; all `EngineConfig` and `HybridConfig` parameters are available, including nested `hybrid.regime`. The CLI refuses to overwrite output.

For a deterministic smoke run using the included synthetic CSV:

```powershell
.\.venv\Scripts\python.exe hybrid_cli.py --data SYNTHETIC_GOLD=examples/hybrid/prices.synthetic.csv --data SYNTHETIC_INDEX=examples/hybrid/prices.synthetic.csv --specs examples/hybrid/specs.synthetic.json --config examples/hybrid/config.synthetic.json --output synthetic-run.json --slippage 0
```

The synthetic configuration shortens HTFs/EMA and lowers thresholds solely to exercise code paths. It is not a trading preset, and the synthetic instrument specs are not broker contract specifications. `examples/hybrid/generate_fixture.py` reproduces the CSV into a new output path. The included [full comparison](backend/examples/hybrid/comparison.synthetic.json) contains campaigns, action logs, marked equity, input/config hashes and metrics. A [compact metrics summary](backend/examples/hybrid/summary.synthetic.json) is also available.

Reports include campaign count, win rate, average positive/negative net P&L, expectancy, profit factor, marked maximum drawdown, average/median R and maximum deployed campaign risk in cash and percent. TREND, RANGE and UNKNOWN attribution is provided for each instrument. Profit factor is null with no losses. Sharpe requires at least 30 observed daily returns and nonzero standard deviation, with configurable annualization (252 by default). R uses initial actual probe risk including fees; maximum deployed risk is reported alongside it.

Orders fill at the next available candle open, subject to confirmation age and fill-time risk validation. Stops take precedence over targets on ambiguous OHLC bars; gaps fill adversely at the open. Stop changes at candle close only affect subsequent bars. Intrabar fills are assigned the candle-open timestamp because tick timing is unavailable. End-of-data closes include costs, reconcile cash/equity, and cancel pending orders.

The risk ceiling is modeled stop-based exposure, including configured costs. Market gaps can produce realized losses beyond a stop budget; they do not retroactively change the reported maximum deployed stop risk. There is no order-book, latency or live-liquidity model. No live broker, API route or frontend execution integration was added. Historical market profitability remains untested because no market dataset was supplied.

## Validation record

The original backend baseline passed **457 tests**, with **3 PostgreSQL integration tests skipped**. Regime/risk, scale-in and scale-out each passed targeted tests and full backend regressions before the next phase. Final synthetic tests cover campaign risk with costs and multiple point values, deduplication, invalid averaging, risk release, quantity/cost basis/P&L, all five trails, invalidation, mirrored long/short logic, A–D accounting, stop-first/gap fills, delayed stop effectiveness, stale confirmations, real-signal integration, future-data causality, repeatability and JSON-safe reports.

Final result: **529 passed, 3 skipped**, including **72 new hybrid tests**. The PostgreSQL skips require `TEST_POSTGRES_URL` pointing to a disposable test database. Existing deprecation warnings remain. Ruff passes for the new modules, CLI, fixture generator and tests; Python compilation and Git whitespace checks pass. The CLI smoke report covers eight independent instrument/variant runs, each with reconciled balances, no remaining quantity or pending orders and maximum deployed stop risk at or below 1%.
