# Autonomous quantitative laboratory: implementation and continuation

Updated 2026-09-28. This is the ordered continuation list requested by the user.
Earlier checkpoints describe historical capabilities and are not current acceptance claims.

## Delivered in this checkpoint

- Local MT5 forward scanner: choose 1-8 exact broker symbols and M1/M5/M15/M30/H1/H4; backend polling continues while the page is closed, while this backend stays running.
- Read-only snapshot adapter uses the existing connected demo account. No order submission or execution configuration changes. Broker account/server, exact symbol and timeframe identify observations. Display labels never substitute broker aliases.
- Durable `backend/data/scanner.sqlite3`: run configuration/role, latest observations, eligible/rejected decisions and automatic hypothetical trades. Same account/symbol/candle/policy is deduplicated even across runs. Failed assets remain visible while other assets continue.
- Existing confluence engine plus a scanner-specific conservative gate: RANGE, TREND, HIGH_VOLATILITY, LOW_LIQUIDITY proxy, UNCERTAIN and UNKNOWN. Invalid/stale candles, recent gaps and stale quotes reject observation. Score is points/20 capped at 100, NOT probability or validated confidence.
- Paper entry on the first full candle beginning after observation, adverse configured ATR slippage, observed fixed spread proxy, 1.5 ATR stop / 2R target, bounded holding period. Same-candle stop wins ambiguity. Gaps and stopped/restarted exposure remain unresolved. One hypothetical exposure per symbol per scan.
- Dashboard at `/scanner`: selected assets, deviation, regime, score, side, reason, paper outcomes and analytics by symbol, score bucket, regime, UTC time bucket, setup, volatility and news-unknown state.
- Outcomes measured in R, not combined currency P&L. No commission, financing, depth or calibrated historical spread model is asserted. Fewer than 300 closed outcomes are exploratory; exceeding 300 requires review, never automatic promotion.
- Operator/admin control, viewer read-only; loopback/origin restrictions; process lock prevents concurrent scanners sharing a ledger; persisted stop requests; restart does not auto-resume.

## Scanner hardening follow-up - 2026-09-26

Delivered after the initial scanner milestone:

- New observations carry exact provider/server/account/symbol identity, broker contract/tick/lot/currency metadata where available, capture time, policy settings and a policy fingerprint. Missing metadata stays null; historical records are not retroactively invented. Display labels do not imply provider equivalence.
- Analytics can group closed outcomes by account scope and policy fingerprint; older records use an explicit legacy-unknown policy group.
- **Load saved scanner settings** restores selected assets, timeframe, threshold, polling, spread/slippage limits and holding period. It does not start scanning or overwrite broker execution settings.
- **Saved evidence** pages through signals/rejections and paper trades beyond the 500-row live view. A fixed row boundary and keyset cursor avoid shifting pages when new observations arrive. Trade outcomes can still evolve during browsing.
- **Download all evidence (JSON)** exports a consistent snapshot of every run, observation and hypothetical trade, including authoritative unresolved/closed state and account identifiers. SQLite WAL permits scanning writes while the export reads; the server streams rows rather than constructing the entire journal in memory. The browser still buffers the downloaded file.
- Export/history endpoints preserve viewer read access, mutation restrictions and loopback/origin checks. No deletion/retention policy has been enabled.

## Required operator workflow - 2026-09-28

The user requires testing one exact pair at a time through backtest, forward test
and live-market demo testing (explicitly confirmed by the user). Preserve single-pair
selection, per-pair results and exact
broker identity across all stages. Current MT5 execution is demo-only; real-money
accounts remain blocked. No broker orders were requested by this workflow statement.
The scanner can now load the server-saved research candidate for one pair and
match signal-engine toggles/threshold; its separate regime and fill gates still
prevent identical cross-stage trade claims.
Forward evidence now separates results by account, exact pair, timeframe and
paper policy. The 300-closed-trade review target is per such series, never the
pooled count across experiments. Pending and unresolved outcomes remain visible.
See USER_MANUAL.md section 17 for the currently available per-pair workflow.
MT5 Demo & Journal now presents the three stages for the loaded candidate.
Demo monitoring counts only fully closed broker positions traced through a
successful order result to that exact research run, strategy and account;
legacy unlinked and incomplete positions do not inflate the comparison.
Verification: 51 targeted history-routing, exact-symbol execution, account checks
and single-asset scanner tests passed using simulated terminal responses.

## Ordered remaining work and acceptance evidence

