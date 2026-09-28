# Catalog-backed scanner mappings

Scanner mappings explicitly bind an MT5 server, account and exact symbol to an
existing immutable instrument-catalog revision. They are optional: existing scan
configurations remain valid. Mappings never change the symbol sent to MT5, switch
providers, merge histories or authorize orders.

## Configuration through the local API

1. An admin registers the supplied broker contract with
   `POST /api/instruments/revisions`, or selects an existing revision using
   `GET /api/instruments/revisions`. Its `venue` must be the exact MT5 server and
   `venue_symbol` the exact broker symbol. It must describe a `linear_contract`:
   quantity step/bounds in broker lots and contract size in underlying units per
   lot. Record genuine source, publication time and validity; do not substitute
   a similarly named contract or a spot-quantity specification.
2. An admin submits `POST /api/scanner/mappings` with the following fields:

   | Field | Required value |
   | --- | --- |
   | `provider` | `mt5` (default; other adapters are not implemented) |
   | `server`, `account`, `symbol` | Exact broker identity; account is a positive integer |
   | `revision`, `source` | Mapping revision and supporting source reference |
   | `spec_hash` | 64-character hash returned by the instrument catalog |
   | `quantity_unit` | `broker_lot` |
   | `currency_base` | Expected broker `currency_base` value |
   | `trade_calc_mode` | Expected broker calculation-mode integer, supplied explicitly |

   The API loads and integrity-checks the catalog revision itself. It does not
   accept a replacement specification inside the mapping request. Registration
   returns the content-addressed mapping `id`. Repeating identical input is
   idempotent; changing an existing server/account/symbol/revision returns 409.
   Publish a new mapping revision to change the contract or source assertion.
3. An operator/admin includes `mapping_id` in the selected scanner asset when
   calling `POST /api/scanner/start`, for example:

   ```json
   {
     "assets": [{"symbol": "EXACT_BROKER_SYMBOL", "mapping_id": "RETURNED_64_CHARACTER_MAPPING_ID"}],
     "timeframe": "M5"
   }
   ```

   Replace both placeholders with supplied values. A missing mapping is rejected;
   it never silently falls back to an unmapped scan.

The dashboard has no mapping editor yet. **Load saved scanner settings** retains
mapping IDs on saved selected assets. Registration requires an admin key;
operators cannot create mappings. Viewer keys can read the endpoints below.
Local-host and browser-origin restrictions apply throughout.

## Inspection and comparison

- `GET /api/scanner/mappings?limit=50&offset=0`: paginated registrations.
- `GET /api/scanner/mappings/{id}`: mapping, pinned contract, registration time/role.
- `GET /api/scanner/mappings/compare?left={id}&right={id}`: field-level contract
  comparison. Reports `matching_supplied_terms` or `incompatible_supplied_terms`.
  Matching instrument IDs alone are insufficient; contract size, currencies,
  price/quantity grids, quantity bounds, unit, calculation mode and minimum
  notional are compared too.
- The full scanner JSON export includes a `mappings` array in its consistent
  snapshot, including registered mappings that have not yet been used by a scan.

Comparison always returns `equivalence_verified: false`. Matching supplied terms
do not establish economic/legal equivalence, identical sessions, fees, financing,
settlement, liquidity or execution behavior. The supplied revisions need not be
currently valid merely to inspect or compare them. No cross-provider adapter or
automatic normalization is claimed.

## Runtime checks and retained evidence

At start and on every observation, a mapped scan checks exact broker identity,
base/profit currencies, calculation mode, contract size, tick size and lot
step/bounds. Missing or changed fields reject the mapping. The mapping must have
been registered already, and the catalog publication and validity interval must
cover the observation. Catalog sessions are not automatically imported as scanner
calendars; use the separate [session contract](SCANNER_SESSIONS.md).

Each successful observation and hypothetical trade retains the full pinned
mapping and contract snapshot, with its mapping ID in the policy fingerprint.
If a selected mapping becomes invalid or its broker metadata changes, unfinished
paper exposure becomes unresolved before new candles can manufacture an outcome.
Historical records are not rewritten by later mapping registrations.

Mappings persist in the existing local scanner SQLite journal. The table is
created on scanner initialization; no PostgreSQL schema migration is introduced.
Mapping content is hash-checked and no update/delete API is provided. This is not
a signed audit log, and recorded roles do not identify individual people.

The checks compare supplied metadata, not independently verified broker contract
documents. Minimum notional, financing, commissions and settlement rules are not
validated against the terminal. Non-MT5 mappings and spot-unit mappings remain
unsupported. All implementation tests use isolated synthetic contracts and fake
terminal responses.
