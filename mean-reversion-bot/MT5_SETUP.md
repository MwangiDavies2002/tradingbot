# Selected broker pairs on MT5 demo

The previous runner (`python -m app.bot`) sends Deriv WebSocket contracts.
Those contracts are not MT5 positions. Its dashboard start endpoint only
writes an event; it does not spawn a trading process.

The local dashboard now starts a separate **demo-only MT5 worker** using
the official MetaTrader5 Python package and your desktop terminal session.
Real accounts are rejected. No MT5 password is stored in the app.

## Start the application

From `backend`, first-time installation:

```powershell
py -3.12 -m venv .venv-mt5
.\.venv-mt5\Scripts\python.exe -m pip install -r requirements-mt5.txt
```

From `frontend`, run `npm ci`. Then from the project directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

Open <http://localhost:3000/backtest>. Logs are under `logs/`.

To start the backend manually, open a PowerShell window and run:

```powershell
cd path\to\mean-reversion-bot\backend
.\.venv-mt5\Scripts\python.exe run_local.py
```

Leave this window running. The backend is ready when it is listening on
`http://127.0.0.1:8000`; you can verify it at
<http://127.0.0.1:8000/health>. In a second PowerShell window, start the
frontend:

```powershell
cd path\to\mean-reversion-bot\frontend
npm run dev -- --host 127.0.0.1
```

Then open <http://localhost:3000/backtest>. You can also use
`start-local.ps1`, which launches both processes for you and writes backend
logs under `logs/`.

`run_local.py` uses `backend/data/local.db` for the existing app database.
It does not edit `.env` or need a Supabase password or Deriv API token.
MT5 needs Windows and the desktop terminal on the same PC. This worker
does not run on Vercel. Use one backend process with one worker, no reload.

## Connect and test

1. In MT5 choose **File → Login to Trade Account**. Enter the MT5 demo
   login, password and exact server supplied by your broker.
   These are your MT5 credentials, not your Deriv website login.
2. Open the intended pair in MT5 Market Watch. Broker names and suffixes matter:
   `EURUSD.a` and `EURUSD` are separate symbols. No alias is automatically substituted.
3. Enable **Algo Trading**. Under **Tools → Options → Expert Advisors**,
   clear **Disable automated trading via external Python API**. The API
   checks terminal and account permissions before accepting Start.
4. In Strategy Lab click **Connect MT5 demo**. Check the account/server
   displayed. Choose **MT5 broker pair** from the connected account catalog, then
   select indicators, timeframe and the minimum weighted score.
   Six points does not require six different indicators to agree: some
   conditions contribute multiple points. Hurst also acts as a regime filter.
5. Under **MT5 / Python**, choose **Historical data source → Connected MT5
   history**, then **Run Combined Test**, or import an OHLCV CSV.
   The source defaults to Deriv history; choosing the platform alone does not
   select MT5 candles. History uses the exact **MT5 broker pair** selected above
   and never falls back to Deriv or V75. Changing a history selection does not
   change the saved execution configuration until you save it.
   Imports override the history source. New results retain their effective source;
   older saved runs without that field show **Not recorded**. For missing
   history, increase MT5's **Max bars in chart**, open/scroll the chart, or
   increase the requested days. At least 100 candles are required. Session closures
   and weekends are allowed; this minimum does not certify complete history.
6. Choose demo risk settings, click **Save lab selection**, then **Start demo**.
   **Load saved selection** restores your saved pair, toggles and risk settings.
   To switch pairs, stop entries, select the exact new pair, save, then start.
   A stale Start request naming a different pair is rejected.
7. View open trades in MT5 **Toolbox → Trade**, closed deals in **History**,
   and the app's **MT5 Demo & Journal**. Expand the journal and download CSV.

The worker polls every two seconds and evaluates each completed candle once.
It enters only when the saved conditions qualify, including the engine's
direction and regime filters. Daily monitoring does not guarantee daily trades.
Backtests share the indicator engine, but the existing backtest simulator uses
its original sizing/fill model. Its P&L is not an exact MT5 CFD simulation;
demo fills include broker spread, lot constraints and execution costs.

