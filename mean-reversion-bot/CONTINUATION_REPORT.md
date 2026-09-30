# Institutional capability expansion - continuation report

## Latest checkpoint: 2026-09-30 - strategy setup versus paper entry

The forward scanner now persists the signal engine's strategy-setup decision
and reason separately from paper-entry eligibility. Its existing RANGE and
instrument/cost gates still control hypothetical entries. The one-pair card
shows both outcomes, including a BUY/SELL setup blocked by the paper gate.
Per-pair evidence now calls the total number of observations **evaluations**;
it includes rejected and error observations, so it was misleading to label
that count as signals. No broker order path or demo rule changed.
Validation: 451 backend tests passed, 3 skipped; 64 focused scanner tests,
frontend production build, and four desktop/mobile scanner/MT5 browser flows
passed. The local API was restarted and is healthy. No MT5 terminal was running.


## Latest checkpoint: 2026-09-29 - visible single-pair signals and Monte Carlo

Analyze now shows each asset's existing Monte Carlo bootstrap metrics directly,
including an insufficient-trades state and the IID/fixed-cash limitation.
Forward scanner now highlights only the latest observation matching its current
single-pair run, exact symbol, timeframe and candidate account. MT5 Demo &
Journal shows the saved pair's last evaluated demo signal and distinguishes it
from a broker fill. No signal generation, research gate or execution rule changed.
Validation: frontend production build and six desktop/mobile browser flows
passed, including wrong-run/account exclusion and insufficient-trade Monte Carlo.


## Latest checkpoint: 2026-09-28 - sequential candidate paper/demo sessions

Demo Start now rejects an active research-candidate forward-paper scanner, closing
the reverse direction of the existing scanner-start guard. The two API start
paths share a transition lock, including first scanner creation, then use the
scanner lock during the final check. Concurrent requests in the single local
API process cannot both pass. Demo readiness names this blocker.
Manual scanner sessions remain independent. Tests cover candidate blocking,
preflight reporting, concurrent start requests and manual-mode behavior; no
broker order was submitted. Validation: 451 backend tests passed, 3 skipped;
the local API was restarted and is healthy.


## Latest checkpoint: 2026-09-28 - read-only live-demo preflight

MT5 Demo & Journal now reports readiness for the one saved broker pair. The
read-only endpoint checks candidate age and strategy, demo account and trading
permissions, exact broker contract, exposure, daily limit, and fresh quotes and
closed candles. It separates setup readiness from live-market readiness so a
closed market can still be monitored without implying a trade can be evaluated.
The preflight never connects, selects a symbol or sends an order. Broker-backed
verification still requires a logged-in MT5 demo terminal and saved candidate.
Validation: 448 backend tests passed, 3 skipped; 35 focused MT5 tests passed
after the final assertion; frontend production build and four desktop/mobile
MT5 browser flows passed. The local API was restarted and exposes the new route.


## Latest checkpoint: 2026-09-28 - attributed single-pair demo comparison

Demo performance comparison now joins each broker entry deal to a successful
order result pinned to the loaded research run, exact saved strategy and demo
account. It groups broker deals by position ID, includes entry and exit deal
costs, and counts a position only when its full volume has closed. Partial exits
remain one position; pre-candidate, other-account, other-run, incomplete and
legacy unlinked positions are excluded. Broker history remains in the journal.
The loaded-candidate status also checks the currently connected demo
account/server, so reconnecting to another account does not appear validated.
The MT5 panel shows research holdout, matching candidate-mode scanner policies
and attributed demo outcomes side by side, without pooling R and currency P&L.

No real account access or broker orders were used for implementation tests;
real-money execution remains disabled. The linked comparison is a monitoring
signal, not approval to trade.

Validation: 445 backend tests passed, 3 skipped; frontend production build and
six desktop/mobile MT5 and candidate-scanner browser flows passed. Existing
candidate reload keeps its original demo observation start time.

## Latest checkpoint: 2026-09-28 - one-pair research candidate in scanner

Forward scanner can now load the server-saved single-pair Analyze candidate already
loaded into MT5 Demo & Journal. The backend rechecks seven-day freshness, exact
demo account/server, broker symbol, timeframe, threshold, saved strategy and
contract fields before scanning. The signal engine uses the frozen candidate's
indicator toggles and account balance. Research run, strategy and contract
snapshot are retained in the paper policy and fingerprint. Contract drift blocks
new signals and makes unfinished hypothetical exposure unresolved. Scanner start
refuses overlap with an active demo execution worker.

Manual exploratory mode stays separate; its existing policy fingerprint is
unchanged. Candidate mode shares signal settings with Analyze and MT5 demo, but
the scanner's RANGE gate and hypothetical fills still differ. No live execution
was enabled or broker terminal connected. See USER_MANUAL.md section 17.

Forward evidence now reports each exact account, broker pair, timeframe and policy
separately. The 300-closed-trade review target is evaluated per row; aggregate
counts across distinct pairs or settings remain context only. Each row shows
observations, unfinished outcomes, scanner runs and its research run when present.

Validation: 15 new candidate and pair-evidence tests, focused scanner regression,
production build and four desktop/mobile visual flows passed. Full backend
regression: 442 passed, 3 skipped.

Next: shared regime/news data and cost/fill comparability, per-setup forward
validation, audited approval, source-backed broker specifications and operational
recovery. Real-account trading remains disabled pending independent validation.

## Latest checkpoint: 2026-09-28 - historical candle-spread provenance

Added optional candle_proxy_v1 paper costs with an explicit scanner UI selector.
The MT5 adapter retains raw bar spread points, captured point-size conversion,
source/identity/timeframe, candle/capture time and price basis. Per-trade consumed
spread history and entry/exit spreads survive persistence, export and the unified
read view. Current broker chart mode must confirm bid OHLC for this proxy mode.

Entries and ask-side exit/stop/target tests use the corresponding candle proxy.
Missing/invalid or unconfirmed-zero spreads block new entries or leave outcomes
unresolved; there is no fallback to an assumed free or fixed cost. Existing fixed
quote policies keep their fingerprints and outcomes. Each new trade pins its
chosen spread model. ATR slippage, tick rounding and calendar rules remain active.

This is a retrospective per-candle cost proxy, not executable ask/tick history.
Current point metadata does not prove historical price-scale stability. Commission,
financing, quantity, FX conversion and empirically calibrated costs remain pending.
See SCANNER_SPREADS.md for configuration, assumptions and provider references.

Validation: 61 targeted tests passed (15 new spread cases plus 46 scanner cases).
Full backend: **427 passed, 3 skipped** in 80 seconds; existing warnings remain.
Ruff and production build passed (existing bundle-size warning). Two isolated
desktop/mobile scanner flows passed; screenshots inspected. The established
Playwright fallback was used after the in-app browser connection limitation.
Tests use simulated MT5 data; no terminal connection, orders,
deployment or user-data migration was performed.

Next: explicit quantity/cost specifications with effective dates, commission,
financing and FX provenance. Historical spread proxies alone do not complete stage 2.

## Latest checkpoint: 2026-09-27 - unified paper evidence read view

