import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api, downloadFile } from '../api/client'
import { usePermissions } from '../auth/identity'

const input = 'block w-full mt-1 rounded bg-slate-900 border border-slate-600 p-2 min-w-0'
const button = 'px-4 py-2 rounded bg-cyan-700 disabled:opacity-40 disabled:cursor-not-allowed'
const presets = ['1HZ75V', '1HZ100V', '1HZ50V', 'BOOM500', 'CRASH500', 'frxEURUSD', 'frxGBPUSD', 'frxUSDJPY']
const freshProfile = () => ({ commission_per_lot: null, financing_long: null, financing_short: null,
  spread_price: null, slippage_ticks: 1, costs_confirmed: false, cost_source: '', specification_confirmed: false,
  contract_size: 1, tick_size: .00001, volume_min: .01, volume_step: .01, volume_max: 100,
  profit_currency: 'USD', account_currency: 'USD', annualization: 252, price_basis: 'bid',
  session: { timezone: 'UTC', weekdays: [0,1,2,3,4], open_minute: 0, close_minute: 1440, confirmed: false },
  rollover_timezone: 'UTC', rollover_minute: 0, rollover_weights: [1,1,3,1,1,0,0] })

export default function Analyze() {
  const { canRunResearch } = usePermissions()
  const [source, setSource] = useState('mt5')
  const [symbols, setSymbols] = useState<string[]>([])
  const [catalog, setCatalog] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [custom, setCustom] = useState('')
  const [profiles, setProfiles] = useState<Record<string, any>>({})
  const [bars, setBars] = useState<Record<string, any[]>>({})
  const [timeframe, setTimeframe] = useState('M5')
  const [days, setDays] = useState(7)
  const [windowSize, setWindowSize] = useState(60)
  const [balance, setBalance] = useState(10000)
  const [threshold, setThreshold] = useState(6)
  const [exposures, setExposures] = useState<Record<string, number>>({})
  const [job, setJob] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [pair, setPair] = useState('')
  const [strategy, setStrategy] = useState<Record<string, boolean>>({use_zscore:true,use_rsi:true,use_bb:true,use_vwap:false,use_stoch:false,use_lsl:false,use_smc:false,use_volume:false,use_hurst:false})
  const refreshHistory = () => api.get('/api/analysis/runs').then((r: any) => setHistory(r))
  async function catalogLoad() {
    const data: any = await api.get('/api/mt5/symbols')
    setCatalog(data.symbols.filter((s: any) => s.eligible).map((s: any) => s.name))
  }
  useEffect(() => {
    refreshHistory().catch(e => setError(String(e)))
    api.get('/api/mt5/status').then((s: any) => { if (s.connected) catalogLoad().catch(e => setError(String(e))) }).catch(() => {})
  }, [])
  useEffect(() => {
    if (!job || job.status !== 'running') return
    let active = true
    const timer = setInterval(async () => {
      try {
        const next: any = await api.get(`/api/analysis/runs/${job.id}`)
        if (active) { setJob(next); if (next.status !== 'running') refreshHistory().catch(() => {}) }
      } catch (e) { if (active) setError(String(e)) }
    }, 1500)
    return () => { active = false; clearInterval(timer) }
  }, [job?.id, job?.status])
  function toggle(symbol: string) {
    setSymbols(old => old.includes(symbol) ? old.filter(s => s !== symbol) : old.length < 8 ? [...old, symbol] : old)
    setProfiles(old => ({ ...old, [symbol]: old[symbol] || freshProfile() }))
  }
  function edit(symbol: string, change: any) { setProfiles(old => ({...old, [symbol]: {...old[symbol], ...change}})) }
  async function run() {
    setBusy(true); setError(''); setMessage(''); setJob(null)
    try {
      const result = await api.post('/api/analysis/runs', { source, timeframe, days, rolling_window: windowSize,
        initial_balance: balance, strategy: { min_confluence: threshold, ...strategy },
        assets: symbols.map(symbol => ({symbol, profile: profiles[symbol], ...(source === 'import' ? {bars: bars[symbol]} : {})})),
        exposures: Object.fromEntries(symbols.filter(s => exposures[s]).map(s => [s, exposures[s]])) })
      setJob(result); await refreshHistory()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const report = job?.report
  const relations = report?.relationships
  const selectedPair = relations?.pairs.find((p: any) => `${p.a}|${p.b}` === pair) || relations?.pairs[0]
  const locked = busy || job?.status === 'running' || !canRunResearch
  return <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto min-w-0">
    <header><h1 className="text-2xl font-bold">Analyze selected assets</h1><p className="text-slate-400 mt-2">Data checks, costed strategy validation and cross-asset relationships in one saved research report. Research never starts trading.</p></header>
    <section className="bg-slate-800 rounded-xl p-5 space-y-4">
      <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <label>Data source<select className={input} value={source} disabled={locked} onChange={e => {setSource(e.target.value);setSymbols([])}}><option value="mt5">Connected MT5 demo</option><option value="deriv">Deriv public history</option><option value="import">Imported candles</option></select></label>
        <label>Timeframe<select className={input} value={timeframe} disabled={locked} onChange={e=>setTimeframe(e.target.value)}>{['M1','M5','M15','M30','H1','H4'].map(t=><option key={t}>{t}</option>)}</select></label>
        <label>Lookback days<input className={input} type="number" min="1" max="90" value={days} disabled={locked} onChange={e=>setDays(+e.target.value)} /></label>
        <label>Rolling window (bars)<input className={input} type="number" min="20" max="500" value={windowSize} disabled={locked} onChange={e=>setWindowSize(+e.target.value)} /></label>
        <label>Starting account balance<input className={input} type="number" min="1" value={balance} disabled={locked} onChange={e=>setBalance(+e.target.value)} /></label>
      </div>
      {source === 'mt5' && <button className={button} disabled={locked} onClick={async()=>{try {await api.post('/api/mt5/connect',{});await catalogLoad()}catch(e){setError(String(e))}}}>Connect demo and load pairs</button>}
      <label className="block">Find asset<input className={input} value={search} onChange={e=>setSearch(e.target.value)} /></label>
      <div className="flex flex-wrap gap-2 max-h-52 overflow-y-auto">{(source==='mt5'?catalog:[...new Set([...presets,...symbols])]).filter(s=>s.toLowerCase().includes(search.toLowerCase())).map(s=><button key={s} disabled={locked || (!symbols.includes(s) && symbols.length>=8)} aria-pressed={symbols.includes(s)} onClick={()=>toggle(s)} className={`px-3 py-2 rounded border ${symbols.includes(s)?'bg-cyan-800 border-cyan-400':'border-slate-600'}`}>{s}</button>)}</div>
      {source !== 'mt5' && <div className="flex flex-wrap gap-2"><input aria-label="Exact asset symbol" placeholder="Exact asset symbol" value={custom} onChange={e=>setCustom(e.target.value)} className="bg-slate-900 rounded p-2" /><button disabled={locked || !custom.trim()} className={button} onClick={()=>{if(!symbols.includes(custom.trim()))toggle(custom.trim());setCustom('')}}>Add asset</button></div>}
      <p className="text-sm text-slate-400">{symbols.length}/8 selected. Each asset has independent capital; results are not a combined portfolio backtest. Maximum 10,000 candles per asset. Imports use the most recent selected lookback in the file.</p>
      <div className="flex flex-wrap gap-4">{Object.entries(strategy).map(([key,value])=><label key={key} className="text-sm"><input type="checkbox" checked={value} disabled={locked} onChange={e=>setStrategy({...strategy,[key]:e.target.checked})}/> {key.slice(4).toUpperCase()}</label>)}<label>Minimum score<input className={input} type="number" min="1" max="20" value={threshold} disabled={locked} onChange={e=>setThreshold(+e.target.value)} /></label></div>
    </section>
    {symbols.map(symbol => { const p=profiles[symbol]; return <details key={symbol} className="bg-slate-800 rounded-xl p-4" open={symbols.length===1 || undefined}>
      <summary className="font-semibold cursor-pointer">{symbol}: costs, contract and trading calendar</summary>
      <p className="text-sm text-slate-400 mt-3">Enter confirmed account-currency costs per lot. Commission is round trip. Financing is a positive charge or negative credit per rollover unit. Blank values block costed validation; confirmed zero is allowed. MT5 supplies contract sizes, lot limits and historical spreads.</p>
      <fieldset disabled={locked} className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
        {([['commission_per_lot','Round-trip commission / lot'],['financing_long','Long financing / lot'],['financing_short','Short financing / lot'],['spread_price','Full spread override (price units)'],['slippage_ticks','Slippage per fill (ticks)']] as const).map(([key,label])=><label key={key}>{label}<input className={input} type="number" step="any" value={p[key]??''} onChange={e=>edit(symbol,{[key]:e.target.value===''?null:+e.target.value})}/></label>)}
        <label>Cost source / broker schedule<input className={input} value={p.cost_source} onChange={e=>edit(symbol,{cost_source:e.target.value})}/></label>
        <label>Trading calendar<select className={input} value={p.session.weekdays.length===7?'365':'252'} onChange={e=>edit(symbol,{annualization:+e.target.value,session:{...p.session,weekdays:e.target.value==='365'?[0,1,2,3,4,5,6]:[0,1,2,3,4]}})}><option value="252">Monday-Friday / 252 days</option><option value="365">Every day / 365 days</option></select></label>
        <label>Session timezone<input className={input} value={p.session.timezone} onChange={e=>edit(symbol,{session:{...p.session,timezone:e.target.value}})}/></label>
        <label>Session open<input className={input} type="time" value={`${String(Math.floor(p.session.open_minute/60)).padStart(2,'0')}:${String(p.session.open_minute%60).padStart(2,'0')}`} onChange={e=>{const [h,m]=e.target.value.split(':').map(Number);edit(symbol,{session:{...p.session,open_minute:h*60+m}})}}/></label>
        <label>Session close minute (1440 = midnight)<input className={input} type="number" min="1" max="1440" value={p.session.close_minute} onChange={e=>edit(symbol,{session:{...p.session,close_minute:+e.target.value}})}/></label>
        <label>Rollover timezone<input className={input} value={p.rollover_timezone} onChange={e=>edit(symbol,{rollover_timezone:e.target.value})}/></label>
        <label>Rollover minute of day<input className={input} type="number" min="0" max="1439" value={p.rollover_minute} onChange={e=>edit(symbol,{rollover_minute:+e.target.value})}/></label>
        <label>Directional exposure (+ long / - short)<input className={input} type="number" value={exposures[symbol]??0} disabled={source==='mt5'} onChange={e=>setExposures({...exposures,[symbol]:+e.target.value})}/><small>MT5 uses the connected account's position snapshot.</small></label>
        {source!=='mt5' && (['contract_size','tick_size','volume_min','volume_step','volume_max','profit_currency','account_currency'] as const).map(key=><label key={key}>{key.replaceAll('_',' ')}<input className={input} value={p[key]} onChange={e=>edit(symbol,{[key]:key.includes('currency')?e.target.value:+e.target.value})}/></label>)}
        <label><input type="checkbox" checked={p.costs_confirmed} onChange={e=>edit(symbol,{costs_confirmed:e.target.checked})}/> I verified commission, financing, rollover settings and cost assumptions</label>
        <label><input type="checkbox" checked={p.session.confirmed} onChange={e=>edit(symbol,{session:{...p.session,confirmed:e.target.checked}})}/> I verified the session calendar, holidays and early closes</label>
        {source!=='mt5' && <label><input type="checkbox" checked={p.specification_confirmed} onChange={e=>edit(symbol,{specification_confirmed:e.target.checked})}/> I verified the linear contract specification</label>}
        <label>Import detailed contract/calendar profile (JSON)<input type="file" accept=".json" className="block max-w-full" onChange={async e=>{try{const f=e.target.files?.[0];if(f) edit(symbol,JSON.parse(await f.text()))}catch(err){setError(String(err))}}}/><small>Supports holiday dates, early closes, rollover weights and historical FX rates. See the automated research guide.</small></label>
        {source==='import' && <label>Candles for {symbol} (CSV/Excel)<input type="file" accept=".csv,.xlsx" className="block max-w-full" onChange={async e=>{try {const f=e.target.files?.[0];if(!f)return;let csv_data=await f.text();if(f.name.endsWith('.xlsx')){const bytes=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));csv_data='data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,'+btoa(binary)}const data:any=await api.post('/api/analysis/parse',{csv_data});setBars(old=>({...old,[symbol]:data.bars}))}catch(err){setError(String(err))}}}/><small>{bars[symbol]?.length??0} candles loaded</small></label>}
      </fieldset>
    </details>})}
    <button className={button} disabled={locked || !symbols.length || (source==='import' && symbols.some(s=>!bars[s]))} onClick={run}>Analyze selected assets</button>
    {error && <p role="alert" className="text-red-300 break-words">{error}</p>}{message && <p role="status" className="text-emerald-300">{message}</p>}
    {job && <section className="bg-slate-800 rounded-xl p-5 space-y-3" aria-label="Analysis progress"><h2 className="text-xl font-bold">{job.status}: {job.stage}</h2><progress aria-label="Research progress" className="w-full" max="1" value={job.progress}/><p className="text-sm text-slate-400">Saved run {job.id}. Progress persists when you leave this page. Cancellation stops at the next analysis checkpoint.</p>{job.status==='running' && <button className={button} disabled={!canRunResearch} onClick={async()=>{try{setJob(await api.post(`/api/analysis/runs/${job.id}/cancel`,{}))}catch(e){setError(String(e))}}}>Cancel analysis</button>}<button className="ml-2 underline" onClick={()=>downloadFile(`/api/analysis/runs/${job.id}/artifact`,`analysis-${job.id}.json`).catch(e=>setError(String(e)))}>Download report and source snapshot</button></section>}
    {report && Object.entries(report.assets||{}).map(([symbol, value])=>{const r:any=value;return <section key={symbol} className="bg-slate-800 rounded-xl p-5 space-y-3"><h2 className="text-xl font-bold">{symbol} research report</h2><p className={r.demo_candidate?'text-emerald-300':'text-amber-200'}>{r.demo_candidate?'Validated demo candidate':'More evidence needed'} · {r.status}</p>{r.error&&<p role="alert" className="text-red-300">{r.error}</p>}{r.quality&&<p>Data coverage: {(r.quality.coverage*100).toFixed(1)}% · {r.quality.missing_bars} missing bars · {r.quality.outside_session_or_grid} outside the supplied calendar · calendar {r.quality.session_confirmed?'confirmed':'unconfirmed'}</p>}
      {r.validation&&<><div className="grid grid-cols-2 md:grid-cols-4 gap-3">{Object.entries({ 'Holdout P&L':r.validation.holdout.total_pnl,'Holdout trades':r.validation.holdout.total_trades,'Profit factor':r.validation.holdout.profit_factor,'Max drawdown (%)':r.validation.holdout.max_drawdown_pct*100,'Sharpe':r.validation.holdout.sharpe_ratio,'Sortino':r.validation.holdout.sortino_ratio,'Expectancy':r.validation.holdout.expectancy,'Win rate (%)':r.validation.holdout.win_rate*100 }).map(([k,v])=><div key={k} className="bg-slate-900 rounded p-3"><div className="text-sm text-slate-400">{k}</div><strong>{Number(v).toFixed(2)}</strong></div>)}</div><ul>{Object.entries(r.validation.checks).map(([k,v])=><li key={k} className={v?'text-emerald-300':'text-amber-300'}>{v?'Pass':'Not met'}: {k.replaceAll('_',' ')}</li>)}</ul><p className="text-sm text-slate-400">{r.validation.note}</p><details><summary>Walk-forward folds and stress results</summary><pre className="overflow-auto max-h-80 text-xs">{JSON.stringify({folds:r.validation.folds,cost_stress:r.validation.holdout_cost_stress,monte_carlo:r.validation.monte_carlo},null,2)}</pre></details></>}
      {r.demo_candidate&&<button className={button} disabled={!canRunResearch || job.status==='running'} onClick={async()=>{try {await api.post(`/api/analysis/runs/${job.id}/candidate`,{symbol});setMessage(`${symbol} candidate loaded. Review MT5 Demo & Journal and explicitly start when ready.`)}catch(e){setError(String(e))}}}>Load validated candidate into MT5</button>}
    </section>})}
    {relations && <section className="bg-slate-800 rounded-xl p-5 space-y-5 min-w-0"><h2 className="text-xl font-bold">Cross-asset relationships</h2><p className="text-sm text-slate-400">{relations.method}. Values near +1 move together, near -1 move oppositely. N/A means insufficient overlap or constant returns.</p>
      <div className="overflow-x-auto"><table className="text-sm w-full" aria-label="Correlation heatmap"><thead><tr><th>Asset</th>{relations.symbols.map((s:string)=><th className="p-2" key={s}>{s}</th>)}</tr></thead><tbody>{relations.symbols.map((a:string)=><tr key={a}><th className="p-2 text-left">{a}</th>{relations.symbols.map((b:string)=>{const v=relations.matrix[a][b];return <td key={b} className="p-3 text-center" style={{background:v===null?'#334155':v>=0?`rgba(8,145,178,${.15+Math.abs(v)*.7})`:`rgba(190,24,93,${.15+Math.abs(v)*.7})`}}>{v===null?'N/A':v.toFixed(2)}</td>})}</tr>)}</tbody></table></div>
      <div className="grid md:grid-cols-2 gap-4">{(['positive','negative'] as const).map(key=><div key={key}><h3 className="font-bold">Strongest {key} relationships</h3><ul>{relations[key].map((p:any)=><li key={`${p.a}-${p.b}`}>{p.a} / {p.b}: {p.correlation.toFixed(3)} ({p.overlap} aligned returns)</li>)}</ul>{!relations[key].length&&<p>None measured.</p>}</div>)}</div>
      <label className="block">Rolling correlation pair<select className={input} value={selectedPair?`${selectedPair.a}|${selectedPair.b}`:''} onChange={e=>setPair(e.target.value)}>{relations.pairs.map((p:any)=><option key={`${p.a}|${p.b}`} value={`${p.a}|${p.b}`}>{p.a} / {p.b}</option>)}</select></label>
      {selectedPair&&<><p>{selectedPair.overlap} aligned returns · {selectedPair.unmatched_returns} unmatched returns excluded · {selectedPair.status}</p><div className="h-64 min-w-0"><ResponsiveContainer width="100%" height="100%"><LineChart data={selectedPair.rolling}><CartesianGrid stroke="#334155"/><XAxis dataKey="timestamp" tickFormatter={t=>new Date(t*1000).toLocaleDateString()}/><YAxis domain={[-1,1]}/><Tooltip labelFormatter={t=>new Date(Number(t)*1000).toLocaleString()}/><Line dataKey="correlation" stroke="#22d3ee" dot={false} connectNulls={false}/></LineChart></ResponsiveContainer></div></>}
      <h3 className="font-bold">Cointegration (separate from correlation)</h3><p className="text-sm text-slate-400">{relations.cointegration_method}</p><div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr><th>Pair</th><th>Evidence</th><th>Adjusted p-value</th><th>Observations</th></tr></thead><tbody>{relations.pairs.map((p:any)=><tr key={`${p.a}-${p.b}`}><td className="p-2">{p.a} / {p.b}</td><td>{p.cointegration.status==='tested'?(p.cointegration.evidence_of_cointegration?'Evidence detected':'Not detected'):p.cointegration.status.replaceAll('_',' ')}</td><td>{p.cointegration.adjusted_p_value?.toFixed(4)??'N/A'}</td><td>{p.cointegration.observations}</td></tr>)}</tbody></table></div>
      <h3 className="font-bold">Exposure warnings</h3>{relations.exposure_warnings.map((w:any)=><p key={`${w.a}-${w.b}`} className="text-amber-200">{w.a} / {w.b}: {w.message} ({w.correlation.toFixed(2)})</p>)}{!relations.exposure_warnings.length&&<p>No strong measured overlap in this snapshot. Missing assets and unmeasured risks are not cleared.</p>}<p className="text-sm text-slate-400">{relations.note}</p>
    </section>}
    <section className="bg-slate-800 rounded-xl p-5 space-y-3"><h2 className="text-xl font-bold">Saved analyses</h2>{history.map(h=><button key={h.id} className="block text-left w-full p-3 border-b border-slate-700 break-words" onClick={async()=>{try {setJob(null);setJob(await api.get(`/api/analysis/runs/${h.id}`));setPair('')}catch(e){setError(String(e))}}}>{new Date(h.created*1000).toLocaleString()} · {h.status} · {h.stage}</button>)}</section>
    <Link className="text-cyan-300 underline" to="/mt5">Review MT5 Demo & Journal</Link>
  </div>
}