1. **Scanner hardening and instrument identity** — MT5 multi-symbol observation delivered; cross-provider normalization remains pending. Explicit catalog-backed MT5 mappings with account/server and contract provenance are delivered. Remaining: non-MT5 adapters, validated provider equivalence, mapping/calendar editor UI, automatic broker-calendar ingestion, currency/cost metadata and retention. Explicit supplied UTC calendars now support session-aware scanner/paper continuity; provider schedule validation and a calendar editor remain pending. Versioned broker tick-size rounding for hypothetical fills is delivered; real fill validation remains pending. Export/pagination and raw broker identity/metadata capture are delivered; cross-provider equivalence and validated cost specifications are not. Add data source adapters without guessing aliases or silently switching providers. Verify equivalent and non-equivalent contracts distinctly.
2. **Paper ledger realism and consolidation** — automatic forward ledger delivered separately from the pre-existing manual ledger. Unified source-selected read views are delivered without rewriting historical/manual evidence; source-specific units and provenance are retained. Optional historical candle-spread proxies with retained source/conversion provenance are delivered; executable ask history and validated point-scale history remain pending. Record commission, financing, quantity and FX conversion with effective-date provenance; supplied session calendars are already retained. Verify bid/ask, gap fills, latency, stop/target ambiguity and restart recovery. Preserve unresolved outcomes in reporting.
3. **Unified regime gate** — scanner-only heuristic delivered. Version and validate a shared model used consistently in research, paper and demo paths. Add trend-strength/liquidity inputs and reliable news coverage. Never classify absent news data as safe; distinguish news-active, stale and unavailable states. Current scanner news is explicitly unknown and cannot approve execution.
4. **Signal analytics** — descriptive R breakdowns delivered. Account/policy grouping is delivered. Add confidence intervals, expectancy/drawdown by cohort, matched account/policy comparisons, selection-bias checks, cost-adjusted outcomes, real trading sessions and observed news proximity. Require enough independent evidence per setup/regime, not merely a pooled 300-row total. Current score index is not a calibrated confidence forecast.
5. **Audited signal review** — pending. Existing manual paper approval labels do not authorize trades and do not provide a complete approval audit. Add immutable Accept/Reject/Expire events, actual user identity (current keys identify roles), mandatory reason, server timestamps, expiry and idempotency. Revalidate quote, symbol, account, regime and portfolio risk at acceptance. Race/replay tests must pass before connecting approval to demo submission.
6. **News and macro inputs** — pending dependable execution integration. Choose licensed/available calendar, DXY, yields and correlation feeds; record timestamps/provenance/currency mappings. Exercise blackout windows, revisions, stale data and outages. External subscriptions/credentials and source coverage must be supplied before claiming integration.
7. **MT5 portfolio execution** — pending; existing worker remains one exact broker pair at a time. Add per-symbol contract/session/cost specifications and portfolio exposure/correlation limits. Exercise concurrent entries, partial fills, rejections, uncertain orders, duplicate approval, broker restart and netting/hedging behavior on isolated tests before a separately authorized demo pilot. No live execution enabled by this checkpoint.
8. **Forward validation** — collection infrastructure delivered, evidence NOT collected by this implementation. Start scanner on the intended demo catalog and accumulate at least 300-500 completed forward signals, including rejected-signal counts and unresolved outcomes. Compare spread, slippage and broker fills with paper/research assumptions by setup/regime. Do not fabricate samples or accelerate timestamps to pass a gate.
9. **Production operations** — pending environment exercises. PostgreSQL migration/rollback, backup/restore (including local scanner/research journals until migrated), monitoring credentials, alert delivery, outage drills and recovery. Read-only/local automated tests do not constitute deployment acceptance.
10. **Learning loop** — pending. Predeclare candidate changes; compare on untouched data and forward cohorts; version models and preserve rollback. No self-retraining or automatic risk expansion from recent wins.

## How to use the delivered stage

1. Restart the backend and refresh the frontend.
2. Connect your MT5 **demo** account from MT5 Demo & Journal; do not start demo execution just to scan.
3. Open **Forward scanner**, click **Load broker symbols**, select your exact pairs, timeframe and score threshold.
4. Click **Start paper scanner**. Keep the backend and terminal running. Read latest observations, paper ledger and forward-evidence groups.
5. After a reload, use **Load saved scanner settings** to restore your prior setup. Use **Saved evidence** for older records and **Download all evidence (JSON)** for a full snapshot.
6. Stop before changing selections. Stop affects only this scanner; it does not close positions or stop the separate MT5 execution worker. Unfinished hypothetical outcomes become unresolved.

No terminal connection, real/demo orders, production deployment, or user data migration was performed while building/testing this checkpoint. All UI feeds and MT5 responses were simulated.


## Tick-grid paper follow-up - 2026-09-26

- New `tick_grid_v2` policies require a positive finite captured broker tick size.
  Missing metadata preserves the observation as rejected without creating a trade.
- Decimal grid calculations round entries/exits adversely and stops outward;
  targets are 2R using the actual rounded stop distance. Requested risk is retained.
- Nonpositive levels remain unresolved; old journal records retain their original
  simulation. Policy fingerprints distinguish the new model from historical evidence.
- 46 focused scanner tests passed; full backend: 343 passed, 3 skipped.
  Targeted Ruff checks passed. No broker connection or orders were used.
- Next: catalog-backed mappings and session continuity with explicit provenance;
  costs and retention remain pending. No cross-provider equivalence is inferred.

## Supplied session continuity follow-up - 2026-09-26

