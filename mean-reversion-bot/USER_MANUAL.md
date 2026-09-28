# MR Bot User Manual

This manual covers the current local workflow for researching assets and, only after validation, monitoring a demo strategy through MT5.

## 1. Before You Start

You need:

- Windows on the same PC as the desktop MT5 terminal.
- An MT5 demo account and its exact server name.
- The MR Bot backend and frontend installed.
- An access key supplied by the administrator.
- At least 100 closed candles for every asset you want to analyze.

This application does not store your MT5 password. Log in to MT5 first and leave the terminal open.

## 2. Start the Local Application

From the project directory, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

Or start the services separately.

Backend:

```powershell
cd path\to\mean-reversion-bot\backend
.\.venv-mt5\Scripts\python.exe run_local.py
```

Frontend, in a second PowerShell window:

```powershell
cd path\to\mean-reversion-bot\frontend
npm run dev -- --host 127.0.0.1
```

Open `http://localhost:3000`.

The backend is ready when `http://127.0.0.1:8000/health` responds. Keep the backend window open while using the dashboard.

## 3. Sign In

1. Enter the access key supplied by your administrator.
2. If the page says it cannot reach the local API, start `backend/run_local.py` and retry.
3. If the key is rejected, it does not match the configured role hash in `backend/.env`. Ask the administrator for the current key; do not copy the hash itself as the key.
4. Your role controls which research and execution actions are available:
   - `admin`: all protected actions.
   - `operator`: run research and operate approved demo workflows.
   - `viewer`: inspect saved reports and export results, but cannot mutate research or trading state.

## 4. Prepare MT5 (Only for MT5 History or Demo Execution)

In the desktop MT5 terminal:

1. Select `File -> Login to Trade Account` and log in to the demo account.
2. Open the intended instrument in Market Watch.
3. Confirm the exact broker symbol. Suffixes matter, for example `EURUSD.a` is different from `EURUSD`.
4. Enable `Algo Trading`.
5. Open `Tools -> Options -> Expert Advisors` and allow external Python trading.
6. Increase MT5 `Max bars in chart` if the requested history is too short.
7. Keep MT5 logged in and running.

## 5. Analyze Selected Assets

This is the main research workflow. It does not start trading.

1. Open `Analyze assets`.
2. Choose a data source:
   - `Connected MT5 demo`: uses the exact symbol selected from the connected MT5 catalog.
   - `Deriv public history`: uses public historical candles for supported symbols.
   - `Imported candles`: uses one candle file per selected asset.
3. Set timeframe, lookback days, rolling window and starting balance.
4. Select one or more assets. A run supports up to eight assets.
5. For each asset, expand `costs, contract and trading calendar`.
6. Enter confirmed commission, financing, spread and slippage assumptions.
7. Enter the session timezone, open/close schedule and a calendar source such as a broker schedule or exchange calendar.
8. Check the session confirmation box only after verifying the schedule, holidays and early closes.
9. For non-MT5 data, confirm the linear contract specification and currencies.
10. Select the strategy indicators and minimum weighted score.
11. For imported data, upload each asset's CSV or Excel candles.
12. Click `Analyze selected assets`.

The job runs independently of trading. Progress is saved, so the page can be left and revisited.

## 6. Read the Research Report

Each asset report includes:

- Data coverage, missing bars and grouped missing ranges.
- Bars outside the supplied session or timestamp grid.
- Flat-close runs and spread statistics.
- Session confirmation and calendar provenance.
- Descriptive behavior: realized volatility, return autocorrelation, trend score and a sample-only regime label.
- Walk-forward folds and an untouched holdout.
- Cost stress and bounded threshold sensitivity.
- Correlations, rolling relationships and exploratory cointegration for multi-asset runs.
- A clear `demo candidate` or `no trade` decision.

A `no trade` decision is expected when evidence is incomplete. Read the listed reasons instead of trying to bypass them.

The run summary at the top reports the number of candidates, no-trade assets and failed assets. One passing asset does not approve the others or create a combined portfolio approval.

## 7. Common Validation Errors

### Negative slippage

`slippage_ticks` must be zero or greater. Use `0` for no slippage or a positive number of ticks.

### Confirmed calendar without a source

A confirmed session calendar requires a non-empty calendar source. Enter the broker schedule, exchange calendar or document reference before checking confirmation.

