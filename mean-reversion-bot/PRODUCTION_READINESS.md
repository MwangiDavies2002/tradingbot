# Verified roadmap and deployment runbook

This file follows the original five-phase roadmap: safety, execution quality,
research quality, operations, and strategy validation. The earlier PHASE2–PHASE6
documents use different numbering and describe experimental features. Their
checkboxes are not evidence that the original roadmap is complete.

## Implementation audit

| Phase | Implemented in the working tree | Validation still required |
| --- | --- | --- |
| 1 — Safety | Hashed admin/operator/viewer access keys; protected API and UI; account/mode checks; durable intents, positions and circuit breakers; stopped startup; SQL entry gate; restart reconciliation; cash, symbol and account exposure limits | Demo broker exercise; PostgreSQL ownership and kill-switch concurrency checks on deployment |
| 2 — Execution | Unique per-candle receipts; no blind buy/sell retries; uncertain-order blocking and audited resolution; reconnect gating; receiver/handler separation; closed-candle processing; stale/gap/invalid data rejection; persisted strategy hash, signal breakdown, latency and broker entry tick | Measure fill slippage and latency on demo; validate broker protection parameters and reconnect behavior against the configured legacy v3 endpoint |
| 3 — Research | Next-open fills; spread, slippage and commission; gap stops; stop-first ambiguity; simulated risk clock; equity drawdown; daily-return Sharpe/Sortino; reproducible data/config hashes; walk-forward train-only selection; seeded Monte Carlo | Calibrate costs to the instrument, collect sufficient real history, and run the research report; OHLC simulation does not model order books, partial fills, network latency or rejection probability |
| 4 — Operations | Frozen Alembic baseline, schema drift check, production migration guard; CI; separate production services; worker health check; protected Prometheus metrics, alert rules and Grafana dashboard; backup helper and recovery procedure | Start Docker/PostgreSQL, run deployment integration checks, provision monitoring credentials and alert delivery, restore a backup, exercise image rollback |
| 5 — Strategy validation | Threshold sensitivity; indicator ablations and cost stress on training data; chronological holdout gates; direction/session/reason attribution; existing Hurst regime filter; Research page and offline CLI | Multi-instrument and multiple-regime empirical results; forward demo sample; choose parameters only after reviewing evidence. No strategy has been promoted to live by this work |

No code-only audit can establish profitability. The default remains demo, and
`LIVE_TRADING_ENABLED=false`. Research reports always return `live_authorized=false`.

## Access and account setup

1. In `backend`, run `python generate_access_key.py admin` locally. Store the
   printed `API_ADMIN_KEY_HASH` in the backend environment and enter the access key
   into the dashboard. Generate separate operator/viewer keys as needed. Keys
   are held in browser memory, not local storage. Rotate a key by replacing its
   hash and restarting the API. This is a single-key-per-role design, not a
   multi-user identity provider or MFA system.
2. Configure `DERIV_ACCOUNT_ID`, `DERIV_API_TOKEN`, `DERIV_APP_ID`, `DERIV_DEMO=true`,
   and `LIVE_TRADING_ENABLED=false` consistently on API and worker. Use separate
   databases, credentials, and deployments for demo and live. MT5 remains local
   and demo-only; its Stop entries button leaves existing broker SL/TP active.
3. Use a direct PostgreSQL connection or a **session-mode** pooler for the worker.
   Transaction-mode poolers cannot preserve its session advisory lock. SQLite
   is supported for local API/MT5 and unit tests, not the Deriv worker.
4. Run `python -m alembic upgrade head` and `python -m alembic check` before a
   production deployment. Back up an existing database first. The baseline
   creates missing tables, preserves existing ones, adds missing indexes and
   widens contract IDs to BIGINT. A drift-check failure needs an explicit
   migration; do not stamp over a mismatched schema.
5. Start `python -m app.bot`. It acquires exclusive ownership, starts stopped,
   reconciles broker positions, and writes heartbeats. Start in the dashboard
   only after the worker is online and recovery has no unresolved issues.

The API checks the durable control row for every admitted buy. A buy admitted
before Stop may finish before Stop commits; the worker then attempts to close
managed positions. A disconnected worker cannot promise an immediate broker
close. Check the journal and broker account. External/unowned positions block
entries and are not automatically liquidated.

