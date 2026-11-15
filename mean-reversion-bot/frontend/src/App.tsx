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
  PanelLeftClose, PanelLeftOpen, Menu, X
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
import QuickTest from './pages/QuickTest'

const TOOLS = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },

  { to: '/trades',   label: 'Deriv History', icon: TrendingUp  },
  { to: '/signals',  label: 'Deriv Signals', icon: Activity    },
  { to: '/backtest', label: 'Full Strategy Lab', icon: FlaskConical },
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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  function toggleSidebar() {
    setSidebarCollapsed(current => {
      const next = !current
      try { localStorage.setItem('sidebar-collapsed', String(next)) } catch { /* Keep the toggle usable without storage. */ }
      return next
    })
  }

  return (
    <AccessGate><BrowserRouter>
      <div className="flex flex-col md:flex-row h-screen md:h-[calc(100vh-36px)] bg-slate-900 text-slate-100 overflow-hidden">

        {/* ── Mobile Header ─────────────────────────────────────── */}
        <header className="md:hidden flex items-center justify-between px-4 py-3 bg-slate-800 border-b border-slate-700 z-50">
          <div className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-cyan-400" />
            <span className="font-bold text-sm text-white">Strategy Tester</span>
          </div>
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700"
          >
            {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </header>

        {/* ── Sidebar ─────────────────────────────────────────── */}
        <aside className={`
          ${sidebarCollapsed ? 'md:w-16' : 'md:w-56'} 
          ${mobileMenuOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
          fixed md:relative inset-y-0 left-0 z-40
          flex-shrink-0 bg-slate-800 border-r border-slate-700 flex flex-col 
          transition-transform md:transition-[width] duration-200 ease-in-out
          w-64 md:w-auto
        `}>
          {/* Logo (Hidden on mobile as it's in the header) */}
          <div className={`${sidebarCollapsed ? 'px-2' : 'px-4'} py-4 border-b border-slate-700 hidden md:block`}>
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
          <nav className={`flex-1 overflow-y-auto ${sidebarCollapsed ? 'md:px-1' : 'md:px-3'} px-3 py-4 space-y-1`}>
            <NavLink 
              to="/test" 
              onClick={() => setMobileMenuOpen(false)}
              aria-label="Run a test" 
              title="Run a test" 
              className="flex items-center gap-3 rounded-lg bg-cyan-500/15 px-3 py-2.5 text-sm font-semibold text-cyan-300"
            >
              <FlaskConical className="w-4 h-4 flex-shrink-0" />
              <span className={sidebarCollapsed ? 'md:hidden' : ''}>Run a test</span>
            </NavLink>
            
            <div className="pt-2 space-y-1">
              {!sidebarCollapsed && (
                <div className="hidden md:block px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Tools
                </div>
              )}
              {TOOLS.map(({ to, label, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setMobileMenuOpen(false)}
                  aria-label={label}
                  title={label}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `flex items-center ${sidebarCollapsed ? 'md:justify-center md:px-2' : 'gap-3 px-3'} py-2 rounded-lg text-sm transition-colors ${
                      isActive
                        ? 'bg-cyan-500/15 text-cyan-400'
                        : 'text-slate-400 hover:text-white hover:bg-slate-700/60'
                    }`
                  }
                >
                  <Icon className="w-4 h-4 flex-shrink-0" />
                  <span className={`truncate ${sidebarCollapsed ? 'md:hidden' : ''}`}>{label}</span>
                </NavLink>
              ))}
            </div>
          </nav>

          {/* Footer */}
          <div className={`${sidebarCollapsed ? 'md:px-1 text-center' : 'md:px-5'} px-5 py-4 border-t border-slate-700`}>
            <p className={`text-xs text-slate-500 ${sidebarCollapsed ? 'md:hidden' : ''}`}>v1.0.0 · protected controls</p>
          </div>
        </aside>

        {/* Mobile Overlay */}
        {mobileMenuOpen && (
          <div 
            className="fixed inset-0 bg-black/50 z-30 md:hidden" 
            onClick={() => setMobileMenuOpen(false)}
          />
        )}

        {/* ── Main Content ─────────────────────────────────────── */}
        <main className="flex-1 min-w-0 overflow-y-auto">
          <Routes>
            <Route path="/" element={<QuickTest />} />
            <Route path="/test" element={<QuickTest />} />
            <Route path="/dashboard" element={<Dashboard />} />
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