### Too few candles

Supply at least 100 candles per asset. Walk-forward validation also needs enough history for development folds and a final holdout.

### Missing or outside-session candles

Review the selected timezone, weekdays, holidays, early closes and imported timestamps. The application does not fill or invent candles.

### MT5 history unavailable

Open and scroll the instrument chart in MT5, increase `Max bars in chart`, confirm the exact broker symbol, and retry. There is no automatic fallback from MT5 history to Deriv history.

## 8. Load a Validated Candidate

Only an eligible MT5 result can be loaded into demo execution.

1. Complete an analysis using `Connected MT5 demo`.
2. Resolve all no-trade reasons.
3. When an asset is marked `Validated demo candidate`, click `Load validated candidate into MT5`.
4. Open `MT5 Demo & Journal`.
5. Confirm the account, server, exact broker pair and saved strategy.
6. Review the research baseline shown in the panel.
7. Save the pair and risk settings before starting.

A candidate is tied to the demo account/server and broker contract specification used during research. Changes to the symbol, strategy or risk settings invalidate the candidate and require a new analysis.

## 9. Start and Monitor Demo Entries

1. In `MT5 Demo & Journal`, click `Connect MT5 demo` if needed.
2. Choose the exact broker pair from the catalog.
3. Click `Save pair selection` or `Save lab selection`.
4. Confirm the saved settings and research validation indicator.
5. Click `Start demo` explicitly.
6. Monitor open positions in MT5 `Toolbox -> Trade` and the app journal.
7. Review the research baseline and forward comparison status:
   - `insufficient_sample`: fewer than 20 closed post-validation trades.
   - `observing`: enough trades for comparison, with no deterioration alert.
   - `deteriorating`: demo profit factor is below half the research holdout baseline.
8. Treat a deterioration alert as a review signal. Inspect the journal, data quality and broker conditions before deciding whether to stop entries.

The current monitor does not automatically halt trading. It does not claim that a small demo sample proves strategy failure or success.

## 10. Stop Safely

1. Click `Stop entries` in the MT5 panel.
2. Confirm in MT5 that open positions still have broker-held stop loss and take profit orders.
3. Stopping entries does not close existing positions.
4. To change pairs, stop entries first, select the new exact symbol, save it, and then start again.
5. A restart does not automatically resume entries. Reconnect and start explicitly.

## 11. What This System Does Not Claim

- Backtests are not exact broker CFD simulations.
- OHLC data does not model order books, partial fills, latency or rejection probability.
- A profitable backtest is not proof of future profitability.
- Research results do not authorize live trading.
- MT5 execution currently operates one exact broker pair at a time.
- Broker session calendars and real cost calibration must be supplied and verified.
- Demo monitoring requires a meaningful forward sample before deterioration conclusions.

## 12. Related Documents

- [MT5 setup and execution details](MT5_SETUP.md)
- [TradingView setup](TRADINGVIEW_SETUP.md)
- [Production readiness and research limits](PRODUCTION_READINESS.md)
- [Continuation report](CONTINUATION_REPORT.md)

## 13. Optional Forward Scanner Session Calendars

The scanner accepts source-referenced UTC session windows through its authenticated
start API. Saved settings and evidence retain each calendar. Scheduled closures
can be distinguished from missing candles; account, symbol, publication time and
coverage must match. See [scanner session configuration](SCANNER_SESSIONS.md) for
the input contract and limitations. The dashboard has no calendar editor yet.

## 14. Optional Scanner Instrument Mappings

An admin can pin an exact MT5 broker instrument to a supplied catalog revision.
Mapped scans verify its account and contract metadata before accepting observations.
See [mapping configuration and comparisons](SCANNER_MAPPINGS.md). The dashboard
preserves saved mapping IDs but does not yet provide a mapping editor.

## 15. Browse Manual and Automatic Paper Evidence

Open **Paper trades** in the local app. **Unified paper evidence** lets you choose
**Automatic scanner** or **Manual entries**, load the latest records and page to
older evidence beyond the 500-row live views. Viewers can use this read-only panel.
Open **Original record** for retained source data, source ID and policy provenance.

