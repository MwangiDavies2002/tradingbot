import React, { useState, useEffect } from 'react';
import { 
  Play, FlaskConical, Check, X, Info, 
  TrendingUp, BarChart3, History, Layers, Upload, ChevronDown
} from 'lucide-react';
import { api } from '../api/client';
import MT5Panel from '../components/MT5Panel';
import TradingViewPanel from '../components/TradingViewPanel';
import { DEFAULT_SELECTION, TV_SUPPORTED, TV_URL } from '../tradingview/strategy';
import { CandlestickChart, type Candle } from '../components/CandlestickChart';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, 
  Tooltip, ResponsiveContainer, AreaChart, Area
} from 'recharts';

const STRATEGIES = [
  { id: 'use_zscore', label: 'Z-Score', description: 'Price deviation from rolling mean' },
  { id: 'use_rsi', label: 'RSI', description: 'Relative Strength Index momentum' },
  { id: 'use_bb', label: 'Bollinger Bands', description: 'Volatility envelope breach' },
  { id: 'use_vwap', label: 'VWAP', description: 'Volume Weighted Average Price' },
  { id: 'use_stoch', label: 'Stochastic', description: 'Momentum exhaustion' },
  { id: 'use_lsl', label: 'LSL Grab', description: 'Liquidity Sweep Levels' },
  { id: 'use_smc', label: 'SMC Structure', description: 'BOS/CHoCH & Order Blocks' },
  { id: 'use_volume', label: 'Volume Spike', description: 'Unusual volume activity' },
  { id: 'use_hurst', label: 'Hurst Regime', description: 'Mean-reversion vs Trending' },
];

const SYMBOLS = ['1HZ75V'];

