import { useEffect, useState, useCallback } from 'react'
import { Activity, RefreshCw, Zap, TrendingUp, TrendingDown, Info } from 'lucide-react'
import { fetchSignals, type Signal } from '../api/client'
import { format } from 'date-fns'

const scoreColor = (s: number) => s >= 9 ? 'text-yellow-400' : s >= 6 ? 'text-emerald-400' : 'text-slate-400'
const dirColor = (d: string | null) => d === 'buy' ? 'text-emerald-400' : d === 'sell' ? 'text-red-400' : 'text-slate-400'

export default function Signals() {
  const [signals, setSignals] = useState<Signal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [firedOnly, setFiredOnly] = useState(false)

  const loadSignals = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchSignals({ 
        limit: 50,
        fired: firedOnly ? true : undefined
      })
      setSignals(res.signals)
      setError(null)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [firedOnly])

  useEffect(() => {
    loadSignals()
    const timer = setInterval(loadSignals, 30000) // Auto-refresh every 30s
    return () => clearInterval(timer)
  }, [loadSignals])

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Signal Feed</h1>
          <p className="text-slate-400 text-sm">Real-time market analysis and strategy evaluations</p>
        </div>
        <div className="flex items-center gap-3">
            <button 
                onClick={() => setFiredOnly(!firedOnly)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                    firedOnly ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'
                }`}
            >
                {firedOnly ? 'Fired Only' : 'All Evaluations'}
            </button>
            <button 
                onClick={() => loadSignals()}
                className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
            >
                <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 text-red-400 text-sm">
          Failed to load signals: {error}
        </div>
      )}

      <div className="grid gap-4">
        {signals.length === 0 && !loading ? (
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-12 text-center text-slate-500">
            No signals found
          </div>
        ) : (
          signals.map((s) => (
            <div key={s.id} className="bg-slate-800 border border-slate-700 rounded-xl p-4 hover:border-slate-600 transition-colors">
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${s.fired ? 'bg-cyan-500/20' : 'bg-slate-700/50'}`}>
                    <Activity className={`w-5 h-5 ${s.fired ? 'text-cyan-400' : 'text-slate-400'}`} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-white">{s.symbol}</span>
                      <span className="text-xs text-slate-500 uppercase">{s.timeframe}</span>
                    </div>
                    <div className="text-xs text-slate-400">
                      {format(new Date(s.evaluated_at), 'HH:mm:ss · MMM dd, yyyy')}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <div className={`text-xl font-mono font-bold ${scoreColor(s.score)}`}>
                    {s.score}/10
                  </div>
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider font-semibold">
                    Confluence
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-4">
                <Indicator 
                    label="Z-Score" 
                    value={s.indicators.z_score?.toFixed(2)} 
                    accent={Math.abs(s.indicators.z_score || 0) > 2} 
                />
                <Indicator 
                    label="RSI" 
                    value={s.indicators.rsi?.toFixed(0)} 
                    accent={(s.indicators.rsi || 50) > 70 || (s.indicators.rsi || 50) < 30} 
                />
                <Indicator 
                    label="Stoch K" 
                    value={s.indicators.stoch_k?.toFixed(0)} 
                />
                <Indicator 
                    label="Hurst" 
                    value={s.indicators.hurst?.toFixed(2)} 
                    accent={(s.indicators.hurst || 0.5) > 0.6} 
                />
                <Indicator 
                    label="LSL Grab" 
                    value={s.indicators.lsl_grab ? 'YES' : 'NO'} 
                    accent={s.indicators.lsl_grab} 
                />
                <Indicator 
                    label="BOS/CH" 
                    value={s.indicators.bos_choch ? 'YES' : 'NO'} 
                    accent={s.indicators.bos_choch} 
                />
                <Indicator 
                    label="OB" 
                    value={s.indicators.order_block ? 'YES' : 'NO'} 
                    accent={s.indicators.order_block} 
                />
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-slate-700/50">
                <div className="flex items-center gap-2 text-sm">
                   {s.direction && (
                       <span className={`flex items-center gap-1 font-bold uppercase text-xs ${dirColor(s.direction)}`}>
                           {s.direction === 'buy' ? <TrendingUp className="w-3 h-3"/> : <TrendingDown className="w-3 h-3"/>}
                           {s.direction}
                       </span>
                   )}
                   <span className="text-slate-400 text-xs italic">{s.reason}</span>
                </div>
                {s.fired && (
                    <span className="flex items-center gap-1 px-2 py-0.5 bg-emerald-500/10 text-emerald-400 text-[10px] font-bold uppercase rounded">
                        <Zap className="w-3 h-3" /> Fired
                    </span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function Indicator({ label, value, accent }: { label: string, value: string | undefined, accent?: boolean }) {
    return (
        <div className="bg-slate-900/30 rounded px-2 py-1 border border-slate-700/30">
            <div className="text-[9px] text-slate-500 uppercase font-bold truncate">{label}</div>
            <div className={`text-xs font-mono ${accent ? 'text-cyan-400' : 'text-slate-300'}`}>{value || '—'}</div>
        </div>
    )
}
