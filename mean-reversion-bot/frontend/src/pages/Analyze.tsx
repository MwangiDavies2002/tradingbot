import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import { api, downloadFile } from '../api/client'
import { usePermissions } from '../auth/identity'

const input = 'block w-full mt-1 rounded bg-slate-900 border border-slate-600 p-2 min-w-0'
const button = 'px-4 py-2 rounded bg-cyan-700 disabled:opacity-40 disabled:cursor-not-allowed'
const presets = ['1HZ75V', '1HZ100V', '1HZ50V', 'BOOM500', 'CRASH500', 'frxEURUSD', 'frxGBPUSD', 'frxUSDJPY']
const STRATEGY_OPTIONS = [
  ['use_zscore','Z-Score'], ['use_rsi','RSI'], ['use_bb','Bollinger Bands'], ['use_vwap','VWAP'],
  ['use_stoch','Stochastic'], ['use_lsl','Liquidity Sweep'], ['use_smc','SMC Structure'],
  ['use_volume','Volume Spike'], ['use_hurst','Hurst Regime'], ['use_linear_regression','Linear Regression'],
  ['use_tree_model','Tree Model'], ['use_time_series_nn','Time-Series Neural Net'], ['use_smt','SMT Divergence'],
  ['use_day_levels','Day High / Low'], ['use_candle_reversal','Candle Reversal'],
  ['use_candle_continuation','Candle Continuation'], ['use_crt','CRT'],
] as const
const freshProfile = () => ({ commission_per_lot: null, financing_long: null, financing_short: null,
  spread_price: null, slippage_ticks: 1, market_impact_ticks_per_lot: 0, costs_confirmed: false, cost_source: '', specification_confirmed: false,
  contract_size: 1, tick_size: .00001, volume_min: .01, volume_step: .01, volume_max: 100,
  profit_currency: 'USD', account_currency: 'USD', annualization: 252, price_basis: 'bid',
  session: { timezone: 'UTC', source: '', weekdays: [0,1,2,3,4], open_minute: 0, close_minute: 1440, holidays: [], early_closes: {}, special_hours: {}, confirmed: false },
  rollover_timezone: 'UTC', rollover_minute: 0, rollover_weights: [1,1,3,1,1,0,0] })

function MonteCarloSummary({ symbol, validation }: { symbol: string; validation: any }) {
  const result = validation.monte_carlo
  if (!result) return null
  const metricsReady = [result.drawdown_p95, result.ending_balance_p05, result.loss_probability]
    .every(value => typeof value === 'number' && Number.isFinite(value))
  return <section className="rounded-lg border border-slate-600 bg-slate-900 p-4 space-y-2" aria-label={`${symbol} Monte Carlo risk`}>
    <h3 className="font-semibold">Monte Carlo · {symbol}</h3>
    <p className="text-sm text-slate-300">Resamples {validation.oos_trades ?? 'unknown'} walk-forward out-of-sample trade outcomes for this asset.</p>
    {metricsReady ? <div className="grid gap-3 sm:grid-cols-3 text-sm">
      <div><span className="block text-slate-400">95th percentile drawdown</span><strong>{(result.drawdown_p95 * 100).toFixed(1)}%</strong></div>
      <div><span className="block text-slate-400">5th percentile ending balance</span><strong>{result.ending_balance_p05.toFixed(2)}</strong> <span className="text-slate-400">account currency</span></div>
      <div><span className="block text-slate-400">Share of paths ending below start</span><strong>{(result.loss_probability * 100).toFixed(1)}%</strong></div>
    </div> : <p className="text-amber-200 text-sm">No usable out-of-sample trade sample; Monte Carlo metrics are unavailable.</p>}
    <p className="text-xs text-slate-400">{metricsReady ? `${result.simulations} seeded simulations · ${result.method}` : 'Simulation not run'}. Assumes independent trades and fixed cash sizing; this is a sensitivity check, not a forecast or a trading signal.</p>
  </section>
}

