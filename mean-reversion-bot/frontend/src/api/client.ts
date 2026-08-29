/**
 * api/client.ts
 * ─────────────────────────────────────────────────────────────────────────────
 * Typed API client for all backend endpoints.
 * Import individual functions — they handle auth headers and error throwing.
 *
 * Usage:
 *   import { fetchTrades, fetchRisk, fetchBotStatus } from '@/api/client'
 *   const { trades } = await fetchTrades({ symbol: 'R_75', page: 1 })
 * ─────────────────────────────────────────────────────────────────────────────
 */

const BASE = (import.meta as any).env?.VITE_API_URL ?? ''

// ── Exported API Client Object ────────────────────────────────────────────────
export const api = {
  get: (path: string) => apiFetch(path),
  post: (path: string, body: any) => apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }),
  put: (path: string, body: any) => apiFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }),
  delete: (path: string) => apiFetch(path, { method: 'DELETE' })
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Trade {
  trade_id:        string
  contract_id:     number | null
  symbol:          string
  timeframe:       string
  direction:       'buy' | 'sell'
  contract_type:   string
  status:          'pending' | 'open' | 'closed' | 'cancelled'
  entry_price:     number
  exit_price:      number | null
  stop_loss:       number
  take_profit:     number
  stake:           number
  pnl:             number | null
  pnl_pct:         number | null
  confluence_score: number
  reason_code:     string
  close_reason:    string | null
  opened_at:       string
  closed_at:       string | null
  // Full detail fields
  breakdown?:      Record<string, number>
  z_score?:        number | null
  rsi_value?:      number | null
  hurst_value?:    number | null
  lsl_wick_ratio?: number | null
}

export interface TradeStats {
  total_trades:    number
  winning_trades:  number
  losing_trades:   number
  win_rate:        number
  total_pnl:       number
  profit_factor:   number
  avg_rr:          number
  sharpe_ratio?:   number
  close_reasons:   Record<string, number>
}

export interface Signal {
  id:           number
  symbol:       string
  timeframe:    string
  direction:    'buy' | 'sell' | null
  score:        number
  fired:        boolean
  reason:       string
  evaluated_at: string
  eval_ms:      number | null
  indicators: {
    z_score:     number | null
    rsi:         number | null
    bb_position: string | null
    vwap_dev:    number | null
    stoch_k:     number | null
    hurst:       number | null
    lsl_grab:    boolean
    bos_choch:   boolean
    order_block: boolean
  }
}

export interface BotStatus {
  bot_running: boolean
  circuit_breaker: {
    state:        string
    last_trigger: string | null
    triggered_at: string | null
  }
  equity: {
    balance:     number | null
    daily_pnl:   number | null
    open_trades: number
  }
  timestamp: string
}

export interface RiskDashboard {
  current_balance:      number | null
  daily_pnl:            number | null
  daily_drawdown_pct:   number
  equity_curve: Array<{ ts: string; balance: number; daily_pnl: number | null }>
  circuit_breaker_history: Array<{
    event_type: string; severity: string; message: string; ts: string
  }>
}

export interface EquityPoint { ts: string; balance: number; open_equity: number | null }

// ── Core fetch helper ─────────────────────────────────────────────────────────

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('access_token')
  const res   = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

// ── Trades ────────────────────────────────────────────────────────────────────

export async function fetchTrades(params?: {
  symbol?:    string
  direction?: string
  status?:    string
  page?:      number
  page_size?: number
  min_score?: number
}): Promise<{ total: number; page: number; pages: number; trades: Trade[] }> {
  const q = new URLSearchParams()
  if (params?.symbol)    q.set('symbol',    params.symbol)
  if (params?.direction) q.set('direction', params.direction)
  if (params?.status)    q.set('status',    params.status)
  if (params?.page)      q.set('page',      String(params.page))
  if (params?.page_size) q.set('page_size', String(params.page_size))
  if (params?.min_score) q.set('min_score', String(params.min_score))
  return apiFetch(`/api/trades?${q}`)
}

export async function fetchTrade(tradeId: string): Promise<Trade> {
  return apiFetch(`/api/trades/${tradeId}`)
}

export async function fetchTradeStats(params?: {
  symbol?: string
}): Promise<{ stats: TradeStats }> {
  const q = new URLSearchParams()
  if (params?.symbol) q.set('symbol', params.symbol)
  return apiFetch(`/api/trades/stats?${q}`)
}

// ── Signals ───────────────────────────────────────────────────────────────────

export async function fetchSignals(params?: {
  symbol?:    string
  fired?:     boolean
  min_score?: number
  limit?:     number
}): Promise<{ count: number; signals: Signal[] }> {
  const q = new URLSearchParams()
  if (params?.symbol    != null) q.set('symbol',    params.symbol)
  if (params?.fired     != null) q.set('fired',     String(params.fired))
  if (params?.min_score != null) q.set('min_score', String(params.min_score))
  if (params?.limit     != null) q.set('limit',     String(params.limit))
  return apiFetch(`/api/signals?${q}`)
}

// ── Bot Control ───────────────────────────────────────────────────────────────

export async function fetchBotStatus(): Promise<BotStatus> {
  return apiFetch('/api/bot/status')
}

export async function startBot(): Promise<{ status: string }> {
  return apiFetch('/api/bot/start', { method: 'POST' })
}

export async function stopBot(): Promise<{ status: string }> {
  return apiFetch('/api/bot/stop', { method: 'POST' })
}

export async function resetCircuitBreaker(): Promise<{ status: string }> {
  return apiFetch('/api/bot/circuit-breaker/reset', { method: 'POST' })
}

// ── Risk ──────────────────────────────────────────────────────────────────────

export async function fetchRisk(): Promise<RiskDashboard> {
  return apiFetch('/api/risk')
}

export async function fetchEquityCurve(limit = 200): Promise<{
  count: number; points: EquityPoint[]
}> {
  return apiFetch(`/api/risk/equity?limit=${limit}`)
}

// ── Health ────────────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<{
  status: string; version: string; database: string; redis: string
}> {
  return apiFetch('/health')
}
