# V75 1s Strategy Lab on TradingView

TradingView is now the default on the home page and Strategy Lab. It does not
call the local MT5 API, so it works as a frontend on Vercel. The MT5 tab on
a hosted site explains that desktop connectivity requires the local app.

## Change the confluence requirement

Choose a minimum score from 1 to 20 in the lab. Quick buttons offer 1, 2, 3
and 6; six is not mandatory. The Pine exporter rejects thresholds above the
maximum achievable by the selected indicators. Settings persist in this
browser; they are not synchronized between devices.

The TradingView companion implements these conditions:

| Condition | Buy | Sell | Points |
|---|---|---|---|
| Z-Score, 20 bars | Z <= -2 | Z >= 2 | 2; 3 when absolute Z >= 3 |
| RSI, 14 bars | RSI < 25 | RSI > 75 | 2 |
| Bollinger Bands, 20 bars / 2 SD | Below lower band | Above upper band | 1 |
| UTC daily VWAP | Below by at least 1.5 ATR | Above by at least 1.5 ATR | 1 |
| Stochastic, 14 bars / 3 smoothing | K < 15 | K > 85 | 1 |
| Volume | At least 1.5 times its 20-bar average | Same | 1 context point |

Choose just Bollinger Bands and threshold 1 for a single-condition experiment.
Volume alone cannot establish a direction. Tied buy and sell directional
scores do not trigger entries. VWAP and volume signals require volume data.
LSL, SMC and Hurst are explicitly unavailable in the Pine companion; use
Python/MT5 for those. No substitute calculations are silently exported.

## Watch simulated trades in TradingView

1. Select indicators, score and timeframe in Strategy Lab.
2. Click **Copy Pine strategy** or **Download Pine strategy**.
3. Open [V75 1s on TradingView](https://www.tradingview.com/chart/?symbol=DERIV%3AVOLATILITY_75_1S_INDEX).
4. In Pine Editor paste the script, save it, and choose **Add to chart**.
   Set the chart timeframe to the one you want to test.
5. The strategy evaluates completed candles and simulates entries on the
   next available emulator tick. Stop and target distances use ATR at the
   signal and are applied relative to the entry fill. Existing simulated
   positions must exit before another entry can occur.
6. Open **Strategy Tester → List of trades** for the entry/exit record.
   Export it from TradingView to retain the experiment. Set suitable quantity,
   commission, slippage and capital in the script/strategy settings.
7. To use a different threshold tomorrow, edit **Settings → Inputs → Minimum
   weighted score**. Changing lab settings does not modify a script already
   installed on TradingView. Export the old trade list before changing inputs,
   since changing inputs recalculates historical results.
8. For live notifications, create a strategy order-fill alert. Alerts retain
   a snapshot of the script/settings, so delete and recreate them after changes.

The embedded chart in the app displays prices. It cannot accept a custom Pine
script or display this companion's trade markers. Use the full TradingView
chart for those. Some symbols may be restricted in embedded widgets; the full
chart link is always available.

Pine strategy fills are simulations, not broker orders or TradingView Paper
Trading account orders. This change does not implement a webhook receiver,
automatic broker execution, or synchronization of TradingView trades back
to the app journal. The Python engine and Pine companion use different
indicator initialization and simulation models; their results are not equal.
Pine must be compiled in TradingView's editor before relying on it; the local
tests verify configuration/export generation, not TradingView compilation.

## Connect a Deriv demo account without MT5

Deriv's TradingView integration supports Deriv **cTrader** accounts, including
demo accounts. It does not connect an existing MT5 account.

Open your Deriv dashboard → CFDs → TradingView → Connect to TradingView →
Go to TradingView. Sign into TradingView, connect, review the permission
screen and approve it yourself. Use the demo account for testing. Broker
positions and history appear in TradingView's Trading Panel after connection.
Connecting a broker does not turn the Pine strategy into automatic execution.

References:

- [Official Deriv connection guide](https://traders-academy.deriv.com/trading-guides/how-to-connect-your-deriv-account-to-tradingview)
- [V75 1s instrument](https://www.tradingview.com/symbols/DERIV-VOLATILITY_75_1S_INDEX/)
- [TradingView strategy simulation](https://www.tradingview.com/pine-script-docs/concepts/strategies/)
- [Strategy alert settings](https://www.tradingview.com/support/solutions/43000481368-strategy-alerts/)

The code must be redeployed to update an existing Vercel URL. Local edits do
not update the published site by themselves.
