# Institutional capability expansion - continuation report

Last checkpoint: 2026-09-23. Status: sixth offline implementation checkpoint
verified; broader production expansion is NOT complete.

## User request and working agreement

Implement the capabilities in the attached institutional-trading overview step
by step, and preserve a detailed report for resuming when credits return.
Account credit usage is not exposed to this agent; a 95% trigger cannot be
observed. Update this file after every verified milestone and before stopping.
The attachment is an overview, not a broker specification or production design.
Implement reproducible offline primitives first, then validated integration.
Do not describe synthetic examples as real market results or research tools as
production execution. No live orders, paid feeds or deployments are authorized
merely by completing a research milestone.

Source attachment: `C:/Users/win/.codex/attachments/4b3683b9-6955-4e7f-a26c-8f33e192fabe/Pasted text.txt`.

## Starting state and previous work

Repository: `C:/Users/win/Desktop/mean-reversion-bot_2`; application is in
`mean-reversion-bot/`. Base HEAD at start: `c5397b9e` (`phase changes`).
Existing uncommitted changes must be preserved. No commits made by this session.

- Existing production roadmap covers authentication, durable execution journal,
  stopped startup, ownership/reconciliation, per-candle receipts, account limits,
  closed-candle feeds, cost-aware OHLC backtests, walk-forward validation,
  monitoring, migrations and deployment procedures. See PRODUCTION_READINESS.md.
- Fixed unsubscribe leaving a forming candle; added four live-feed regressions.
- Added normalized broker registry and OANDA configuration placeholders.
  Unsupported OANDA/FXCM execution is rejected by Start, worker setup and account
  validation, preventing accidental Deriv execution under another broker scope.
- Exposed experimental classifier under its correct `logistic_regression` name.
  Unimplemented linear-regression/neural-net Python selections fail validation.
  Added minimum training count, chronological/finite input checks and abstention.
  Tree selection now applies consistently in EngineConfig.
- Baseline verified: 69 backend tests passed, 2 PostgreSQL tests skipped;
  targeted Ruff and diff whitespace checks passed. Frontend build and four
  TradingView tests passed before these backend-only changes.
- No sufficient stored historical data, deployment PostgreSQL exercise or
  forward demo sample has been established. No profitability claim is supported.

## Ordered implementation backlog

| Step | Deliverable | Status and acceptance evidence |
| --- | --- | --- |
| 1 | Normalized multi-venue quote/depth data, sequence/age checks, deterministic replay, point-in-time features and provenance | Offline primitives implemented; 10 tests passed |
| 2 | Execution research: depth-aware routing, partial fills, TWAP/VWAP/participation schedules and transaction-cost attribution | Offline plans implemented and tested; real venue lifecycle and calibrated fills remain |
| 3 | Portfolio risk: historical VaR/ES, scenarios, factor/counterparty/concentration limits and capital budgets | Linear scenario risk and configurable gross/net/concentration budgets implemented; liquidity/credit/regulatory capital models remain |
| 4 | Portfolio allocation, covariance/correlation diagnostics and turnover limits | Capped inverse-volatility allocation with cash, turnover and covariance risk implemented; expected-return/constrained optimization remains |
| 5 | Model research infrastructure: point-in-time cross-asset features, expanding validation, experiment registry, multiple-testing controls | Point-in-time joins, purged ridge folds, BH adjustment and searchable append-only trial registry implemented; broader models and curated data remain |
| 6 | European option pricing/Greeks and hedging scenarios | BSM price/Greeks, signed position aggregation by underlying and pre-expiry full-repricing scenarios implemented; option chains, settlement and executable hedging remain |
| 7 | Inventory-aware market-making simulator and quote/fill analytics | Quotes/print replay plus separate explicit order-lifecycle scenarios with reservations, delayed cancel, partial fills and cash/fee accounting implemented; real queue/hedging/adverse-selection calibration remains |
| 8 | Protected API, dashboard, offline CLI, reproducible artifacts and observability for new modules | Seventeen analyses, saved trial families/history, protected API and report exports implemented; durable job workers and dedicated telemetry remain; visual QA blocked by browser tool |
| 9 | Licensed feeds, venue/broker adapters, instrument metadata, currency conversion and real cost calibration | Supplied metadata catalog, pinned single-venue planning, order checks and timestamped bid/ask conversion implemented; provider adapters and real calibration remain external dependencies |
| 10 | Durable multi-venue order lifecycle, cancel/replace, reconciliation, permission/audit controls, resilience and deployment exercises | Pending; existing Deriv controls cannot imply multi-venue support |
| 11 | Multi-regime empirical validation, stress/capacity studies and forward demo acceptance | Requires representative real datasets and demo access |

