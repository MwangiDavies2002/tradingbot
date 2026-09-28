# Scanner paper spread models

Select **Paper spread model** on the Forward scanner before starting. Saved
settings restore this choice. Operators/admins can change it while stopped;
viewers can inspect outcomes and retained evidence.

The authenticated start API also accepts `spread_model`:

- `fixed_quote` (default): preserves the existing observation-time bid/ask spread
  for the hypothetical trade. Existing policy fingerprints and historical results
  retain their original behavior.
- `candle_proxy_v1`: uses the recorded spread for each outcome candle. It is an
  optional historical proxy, not a reconstruction of executable ask quotes.

The paper model still includes configured adverse ATR slippage and adverse
tick-grid rounding. Commission, financing, quantity/currency conversion and
broker-fill calibration remain unimplemented in scanner outcomes.

## Retained evidence

The MT5 adapter reads the bar's `spread` field and converts points to price units
using captured symbol `point`, never `trade_tick_size`. It records raw points,
point size, decimal price spread, candle timestamp, capture time, exact account
scope/symbol/timeframe, chart price basis and source version
`mt5_copy_rates_spread_points_v1`.

New observations retain the latest bar's spread evidence. In candle-proxy mode,
paper trades retain `spread_history` for every consumed candle, plus `entry_spread`
and `exit_spread`. The original observation spread is kept separately in `spread`.
Exports and the unified evidence browser's Original record retain these fields.
Unused bars in a fetched snapshot are not a separate durable tick/history archive.

Buy entries use the entry candle's spread. Sell exits and stop/target tests use
that candle's spread as an ask offset from bid OHLC. Buy exits remain bid-based.
Closed-candle spread information is available only after the candle completes;
applying it to the opening price is an explicit retrospective cost approximation.
It does not model intrabar spread variation or prove a price was tradable.

## Missing data and model separation

The new mode requires a confirmed bid-based chart and a positive finite point
size and integer spread-point count. Missing, negative, fractional, nonfinite or
unconfirmed zero spreads block a new hypothetical entry, or leave an unfinished
outcome unresolved when encountered later. No zero-cost interpretation or fallback
to the fixed quote is applied. This implementation conservatively treats zero as
unconfirmed, even if a broker might genuinely quote zero spread.

The model is pinned to each trade and included in policy fingerprints. Changing
settings cannot rewrite previous outcomes or change a trade's selected spread
model. Default fixed-model policy hashes remain unchanged. Compare cohorts by
policy; a changed cost model is not an improvement in observed strategy skill.

Symbol point size is captured from current broker metadata; historical changes
to price scaling are not independently reconstructed. Supplied schedules, contract
mappings, and positive spread records do not validate historical broker execution.

## Provider references

- [MetaQuotes Python bar schema](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py)
  includes the spread field.
- [Symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants)
  distinguish point size, tick size, spread points and chart price basis.
- [Bar spread access](https://www.mql5.com/en/docs/series/ispread)
  describes the per-bar spread value and possible error return.