## Risk and recording behavior

### Multiple-asset historical tests

In Strategy Lab, select **MT5 / Python** and **Deriv history**. Under **Assets
to Include**, click each asset to add/remove it, then choose **Run Combined Test**.
The app runs one independent test per selected asset, keeps successful results,
and displays failures with their asset names. Each test uses the full starting
capital; results are not a shared portfolio simulation. Provider availability
still determines which instruments can supply candles.

TradingView displays one chart at a time using the **Chart asset** selector,
independently of the selected batch-test assets. **Other TradingView pair** accepts
an exact `EXCHANGE:SYMBOL` identifier; **Show pair** updates the chart, external links
and Pine export together. The last chart asset is remembered in this browser.
Custom chart symbols do not automatically become available to Deriv history or
MT5 execution. CSV/Excel imports require one selected asset at a time.
Connected MT5 history and demo execution use one exact broker pair at a time. News-only execution
and Pine translation are not implemented by the Python backtester, so those
unavailable choices cannot be selected in the test form. Pine exports are tested
in TradingView separately.

### Demo execution

- Any eligible symbol offered by the connected demo account; magic number `751006`.
  Market orders, broker-held SL/TP, and valid price/lot specifications are required.
  Broker direction restrictions are checked before an order.
- No entry when any position or pending order exists on the selected symbol,
  or when this bot has exposure on an earlier symbol. Stop entries does not close trades.
- Candles, signals, quotes, account-currency risk sizing and orders all use the
  saved exact symbol. Journal recovery includes bot deals across previous pairs.
- Default risk budget: 0.5% of the lower of balance/equity, capped at 1%.
  Lots are rounded down using MT5's profit calculation in account currency.
  A minimum lot exceeding the budget is skipped. Costs/slippage/gaps can
  make realized loss exceed the planned stop risk.
- ATR stop loss and 2:1 target are sent to the broker with the entry.
- Default daily equity loss limit: 3%, capped at 5%. Baseline is equity
  at the first poll each UTC day, not an inferred midnight balance.
  Once reached, the block persists through restarts for that UTC day.
  It blocks new entries; it does not liquidate existing positions.
- Stop entries waits for the current terminal call to finish. An in-flight
  order may complete. Existing positions retain their broker SL/TP and
  can be managed in MT5. Reconnect is required after terminal/account errors.
- Every evaluated candle, strategy snapshot, order request/result, and bot
  position deal is persisted in `backend/data/mt5_journal.sqlite3`.
  Deal history includes manual exits of bot positions and is deduplicated
  by account/server/ticket. It is synchronized every 15 seconds while running,
  while viewing the stopped connected journal, and on reconnect after downtime.
- Journal entries preserve broker deal timestamps and P&L, commission, swap,
  and fees. Requests are persisted before submission; an uncertain response
  stops the worker rather than retrying an order that may already exist.

Keep Windows awake, MT5 logged in and the backend running for continuous
monitoring. The browser can be closed. A restart does not automatically
resume entries; reconnect and start the saved strategy explicitly. Back up
the local database files while the backend is stopped.

If MT5 discovery fails, set the `MT5_TERMINAL_PATH` environment variable to
your terminal64.exe path before launching. Logins remain in the terminal.

Official references: [Python integration](https://www.mql5.com/en/docs/python_metatrader5),
[initialize](https://www.mql5.com/en/docs/python_metatrader5/mt5initialize_py),
[order_send](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py).

### If Deriv history reports HTTP 520

Restart the backend after updating. Historical tests now use Deriv's public
market-data endpoint and retry temporary connection failures up to three times.
If the provider remains unavailable, select **Connected MT5 history**, choose your
exact **MT5 broker pair**, and run the test again, or import that pair's candles.
MT5 connection alone does not change the history source. A test never switches
providers automatically or starts demo trading.
