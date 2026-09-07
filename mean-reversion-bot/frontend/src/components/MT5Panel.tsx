import { useEffect, useState } from 'react'
import { api } from '../api/client'

type Selection = { timeframe: string; min_confluence: number; [key: string]: string | number | boolean }
type Props = { selection?: Selection; onLoad?: (config: any) => void }

export default function MT5Panel({ selection, onLoad }: Props) {
  const [status, setStatus] = useState<any>(null)
  const [journal, setJournal] = useState<any[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [risk, setRisk] = useState(0.5)
  const [lossLimit, setLossLimit] = useState(3)
  const refresh = async () => {
    const [state, rows] = await Promise.all([api.get('/api/mt5/status'), api.get('/api/mt5/journal')])
    setStatus(state); setJournal(rows as any[])
    return state as any
  }
  useEffect(() => {
    let active = true
    const poll = async () => {
      try { if (active) await refresh() } catch (e) { if (active) setError(String(e)) }
    }
    poll()
    const timer = setInterval(poll, 5000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  const action = async (name: string) => {
    setBusy(true); setError('')
    try {
      if (name === 'save') {
        await api.put('/api/mt5/strategy', { ...selection, risk_pct: risk / 100, daily_loss_pct: lossLimit / 100 })
      } else {
        await api.post(`/api/mt5/${name}`, {})
      }
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const saved = status?.config
  const dirty = !!selection && (!saved || Object.entries(selection).some(([key, value]) => saved[key] !== value)
    || saved.risk_pct !== risk / 100 || saved.daily_loss_pct !== lossLimit / 100)
  const button = 'px-3 py-2 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-sm'
  return <section className="bg-slate-800 border border-cyan-800 rounded-xl p-5 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="font-bold text-lg text-white">MT5 demo · Volatility 75 (1s) only</h2>
        <p className="text-sm text-slate-400">{status?.running ? 'Running' : 'Stopped'} · {status?.connected ? `Account ${status.account} · ${status.server}` : 'Terminal not connected'}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={busy || status?.running} onClick={() => action('connect')}>Connect MT5 demo</button>
        {selection && <button className={button} disabled={busy || status?.running} onClick={() => action('save')}>Save lab selection</button>}
        <button className={`${button} text-green-300`} disabled={busy || !status?.connected || status?.running || dirty} onClick={() => action('start')}>Start demo</button>
        <button className={`${button} text-red-300`} disabled={busy || !status?.running} onClick={() => action('stop')}>Stop entries</button>
      </div>
    </div>
    <p className="text-sm text-cyan-200" role="status">{status?.message || 'Loading local MT5 service…'}</p>
    {error && <p className="text-sm text-red-300" role="alert">{error}</p>}
    {selection && <>
      <div className="flex flex-wrap gap-5 items-end text-sm">
        <label>Risk per trade (%)<input type="number" min="0.01" max="1" step="0.1" value={risk} onChange={e => setRisk(Number(e.target.value))} className="block bg-slate-900 p-2 rounded w-28" /></label>
        <label>Daily equity loss limit (%)<input type="number" min="0.1" max="5" step="0.5" value={lossLimit} onChange={e => setLossLimit(Number(e.target.value))} className="block bg-slate-900 p-2 rounded w-28" /></label>
        <button className={button} disabled={!saved || busy} onClick={() => { onLoad?.(saved); setRisk(saved.risk_pct * 100); setLossLimit(saved.daily_loss_pct * 100) }}>Load saved selection</button>
        {dirty && <span className="text-amber-300">Save these changes before starting.</span>}
      </div>
      <p className="text-xs text-slate-400">The lab uses a weighted confluence score: 6 points does not mean six indicators all agree. Saved toggles and the threshold are used by the same signal engine for backtests and demo entries. MT5 uses tick volume and broker lot sizing.</p>
    </>}
    {saved && <p className="text-xs text-slate-400">Saved: {saved.timeframe} · minimum {saved.min_confluence} points · risk {saved.risk_pct * 100}% · daily limit {saved.daily_loss_pct * 100}% · {Object.entries(saved).filter(([key, value]) => key.startsWith('use_') && value).map(([key]) => key.slice(4).toUpperCase()).join(', ')}</p>}
    <p className="text-xs text-slate-400">Log into your Deriv demo account in MT5, enable Algo Trading, and allow external Python trading under Options → Expert Advisors. Keep this backend and MT5 running on this PC. Stop entries leaves existing broker SL/TP orders active.</p>
    <div className="flex flex-wrap gap-6 text-sm">
      <span>Balance: {status?.balance?.toFixed(2) ?? '—'}</span>
      <span>Equity: {status?.equity?.toFixed(2) ?? '—'}</span>
      <span>Open positions: {status?.open_positions?.length ?? 0}</span>
      <span>Last poll: {status?.last_poll ? new Date(status.last_poll).toLocaleTimeString() : '—'}</span>
    </div>
    {status?.open_positions?.length > 0 && <div className="overflow-x-auto"><table className="w-full text-sm text-left">
      <thead><tr><th>Ticket</th><th>Side</th><th>Lots</th><th>Entry</th><th>SL / TP</th><th>Floating P&amp;L</th></tr></thead>
      <tbody>{status.open_positions.map((p: any) => <tr key={p.ticket}><td>{p.ticket}</td><td>{p.type === 0 ? 'Buy' : 'Sell'}</td><td>{p.volume}</td><td>{p.price_open}</td><td>{p.sl} / {p.tp}</td><td>{p.profit}</td></tr>)}</tbody>
    </table></div>}
    <details>
      <summary className="cursor-pointer font-semibold">Trade journal · latest {journal.length} events</summary>
      <a className="inline-block text-sm text-cyan-300 my-3" href={`${(import.meta as any).env?.VITE_API_URL ?? ''}/api/mt5/journal.csv`}>Download complete journal CSV</a>
      <p className="text-xs text-slate-400 mb-3">Includes signals, strategy snapshots, order requests, broker responses and entry/exit deals. Net deal P&amp;L includes commission, swap and fees. Exits while offline are recovered on reconnect.</p>
      <div className="max-h-96 overflow-auto"><table className="w-full text-xs text-left">
        <thead><tr><th className="p-2">Time</th><th>Event</th><th>Ticket / side</th><th>Lots / price</th><th>Net P&amp;L</th><th>Details</th></tr></thead>
        <tbody>{journal.map(row => <tr key={row.id} className="border-t border-slate-700">
          <td className="p-2 whitespace-nowrap">{new Date(row.ts).toLocaleString()}</td><td>{row.kind}{row.kind === 'deal' ? (row.data.entry === 0 ? ' · entry' : ' · exit') : ''}</td>
          <td>{row.data.ticket ?? row.data.order ?? '—'} {row.data.direction ?? (row.kind === 'deal' ? row.data.type === 0 ? 'Buy' : 'Sell' : '')}</td>
          <td>{row.data.volume ?? '—'} / {row.data.price ?? '—'}</td>
          <td>{row.kind === 'deal' ? (row.data.profit + row.data.commission + row.data.swap + row.data.fee).toFixed(2) : '—'}</td>
          <td><details><summary className="cursor-pointer">{row.data.reason ?? row.data.comment ?? 'View'}</summary><pre className="whitespace-pre-wrap max-w-lg">{JSON.stringify(row.data, null, 2)}</pre></details></td>
        </tr>)}</tbody>
      </table>{journal.length === 0 && <p className="py-4 text-slate-400">No recorded events yet. Connect MT5 and start a demo session.</p>}</div>
    </details>
  </section>
}