Uncertain buys are never blindly retried. Stop entries, inspect the broker's
statement, then use `GET /api/bot/orders/unresolved` and the admin-only
`POST /api/bot/orders/{trade_id}/resolve` with a matching `contract_id` or
`confirmed_not_executed=true`, plus an evidence description. A linked contract
must match the original symbol, contract type, stake and start time. Resolution
does not enable trading; reconciliation and explicit Start are still required.

## Research workflow

Use Research validation in the dashboard, or from `backend`:

```text
python research_cli.py history.csv --symbol R_75 --timeframe M5 --balance 1000 --spread 0.02 --slippage 0.0005 --commission 0.1 --output research-report.json
```

CLI CSV headers: `timestamp,open,high,low,close,volume`; timestamps are UTC epoch
seconds. Costs above are examples, not broker-calibrated recommendations.
The API caps uploaded research at 10,000 candles. Prefer the CLI for long runs;
serverless function time limits are unsuitable for sustained research jobs.

The expanding training window chooses among the selected confluence threshold
and its neighbors. Each following test window is untouched by that selection.
Indicator ablations and doubled-cost stress use the initial training half only.
Monte Carlo bootstraps test-trade cash P&L and explicitly assumes independence.
These diagnostics do not represent a fitted ML system or a tick-accurate simulator.
Scaling/trailing configurations are rejected by research until their simulator
has validated parity with execution. Earlier descriptions of martingale risk
bypasses are not a supported production behavior: all entries face execution limits.

Research gates require all folds, at least 100 out-of-sample trades, positive
net P&L, profit factor >=1.2, >=70% profitable folds, and fold drawdown below 20%.
These are editable engineering acceptance defaults, not a guarantee of returns.
After evaluating several instruments/regimes, collect a forward demo sample and
compare actual fills/costs with the simulation before considering live deployment.

## Deployment, monitoring, backup and rollback

Build and tag an immutable release image. With `backend/.env` configured:

```text
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml --profile migration run --rm migrate
docker compose -f docker-compose.prod.yml --profile worker up -d
```

The API binds to loopback; place an authenticated HTTPS reverse proxy in front.
Vercel may host the dashboard/API, but never the continuous worker. Production
startup checks the migration revision rather than modifying tables.

For monitoring, create `.secrets/metrics_key` containing a viewer access key,
configure the matching hash on the API, set `GRAFANA_ADMIN_PASSWORD`, and combine
`docker-compose.prod.yml` with `docker-compose.monitoring.yml`. Prometheus/Grafana
bind to loopback. Alert rules detect stale heartbeat, unresolved orders,
recovery blocking and API scrape failures. Configure an Alertmanager or Grafana
notification destination separately and test delivery; rule files alone do not
send notifications. Container unhealthy status alone does not trigger Compose
restarts; use your deployment supervisor for that policy.

Backups: configure `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and a protected
`PGPASSFILE`, then run `ops/backup.ps1 -Destination <existing-backup-directory>`.
The helper creates a custom-format dump and verifies its archive listing.
Schedule it externally, encrypt backups, retain off-host copies, and test a
restore into a fresh isolated database. Listing an archive is not a restore drill.

Rollback: stop entries, verify exposure, stop the worker, deploy the prior image
via `MRBOT_IMAGE`, and only restart after confirming schema compatibility. No
automatic destructive database downgrade is provided. Restore into a new
database and reconcile broker positions if schema rollback is required.

## Verification commands

```text
cd backend
python -m pytest -q --disable-warnings
python -m ruff check app tests --select E9,F63,F7,F82
python -m alembic check
cd ../frontend
npm run build
npm run test:tradingview
```

PostgreSQL integration tests require `TEST_POSTGRES_URL` pointing to a disposable
database; they create and remove uniquely named test schemas. CI supplies one.
Without that setting the tests explicitly skip. Legacy `verify_phase*.py` files
are exploratory scripts and are not the regression acceptance suite.

Implementation references: [Deriv multiplier protection](https://legacy-docs.deriv.com/docs/multipliers),
[Alembic async migrations](https://alembic.sqlalchemy.org/en/latest/cookbook.html#using-asyncio-with-alembic),
[Prometheus scrape authentication](https://prometheus.io/docs/prometheus/latest/configuration/configuration/).
