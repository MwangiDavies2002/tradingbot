import { useEffect, useState } from 'react'
import { api, fetchPaperTrades, type PaperTrade } from '../api/client'
import { usePermissions } from '../auth/identity'
import PaperEvidence from '../components/PaperEvidence'

const input = 'block w-full mt-1 rounded bg-slate-900 border border-slate-600 p-2'

export default function PaperTrades() {
  const { canRunResearch } = usePermissions()
  const [trades, setTrades] = useState<PaperTrade[]>([])
  const [analytics, setAnalytics] = useState<any>(null)
  const [form, setForm] = useState({ symbol: '', timeframe: 'M5', direction: 'buy', entry_price: '', stop_loss: '', take_profit: '', quantity: '1', score: '0', regime: 'unknown', reason: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const load = () => Promise.all([fetchPaperTrades(), api.get('/api/paper-trades/analytics')]).then(([result, report]) => { setTrades(result.trades); setAnalytics(report) }).catch(err => setError(String(err)))
  useEffect(() => { void load() }, [])
  const update = (key: string, value: string) => setForm(previous => ({ ...previous, [key]: value }))
  async function create() {
    setBusy(true); setError('')
    try {
      await api.post('/api/paper-trades', { ...form, entry_price: Number(form.entry_price), stop_loss: Number(form.stop_loss), take_profit: Number(form.take_profit), quantity: Number(form.quantity), score: Number(form.score) })
      setForm(previous => ({ ...previous, entry_price: '', stop_loss: '', take_profit: '', reason: '' })); await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) } finally { setBusy(false) }
  }
  async function close(trade: PaperTrade) {
    const value = window.prompt(`Exit price for ${trade.symbol}`)
    if (!value) return
    try { await api.post(`/api/paper-trades/${trade.id}/close`, { exit_price: Number(value) }); await load() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }
  async function approval(trade: PaperTrade, action: 'request-approval' | 'approve' | 'reject') {
    try { await api.post(`/api/paper-trades/${trade.id}/${action}`, {}); await load() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }
  return <div className="p-4 md:p-6 space-y-6 max-w-6xl mx-auto">
    <header><h1 className="text-2xl font-bold">Paper trade ledger</h1><p className="text-slate-400 mt-2">Record hypothetical entries and exits before enabling broader execution. This page never submits broker orders.</p></header>
    <PaperEvidence />
    <section className="bg-slate-800 rounded-xl p-5 space-y-4">
      <h2 className="font-semibold">Record hypothetical entry</h2>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <label>Symbol<input className={input} value={form.symbol} disabled={!canRunResearch || busy} onChange={e => update('symbol', e.target.value)} /></label>
        <label>Timeframe<select className={input} value={form.timeframe} disabled={!canRunResearch || busy} onChange={e => update('timeframe', e.target.value)}><option>M1</option><option>M5</option><option>M15</option><option>H1</option></select></label>
        <label>Direction<select className={input} value={form.direction} disabled={!canRunResearch || busy} onChange={e => update('direction', e.target.value)}><option value="buy">Buy</option><option value="sell">Sell</option></select></label>
        <label>Quantity<input className={input} type="number" min="0.0001" step="any" value={form.quantity} disabled={!canRunResearch || busy} onChange={e => update('quantity', e.target.value)} /></label>
        <label>Entry price<input className={input} type="number" min="0" step="any" value={form.entry_price} disabled={!canRunResearch || busy} onChange={e => update('entry_price', e.target.value)} /></label>
        <label>Stop loss<input className={input} type="number" min="0" step="any" value={form.stop_loss} disabled={!canRunResearch || busy} onChange={e => update('stop_loss', e.target.value)} /></label>
        <label>Take profit<input className={input} type="number" min="0" step="any" value={form.take_profit} disabled={!canRunResearch || busy} onChange={e => update('take_profit', e.target.value)} /></label>
        <label>Score<input className={input} type="number" min="0" max="100" value={form.score} disabled={!canRunResearch || busy} onChange={e => update('score', e.target.value)} /></label>
        <label>Regime<input className={input} value={form.regime} disabled={!canRunResearch || busy} onChange={e => update('regime', e.target.value)} /></label>
        <label className="sm:col-span-2">Reason<input className={input} value={form.reason} disabled={!canRunResearch || busy} onChange={e => update('reason', e.target.value)} /></label>
      </div>
      <button type="button" disabled={!canRunResearch || busy || !form.symbol || !form.entry_price || !form.stop_loss || !form.take_profit} onClick={() => void create()} className="px-4 py-2 rounded bg-cyan-700 disabled:opacity-40">Record paper trade</button>
      {!canRunResearch && <p className="text-sm text-slate-400">Viewer access is read-only.</p>}
      {error && <p role="alert" className="text-red-300">{error}</p>}
    </section>
    {analytics&&<section className="bg-slate-800 rounded-xl p-5 space-y-4"><div className="flex flex-wrap justify-between gap-3"><h2 className="font-semibold">Paper performance analytics</h2><span className="text-xs text-amber-200">{analytics.sample_status === 'insufficient_sample' ? 'Fewer than 300 closed trades: exploratory only' : 'Reviewable sample'}</span></div><div className="grid grid-cols-2 md:grid-cols-4 gap-3"><div><span className="text-xs text-slate-400">Closed trades</span><strong className="block text-xl">{analytics.overall.trades}</strong></div><div><span className="text-xs text-slate-400">Win rate</span><strong className="block text-xl">{analytics.overall.win_rate == null ? 'N/A' : `${(analytics.overall.win_rate * 100).toFixed(1)}%`}</strong></div><div><span className="text-xs text-slate-400">P&amp;L</span><strong className="block text-xl">{analytics.overall.total_pnl.toFixed(2)}</strong></div><div><span className="text-xs text-slate-400">Profit factor</span><strong className="block text-xl">{analytics.overall.profit_factor?.toFixed(2) ?? 'N/A'}</strong></div></div><p className="text-sm text-slate-400">Breakdowns are available in the API report by symbol, regime and score bucket. Session analytics: {analytics.session.status}.</p></section>}
    <section className="bg-slate-800 rounded-xl p-5 overflow-x-auto"><h2 className="font-semibold mb-3">Recorded trades</h2><table className="w-full min-w-[1100px] text-sm"><thead><tr className="text-left text-slate-500"><th className="p-2">Market</th><th>Direction</th><th>Entry</th><th>Stop / target</th><th>Regime</th><th>Status</th><th>Approval</th><th>P&amp;L</th><th /></tr></thead><tbody>{trades.map(trade => <tr key={trade.id} className="border-t border-slate-700"><td className="p-2">{trade.symbol} <span className="text-xs text-slate-500">{trade.timeframe}</span></td><td>{trade.direction}</td><td>{trade.entry_price}</td><td>{trade.stop_loss} / {trade.take_profit}</td><td>{trade.regime}</td><td>{trade.status}</td><td>{trade.approval_status}</td><td>{trade.pnl?.toFixed(2) ?? 'N/A'}</td><td className="space-x-2">{trade.status === 'open' && canRunResearch && trade.approval_status === 'not_requested' && <button type="button" className="text-cyan-300 underline" onClick={() => void approval(trade, 'request-approval')}>Request</button>}{trade.status === 'open' && canRunResearch && trade.approval_status === 'pending' && <><button type="button" className="text-emerald-300 underline" onClick={() => void approval(trade, 'approve')}>Approve</button><button type="button" className="text-amber-300 underline" onClick={() => void approval(trade, 'reject')}>Reject</button></>}{trade.status === 'open' && canRunResearch && <button type="button" className="text-slate-300 underline" onClick={() => void close(trade)}>Close</button>}</td></tr>)}</tbody></table>{!trades.length&&<p className="text-slate-500 py-4">No paper trades recorded yet.</p>}</section>
  </div>
}
