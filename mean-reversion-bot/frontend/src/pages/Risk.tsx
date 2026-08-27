import { useEffect, useState, useCallback } from 'react'
import { 
  Shield, AlertTriangle, Activity, 
  ArrowUpRight, ArrowDownRight, Info,
  RefreshCw, RotateCcw
} from 'lucide-react'
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, 
  Tooltip, ResponsiveContainer, YAxisProps
} from 'recharts'
import { fetchRisk, resetCircuitBreaker, type RiskDashboard } from '../api/client'
import { format } from 'date-fns'

export default function Risk() {
  const [data, setData] = useState<RiskDashboard | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [resetting, setResetting] = useState(false)

  const loadRisk = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchRisk()
      setData(res)
      setError(null)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRisk()
  }, [loadRisk])

  const handleResetCB = async () => {
    if (!confirm('Are you sure you want to manually reset the circuit breaker?')) return
    setResetting(true)
    try {
      await resetCircuitBreaker()
      await loadRisk()
    } catch (err: any) {
      alert('Reset failed: ' + err.message)
    } finally {
      setResetting(false)
    }
  }

  if (loading && !data) {
    return <div className="p-12 text-center text-slate-500">Loading risk metrics...</div>
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Risk Dashboard</h1>
          <p className="text-slate-400 text-sm">Monitor exposure and circuit breaker status</p>
        </div>
        <button 
            onClick={() => loadRisk()}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
        >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <StatCard 
            label="Current Balance" 
            value={data?.current_balance ? `$${data.current_balance.toFixed(2)}` : '—'} 
        />
        <StatCard 
            label="Daily PnL" 
            value={data?.daily_pnl ? `$${data.daily_pnl.toFixed(2)}` : '—'} 
            sub={data?.daily_pnl ? `${data.daily_pnl >= 0 ? '+' : ''}${data.daily_pnl.toFixed(2)}` : undefined}
            accent={data?.daily_pnl !== null && data?.daily_pnl !== undefined && data.daily_pnl < 0 ? 'text-red-400' : 'text-emerald-400'}
        />
        <StatCard 
            label="Daily Drawdown" 
            value={`${data?.daily_drawdown_pct.toFixed(2)}%`} 
            accent={data?.daily_drawdown_pct && data.daily_drawdown_pct > 2 ? 'text-red-400' : 'text-slate-200'}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-slate-800 border border-slate-700 rounded-xl p-6">
          <h3 className="text-white font-bold mb-6 flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            Equity Curve (Last 48 Points)
          </h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data?.equity_curve || []}>
                <defs>
                  <linearGradient id="colorBalance" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#06b6d4" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                <XAxis 
                  dataKey="ts" 
                  stroke="#64748b" 
                  fontSize={10}
                  tickFormatter={(t) => format(new Date(t), 'HH:mm')}
                />
                <YAxis 
                  stroke="#64748b" 
                  fontSize={10} 
                  domain={['auto', 'auto']}
                  tickFormatter={(v) => `$${v}`}
                />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
                  labelStyle={{ color: '#94a3b8', fontSize: '10px', marginBottom: '4px' }}
                  itemStyle={{ color: '#fff', fontSize: '12px', fontWeight: 'bold' }}
                  labelFormatter={(t) => format(new Date(t), 'MMM dd, HH:mm')}
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

        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 flex flex-col">
          <div className="flex items-center justify-between mb-6">
            <h3 className="text-white font-bold flex items-center gap-2">
              <Shield className="w-4 h-4 text-emerald-400" />
              Circuit Breaker
            </h3>
            <button 
                onClick={handleResetCB}
                disabled={resetting}
                className="text-[10px] uppercase font-bold text-cyan-400 hover:text-cyan-300 transition-colors flex items-center gap-1"
            >
                <RotateCcw className={`w-3 h-3 ${resetting ? 'animate-spin' : ''}`} />
                Reset
            </button>
          </div>
          
          <div className="flex-1 space-y-4">
            {data?.circuit_breaker_history.length === 0 ? (
                <div className="text-center py-12 text-slate-500 text-sm italic">
                    No circuit breaker events logged
                </div>
            ) : (
                data?.circuit_breaker_history.map((event, i) => (
                    <div key={i} className="flex gap-3">
                        <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${
                            event.severity === 'critical' ? 'bg-red-500' : 
                            event.severity === 'warning' ? 'bg-yellow-500' : 'bg-emerald-500'
                        }`} />
                        <div>
                            <div className="text-xs font-bold text-white uppercase tracking-tight">{event.event_type}</div>
                            <div className="text-[11px] text-slate-400 leading-relaxed mb-1">{event.message}</div>
                            <div className="text-[9px] text-slate-500">{format(new Date(event.ts), 'MMM dd, HH:mm:ss')}</div>
                        </div>
                    </div>
                ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StatCard({ label, value, sub, accent }: { label: string, value: string, sub?: string, accent?: string }) {
    return (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-6">
            <div className="text-xs text-slate-500 uppercase font-bold tracking-wider mb-2">{label}</div>
            <div className={`text-3xl font-bold ${accent || 'text-white'}`}>{value}</div>
            {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
        </div>
    )
}
