import { useEffect, useRef, useState } from 'react'
import { buildPineStrategy, selectionError, TV_SYMBOL, TV_URL, type Selection } from '../tradingview/strategy'

export default function TradingViewPanel({ selection, threshold, timeframe }: { selection: Selection; threshold: number; timeframe: string }) {
  const chart = useRef<HTMLDivElement>(null)
  const [message, setMessage] = useState('')
  const [scriptError, setScriptError] = useState(false)
  const error = selectionError(selection, threshold)
  const source = error ? '' : buildPineStrategy(selection, threshold)
  useEffect(() => {
    const container = chart.current
    if (!container) return
    setScriptError(false)
    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'
    widget.style.height = '100%'
    container.replaceChildren(widget)
    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.async = true
    script.textContent = JSON.stringify({ autosize: true, symbol: TV_SYMBOL,
      interval: String(Number(timeframe.slice(1)) * (timeframe.startsWith('H') ? 60 : 1)),
      timezone: 'Etc/UTC', theme: 'dark', style: '1', locale: 'en',
      allow_symbol_change: false, hide_side_toolbar: false, calendar: false, support_host: 'https://www.tradingview.com' })
    script.onerror = () => setScriptError(true)
    container.appendChild(script)
    return () => { script.onerror = null; container.replaceChildren() }
  }, [timeframe])
  const download = () => {
    const url = URL.createObjectURL(new Blob([source], { type: 'text/plain;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url; link.download = 'v751s-dynamic-confluence.pine'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setMessage('Downloaded. Paste the script into TradingView Pine Editor and choose Add to chart.')
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(source); setMessage('Copied. Paste into Pine Editor → Add to chart.') }
    catch { setMessage('Clipboard unavailable. Use Download Pine strategy or copy from the source below.') }
  }
  return <section className="bg-slate-800 border border-cyan-800 rounded-xl p-5 space-y-4">
    <div className="flex flex-wrap justify-between gap-3">
      <div><h2 className="text-lg font-bold">TradingView · V75 1s</h2>
        <p className="text-sm text-slate-400">Selected threshold: {threshold} points · change it whenever you want.</p></div>
      <a href={TV_URL} target="_blank" rel="noopener noreferrer" className="rounded bg-cyan-500 px-4 py-2 text-slate-950 font-semibold">Open V75 1s in TradingView ↗</a>
    </div>
    <div ref={chart} className="tradingview-widget-container h-[460px] w-full" />
    <p className="text-xs text-slate-400"><a href={TV_URL} target="_blank" rel="noopener noreferrer" className="text-cyan-300">V75 1s chart by TradingView</a>. This embedded chart shows market prices. Your Pine strategy's trade markers appear on the full TradingView chart after you add the script.</p>
    {scriptError && <p role="alert" className="text-amber-300">The chart could not load. Open the full TradingView chart using the link above.</p>}
    <p className="text-xs text-slate-400">If TradingView restricts this symbol in embedded charts, use Open V75 1s. No MT5 connection is needed for this workflow.</p>
    <div className="flex flex-wrap gap-3">
      <button disabled={!!error} onClick={download} className="px-4 py-2 bg-cyan-600 rounded disabled:opacity-40">Download Pine strategy</button>
      <button disabled={!!error} onClick={copy} className="px-4 py-2 bg-slate-700 rounded disabled:opacity-40">Copy Pine strategy</button>
      <a href="https://home.deriv.com/" target="_blank" rel="noopener noreferrer" className="px-4 py-2 border border-slate-600 rounded">Open Deriv to connect a demo account ↗</a>
    </div>
    {error && <p role="alert" className="text-amber-300">{error}</p>}
    {message && <p role="status" className="text-cyan-300">{message}</p>}
    <ol className="list-decimal pl-5 text-sm text-slate-300 space-y-2">
      <li>Select your indicators and a threshold below (1, 2, 3, or any achievable score). Your selection is saved in this browser.</li>
      <li>Copy the script, open the V75 1s chart, then use <strong>Pine Editor → paste → Save → Add to chart</strong>. Choose your timeframe on that chart.</li>
      <li>Watch simulated entries/exits on the chart and inspect <strong>Strategy Tester → List of trades</strong>. Export the trade list there to keep your records.</li>
      <li>Tomorrow, change <strong>strategy Settings → Inputs → Minimum weighted score</strong>. Changing lab settings does not update an already-installed Pine script; copy it again or change its inputs.</li>
      <li>Export today's trade list before changing inputs: TradingView recalculates historical strategy results using the new settings.</li>
      <li>For notifications, create an alert on the strategy's order fills. Recreate the alert after changing settings.</li>
    </ol>
    <p className="text-sm text-amber-200">Pine strategies simulate orders; they do not automatically trade a connected broker or the TradingView Paper Trading account. This app does not receive TradingView fills or alerts yet.</p>
    <p className="text-sm text-slate-400">For broker trading in TradingView, go to Deriv → CFDs → TradingView → Connect to TradingView. Use a demo account. Deriv routes this connection through cTrader, not MT5. <a className="text-cyan-300" href="https://traders-academy.deriv.com/trading-guides/how-to-connect-your-deriv-account-to-tradingview" target="_blank" rel="noopener noreferrer">Official connection guide ↗</a></p>
    <details><summary className="cursor-pointer text-sm">Pine source and calculation scope</summary>
      <p className="text-xs text-slate-400 my-3">This companion supports Z-Score, RSI, Bollinger Bands, VWAP, Stochastic and volume. LSL, SMC and Hurst remain Python-only. Pine's indicator initialization and broker emulator differ from the Python backtester; results are not interchangeable. Quantity is simulated units, not MT5 lots. Set commission and slippage in Strategy Properties.</p>
      <pre className="max-h-80 overflow-auto text-xs bg-slate-950 p-3 rounded">{source || error}</pre>
    </details>
  </section>
}
