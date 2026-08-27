import { useEffect, useState, useCallback } from 'react'
import { TrendingUp, TrendingDown, RefreshCw, Filter, ExternalLink } from 'lucide-react'
import { fetchTrades, type Trade } from '../api/client'
import { format } from 'date-fns'

const pnlColor  = (v: number | null) => {
  if (v === null) return 'text-slate-400'
  return v >= 0 ? 'text-emerald-400' : 'text-red-400'
}
const dirBg = (d: string) => d === 'buy' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
const statusBg = (s: string) => {
  switch (s) {
    case 'open': return 'bg-cyan-500/20 text-cyan-400'
    case 'closed': return 'bg-slate-700 text-slate-300'
    case 'pending': return 'bg-yellow-500/20 text-yellow-400'
    default: return 'bg-slate-800 text-slate-500'
  }
}

export default function Trades() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string>('')

  const loadTrades = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchTrades({ 
        page, 
        page_size: 20,
        status: statusFilter || undefined
      })
      setTrades(res.trades)
      setTotal(res.total)
      setError(null)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [page, statusFilter])

  useEffect(() => {
    loadTrades()
  }, [loadTrades])

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Trade History</h1>
          <p className="text-slate-400 text-sm">Review all executed and pending orders</p>
        </div>
        <div className="flex items-center gap-3">
            <select 
                value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                className="bg-slate-800 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 outline-none focus:border-cyan-500"
            >
                <option value="">All Status</option>
                <option value="open">Open</option>
                <option value="closed">Closed</option>
                <option value="pending">Pending</option>
            </select>
            <button 
                onClick={() => loadTrades()}
                className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
                title="Refresh"
            >
                <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
            </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-center gap-3 text-red-400">
          <p className="text-sm">Failed to load trades: {error}</p>
        </div>
      )}

      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-900/50 text-slate-400 uppercase text-[10px] tracking-wider">
              <tr>
                <th className="px-6 py-4 font-semibold">Asset / Time</th>
                <th className="px-6 py-4 font-semibold">Direction</th>
                <th className="px-6 py-4 font-semibold">Entry / Exit</th>
                <th className="px-6 py-4 font-semibold">SL / TP</th>
                <th className="px-6 py-4 font-semibold">Stake</th>
                <th className="px-6 py-4 font-semibold">PnL</th>
                <th className="px-6 py-4 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {trades.length === 0 && !loading ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-slate-500">
                    No trades found
                  </td>
                </tr>
              ) : (
                trades.map((t) => (
                  <tr key={t.trade_id} className="hover:bg-slate-700/30 transition-colors">
                    <td className="px-6 py-4">
                      <div className="font-medium text-white">{t.symbol}</div>
                      <div className="text-xs text-slate-500">{format(new Date(t.opened_at), 'MMM dd, HH:mm')}</div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${dirBg(t.direction)}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-white font-mono">{t.entry_price.toFixed(2)}</div>
                      <div className="text-xs text-slate-500 font-mono">{t.exit_price?.toFixed(2) || '—'}</div>
                    </td>
                    <td className="px-6 py-4 text-xs font-mono">
                      <div className="text-red-400/80">{t.stop_loss.toFixed(2)}</div>
                      <div className="text-emerald-400/80">{t.take_profit.toFixed(2)}</div>
                    </td>
                    <td className="px-6 py-4 text-white font-medium">
                      ${t.stake.toFixed(2)}
                    </td>
                    <td className={`px-6 py-4 font-bold ${pnlColor(t.pnl)}`}>
                      {t.pnl !== null ? `${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(2)}` : '—'}
                      {t.pnl_pct !== null && (
                        <span className="text-[10px] ml-1 opacity-70">
                          ({t.pnl_pct.toFixed(1)}%)
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase ${statusBg(t.status)}`}>
                        {t.status}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {total > 0 && (
          <div className="flex items-center justify-between text-sm text-slate-400">
              <p>Showing {trades.length} of {total} trades</p>
              <div className="flex gap-2">
                  <button 
                    disabled={page === 1}
                    onClick={() => setPage(p => p - 1)}
                    className="px-3 py-1 bg-slate-800 border border-slate-700 rounded hover:bg-slate-700 disabled:opacity-50 transition-colors"
                  >
                      Prev
                  </button>
                  <button 
                    disabled={trades.length < 20}
                    onClick={() => setPage(p => p + 1)}
                    className="px-3 py-1 bg-slate-800 border border-slate-700 rounded hover:bg-slate-700 disabled:opacity-50 transition-colors"
                  >
                      Next
                  </button>
              </div>
          </div>
      )}
    </div>
  )
}