Specialist topics in the attachment (pricing, market making, client analytics,
capital/regulatory models) are separate workstreams. Simple research primitives
must not be labeled regulatory capital calculations or an institutional platform.

### New files and milestone details

- `backend/app/institutional/data.py`: strict normalized snapshot/delta schema,
  atomic price-level updates, sequence-gap blocking until a fresh snapshot,
  crossed/empty/stale/future book rejection, spread/imbalance/microprice/depth,
  receive-order replay and canonical data hash. Point-in-time features respect
  publication times and revision availability. Ten regression cases passed.
- `backend/app/institutional/execution.py`: static fee-adjusted depth sweeps,
  raw-price limits, partial/residual quantities, signed arrival shortfall;
  TWAP/VWAP/participation scenario schedules; separated spread/fee/slippage/impact/
  financing costs. Common symbol/currency required; no real broker calls.
- Tests: `test_institutional_data.py`, `test_institutional_execution.py`.
- Remaining data work: feed adapters, exchange tick/lot sizes, corporate actions,
  FX/unit normalization, trade prints, durable replay storage and entitlements.
- Remaining execution work: queue/fill probabilities, transient impact,
  cancellation, venue outages, active participation controller and calibration.

| File | Implemented behavior |
| --- | --- |
| `backend/app/institutional/risk.py` | Historical inverse-CDF VaR, fractional-tail ES, one-period P&L, gross/net/symbol/counterparty/factor checks, complete asset shocks, correlation matrix, capped inverse-volatility allocation and L1 turnover constraint |
| `backend/app/institutional/research.py` | Training-only standardization, expanding ridge fits, target-availability purge/embargo, mean-forecast benchmark, turnover cost including fold liquidation, BH multiple-testing adjustment |
| `backend/app/institutional/derivatives.py` | European Black-Scholes-Merton with continuous dividend yield; delta, gamma, calendar-day theta, per-vol-point vega and per-rate-point rho |
| `backend/app/institutional/market_making.py` | Inventory skew, conservative tick rounding, side disablement at inventory caps; prior-quote trade replay with latency/age gating, hypothetical partial fills, fees and marked P&L |
| `backend/app/institutional/service.py` | Shared validated dispatch for twelve operations; canonical request/result, source/runtime identity and report hashes; refuses non-finite reports |
| `backend/app/api/routes/institutional.py` | Capabilities schemas and protected analyses; 2 MB request cap, two jobs per process, calculations off the async event loop |
| `backend/app/main.py` | Registers `/api/institutional` router under existing authentication middleware |
| `backend/institutional_cli.py` | Standalone offline JSON analysis, no broker settings import, exclusive-create report output |
| `backend/examples/institutional/` | Synthetic route, option and market-making request files |
| `frontend/src/pages/Institutional.tsx` | Operation selection, scenario upload/editor, numeric results, assumptions and full report download |
| `frontend/src/data/institutional-examples.json` | Canonical synthetic examples for all twelve operations; each is executed through the real backend service by regression tests |
| `frontend/src/App.tsx`, `frontend/tsconfig.json` | New lab navigation/route and typed JSON imports |
| `INSTITUTIONAL_LAB.md` | User instructions, units, assumptions, endpoint/CLI details and limitations |

The new ridge regression is an **offline experiment model**, separate from the
production SignalEngine's intentionally rejected legacy `linear_regression`
toggle. Do not remove those guards without implementing and testing an explicit
research-to-execution contract. No new analytics are used to admit real orders.

## Latest verification and environment constraints

### Sixth checkpoint: explicit offline order lifecycle

- Verification: **211 backend tests passed, 3 PostgreSQL checks skipped** because
  no disposable test URL is configured; 56 seconds and 20,396 existing warnings.
  Targeted Ruff and whitespace checks passed. Frontend build and four TradingView
  tests passed; Vite retains its bundle-size warning at approximately 707 kB.
- Added `backend/app/institutional/order_lifecycle.py` and `order-lifecycle` service
  dispatch, canonical dashboard example and standalone CLI example. The existing
  lab, authenticated analysis API, CLI and generic registry dispatch accept it.