Scanner outcomes use R. Manual outcomes retain stored price change times quantity;
the manual ledger has no declared currency. These values are not pooled or converted.
Unavailable outcomes stay unavailable, including unresolved scanner exposure.
Manual approval labels do not authorize orders. Existing manual entry/close controls
remain below this panel; the evidence browser itself has no mutation controls.

Use **Latest evidence** to refresh after a manual edit or scanner update. Records
can change state while browsing, and the two sources are not one synchronized
snapshot. Outside the local app, use the existing manual ledger; the scanner
journal remains restricted to local access.

## 16. Choose the Scanner Paper Spread Model

Before starting the Forward scanner, choose **Fixed observed quote** (existing
behavior) or **Historical candle proxy** under **Paper spread model**. Stop before
changing the setting; Load saved scanner settings restores it.

Historical mode preserves each consumed candle's spread evidence. Missing or
unconfirmed zero spreads leave outcomes unresolved. It remains a cost approximation,
not executable ask history. Inspect spread_history in Original record or export.
See [spread models and limitations](SCANNER_SPREADS.md) for details.

## 17. Test One Broker Pair at a Time

Use the same exact broker symbol (including suffix), account/server and timeframe
throughout each pair's evaluation. Select only that pair, finish and save its
results, then stop the relevant workers before selecting another pair.

1. **Backtest:** in Strategy Lab choose MT5 / Python and Connected MT5 history,
   then select the exact broker pair. For the validated execution path, open Analyze
   selected assets, choose Connected MT5 demo and select only that same pair.
   Supply/verify its contract, calendar and cost assumptions. Results remain tied
   to the selected symbol; missing MT5 history never silently falls back to Deriv.
2. **Forward paper test:** open Forward scanner, load broker symbols and select
   only that pair. Choose its timeframe and paper-cost model, then Start paper
   scanner. Keep the backend and terminal running. Review/export its observations,
   rejections, closed trades and unresolved outcomes before stopping the scanner.
3. **Live-market demo test:** a passing Analyze candidate can be loaded into
   MT5 Demo & Journal. Review the exact saved pair/account/settings and explicitly
   Start demo. The worker executes one selected symbol. A changed pair/account or
   contract invalidates the candidate, and old bot exposure blocks new entries.
   Stop entries before switching; stopping does not close existing positions.

Real-money MT5 accounts are currently rejected. A request to test a pair does not
start orders automatically. Broker-backed history and execution require the user's
connected terminal; automated implementation tests use simulated terminal responses.

To use the same **signal-engine configuration** in forward paper testing, first
load a passing single-pair candidate from Analyze selected assets into MT5 Demo &
Journal. Then open Forward scanner and click **Use loaded research candidate**.
The scanner selects that exact pair, timeframe and score threshold and loads the
indicator toggles from the server's saved candidate. Start the scanner explicitly.
The backend checks the demo account and broker contract again before starting;
changed or stale candidates are rejected. The scanner and MT5 demo worker must be
run sequentially in this candidate mode.

The scanner still applies its own conservative RANGE paper gate and hypothetical
spread/slippage model. Historical Analyze fills and actual MT5 demo fills have
separate assumptions. Use policy and research run identifiers when comparing
results; this is shared signal configuration, not identical end-to-end trades.

In **Forward evidence by pair and policy**, review the row matching the exact
account, broker symbol, timeframe and paper settings you tested. Its 300 closed
paper trades are an initial review target for that row alone. Check unresolved
outcomes and open the policy details to find the scanner run IDs. The all-scanner
totals combine unrelated experiments and cannot qualify a single pair.

## 18. Compare the Three Stages for One Candidate

After loading a passing Analyze candidate, open **MT5 Demo & Journal** and read
**Single-pair validation evidence**. The panel shows the research holdout, each
matching forward-paper policy and the live-market demo comparison for the exact
research run, account, broker pair and timeframe. Backtest and demo P&L use
account currency; scanner outcomes use R, so do not add or average them.

The demo comparison counts complete broker positions that began from a successful
order linked to the loaded research run. Partial closes count as one position
only after the whole volume closes. Older positions, another account or research
run, and orders without a provable link remain in the complete journal but do not
enter the comparison. An incomplete-position count calls out linked exposure
that still needs reconciliation. Review the journal and terminal before drawing
conclusions from the comparison; it never enables real-money trading.