export default function Backtest() {
  const [savedLab] = useState(() => {
    try { return JSON.parse(localStorage.getItem('v751s-strategy-lab-v2') || '{}') || {} } catch { return {} }
  });
  const [platform, setPlatform] = useState<'tradingview' | 'mt5'>('tradingview');
  const [selectedStrategies, setSelectedStrategies] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(STRATEGIES.map(s => [s.id, typeof savedLab.selection?.[s.id] === 'boolean' ? savedLab.selection[s.id] : DEFAULT_SELECTION[s.id]])));
  const [selectedSymbols, setSelectedSymbols] = useState<string[]>(['1HZ75V']);
  const [timeframe, setTimeframe] = useState(['M1', 'M5', 'M15', 'M30', 'H1', 'H4'].includes(savedLab.timeframe) ? savedLab.timeframe : 'M5');
  const [days, setDays] = useState(7);
  const [minConfluence, setMinConfluence] = useState(Number.isInteger(savedLab.threshold) && savedLab.threshold >= 1 && savedLab.threshold <= 20 ? savedLab.threshold : 3);
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<any[]>([]);
  const [recentRuns, setRecentRuns] = useState<any[]>([]);
  const [selectedRun, setSelectedRun] = useState<any | null>(null);
  const [expandedTrades, setExpandedTrades] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (platform === 'mt5') fetchRecentRuns();
  }, [platform]);

  useEffect(() => {
    try { localStorage.setItem('v751s-strategy-lab-v2', JSON.stringify({ selection: selectedStrategies, threshold: minConfluence, timeframe })) } catch { /* Download still works without browser storage. */ }
  }, [selectedStrategies, minConfluence, timeframe]);

  const fetchRecentRuns = async () => {
    try {
      const data = await api.get('/api/backtest/results') as any[];
      setRecentRuns(data);
    } catch (err) {
      console.error('Failed to fetch recent runs', err);
    }
  };

  const toggleStrategy = (id: string) => {
    setSelectedStrategies(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const toggleSymbol = (symbol: string) => {
    setSelectedSymbols(['1HZ75V']);
  };

  const runBacktest = async (csvText?: string) => {
    if (selectedSymbols.length === 0) return;
    setLoading(true);
    try {
      const payload = {
        data_source: 'mt5',
        symbols: selectedSymbols,
        timeframe,
        days,
        min_confluence: minConfluence,
        csv_data: csvText || null,
        ...selectedStrategies
      };
      const data = await api.post('/api/backtest/run', payload) as any[];
      setResults(data);
      setSelectedRun(null);
      await fetchRecentRuns();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      alert(`Backtest failed: ${message}`)
    } finally {
      setLoading(false);
    }
  };

  const handleCsvUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const csvText = await file.text();
      await runBacktest(csvText);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      alert(`CSV import failed: ${message}`);
    }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <FlaskConical className="text-cyan-400" />
            Strategy Lab
          </h1>
          <p className="text-slate-400 text-sm mt-1">
            Choose your own threshold — 1, 2, 3 or more — and test V75 1s on TradingView.
          </p>
        </div>
        {platform === 'mt5' && <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-slate-600 bg-slate-800 text-slate-200 hover:bg-slate-700 cursor-pointer">
            <Upload className="w-4 h-4" />
            Import CSV
            <input type="file" accept=".csv" className="hidden" onChange={handleCsvUpload} />
          </label>
          <button
            onClick={() => runBacktest()}
            disabled={loading || selectedSymbols.length === 0}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-lg font-semibold transition-all ${
              loading || selectedSymbols.length === 0
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-cyan-500 hover:bg-cyan-400 text-slate-900 shadow-lg shadow-cyan-500/20'
            }`}
          >
            {loading ? (
              <div className="w-5 h-5 border-2 border-slate-900 border-t-transparent rounded-full animate-spin" />
            ) : (
              <Play className="w-5 h-5 fill-current" />
            )}
            {loading ? 'Running Test...' : 'Run Combined Test'}
          </button>
        </div>}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">Platform <select aria-label="Platform" value={platform} onChange={e => setPlatform(e.target.value as 'tradingview' | 'mt5')} className="ml-2 bg-slate-800 border border-slate-600 rounded p-2">
          <option value="tradingview">TradingView</option><option value="mt5">MT5 / Python</option>
        </select></label>
        <label className="text-sm">Timeframe <select aria-label="Timeframe" value={timeframe} onChange={e => setTimeframe(e.target.value)} className="ml-2 bg-slate-800 border border-slate-600 rounded p-2">
          {['M1', 'M5', 'M15', 'M30', 'H1', 'H4'].map(tf => <option key={tf}>{tf}</option>)}
        </select></label>
        <span className="text-sm text-cyan-300">V75 1s only · {minConfluence} points required</span>
        <label className="text-sm">Minimum score <input aria-label="Minimum weighted score" type="number" min="1" max="20" step="1" value={minConfluence} onChange={e => { const value = Number(e.target.value); if (Number.isInteger(value) && value >= 1 && value <= 20) setMinConfluence(value) }} className="ml-2 w-20 bg-slate-800 border border-slate-600 rounded p-2" /></label>
        {[1, 2, 3, 6].map(score => <button key={score} onClick={() => setMinConfluence(score)} aria-pressed={minConfluence === score} className={`px-3 py-2 rounded ${minConfluence === score ? 'bg-cyan-600' : 'bg-slate-800'}`}>{score} points</button>)}
      </div>
      {platform === 'tradingview' ? <TradingViewPanel selection={selectedStrategies} threshold={minConfluence} timeframe={timeframe} /> :
      <MT5Panel selection={{ timeframe, min_confluence: minConfluence, ...selectedStrategies }}
        onLoad={config => {
          setTimeframe(config.timeframe); setMinConfluence(config.min_confluence);
          setSelectedStrategies(Object.fromEntries(STRATEGIES.map(s => [s.id, config[s.id]])));
        }} />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Sidebar: Controls */}
        <div className="space-y-6">
          {/* Strategies */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
              <Layers className="w-4 h-4 text-cyan-400" />
              Active Strategies
            </h2>
            <div className="grid grid-cols-1 gap-2">
              {STRATEGIES.map(s => (
                <button
                  key={s.id}
                  aria-pressed={selectedStrategies[s.id]}
                  disabled={platform === 'tradingview' && !TV_SUPPORTED.includes(s.id) && !selectedStrategies[s.id]}
                  onClick={() => toggleStrategy(s.id)}
                  className={`flex items-center justify-between px-3 py-2.5 rounded-lg border transition-all text-left group ${
                    selectedStrategies[s.id]
                      ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                      : 'bg-slate-900/50 border-slate-700 text-slate-500 hover:border-slate-600'
                  }`}
                >
                  <div>
                    <div className="text-sm font-medium">{s.label}</div>
                    {platform === 'tradingview' && !TV_SUPPORTED.includes(s.id) && <div className="text-xs text-amber-300">Python / MT5 only</div>}
                    <div className="text-[10px] opacity-60 leading-tight mt-0.5">{s.description}</div>
                  </div>
                  {selectedStrategies[s.id] ? (
                    <Check className="w-4 h-4 flex-shrink-0" />
                  ) : (
                    <X className="w-4 h-4 flex-shrink-0 opacity-20 group-hover:opacity-100" />
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Symbols */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 shadow-sm">
            <h2 className="text-sm font-bold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-cyan-400" />
              Assets to Include
            </h2>
            <div className="flex flex-wrap gap-2">
              {SYMBOLS.map(symbol => (
                <button
                  key={symbol}
                  onClick={() => toggleSymbol(symbol)}
                  className={`px-3 py-1.5 rounded-md text-xs font-semibold border transition-all ${
                    selectedSymbols.includes(symbol)
                      ? 'bg-cyan-500 border-cyan-500 text-slate-900'
                      : 'bg-slate-900/50 border-slate-700 text-slate-400 hover:border-slate-600'
                  }`}
                >
                  {symbol}
                </button>
              ))}
            </div>
          </div>

          {/* Parameters */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 shadow-sm space-y-4">
            <h2 className="text-sm font-bold text-slate-300 uppercase tracking-wider mb-2">Parameters</h2>
            <div>
              <label className="text-xs text-slate-500 block mb-1.5">Lookback (Days)</label>
              <select 
                value={days} 
                onChange={e => setDays(Number(e.target.value))}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 outline-none focus:border-cyan-500"
              >
                <option value={1}>1 Day</option>
                <option value={7}>7 Days</option>
                <option value={30}>30 Days</option>
                <option value={90}>90 Days</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-500 block mb-1.5">Min. Confluence Score ({minConfluence})</label>
              <input 
                type="range" min="1" max="20" step="1"
                value={minConfluence}
                onChange={e => setMinConfluence(Number(e.target.value))}
                className="w-full accent-cyan-500"
              />
            </div>
          </div>
        </div>

        {/* Main Result Area */}
        <div className="lg:col-span-2 space-y-6">
          {platform === 'tradingview' ? (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 space-y-3">
              <h3 className="text-lg font-semibold">Your selection: {minConfluence} weighted points</h3>
              <p className="text-slate-300">{STRATEGIES.filter(s => selectedStrategies[s.id]).map(s => s.label).join(', ') || 'Select an indicator to begin.'}</p>
              <p className="text-sm text-slate-400">There is no required six-point minimum. A one-point Bollinger setup is allowed. Lower thresholds admit more setups; they do not guarantee profitable trades.</p>
              <p className="text-sm text-slate-400">Download or copy your Pine strategy above. Run the test in TradingView, where the script can access this instrument's price history and draw its simulated trades.</p>
              <a className="inline-block text-cyan-300" href={TV_URL} target="_blank" rel="noopener noreferrer">Open TradingView chart and Strategy Tester ↗</a>
            </div>
          ) : results.length > 0 ? (
            results.map((res, idx) => (
              <div key={idx} className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden shadow-sm">
                <div className="p-5 border-b border-slate-700 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-cyan-500/20 flex items-center justify-center">
                      <BarChart3 className="w-6 h-6 text-cyan-400" />
                    </div>
                    <div>
                      <h3 className="font-bold text-white text-lg">{res.symbol} Analysis</h3>
                      <p className="text-xs text-slate-500">Backtest Period: {days} days · Timeframe: {timeframe}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-slate-500 uppercase tracking-widest font-bold">Sharpe Ratio</div>
                    <div className={`text-2xl font-black ${res.sharpe_ratio > 1 ? 'text-green-400' : 'text-yellow-400'}`}>
                      {res.sharpe_ratio.toFixed(2)}
                    </div>
                  </div>
                </div>

                {/* Stats Grid */}
                <div className="grid grid-cols-2 md:grid-cols-4 border-b border-slate-700">
                  <div className="p-4 border-r border-slate-700">
                    <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Total P&L</div>
                    <div className={`text-lg font-bold ${res.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {res.total_pnl >= 0 ? '+' : ''}{res.total_pnl.toFixed(2)} ({res.total_pnl_pct.toFixed(1)}%)
                    </div>
                  </div>
                  <div className="p-4 border-r border-slate-700">
                    <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Win Rate</div>
                    <div className="text-lg font-bold text-white">{(res.win_rate * 100).toFixed(1)}%</div>
                  </div>
                  <div className="p-4 border-r border-slate-700">
                    <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Trades</div>
                    <div className="text-lg font-bold text-white">{res.total_trades}</div>
                  </div>
                  <div className="p-4">
                    <div className="text-[10px] text-slate-500 uppercase font-bold mb-1">Max DD</div>
                    <div className="text-lg font-bold text-red-400">{(res.max_drawdown * 100).toFixed(1)}%</div>
                  </div>
                </div>

                {/* Chart Area */}
                <div className="h-64 p-5">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={res.equity_curve}>
                      <defs>
                        <linearGradient id="colorBalance" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3}/>
                          <stop offset="95%" stopColor="#06b6d4" stopOpacity={0}/>
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                      <XAxis dataKey="ts" hide />
                      <YAxis 
                        hide 
                        domain={['dataMin - 100', 'dataMax + 100']}
                      />
                      <Tooltip 
                        contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                        itemStyle={{ color: '#22d3ee' }}
                      />
                      <Area 
                        type="monotone" 
                        dataKey="balance" 
                        stroke="#06b6d4" 
                        fillOpacity={1} 
                        fill="url(#colorBalance)" 
                        strokeWidth={2}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ))
          ) : (
            <div className="bg-slate-800/50 border-2 border-dashed border-slate-700 rounded-2xl flex flex-col items-center justify-center p-20 text-center">
              <FlaskConical className="w-16 h-16 text-slate-600 mb-4" />
              <h3 className="text-xl font-bold text-slate-400">Ready to Experiment</h3>
              <p className="text-slate-500 max-w-sm mt-2">
                Select your strategies and pairs on the left, then run a combined test to see the performance report.
              </p>
            </div>
          )}

          {/* Recent Runs */}
          <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden shadow-sm">
            <div className="p-4 border-b border-slate-700 flex items-center gap-2">
              <History className="w-4 h-4 text-slate-400" />
              <h3 className="text-sm font-bold text-slate-300 uppercase tracking-wider">Recent Experiments</h3>
            </div>
            <div className="divide-y divide-slate-700">
              {recentRuns.length > 0 ? (
                recentRuns.map((run, i) => (
                  <button
                    key={i}
                    onClick={() => setSelectedRun(run)}
                    className={`w-full px-5 py-3 flex items-center justify-between hover:bg-slate-700/30 transition-colors text-left ${selectedRun?.run_id === run.run_id ? 'bg-cyan-500/10' : ''}`}
                  >
                    <div className="flex items-center gap-4">
                      <span className="text-xs font-mono text-slate-500">#{run.run_id}</span>
                      <div>
                        <div className="text-sm font-bold text-white">{run.symbol}</div>
                        <div className="text-[10px] text-slate-500">{new Date(run.run_at).toLocaleString()}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-6">
                      <div className="text-right">
                        <div className="text-[10px] text-slate-500 uppercase font-bold">Sharpe</div>
                        <div className="text-sm font-bold text-cyan-400">{run.sharpe_ratio?.toFixed(2)}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-[10px] text-slate-500 uppercase font-bold">P&L</div>
                        <div className={`text-sm font-bold ${run.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                          {run.total_pnl >= 0 ? '+' : ''}{run.total_pnl?.toFixed(1)}%
                        </div>
                      </div>
                    </div>
                  </button>
                ))
              ) : (
                <div className="p-8 text-center text-slate-500 text-sm italic">No recent experiments found.</div>
              )}
            </div>
          </div>

          {selectedRun && (
            <div className="bg-slate-800 border border-slate-700 rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500">Selected Experiment</div>
                  <h3 className="text-lg font-bold text-white">{selectedRun.symbol} · {selectedRun.timeframe}</h3>
                </div>
                <div className="text-right">
                  <div className="text-[10px] text-slate-500 uppercase font-bold">Sharpe</div>
                  <div className="text-xl font-black text-cyan-400">{Number(selectedRun.sharpe_ratio || 0).toFixed(2)}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                <div className="bg-slate-900 border border-slate-700 rounded-lg p-3"><div className="text-slate-500">P&L</div><div className={`font-bold ${selectedRun.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>{selectedRun.total_pnl >= 0 ? '+' : ''}{Number(selectedRun.total_pnl || 0).toFixed(2)}</div></div>
                <div className="bg-slate-900 border border-slate-700 rounded-lg p-3"><div className="text-slate-500">Win rate</div><div className="font-bold text-white">{Number(selectedRun.win_rate || 0).toFixed(1)}%</div></div>
                <div className="bg-slate-900 border border-slate-700 rounded-lg p-3"><div className="text-slate-500">Trades</div><div className="font-bold text-white">{selectedRun.total_trades}</div></div>
                <div className="bg-slate-900 border border-slate-700 rounded-lg p-3"><div className="text-slate-500">Max DD</div><div className="font-bold text-red-400">{Number(selectedRun.max_drawdown || 0).toFixed(1)}%</div></div>
              </div>
              {selectedRun.candles && selectedRun.candles.length > 0 && (
                <div className="bg-slate-900 border border-slate-700 rounded-lg p-4">
                  <h4 className="text-sm font-bold text-white mb-3 flex items-center gap-2"><BarChart3 className="w-4 h-4 text-cyan-400" /> Price Action</h4>
                  <CandlestickChart candles={selectedRun.candles as Candle[]} width={750} height={250} />
                </div>
              )}
              {selectedRun.trades && selectedRun.trades.length > 0 && (
                <div className="bg-slate-900 border border-slate-700 rounded-lg overflow-hidden">
                  <div className="p-4 border-b border-slate-700"><h4 className="text-sm font-bold text-white">Trades ({selectedRun.trades.length})</h4></div>
                  <div className="divide-y divide-slate-700">
                    {selectedRun.trades.map((trade: any, idx: number) => (
                      <div key={idx} className="p-4">
                        <button onClick={() => setExpandedTrades(prev => ({ ...prev, [idx]: !prev[idx] }))} className="w-full flex items-center justify-between hover:text-cyan-400 transition-colors text-left">
                          <div className="flex items-center gap-3">
                            <div className={`px-2 py-1 rounded text-xs font-bold ${trade.direction === 'buy' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>{trade.direction.toUpperCase()}</div>
                            <div><div className="text-sm font-mono">{trade.id.slice(0, 8)}</div><div className="text-xs text-slate-500">{trade.reason || 'manual'}</div></div>
                          </div>
                          <div className="flex items-center gap-6">
                            <div className="text-right"><div className={`text-sm font-bold ${(trade.pnl || 0) >= 0 ? 'text-green-400' : 'text-red-400'}`}>{(trade.pnl || 0) >= 0 ? '+' : ''}{trade.pnl?.toFixed(2)}</div><div className="text-xs text-slate-500">{trade.pnl_pct?.toFixed(1)}%</div></div>
                            <ChevronDown className={`w-4 h-4 transition-transform ${expandedTrades[idx] ? 'rotate-180' : ''}`} />
                          </div>
                        </button>
                        {expandedTrades[idx] && (<div className="mt-3 pt-3 border-t border-slate-600 text-xs grid grid-cols-2 gap-2"><div><span className="text-slate-500">Entry:</span> <span className="text-white font-mono">{trade.entry?.toFixed(4)}</span></div><div><span className="text-slate-500">Exit:</span> <span className="text-white font-mono">{trade.exit?.toFixed(4)}</span></div></div>)}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