- Explicit single-instrument submit/cancel/trade events use decimal accounting,
  independent buy/sell outstanding-size reservations and inventory-capacity
  rejection. Pending submissions and cancellations retain remaining capacity.
  Partial fills share each print's hypothetical volume budget across orders in
  price/time order. Cancel acknowledgement releases only the unfilled remainder;
  duplicate cancel requests preserve the original effective time.
- Submission/cancel delays are supplied scenario values. Equal-time inputs execute
  in list order, with already-effective cancels processed first. A cancel cannot
  overtake its original submission. Replacements are new explicit submissions,
  constrained by remaining capacity. End time settles due cancels but does not
  cancel all orders or liquidate holdings. Reports retain inventory bounds, order
  states, fills, audit, cash, fees, outstanding reservations and marked P&L.
- Added `test_order_lifecycle.py` coverage for pending submission reservation,
  activation boundary, cancel/fill races, terminal reservations, partial/full
  fills, shared print budget, price/time priority, non-netted opposite orders,
  invalid event streams and exact cash/fee reconciliation. API permissions/body
  checks, dashboard example execution and CLI overwrite protection include the
  new operation. No schema migration was needed.
- Limits: 5,000 events, 500 submitted orders; single underlying/quote units only.
  No real queue, instrument-grid checks, self-trade prevention, delayed fill
  acknowledgements, data delay, venue outage/rejection, hedging or exit costs.
  Existing automatic `market-making` replay retains its earlier assumptions;
  this separate operation does not silently change prior simulations.
- No broker calls, deployment, migration or real performance study performed.
  Visual QA remains pending from the earlier browser failure; no browser retry
  was made in this milestone. All prior uncommitted changes are preserved.

### Fifth checkpoint: option portfolio full-repricing scenarios

- Final verification: **195 backend tests passed, 3 PostgreSQL tests skipped**
  because no disposable PostgreSQL URL was configured; 33 seconds and 20,397
  warnings. Targeted Ruff and diff whitespace checks passed. Frontend build and
  four TradingView tests passed; the existing Vite warning remains at about 706 kB.
- Added `backend/app/institutional/option_portfolio.py` and the `option-portfolio`
  service operation, automatically exposed through the protected API, offline CLI,
  existing lab UI and saved research registry. Added canonical dashboard/CLI
  synthetic call-spread examples and usage/units documentation.
- Signed integer contracts and explicit multipliers scale values and five Greeks.
  Sensitivities stay grouped by underlying; portfolio value and gross option value
  share one explicit currency. Each supplied scenario fully recomputes option
  prices and Greeks after spot, volatility, rate, yield and calendar-time shocks.
- Validation requires unique position/scenario IDs, common reporting currency,
  consistent spot per underlying, complete shock maps, valid transformed pricing
  inputs and strictly pre-expiry horizons. Inputs are bounded to 100 positions and
  50 scenarios. Expiry settlement, FX, costs, smile dynamics, collateral, legal
  netting and executable hedge proposals remain outside this model.
- Tests cover signed scaling, offsetting positions, gross/net distinctions,
  separate underlying units, combined-shock repricing, expiry/input rejection,
  report identity, API permissions, CLI overwrite protection and persisted trial
  export retaining position/scenario inputs. Existing BSM finite-difference tests
  continue to validate the pricing primitive.
- No schema changes or deployment database migration were needed. Migration head
  remains `0003_instrument_catalog`. No feeds, orders, deployment or empirical
  profitability validation were performed. Visual browser QA remains outstanding
  from the prior tooling failure; it was not retried during this milestone.

### Fourth checkpoint: persistent instrument catalog and pinned plans

- Verification: **174 backend tests passed, 3 PostgreSQL tests skipped**, about
  59 seconds; 20,394 warnings remain. Targeted Ruff passed. Frontend build and
  all four TradingView tests passed; largest bundle is about 705 kB and retains
  Vite's size warning. Browser connection was retried and failed before opening
  a page with the same `sandboxPolicy` tooling error; visual QA remains pending.
- Recovered the unfinished catalog implementation already in the working tree
  and reviewed its persistence, API, planner, dashboard and migration integration.
  Added rejection of snapshots from earlier trading sessions, even when within
  the age limit; added zero-fill conservation, request/body/capacity regressions
  and direct-SQL immutability checks against the migrated catalog schema.
