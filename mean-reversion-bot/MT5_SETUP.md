# V75 1s on MT5 demo

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
Alternatively run `.venv-mt5\Scripts\python.exe run_local.py` inside
`backend`, and `npm run dev -- --host 127.0.0.1` inside `frontend`.

`run_local.py` uses `backend/data/local.db` for the existing app database.
It does not edit `.env` or need a Supabase password or Deriv API token.
MT5 needs Windows and the desktop terminal on the same PC. This worker
does not run on Vercel. Use one backend process with one worker, no reload.

## Connect and test

1. In MT5 choose **File → Login to Trade Account**. Enter the MT5 demo
   login, password and exact server shown in your Deriv MT5 account page.
   These are your MT5 credentials, not your Deriv website login.
2. In Market Watch show **Volatility 75 (1s) Index**, then open its chart.
   This is the one-second instrument, represented as `1HZ75V` in the lab.
   `R_75` is a different instrument.
3. Enable **Algo Trading**. Under **Tools → Options → Expert Advisors**,
   clear **Disable automated trading via external Python API**. The API
   checks terminal and account permissions before accepting Start.
4. In Strategy Lab click **Connect MT5 demo**. Check the account/server
   displayed. Select indicators, timeframe and the minimum weighted score.
   Six points does not require six different indicators to agree: some
   conditions contribute multiple points. Hurst also acts as a regime filter.
5. Run a backtest using MT5 history, or import an OHLCV CSV. For missing
   history, increase MT5's **Max bars in chart**, open/scroll the chart, or
   request fewer days. Incomplete history produces an error, not fake results.
6. Choose demo risk settings, click **Save lab selection**, then **Start demo**.
   **Load saved selection** restores your saved toggles after reloading.
7. View open trades in MT5 **Toolbox → Trade**, closed deals in **History**,
   and the app's **MT5 Demo & Journal**. Expand the journal and download CSV.

The worker polls every two seconds and evaluates each completed candle once.
It enters only when the saved conditions qualify, including the engine's
direction and regime filters. Daily monitoring does not guarantee daily trades.
Backtests share the indicator engine, but the existing backtest simulator uses
its original sizing/fill model. Its P&L is not an exact MT5 CFD simulation;
demo fills include broker spread, lot constraints and execution costs.

## Risk and recording behavior

- Only `Volatility 75 (1s) Index`; magic number `751006`.
- No entry when any position or pending order exists on that symbol.
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
