import { useEffect, useState } from 'react'
import { api, downloadFile } from '../api/client'
import { usePermissions } from '../auth/identity'

const button = 'px-3 py-2 rounded bg-cyan-800 disabled:opacity-40'
export default function Scanner() {
  const { canRunResearch } = usePermissions()
  const [state, setState] = useState<any>(null)
  const [ledger, setLedger] = useState<any>({ observations: [], trades: [] })
  const [analytics, setAnalytics] = useState<any>(null)
  const [symbols, setSymbols] = useState<any[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [timeframe, setTimeframe] = useState('M5')
  const [threshold, setThreshold] = useState(6)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [restored, setRestored] = useState<any>({})
  const [historyKind, setHistoryKind] = useState('observations')
  const [historyPage, setHistoryPage] = useState<any>(null)
  const [historyBusy, setHistoryBusy] = useState(false)
  const [exportBusy, setExportBusy] = useState(false)
  const [group, setGroup] = useState('symbol')
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
  const active = state?.run?.status === 'running'
  const candidateMode = restored.strategy_mode === 'research_candidate'
  const refresh = async () => {
    const [s, l, a] = await Promise.all([api.get('/api/scanner'), api.get('/api/scanner/ledger'), api.get('/api/scanner/analytics')])
    setState(s); setLedger(l); setAnalytics(a)
  }
  useEffect(() => {
    if (!local) return
    let mounted = true
    const poll = () => { if (mounted) refresh().catch(e => setError(String(e))) }
    poll(); const timer = setInterval(poll, 5000)
    return () => { mounted = false; clearInterval(timer) }
  }, [])
  async function catalog() {
    setBusy(true); setError('')
    try { const data: any = await api.get('/api/mt5/symbols'); setSymbols(data.symbols || []) }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  async function loadHistory(kind: string, older = false) {
    setHistoryBusy(true); setError('')
    const cursor = older ? `&through=${historyPage.through}&before=${historyPage.next_before}` : ''
    try { setHistoryPage(await api.get(`/api/scanner/records?kind=${kind}&limit=50${cursor}`)) }
    catch (e) { setError(String(e)) } finally { setHistoryBusy(false) }
  }
  async function exportEvidence() {
    setExportBusy(true); setError('')
    try { await downloadFile('/api/scanner/export', 'scanner-evidence.json') }
    catch (e) { setError(String(e)) } finally { setExportBusy(false) }
  }
  function restoreSettings() {
    const config = state?.run?.config
    if (!config) return
    setRestored(config); setSelected(config.assets.map((a: any) => a.symbol))
    setTimeframe(config.timeframe); setThreshold(config.threshold)
  }
  async function loadCandidate() {
    setBusy(true); setError('')
    try {
      const status: any = await api.get('/api/mt5/status')
      const candidate = status.research_candidate
      if (!status.research_validated || !candidate?.strategy?.symbol) {
        throw new Error('Load a passing single-pair candidate from Analyze selected assets into MT5 Demo & Journal first.')
      }
      const strategy = candidate.strategy
      setSelected([strategy.symbol]); setTimeframe(strategy.timeframe); setThreshold(strategy.min_confluence)
      setRestored((previous: any) => ({ ...previous, assets: [{ symbol: strategy.symbol }],
        strategy_mode: 'research_candidate', strategy, research_run_id: candidate.run_id,
        candidate_snapshot: candidate.snapshot }))
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  async function control(action: string) {
    setBusy(true); setError('')
    try {
      await api.post(`/api/scanner/${action}`, action === 'start' ? { ...restored, assets: selected.map(symbol => restored.assets?.find((a: any) => a.symbol === symbol) || { symbol }), timeframe, threshold } : {})
      await refresh()
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  if (!local) return <div className="p-6">Forward scanning requires the local app and your connected MT5 demo terminal.</div>
  return <div className="p-4 md:p-6 space-y-5 max-w-7xl mx-auto">
    <header><h1 className="text-2xl font-bold">Forward scanner</h1><p className="text-slate-300 mt-2">Continuously observe up to eight MT5 pairs and record hypothetical signals. Scanning never starts or approves broker trades.</p></header>
    {error && <p role="alert" className="p-3 bg-red-950 rounded break-words">{error}</p>}
    <section className="bg-slate-800 rounded-xl p-4 space-y-4">
      <div className="flex flex-wrap gap-3 items-center"><a className="text-cyan-300 underline" href="/mt5">Connect MT5 demo</a><button className={button} disabled={busy} onClick={() => void catalog()}>Load broker symbols</button><button className={button} disabled={!canRunResearch || busy || active || !state?.run?.config} onClick={restoreSettings}>Load saved scanner settings</button><button className={button} disabled={!canRunResearch || busy || active} onClick={() => void loadCandidate()}>Use loaded research candidate</button><span>{state?.run?.status || 'Not started'}</span></div>
      <label className="block">Find instruments<input className="block mt-1 bg-slate-900 rounded p-2 w-full" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <div className="max-h-52 overflow-auto flex flex-wrap gap-2" aria-label="Scanner assets">
        {symbols.filter(s => `${s.name} ${s.description}`.toLowerCase().includes(query.toLowerCase())).map(s => <button key={s.name} aria-pressed={selected.includes(s.name)} disabled={!canRunResearch || active || busy || candidateMode || !s.eligible || (!selected.includes(s.name) && selected.length >= 8)} className={`px-3 py-2 rounded border disabled:opacity-40 ${selected.includes(s.name) ? 'bg-cyan-700 border-cyan-400' : 'border-slate-600'}`} onClick={() => setSelected(p => p.includes(s.name) ? p.filter(n => n !== s.name) : [...p, s.name])}>{s.name}</button>)}
      </div>
      <p className="text-sm break-words">Selected: {selected.join(', ') || 'Load the connected catalog and select pairs'}</p>
      {candidateMode && <div className="text-sm text-cyan-200">Research candidate {restored.research_run_id || 'loaded'} · one pair · strategy and threshold locked to the validated report. <button className="underline" disabled={busy || active} onClick={() => setRestored((previous: any) => ({ ...previous, strategy_mode: 'manual', strategy: undefined, research_run_id: undefined, candidate_snapshot: undefined }))}>Use manual scanner settings</button></div>}
      <div className="flex flex-wrap gap-4 items-end">
        <label>Timeframe<select className="block bg-slate-900 p-2 rounded" value={timeframe} disabled={active || busy || candidateMode} onChange={e => setTimeframe(e.target.value)}>{['M1','M5','M15','M30','H1','H4'].map(t => <option key={t}>{t}</option>)}</select></label>
        <label>Paper spread model<select className="block bg-slate-900 p-2 rounded" value={restored.spread_model || 'fixed_quote'} disabled={!canRunResearch || active || busy} onChange={e => setRestored((p: any) => ({ ...p, spread_model: e.target.value }))}><option value="fixed_quote">Fixed observed quote</option><option value="candle_proxy_v1">Historical candle proxy</option></select></label>
        <label>Minimum weighted score<input className="block bg-slate-900 p-2 rounded w-24" type="number" min="1" max="20" value={threshold} disabled={active || busy || candidateMode} onChange={e => setThreshold(Number(e.target.value))} /></label>
        <button className={button} disabled={!canRunResearch || busy || active || !selected.length || !Number.isInteger(threshold) || threshold < 1 || threshold > 20} onClick={() => void control('start')}>Start paper scanner</button>
        <button className={button} disabled={!canRunResearch || busy || !active} onClick={() => void control('stop')}>Stop scanner</button>
      </div>
      <p className="text-sm text-slate-400">{candidateMode ? 'Signal indicators and threshold follow the loaded research candidate. The scanner still applies its own conservative paper regime gate and cost assumptions.' : 'Manual mode uses a fixed indicator configuration.'} Score /100 is weighted points /20, capped at 100; it is not a probability. RANGE requires Hurst below 0.45 and drift below 3 ATR. Trend, wide spread, volatility spikes, uncertain regimes and stale/gapped data block new paper entries.</p>
      <p className="text-sm text-amber-200">News and macro coverage: unknown. Liquidity is a spread proxy, not order-book depth. Session groups use six-hour UTC buckets. These exploratory observations do not qualify a strategy for execution.</p>
      <p className="text-sm text-slate-400">Historical candle mode uses each recorded bar spread as an ask-price proxy, not an executable quote. Missing or unconfirmed zero spreads leave outcomes unresolved. Commission and financing remain unmodeled.</p>
      <p className="text-xs text-slate-400">Polling: {restored.poll_seconds ?? 30}s | Max spread/ATR: {restored.max_spread_atr ?? 0.2} | Slippage/ATR: {restored.slippage_atr ?? 0.02} | Max holding bars: {restored.max_hold_bars ?? 12}. Loading saved settings restores these limits too.</p>
      {state?.run && <p className="text-xs text-slate-400 break-words">Active/saved selection: {state.run.config.assets.map((a: any) => a.symbol).join(', ')} · {state.run.config.timeframe} · started {new Date(state.run.created * 1000).toLocaleString()}{state.run.error && ` · ${state.run.error}`}</p>}
    </section>
    <section className="bg-slate-800 rounded-xl p-4"><h2 className="font-semibold mb-3">Latest observations</h2><div className="overflow-x-auto"><table className="w-full min-w-[850px] text-sm text-left"><thead><tr>{['Pair','Observed','Regime','Deviation','Score /100','Direction','Action / reasons'].map(h => <th className="p-2" key={h}>{h}</th>)}</tr></thead><tbody>{(state?.latest || []).map((r: any) => <tr key={r.symbol} className="border-t border-slate-700"><td className="p-2">{r.symbol}<details><summary className="text-cyan-300 cursor-pointer">Instrument identity</summary><p>{r.scope || 'Legacy account unknown'}</p><pre className="whitespace-pre-wrap break-all max-w-xs text-xs">{JSON.stringify(r.instrument || { provider: r.provider, symbol: r.symbol, scope: r.scope }, null, 2)}</pre></details></td><td>{new Date(r.observed * 1000).toLocaleString()}</td><td>{r.regime}</td><td>{r.deviation?.toFixed(2) ?? 'N/A'}</td><td>{r.score ?? 'N/A'}</td><td>{r.direction || 'none'}</td><td className="p-2 max-w-xs">{r.eligible ? 'Paper eligible' : 'No trade'}: {r.reasons.join('; ')}</td></tr>)}</tbody></table></div>{!state?.latest?.length && <p className="text-slate-400">No observations yet.</p>}</section>
    {analytics && <section className="bg-slate-800 rounded-xl p-4 space-y-3">
      <h2 className="font-semibold">Forward evidence by pair and policy</h2>
      <p className="text-sm text-slate-300">Review each exact account, broker pair, timeframe and paper policy separately. The 300 closed-trade target applies to each row; pooled totals do not qualify a pair.</p>
      <div className="overflow-x-auto"><table className="w-full min-w-[850px] text-sm text-left [&_th]:p-2 [&_td]:p-2">
        <thead><tr><th>Account / pair</th><th>Timeframe</th><th>Policy</th><th>Signals</th><th>Closed / 300</th><th>Mean R</th><th>Win rate</th><th>Other states</th></tr></thead>
        <tbody>{(analytics.per_pair_policy || []).map((p: any) => <tr key={`${p.scope}:${p.symbol}:${p.timeframe}:${p.policy_id}`} className="border-t border-slate-700">
          <td>{p.scope} / {p.symbol}{p.research_run_id && <div className="text-xs text-cyan-300">Research {p.research_run_id}</div>}</td>
          <td>{p.timeframe}</td>
          <td><details><summary className="cursor-pointer">{p.policy_id === 'legacy_unknown' ? 'Unknown' : p.policy_id.slice(0, 12)}</summary><p className="break-all text-xs">{p.policy_id}</p><p className="break-all text-xs">Scanner runs: {p.run_ids.join(', ') || 'Unknown'}</p></details></td>
          <td>{p.observations}</td><td>{p.count} / 300 ({p.sample})</td><td>{p.mean_r?.toFixed(2) ?? 'N/A'}</td>
          <td>{p.win_rate == null ? 'N/A' : `${(p.win_rate*100).toFixed(1)}%`}</td>
          <td>Pending {p.states.pending || 0}; Open {p.states.open || 0}; Unresolved {p.states.unresolved || 0}</td>
        </tr>)}</tbody>
      </table></div>
      {!analytics.per_pair_policy?.length && <p className="text-slate-400">No saved pair evidence yet.</p>}
    </section>}
    {analytics && <section className="bg-slate-800 rounded-xl p-4 space-y-3"><h2 className="font-semibold">All scanner evidence</h2><p>{analytics.observations} observations · {analytics.overall.count} closed paper trades across all pairs and policies</p><p className="text-sm text-slate-400">{analytics.model} A large sample alone does not establish an edge.</p><label>Break down by<select className="block bg-slate-900 p-2 rounded" value={group} onChange={e => setGroup(e.target.value)}>{['symbol','scope','policy_id','score_bucket','regime','session','setup','volatility','news'].map(g => <option key={g}>{g}</option>)}</select></label><div className="overflow-x-auto"><table className="w-full min-w-[480px] text-sm text-left [&_th]:p-2 [&_td]:p-2"><thead><tr><th>Group</th><th>Closed</th><th>Mean R</th><th>Win rate</th><th>Evidence</th></tr></thead><tbody>{Object.entries(analytics.groups[group] || {}).map(([k,v]: [string, any]) => <tr key={k}><td>{k}</td><td>{v.count}</td><td>{v.mean_r?.toFixed(2) ?? 'N/A'}</td><td>{v.win_rate == null ? 'N/A' : `${(v.win_rate*100).toFixed(1)}%`}</td><td>{v.sample}</td></tr>)}</tbody></table></div><p className="text-xs text-slate-400">Pending {analytics.states.pending || 0} · Open {analytics.states.open || 0} · Unresolved {analytics.states.unresolved || 0}. Stopping or restarting leaves unfinished outcomes unresolved.</p></section>}
    <section className="bg-slate-800 rounded-xl p-4 space-y-3"><h2 className="font-semibold">Automatic paper ledger</h2><p className="text-sm text-slate-400">Latest 500. Entry uses the first full candle starting after observation, with adverse slippage. If stop and target both occur in a candle, stop wins. One hypothetical position per symbol per scan; missing outcome bars remain unresolved.</p><div className="overflow-x-auto"><table className="w-full min-w-[700px] text-sm text-left"><thead><tr>{['Pair','Side','State','Entry','Stop / target','Outcome R','Exit reason'].map(h => <th className="p-2" key={h}>{h}</th>)}</tr></thead><tbody>{ledger.trades.map((p: any) => <tr key={p.id} className="border-t border-slate-700"><td className="p-2">{p.symbol}</td><td>{p.direction}</td><td>{p.state}</td><td>{p.entry ?? 'Pending'}</td><td>{p.stop ?? '—'} / {p.target ?? '—'}</td><td>{p.r_multiple?.toFixed(2) ?? 'N/A'}</td><td>{p.exit_reason || '—'}</td></tr>)}</tbody></table></div><details><summary>Eligible and rejected signal history ({ledger.observations.length} latest)</summary><ul className="space-y-2 mt-3 text-sm">{ledger.observations.map((r: any, i: number) => <li key={r.id || i} className="break-words">{r.symbol} · {new Date(r.observed*1000).toLocaleString()} · {r.regime} · {r.reasons.join('; ')}</li>)}</ul></details></section>
    <section className="bg-slate-800 rounded-xl p-4 space-y-3" aria-label="Saved scanner evidence">
      <h2 className="font-semibold">Saved evidence</h2>
      <p className="text-sm text-slate-400">Browse older records or download all runs, observations and paper trades. Pages keep a fixed record boundary while new signals arrive; trade outcomes may still update. Downloads capture a consistent snapshot. Exports include broker account identifiers.</p>
      <div className="flex flex-wrap gap-3 items-end">
        <label>Record type<select className="block bg-slate-900 p-2 rounded" value={historyKind} disabled={historyBusy} onChange={e => { setHistoryKind(e.target.value); setHistoryPage(null) }}><option value="observations">Signals and rejections</option><option value="trades">Paper trades</option></select></label>
        <button className={button} disabled={historyBusy} onClick={() => void loadHistory(historyKind)}>Latest records</button>
        <button className={button} disabled={historyBusy || historyPage?.next_before == null} onClick={() => void loadHistory(historyKind, true)}>Older records</button>
        <button className={button} disabled={exportBusy} onClick={() => void exportEvidence()}>{exportBusy ? 'Exporting...' : 'Download all evidence (JSON)'}</button>
      </div>
      {historyPage && <><p className="text-sm">{historyPage.items.length} shown | {historyPage.total} records in this browsing window</p><ul className="space-y-2 text-sm">{historyPage.items.map((r: any) => <li key={r.record_cursor} className="border-t border-slate-700 pt-2 break-words"><details><summary className="cursor-pointer">{r.symbol} | {r.scope || 'Legacy account unknown'} | {new Date(r.observed*1000).toLocaleString()} | {r.state || r.regime}</summary><pre className="whitespace-pre-wrap break-all text-xs mt-2">{JSON.stringify(r, null, 2)}</pre></details></li>)}</ul>{historyPage.items.length === 0 && <p>No saved records for this selection.</p>}</>}
    </section>
  </div>
}

