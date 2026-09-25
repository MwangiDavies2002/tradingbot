# Verified roadmap and deployment runbook

This file follows the original five-phase roadmap: safety, execution quality,
research quality, operations, and strategy validation. The earlier PHASE2–PHASE6
documents use different numbering and describe experimental features. Their
checkboxes are not evidence that the original roadmap is complete.

## Implementation audit

### MT5 exact broker pair selection - 2026-09-25

The demo worker now selects one exact symbol from the connected broker catalog.
Saved symbols are validated; Start includes the expected symbol and rejects stale
mismatches. Candles, signals, sizing and orders follow the saved pair. History
uses the explicitly selected broker pair. Earlier bot exposure blocks new entries,
and journal recovery includes bot deals on previous pairs. This supersedes V75-only
limitations recorded in earlier entries below. Simultaneous multi-pair execution
and broker-equivalent backtest fills remain outside this implementation.

Validation: production build, 35 final targeted backend tests, six desktop/mobile
UI flows. Full backend suite before final additional assertions: 286 passed,
3 skipped. All MT5 responses were mocked; no live terminal or broker order verified.


### Chart asset selection - 2026-09-24

Strategy Lab now has a chart-asset selector independent of batch-test selection,
plus an exact TradingView `EXCHANGE:SYMBOL` input. Chart content, external links,
Pine symbol checks and download filenames follow that selection. The last chart
symbol persists in browser settings; switching platforms preserves batch choices.
Fully qualified symbols retain their provider prefix. This expands chart/export
selection, not broker symbol support: MT5 remains V75 1s only, and arbitrary
TradingView symbols are not automatically available to Deriv historical tests.

### Multiple-asset historical test batches - 2026-09-24

Strategy Lab supports multiple Deriv-history assets through sequential independent
test requests. Successful results survive another asset's failure, and inline errors
identify the affected asset. Unsupported News-only/Pine execution controls no longer
produce invalid Python backtest requests. MT5 history and demo execution remain
V75 1s only; file imports require one asset. Four desktop/mobile tests with stubbed
market responses passed, along with the frontend build. This verifies orchestration
and UI behavior, not provider instrument coverage or portfolio-level backtesting.

### Research history and role-aware UI - 2026-09-24

Institutional lab, the research registry and instrument catalog now disable actions
unavailable to the authenticated role. API authorization remains authoritative.
Opening failed/pending trials clears the previous report. Real isolated API browser
tests cover successful/failed saved trials, completeness, search, exports across
operator/viewer sessions and direct permission denials at desktop/mobile sizes.
Both new flows and existing admin lifecycle/catalog flows passed, alongside 36
registry/catalog backend tests and the production build. Remaining dashboard pages
still need equivalent UI permission handling; pagination/large histories and tenant
identity remain separate work. No production database or broker was accessed.

### TradingView chart lifecycle - 2026-09-24

Chart embeds now use a separate iframe document so delayed script execution
cannot reference a container removed by platform/timeframe changes. Added Reload
chart and a visible script-load failure message. Production build, four Pine
tests, two deterministic desktop/mobile lifecycle/recovery tests, and the two
MT5 historical-source UI tests passed. A separate opt-in check rendered real
public TradingView V75 candles after platform switching; screenshot inspected.
Provider availability remains external. No broker or backend behavior changed.

### MT5 historical source selection - 2026-09-24

Strategy Lab now explicitly selects Deriv or connected MT5 historical candles.
MT5 history is restricted to V75 1s and supported timeframes at both UI/API
boundaries; imported files override the selected provider. New results retain
and display the effective source. 22 targeted backend tests, the frontend build,
targeted Ruff, and two desktop/mobile Edge tests passed. MT5/backtest endpoints
were stubbed in browser QA; no live-terminal or order verification is implied.
The external TradingView embed was blocked in those isolated MT5 browser tests;
its load/unmount race was subsequently fixed and checked as described above.

### Institutional research extension - 2026-09-23

The Institutional lab adds eighteen **offline** analyses for instrument checks,
timestamped currency conversion, book replay, point-in-
time features, routing/schedules/costs, portfolio risk/allocation, model experiments,
multiple testing, European option portfolio Greeks/full-repricing scenarios and
inventory-aware market making and explicit order-lifecycle scenarios with inventory
reservations, partial fills, delayed cancellation and fill acknowledgements. A new
automatic quoting controller uses this ledger and client-known inventory at explicit
fair receipt events, with automatic expiry cancellation timers that preserve
cancel-latency and pending-fill reservations. Both remain separate from broker execution.
The extension has no broker execution authority. Full backend verification now
reports 267 passed and 3 PostgreSQL skips; frontend build and TradingView tests
pass. Two Edge browser flows verify lifecycle/automatic-quoting/catalog behavior at desktop/mobile
sizes against an isolated test API. Screenshots were inspected; mobile catalog
overflow was fixed. Broader dashboard and deployed UI verification remain.

See [INSTITUTIONAL_LAB.md](INSTITUTIONAL_LAB.md) for operation contracts and
[CONTINUATION_REPORT.md](CONTINUATION_REPORT.md) for the detailed handoff, prior
changes, test evidence and remaining production/data work. This extension does
not complete the deployment and empirical-validation requirements below.

The durable research registry now retains declared trial families, requests and
successful/failed/aborted outcomes with search, lineage and integrity-checked
exports. The instrument catalog retains immutable supplied revisions and supports
single-venue offline plans pinned to exact specification hashes, with session,
grid, quantity and freshness checks. Migration head is `0003_instrument_catalog`; production startup requires
it. Back up and migrate the deployment database before using the registry.
This implementation tested migrations on disposable databases only; it did not
migrate the configured application database. See INSTITUTIONAL_LAB.md for the
pending-run recovery procedure and append-only migration/rollback limitations.

### Broker/model continuation - 2026-09-23

- Broker names are normalized and validated. OANDA and FXCM remain registry
  placeholders: Start, worker setup, and account validation reject their
  execution before using the Deriv adapter. OANDA credentials do not make its
  execution adapter available.
- The experimental classifier is explicitly selected with
  `model_strategy="logistic_regression"` in the Python backtest/research API or
  `EngineConfig`. It is not a linear regression or neural network; those Python
  selections now return validation errors instead of silently running a different
  model. The existing dashboard has no logistic-model selector.
- Training requires 80 labeled examples after the 20-candle feature warmup
  (101 closed candles). Inputs must have positive finite closes and strictly
  increasing timestamps. The latest closed candle can complete a training label;
  inference concerns the next candle. Model abstention blocks indicator fallback.
  Scores are uncalibrated; the classifier has no empirical strategy validation.
- Regression coverage checks unsupported broker startup, normalized account
  scopes, model selection, sample counts, invalid history and abstention.
  Backend verification: 69 passed, 2 PostgreSQL integration tests skipped;
  targeted Ruff checks and `git diff --check` passed.
  PostgreSQL deployment checks and forward demo validation remain outstanding.

### Local verification — 2026-09-18

- Backend suite: 54 passed, 2 PostgreSQL integration tests skipped. Docker's
  Linux engine is unavailable locally; these skips are not deployment evidence.
- Live-feed regressions cover closed-candle-only evaluation, duplicate updates,
  stale/invalid updates, gap blocking, and clean unsubscribe/resubscribe state.
  Unsubscribe now discards the unfinished candle as well as the history buffer.
- Read-only inspection of `backend/data/local.db` found no stored candles.
  Historical strategy validation therefore remains pending; no profitability
  conclusions or live-trading authorization follow from the unit tests.

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
These diagnostics do not by themselves validate a fitted ML model or a tick-accurate simulator.
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
