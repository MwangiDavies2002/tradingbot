# Institutional research lab

This extension implements offline research building blocks from the supplied
institutional-trading overview. Open **Institutional lab** in the dashboard,
select an analysis, edit or upload its JSON scenario, run it and download the
report. Every built-in example is synthetic. No operation submits an order,
starts a worker or changes trading permissions.

## Reproduce an analysis without starting the app

From `backend` in PowerShell:

```powershell
.\.venv\Scripts\python.exe institutional_cli.py route examples/institutional/route.json --output route-report.json
.\.venv\Scripts\python.exe institutional_cli.py option examples/institutional/option.json --output option-report.json
.\.venv\Scripts\python.exe institutional_cli.py market-making examples/institutional/market-making.json --output market-making-report.json
.\.venv\Scripts\python.exe institutional_cli.py instrument-order examples/institutional/instrument-order.json --output instrument-order-report.json
.\.venv\Scripts\python.exe institutional_cli.py currency-convert examples/institutional/currency-convert.json --output currency-conversion-report.json
```

Use a new output filename each time: reports are never overwritten. The CLI
does not load broker settings or require `.env`. Reports contain the complete
normalized request, result, schema version, Python/NumPy/Pydantic versions,
implementation hash and report ID. The ID covers the operation, request, source
and runtime versions; it is provenance, not an authenticated audit signature.
Preserve reports as research artifacts. They can contain private portfolio data.
The standalone CLI still writes local files only; use the registry API/dashboard
for centrally persisted trials.

## Persistent instrument catalog and offline plans

Open **Instrument catalog** in the dashboard. Administrators can register a
specification; authenticated users can search and inspect stored revisions.
Select a revision, supply the order and native book JSON, and generate an offline
plan as operator/admin. Download preserves the exact specification and report.
The prefilled inputs are synthetic examples, not verified provider metadata.

`POST /api/instruments/revisions` registers an immutable specification. Identical
retries return the existing revision; changed content under the same venue,
symbol and revision returns 409. Publish a new revision for changes.
`GET /api/instruments/revisions` supports `q`, `venue`, `limit` and `offset`;
`GET /api/instruments/revisions/{spec_hash}` verifies and returns its content.
`POST /api/instruments/plans` accepts `spec_hash` plus the order/book inputs.
Requests are limited to 2 MB; planning shares the two process-local analysis slots.

Planning checks identity, publication/validity times, same-session book freshness,
tick/quantity grids and order constraints before sweeping price-prioritized depth
within the limit. Decimal results distinguish native quantity, underlying units,
reference notional, hypothetical fees and signed arrival shortfall. Partial fills
retain residual quantity. No order is submitted. Queue priority, latency, impact,
margin and settlement are not simulated. Catalog registration after decision time
is explicitly flagged as backfilled metadata; publication times remain assertions.

The `instrument-plan` operation is also available in the Institutional lab,
research registry and offline CLI with the complete `instrument` in its input.
Standalone reports do not imply a persisted catalog lookup. The catalog is an
append-only supplied-metadata store, not a provider feed or verified security master.

## Durable research registry