- `app/institutional/catalog.py`, `InstrumentRevision` and migration
  `0003_instrument_catalog` retain immutable supplied specifications with hashes,
  registration timestamps and roles. Exact retries are idempotent; conflicting
  venue/symbol/revision content requires a new revision. Detail/planning lookups
  verify stored content integrity. SQLite/PostgreSQL mutation guards are defined;
  PostgreSQL behavior has not been verified in this environment.
- `app/institutional/instrument_planning.py` adds decimal single-venue limit-order
  projections with pinned metadata, native quantity/contract-unit conversion,
  identity/grid/session/validity/age checks, partial fills, residuals, hypothetical
  fees and signed arrival shortfall. The service now has fifteen operations.
- `/api/instruments` supports admin registration, authenticated search/detail and
  operator/admin planning. Inputs are capped at 2 MB; analysis concurrency shares
  existing process-local slots. Historical plans flag catalog registration after
  decision time; publication/validity times remain unverified source assertions.
- `frontend/src/pages/InstrumentCatalog.tsx` provides revision search, selection,
  registration, planning and JSON export. The canonical `instrument-plan` example
  is also available through the lab, CLI and saved research trials.
- Production startup requires `0003_instrument_catalog`. **The configured
  application database was not migrated.** Back up then upgrade/check before
  deployment. Destructive downgrade is refused to retain history.
- No real feed, broker execution, deployment or empirical performance validation
  was added. This is a supplied-metadata catalog and offline planner. All existing
  work remains uncommitted; no orders, external messages or paid feeds were used.

### Third checkpoint: durable research registry

- Final verification: **151 backend tests passed, 3 PostgreSQL tests skipped**
  (disposable PostgreSQL URL not configured). Full run took about 52 seconds.
  Targeted Ruff and `git diff --check` passed. Final frontend build passed and
  four TradingView tests passed; largest JS bundle is about 697 kB with the
  existing Vite size warning. No visual browser verification was completed.
  The suite reports about 20,387 warnings; this milestone does not clean them up.

- Added append-only `research_families`, `research_runs`, `research_outcomes`
  models and frozen migration `0002_research_registry`. SQLite/PostgreSQL triggers
  reject updates/deletes. A trial request is committed before computation; its
  terminal success/failure/abort is a separate immutable row.
- Production startup now requires revision `0002_research_registry`. **The
  configured application database was not migrated.** Back it up, then run
  `python -m alembic upgrade head` and `python -m alembic check` when deploying.
  Only disposable databases were used for migration tests. Downgrade deliberately
  refuses to drop research history; rollback needs a compatible image/schema plan.
- `backend/app/institutional/registry.py` provides fixed trial-family declarations,
  unique family/trial reservations, exact-input idempotency, source/runtime and
  dataset provenance, parent lineage and append-only terminal finalization.
  Changed inputs need a new declared trial. Failed computations remain recorded.
- `backend/app/api/routes/research_registry.py` adds declare/list/manifest,
  execute/list/search/export and admin abort endpoints under `/api/research-registry`.
  GET allows all authenticated roles; declare/run require operator/admin;
  `/resolve` is admin only. Requests are capped at 2 MB. The two analysis slots
  are shared with unsaved analyses, and 429 does not consume a declared trial.
- Exports verify both stored request and report hashes. Reports reside in the
  application database, with a stable export URL and source/runtime/role/time
  metadata. The full experiment report retains train/test boundaries. Role
  attribution is not individual identity; this registry is shared, not multi-tenant.
- `frontend/src/components/ResearchRegistry.tsx` adds family declaration,
  hypothesis review, current-scenario execution/save, parent/dataset fields,
  family completeness, name/status search, paginated history and view/export.
  It is embedded in Institutional lab. Scenario changes are disabled while a
  registry action is running. Existing unsaved analyses and offline CLI remain.
- `backend/app/institutional/service.py` exposes reusable source/runtime provenance.
  `app/main.py` registers the new router; `app/database/session.py` updates the
  production revision guard. Existing local/development create_all installs guards.
