/**
 * App.tsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Root app component: router, sidebar nav, dark layout shell.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { useState } from 'react'
import {
  LayoutDashboard, TrendingUp, Activity, Shield,
  Settings as SettingsIcon, FileText, Zap, FlaskConical,
  PanelLeftClose, PanelLeftOpen
} from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Trades from './pages/Trades'
import Signals from './pages/Signals'
import Risk from './pages/Risk'
import Settings from './pages/Settings'
import Logs from './pages/Logs'
import Backtest from './pages/Backtest'
import MT5Panel from './components/MT5Panel'
import AccessGate from './components/AccessGate'
import Research from './pages/Research'
import Analyze from './pages/Analyze'
import Institutional from './pages/Institutional'
import InstrumentCatalog from './pages/InstrumentCatalog'
import PaperTrades from './pages/PaperTrades'
import Scanner from './pages/Scanner'

const NAV = [
  { to: '/',         label: 'Dashboard', icon: LayoutDashboard },
  { to: '/trades',   label: 'Deriv History', icon: TrendingUp  },
  { to: '/signals',  label: 'Deriv Signals', icon: Activity    },
  { to: '/backtest', label: 'Strategy Lab', icon: FlaskConical },
  { to: '/analyze', label: 'Analyze assets', icon: FlaskConical },
  { to: '/scanner', label: 'Forward scanner', icon: Activity },
  { to: '/paper-trades', label: 'Paper trades', icon: FlaskConical },
  { to: '/research', label: 'Research validation', icon: FlaskConical },
  { to: '/institutional', label: 'Institutional lab', icon: FlaskConical },
  { to: '/instruments', label: 'Instrument catalog', icon: SettingsIcon },
  { to: '/mt5', label: 'MT5 Demo & Journal', icon: TrendingUp },
  { to: '/risk',     label: 'Deriv Risk', icon: Shield         },
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem('sidebar-collapsed') === 'true' } catch { return false }
  })

  function toggleSidebar() {
    setSidebarCollapsed(current => {
      const next = !current
      try { localStorage.setItem('sidebar-collapsed', String(next)) } catch { /* Keep the toggle usable without storage. */ }
      return next
    })
  }

  return (
    <AccessGate><BrowserRouter>
      <div className="flex h-[calc(100vh-36px)] bg-slate-900 text-slate-100 overflow-hidden">

        {/* ── Sidebar ─────────────────────────────────────────── */}
        <aside className={`${sidebarCollapsed ? 'w-16' : 'w-56'} flex-shrink-0 bg-slate-800 border-r border-slate-700 flex flex-col transition-[width] duration-200`}>
          {/* Logo */}
          <div className={`${sidebarCollapsed ? 'px-2' : 'px-4'} py-4 border-b border-slate-700`}>
            <div className={`flex items-center ${sidebarCollapsed ? 'flex-col gap-3' : 'justify-between gap-2'}`}>
              <div className="flex items-center gap-2 min-w-0">
              <Zap className="w-5 h-5 text-cyan-400" />
              {!sidebarCollapsed && <span className="font-bold text-sm text-white truncate">Strategy Tester</span>}
              </div>
              <button
                type="button"
                onClick={toggleSidebar}
                aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                aria-expanded={!sidebarCollapsed}
                title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700/60 transition-colors"
              >
                {sidebarCollapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
              </button>
            </div>
            {!sidebarCollapsed && <p className="text-xs text-slate-500 mt-0.5">Deriv · Synthetic Indices</p>}
          </div>

          {/* Nav */}
          <nav className={`flex-1 overflow-y-auto ${sidebarCollapsed ? 'px-1' : 'px-3'} py-4 space-y-1`}>
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                aria-label={label}
                title={label}
                end={to === '/'}
                className={({ isActive }) =>
                  `flex items-center ${sidebarCollapsed ? 'justify-center px-2' : 'gap-3 px-3'} py-2 rounded-lg text-sm transition-colors ${
                    isActive
                      ? 'bg-cyan-500/15 text-cyan-400'
                      : 'text-slate-400 hover:text-white hover:bg-slate-700/60'
                  }`
                }
              >
                <Icon className="w-4 h-4 flex-shrink-0" />
                {!sidebarCollapsed && <span className="truncate">{label}</span>}
              </NavLink>
            ))}
          </nav>

          {/* Footer */}
          <div className={`${sidebarCollapsed ? 'px-1 text-center' : 'px-5'} py-4 border-t border-slate-700`}>
            {!sidebarCollapsed && <p className="text-xs text-slate-500">v1.0.0 · protected controls</p>}
          </div>
        </aside>

        {/* ── Main Content ─────────────────────────────────────── */}
        <main className="flex-1 min-w-0 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/trades"   element={<Trades />} />
            <Route path="/signals"  element={<Signals />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/analyze" element={<Analyze />} />
            <Route path="/scanner" element={<Scanner />} />
            <Route path="/paper-trades" element={<PaperTrades />} />
            <Route path="/research" element={<Research />} />
            <Route path="/institutional" element={<Institutional />} />
            <Route path="/instruments" element={<InstrumentCatalog />} />
            <Route path="/mt5" element={<div className="p-6"><MT5Panel /></div>} />
            <Route path="/risk"     element={<Risk />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/logs"     element={<Logs />} />
          </Routes>
        </main>

      </div>
    </BrowserRouter></AccessGate>
  )
}