export default function Analyze() {
  const location = useLocation()
  const scanLaunch = location.state as { source?: string; symbol?: string; symbols?: string[]; timeframe?: string; days?: number; scanDepth?: string } | null
  let savedSelection: { source?: string; symbols?: string[]; timeframe?: string; days?: number } = {}
  try { savedSelection = JSON.parse(sessionStorage.getItem('research-selection-v1') || '{}') } catch { /* Continue with an empty selection. */ }
  const selectionSource = scanLaunch?.source || savedSelection.source
  const selectedTimeframe = scanLaunch?.timeframe || savedSelection.timeframe
  const selectedDays = scanLaunch?.days || savedSelection.days
  const carriedSymbols = scanLaunch?.symbols?.length ? scanLaunch.symbols : scanLaunch?.symbol ? [scanLaunch.symbol] : savedSelection.symbols || []
  const launchedFromQuickScan = scanLaunch?.scanDepth === 'deep'
  const { canRunResearch } = usePermissions()
  const [source, setSource] = useState(() => ['mt5', 'deriv', 'import'].includes(selectionSource || '') ? selectionSource! : 'mt5')
  const [symbols, setSymbols] = useState<string[]>(() => carriedSymbols.slice(0, 8))
  const [catalog, setCatalog] = useState<{ name: string; description: string }[]>([])
  const [search, setSearch] = useState('')
  const [custom, setCustom] = useState('')
  const [profiles, setProfiles] = useState<Record<string, any>>(() => Object.fromEntries(carriedSymbols.slice(0, 8).map(symbol => [symbol, freshProfile()])))
  const [calendarDrafts, setCalendarDrafts] = useState<Record<string, { holiday: string; date: string; open: string; close: string }>>({})
  const [bars, setBars] = useState<Record<string, any[]>>({})
  const [timeframe, setTimeframe] = useState(() => ['M1','M5','M15','M30','H1','H4'].includes(selectedTimeframe || '') ? selectedTimeframe! : 'M5')
  const [days, setDays] = useState(() => [7,30,90].includes(selectedDays || 0) ? selectedDays! : 7)
  const [windowSize, setWindowSize] = useState(60)
  const [balance, setBalance] = useState(10000)
  const [threshold, setThreshold] = useState(6)
  const [researchScope, setResearchScope] = useState({ sessions: [] as string[], setup: 'strategy_signals', opening_range_session: 'new_york', opening_range_minutes: 15, opening_range_volume_filter: false, opening_range_volume_multiple: 1.5, opening_range_indicator_confirmation: false })
  const [exposures, setExposures] = useState<Record<string, number>>({})
  const [job, setJob] = useState<any>(null)
  const [history, setHistory] = useState<any[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [pair, setPair] = useState('')
  const [strategy, setStrategy] = useState<Record<string, boolean>>(() => Object.fromEntries(STRATEGY_OPTIONS.map(([key]) => [key, ['use_zscore','use_rsi','use_bb'].includes(key)])))
  useEffect(() => {
    try { sessionStorage.setItem('research-selection-v1', JSON.stringify({ source, symbols, timeframe, days })) } catch { /* Selection remains available in this page. */ }
  }, [source, symbols, timeframe, days])
  const refreshHistory = () => api.get('/api/analysis/runs').then((r: any) => setHistory(r))
  async function catalogLoad() {
    const data: any = await api.get('/api/mt5/symbols')
    setCatalog(data.symbols.filter((s: any) => s.eligible).map((s: any) => ({ name: s.name, description: s.description || '' })))
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
  function calendarDraft(symbol: string) { return calendarDrafts[symbol] || { holiday: '', date: '', open: '', close: '' } }
  function setCalendarDraft(symbol: string, change: Partial<{ holiday: string; date: string; open: string; close: string }>) {
    setCalendarDrafts(old => ({...old, [symbol]: {...calendarDraft(symbol), ...change}}))
  }
  function addHoliday(symbol: string, profile: any) {
    const holiday = calendarDraft(symbol).holiday
    if (!/^\d{4}-\d{2}-\d{2}$/.test(holiday)) { setError('Choose a valid holiday date.'); return }
    if (profile.session.special_hours?.[holiday] || profile.session.early_closes?.[holiday]) { setError('Remove the special hours or early close for this date before marking it as a holiday.'); return }
    edit(symbol, {session: {...profile.session, holidays: [...new Set([...(profile.session.holidays || []), holiday])].sort()}})
    setCalendarDraft(symbol, {holiday: ''})
  }
  function addSpecialHours(symbol: string, profile: any) {
    const draft = calendarDraft(symbol)
    const minute = (value: string) => { const [hours, minutes] = value.split(':').map(Number); return hours * 60 + minutes }
    if (!draft.date || !draft.open || !draft.close || minute(draft.open) >= minute(draft.close)) { setError('Choose a date and valid opening and closing times; overnight hours must be split at midnight.'); return }
    if (profile.session.holidays?.includes(draft.date) || profile.session.early_closes?.[draft.date]) { setError('Remove the holiday or early close for this date before adding special hours.'); return }
    edit(symbol, {session: {...profile.session, special_hours: {...(profile.session.special_hours || {}), [draft.date]: {open_minute: minute(draft.open), close_minute: minute(draft.close)}}}})
    setCalendarDraft(symbol, {date: '', open: '', close: ''})
  }
  async function run() {
    const intervalSeconds = Number(timeframe.slice(1)) * (timeframe.startsWith('M') ? 60 : 3600)
    const rangeSeconds = researchScope.opening_range_minutes * 60
    if (researchScope.setup === 'opening_range_breakout' && (intervalSeconds > rangeSeconds || rangeSeconds % intervalSeconds !== 0)) {
      setError(`Choose a timeframe that divides the ${researchScope.opening_range_minutes}-minute opening range evenly.`)
      return
    }
    const invalidAsset = symbols.find(symbol => {
      const profile = profiles[symbol]
      return profile?.slippage_ticks < 0 || (profile?.session?.confirmed && !profile.session.source?.trim())
    })
    if (invalidAsset) {
      setError(`${invalidAsset}: enter a nonnegative slippage value and a calendar source before confirming the session`)
      return
    }
    const missingCost = symbols.find(symbol => ['commission_per_lot','financing_long','financing_short'].some(key => profiles[symbol]?.[key] == null || profiles[symbol]?.[key] === ''))
    if (missingCost) {
      setError(`${missingCost}: fill the red starred commission and both financing fields. Enter 0 only when you have verified the broker charges zero.`)
      return
    }
    const missingCostSource = symbols.find(symbol => profiles[symbol]?.costs_confirmed && !profiles[symbol]?.cost_source?.trim())
    if (missingCostSource) {
      setError(`${missingCostSource}: add the broker cost schedule or other source before confirming costs.`)
      return
    }
    if ((researchScope.setup === 'strategy_signals' || researchScope.opening_range_indicator_confirmation)
        && !['use_zscore','use_rsi','use_bb','use_vwap','use_stoch','use_lsl','use_smc'].some(key => strategy[key])) {
      setError('Select at least one directional indicator. Volume and Hurst alone do not choose a direction.')
      return
    }
    setBusy(true); setError(''); setMessage(''); setJob(null)
    try {
      const result = await api.post('/api/analysis/runs', { source, timeframe, days, rolling_window: windowSize,
        initial_balance: balance, strategy: { min_confluence: threshold, ...strategy }, research_scope: researchScope,
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
  const runDisabled = locked
  const useIndicators = researchScope.setup === 'strategy_signals' || researchScope.opening_range_indicator_confirmation
  const selectedStrategyNames = STRATEGY_OPTIONS.filter(([key]) => strategy[key]).map(([, label]) => label)
  const customSymbol = custom.trim()
  const validCustomSymbol = customSymbol.length <= 128 && Array.from(customSymbol).every(character => character >= ' ' && character !== '\u007f')
  const availableAssets = source === 'mt5'
    ? catalog.filter(asset => `${asset.name} ${asset.description}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
    : [...new Set([...presets, ...symbols])].filter(symbol => symbol.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())).map(name => ({ name, description: '' }))
  const searchResults = search.trim() ? availableAssets.slice(0, 30) : []
  return <div className="p-4 md:p-6 space-y-6 max-w-7xl mx-auto min-w-0">
    <header><h1 className="text-2xl font-bold">{launchedFromQuickScan ? 'Deep scan · Analyze selected assets' : 'Analyze selected assets'}</h1><p className="text-slate-400 mt-2">Data checks, costed strategy validation and cross-asset relationships in one saved research report. Research never starts trading.</p>{launchedFromQuickScan && <p className="mt-1 text-sm text-slate-300">Confirm the detailed assumptions before running this deeper validation.</p>}</header>
    <section className="bg-slate-800 rounded-xl p-5 space-y-4">
      <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <label>Data source<select className={input} value={source} disabled={locked} onChange={e => {setSource(e.target.value);setSymbols([])}}><option value="mt5">Connected MT5 demo</option><option value="deriv">Deriv public history</option><option value="import">Imported candles</option></select></label>
        <label>Timeframe<select className={input} value={timeframe} disabled={locked} onChange={e=>setTimeframe(e.target.value)}>{['M1','M5','M15','M30','H1','H4'].map(t=><option key={t}>{t}</option>)}</select></label>
        <label>Lookback days<input className={input} type="number" min="1" max="90" value={days} disabled={locked} onChange={e=>setDays(+e.target.value)} /></label>
        <label>Rolling window (bars)<input className={input} type="number" min="20" max="500" value={windowSize} disabled={locked} onChange={e=>setWindowSize(+e.target.value)} /></label>
        <label>Starting account balance<input className={input} type="number" min="1" value={balance} disabled={locked} onChange={e=>setBalance(+e.target.value)} /></label>
      </div>
      {source === 'mt5' && <button className={button} disabled={locked} onClick={async()=>{try {await api.post('/api/mt5/connect',{});await catalogLoad()}catch(e){setError(String(e))}}}>Connect demo and load pairs</button>}
      <section className="rounded-lg border border-slate-600 bg-slate-900 p-4 space-y-3" aria-label="Selected research assets">
        <div><h2 className="font-semibold">Assets selected</h2><p className="text-sm text-slate-400">Your first-page selection is already here. Search to change it or add markets to compare (up to 8).</p></div>
        <div className="min-h-12 rounded-lg border border-slate-700 bg-slate-950/50 p-2 flex flex-wrap gap-2 items-center">
          {symbols.map(symbol=><span key={symbol} className="inline-flex items-center gap-2 rounded-md border border-cyan-700 bg-cyan-950/60 px-3 py-2 text-sm"><strong>{symbol}</strong><button type="button" aria-label={`Remove ${symbol}`} disabled={locked} onClick={()=>toggle(symbol)} className="text-slate-300 hover:text-red-300 disabled:opacity-40">×</button></span>)}
          {!symbols.length&&<span className="text-sm text-slate-500">No asset selected yet</span>}
        </div>
        <label className="block">Search and add or change an asset<input className={input} value={search} disabled={locked} placeholder={source==='mt5'?'Search broker symbols or descriptions, e.g. GER40':'Search assets, e.g. EURUSD, gold'} onChange={e=>setSearch(e.target.value)} /></label>
        {search.trim()&&<div className="max-h-48 overflow-y-auto rounded-lg border border-slate-700 divide-y divide-slate-700" role="listbox" aria-label="Asset search results">
          {searchResults.map(({name,description})=><button type="button" role="option" aria-selected={symbols.includes(name)} key={name} disabled={locked||(!symbols.includes(name)&&symbols.length>=8)} onClick={()=>toggle(name)} className={`w-full px-3 py-2 text-left hover:bg-slate-800 disabled:opacity-40 ${symbols.includes(name)?'bg-cyan-950/60 text-cyan-200':''}`}><span className="font-medium">{name}</span>{description&&<span className="ml-2 text-sm text-slate-400">{description}</span>}<span className="float-right text-xs text-slate-400">{symbols.includes(name)?'Selected · click to remove':'Add'}</span></button>)}
          {!searchResults.length&&<p className="p-3 text-sm text-slate-400">{source==='mt5'&&!catalog.length?'Connect your MT5 demo to search its instruments.':source==='mt5'?`No broker instrument matches “${search.trim()}”. Search symbol and description.`:`No preset matches “${search.trim()}”. Add the exact symbol below if needed.`}</p>}
        </div>}
        {source!=='mt5'&&search.trim()&&<div className="flex flex-wrap gap-2"><input aria-label="Exact asset symbol" maxLength={128} placeholder="Exact asset symbol" value={custom} onChange={e=>setCustom(e.target.value)} className="bg-slate-950 rounded p-2" /><button disabled={locked||symbols.length>=8||!validCustomSymbol} className={button} onClick={()=>{if(!symbols.includes(customSymbol))toggle(customSymbol);setCustom('')}}>Add exact symbol</button></div>}
        <p className="text-xs text-slate-400">{symbols.length}/8 selected · each asset has independent capital; this is not a combined portfolio backtest. Maximum 10,000 candles per asset.</p>
      </section>
      <div className="rounded-lg border border-slate-600 bg-slate-900 p-4 space-y-4">
        <div><h2 className="font-semibold">Research scope</h2><p className="text-sm text-slate-400">Choose when entries may happen and what price movement to test. These settings affect every validation period.</p></div>
        <label>Movement to test<select className={input} value={researchScope.setup} disabled={locked} onChange={e=>setResearchScope({...researchScope,setup:e.target.value,sessions:e.target.value==='opening_range_breakout'?[]:researchScope.sessions})}><option value="strategy_signals">Selected strategy signals</option><option value="opening_range_breakout">Opening range breakout</option></select></label>
        {researchScope.setup === 'opening_range_breakout' ? <div className="grid sm:grid-cols-2 gap-4">
          <label>Opening session<select className={input} value={researchScope.opening_range_session} disabled={locked} onChange={e=>setResearchScope({...researchScope,opening_range_session:e.target.value})}><option value="asia">Asia · Tokyo 09:00</option><option value="london">London · 08:00</option><option value="new_york">New York · 09:30</option></select></label>
          <label>Opening range<select className={input} value={researchScope.opening_range_minutes} disabled={locked} onChange={e=>setResearchScope({...researchScope,opening_range_minutes:+e.target.value})}><option value={15}>First 15 minutes</option><option value={30}>First 30 minutes</option><option value={60}>First 60 minutes</option></select></label>
          <label className="sm:col-span-2"><input type="checkbox" checked={researchScope.opening_range_volume_filter} disabled={locked} onChange={e=>setResearchScope({...researchScope,opening_range_volume_filter:e.target.checked})}/> Require breakout volume above its recent average</label>
          <label className="sm:col-span-2"><input type="checkbox" checked={researchScope.opening_range_indicator_confirmation} disabled={locked} onChange={e=>setResearchScope({...researchScope,opening_range_indicator_confirmation:e.target.checked})}/> Also require selected strategy indicators to agree with the breakout direction</label>
          {researchScope.opening_range_volume_filter && <label>Minimum volume vs prior 20 candles<input className={input} type="number" min="1" max="10" step="0.1" value={researchScope.opening_range_volume_multiple} disabled={locked} onChange={e=>setResearchScope({...researchScope,opening_range_volume_multiple:+e.target.value})}/></label>}
          <p className="sm:col-span-2 text-xs text-slate-400">The range begins at the later of the preset session open and this asset’s calendar open; it ends at the earlier close. A close beyond the range high/low triggers an entry at the next candle open; the opposite range edge is the stop. Optional volume confirmation requires the breakout candle to exceed the prior 20 candle average by the selected multiple. MT5 volume is tick volume, not traded quantity; missing or zero volume skips a filtered breakout. Preset clocks follow daylight saving time, and each asset’s holidays, early closes and special-hours calendar are applied. If any range candle is missing or the market is closed, that session is skipped. The chosen timeframe must divide this range evenly.</p>
        </div> : <fieldset disabled={locked} className="space-y-2"><legend className="text-sm">Only allow new entries during</legend><p className="text-xs text-slate-400">Leave all unchecked to include every candle inside the supplied broker calendar. Presets: Tokyo 09:00–15:00 JST, London 08:00–16:30 local, New York 09:30–16:00 ET. Positions may exit outside the selected entry window.</p><div className="flex flex-wrap gap-4">{[['asia','Asia · Tokyo'],['london','London'],['new_york','New York']].map(([key,label])=><label key={key}><input type="checkbox" checked={researchScope.sessions.includes(key)} onChange={e=>setResearchScope({...researchScope,sessions:e.target.checked?[...researchScope.sessions,key]:researchScope.sessions.filter(s=>s!==key)})}/> {label}</label>)}</div></fieldset>}
        <details className="rounded-lg border border-slate-600 bg-slate-800 p-3">
          <summary className="cursor-pointer select-none font-medium">Choose strategies · {selectedStrategyNames.length} selected{selectedStrategyNames.length ? `: ${selectedStrategyNames.slice(0,3).join(', ')}${selectedStrategyNames.length>3?'…':''}` : ''}</summary>
          <p className="mt-2 text-sm text-slate-400">Pick the signals to test together. For Opening Range Breakout, changing a strategy here automatically turns on indicator confirmation so the selected signals are applied.</p>
          <fieldset disabled={locked} className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {STRATEGY_OPTIONS.map(([key,label])=><label key={key} className={`rounded border px-3 py-2 text-sm ${strategy[key]?'border-cyan-500 bg-cyan-950/40':'border-slate-600'}`}><input type="checkbox" checked={strategy[key]} onChange={e=>{setStrategy({...strategy,[key]:e.target.checked});if(researchScope.setup==='opening_range_breakout')setResearchScope({...researchScope,opening_range_indicator_confirmation:true})}}/> <span className="ml-2">{label}</span></label>)}
          </fieldset>
          <label className="mt-3 inline-flex items-center gap-2">Minimum score<input className={`${input} max-w-28`} type="number" min="1" max="20" value={threshold} disabled={locked} onChange={e=>{setThreshold(+e.target.value);if(researchScope.setup==='opening_range_breakout')setResearchScope({...researchScope,opening_range_indicator_confirmation:true})}} /></label>
        </details>
      </div>
    </section>
    {symbols.map(symbol => { const p=profiles[symbol]; return <details key={symbol} className="bg-slate-800 rounded-xl p-4" open={symbols.length===1 || undefined}>
      <summary className="font-semibold cursor-pointer">{symbol}: costs, contract and trading calendar</summary>
      <p className="text-sm text-slate-400 mt-3">Enter confirmed account-currency costs per lot. Commission is round trip. Financing is a positive charge or negative credit per rollover unit. Blank values block costed validation; confirmed zero is allowed. MT5 supplies contract sizes, lot limits and historical spreads.</p>
      <fieldset disabled={locked} className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
        {([['commission_per_lot','Round-trip commission / lot'],['financing_long','Long financing / lot'],['financing_short','Short financing / lot'],['spread_price','Full spread override (price units)'],['slippage_ticks','Base slippage per fill (ticks)'],['market_impact_ticks_per_lot','Extra impact ticks per lot per fill']] as const).map(([key,label])=>{const required=['commission_per_lot','financing_long','financing_short'].includes(key);const missing=required&&(p[key]==null||p[key]==='');return <label key={key}>{label}{required&&<span className="text-red-400 font-bold"> *</span>}<input className={`${input} ${missing?'border-red-500 focus:border-red-400':''}`} aria-invalid={missing} required={required} type="number" min={key==='financing_long'||key==='financing_short'?undefined:0} step="any" value={p[key]??''} onChange={e=>edit(symbol,{[key]:e.target.value===''?(key==='market_impact_ticks_per_lot'?0:null):+e.target.value})}/>{missing&&<small className="text-red-300">Required for costed validation. Use 0 only if verified.</small>}</label>})}
        <p className="sm:col-span-2 lg:col-span-3 text-xs text-slate-400">Each fill adds base slippage plus (impact ticks per lot × position size). Impact is a user-supplied scenario, not a value inferred from candle volume or order-book depth. Enter a broker-calibrated value or leave at zero and treat the result as having no size-based impact.</p>
        <label>Cost source / broker schedule{p.costs_confirmed&&<span className="text-red-400 font-bold"> *</span>}<input className={`${input} ${p.costs_confirmed&&!p.cost_source.trim()?'border-red-500':''}`} aria-invalid={p.costs_confirmed&&!p.cost_source.trim()} required={p.costs_confirmed} value={p.cost_source} onChange={e=>edit(symbol,{cost_source:e.target.value})}/>{p.costs_confirmed&&!p.cost_source.trim()&&<small className="text-red-300">Required when cost assumptions are confirmed.</small>}</label>
        <label>Trading calendar<select className={input} value={p.session.weekdays.length===7?'365':'252'} onChange={e=>edit(symbol,{annualization:+e.target.value,session:{...p.session,weekdays:e.target.value==='365'?[0,1,2,3,4,5,6]:[0,1,2,3,4]}})}><option value="252">Monday-Friday / 252 days</option><option value="365">Every day / 365 days</option></select></label>
        <label>Session timezone<input className={input} value={p.session.timezone} onChange={e=>edit(symbol,{session:{...p.session,timezone:e.target.value}})}/></label>
        <label>Session calendar source<input className={input} placeholder="Broker schedule, exchange calendar or document" value={p.session.source} onChange={e=>edit(symbol,{session:{...p.session,source:e.target.value}})}/></label>
        <label>Session open<input className={input} type="time" value={`${String(Math.floor(p.session.open_minute/60)).padStart(2,'0')}:${String(p.session.open_minute%60).padStart(2,'0')}`} onChange={e=>{const [h,m]=e.target.value.split(':').map(Number);edit(symbol,{session:{...p.session,open_minute:h*60+m}})}}/></label>
        <label>Session close minute (1440 = midnight)<input className={input} type="number" min="1" max="1440" value={p.session.close_minute} onChange={e=>edit(symbol,{session:{...p.session,close_minute:+e.target.value}})}/></label>
        <div className="sm:col-span-2 lg:col-span-3 space-y-3 rounded border border-slate-600 p-3">
          <h3 className="font-medium">Holiday and special-hours dates · {p.session.timezone}</h3><p className="text-xs text-slate-400">Enter dates from the broker or exchange calendar; the app applies these to data checks and new entries but does not download holiday calendars automatically.</p>
          <div className="flex flex-wrap items-end gap-2"><label>Holiday date<input className={input} type="date" value={calendarDraft(symbol).holiday} onChange={e=>setCalendarDraft(symbol,{holiday:e.target.value})}/></label><button type="button" className={button} onClick={()=>addHoliday(symbol,p)}>Add holiday</button></div>
          <p className="text-xs text-slate-400">{(p.session.holidays||[]).length ? `Closed holidays: ${p.session.holidays.join(', ')}` : 'No holiday dates added.'}</p>
          <div className="flex flex-wrap gap-2">{(p.session.holidays||[]).map((date:string)=><button type="button" key={date} className="text-xs text-red-300 underline" onClick={()=>edit(symbol,{session:{...p.session,holidays:p.session.holidays.filter((item:string)=>item!==date)}})}>Remove holiday {date}</button>)}</div>
          <div className="flex flex-wrap items-end gap-2"><label>Special date<input className={input} type="date" value={calendarDraft(symbol).date} onChange={e=>setCalendarDraft(symbol,{date:e.target.value})}/></label><label>Open<input className={input} type="time" value={calendarDraft(symbol).open} onChange={e=>setCalendarDraft(symbol,{open:e.target.value})}/></label><label>Close<input className={input} type="time" value={calendarDraft(symbol).close} onChange={e=>setCalendarDraft(symbol,{close:e.target.value})}/></label><button type="button" className={button} onClick={()=>addSpecialHours(symbol,p)}>Add special hours</button></div>
          <div className="space-y-1">{Object.entries(p.session.special_hours||{}).map(([date,hours]:[string,any])=><div key={date} className="flex items-center gap-2 text-sm"><span>{date} · {String(Math.floor(hours.open_minute/60)).padStart(2,'0')}:{String(hours.open_minute%60).padStart(2,'0')}–{hours.close_minute===1440?'24:00':`${String(Math.floor(hours.close_minute/60)).padStart(2,'0')}:${String(hours.close_minute%60).padStart(2,'0')}`}</span><button type="button" className="text-red-300 underline" onClick={()=>{const next={...p.session.special_hours};delete next[date];edit(symbol,{session:{...p.session,special_hours:next}})}}>Remove</button></div>)}{!Object.keys(p.session.special_hours||{}).length&&<p className="text-xs text-slate-400">No special hours added.</p>}</div>
          {Object.entries(p.session.early_closes||{}).map(([date,close]:[string,any])=><div key={`early-${date}`} className="flex items-center gap-2 text-sm"><span>{date} · early close at {String(Math.floor(close/60)).padStart(2,'0')}:{String(close%60).padStart(2,'0')}</span><button type="button" className="text-red-300 underline" onClick={()=>{const next={...p.session.early_closes};delete next[date];edit(symbol,{session:{...p.session,early_closes:next}})}}>Remove</button></div>)}
        </div>
        <label>Rollover timezone<input className={input} value={p.rollover_timezone} onChange={e=>edit(symbol,{rollover_timezone:e.target.value})}/></label>
        <label>Rollover minute of day<input className={input} type="number" min="0" max="1439" value={p.rollover_minute} onChange={e=>edit(symbol,{rollover_minute:+e.target.value})}/></label>
        <label>Directional exposure (+ long / - short)<input className={input} type="number" value={exposures[symbol]??0} disabled={source==='mt5'} onChange={e=>setExposures({...exposures,[symbol]:+e.target.value})}/><small>MT5 uses the connected account's position snapshot.</small></label>
        {source!=='mt5' && (['contract_size','tick_size','volume_min','volume_step','volume_max','profit_currency','account_currency'] as const).map(key=><label key={key}>{key.replace(/_/g,' ')}<input className={input} value={p[key]} onChange={e=>edit(symbol,{[key]:key.includes('currency')?e.target.value:+e.target.value})}/></label>)}
        <label><input type="checkbox" checked={p.costs_confirmed} onChange={e=>edit(symbol,{costs_confirmed:e.target.checked})}/> I verified commission, financing, rollover settings and cost assumptions</label>
        <label><input type="checkbox" disabled={!p.session.source.trim()} checked={p.session.confirmed} onChange={e=>edit(symbol,{session:{...p.session,confirmed:e.target.checked}})}/> I verified the session calendar, holidays and early closes {!p.session.source.trim()&&<small className="block text-amber-200">Enter a calendar source before confirming.</small>}</label>
        {source!=='mt5' && <label><input type="checkbox" checked={p.specification_confirmed} onChange={e=>edit(symbol,{specification_confirmed:e.target.checked})}/> I verified the linear contract specification</label>}
        <label>Import detailed contract/calendar profile (JSON)<input type="file" accept=".json" className="block max-w-full" onChange={async e=>{try{const f=e.target.files?.[0];if(f) edit(symbol,JSON.parse(await f.text()))}catch(err){setError(String(err))}}}/><small>Supports holiday dates, early closes, rollover weights and historical FX rates. See the automated research guide.</small></label>
        {source==='import' && <label>Candles for {symbol} (CSV/Excel)<input type="file" accept=".csv,.xlsx" className="block max-w-full" onChange={async e=>{try {const f=e.target.files?.[0];if(!f)return;let csv_data=await f.text();if(f.name.endsWith('.xlsx')){const bytes=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));csv_data='data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,'+btoa(binary)}const data:any=await api.post('/api/analysis/parse',{csv_data});setBars(old=>({...old,[symbol]:data.bars}))}catch(err){setError(String(err))}}}/><small>{bars[symbol]?.length??0} candles loaded</small></label>}
      </fieldset>
    </details>})}
    <button className={button} disabled={runDisabled || !symbols.length || (source==='import' && symbols.some(s=>!bars[s]))} onClick={run}>Analyze selected assets</button>
    {error && <p role="alert" className="text-red-300 break-words whitespace-pre-line">{error}</p>}{message && <p role="status" className="text-emerald-300">{message}</p>}
    {job && <section className="bg-slate-800 rounded-xl p-5 space-y-3" aria-label="Analysis progress"><h2 className="text-xl font-bold">{job.status}: {job.stage}</h2><progress aria-label="Research progress" className="w-full" max="1" value={job.progress}/><p className="text-sm text-slate-400">Saved run {job.id}. Progress persists when you leave this page. Cancellation stops at the next analysis checkpoint.</p>{job.status==='running' && <button className={button} disabled={!canRunResearch} onClick={async()=>{try{setJob(await api.post(`/api/analysis/runs/${job.id}/cancel`,{}))}catch(e){setError(String(e))}}}>Cancel analysis</button>}<button className="ml-2 underline" onClick={()=>downloadFile(`/api/analysis/runs/${job.id}/artifact`,`analysis-${job.id}.json`).catch(e=>setError(String(e)))}>Download report and source snapshot</button></section>}
    {report?.decision_summary&&<section className="bg-slate-800 rounded-xl p-5" aria-label="Research decision summary"><h2 className="text-xl font-bold">Run decision: {report.decision_summary.overall_decision==='candidate_available'?'candidate available':'no trade'}</h2><p className="text-sm text-slate-400">{report.decision_summary.demo_candidates} demo candidates · {report.decision_summary.no_trade} no-trade assets · {report.decision_summary.failed} failed</p></section>}
    {report && Object.entries(report.assets||{}).map(([symbol, value])=>{const r:any=value;const scope=r.validation?.research_scope;const holdoutMeta=r.validation?.holdout?.metadata;const researchOnly=scope?.setup==='opening_range_breakout'||Boolean(scope?.sessions?.length);return <section key={symbol} className="bg-slate-800 rounded-xl p-5 space-y-3"><h2 className="text-xl font-bold">{symbol} research report</h2><p className={r.demo_candidate?'text-emerald-300':'text-amber-200'}>{r.demo_candidate?'Validated demo candidate':researchOnly&&r.validation?'Research complete · research-only scope':'No trade: more evidence needed'} · {r.status}</p>{r.error&&<p role="alert" className="text-red-300">{r.error}</p>}{scope&&<p className="text-sm text-cyan-200">Tested: {scope.setup==='opening_range_breakout'?`Opening range breakout · ${scope.opening_range_session.replace('_',' ')} · first ${scope.opening_range_minutes} minutes${scope.opening_range_volume_filter?` · volume ≥ ${scope.opening_range_volume_multiple}× prior 20-bar average`:''}`: `Selected strategy signals · ${scope.sessions.length?scope.sessions.join(', '):'all broker session hours'}`}</p>}{holdoutMeta?.opening_range_volume&&<p className="text-sm text-slate-300">Holdout breakout volume: {holdoutMeta.opening_range_volume.volume_confirmed} confirmed · {holdoutMeta.opening_range_volume.volume_rejected} rejected · {holdoutMeta.opening_range_volume.volume_unavailable} unavailable.</p>}{holdoutMeta?.market_impact_model&&<p className="text-sm text-slate-400">Holdout size impact: {holdoutMeta.market_impact_model.configured_ticks_per_lot} ticks per lot per fill. This is the configured user-supplied scenario; it is not measured market depth.</p>}{holdoutMeta?.intrabar_ambiguity&&<p className="text-sm text-slate-400">Holdout candles touching both stop and target: {holdoutMeta.intrabar_ambiguity.same_bar_stop_and_target}. The simulator resolves these stop first.</p>}{r.no_trade_reasons?.length>0&&<ul className="list-disc pl-5 text-amber-200">{r.no_trade_reasons.map((reason:string)=><li key={reason}>{reason}</li>)}</ul>}{r.quality&&<p>Data coverage: {(r.quality.coverage*100).toFixed(1)}% · {r.quality.missing_bars} missing bars in {r.quality.missing_ranges?.length??0} ranges · {r.quality.outside_session_or_grid} outside the supplied calendar · longest flat close run {r.quality.stale_close_run_bars} bars · spread median/max {r.quality.median_spread??'N/A'} / {r.quality.max_spread??'N/A'} · calendar {r.quality.session_confirmed?'confirmed':'unconfirmed'} ({r.quality.calendar_timezone}; {r.quality.holiday_dates} holidays, {r.quality.early_close_dates} early closes, {r.quality.special_hours_dates} special dates)</p>}{r.market_behavior?.status==='ok'&&<p>Behavior: {r.market_behavior.regime} · annualized volatility {(r.market_behavior.annualized_volatility*100).toFixed(2)}% · lag-1 return correlation {r.market_behavior.lag1_return_autocorrelation.toFixed(3)} · trend z-score {r.market_behavior.trend_zscore.toFixed(2)}</p>}
      {r.validation&&<><div className="grid grid-cols-2 md:grid-cols-4 gap-3">{Object.entries({ 'Holdout P&L':r.validation.holdout.total_pnl,'Holdout trades':r.validation.holdout.total_trades,'Profit factor':r.validation.holdout.profit_factor,'Max drawdown (%)':r.validation.holdout.max_drawdown_pct*100,'Sharpe':r.validation.holdout.sharpe_ratio,'Sortino':r.validation.holdout.sortino_ratio,'Expectancy':r.validation.holdout.expectancy,'Win rate (%)':r.validation.holdout.win_rate*100 }).map(([k,v])=><div key={k} className="bg-slate-900 rounded p-3"><div className="text-sm text-slate-400">{k}</div><strong>{Number(v).toFixed(2)}</strong></div>)}</div><ul>{Object.entries(r.validation.checks).map(([k,v])=><li key={k} className={v?'text-emerald-300':'text-amber-300'}>{v?'Pass':'Not met'}: {k.replace(/_/g,' ')}</li>)}</ul><p className="text-sm text-slate-400">{r.validation.note}</p><details><summary>Walk-forward folds and stress results</summary><p className="text-sm text-slate-400">Sensitivity: {r.validation.sensitivity?.positive_pnl_cases ?? 0}/{r.validation.sensitivity?.tested ?? 0} cases positive; worst P&amp;L {r.validation.sensitivity?.worst_case_pnl?.toFixed(2) ?? 'N/A'}.</p><pre className="overflow-auto max-h-80 text-xs">{JSON.stringify({folds:r.validation.folds,cost_stress:r.validation.holdout_cost_stress,sensitivity:r.validation.sensitivity,monte_carlo:r.validation.monte_carlo},null,2)}</pre></details></>}
      {r.validation?.monte_carlo && <MonteCarloSummary symbol={symbol} validation={r.validation} />}
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