- New tests in `test_research_registry.py` cover persisted success/failure,
  idempotency/conflicts, lineage, interruption/admin resolution, roles, literal
  search, body/capacity limits, direct-SQL immutability, concurrent reservations,
  unexpected/empty errors and detection of privileged request/report tampering.
  `test_migrations.py` verifies migrated guards as well as upgrade/drift checks.
  A new PostgreSQL integration test covers concurrent reservations and guards;
  it requires the existing disposable `TEST_POSTGRES_URL` supplied by CI.
- No background job worker was added. Cancellation/crash after reservation can
  leave a pending run; exact retries return 202 without repeating computation.
  Admin may append an abort with evidence and rerun under a new declared key.
  Aborting does not terminate an already-running thread. First terminal outcome
  wins; a late computation cannot overwrite an abort or another outcome.
- Source/data labels and hashes do not prove genuine preregistration, completeness
  outside a declared family, valid statistics or profitability. Database admins
  can disable triggers; artifact hashes are not signatures.

### Second checkpoint: instrument/data contract

- Added `backend/app/institutional/instruments.py`: sourced/revisioned instrument
  specs with publication/validity times, explicit UTC session windows, Decimal
  price/quantity grids, lot bounds, contract multipliers and minimum notional.
- `instrument-order` validates without rounding or mutating the requested order.
  It exposes each failed check and distinguishes signed reference exposure from
  actual spot cash flow; leveraged-contract margin/payment is never inferred.
- `currency-convert` handles direct/inverse bid/ask pairs and positive/negative
  cash, rejecting wrong, stale or not-yet-published quotes. Same-currency amounts
  need no FX. Decimal results remain strings, including in downloadable reports.
- `service.py` now canonicalizes requests with JSON-mode serialization, preserving
  Decimal inputs for fingerprints and report replay. Existing analyses still pass.
- Both operations are exposed automatically through API capabilities and CLI;
  the dashboard has two new canonical examples (fourteen analyses total).
  Standalone request examples are in `backend/examples/institutional/`.
- Added `test_institutional_instruments.py`: 25 cases covering precision,
  contract size, tick/lot/bounds, metadata timing, session close/expiry,
  inconsistent specs, FX direction/sign/availability and report replay. Two
  additional dashboard example cases bring this checkpoint to 27 new tests.
- Full backend: **138 passed, 2 PostgreSQL skips**. Targeted Ruff and whitespace
  checks passed. Frontend production build and all four TradingView tests passed.
  Largest bundle is approximately 689 kB; Vite's size warning remains. No new
  visual browser verification was attempted; the prior tooling limitation remains.
- These are offline preflight primitives. The existing routing simulator and
  broker worker are not yet integrated with the contract. Instrument calendars,
  provider specifications, FX data, persistence and adapter integration remain.

### Previous checkpoint evidence

- Full backend: **111 passed, 2 skipped**, approximately 14 seconds. The two skips
  are PostgreSQL integration tests because `TEST_POSTGRES_URL` is unset.
- New institutional coverage adds **42 cases** to the prior 69-test baseline.
  Coverage includes all dashboard examples, API 401/403/422/413 behavior,
  deterministic report IDs, CLI overwrite refusal, quantity conservation,
  publication-time leakage, target purging, tail risk, hedges and Greek finite
  differences, plus market-making latency and inventory caps.
- Targeted Ruff checks (`E9,F63,F7,F82`) passed. `git diff --check` passed before
  the final documentation checkpoint; rerun it after edits.
- Latest frontend production build passed. Its largest JS bundle is about
  688 kB uncompressed; Vite reports the existing >500 kB warning. Four TradingView
  tests passed. No unrelated TradingView code was changed.
- Browser skill was read and bootstrap attempted. Browser execution failed
  before connecting: `codex/sandbox-state-meta: missing field sandboxPolicy`.
  This is a tooling limitation. **No visual browser check was completed.** No
  fallback browser, broker session or QA server was left running.
- The backend suite still emits roughly 20,348 warnings from the existing
  dependency/application stack; passing with warnings is not warning cleanup.
- No production database, deployment, live orders, paid data or external messages
  were used. No commit or push was made. All changes remain in the working tree.

## Next concrete work, in priority order

1. **Close UI verification:** restore the Browser tool, use an isolated local API
   with dummy credentials and synthetic inputs, and verify selection, malformed
   JSON handling, report download, signed-out access and responsive layout.
