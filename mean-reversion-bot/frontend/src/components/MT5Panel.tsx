import { useEffect, useState } from 'react'
import { api, downloadFile } from '../api/client'
import { usePermissions } from '../auth/identity'

type Selection = { timeframe: string; min_confluence: number; [key: string]: string | number | boolean }
type Props = { selection?: Selection; onLoad?: (config: any) => void; onSymbolChange?: (symbol: string) => void }

export default function MT5Panel({ selection, onLoad, onSymbolChange }: Props) {
  const { canRunResearch: canOperate } = usePermissions()
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
  const [status, setStatus] = useState<any>(null)
  const [preflight, setPreflight] = useState<any>(null)
  const [journal, setJournal] = useState<any[]>([])
  const [paperEvidence, setPaperEvidence] = useState<any>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [risk, setRisk] = useState(0.5)
  const [lossLimit, setLossLimit] = useState(3)
  const [symbol, setSymbol] = useState('')
  const [symbols, setSymbols] = useState<{ name: string; description: string; eligible: boolean; reason: string | null }[]>([])
  const [catalogRevision, setCatalogRevision] = useState(0)
  const [symbolSearch, setSymbolSearch] = useState('')
  const refresh = async () => {
    const [state, rows, paper, readiness] = await Promise.all([api.get('/api/mt5/status'), api.get('/api/mt5/journal'),
      api.get('/api/scanner/analytics').catch(() => null),
      api.get('/api/mt5/preflight').catch(e => ({ error: e instanceof Error ? e.message : String(e) }))])
    setStatus(state); setJournal(rows as any[]); setPaperEvidence(paper); setPreflight(readiness)
    return state as any
  }
  useEffect(() => {
    if (!local) return
    let active = true
    const poll = async () => {
      try { if (active) await refresh() } catch (e) { if (active) setError(String(e)) }
    }
    poll()
    const timer = setInterval(poll, 5000)
    return () => { active = false; clearInterval(timer) }
  }, [])
  useEffect(() => {
    if (status?.config?.symbol) setSymbol(previous => previous || status.config.symbol)
  }, [status?.config?.symbol])
  useEffect(() => { onSymbolChange?.(symbol) }, [symbol, onSymbolChange])
  useEffect(() => {
    let active = true
    setSymbols([])
    if (status?.connected) {
      api.get('/api/mt5/symbols').then((data: any) => {
        if (active) setSymbols(Array.isArray(data.symbols) ? data.symbols : [])
      }).catch(e => { if (active) setError(String(e)) })
    }
    return () => { active = false }
  }, [status?.connected, status?.account, status?.server, catalogRevision])
  useEffect(() => {
    if (!selection && status?.config) {
      setRisk(status.config.risk_pct * 100); setLossLimit(status.config.daily_loss_pct * 100)
    }
  }, [!!selection, status?.config?.risk_pct, status?.config?.daily_loss_pct])
  const action = async (name: string) => {
    setBusy(true); setError('')
    try {
      if (name === 'save') {
        await api.put('/api/mt5/strategy', { ...status?.config, ...selection, symbol, risk_pct: risk / 100, daily_loss_pct: lossLimit / 100 })
      } else {
        await api.post(`/api/mt5/${name}`, name === 'start' ? { symbol } : {})
      }
      if (name === 'connect') setCatalogRevision(value => value + 1)
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const saved = status?.config
  const demoSignal = saved?.symbol && status?.last_signal?.symbol === saved.symbol ? status.last_signal : null
  const candidate = status?.research_candidate
  const candidateScope = candidate?.snapshot ? `${candidate.snapshot.server}:${candidate.snapshot.account}` : ''
  const candidatePaper = (paperEvidence?.per_pair_policy || []).filter((row: any) =>
    row.research_run_id === candidate?.run_id && row.scope === candidateScope &&
    row.symbol === candidate?.strategy?.symbol && row.timeframe === candidate?.strategy?.timeframe)
  const eligible = symbols.some(row => row.name === symbol && row.eligible)
  const dirty = !saved || saved.symbol !== symbol || (!!selection && Object.entries(selection).some(([key, value]) => saved[key] !== value))
    || saved.risk_pct !== risk / 100 || saved.daily_loss_pct !== lossLimit / 100
  const button = 'px-3 py-2 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 disabled:cursor-not-allowed text-sm'
  if (!local) return <section className="p-5 rounded-xl bg-slate-800 border border-slate-700 space-y-3"><h2 className="font-bold">MT5 is available on your Windows PC</h2><p className="text-slate-300">This hosted site cannot connect to a desktop MT5 terminal. Use TradingView in Strategy Lab, or open the local app with the backend running.</p><a className="text-cyan-300" href="http://localhost:3000/backtest">Open local Strategy Lab ↗</a></section>
  return <section className="bg-slate-800 border border-cyan-800 rounded-xl p-5 space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h2 className="font-bold text-lg text-white">MT5 demo · {symbol || 'Choose a broker pair'}</h2>
        <p className="text-sm text-slate-400">{status?.running ? 'Running' : 'Stopped'} · {status?.connected ? `Account ${status.account} · ${status.server}` : 'Terminal not connected'}</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <button className={button} disabled={!canOperate || busy || status?.running} onClick={() => action('connect')}>Connect MT5 demo</button>
        <button className={button} disabled={!canOperate || busy || status?.running || !status?.connected || !eligible} onClick={() => action('save')}>{selection ? 'Save lab selection' : 'Save pair selection'}</button>
        <button className={`${button} text-green-300`} disabled={!canOperate || busy || !status?.connected || status?.running || dirty || !eligible || !status?.research_validated} onClick={() => action('start')}>Start demo</button>
        <button className={`${button} text-red-300`} disabled={!canOperate || busy || !status?.running} onClick={() => action('stop')}>Stop entries</button>
      </div>
    </div>
    {preflight?.error && <p className="text-sm text-amber-200" role="alert">Demo readiness unavailable: {preflight.error}</p>}
    {preflight && !preflight.error && <section className="rounded-lg border border-slate-600 bg-slate-900 p-4 space-y-2 text-sm" aria-label="Demo readiness">
      <h3 className="font-semibold text-white">Demo readiness for saved pair {preflight.symbol} · {preflight.timeframe}</h3>
      <p className={preflight.ready_to_start || preflight.monitoring ? 'text-green-300' : 'text-amber-200'}>
        {preflight.monitoring ? 'Monitoring is running.' : preflight.ready_to_start ? 'Ready to start demo monitoring.' : 'Setup needs attention before demo monitoring can start.'}
      </p>
      <p className={preflight.live_market_ready ? 'text-green-300' : 'text-amber-200'}>
        {preflight.live_market_ready ? 'Live data and entry safeguards are currently ready.' : 'Live-market entry checks are blocked right now.'}
      </p>
      {preflight.start_blockers?.length > 0 && <div><p className="font-medium">Setup blockers</p><ul className="list-disc pl-5 space-y-1">{preflight.start_blockers.map((message: string) => <li key={message}>{message}</li>)}</ul></div>}
      {preflight.market_blockers?.length > 0 && <div><p className="font-medium">Current market blockers</p><ul className="list-disc pl-5 space-y-1">{preflight.market_blockers.map((message: string) => <li key={message}>{message}</li>)}</ul></div>}
      <p className="text-xs text-slate-400">This read-only check applies to the saved pair and does not place an order. Quotes and candles can change; check again while monitoring.</p>
    </section>}
    {demoSignal && <section className="rounded-lg border border-cyan-800 bg-slate-900 p-4 space-y-2 text-sm" aria-label="Latest demo signal">
      <h3 className="font-semibold">Latest demo evaluation · {demoSignal.symbol}</h3>
      <p className={demoSignal.should_trade ? 'text-emerald-300' : 'text-slate-300'}>{demoSignal.should_trade && ['buy', 'sell'].includes(demoSignal.direction) ? `Qualified ${demoSignal.direction.toUpperCase()} strategy signal` : 'No qualifying entry'} · weighted score {demoSignal.score ?? 'N/A'} · {saved?.timeframe}</p>
      <p>Closed candle {new Date(demoSignal.bar * 1000).toLocaleString()} · {demoSignal.reason || 'No reason recorded'}</p>
      <p className="text-xs text-slate-400">This is the last evaluated candle for the saved pair. A qualifying signal does not prove an order was accepted or filled; check the journal and MT5 terminal.</p>
    </section>}
    {!status?.research_validated && <p className="text-sm text-amber-200">Demo entries require a passing research candidate. <a className="underline text-cyan-300" href="/analyze">Analyze selected assets</a>, then load the validated candidate. Editing or saving strategy settings invalidates previous validation.</p>}
    {status?.research_validated && status.research_candidate?.research_baseline && <p className="text-sm text-slate-300">Research baseline: holdout P&amp;L {Number(status.research_candidate.research_baseline.holdout.total_pnl).toFixed(2)}, {status.research_candidate.research_baseline.holdout.total_trades} trades, profit factor {Number(status.research_candidate.research_baseline.holdout.profit_factor).toFixed(2)}. Compare future demo results against this baseline; it is not a live performance claim.</p>}
    {status?.research_validated && candidate && <section className="rounded-lg border border-cyan-800 p-4 space-y-3" aria-label="Single-pair validation evidence">
      <h3 className="font-semibold">Single-pair validation evidence</h3>
      <p className="text-xs text-slate-300 break-words">Research {candidate.run_id} | {candidateScope} | {candidate.strategy.symbol} | {candidate.strategy.timeframe}. Paper outcomes use R; research and demo P&amp;L use account currency. Review each stage separately.</p>
      <div className="grid gap-3 md:grid-cols-3 text-sm">
        <div className="rounded bg-slate-900 p-3"><strong>Backtest holdout</strong><p>{candidate.research_baseline?.holdout?.total_trades ?? 0} trades; P&amp;L {candidate.research_baseline?.holdout?.total_pnl ?? 'N/A'}; profit factor {candidate.research_baseline?.holdout?.profit_factor ?? 'N/A'}.</p></div>
        <div className="rounded bg-slate-900 p-3"><strong>Forward paper</strong>{paperEvidence === null ? <p>Forward scanner evidence unavailable.</p> : candidatePaper.length ? candidatePaper.map((row: any) => <p key={row.policy_id} className="break-words">Policy {row.policy_id.slice(0, 12)}: {row.count}/300 closed; {row.observations} evaluations; {row.states.unresolved || 0} unresolved; mean {row.mean_r?.toFixed(2) ?? 'N/A'} R.</p>) : <p>No matching candidate-mode scanner evidence yet.</p>}<a className="text-cyan-300 underline" href="/scanner">Open Forward scanner</a></div>
        <div className="rounded bg-slate-900 p-3"><strong>Live-market demo</strong><p>{status.research_comparison?.closed_trades ?? 0} complete candidate-linked positions; P&amp;L {status.research_comparison?.total_pnl ?? 'N/A'} {status.research_comparison?.currency || ''}; profit factor {status.research_comparison?.profit_factor ?? 'N/A'}.</p><p>{status.research_comparison?.incomplete_positions ?? 0} incomplete positions excluded.</p></div>
      </div>
      <p className="text-xs text-slate-400">Demo comparison counts only complete positions opened by a successful order linked to this research run on this account. Older or unlinked journal entries remain in the journal but are excluded from this comparison.</p>
    </section>}
    {status?.research_comparison?.status === 'deteriorating' && <p role="alert" className="text-red-300">Research deterioration alert: {status.research_comparison.closed_trades} closed candidate-linked positions have profit factor {status.research_comparison.profit_factor}, below half the research baseline. Review the journal and stop entries if appropriate.</p>}
    {status?.research_comparison?.status === 'insufficient_sample' && <p className="text-xs text-slate-400">Forward comparison: {status.research_comparison.closed_trades}/{status.research_comparison.minimum_sample} complete candidate-linked positions; no deterioration conclusion yet.</p>}
    {status?.research_comparison?.status === 'observing' && <p className="text-xs text-cyan-200">Forward comparison active: {status.research_comparison.closed_trades} complete candidate-linked positions; current profit factor {status.research_comparison.profit_factor ?? 'N/A'} remains under observation.</p>}
    {status?.research_comparison?.status === 'no_baseline' && <p className="text-xs text-slate-400">Forward comparison is unavailable until a validated research candidate is loaded.</p>}
    <p className="text-sm text-cyan-200" role="status">{status?.message || 'Loading local MT5 service…'}</p>
    {error && <p className="text-sm text-red-300" role="alert">{error}</p>}
    <div className="space-y-3">
      <label className="block text-sm">Find broker pair<input value={symbolSearch} onChange={e => setSymbolSearch(e.target.value)} className="block mt-1 w-full max-w-sm bg-slate-900 p-2 rounded" placeholder="Search the connected MT5 account" /></label>
      <label className="block text-sm">MT5 broker pair<select aria-label="MT5 broker pair" value={symbol} disabled={!canOperate || busy || status?.running || !status?.connected} onChange={e => setSymbol(e.target.value)} className="block mt-1 w-full max-w-lg bg-slate-900 p-2 rounded">
        <option value="">Select an exact broker symbol</option>
        {symbol && !symbols.some(row => row.name === symbol) && <option value={symbol} disabled>{symbol} (not available in the connected catalog)</option>}
        {symbols.filter(row => row.name === symbol || `${row.name} ${row.description}`.toLowerCase().includes(symbolSearch.toLowerCase())).map(row => <option key={row.name} value={row.name} disabled={!row.eligible}>{row.name}{row.eligible ? '' : ` — ${row.reason}`}</option>)}
      </select></label>
      <p className="text-xs text-slate-400">Trade one exact broker pair at a time. Chart symbols and research asset codes are not automatically mapped to MT5. Stop entries, choose the broker pair, save, then start. Existing bot positions on earlier pairs block new entries until resolved.</p>
      {dirty && <p className="text-amber-300 text-sm">Save these changes before starting.</p>}
    </div>
    {selection && <>
      <div className="flex flex-wrap gap-5 items-end text-sm">
        <label>Risk per trade (%)<input type="number" min="0.01" max="1" step="0.1" value={risk} onChange={e => setRisk(Number(e.target.value))} className="block bg-slate-900 p-2 rounded w-28" /></label>
        <label>Daily equity loss limit (%)<input type="number" min="0.1" max="5" step="0.5" value={lossLimit} onChange={e => setLossLimit(Number(e.target.value))} className="block bg-slate-900 p-2 rounded w-28" /></label>
        <button className={button} disabled={!saved || busy} onClick={() => { onLoad?.(saved); setSymbol(saved.symbol); setRisk(saved.risk_pct * 100); setLossLimit(saved.daily_loss_pct * 100) }}>Load saved selection</button>
      </div>
      <p className="text-xs text-slate-400">Choose any threshold from 1 upward. Points are weighted, so the threshold is not a count of indicators. Save changes before starting. MT5 uses tick volume and broker lot sizing.</p>
    </>}
    {saved && <p className="text-xs text-slate-400">Saved: {saved.symbol} · {saved.timeframe} · minimum {saved.min_confluence} points · risk {saved.risk_pct * 100}% · daily limit {saved.daily_loss_pct * 100}% · {Object.entries(saved).filter(([key, value]) => key.startsWith('use_') && value).map(([key]) => key.slice(4).toUpperCase()).join(', ')}</p>}
    <p className="text-xs text-slate-400">Log into your demo account in MT5, enable Algo Trading, and allow external Python trading under Options → Expert Advisors. Keep this backend and MT5 running on this PC. Stop entries leaves positions open; verify their protective orders in MT5.</p>
    <div className="flex flex-wrap gap-6 text-sm">
      <span>Balance: {status?.balance?.toFixed(2) ?? '—'}</span>
      <span>Equity: {status?.equity?.toFixed(2) ?? '—'}</span>
      <span>Open positions: {status?.open_positions?.length ?? 0}</span>
      <span>Last poll: {status?.last_poll ? new Date(status.last_poll).toLocaleTimeString() : '—'}</span>
    </div>
    {status?.open_positions?.length > 0 && <div className="overflow-x-auto"><table className="w-full text-sm text-left">
      <thead><tr><th>Ticket</th><th>Pair</th><th>Side</th><th>Lots</th><th>Entry</th><th>SL / TP</th><th>Floating P&amp;L</th></tr></thead>
      <tbody>{status.open_positions.map((p: any) => <tr key={p.ticket}><td>{p.ticket}</td><td>{p.symbol}</td><td>{p.type === 0 ? 'Buy' : 'Sell'}</td><td>{p.volume}</td><td>{p.price_open}</td><td>{p.sl} / {p.tp}</td><td>{p.profit}</td></tr>)}</tbody>
    </table></div>}
    <details>
      <summary className="cursor-pointer font-semibold">Trade journal · latest {journal.length} events</summary>
      <button className="inline-block text-sm text-cyan-300 my-3" onClick={() => downloadFile('/api/mt5/journal.csv', 'mt5-journal.csv').catch(e => setError(String(e)))}>Download complete journal CSV</button>
      <p className="text-xs text-slate-400 mb-3">Includes signals, strategy snapshots, order requests, broker responses and entry/exit deals. Net deal P&amp;L includes commission, swap and fees. Exits while offline are recovered on reconnect.</p>
      <div className="max-h-96 overflow-auto"><table className="w-full text-xs text-left">
        <thead><tr><th className="p-2">Time</th><th>Event</th><th>Ticket / side</th><th>Lots / price</th><th>Net P&amp;L</th><th>Details</th></tr></thead>
        <tbody>{journal.map(row => <tr key={row.id} className="border-t border-slate-700">
          <td className="p-2 whitespace-nowrap">{new Date(row.ts).toLocaleString()}</td><td>{row.kind}{row.kind === 'deal' ? (row.data.entry === 0 ? ' · entry' : ' · exit') : ''}</td>
          <td>{row.data.symbol || row.data.strategy?.symbol} · {row.data.ticket ?? row.data.order ?? '—'} {row.data.direction ?? (row.kind === 'deal' ? row.data.type === 0 ? 'Buy' : 'Sell' : '')}</td>
          <td>{row.data.volume ?? '—'} / {row.data.price ?? '—'}</td>
          <td>{row.kind === 'deal' ? (row.data.profit + row.data.commission + row.data.swap + row.data.fee).toFixed(2) : '—'}</td>
          <td><details><summary className="cursor-pointer">{row.data.reason ?? row.data.comment ?? 'View'}</summary><pre className="whitespace-pre-wrap max-w-lg">{JSON.stringify(row.data, null, 2)}</pre></details></td>
        </tr>)}</tbody>
      </table>{journal.length === 0 && <p className="py-4 text-slate-400">No recorded events yet. Connect MT5 and start a demo session.</p>}</div>
    </details>
  </section>
}
