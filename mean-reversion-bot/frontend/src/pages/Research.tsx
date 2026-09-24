import { useState } from 'react'
import { api } from '../api/client'

const SYMBOLS = ['R_75', '1HZ75V', '1HZ100V', '1HZ50V', 'BOOM500', 'CRASH500', 'UK100', 'NAS100', 'SP500', 'GER40', 'FRA40', 'XAUUSD']

export default function Research() {
  const [csv, setCsv] = useState('')
  const [symbol, setSymbol] = useState('R_75')
  const [timeframe, setTimeframe] = useState('M5')
  const [balance, setBalance] = useState(1000)
  const [threshold, setThreshold] = useState(6)
  const [spread, setSpread] = useState(0)
  const [slippage, setSlippage] = useState(.0005)
  const [commission, setCommission] = useState(0)
  const [report, setReport] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const input = 'block w-full mt-1 rounded bg-slate-900 border border-slate-600 p-2'
  async function run() {
    setBusy(true); setError(''); setReport(null)
    try {
      setReport(await api.post('/api/backtest/research', {
        symbols: [symbol], timeframe, initial_balance: balance,
        min_confluence: threshold, csv_data: csv,
        spread_price: spread, slippage_pct: slippage, commission,
      }))
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = 'research-report.json'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <div className="p-6 max-w-5xl space-y-6">
    <header><h1 className="text-2xl font-bold">Research validation</h1>
      <p className="text-slate-400 mt-2">Test the baseline mean-reversion strategy on chronological holdouts. Threshold selection uses training data only.</p></header>
    <section className="bg-slate-800 rounded-xl p-5 space-y-4">
      <p className="text-sm text-amber-200">Multiplier simulation only. OHLC data cannot reproduce tick execution or MT5 CFD costs. A passing report does not enable live trading.</p>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
        <label>Instrument<select className={input} value={symbol} onChange={e => setSymbol(e.target.value)}>{SYMBOLS.map(option => <option key={option} value={option}>{option}</option>)}</select></label>
        <label>Timeframe<select className={input} value={timeframe} onChange={e => setTimeframe(e.target.value)}><option>M1</option><option>M5</option><option>M15</option><option>H1</option></select></label>
        <label>Starting balance (USD)<input type="number" min="1" className={input} value={balance} onChange={e => setBalance(Number(e.target.value))} /></label>
        <label>Confluence threshold<input type="number" min="1" max="20" className={input} value={threshold} onChange={e => setThreshold(Number(e.target.value))} /></label>
        <label>Full spread (price units)<input type="number" min="0" step="0.01" className={input} value={spread} onChange={e => setSpread(Number(e.target.value))} /></label>
        <label>Slippage (fraction)<input type="number" min="0" max="0.05" step="0.0001" className={input} value={slippage} onChange={e => setSlippage(Number(e.target.value))} /></label>
        <label>Round-trip commission (USD)<input type="number" min="0" step="0.01" className={input} value={commission} onChange={e => setCommission(Number(e.target.value))} /></label>
      </div>
      <label className="block text-sm">Historical OHLCV CSV (up to 10,000 rows)<input type="file" accept=".csv" className="block mt-2" onChange={async e => { const file = e.target.files?.[0]; if (file) setCsv(await file.text()) }} /></label>
      <button disabled={busy || !csv || !symbol} onClick={run} className="px-4 py-2 rounded bg-cyan-700 disabled:opacity-40">{busy ? 'Running research…' : 'Run validation'}</button>
      {error && <p role="alert" className="text-red-300">{error}</p>}
    </section>
    {report && <section className="bg-slate-800 rounded-xl p-5 space-y-4">
      <h2 className="font-bold text-xl">{report.research_gate_passed ? 'Research checks passed' : 'More evidence needed'}</h2>
      <p>{report.oos_trade_count} out-of-sample trades · combined fold P&amp;L: ${report.oos_pnl.toFixed(2)}</p>
      <ul className="space-y-2">{Object.entries(report.checks).map(([name, pass]) => <li key={name} className={pass ? 'text-emerald-300' : 'text-amber-300'}>{pass ? 'Pass' : 'Not met'} — {name.replace(/_/g, ' ')}</li>)}</ul>
      <p className="text-sm text-slate-400">{report.note}</p>
      <button onClick={download} className="px-4 py-2 rounded bg-slate-700">Download full report</button>
    </section>}
  </div>
}