Added a common read-only projection for manual and automatic scanner paper records
at GET /api/scanner/paper-evidence. Source-specific cursors page beyond 500 rows;
source-prefixed IDs prevent collisions, scanner states remain authoritative, and
native records/provenance remain available. Manual outcomes retain stored price
change times quantity with unspecified currency; scanner outcomes remain R. No
pooled statistics, historical conversion or journal rewrite was introduced.

The Paper trades page now includes Unified paper evidence with source selection,
latest/older navigation, source units, missing/unresolved outcomes, account/policy
metadata and expandable original records. Viewer access remains read-only. Local
host/origin restrictions protect the scanner journal. Existing manual entry,
approval and close controls remain separate from this read-only view.

Pagination is not a cross-store snapshot. Scanner pages retain their row ceiling;
manual pages use timestamp/ID keysets so normal newer inserts do not shift them.
Backfilled manual rows may appear among older records, and states can change during
browsing. No combined currency P&L is inferred from either source.

Validation: 10 new backend tests passed, including >500-row paging, equal-time
ID ordering, concurrent inserts, native units/state, cursor rejection, viewer/auth
checks and unchanged stored evidence. Full backend: **412 passed, 3 skipped**
(90 seconds), with existing warnings. The 10 focused tests were rerun after the
final asynchronous read adjustment and passed. Frontend build
passed with the existing bundle-size warning. Two desktop/mobile Playwright flows
passed and screenshots were inspected; in-app browser bootstrap remained unavailable
(missing sandboxPolicy), so the established isolated fallback was used. Ruff passed.
No broker connection/orders, deployment or user-ledger migration occurred.

Next: stage 2 time-varying spread/cost provenance and quantity/FX/financing models;
shared regime gates and audited approval remain pending. Stage 1 non-MT5 adapters,
verified provider equivalence, calendar ingestion/editors and retention remain open.

## Latest checkpoint: 2026-09-27 - catalog-backed MT5 mappings

Added explicit immutable scanner mappings to existing instrument-catalog revisions.
Admin registration reads the actual catalog revision and checks its content hash,
exact venue/server/symbol identity and linear-contract broker-lot unit convention.
Server/account/symbol/revision uniqueness prevents silent redefinition; identical
registrations are idempotent. Registrations persist in the scanner SQLite journal.

Optional asset mapping IDs are validated against broker metadata at start and on
each cycle. Currency, calculation mode, multiplier, tick and lot-grid/bound drift,
missing metadata or expired specs reject new entries and preserve unfinished mapped
exposure as unresolved. Observation/trade evidence pins the full mapping and spec;
policy hashes distinguish mapping revisions. Exports include every registration.

Authenticated local read endpoints list, inspect and compare supplied terms.
Comparison distinguishes matching from incompatible supplied contracts without
claiming verified economic equivalence or automatically merging provider data.
Mapping registration is admin-only; viewer reads and existing start permissions
are retained. SCANNER_MAPPINGS.md documents configuration and limitations.

Validation: **402 passed, 3 skipped** in the full backend suite (91 seconds),
including 30 new mapping tests and 75 prior scanner tests. Existing dependency
and application warnings remain. Ruff checks passed. No frontend changes, terminal connection,
broker orders, deployment or user-data migration were performed. Only temporary
SQLite catalogs and simulated broker metadata were used by tests.

Remaining stage 1 work: non-MT5 adapters and validated provider equivalence,
mapping/calendar editor UI, broker-calendar ingestion, validated currency/cost
specifications and retention. A useful next implementation is a unified read view
of automatic and manual paper evidence without rewriting historical records.

## Latest checkpoint: 2026-09-26 - supplied session continuity

Continued stage 1 with optional per-asset source/revisioned UTC calendars, bound
explicitly to the broker account scope and exact symbol. Publication/coverage,
ordered nonoverlapping windows, candle-grid alignment and full-history continuity
are checked. Scheduled closures can separate candles; missing open-session bars,
stale quotes, unavailable/expired calendars and closed sessions cannot approve
new paper entries. Without a calendar, existing strict gap behavior is retained.

Calendars are pinned in policy fingerprints and saved/exported evidence. Paper
entries use the next full scheduled candle, held-bar counts skip closures, and
reopening stop fills retain adverse gap handling. Missing outcome bars and expired
coverage remain unresolved. Historical evidence is not rewritten. Validated closed
history now advances existing outcomes before fresh-entry gates run, so stale
quotes or closed-session rejection do not freeze otherwise observable outcomes.

Configuration is available through the existing authenticated scanner start API;
the dashboard preserves saved calendars but has no calendar editor. See
SCANNER_SESSIONS.md for the contract, provenance requirements and limitations.
No broker calendar is inferred, downloaded or claimed independently verified.

Validation: **372 passed, 3 skipped** in the full backend suite (50 seconds),
including 75 scanner tests, 29 new calendar cases. Existing dependency/application
warnings remain. Ruff checks passed. No frontend source changed. No broker session,
orders, deployment or user ledger migration was performed.

Next stage 1 work: explicit catalog-backed provider mappings, broker-calendar
adapters/UI, validated currency/cost metadata and retention policy. Provider
specifications and equivalence must be supplied rather than inferred from labels.

## Latest checkpoint: 2026-09-26 - broker tick grid for paper outcomes

Continued QUANT_CONTINUATION.md stage 1 with the versioned `tick_grid_v2`
paper model. New observations require a positive finite captured broker tick
size to create hypothetical trades; missing/invalid metadata preserves a rejected
observation. Display precision is never substituted for the contract tick.

Decimal calculations round buy entries up, sell entries down, stops outward,
and exits adversely after slippage. Targets remain 2R from the rounded entry;
R uses the actual rounded stop distance. The original requested risk is retained.
Nonpositive levels remain unresolved. The model version is included in the policy
fingerprint and deduplication key, separating new evidence from earlier policies.
Historical rows are not rewritten; old pending records retain their original model.

Validation: 46 focused scanner tests passed, including buy/sell quarter-tick
fills, coarse-grid risk, timed exits, gap stops after reopening the ledger,
invalid metadata, nonpositive levels and legacy compatibility. Targeted Ruff
checks passed. Full backend regression: **343 passed, 3 skipped** (42 seconds),
with existing dependency/application warnings. No frontend source changed.
Workspace whitespace check reports existing EOF blank lines in jobs.py, schemas.py
and statistics.py. No broker connection, orders, deployment or user ledger access.

Remaining stage 1 work includes explicit catalog-backed provider mappings,
session-aware continuity, validated cost specifications and retention policy.
Tick handling remains a fixed-spread hypothetical model, not broker fill validation.

## Latest checkpoint: 2026-09-26 - scanner identity and evidence access

Continued QUANT_CONTINUATION.md stage 1: exact MT5 identity and raw broker contract,
tick, lot and currency metadata are captured on new observations. Missing values
remain null. Policy snapshots/fingerprints identify configurations; analytics adds
account and policy grouping with a legacy-unknown bucket for older rows.

Scanner settings can be explicitly restored without starting observation, preserving
advanced polling/spread/slippage/holding parameters. Cursor-based evidence browsing
covers history beyond the live 500-row display. JSON export streams all runs,
observations and hypothetical trades from one consistent SQLite WAL read snapshot.
Page membership stays stable under concurrent inserts; mutable trade states can
still update while browsing. No retention/deletion or cross-provider equivalence
mapping is claimed. Existing journals are preserved; metadata is not backfilled.

