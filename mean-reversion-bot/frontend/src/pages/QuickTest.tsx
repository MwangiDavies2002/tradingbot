import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRight, Check, LoaderCircle, Play, RotateCcw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { usePermissions } from '../auth/identity'

const STRATEGIES = [
  { id: 'use_zscore', name: 'Z-Score', detail: 'Price deviation from rolling mean' },
  { id: 'use_rsi', name: 'RSI', detail: 'Relative Strength Index momentum' },
  { id: 'use_bb', name: 'Bollinger Bands', detail: 'Volatility envelope breach' },
  { id: 'use_vwap', name: 'VWAP', detail: 'Volume Weighted Average Price' },
  { id: 'use_stoch', name: 'Stochastic', detail: 'Momentum exhaustion' },
  { id: 'use_lsl', name: 'LSL Grab', detail: 'Liquidity Sweep Levels' },
  { id: 'use_smc', name: 'SMC Structure', detail: 'BOS/CHoCH & Order Blocks' },
  { id: 'use_volume', name: 'Volume Spike', detail: 'Unusual volume activity' },
  { id: 'use_hurst', name: 'Hurst Regime', detail: 'Mean-reversion vs Trending' },
  { id: 'use_linear_regression', name: 'Linear Regression', detail: 'Regression trend forecast' },
  { id: 'use_tree_model', name: 'Tree Model', detail: 'Non-linear feature classifier' },
  { id: 'use_time_series_nn', name: 'Time-Series Neural Net', detail: 'Sequence forecast filter' },
  { id: 'use_smt', name: 'SMT Divergence', detail: 'Cross-market divergence' },
  { id: 'use_day_levels', name: 'Day High / Low', detail: 'High/low of day reactions' },
  { id: 'use_candle_reversal', name: 'Candle Reversal', detail: 'Closed-candle reversal' },
  { id: 'use_candle_continuation', name: 'Candle Continuation', detail: 'Closed-candle continuation' },
  { id: 'use_crt', name: 'CRT', detail: 'Candle range theory setup' },
]
const DERIV_ASSETS = [
  { name: '1HZ75V', description: 'Volatility 75 (1s)', group: 'Synthetic indices' },
  { name: '1HZ100V', description: 'Volatility 100 (1s)', group: 'Synthetic indices' },
  { name: '1HZ50V', description: 'Volatility 50 (1s)', group: 'Synthetic indices' },
  { name: 'BOOM500', description: 'Boom 500 Index', group: 'Synthetic indices' },
  { name: 'CRASH500', description: 'Crash 500 Index', group: 'Synthetic indices' },
  { name: 'frxEURUSD', description: 'Euro / US Dollar', group: 'Forex' },
  { name: 'frxGBPUSD', description: 'British Pound / US Dollar', group: 'Forex' },
  { name: 'frxUSDJPY', description: 'US Dollar / Japanese Yen', group: 'Forex' },
]
const GROUPS = ['All groups', 'Stocks', 'Bonds', 'Forex', 'Indices', 'Commodities', 'Gold', 'Silver', 'Synthetic indices', 'Cryptocurrencies', 'Other']
type Broker = 'deriv' | 'mt5'
type Asset = { name: string; description: string; group: string; eligible?: boolean; reason?: string }
function classifyAsset(asset: { name: string; description?: string }): string {
  const name = asset.name.toLowerCase()
  const text = (asset.name + ' ' + (asset.description || '')).toLowerCase()
  if (/xau|gold/.test(text)) return 'Gold'
  if (/xag|silver/.test(text)) return 'Silver'
  if (/bond|treasury|gilt|bund|fixed income|t-note|10y|30y/.test(text)) return 'Bonds'
  if (/crypto|bitcoin|ethereum|(^|[^a-z])(btc|eth|ltc|xrp)([^a-z]|$)|btcusd|ethusd|ltcusd|xrpusd/.test(text)) return 'Cryptocurrencies'
  if (/commodity|commodities|x(pt|pd|ti|br)|wti|brent|crude|natural gas|oil|copper|platinum|palladium|wheat|coffee|cocoa/.test(text)) return 'Commodities'
  if (/forex|fx|frx/.test(text) || /^[a-z]{6}([._-].*)?$/.test(name)) return 'Forex'
  if (/synthetic|volatility|boom|crash|jump|step index|range break/.test(text)) return 'Synthetic indices'
  if (/index|indices|\.cash|nasdaq|s&p|dow jones|dax|ftse|nikkei/.test(text) || /^(us|nas|sp|uk|ger|de|fra|jp|hk)\d{2,4}/.test(name)) return 'Indices'
  if (/stock|share|equity|equities|inc\.|corp\.| plc/.test(text) || /^[a-z]{1,5}([._-].*)?$/.test(name)) return 'Stocks'
  return 'Other'
}
const DEFAULT_STRATEGIES = Object.fromEntries(STRATEGIES.map(item => [item.id, ['use_zscore', 'use_rsi', 'use_bb'].includes(item.id)]))
type Result = { symbol: string; total_pnl: number; win_rate: number; total_trades: number; max_drawdown: number }