- Optional exact-account/symbol UTC calendars carry source, revision, publication
  time and explicit coverage. Complete open windows are supplied by the operator;
  no market schedule or DST conversion is inferred.
- All returned history must fit scheduled windows; missing open-session bars
  reject observations. Existing freshness checks still apply. Unknown calendars
  retain strict gap handling. Invalid or unavailable calendars fail closed.
- Calendar policy fingerprints and exports preserve provenance. Paper trades use
  pinned schedules, skip closures, and retain adverse reopening gap fills.
  Missing bars and expired coverage remain unresolved. Old rows are unchanged.
- Valid closed history resolves existing outcomes before fresh-entry gate checks;
  malformed/future history and changed accounts cannot advance the ledger.
- API configuration and limits are documented in SCANNER_SESSIONS.md. Dashboard
  saved-setting restoration retains calendars; no calendar editor was added.
- Validation: full backend 372 passed, 3 skipped, including 75 scanner cases;
  targeted Ruff passed. All calendars/MT5 data were simulated. No orders were sent.
- Next: catalog-backed mappings, provider calendar ingestion/UI, validated costs
  and retention. None of these supplied schedules is broker-validated evidence.

## Catalog-backed MT5 mapping follow-up - 2026-09-27

- Admin registration binds exact server/account/symbol to an integrity-checked
  catalog revision with explicit broker-lot units and source/revision provenance.
  Immutable revision registration is idempotent; changes require a new revision.
- Optional mapping IDs pin contract snapshots in observations and hypothetical
  trades. Runtime checks reject unknown/changed metadata or unavailable contracts;
  unfinished mapped exposure becomes unresolved before outcomes are advanced.
- Viewer-readable listing/detail/comparison APIs and full-journal export preserve
  registrations. Comparison separates differing supplied terms from matching
  terms; neither names nor matching terms establish verified economic equivalence.
- API usage and limits: SCANNER_MAPPINGS.md. Dashboard restoration keeps IDs;
  a mapping editor and non-MT5 data adapters remain pending.
- Validation: full backend **402 passed, 3 skipped**, including 30 mapping tests
  and 75 prior scanner tests; targeted Ruff passed. No real contracts or fills validated.

## Unified paper evidence follow-up - 2026-09-27

- Paper trades now includes a unified read-only evidence browser for manual entries
  and automatic scanner records, with source selection, keyset pagination and
  expandable native records. Pending/unresolved outcomes remain explicit.
- The authenticated local GET /api/scanner/paper-evidence endpoint accepts
  source=manual|scanner, limit=1..200 and an opaque source-specific cursor.
  Read views never recalculate old outcomes or pool manual raw units with scanner R.
- Separate stores are retained. Paging is not a joint snapshot; states can evolve,
  and backfilled manual entries can appear among older records.
- Validation: full backend 412 passed, 3 skipped; 10 focused tests rerun after
  the final read adjustment passed. Production build and two desktop/mobile UI
  flows passed; screenshots inspected. Targeted Ruff passed.
- Next stage 2 work: historical spread and cost provenance, quantity, FX conversion,
  financing and broker-fill comparisons. Existing approval labels are not an audit.

## Historical spread-proxy follow-up - 2026-09-28

- Optional candle_proxy_v1 spread model is selectable in the scanner UI and API;
  saved settings preserve it. The default fixed_quote model remains unchanged.
- New MT5 observations retain bar-spread points, point conversion, capture/candle
  timestamps, identity and price basis. Consumed per-trade spread evidence is saved
  with entry/exit spreads and exposed in exports/original-record views.
- Missing/invalid/unconfirmed-zero spreads fail closed without cost fallback;
  confirmed bid chart basis is required. Policy fingerprints separate cost models.
- This is a retrospective candle proxy, not executable ask history or historical
  price-scale validation. Commission, financing, quantity and FX remain pending.
- SCANNER_SPREADS.md documents assumptions and source references. Full backend:
  427 passed, 3 skipped; targeted Ruff, production build and two desktop/mobile
  scanner flows passed. Screenshots inspected; all terminal responses simulated.

## Single-pair research candidate scanner - 2026-09-28

- Forward scanner now offers **Use loaded research candidate**. It reads the
  server-saved Analyze candidate already loaded into MT5 Demo & Journal and
  selects exactly one pair, timeframe, indicator configuration and threshold.
- Backend rechecks candidate age, account/server, exact broker symbol, timeframe,
  threshold and contract metadata; it rejects demo-worker overlap. Contract drift
  during scanning leaves unfinished hypothetical exposure unresolved. Client-
  submitted strategy fields cannot replace the server-saved candidate at start.
- Policy fingerprints and evidence retain the research run, frozen strategy and
  contract snapshot. Manual exploratory scanning remains a separate mode with
  unchanged policy fingerprints.
- The scanner's conservative regime filter and fill assumptions remain distinct
  from historical Analyze and actual MT5 demo fills. This is signal-setting parity,
  not full trade/outcome parity or live authorization.