Validation: 31 focused scanner tests passed, including >500-row pagination,
concurrent-write export consistency, exact identity, authorization and existing
paper simulation/regime/lifecycle checks. Production build passed with the existing
bundle-size warning. Two desktop/mobile history/download/restore flows passed; screenshots inspected.
In-app browser bootstrap was unavailable, so isolated Playwright was used. No terminal connection, trades or deployment occurred.


## Latest checkpoint: 2026-09-26 ? forward scanner and automatic paper evidence

The current ordered continuation list is **QUANT_CONTINUATION.md**. It supersedes
older remaining-work summaries without treating unverified work as complete.

Implemented `/scanner`: continuous read-only observation of up to eight exact MT5
demo symbols; persistent eligible/rejected signals; conservative scanner regime
gates; future-candle hypothetical entries and outcomes; cross-asset dashboard and
R-based breakdowns. Existing manual paper ledger and single-pair execution remain
separate. Scanner never submits or approves broker orders. News is unknown,
liquidity is a spread proxy, scores are uncalibrated indices and sessions are UTC
buckets. Stopped/restarted/gapped outcomes remain unresolved. Provider normalization,
shared execution regime gates, audited approval and portfolio execution remain open.

Validation: 26 scanner/backend tests passed; frontend production build passed;
two isolated Edge desktop/mobile scanner flows passed. Screenshots inspected.
In-app browser bootstrap failed, so established isolated Playwright fallback was
used. Full backend regression: 317 passed, 3 skipped; six additional scanner gate/short-fill tests then passed in the final 26-test targeted suite.
Existing datetime deprecations and the Vite bundle-size warning remain.

No broker connection/orders, deployment or user database migration was performed.
See QUANT_CONTINUATION.md for operation steps, limits and acceptance requirements.


## Checkpoint twenty: legacy research permission coverage

Resumed the automated research workflow from checkpoint nineteen. The durable
Analyze selected assets workflow was already complete: it persists jobs and
artifacts, audits data, validates costed holdout/walk-forward results, reports
relationships, and gates MT5 candidate loading without starting trading.

Added the shared role-aware UI gate to the older Strategy Lab and Research
validation pages. Viewer sessions can still inspect results and download
reports, while backtest runs, candle imports, and validation submissions are
disabled consistently with the API's fail-closed authorization. Replaced two
unsupported `replaceAll` calls in Analyze with compatible regular expressions.

Validation: frontend TypeScript and production build passed. Vite reported the
existing single-bundle size warning (755 kB minified). No broker connection,
orders, deployment, or database migration was performed.

## Checkpoint twenty-one: bounded sensitivity evidence

Extended each automated asset validation report with a deterministic offline
sensitivity matrix: five predeclared confluence thresholds centered on the
selected threshold, crossed with 0.75x, 1x, 1.5x and 2x positive-cost
multipliers on the untouched holdout. Reports now include every case, the
positive-P&amp;L count/fraction and worst-case P&amp;L. The result is descriptive
evidence only; it does not alter strategy selection or the demo-candidate gate.
Analyze displays the summary and retains the full matrix in the saved report.

Validation: 8 focused backend research tests passed; frontend production build
passed; changed Python and TypeScript files report no diagnostics. Existing
Python datetime deprecation warnings and the Vite bundle-size warning remain.
No broker connection, orders, deployment, or database migration was performed.

## Checkpoint twenty-two: stale-price and spread audit metrics

Extended the session-aware candle audit used by Analyze to report the longest
consecutive flat-close run, a stale-close warning, spread observation count,
median/max spread and simple high-spread outlier count. These are explicit
quality warnings and are never silently repaired or used to reject a genuinely
flat market; existing missing-grid, outside-session and unconfirmed-calendar
checks remain the fail-closed data gate. Analyze now shows the metrics beside
coverage and session status, and a regression test covers flat prices and a
spread outlier.

Validation: 9 focused backend research tests passed; frontend production build
passed. The MT5-only environment lacks `statsmodels`, so the test used the
repository backend environment. Existing Python datetime deprecation warnings
and the Vite bundle-size warning remain. No broker connection, orders,
deployment, or database migration was performed.

## Checkpoint twenty-three: actionable session gap ranges

Extended the same session-aware audit to group missing candles into contiguous
timestamp ranges, retaining bounded examples for large gaps. Analyze now shows
the number of missing ranges alongside the missing-bar count, while the full
ranges remain in the saved report artifact. This distinguishes isolated data
holes from whole-session outages without filling or inferring candles.

The MT5 adapter still does not invent broker trading hours: complete calendar
coverage requires a supplied and confirmed session profile, holidays and early
closes. That limitation is now explicit rather than hidden behind a raw gap
count.

Validation: 9 focused backend research tests passed; frontend production build
passed; changed files report no diagnostics. Existing Python datetime
deprecation warnings and the Vite bundle-size warning remain. No broker
connection, orders, deployment, or database migration was performed.

## Checkpoint twenty-four: session-calendar provenance

Made confirmed session calendars require a non-empty provenance reference, such
as a broker schedule, exchange calendar or supplied document. The Analyze form
now captures that reference, and the audit report preserves it beside the
session confirmation state. This prevents a manual confirmation checkbox from
being mistaken for independently verified broker hours while retaining the
existing fail-closed gap checks.

Validation: 9 focused backend research tests passed; frontend production build
passed; changed schema, audit and Analyze files report no diagnostics. Existing
Python datetime deprecation warnings and the Vite bundle-size warning remain.
No broker connection, orders, deployment, or database migration was performed.

## Checkpoint twenty-five: structured no-trade decisions

Completed the next research-report gap: every analyzed asset now receives an
explicit `demo_candidate` or `no_trade` decision. No-trade reports preserve
actionable reasons, including failed data/session quality, unconfirmed costs or
contract specifications, failed validation checks, broker warnings and the
fact that non-MT5 research cannot authorize demo execution. Failed ingestion
also records its error as a no-trade reason. Analyze displays these reasons
beside the asset result; the execution gate itself is unchanged.

Validation: research worker compilation passed; 9 focused backend research
tests passed; frontend production build passed; changed files report no
diagnostics. Existing Python datetime deprecation warnings and the Vite
bundle-size warning remain. No broker connection, orders, deployment, or
database migration was performed.

## Checkpoint twenty-six: forward-demo research baseline

Validated demo candidates now preserve their research holdout baseline with
holdout trade count, P&amp;L, profit factor, out-of-sample trade count/P&amp;L and a
validation timestamp. MT5 Demo &amp; Journal displays the holdout reference when a
candidate is loaded and explicitly labels it as a comparison baseline, not a
live performance claim. No deterioration alert is asserted yet because that
requires actual forward demo observations.

Validation: research worker compilation passed; 9 focused backend research
tests passed; frontend production build passed; changed files report no
diagnostics. Existing Python datetime deprecation warnings and the Vite
bundle-size warning remain. No broker connection, orders, deployment, or
database migration was performed.

## Checkpoint twenty-seven: bounded forward deterioration monitor

