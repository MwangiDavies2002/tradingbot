/**
 * App.tsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Root app component: router, sidebar nav, dark layout shell.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import {
  LayoutDashboard, TrendingUp, Activity, Shield,
  Settings as SettingsIcon, FileText, Zap, FlaskConical
} from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import Signals from './pages/Signals'
import Risk from './pages/Risk'
import Settings from './pages/Settings'
import Logs from './pages/Logs'
import Backtest from './pages/Backtest'

const NAV = [
  { to: '/',         label: 'Dashboard', icon: LayoutDashboard },
  { to: '/trades',   label: 'Trades',    icon: TrendingUp      },
  { to: '/signals',  label: 'Signals',   icon: Activity        },
  { to: '/backtest', label: 'Strategy Lab', icon: FlaskConical },
  { to: '/risk',     label: 'Risk',      icon: Shield          },
  { to: '/settings', label: 'Settings',  icon: SettingsIcon    },
  { to: '/logs',     label: 'Logs',      icon: FileText        },
]

function Placeholder({ title }: { title: string }) {
  return (
    <div className="p-6">
      <h1 className="text-xl font-bold text-white mb-2">{title}</h1>
      <p className="text-slate-400 text-sm">
        This page is ready to implement. Wire it to the API using the client in
        <code className="ml-1 bg-slate-700 px-1.5 py-0.5 rounded text-cyan-400 text-xs">
          src/api/client.ts
        </code>
      </p>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="flex h-screen bg-slate-900 text-slate-100 overflow-hidden">

        {/* ── Sidebar ─────────────────────────────────────────── */}
        <aside className="w-56 flex-shrink-0 bg-slate-800 border-r border-slate-700 flex flex-col">
          {/* Logo */}
          <div className="px-5 py-5 border-b border-slate-700">
            <div className="flex items-center gap-2">
              <Zap className="w-5 h-5 text-cyan-400" />
              <span className="font-bold text-sm text-white">MR Bot</span>
            </div>
            <p className="text-xs text-slate-500 mt-0.5">Deriv · Synthetic Indices</p>
          </div>

          {/* Nav */}
          <nav className="flex-1 px-3 py-4 space-y-1">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-cyan-500/15 text-cyan-400'
                      : 'text-slate-400 hover:text-white hover:bg-slate-700/60'
                  }`
                }
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {label}
              </NavLink>
            ))}
          </nav>

          {/* Footer */}
          <div className="px-5 py-4 border-t border-slate-700">
            <p className="text-xs text-slate-500">v1.0.0 · demo mode</p>
          </div>
        </aside>

        {/* ── Main Content ─────────────────────────────────────── */}
        <main className="flex-1 overflow-y-auto">
          <Routes>
            <Route path="/"         element={<Dashboard />} />
            <Route path="/trades"   element={<Trades />} />
            <Route path="/signals"  element={<Signals />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/risk"     element={<Risk />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/logs"     element={<Logs />} />
          </Routes>
        </main>

      </div>
    </BrowserRouter>
  )
}