2. **Instrument/data integration:** the supplied metadata/session/tick/lot/FX
   contracts are implemented and tested at checkpoint two; checkpoint four adds
   persistent supplied revisions and pinned single-venue execution planning. Build
   one read-only adapter for an explicitly selected provider, then persist raw
   events with provenance and replay snapshots after gaps. Deriv synthetic
   multiplier feeds must not be presented as exchange depth.
3. **Registry follow-through:** checkpoint three implements the schema, trial
   families, lineage, provenance, search/export, role checks and history UI.
   Remaining extensions are authenticated individual identity/tenant scoping,
   signed audit retention, cross-study analytics and durable job execution with
   progress/heartbeats/cancellation. Do not confuse retained requests with a queue.
   The persistent catalog/planning milestone is verified at checkpoint four.
   Provider ingestion requires explicit provider selection and specifications;
   checkpoint five implements option position aggregation and full-repricing
   scenarios. Checkpoint six adds explicit outstanding-order inventory reservations
   and delayed cancellation scenarios. Next independent offline work can extend
   that ledger with venue rejection/outage events and delayed fill acknowledgement,
   before integrating it with automatic quoting (item 6).
4. **Data-backed validation:** load representative licensed histories, audit
   missing/outlier/corporate-action data and publication lags, calibrate fees,
   spreads, slippage, impact/financing, then run cross-asset/regime experiments.
   Preserve untouched final holdouts and all attempted hypotheses.
5. **Portfolio/instrument extensions:** add liquidity horizons/volume constraints,
   expected-return optimization, option settlement and hedge proposals, and
   explicit client/counterparty netting assumptions. Position Greeks and
   pre-expiry full-repricing shocks are complete at checkpoint five. Keep
   regulatory capital out of scope until jurisdiction/product rules are specified.
6. **Execution simulator:** add queue position/trade-print reconciliation,
   maker/taker fees/rebates, delayed fill acknowledgement, rejection/outage handling,
   hedges and final liquidation costs. Explicit outstanding-order reservations and
   delayed cancel/replacement scenarios are implemented at checkpoint six;
   integration with automatic quoting remains.
7. **Live adapter contract:** design capabilities and durable parent/child order
   states; require idempotency, partial-fill accounting and restart reconciliation.
   Integrate portfolio pre-trade risk only after currency/instrument metadata is
   verified. OANDA/FXCM are still blocked placeholders, not working adapters.
8. **Operations:** durable bounded job workers, cancellation, monitoring/latency
   histograms, signed audit retention, load/fault tests, PostgreSQL concurrency,
   backup restore and rollout/rollback drills. Current thread limit is per process.
9. **Forward demo:** compare predicted/actual costs, fills, inventory, risk and
   signal decay on the chosen provider. Establish acceptance criteria and obtain
   explicit deployment/trading authorization separately.

External inputs needed for those stages: target assets/venues; provider access
and entitlements; representative historical trades/quotes/depth and macro
publication data; instrument specifications and fee schedules; deployment
PostgreSQL/monitoring access; demo account access. Do not invent these values or
substitute the synthetic dashboard data as validation evidence.

## How to resume

1. Read this report and PRODUCTION_READINESS.md; inspect `git status --short`.
2. Read tests and source for the last verified milestone before editing.
3. Backend shell directory: `mean-reversion-bot/backend`.
   Use `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings` and
   `.\.venv\Scripts\python.exe -m ruff check app tests --select E9,F63,F7,F82`.
4. Frontend: `npm run build` and `npm run test:tradingview`.
5. PostgreSQL integration needs `TEST_POSTGRES_URL` for a disposable database.
   Do not substitute a production database. Never print `.env` secrets.
6. Continue the earliest unfinished milestone; update this report with files,
   tests, limitations, commands and the next concrete task.

Suggested continuation instruction:

> Read CONTINUATION_REPORT.md and INSTITUTIONAL_LAB.md. Preserve all existing
> uncommitted changes. Continue the ordered remaining work from the latest
> verified checkpoint, keeping production execution disabled until its explicit
> acceptance checks are met. Update the handoff after each verified milestone.

## Design references

- FIX market data snapshot/incremental concepts:
  https://fixtrading.org/guidelines/data-transparency/
- BIS review explaining tail-risk and liquidity concerns (context, not a claim
  of regulatory implementation): https://www.bis.org/publications/201205-consultation-fundamental-review-trading-book
- OIC Greeks and their model limitations:
  https://prd-web.optionseducation.org/advancedconcepts/volatility-the-greeks