Added a forward-demo comparison from the existing MT5 deal journal. Candidate
status now reports `no_baseline`, `insufficient_sample`, `observing` or
`deteriorating`; the latter requires at least 20 closed post-validation trades
and a profit factor below half the research holdout baseline. The MT5 panel
shows the insufficient-sample state or a visible alert, but does not
automatically halt trading or claim statistical certainty. Deal matching is
limited to the candidate symbol and exits after its validation timestamp.

Validation: 29 focused MT5 tests passed; frontend production build passed;
changed worker, panel and test files report no diagnostics. Existing Python
datetime deprecation warnings and the Vite bundle-size warning remain. No
broker connection, orders, deployment, or database migration was performed.

## Checkpoint twenty-eight: custom asset input hardening

Aligned Analyze custom asset entry with the backend symbol contract. The input
now trims values, rejects empty/control-character symbols, caps length at 128
characters and disables Add asset once eight assets are selected. Duplicate
selection behavior remains unchanged.

Validation: frontend production build passed and Analyze reports no diagnostics.
The existing Vite bundle-size warning remains. No broker connection, orders,
deployment, or database migration was performed.

## Checkpoint twenty-nine: stale-price candidate gate

Closed a research-integrity gap: stale close runs were previously reported but
could still qualify an MT5 demo candidate. Candidate eligibility now fails
closed when the audit reaches its stale-close warning threshold, and the saved
asset report records the exact run length as a no-trade reason. Spread outliers
remain visible evidence for review rather than an automatic rejection because
legitimate broker spread widening can occur.

Validation: research worker compilation passed; 38 focused research and MT5
tests passed. Existing Python datetime deprecation warnings remain. No broker
connection, orders, deployment, or database migration was performed.

## Checkpoint thirty: run-level research decision summary

Added a saved summary for multi-asset analyses: total assets, demo-candidate
count, no-trade count, failed count and an overall `candidate_available` or
`no_trade` decision. Analyze displays this summary before the individual asset
reports, making a mixed batch outcome explicit without hiding failed assets or
turning one successful asset into portfolio approval.

Validation: research worker compilation passed; 38 focused research and MT5
tests passed; frontend production build passed; changed files report no
diagnostics. Existing Python datetime deprecation warnings and the Vite
bundle-size warning remain. No broker connection, orders, deployment, or
database migration was performed.

## Checkpoint thirty-one: explicit forward-monitoring states

MT5 Demo &amp; Journal now explains every forward-comparison state: no validated
baseline, insufficient sample, active observation and deterioration alert. The
normal observing state shows the current closed-trade count and profit factor,
so silence is no longer ambiguous while evidence accumulates.

Validation: frontend production build passed; MT5Panel reports no diagnostics.
The existing Vite bundle-size warning remains. No broker connection, orders,
deployment, or database migration was performed.

## Checkpoint thirty-two: full backend verification

Ran the complete backend regression suite after the research workflow, data
quality gates, candidate baseline, forward comparison and decision-report
changes. All 294 tests passed; 3 PostgreSQL-dependent tests were skipped. The
suite emitted the repository's existing Python/Pydantic deprecation warnings,
but no test failures or new diagnostics.

## Checkpoint thirty-three: market behavior diagnostics

Added descriptive per-asset behavior analysis to automated research reports:
annualized realized volatility, lag-1 return autocorrelation, normalized price
trend z-score and a sample-only `mean_reverting`, `trending` or `mixed` regime
label. Degenerate and insufficient histories are reported explicitly. These
diagnostics are evidence for interpretation only and do not alter strategy
selection or authorize trading.

Validation: 12 focused research tests passed; research worker compilation and
frontend production build passed; changed files report no diagnostics. Existing
Python datetime deprecation warnings and the Vite bundle-size warning remain.
The local backend is reachable on port 8000; authentication requires the
access key matching the configured `API_ADMIN_KEY_HASH` in `backend/.env`.

## Checkpoint thirty-four: actionable sign-in failure

Improved AccessGate so an unavailable local backend no longer appears as an
opaque internal error: connection failures now tell the operator to start
`backend/run_local.py` and retry. Auth identity state is typed, and sign-in and
sign-out buttons now declare their form types explicitly. The local FastAPI
service was verified reachable on port 8000; valid credentials still must match
the configured role hash.

Validation: frontend production build passed; the existing Vite bundle-size
warning remains. No broker connection, orders, deployment, or database
migration was performed.

## Checkpoint thirty-five: custom-symbol diagnostic cleanup

Replaced the analyzer-flagged control-character regular expression in Analyze
with an equivalent explicit printable-character predicate. Custom-symbol
validation still enforces trimming and the 128-character limit, while the
Analyze file now reports no diagnostics.

Validation: frontend production build passed; the existing Vite bundle-size
warning remains. No broker connection, orders, deployment, or database
migration was performed.

## Checkpoint thirty-six: Strategy Lab diagnostic cleanup

Cleaned the concrete Strategy Lab diagnostics without changing behavior:
removed unused imports, replaced the default React import with a type import,
associated parameter labels with their controls, added explicit button types
and replaced index-based trade keys with stable trade identifiers.

Validation: frontend production build passed and Backtest reports no
diagnostics. The existing Vite bundle-size warning remains. No broker
connection, orders, deployment, or database migration was performed.

## Checkpoint thirty-seven: end-to-end user manual

Created `USER_MANUAL.md` as the primary step-by-step operator guide. It covers
installation and startup, access-key sign-in, MT5 preparation, Analyze
selected assets, cost/session/calendar validation, report interpretation,
no-trade decisions, candidate loading, demo start/stop, forward monitoring,
common validation errors and system limitations. `MT5_SETUP.md` now links to it
as the starting point while retaining detailed MT5 reference material.

Validation: documentation links and workflow sections were checked in the
workspace. No broker connection, orders, deployment, or database migration was
performed.

## Checkpoint thirty-eight: client-side research validation guards

Updated Analyze to prevent two common submission errors before they reach the
API: slippage ticks cannot be entered below zero, and session-calendar
confirmation remains disabled until a calendar source is supplied. The API
validation remains authoritative, but the form now explains the missing source
inline.

Validation: frontend production build passed; Analyze reports no diagnostics.
The existing Vite bundle-size warning remains. No broker connection, orders,
deployment, or database migration was performed.

## Checkpoint thirty-nine: imported-profile consistency guard

Analyze now validates selected profiles before submission as well as individual
fields. It blocks negative slippage and confirmed sessions with a blank source
even when those values came from an imported JSON profile or from clearing a
previously entered source, and reports the affected asset directly.

Validation: frontend production build passed; Analyze reports no diagnostics.
The existing Vite bundle-size warning remains. No broker connection, orders,
deployment, or database migration was performed.

## Checkpoint forty: unified signal scanner

Added read-only `/api/signals/scanner`, which groups the latest stored signal
evaluation by symbol and timeframe and reports direction, confluence score,
Z-score deviation, Hurst-derived regime proxy, freshness age and reason. The
Signals page now includes a unified scanner table and regime/confluence summary
without treating confluence scores as probabilities or starting execution.

Validation: scanner route compilation, 19 protected API tests, frontend
production build and changed-file diagnostics passed. Existing Vite bundle-size
and Python deprecation warnings remain.

## Checkpoint forty-one: durable paper-trade ledger