Before using the registry on an existing deployment, back up the database and
apply the new migration from `backend`:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
```

The required head is `0003_instrument_catalog`. Production startup refuses the
older baseline. Local development `create_all` also creates the new tables and
their guards. Migration checks in this work used disposable test databases;
your configured application database was not migrated by the implementation.
The migration refuses destructive downgrade to preserve research history.

In the Institutional lab, open **Declare a new trial family**, enter a hypothesis
and the complete list of trial keys, then declare it. Select that family/trial,
enter a run name and a real dataset/source version (or keep the explicit synthetic
label for examples), and choose **Run current scenario & save trial**. Optional
parent run IDs establish lineage; parents must have a terminal outcome. Saved
history supports name/status search, pagination, report viewing and JSON export.
The ordinary **Run offline analysis** button remains an unsaved calculation.

Family declarations, run requests and terminal outcomes occupy separate append-
only tables. The request commits before analysis begins. Validation/computation
failures are retained as failed outcomes, alongside successful reports. Repeating
the exact family/trial request returns its original run. Changing its inputs or
metadata returns 409; use a new declared trial or family. Concurrent requests
share the unique family/trial reservation. Terminal outcomes use first-writer-wins
semantics, so an admin abort cannot later be overwritten by a finishing worker.

Interrupted requests can remain `pending`. Retrying a pending trial returns 202
without rerunning it. There is no background queue, automatic retry, heartbeat
or cancellation scheduler in this milestone. An administrator can append an
`aborted` outcome with evidence via the resolution endpoint, then declare a new
trial with the interrupted run as its parent. Aborting records the decision; it
does not stop an already-running computation thread.

| Endpoint under `/api/research-registry` | Behavior |
| --- | --- |
| `POST /families` | Declare `{family_id, name, hypothesis, trial_keys}`; family ID is 32 lowercase hex characters, allowing safe retry |
| `GET /families` | List declarations; `limit` up to 100 and `offset` |
| `GET /families/{id}` | Manifest with every declared key, attempted runs, missing keys and terminal completeness |
| `POST /runs` | Execute/persist `{family_id, trial_key, name, operation, dataset_version, parent_run_id?, payload}`; 201 for a new terminal success/failure, 200 for an existing terminal run, 202 for pending |
| `GET /runs` | Search with `q` (literal run-name substring), `family_id`, `operation`, `status`, `limit`, `offset` |
| `GET /runs/{id}/export` | Download request, registry metadata and report; verify the saved artifact hash before serving |
| `POST /runs/{id}/resolve` | Admin only; append an abort with `{evidence}` of 20-4000 characters, without rewriting history |

Viewer keys can list/read/export. Operator/admin keys can declare and execute;
only admin keys can resolve. All roles share one registry: this is not a
multi-tenant system, and role attribution is not individual user identity. Bodies
are limited to 2 MB. Analysis slots are shared with the unsaved analysis endpoint;
capacity rejection returns 429 before consuming a trial.

Reports and raw requests are stored in the application database. Exports include
an artifact URL, artifact hash, request hash, dataset version, implementation hash,
runtime versions, parent ID, UTC registration/completion times and role attribution.
Experiment train/test boundaries remain in the full stored request/report.
SQLite/PostgreSQL triggers reject updates and deletes. These protect application
history; a database administrator can still disable guards. Hashes are integrity
checks, not signed or independently timestamped audit evidence.

Family completeness includes failed/aborted trials and only describes that
declared family. It cannot detect unregistered trials or establish statistical
validity, genuine preregistration, profitability or trading approval.

## API and operations

### Automatic quoting

Select **Automatic quoting**, use `POST /api/institutional/auto-quoting`, or run
`institutional_cli.py auto-quoting examples/institutional/auto-quoting.json --output
auto-quoting-report.json` with the backend virtual-environment Python. Saved trials
use the same operation name. The supplied example is synthetic.

This controller shares the order-lifecycle ledger and latency settings. Supply
`fair`, `trade`, `venue` and `connection` events in chronological order (same-time events retain
input order). A fair event has receipt `at_ms`, source `observed_ms` and `price`.
Only a fair receipt can create new quotes; expiry timers request cancellation.
Future observations are rejected and stale fair receipts request cancellation.
No initial quote is inferred from the initial
mark; no future fair value or final mark is used to choose orders.

The fair price is skewed using acknowledged client inventory and
`inventory_skew_bps`. Bid/ask are rounded outward to supplied `tick_size`; sizes
round down to `quantity_step` and respect `order_size` and conservative client
capacity. Unchanged quotes remain in place. Changed quotes cancel first, and
replacement waits until a subsequent fair event with zero same-side reservations.
Unacknowledged fills remain reserved. A new quote cannot cross a known outstanding
opposite order, including one awaiting cancellation.

Reports include the lifecycle tables plus **Quote decisions**, showing the fair
price, known inventory, target prices and actions at each receipt. Maximum: 1,000
source events and 500 generated orders; exceeding the order budget rejects the
analysis. Tick/quantity inputs are hypothetical, not verified instrument metadata.
`quote_ttl_ms` (default 1,000; range 1–60,000 ms) schedules cancellation at the
earlier of receipt time plus TTL and source observation time plus
`max_fair_age_ms + 1`. Source age remains valid at the inclusive maximum; the next
integer millisecond is stale. Eligible fair refreshes renew the timer, including
unchanged quotes. Superseded deadlines are ignored. Timers run before same-time
source inputs and through `end_ms`, even if no further inputs arrive. The decision
table records `fair`/`expiry` triggers and the scheduled expiry timestamp.

Expiry requests cancellation, not immediate order removal: quotes may still fill
during cancel latency or remain reserved through a venue halt. A timer before
submission activation retains the existing pre-activation cancellation rules.
Timers and acknowledgements do not create replacement orders; another eligible
fair receipt is required. Deadlines beyond `end_ms` are not processed. This is an
offline quoting experiment, not a validated market-making
strategy, exchange queue model or broker integration.

### Order lifecycle simulator

#### Fee/rebate and exit-cost scenarios

For `order-lifecycle` and `auto-quoting`, `fee_bps` is signed: positive charges,
negative credits (range -1,000 to +1,000 bps). `fees` is the net signed amount;
`fees_charged` and `rebates_earned` show positive totals separately. Client cash
and fee totals reflect rebates only after fill acknowledgement, just like charges.
This is a supplied resting-fill rate, not proof of exchange maker status or a
calibrated fee schedule.

Optional `liquidation` inputs provide bid/ask, available exit-side quantity,
quote `event_ms`/`available_ms`, maximum age, adverse `slippage_bps` and nonnegative
`taker_fee_bps`. Projection requires a connected client, online venue, no unresolved
reservations/messages/cancels, and a quote available and fresh at `end_ms`.
Otherwise status is `blocked`, with reasons and no projected P&L.

Long inventory projects a sale at bid minus slippage; short inventory projects a
buy at ask plus slippage. Available quantity caps the exit: `partial` retains a
marked residual, `complete` projects zero inventory, and `flat` has no exit or fee.
Results include projected quantity/price, residual, cash change, slippage cost,
taker fee, signed execution cost versus final mark, and projected marked P&L after
exit. Cost versus mark may be negative when the quote is more favorable than that
mark. Hypothetical exit prices do not guarantee fills.

This projection never changes the replayed ledger, fill history, cash or headline
inventory. It is a terminal cost estimate, not an executed closing trade. Financing,
margin, contract settlement and calibrated depth/impact remain unmodeled.

Select **Order lifecycle simulator**, call `POST /api/institutional/order-lifecycle`,
or run `institutional_cli.py order-lifecycle examples/institutional/order-lifecycle.json
--output lifecycle-report.json` from the backend with its virtual-environment Python.
The operation also supports saved research trials through the existing registry.

Supply a single instrument's explicit `submit`, `cancel`, `trade`, `venue`, `reject` and `connection` scenario
events in nondecreasing `at_ms` order. Equal timestamps execute in input order;
cancellations already effective at that timestamp settle before each input.
Order IDs cannot be reused, including after rejection. Maximum: 5,000 events
and 500 submitted orders. Quantities/prices and results use decimal strings.

Accepted orders reserve their remaining quantity immediately, including during
submission latency and pending cancellation. Buys and sells reserve separately:
inventory plus all remaining buys cannot exceed the upper limit; inventory minus
remaining sells cannot breach the lower limit. An order exceeding capacity is
rejected in the report. Cancel requests release capacity only when effective;
duplicate cancels do not restart their timer. Pre-activation cancellation waits
until the original order's activation. A replacement is an explicit new submit
and must pass capacity checks while its predecessor remains outstanding.

Eligible trade-through fills consume one shared `trade.quantity * fill_fraction`
budget across simulated orders in price/time order. Orders fill at their own limit
price, with supplied signed bps fees (negative values are hypothetical rebates). Fills arriving before cancellation takes
effect still count; a fully filled order remains filled. `end_ms` processes due
cancellations and preserves outstanding reservations. It does not close inventory.
The report includes order states, fills, cancellation audit, inventory bounds,
cash, fees and final marked P&L using the explicit `initial_mark`/`final_mark`.

`venue` events carry `online: false/true` to simulate a matching halt/resume.
While halted, fills stop and new submissions are rejected; existing reservations
remain and cancellation acknowledgements wait for resume. This does not simulate
a client network disconnect while a venue continues matching. `reject` events
carry `order_id` and `reason`, acknowledging rejection of any remaining quantity;
earlier fills remain booked. A late rejection of a terminal order is a no-op.

The lifecycle report includes readable metric cards and order/fill/audit tables.
Tables scroll horizontally on narrow screens; the complete JSON remains downloadable.

`fill_ack_latency_ms` adds a fixed acknowledgement delay (default zero, maximum
60,000 ms). Venue fills immediately affect `ending_inventory`, `cash_change`, fees
and marked P&L. Client inventory/cash/fees change only at each fill's `ack_at_ms`.
The acknowledgement panel and downloaded report show both views, per-fill
acknowledgement flags, pending count and unacknowledged quantities by side.

Admission uses client-known inventory plus outstanding quantity and unacknowledged
fills, separately for buys and sells. Unknown opposing fills never net. Cancel or
rejection acknowledgement releases only the unfilled remainder; pending fills
remain reserved. Acknowledgements due exactly at an event time are processed before
that event; zero-delay fills are acknowledged immediately. End time processes only
acknowledgements due by `end_ms`, leaving later ones pending. Delivery continues
during a matching halt if the client is connected. Delivery assumes reliable
buffering, without message loss/reordering. Cancel/reject acknowledgements do not reveal
cumulative fills in this intentionally conservative scenario model.

`connection` events use `connected: false/true` to disconnect/reconnect the client
order session, independently of the venue matching state. A disconnect does not
stop venue fills or already-transmitted cancellations. New client submissions are
locally rejected. Unsent cancellations queue, and their cancel latency starts only
when transmitted after reconnection; duplicate requests do not restart the timer.
Full fills or terminal orders make queued cancels obsolete.

During disconnects, due fill and cancel/reject confirmations remain buffered.
Unreceived terminal confirmations retain the remaining quantity reservation as
well as any unacknowledged fills. Reconnect delivers due messages before transmitting
queued cancels; future-due fill messages still wait. Fill `ack_at_ms` records the
nominal due time and `delivered_at_ms` the actual receipt (null if still pending).
The report shows connection state, queued cancellations and pending terminal
confirmations. Equal-time messages due before a connection event are processed first.
Automatic quote expiry can queue cancellations offline, but reconnect itself does
not place quotes: a subsequent eligible fair receipt is required. This models
reliable reconnect replay, not broker reconciliation, lost messages or a live adapter.

This is a hypothetical single-instrument ledger, not exchange queue reconstruction
or an automatic quoting strategy. Market-data
delay, message loss/reordering, self-trade prevention, instrument grids, hedges,
margin, financing and final exit costs are not modeled. The existing `market-making`
operation retains its original instantaneous replacement assumptions.

### Option portfolio scenarios

Select **Option portfolio scenarios** in the lab, or run from `backend`:

```powershell
.\.venv\Scripts\python.exe institutional_cli.py option-portfolio examples/institutional/option-portfolio.json --output option-portfolio-report.json
```

The synthetic call-spread example is also accepted by
`POST /api/institutional/option-portfolio` and saved registry trials. Each position
has a unique ID, underlying, currency, signed integer contracts, explicit contract
multiplier and European option inputs. All positions must use the same currency;
positions on one underlying must share its spot. Maximum: 100 positions and 50
uniquely named scenarios, each covering exactly every underlying.

`spot_return` is relative (0.10 means +10%). `volatility_change`, `rate_change`
and `dividend_yield_change` are additive decimal changes (0.01 means one percentage
point). `elapsed_days` uses calendar days on a 365-day year. Shocks must leave
positive spot, volatility and time to expiry within the pricing model's bounds.
Horizons at or beyond any expiry are rejected; settlement is not simulated.

Values and Greeks scale by signed contracts times multiplier. Delta and gamma
remain grouped by underlying. Theta is per calendar day; vega and rho are per
one percentage point. Each scenario fully recalculates prices and Greeks and
reports position/portfolio model-value changes, not realized trading returns.
No FX, transaction costs, financing, collateral, legal netting, smile evolution,
American exercise or executable hedge is modeled. Gross option value is the sum
of absolute modeled position values, not notional exposure or capital required.
Greek terminology follows the [OIC reference](https://prd-web.optionseducation.org/advancedconcepts/volatility-the-greeks).

`GET /api/institutional/capabilities` returns input JSON schemas. Submit a schema-
matching body to `POST /api/institutional/{operation}`. Existing access keys apply:
viewer can read schemas; operator/admin can run analyses. HTTP bodies are capped
at 2 MB, with at most two concurrent analyses per API process. Work runs off the
event loop; this is not a durable distributed job queue. The CLI retains schema
row limits but does not impose the HTTP byte limit.

| Operation | Input and result |
| --- | --- |
| `instrument-order` | Versioned supplied specification, quantity, price and decision time -> session/tick/lot/notional checks and signed reference exposure |
| `currency-convert` | Signed amount, currency pair and available FX bid/ask -> liquidation value for positive cash or replacement cost for a liability |
| `replay` | Ordered snapshot/delta events -> spread, microprice, imbalance, depth, feed latency, age and data hash |
| `features` | Published observations and decision times -> point-in-time feature rows; missing/expired values remain null |
| `route` | Fresh venue snapshots, side, size, arrival price, optional limit -> fee-adjusted taker sweep, partial fills, residual and shortfall |
| `schedule` | Quantity, timing, TWAP/VWAP/participation method -> child quantities and unallocated residual |
| `cost` | Notional, spread/fee/slippage bps, volatility, volume, impact and financing assumptions -> separated cash costs |
| `risk` | Signed linear exposures, aligned asset returns, shocks and limits -> historical VaR/ES, correlations, stress P&L, gross/net/factor/counterparty checks |
| `allocate` | Training returns, weight/gross caps, prior weights, turnover limit -> long-only capped inverse-volatility weights and cash |
| `experiment` | Timestamped features and future-return labels -> expanding-window ridge predictions, baseline errors, fold costs and purge diagnostics |
| `multiple-testing` | Complete family of valid p-values -> Benjamini-Hochberg adjusted values and discoveries |
| `option` | European option, spot/strike, years, vol/rate/yield -> theoretical price and five Greeks |
| `option-portfolio` | Signed European positions and complete underlying shocks -> position values, grouped Greeks and full-repricing scenario P&L |
| `quote` | Fair price, inventory, tick and risk settings -> inventory-skewed bid/ask and capacity-limited sizes |
| `market-making` | Quote configuration, received trade prints, fair estimates, latency and fill assumption -> fills, marked P&L, fees and inventory path |

## Units and data contracts

- Instrument specs identify canonical instrument, venue symbol, revision, source,
  publication/validity times, units, contract size, fixed tick/quantity grids and
  quantity/notional bounds. This is a schema for supplied metadata, not a provider
  instrument master. Sessions are explicit UTC windows `[open, close)`; holidays,
  breaks and DST must already be resolved by the data provider. Windows cannot
  overlap or extend past validity. Only zero-origin fixed tick/quantity grids
  are supported. No automatic snapping or order-size changes are performed.
- `instrument-order` reports `order_valid=false` and individual failed checks for
  grid, bound, session or metadata-availability failures. Invalid spec structure
  or unusable FX raises validation errors. These checks do not currently gate the
  existing routing simulator or broker worker. They are an adapter foundation.
- Spot quantities are underlying units with contract size 1. Linear contract
  quantity times contract size gives underlying units; times price gives reference
  exposure, **not** margin or contract cash payment. Exposure is positive for a buy
  and negative for a sell. Only spot reports pre-fee cash flow. Quote/reporting
  values use Decimal and are returned as exact decimal strings; division may
  produce a repeating result rounded to 80 significant digits.
- FX conversion requires one explicit pair, a source and event/publication times.
  Base-to-quote uses bid for positive cash and ask for a liability. Reverse
  conversion divides positive cash by ask and liabilities by bid. Same-currency
  conversion uses 1 and rejects unnecessary FX inputs. No triangulation, fees,
  settlement rules or currency minor-unit rounding are inferred. Instrument
  exposure conversion uses these same liquidation/replacement conventions.

- All times are UTC epoch **milliseconds**, distinct from the legacy OHLC CSV's
  epoch seconds. A receive/publication time cannot precede the event. Features
  unavailable at a decision must not be forward-filled from a later publication.
- Book price is quote currency per asset unit; book/trade size is asset units.
  Deltas replace size at a price; zero removes a price level. Sequences are per
  instrument/venue. A gap blocks the book until a newer full snapshot arrives.
  Invalid updates do not partially mutate a book. Locked/crossed and one-sided
  books are intentionally rejected in this initial implementation.
- Routing accepts only one symbol and quote currency with distinct venues.
  Venue names do not constitute real connections. Fees are positive bps on
  notional, and raw-price limits exclude fees. Shortfall is signed so positive
  means execution cost, measured against supplied arrival price for filled size.
  Unfilled opportunity cost is excluded.
- VWAP volumes must be **ex-ante forecasts**. Participation volumes are supplied
  scenario volumes; schedules are not real-time participation controllers.
- Risk inputs must already use one currency and aligned observation periods.
  Returns are decimal simple returns. Historical risk uses fixed exposures over
  one supplied period, without time scaling. VaR uses the empirical inverse CDF;
  ES averages the worst tail with fractional weight at its boundary. Losses are
  floored at zero. A small effective tail sample is explicitly flagged.
- Factor exposure is signed value times supplied beta. Gross counterparty
  exposure is a concentration proxy, not expected credit loss, netting-set EAD,
  CVA or regulatory capital. Every limited factor needs an explicit beta on every
  position. Scenario shocks must explicitly cover every asset.
- Allocation uses inverse volatility, not expected-return optimization or true
  equal risk contribution. Constant-return assets receive no new allocation.
  Caps can leave cash. Turnover is the L1 sum of asset-weight changes, excluding
  cash; cap-violating prior portfolios require a separate liquidation plan.
- Experiments standardize and fit only label-available training rows. Purging
  uses target availability plus the supplied embargo. Target holding periods
  must not overlap for the simple signed-return cost diagnostic to be meaningful.
  Fold end liquidation is charged. Arithmetic return sums are not equity curves.
  Test data inspected while choosing model settings is no longer a holdout.
- Greeks are per underlying unit: delta/gamma per unit spot movement, theta per
  calendar day, vega per 0.01 volatility change and rho per 0.01 rate change.
  Multiply by signed contracts and contract multiplier for position sensitivity.
- Market-making fills use **previous** quotes, subject to latency/age checks.
  Each print triggers hypothetical cancel/requote; a fixed fraction of crossing
  trade volume fills up to quoted capacity. This is not reconstructed queue
  position. Ending inventory is marked and has not been liquidated.

## What is not implemented

These tools do not supply licensed exchange feeds, order-book reconstruction
from a particular exchange protocol, historical data entitlements, instrument
master/provider FX feeds, real venue execution, market impact calibration, realistic
queue fills, portfolio-to-order integration, option chains, American/exotic
pricing, automated hedging, regulatory capital, client-flow analytics, durable
cross-study experiment analytics, distributed jobs or production-scale latency guarantees.

The broader roadmap and exact remaining tasks are in CONTINUATION_REPORT.md.
The existing bot's live controls remain a separate system; an offline analysis
is not a trading approval. None of the synthetic examples establishes an edge.

## Verification

Tests are in `backend/tests/unit/test_institutional_*.py`. They exercise data
quality, publication-time leakage, quantity conservation, execution cost signs,
hedge/counterparty behavior, tail-mass calculations, allocation caps, finite-
difference Greeks, model purging, market-making timing, HTTP authorization/body
limits, and immutable CLI output. See the continuation report for latest counts
and the browser verification limitation.