export default function QuickTest() {
  const { canRunResearch } = usePermissions()
  const navigate = useNavigate()
  const [step, setStep] = useState(0)
  const [scanDepth, setScanDepth] = useState<'quick' | 'deep'>('quick')
  const [broker, setBroker] = useState<Broker>('deriv')
  const [brokerConnected, setBrokerConnected] = useState(false)
  const [brokerLoading, setBrokerLoading] = useState(false)
  const [brokerMessage, setBrokerMessage] = useState('')
  const [mt5Assets, setMt5Assets] = useState<Asset[]>([])
  const [assetGroup, setAssetGroup] = useState('All groups')
  const [assetSearch, setAssetSearch] = useState('')
  const [symbol, setSymbol] = useState('1HZ75V')
  const [strategies, setStrategies] = useState<Record<string, boolean>>(DEFAULT_STRATEGIES)
  const [timeframe, setTimeframe] = useState('M5')
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Result | null>(null)
  const [finished, setFinished] = useState(false)
  useEffect(() => {
    try {
      sessionStorage.setItem('research-selection-v1', JSON.stringify({ source: broker, symbols: [symbol], timeframe, days }))
    } catch { /* The guided test still works if browser storage is unavailable. */ }
  }, [broker, symbol, timeframe, days])
  const selectedStrategies = STRATEGIES.filter(item => strategies[item.id])
  const strategySummary = selectedStrategies.length === STRATEGIES.length
    ? 'All ' + STRATEGIES.length + ' strategies'
    : selectedStrategies.map(item => item.name).join(', ')
  const assets: Asset[] = broker === 'deriv'
    ? DERIV_ASSETS
    : mt5Assets.map(item => ({ ...item, group: classifyAsset(item) }))
  const searchTerm = assetSearch.trim().toLocaleLowerCase()
  const filteredAssets = assets.filter(item => {
    if (searchTerm) return (item.name + ' ' + item.description).toLocaleLowerCase().includes(searchTerm)
    return assetGroup === 'All groups' || item.group === assetGroup
  })
  function selectFirstMatchingAsset(listed: Asset[]) {
    const term = assetSearch.trim().toLocaleLowerCase()
    const match = listed.find(item => term
      ? (item.name + ' ' + item.description).toLocaleLowerCase().includes(term)
      : assetGroup === 'All groups' || item.group === assetGroup)
    if (match) setSymbol(match.name)
  }

  useEffect(() => {
    if (broker !== 'mt5') return
    let active = true
    setBrokerLoading(true); setBrokerMessage('')
    api.get('/api/mt5/status').then(async (status: any) => {
      if (!active) return
      if (!status.connected) {
        setBrokerConnected(false); setMt5Assets([])
        setBrokerMessage('Connect your MT5 terminal to load its broker instruments.')
        return
      }
      const data = await api.get('/api/mt5/symbols') as { symbols: Asset[] }
      if (active) {
        setBrokerConnected(true)
        const listed = data.symbols.map(row => ({ ...row, group: classifyAsset(row) }))
        setMt5Assets(listed)
        if (listed.length) selectFirstMatchingAsset(listed)
        setBrokerMessage(listed.length ? '' : 'No instruments were returned by the connected broker.')
      }
    }).catch(err => {
      if (active) { setBrokerConnected(false); setBrokerMessage(err instanceof Error ? err.message : 'Could not load the MT5 instrument list.') }
    }).finally(() => { if (active) setBrokerLoading(false) })
    return () => { active = false }
  }, [broker])

  async function connectMt5() {
    setBrokerLoading(true); setBrokerMessage('')
    try {
      await api.post('/api/mt5/connect', {})
      const data = await api.get('/api/mt5/symbols') as { symbols: Asset[] }
      const listed = data.symbols.map(row => ({ ...row, group: classifyAsset(row) }))
      setMt5Assets(listed); setBrokerConnected(true)
      if (listed.length) selectFirstMatchingAsset(listed)
      setBrokerMessage(listed.length ? '' : 'Connected, but no instruments were returned.')
    } catch (err) {
      setBrokerConnected(false)
      setBrokerMessage(err instanceof Error ? err.message : 'Could not connect to MT5. Check that the terminal is installed and logged in.')
    } finally { setBrokerLoading(false) }
  }

  function changeBroker(value: Broker) {
    setBroker(value); setAssetGroup('All groups'); setAssetSearch('')
    const first = value === 'deriv' ? DERIV_ASSETS[0]?.name : mt5Assets[0]?.name
    if (first) setSymbol(first)
  }

  async function runTest() {
    if (!canRunResearch || loading) return
    setLoading(true); setError(''); setResult(null); setFinished(false)
    try {
      const data = await api.post('/api/backtest/run', {
        data_source: broker, symbols: [symbol], timeframe, days, initial_balance: 10000,
        min_confluence: 3, csv_data: null, ...strategies, strategy_versions: {}, news_only: false,
      }) as Result[]
      if (!data || !data.length) throw new Error('The test finished without a result. Try another asset or interval.')
      setResult(data[0]); setFinished(true)
    } catch (err) { setError(err instanceof Error ? err.message : 'The test could not be completed.') }
    finally { setLoading(false) }
  }
  function startOver() { setStep(0); setResult(null); setError(''); setFinished(false) }

  return <div className="min-h-full px-4 py-10 sm:px-8"><div className="mx-auto max-w-2xl">
    <div className="mb-8"><p className="text-sm font-medium text-cyan-300">STRATEGY TESTER</p><h1 className="mt-2 text-3xl font-bold text-white">Run a test</h1><p className="mt-2 text-slate-400">Choose what to test. We’ll run it on past market data and show you what happened.</p></div>
    {!finished && <div className="mb-5 flex items-center gap-2" aria-label={'Step ' + (step + 1) + ' of 3'}>{[0,1,2].map(index => <div key={index} className={'h-1.5 flex-1 rounded-full ' + (index <= step ? 'bg-cyan-400' : 'bg-slate-700')} />)}<span className="ml-2 text-xs text-slate-400">Step {step + 1} of 3</span></div>}
    <section className="rounded-2xl border border-slate-700 bg-slate-800 p-5 shadow-xl sm:p-7">
      {step === 0 && <div className="mb-6"><p className="mb-3 text-sm font-medium text-slate-300">Choose scan depth</p><div className="grid gap-3 sm:grid-cols-2"><button type="button" aria-pressed={scanDepth === 'quick'} onClick={() => setScanDepth('quick')} className={'rounded-xl border p-4 text-left ' + (scanDepth === 'quick' ? 'border-cyan-400 bg-cyan-400/10' : 'border-slate-600 bg-slate-900 hover:border-slate-400')}><span className="block font-semibold text-white">Quick scan</span><span className="mt-1 block text-sm text-slate-400">Fast historical strategy test with a simple results summary.</span></button><button type="button" aria-pressed={scanDepth === 'deep'} onClick={() => setScanDepth('deep')} className={'rounded-xl border p-4 text-left ' + (scanDepth === 'deep' ? 'border-cyan-400 bg-cyan-400/10' : 'border-slate-600 bg-slate-900 hover:border-slate-400')}><span className="block font-semibold text-white">Deep scan</span><span className="mt-1 block text-sm text-slate-400">Checks data quality, trading costs, market hours, and out-of-sample results.</span></button></div></div>}
      {loading ? <div className="py-12 text-center" role="status"><LoaderCircle className="mx-auto h-10 w-10 animate-spin text-cyan-300" /><h2 className="mt-5 text-xl font-semibold text-white">Running your test…</h2><p className="mt-2 text-slate-400">Getting market history, checking the strategy, and preparing your results.</p><p className="mt-5 text-sm text-slate-500">You can wait here. This does not place a trade.</p></div>
      : finished && result ? <div><div className="flex items-center gap-3"><div className="rounded-full bg-emerald-500/15 p-2 text-emerald-300"><Check /></div><div><p className="text-sm text-emerald-300">Test complete</p><h2 className="text-2xl font-bold text-white">{result.symbol} · {timeframe}</h2></div></div><p className="mt-3 text-slate-400">{broker === 'mt5' ? 'MT5' : 'Deriv'} · {strategySummary} · past {days} days</p><div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4"><Metric label="Profit / loss" value={(result.total_pnl >= 0 ? '+' : '') + Number(result.total_pnl || 0).toFixed(2)} positive={result.total_pnl >= 0} /><Metric label="Winning trades" value={(Number(result.win_rate || 0) * 100).toFixed(1) + '%'} /><Metric label="Number of trades" value={String(result.total_trades ?? 0)} /><Metric label="Largest drop" value={(Number(result.max_drawdown || 0) * 100).toFixed(1) + '%'} /></div><p className="mt-5 rounded-lg bg-slate-900 p-3 text-sm text-slate-400">This is a simulation using historical data. Past results don’t guarantee future results. No real trade was placed.</p><button onClick={startOver} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-3 font-semibold text-slate-950 hover:bg-cyan-300"><RotateCcw size={18} /> Run another test</button></div>
      : <>
        {step === 0 && <><p className="text-sm text-cyan-300">1 · Choose a broker and market</p><h2 className="mt-2 text-2xl font-semibold text-white">Where should we look?</h2><p className="mt-2 text-slate-400">Choose the broker first. We’ll show only instruments available from that source.</p><label className="mt-6 block text-sm text-slate-300">Broker or data source<select value={broker} onChange={event => changeBroker(event.target.value as Broker)} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"><option value="deriv">Deriv · public history</option><option value="mt5">MetaTrader 5 · connected broker</option></select></label><label className="mt-4 block text-sm text-slate-300">Search for a pair or instrument<input aria-label="Search for a pair or instrument" placeholder="Try GER40, EURUSD, gold..." value={assetSearch} onChange={event => { const query = event.target.value; setAssetSearch(query); if (query.trim()) setAssetGroup('All groups'); const term = query.trim().toLocaleLowerCase(); const matches = assets.filter(item => !term || (item.name + ' ' + item.description).toLocaleLowerCase().includes(term)); if (matches.length) setSymbol(matches[0].name) }} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white placeholder:text-slate-500" /></label>{broker === 'mt5' && <div className="mt-4 rounded-xl border border-slate-700 bg-slate-900 p-4"><p className="text-sm text-slate-300">{brokerConnected ? 'Connected. Instruments are loaded from your broker.' : brokerMessage || 'Connect MT5 to load broker instruments.'}</p>{!brokerConnected && <button type="button" disabled={brokerLoading} onClick={connectMt5} className="mt-3 rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">{brokerLoading ? 'Connecting…' : 'Connect MT5 and load instruments'}</button>}</div>}<div className="mt-4 grid grid-cols-2 gap-3"><label className="text-sm text-slate-300">Asset group<select value={assetGroup} onChange={event => { setAssetGroup(event.target.value); setAssetSearch(''); const next = assets.filter(item => event.target.value === 'All groups' || item.group === event.target.value); if (next.length) setSymbol(next[0].name) }} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white">{GROUPS.map(group => <option key={group}>{group}</option>)}</select></label><label className="text-sm text-slate-300">Market<select value={symbol} onChange={event => setSymbol(event.target.value)} disabled={!filteredAssets.length || (broker === 'mt5' && !brokerConnected)} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white">{filteredAssets.map(asset => <option key={asset.name} value={asset.name}>{asset.name}{asset.description ? ' · ' + asset.description : ''}</option>)}</select></label></div>{broker === 'mt5' && brokerConnected && mt5Assets.find(item => item.name === symbol)?.eligible === false && <p className="mt-2 text-xs text-amber-300">This broker instrument is not eligible for demo execution, but its historical data can still be tested.</p>}{brokerMessage && broker === 'mt5' && brokerConnected && <p className="mt-2 text-xs text-amber-300">{brokerMessage}</p>}{!filteredAssets.length && <p className="mt-2 text-sm text-slate-400">{broker === 'mt5' ? (brokerConnected ? 'No instruments in this group are available from the connected broker.' : 'Connect MT5 to see instruments in this group.') : 'No instruments are available in this group for Deriv.'}</p>}<div className="mt-4 grid grid-cols-2 gap-3"><label className="text-sm text-slate-300">Chart interval<select value={timeframe} onChange={event => setTimeframe(event.target.value)} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white">{['M1','M5','M15','M30','H1','H4'].map(tf => <option key={tf}>{tf}</option>)}</select></label><label className="text-sm text-slate-300">History to check<select value={days} onChange={event => setDays(Number(event.target.value))} className="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-white"><option value={7}>Past 7 days</option><option value={30}>Past 30 days</option><option value={90}>Past 90 days</option></select></label></div></>}
        {step === 1 && <><p className="text-sm text-cyan-300">2 · Active strategies</p><h2 className="mt-2 text-2xl font-semibold text-white">Choose what to include</h2><p className="mt-2 text-slate-400">Select any combination, or use Select all to include every strategy.</p><div className="mt-5 flex flex-wrap gap-3"><button type="button" onClick={() => setStrategies(Object.fromEntries(STRATEGIES.map(item => [item.id, true])))} className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600">Select all</button><button type="button" onClick={() => setStrategies(Object.fromEntries(STRATEGIES.map(item => [item.id, false])))} className="rounded-lg bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-600">Clear all</button><span className="self-center text-sm text-slate-400">{selectedStrategies.length} of {STRATEGIES.length} selected</span></div><div className="mt-4 max-h-[52vh] space-y-2 overflow-y-auto pr-1">{STRATEGIES.map(item => <button key={item.id} onClick={() => setStrategies(previous => ({ ...previous, [item.id]: !previous[item.id] }))} aria-pressed={strategies[item.id]} className={'flex w-full items-center justify-between rounded-xl border p-3 text-left transition ' + (strategies[item.id] ? 'border-cyan-500/50 bg-cyan-500/10 text-cyan-300' : 'border-slate-600 bg-slate-900 text-slate-400 hover:border-slate-500')}><span><span className="block font-semibold">{item.name}</span><span className="mt-1 block text-xs opacity-70">{item.detail}</span></span><span aria-hidden="true" className="ml-3 text-lg">{strategies[item.id] ? '✓' : '×'}</span></button>)}</div></>}
        {step === 2 && <><p className="text-sm text-cyan-300">3 · Ready to run</p><h2 className="mt-2 text-2xl font-semibold text-white">Here’s your test</h2><p className="mt-2 text-slate-400">Check the choices, then press the button. You can change them at any time.</p><dl className="mt-6 divide-y divide-slate-700 rounded-xl bg-slate-900 px-4"><Summary label="Broker" value={broker === 'mt5' ? 'MetaTrader 5' : 'Deriv'} /><Summary label="Market" value={symbol} /><Summary label="Interval" value={timeframe} /><Summary label="History" value={'Past ' + days + ' days'} /><Summary label="Strategies" value={strategySummary} /></dl>{!canRunResearch && <p className="mt-4 text-sm text-amber-300">Your account can view results but cannot run a new test.</p>}</>}
        {error && <p role="alert" className="mt-5 rounded-lg bg-red-950/40 p-3 text-sm text-red-200">{error}</p>}
        <div className="mt-7 flex justify-between gap-3"><button onClick={() => step === 0 ? startOver() : setStep(step - 1)} className="inline-flex items-center gap-2 rounded-lg px-4 py-3 text-slate-300 hover:bg-slate-700"><ArrowLeft size={18} />{step === 0 ? 'Start over' : 'Back'}</button>{step < 2 ? <button onClick={() => step === 0 && scanDepth === 'deep' ? navigate('/analyze', { state: { source: broker, symbol, symbols: [symbol], timeframe, days, scanDepth: 'deep' } }) : setStep(step + 1)} disabled={(step === 0 && (!filteredAssets.length || brokerLoading || (broker === 'mt5' && !brokerConnected))) || (step === 1 && selectedStrategies.length === 0)} className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-3 font-semibold text-slate-950 hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50">{step === 0 && scanDepth === 'deep' ? 'Continue to deep scan' : 'Continue'}<ArrowRight size={18} /></button> : <button onClick={runTest} disabled={!canRunResearch} className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-3 font-semibold text-slate-950 hover:bg-cyan-300 disabled:cursor-not-allowed disabled:opacity-50"><Play size={18} />Run test</button>}</div>
      </>}
    </section>
    {!finished && <p className="mt-4 text-center text-xs text-slate-500">Historical simulation only · No real trades</p>}
  </div></div>
}

function Metric({ label, value, positive }: { label: string; value: string; positive?: boolean }) { return <div className="rounded-xl bg-slate-900 p-4"><p className="text-xs text-slate-400">{label}</p><p className={'mt-2 text-xl font-bold ' + (positive === undefined ? 'text-white' : positive ? 'text-emerald-300' : 'text-rose-300')}>{value}</p></div> }
function Summary({ label, value }: { label: string; value: string }) { return <div className="flex justify-between gap-4 py-4 text-sm"><dt className="text-slate-400">{label}</dt><dd className="font-medium text-white">{value}</dd></div> }