Added protected hypothetical paper trading under `/api/paper-trades` with
durable create/list/close operations, explicit entry/stop/target/quantity,
signal score, regime and reason fields. Added a Paper Trades page. The ledger
never submits broker orders and is separated from the live Trade table.
Migration `0004_paper_trades` adds the production table and indexes.

## Checkpoint forty-two: regime dashboard and paper analytics

Signals now summarizes latest mean-reverting, trending and mixed markets plus
score-9+ observations. Paper analytics report sample sufficiency, win rate,
P&amp;L and profit factor overall and by symbol, regime and score bucket. Session
breakdown is explicitly `not_recorded` until paper entries capture session
metadata; no session values are inferred.

Validation: 20 migration/safety tests, frontend production build and changed
file diagnostics passed. Existing Vite bundle-size and Python deprecation
warnings remain.

## Checkpoint forty-three: paper manual approval boundary

Added a durable paper-trade approval state machine: `not_requested`, `pending`,
`approved` and `rejected`, with protected request/approve/reject endpoints and
operator controls in the Paper Trades page. Approval is explicitly paper-only;
ledger responses return `live_authorized: false` and no approval path calls a
broker or MT5 execution route. Migration `0005_paper_trade_approval` adds the
approval state and index.

Validation: migration/safety tests passed; frontend production build and
changed-file diagnostics passed. Existing Vite bundle-size and Python
deprecation warnings remain.

Last checkpoint: 2026-09-25. Status: nineteenth implementation checkpoint
verified (exact broker pair selection on MT5 demo); broader production expansion is NOT complete.

## Checkpoint nineteen: exact MT5 broker pair selection

Connected demo accounts expose a searchable symbol catalog. The UI saves an exact
broker name (including suffixes); Start includes that name and fails if it differs
from the saved configuration. Saving validates tradability and broker metadata;
configuration changes while running are rejected. Connection no longer requires
V75 to exist. No alias mapping or fallback to V75 is performed.

Candles, signals, quotes, protective prices, profit-based lot sizing and orders
use the selected symbol. History requests also carry that symbol, without changing
the saved trading configuration. Session instruments require at least 100 candles;
complete session-aware gap auditing remains outstanding. Execution remains one pair
at a time. Previous bot positions/pending orders block new entries across pairs;
journal recovery includes earlier symbols. Legacy V75 candle dedup keys are retained.

Validation: full backend run passed 286 tests (3 skipped); after additional journal,
signal-symbol and endpoint assertions, the final targeted suite passed 35 tests.
Production build passed (existing bundle-size warning). Six isolated Edge tests
passed at 1440px/390px, covering save/start/stop and switching exact broker symbols,
history source routing and multi-asset research. Both MT5 screenshots were inspected.
Browser plugin bootstrap failed; existing isolated Playwright fallback was used.
All broker responses were simulated. No terminal connection or order was made.

Current operating instructions: MT5_SETUP.md. Its selected-pair workflow supersedes
V75-only instructions in older checkpoint records and the older Word user guide.
Restart the local backend and refresh the UI to load these changes. Next work remains
role UI coverage and bounded offline sensitivity studies; simultaneous multi-pair
execution and true broker-equivalent CFD backtests are not implemented.


## Checkpoint eighteen: chart selection beyond the V75 default

Addressed the user's report that the chart only showed 1HZ75V. Chart asset is now
explicit and separate from the batch selection. Added an exact TradingView
EXCHANGE:SYMBOL input for assets outside the preset list, preserving qualified
provider prefixes rather than prepending DERIV. The chart, links, Pine symbol
guard and downloaded filename all follow the selected chart asset. Removed V75-only
instruction text from the chart panel. The last chart symbol is stored with lab
settings. Platform switching no longer truncates a multi-asset batch to its first
asset; asset buttons can toggle multiple choices in either platform mode.

Scope: custom symbols select TradingView charts/exports, subject to provider
availability. They do not enter the Deriv batch list or add MT5 execution support.
The existing V75-only MT5 worker still needs a separate instrument-aware expansion
before the whole system can truthfully claim all-pairs broker execution.

Validation: production build and five Pine-generation tests passed. Six Edge
desktop/mobile tests passed (four source/batch flows and two chart lifecycle flows).
New assertions cover switching preset/custom chart assets, provider-qualified links,
matching Pine download contents/filenames and retained batch selection across
platform changes. Screenshots inspected; no page errors or main-container overflow.
The opt-in public TradingView smoke test was skipped in this run; chart/provider
responses were stubbed, so universal external symbol coverage is not claimed.
In-app browser bootstrap still fails; used the isolated Edge runner. No broker
connection or trading actions occurred. MT5_SETUP.md contains the new chart workflow.

Next: instrument-aware MT5 expansion needs broker symbol discovery, per-instrument
sizing/limits and tests before multi-pair execution; remaining role UI and bounded
offline sensitivity-study work also remain open.

## Checkpoint seventeen: multiple assets and unsupported test choices

Addressed the user's News-only/Pine rejection screenshot. The Python test form
no longer offers an unimplemented Pine execution selector; News-only is disabled
with an explanation. Test requests explicitly use Python defaults without those
unsupported flags. Backend rejection of unsupported external API requests remains.

With MT5 / Python and Deriv history selected, asset buttons now toggle independently.
Run Combined Test submits one existing single-asset API request per selected asset,
sequentially, retaining successes and showing per-asset errors inline rather than
using alert popups. Progress identifies the current asset. Each run uses the full
starting capital, not shared portfolio capital. Snapshotted timeframe/days remain
attached to results even if form controls change. Result headers wrap on mobile and
chart gradient IDs are unique per result.

TradingView remains one chart at a time. MT5 history/execution remains V75 1s only.
Imports require exactly one selected asset so one file is not silently reused under
different symbols. Provider availability still controls which listed assets can
load candles; an unavailable asset no longer prevents the remaining batch tests.
No broker symbols were invented or execution scope expanded.

Validation: four Edge desktop/mobile flows passed (two source-selection checks,
two batch checks), covering selection/deselection, no-selection disabling, disabled
multi-asset import, successful results around a failed middle asset, and absence
of unsupported flags. Screenshots inspected with no page errors or main-container
overflow. Tests used stubbed market/backtest responses and isolated sign-in; no
live provider-history or terminal verification is claimed. Frontend production
build passed; existing large-bundle warning remains. API code/schema did not change.
Updated MT5_SETUP.md with batch usage and limitations. The role UI and offline
sensitivity-study work listed at checkpoint sixteen remain next tasks.

## Checkpoint sixteen: saved research history and role-aware controls

Added authenticated identity context from AccessGate and fail-closed permission
flags for institutional research and the instrument catalog. Viewer sessions can
browse families, check completeness, view/export saved trials and read instrument
revisions; analysis/trial submissions are disabled. Operators can run/save trials
but cannot register instrument specifications; registration remains admin-only.
The server remains the authorization boundary, and existing API rules are unchanged.
These UI permissions are scoped to Institutional lab/registry and Instrument catalog;
other dashboard control surfaces still need the same UI treatment.

Registry report handling now clears an old success report before saving or viewing
another run, including failed/pending outcomes and export errors. Added explicit
accessible dropdown names and a labelled saved-trials table. Registry fieldset and
section widths allow its table to scroll within the mobile layout.

