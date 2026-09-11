export const TV_SYMBOLS: Record<string, string> = { '1HZ75V': 'DERIV:VOLATILITY_75_1S_INDEX', '1HZ100V': 'DERIV:VOLATILITY_100_1S_INDEX', '1HZ50V': 'DERIV:VOLATILITY_50_1S_INDEX', BOOM500: 'DERIV:BOOM_500_INDEX', CRASH500: 'DERIV:CRASH_500_INDEX', GER40: 'TVC:DE40', FRA40: 'TVC:CAC40' }
export const tradingViewSymbol = (symbol: string) => TV_SYMBOLS[symbol] || `DERIV:${symbol}`
export const tradingViewUrl = (symbol = '1HZ75V') => `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tradingViewSymbol(symbol))}`
export const TV_SYMBOL = tradingViewSymbol('1HZ75V')
export const TV_URL = tradingViewUrl()
export const TV_SUPPORTED = ['use_zscore', 'use_rsi', 'use_bb', 'use_vwap', 'use_stoch', 'use_volume']
export type Selection = Record<string, boolean>
export const DEFAULT_SELECTION: Selection = {
  use_zscore: true, use_rsi: true, use_bb: true, use_vwap: false,
  use_stoch: false, use_volume: false, use_lsl: false, use_smc: false, use_hurst: false,
}
export const WEIGHTS: Record<string, number> = { use_zscore: 3, use_rsi: 2, use_bb: 1, use_vwap: 1, use_stoch: 1, use_volume: 1 }

export function selectionError(selection: Selection, threshold: number): string | null {
  if (!Object.values(selection).some(Boolean)) return 'Select at least one strategy.'
  const maximum = Object.entries(selection).reduce((sum, [key, enabled]) => sum + (enabled ? (WEIGHTS[key] || 1) : 0), 0)
  if (!Number.isInteger(threshold) || threshold < 1 || threshold > maximum) return `Choose a threshold from 1 to ${maximum} for this selection.`
  return null
}

