/**
 * pages/Dashboard.tsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Main trading dashboard — real-time bot status, equity curve,
 * open positions, live signal feed, circuit breaker panel.
 *
 * Polls the API every 5s for updates. A production build would
 * upgrade this to a WebSocket connection (/ws/live).
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { useEffect, useState, useCallback } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from 'recharts'
import { format } from 'date-fns'
import {
  Activity, TrendingUp, TrendingDown, AlertTriangle,
  StopCircle, PlayCircle, RefreshCw, Zap, Shield,
} from 'lucide-react'
import {
  fetchBotStatus, fetchRisk, fetchSignals, fetchTrades,
  stopBot, startBot, resetCircuitBreaker,
  type BotStatus, type RiskDashboard, type Signal, type Trade,
} from '../api/client'

// ── Types ─────────────────────────────────────────────────────────────────────

interface DashState {
  status:   BotStatus | null
  risk:     RiskDashboard | null
  signals:  Signal[]
  trades:   Trade[]
  loading:  boolean
  error:    string | null
  lastRefresh: Date | null
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const pnlColor  = (v: number) => v >= 0 ? 'text-emerald-400' : 'text-red-400'
const dirColor  = (d: string) => d === 'buy' ? 'text-emerald-400' : 'text-red-400'
const dirBg     = (d: string) => d === 'buy' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
const scoreColor = (s: number) => s >= 9 ? 'text-yellow-400' : s >= 6 ? 'text-emerald-400' : 'text-slate-400'
const cbColor   = (state: string) => ({
  active:   'text-emerald-400 bg-emerald-500/10',
  paused:   'text-yellow-400 bg-yellow-500/10',
  halted:   'text-red-400 bg-red-500/10',
  cooldown: 'text-orange-400 bg-orange-500/10',
}[state] ?? 'text-slate-400 bg-slate-500/10')

function fmt(ts: string) {
  try { return format(new Date(ts), 'HH:mm:ss') } catch { return ts }
}

// ── Stat Card ─────────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent = false }: {
  label: string; value: string; sub?: string; accent?: boolean
}) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
      <p className="text-xs text-slate-400 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${accent ? 'text-cyan-400' : 'text-white'}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  )
}

// ── Circuit Breaker Badge ─────────────────────────────────────────────────────

function CBBadge({ state }: { state: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-semibold uppercase ${cbColor(state)}`}>
      {state}
    </span>
  )
}

// ── Main Dashboard ────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [state, setState] = useState<DashState>({
    status: null, risk: null, signals: [], trades: [],
    loading: true, error: null, lastRefresh: null,
  })
  const [actionLoading, setActionLoading] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [status, risk, sigRes, tradeRes] = await Promise.all([
        fetchBotStatus(),
        fetchRisk(),
        fetchSignals({ limit: 20, fired: true }),
        fetchTrades({ status: 'open', page_size: 10 }),
      ])
      setState(s => ({
        ...s, status, risk,
        signals: sigRes.signals,
        trades:  tradeRes.trades,
        loading: false, error: null,
        lastRefresh: new Date(),
      }))
    } catch (err: any) {
      setState(s => ({ ...s, loading: false, error: err.message }))
    }
  }, [])

  // Poll every 5s
  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5000)
    return () => clearInterval(id)
  }, [refresh])

  const handleStop = async () => {
    setActionLoading(true)
    try { await stopBot(); await refresh() }
    finally { setActionLoading(false) }
  }
  const handleStart = async () => {
    setActionLoading(true)
    try { await startBot(); await refresh() }
    finally { setActionLoading(false) }
  }
  const handleResetCB = async () => {
    if (!confirm('Reset circuit breaker? Only do this if you have reviewed the cause.')) return
    setActionLoading(true)
    try { await resetCircuitBreaker(); await refresh() }
    finally { setActionLoading(false) }
  }

  const { status, risk, signals, trades, loading, error, lastRefresh } = state
  const cbState    = status?.circuit_breaker.state ?? 'unknown'
  const balance    = status?.equity.balance ?? risk?.current_balance ?? null
  const dailyPnl   = status?.equity.daily_pnl ?? risk?.daily_pnl ?? null
  const openTrades = status?.equity.open_trades ?? 0
  const ddPct      = risk?.daily_drawdown_pct ?? 0
  const equityCurve = (risk?.equity_curve ?? []).map(p => ({
    time:    fmt(p.ts),
    balance: p.balance,
  }))

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <RefreshCw className="animate-spin text-cyan-400 w-8 h-8" />
    </div>
  )

  return (
    <div className="p-6 space-y-6">

      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Zap className="text-cyan-400 w-6 h-6" />
            Mean Reversion Bot
          </h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {lastRefresh ? `Updated ${format(lastRefresh, 'HH:mm:ss')}` : 'Loading...'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <CBBadge state={cbState} />
          {cbState === 'halted' && (
            <button
              onClick={handleResetCB}
              disabled={actionLoading}
              className="px-3 py-1.5 text-xs bg-orange-500/20 text-orange-400 border border-orange-500/30 rounded-lg hover:bg-orange-500/30 transition"
            >
              Reset CB
            </button>
          )}
          <button
            onClick={status?.bot_running ? handleStop : handleStart}
            disabled={actionLoading}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition
              ${status?.bot_running
                ? 'bg-red-500/20 text-red-400 border border-red-500/30 hover:bg-red-500/30'
                : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30'
              }`}
          >
            {status?.bot_running
              ? <><StopCircle className="w-4 h-4" /> Stop Bot</>
              : <><PlayCircle className="w-4 h-4" /> Start Bot</>
            }
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400 text-sm flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* ── Stats Row ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Account Balance"
          value={balance != null ? `$${balance.toFixed(2)}` : '—'}
          accent
        />
        <StatCard
          label="Daily P&L"
          value={dailyPnl != null ? `$${dailyPnl >= 0 ? '+' : ''}${dailyPnl.toFixed(2)}` : '—'}
          sub={`Daily drawdown: ${ddPct.toFixed(1)}%`}
        />
        <StatCard
          label="Open Positions"
          value={String(openTrades)}
          sub="Max 3 allowed"
        />
        <StatCard
          label="CB State"
          value={cbState.toUpperCase()}
          sub={status?.circuit_breaker.last_trigger?.replace(/_/g, ' ') ?? ''}
        />
      </div>

      {/* ── Equity Curve ───────────────────────────────────────── */}
      {equityCurve.length > 1 && (
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Activity className="w-4 h-4 text-cyan-400" />
            Equity Curve
          </h2>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={equityCurve} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <defs>
                <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#06b6d4" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis dataKey="time" tick={{ fill: '#475569', fontSize: 10 }} tickLine={false} />
              <YAxis tick={{ fill: '#475569', fontSize: 10 }} tickLine={false} axisLine={false}
                     tickFormatter={v => `$${v.toFixed(0)}`} width={55} />
              <Tooltip
                contentStyle={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8 }}
                labelStyle={{ color: '#94a3b8', fontSize: 11 }}
                formatter={(v: number) => [`$${v.toFixed(2)}`, 'Balance']}
              />
              <Area type="monotone" dataKey="balance" stroke="#06b6d4" strokeWidth={2}
                    fill="url(#eqGrad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Bottom Grid: Open Trades + Signal Feed ──────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Open Positions */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4">
            Open Positions
          </h2>
          {trades.length === 0
            ? <p className="text-slate-500 text-sm text-center py-6">No open positions</p>
            : (
              <div className="space-y-3">
                {trades.map(t => (
                  <div key={t.trade_id}
                       className="flex items-center justify-between bg-slate-700/50 rounded-lg px-4 py-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-bold px-2 py-0.5 rounded ${dirBg(t.direction)}`}>
                          {t.direction.toUpperCase()}
                        </span>
                        <span className="text-sm font-medium text-white">{t.symbol}</span>
                        <span className="text-xs text-slate-400">{t.timeframe}</span>
                      </div>
                      <div className="text-xs text-slate-400 mt-1">
                        Entry {t.entry_price.toFixed(5)} &nbsp;|&nbsp;
                        SL {t.stop_loss.toFixed(5)} &nbsp;|&nbsp;
                        TP {t.take_profit.toFixed(5)}
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-xs text-slate-400">Score</div>
                      <div className={`font-bold ${scoreColor(t.confluence_score)}`}>
                        {t.confluence_score}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )
          }
        </div>

        {/* Signal Feed */}
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-4 flex items-center gap-2">
            <Shield className="w-4 h-4 text-cyan-400" />
            Recent Fired Signals
          </h2>
          {signals.length === 0
            ? <p className="text-slate-500 text-sm text-center py-6">No signals yet</p>
            : (
              <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                {signals.map(s => (
                  <div key={s.id}
                       className="flex items-center justify-between bg-slate-700/40 rounded-lg px-3 py-2 text-xs">
                    <div className="flex items-center gap-2 min-w-0">
                      {s.direction === 'buy'
                        ? <TrendingUp  className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                        : <TrendingDown className="w-3 h-3 text-red-400 flex-shrink-0" />
                      }
                      <span className="font-medium text-white truncate">{s.symbol}</span>
                      <span className="text-slate-400">{s.timeframe}</span>
                    </div>
                    <div className="flex items-center gap-3 flex-shrink-0 ml-2">
                      <span className={`font-bold ${scoreColor(s.score)}`}>{s.score}pts</span>
                      <span className="text-slate-500">{fmt(s.evaluated_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )
          }
        </div>

      </div>
    </div>
  )
}