The isolated visual API now supplies operator/viewer test identities. New real-API
Edge tests create an immutable family and successful/failed trials, check completeness,
view retained results, search/filter empty and failed histories, export identical
artifacts across roles, and verify direct viewer POST/operator registration 403s.
Viewer mutation controls are checked with required fields populated, not just blank
forms. The temporary SQLite database is separate from all configured app databases.

Validation: 36 registry/catalog backend tests passed; production frontend build
passed (existing 500 kB bundle warning remains). Two new desktop/mobile registry
flows passed at 1440px/390px and their screenshots were inspected; no main-container
overflow or page errors. Existing admin lifecycle/catalog flows also passed. Initial
registry browser failures identified ambiguous select names; explicit labels fixed
them. The in-app browser bootstrap remains unavailable, so isolated Edge was used.
No broker connection, trading action, migration, deployment or git commit was made
by this agent. Existing and externally committed workspace changes were preserved.

Next concrete work: expand shared UI permission handling to remaining mutation
surfaces (Strategy Lab, Research validation, MT5 controls, Settings) while preserving
server authorization; add family/pagination history coverage. The bounded offline
sensitivity study and provider/data validation roadmap also remain open.

## Checkpoint fifteen: TradingView chart lifecycle and reload

Fixed the pending external-script/unmounted-container race from checkpoint fourteen.
TradingViewPanel now renders the embed inside a dedicated iframe document keyed
by symbol, timeframe and reload revision. Switching platforms, changing chart
inputs, or reloading destroys the previous document and its script context.
The new `frontend/src/tradingview/widget.ts` builds the document and escapes
JSON configuration against script-tag termination. Failed script loads show a
visible message inside the chart; Reload chart and the external chart link remain
available. The existing provider configuration and Pine generation are preserved.

Validation: frontend production build and all four Pine-generation tests passed.
Two deterministic Edge tests at 1440px/390px cover delayed script arrival after
unmount, rapid timeframe replacement, symbol changes, failed loads and recovery;
both passed with no page errors or main-container overflow. The two existing
historical-source browser tests also passed. Broker endpoints were stubbed.
An opt-in public-CDN smoke test additionally passed: the real provider rendered
V75 1s candles on M15 after platform switching, with no page errors. Its screenshot
and desktop/mobile failure/recovery screenshots were inspected. Initial smoke
assertions were strengthened from frame presence to actual symbol content/canvas;
a wrong expected provider text was corrected using the observed chart content.

Reproduce deterministic checks with `npm run test:visual -- tradingview.spec.ts
backtest.spec.ts`. The public provider check is skipped by default; opt in using
`$env:UI_REAL_TV='1'; npm run test:visual -- tradingview.spec.ts` in PowerShell.
It depends on external provider availability. The in-app browser bootstrap still
fails before connecting; verification used isolated headless Edge. The existing
Vite large-bundle warning remains. No backend code changed in this checkpoint,
so the backend suite was not rerun. No terminal access or trading actions occurred.

Next concrete work: extend UI verification to saved-family/trial history and
role-specific permissions. The bounded sensitivity-study roadmap remains open.

## Checkpoint fourteen: explicit historical sources in Strategy Lab

Following the connected-MT5 user guide, resolved its identified source-selection
gap. In MT5 / Python mode, Historical data source now explicitly selects Deriv
or connected MT5 history. Deriv remains the default; choosing MT5 locks the
instrument to 1HZ75V, including after switching platforms. Imported files override
the history selection. MT5 history errors do not fall back to Deriv.

The backend rejects unsupported MT5 history symbols/timeframes before reading
the terminal. New backtests persist `input_source` in existing params JSON and
return the effective source in immediate/recent results; the UI labels it.
Older runs without the field remain `Not recorded` instead of inferring provenance.
No schema migration is needed. Header controls now wrap on small screens.

Validation: 22 targeted backend tests passed (7 new routing/validation cases,
15 existing MT5 cases); targeted Ruff and frontend production build passed.
Two Edge browser tests passed at 1440px and 390px, with screenshots inspected
and no main-container overflow. Browser tests use real isolated sign-in but
stub backtest/MT5 responses, and block the external TradingView embed. They
verify Deriv/MT5 request selection, symbol lock, missing-terminal error and file
override. They do not verify the user's terminal or execute broker orders.
The in-app browser bootstrap still fails before connecting. An initial unblocked
Edge run revealed an existing TradingView embed `querySelector` error when its
asynchronous script runs after switching platforms (fixed at checkpoint fifteen); do
not count the isolated MT5 test as validation of that widget. Existing Vite bundle
size warning remains. Full backend suite was not rerun for this scoped change.

Updated MT5_SETUP.md and regenerated docs/Mean_Reversion_Bot_User_Guide.docx.
Document structural checks passed; rendered document QA remains unavailable
because LibreOffice is missing. Trading was not started, application databases
were not migrated, and existing uncommitted work was preserved.

Next concrete work at that checkpoint: fix the TradingView widget unmount/load race, then extend
UI verification to saved-family/trial history and role-specific permissions.
The bounded sensitivity-study and other offline roadmap work below remain.

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
| 8 | Protected API, dashboard, offline CLI, reproducible artifacts and observability for new modules | Eighteen analyses, saved trials, protected API and exports implemented; desktop/mobile lifecycle, automatic quoting and catalog browser flows verified; durable workers, broader UI coverage and dedicated telemetry remain |
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

### Thirteenth checkpoint: deterministic queue-ahead volume scenarios

- Verification: **267 backend tests passed, 3 PostgreSQL checks skipped** (no
  disposable URL), 40 seconds, 20,397 warnings. Targeted Ruff and whitespace checks
  passed. Two desktop/mobile browser flows passed; screenshots inspected. Frontend
  build and four TradingView tests passed. Existing Vite bundle warning remains at
  about 716 kB. Playwright stopped its isolated servers after QA.
- Added optional nonnegative `queue_ahead_quantity` per manual submit and as an
  automatic-quoting default for generated orders. Default zero preserves the old
  fill rule. Unchanged quotes retain progress; replacement orders start afresh.
- Eligible prints consume one shared fractional volume budget across queue amounts
  and simulated fills in price/time order. Queue depletion does not change cash,
  inventory, fees or acknowledgement state. Reports retain initial/remaining/
  consumed queue amounts, depletion events and budget/fill/unused reconciliation.
- These are incremental independent per-order volume hurdles, excluding earlier
  simulated orders. Canceled/rejected orders retire residual hurdles. They are not
  cumulative depth, a shared external order book or calibrated exchange queues.
- Eight new regression cases cover queue-first fills, shared budget conservation,
  priority, activation/price/halt eligibility, cancel latency, disconnect behavior,
  replacement/reset semantics, invalid inputs and default-zero parity. UI adds
  queue summary/columns, consumption events and expandable trade allocations.
  Synthetic automatic example and desktop/mobile browser assertions include queues.
- No schema, deployment or live-execution changes. Empirical queue calibration
  remains dependent on representative provider data and actual venue rules.

### Twelfth checkpoint: fee rebates and terminal exit-cost projections

- Backend verification: **259 tests passed, 3 PostgreSQL checks skipped** (no
  disposable URL), 61 seconds, 20,397 warnings. Targeted Ruff passed. Desktop/mobile
  browser flows cover blocked and complete exit panels; screenshots inspected.
  Four TradingView tests pass. Existing Vite bundle warning remains at about 714 kB.