export function buildPineStrategy(selection: Selection, threshold: number, symbol = '1HZ75V', startingCapital = 10000): string {
  const error = selectionError(selection, threshold)
  if (error) throw new Error(error)
  const flag = (key: string) => selection[key] ? 'true' : 'false'
  return `//@version=6
// Strategy Lab TradingView companion: simulated orders, never broker execution.
// Uses Pine's indicator calculations. Python-only selections are translated to a documented
// conservative proxy, not a byte-for-byte execution-equivalent port.
// Recreate TradingView alerts after changing any inputs; alerts retain old settings.
strategy("Dynamic Confluence Lab - ${symbol}", overlay=true, pyramiding=0, initial_capital=${startingCapital}, default_qty_type=strategy.fixed, default_qty_value=1, calc_on_every_tick=false, process_orders_on_close=false, commission_type=strategy.commission.percent, commission_value=0.02, slippage=2)

threshold = input.int(${threshold}, "Minimum weighted score", minval=1, maxval=20, group="Confluence")
useZ = input.bool(${flag('use_zscore')}, "Z-Score (2 points; 3 if extreme)", group="Indicators")
useRsi = input.bool(${flag('use_rsi')}, "RSI (2 points)", group="Indicators")
useBb = input.bool(${flag('use_bb')}, "Bollinger Bands (1 point)", group="Indicators")
useVwap = input.bool(${flag('use_vwap')}, "UTC daily VWAP (1 point; requires volume)", group="Indicators")
useStoch = input.bool(${flag('use_stoch')}, "Stochastic (1 point)", group="Indicators")
useVol = input.bool(${flag('use_volume')}, "Volume spike (1 context point)", group="Indicators")
useLsl = input.bool(${flag('use_lsl')}, "Liquidity sweep", group="Python translations")
useSmc = input.bool(${flag('use_smc')}, "Structure break", group="Python translations")
useHurst = input.bool(${flag('use_hurst')}, "Hurst mean-reversion regime", group="Python translations")
useLinReg = input.bool(${flag('use_linear_regression')}, "Linear regression", group="Python translations")
useDay = input.bool(${flag('use_day_levels')}, "Previous-day levels", group="Python translations")
useRev = input.bool(${flag('use_candle_reversal')}, "Candle reversal", group="Python translations")
useCont = input.bool(${flag('use_candle_continuation')}, "Candle continuation", group="Python translations")
useCrt = input.bool(${flag('use_crt')}, "Candle range theory", group="Python translations")
useTree = input.bool(${flag('use_tree_model')}, "Fixed decision tree", group="Python translations")
useSmt = input.bool(${flag('use_smt')}, "SMT divergence", group="Cross-market")
smtSymbol = input.symbol("TVC:SPX", "Comparison symbol", group="Cross-market")
smtLookback = input.int(20, "SMT lookback", minval=5, maxval=100, group="Cross-market")
quantity = input.float(1, "Simulated quantity (units, not MT5 lots)", minval=0.001, group="Simulation")
slMult = input.float(1.5, "Stop distance in ATR", minval=0.1, group="Simulation")
rr = input.float(2, "Target / stop ratio", minval=0.1, group="Simulation")
minDirectional = input.int(2, "Minimum directional points", minval=1, maxval=10, group="Filters")
cooldownBars = input.int(10, "Cooldown bars after entry", minval=0, maxval=200, group="Filters")
trendAtrLimit = input.float(3.0, "Trend distance limit (ATR)", minval=0.5, step=0.5, group="Filters")

maxScore = (useZ ? 3 : 0) + (useRsi ? 2 : 0) + (useBb ? 1 : 0) + (useVwap ? 1 : 0) + (useStoch ? 1 : 0) + (useVol ? 1 : 0)
maxScore += (useLsl ? 2 : 0) + (useSmc ? 1 : 0) + (useHurst ? 1 : 0) + (useLinReg ? 1 : 0) + (useDay ? 1 : 0) + (useRev ? 1 : 0) + (useCont ? 1 : 0) + (useCrt ? 1 : 0)
maxScore += useTree ? 3 : 0
maxScore += useSmt ? 2 : 0
// Translated Python detectors use a bounded RSI proxy. Clamp an imported lab
// threshold so the script remains executable when the two score systems differ.
effectiveThreshold = math.max(1, math.min(threshold, maxScore))

basis = ta.sma(close, 20)
sd = ta.stdev(close, 20)
z = sd > 0 ? (close - basis) / sd : 0.0
rsi = ta.rsi(close, 14)
atr = ta.atr(14)
ema50 = ta.ema(close, 50)
ema200 = ta.ema(close, 200)
trendDistance = atr > 0 ? math.abs(ema50 - ema200) / atr : 999.0
treeBuy = useTree and z <= -1.5 and rsi <= 35 and close < ema50 and trendDistance <= 3.0
treeSell = useTree and z >= 1.5 and rsi >= 65 and close > ema50 and trendDistance <= 3.0
smtClose = request.security(smtSymbol, timeframe.period, close, barmerge.gaps_off, barmerge.lookahead_off)
smtBase = smtClose[smtLookback]
mainBase = close[smtLookback]
mainReturn = mainBase != 0 ? (close - mainBase) / mainBase : 0.0
smtReturn = smtBase != 0 ? (smtClose - smtBase) / smtBase : 0.0
smtBull = useSmt and not na(smtClose) and low < ta.lowest(low, smtLookback)[1] and smtReturn > mainReturn
smtBear = useSmt and not na(smtClose) and high > ta.highest(high, smtLookback)[1] and smtReturn < mainReturn

// Deterministic Pine counterparts for the Python detectors.
priorHigh = ta.highest(high, 20)[1]
priorLow = ta.lowest(low, 20)[1]
lslBuy = low < priorLow and close > priorLow
lslSell = high > priorHigh and close < priorHigh
structureUp = close > ta.highest(high, 10)[1]
structureDown = close < ta.lowest(low, 10)[1]
priceRange = ta.highest(high, 50) - ta.lowest(low, 50)
hurstProxy = priceRange > 0 ? math.log(math.max(ta.stdev(close, 20), syminfo.mintick) / priceRange) / math.log(20) + 0.5 : 0.5
meanReverting = hurstProxy < 0.5
regNow = ta.linreg(close, 50, 0)
regPrev = ta.linreg(close, 50, 1)
regUp = regNow > regPrev
regDown = regNow < regPrev
prevDayHigh = request.security(syminfo.tickerid, "D", high[1])
prevDayLow = request.security(syminfo.tickerid, "D", low[1])
dayBuy = low <= prevDayLow and close > prevDayLow
daySell = high >= prevDayHigh and close < prevDayHigh
bullReversal = close > open and close[1] < open[1] and close >= open[1] and open <= close[1]
bearReversal = close < open and close[1] > open[1] and close <= open[1] and open >= close[1]
bullContinuation = close > high[1] and close > open
bearContinuation = close < low[1] and close < open
rangeMid = (high[1] + low[1]) / 2
crtBuy = low < low[1] and close > rangeMid
crtSell = high > high[1] and close < rangeMid
upper = basis + 2 * sd
lower = basis - 2 * sd
k = ta.sma(ta.stoch(close, high, low, 14), 3)
utcDay = time("1D", "0000-0000", "UTC")
newDay = ta.change(utcDay) != 0
vwap = ta.vwap(hlc3, newDay or barstate.isfirst)
vwapDev = atr > 0 ? (close - vwap) / atr : na
averageVolume = ta.sma(volume, 20)
volumePoint = useVol and not na(volume) and averageVolume > 0 and volume >= 1.5 * averageVolume ? 1 : 0

buyDirectional = (useZ and z <= -2 ? (z <= -3 ? 3 : 2) : 0) + (useRsi and rsi < 25 ? 2 : 0) + (useBb and close < lower ? 1 : 0) + (useVwap and vwapDev <= -1.5 ? 1 : 0) + (useStoch and k < 15 ? 1 : 0) + (useLsl and lslBuy ? 2 : 0) + (useSmc and structureUp ? 1 : 0) + (useHurst and meanReverting ? 1 : 0) + (useLinReg and regUp ? 1 : 0) + (useDay and dayBuy ? 1 : 0) + (useRev and bullReversal ? 1 : 0) + (useCont and bullContinuation ? 1 : 0) + (useCrt and crtBuy ? 1 : 0)
sellDirectional = (useZ and z >= 2 ? (z >= 3 ? 3 : 2) : 0) + (useRsi and rsi > 75 ? 2 : 0) + (useBb and close > upper ? 1 : 0) + (useVwap and vwapDev >= 1.5 ? 1 : 0) + (useStoch and k > 85 ? 1 : 0) + (useLsl and lslSell ? 2 : 0) + (useSmc and structureDown ? 1 : 0) + (useHurst and meanReverting ? 1 : 0) + (useLinReg and regDown ? 1 : 0) + (useDay and daySell ? 1 : 0) + (useRev and bearReversal ? 1 : 0) + (useCont and bearContinuation ? 1 : 0) + (useCrt and crtSell ? 1 : 0)
buyDirectional += useTree and treeBuy ? 3 : 0
sellDirectional += useTree and treeSell ? 3 : 0
buyDirectional += smtBull ? 2 : 0
sellDirectional += smtBear ? 2 : 0
buyScore = buyDirectional + volumePoint
sellScore = sellDirectional + volumePoint
var int lastEntryBar = na
cooldownReady = na(lastEntryBar) or bar_index - lastEntryBar >= cooldownBars
// Avoid fading an unusually strong directional regime and reject weak one-point setups.
ready = barstate.isconfirmed and bar_index >= 200 and atr > 0 and trendDistance <= trendAtrLimit and cooldownReady
requiredScore = math.max(effectiveThreshold, minDirectional)
longSignal = ready and buyDirectional > sellDirectional and buyDirectional >= requiredScore and buyScore >= requiredScore
shortSignal = ready and sellDirectional > buyDirectional and sellDirectional >= requiredScore and sellScore >= requiredScore

// Stop/target ticks are fixed at the signal, relative to the emulator's actual entry fill.
if strategy.position_size == 0
    stopTicks = math.max(1, math.round(atr * slMult / syminfo.mintick))
    targetTicks = math.max(1, math.round(stopTicks * rr))
    if longSignal
        strategy.entry("Long", strategy.long, qty=quantity, alert_message="V751S simulated long entry")
        strategy.exit("Long exit", "Long", loss=stopTicks, profit=targetTicks, alert_message="V751S simulated long exit")
        lastEntryBar := bar_index
    else if shortSignal
        strategy.entry("Short", strategy.short, qty=quantity, alert_message="V751S simulated short entry")
        strategy.exit("Short exit", "Short", loss=stopTicks, profit=targetTicks, alert_message="V751S simulated short exit")
        lastEntryBar := bar_index

plot(useBb ? upper : na, "Upper BB", color=color.new(color.blue, 50))
plot(useBb ? lower : na, "Lower BB", color=color.new(color.blue, 50))
plot(useVwap ? vwap : na, "UTC VWAP", color=color.orange)
plot(buyScore, "Buy score", display=display.data_window)
plot(sellScore, "Sell score", display=display.data_window)
plot(effectiveThreshold, "Effective threshold", display=display.data_window)
plot(requiredScore, "Required directional score", display=display.data_window)
// Strategy Tester > List of trades contains all simulated entries and exits.
// Set realistic commission/slippage in Strategy Properties before interpreting P&L.
`
}