- Screenshot review found cash values wrapping on narrow metric cards; reduced
  mobile metric font size while preserving exact decimal text and larger desktop
  type. Browser flows and production build were rerun after that adjustment.
- Lifecycle/automatic quoting now accept signed `fee_bps` (-1,000 to +1,000).
  Negative fees credit rebates; separate positive `fees_charged`/`rebates_earned`
  reconcile to signed net fees. Client cash/fees still update on acknowledgement.
  These supplied rates do not establish maker eligibility or actual venue pricing.
- Added `liquidation.py`: optional terminal bid/ask, available exit-side quantity,
  timestamp/age, adverse slippage and nonnegative taker-fee scenario. Projection
  blocks if disconnected, halted, unresolved reservations/messages/cancels exist,
  or the quote is stale/unavailable at the horizon. It does not mutate the ledger.
- Ready projections distinguish flat, partial and complete exits. Long positions
  sell at bid less slippage; shorts buy at ask plus slippage. Limited liquidity
  preserves residual marked inventory. Outputs include cash effect, taker fee,
  slippage cost, signed cost versus final mark and projected marked P&L after exit.
  This is hypothetical exit-cost attribution, not a submitted or executed close.
- Thirteen new test cases cover long/short arithmetic, partial/zero liquidity,
  flat exposure, readiness blockers, quote timestamps, signed rebate acknowledgement,
  conservation of marked P&L and invalid inputs. Canonical examples now include a
  blocked lifecycle projection and a complete automatic-quoting projection.
- UI displays net fees, charged fees/rebates and a separate exit-cost panel, including
  blockers and a clear unchanged-ledger statement. Browser checks cover both states
  at desktop/mobile sizes. No schema migration, live trading or deployment.

### Eleventh checkpoint: client order-session disconnect/recovery

- Verification: **246 backend tests passed, 3 PostgreSQL checks skipped** (no
  disposable URL), 57 seconds and 20,397 warnings. Targeted Ruff and whitespace
  checks passed. Two desktop/mobile browser flows passed; current screenshots were
  inspected. Frontend build and four TradingView tests passed. Existing Vite bundle
  warning remains at about 712 kB. Test servers stopped after browser QA.
- Added `connection` events to both lifecycle and automatic quoting. Client
  disconnect is independent of matching halt: existing venue orders keep filling,
  transmitted cancels still execute, and new client submits are locally rejected.
  Unsent cancel requests queue once; cancel latency starts on reconnect transmission.
- Fill acknowledgements and terminal cancel/reject confirmations buffer offline.
  Conservative client reservations retain both unreceived terminal remainders and
  unacknowledged fills. Reconnect delivers due messages before sending queued cancels;
  future-due fills remain pending. Repeated reconnect does not duplicate accounting.
  Full fills/terminal orders make queued cancels obsolete.
- Reports add connected state, queued cancel/pending terminal counts and actual fill
  delivery timestamps alongside nominal due times. UI displays those fields.
  Automatic expiry queues cancellation during disconnect; reconnect alone never
  submits replacement quotes. The synthetic automatic example exercises this flow.
- Seven new regression cases cover matching while disconnected, buffered cash,
  partial message delivery, duplicate commands, cancellation transmission latency,
  unreceived terminal confirmations, full-fill/cancel races and automatic expiry
  through reconnect. Existing browser flows assert connection audit and delivery UI.
- Limits remain explicit: reliable buffering only, no message loss/reordering,
  broker reconciliation, uncertain submit outcomes or executable/live adapter.
  No schema change, application database migration, broker call or deployment.

### Tenth checkpoint: automatic quote expiry

- Verification: **239 backend tests passed, 3 PostgreSQL checks skipped** (no
  disposable URL), 59 seconds, 20,397 warnings. Targeted Ruff and whitespace checks
  passed. Two desktop/mobile browser flows passed with expiry assertions; screenshots
  inspected. Frontend build and four TradingView tests passed. Existing Vite bundle
  warning remains at about 712 kB. No test servers left running by Playwright.
- Added internal `QuoteTimer` events and an ordered timer heap to the shared
  lifecycle engine. Automatic quoting schedules a cancellation decision at the
  earlier of fair receipt plus `quote_ttl_ms` and observed time plus maximum age
  plus one millisecond. TTL defaults to 1,000 ms, bounded to 1–60,000 ms.
- Eligible refresh renews the deadline; generation numbers invalidate older timers.
  Timers run before same-time source events, including a fresh fair receipt, and
  continue during quiet periods up through `end_ms`. Source age remains inclusive
  at `max_fair_age_ms`. Timers never submit replacements or use future fair values.
- Cancellation still obeys venue halt, submit/cancel latency and unknown-fill
  reservation rules. An expired quote may still fill before cancellation takes
  effect. Unacknowledged fills stay reserved after cancellation. Timers after the
  simulation horizon remain unprocessed.
- Seven new regressions cover no-input expiry, exact-deadline ordering, timer
  supersession versus source freshness, halted cancellation, horizon boundaries,
  unacknowledged fill retention and cancellation before activation.
- UI decision table adds Trigger and Expiry columns; the synthetic example has a
  30 ms TTL and expires during its final quiet interval. Desktop/mobile browser
  assertions cover the visible expiry row and column. No new operation/schema,
  live orders, deployment or application database migration was introduced.

### Ninth checkpoint: causal automatic quoting

- Verification: **232 backend tests passed, 3 PostgreSQL checks skipped** (no
  disposable URL), 61 seconds and 20,397 warnings. Targeted Ruff and whitespace
  checks passed. Desktop/mobile browser flows passed with automatic quoting added;
  screenshots inspected. Frontend build and four TradingView tests passed; existing
  Vite bundle warning remains at about 712 kB. Test servers shut down after QA.
- Added `auto_quoting.py`, the `auto-quoting` service operation and canonical lab/CLI
  synthetic example. The authenticated API and existing saved-trial dispatch expose
  it. UI reuses lifecycle metrics/tables and adds a quote-decision table.
- Extended the shared lifecycle engine with bounded generated commands at explicit
  fair receipt events. Controller receives only client-known inventory/reservations,
  own order prices/cancel requests and venue state, not venue fill totals/status.
  Source events are fair receipts, prints and matching halt/resume; direct manual
  submissions/rejections are excluded from this automatic operation.
- Decimal inventory skew, outward tick rounding and downward quantity-step rounding
  determine target orders. Unchanged orders stay in place; changed/stale orders
  request cancellation and replacement waits for a later fair receipt after all
  same-side reservations clear. Known opposite pending orders block crossing quotes.
- Input limit: 1,000 source events, 500 generated orders. Future fair observations
  are rejected. Fair freshness is checked at decision events only. No autonomous
  timer/expiry or acknowledgement-triggered refresh; final marks never drive quotes.
  Historical standalone `market-making` behavior remains unchanged.
- New tests check grid/size constraints, zero capacity, unchanged quote retention,
  future-data/final-mark independence, hidden fill state, delayed cancellation,
  stale observations, matching halts and prevention of crossing own pending orders.
  API/CLI tests include the new operation. Browser flows include rendering the
  automatic decision report at desktop and mobile widths.
- No broker integration, production migration or performance validation. Real data,
  queue calibration, autonomous timer semantics and executable acceptance remain.

### Eighth checkpoint: delayed fill acknowledgements

- Verification: **221 backend tests passed, 3 PostgreSQL checks skipped** (no
  disposable URL), 51 seconds, 20,397 warnings. Targeted Ruff and whitespace checks
  passed. Two browser flows at 1440x1000 and 390x844 passed, with current screenshots
  inspected. Frontend build and four TradingView tests passed; existing Vite bundle
  warning remains at about 711 kB. Isolated browser test servers stopped after QA.
- `order_lifecycle.py` now accepts bounded `fill_ack_latency_ms` (default zero).
  Venue inventory/cash/fees and client-acknowledged inventory/cash/fees are separate.
  A FIFO acknowledgement queue processes due fills before each input, immediately
  after zero-delay fills, and at simulation end. Each fill records its due time
  and acknowledgement flag; orders retain acknowledged filled quantity.
- Admission uses client inventory and separate buy/sell reservations comprising
  outstanding size plus unacknowledged fills. Cancel/reject acknowledgements only
  release unfilled remainder, including after partial fills. Unknown opposing
  fills do not net and unconfirmed risk reduction cannot fund new capacity.
- Reports expose client exposure bounds per input, terminal client reservations,
  unacknowledged quantities and pending acknowledgements. Existing headline values
  and order states remain venue truth. Fixed reliable delivery continues during
  matching halts; message loss/reordering and disconnect recovery are not modeled.
- Added six regression cases for exact acknowledgement timing, conservative
  capacity, cancel/reject races, opposing fills, partial end-time acknowledgement,
  halt delivery, zero-delay parity and client/venue cash/fee reconciliation.
  Corrected default zero inventory to a Decimal so untouched ledgers serialize
  consistently as decimal strings.
- Lifecycle UI adds an explicit client acknowledgement panel and fill due-time/
  acknowledgement columns. Synthetic example deliberately ends with one pending
  acknowledgement. Browser assertions verify both visible client state and the
  client/venue discrepancy in the downloaded report at desktop/mobile sizes.
- No schema change, broker connection or production migration. This remains an
  explicit offline scenario model; automatic quoting integration is still pending.

### Seventh checkpoint: venue events, readable reports and visual UI verification

- `order_lifecycle.py` accepts explicit `venue` matching-halt/resume and `reject`
  remainder-rejection events. Halts prevent fills/new admission but preserve
  outstanding reservations; due cancellation acknowledgements wait for resume.
  Explicit rejection releases the remaining quantity while preserving prior fills.
  This is a matching halt, not a network disconnect. Fill acknowledgements remain
  immediate; delayed fill knowledge and automatic quoting integration remain next.
- Added four lifecycle regressions and updated the synthetic example. Full backend
  verification: **215 passed, 3 PostgreSQL skips**, 50 seconds, 20,396 warnings.
  Targeted Ruff passed. Frontend production build and four TradingView tests pass;
  existing bundle-size warning remains (about 710 kB).
- `LifecycleReport.tsx` displays decimal metrics, order states, fills, event audit
  and assumptions; raw JSON/export remains available. Navigation collapses to
  labeled icons on mobile. Browser testing found catalog fieldset/search overflow;
  fixed minimum widths and stacked search controls on narrow screens.
- **Visual verification completed** using standalone headless Microsoft Edge via
  Playwright after the in-app browser again failed on `sandboxPolicy`. Two browser
  tests passed at 1440x1000 and 390x844. Inspected actual screenshots at both sizes.
  Verified sign-in, malformed JSON, real lifecycle analysis, visible rejection,
  JSON download contents, catalog registration/planning, sign-out, no page errors
  and no horizontal page/main overflow. Wide report tables scroll within their cards.
- Reproduce with `npm run test:visual` in frontend. `playwright.config.ts` starts
  isolated loopback API/frontend servers on 8017/4173 and stops them after tests.
  `backend/tests/visual_api.py` uses a disposable SQLite database and dummy access
  key, avoids loading application `.env`, and includes only real research/catalog
  routes plus test identity/health endpoints. It never starts broker services.
  Defaults to installed Edge and backend Windows virtualenv; `UI_BROWSER_CHANNEL`
  and `UI_PYTHON` can override those for other environments.
- Screenshots: `frontend/test-results/research-research-lifecycle-and-catalog-at-1440px/`
  and corresponding `...-390px/`, each with `lifecycle.png` and `catalog.png`.
  Test artifacts are ignored by Git and regenerated on each run. Added Playwright
  development dependency. npm reported 8 dependency advisories; no broad dependency
  upgrade was attempted in this milestone.
- Scope: these browser checks cover lifecycle/catalog workflows against the isolated
  test API, not the full trading dashboard, deployment or all saved-registry flows.
  No production migration, live order or deployment occurred. Work already present
  was preserved; no commit or push was made by this agent.

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

1. **Broaden UI verification:** checkpoint seven verifies lifecycle/catalog flows
   at desktop/mobile sizes against an isolated real API. Extend browser coverage
   to saved-family/trial history, role-specific permissions and other lab operations.
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
   and delayed cancellation scenarios. Checkpoint seven adds matching halt/resume
   and remainder rejection. Checkpoint eight adds delayed fill acknowledgement and
   conservative client-known reservations. Checkpoint nine adds a causal quoting
   controller driven by explicit fair receipts. Checkpoint ten adds automatic
   quote-expiry timers with cancel-latency handling. Checkpoint eleven adds client
   disconnect/recovery and buffered message delivery. Checkpoint twelve adds signed
   fee/rebate scenarios and explicit end-of-run exit-cost projections. Next independent
   work at checkpoint thirteen adds deterministic per-order queue-ahead scenarios.
   Next self-contained work can compare supplied fill/latency/cost assumptions in
   a bounded sensitivity study with reproducible reports and worst-case summaries;
   empirical queue/fill calibration still requires suitable supplied data (item 6).
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
   calibrated maker/taker fees, queue-ahead scenarios, message loss/reordering,
   hedges and simulated executable liquidation. Signed fee/rebate and terminal
   exit-cost projections are implemented at checkpoint twelve. Outstanding reservations and
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

## Deriv history HTTP 520 fix - 2026-09-25

Historical backfills now use Deriv's documented public market-data WebSocket
(wss://api.derivws.com/trading/v1/options/ws/public), without account credentials
or the legacy authenticated trading client. This resolves the reported legacy
connection failure in the verified read-only smoke test: 288 real 1HZ75V M5 candles
were fetched and cached into an isolated in-memory SQLite database.

Transient transport failures, HTTP 429 and 5xx responses receive at most three
attempts with bounded timeouts/backoff. Permanent request errors fail immediately;
persistent outages explain retry, MT5 history and import options. Requests page at
5,000 candles, exclude the forming bar, and insert in small database batches.
MT5 source selection remains explicit; no cross-provider fallback was introduced.
Twelve targeted tests cover retries, failures, pagination, SQLite deduplication and
source routing. Restart the backend to load this fix; no user database or broker
session was used by the smoke test.

Provider documentation: https://developers.deriv.me/docs/options/ws-public/
