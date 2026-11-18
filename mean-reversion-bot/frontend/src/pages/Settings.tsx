import { useEffect, useState, useCallback } from 'react'
import { Settings as SettingsIcon, Save, RefreshCw, AlertCircle, Link as LinkIcon, CheckCircle2 } from 'lucide-react'
import { authHeaders } from '../api/client'

// Mocking some config fetch since I don't have a specific client function for all config
// But I can see the routes in bot_control.py
const BASE = (import.meta as any).env?.VITE_API_URL ?? ''

interface ConfigItem {
  key: string
  value: string
  value_type: string
  description: string
  updated_at: string
}

interface UserProfile {
  id: number
  email: string
  deriv_connected: boolean
  deriv_account_id: string | null
}

export default function Settings() {
  const [config, setConfig] = useState<ConfigItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  
  // Deriv Connection State
  const [user, setUser] = useState<UserProfile | null>(null)
  const [derivKey, setDerivKey] = useState('')
  const [connecting, setConnecting] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [configRes, userRes] = await Promise.all([
        fetch(`${BASE}/api/config`, { headers: authHeaders() }),
        fetch(`${BASE}/api/users/me`, { headers: authHeaders() })
      ])
      
      if (configRes.ok) {
        const configData = await configRes.json()
        setConfig(configData.config)
      }
      
      if (userRes.ok) {
        const userData = await userRes.json()
        setUser(userData)
      }
      
      setError(null)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleConnectDeriv = async () => {
    if (!derivKey) return
    setConnecting(true)
    try {
      const res = await fetch(`${BASE}/api/users/me/deriv-connection`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ api_key: derivKey })
      })
      
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to connect Deriv')
      }
      
      const data = await res.json()
      alert(`Successfully connected to Deriv account: ${data.account_id}`)
      setDerivKey('')
      loadData()
    } catch (err: any) {
      alert(err.message)
    } finally {
      setConnecting(false)
    }
  }

  const handleUpdate = async (key: string, newValue: string) => {
    setSaving(key)
    try {
      const res = await fetch(`${BASE}/api/config/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ value: newValue })
      })
      if (!res.ok) {
          const err = await res.json()
          throw new Error(err.detail || 'Update failed')
      }
      // Update local state
      setConfig(prev => prev.map(item => item.key === key ? { ...item, value: newValue } : item))
    } catch (err: any) {
      alert(err.message)
    } finally {
      setSaving(null)
    }
  }

  return (
    <div className="p-4 sm:p-6 space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold text-white">Account Settings</h1>
          <p className="text-slate-400 text-xs sm:text-sm">Manage your profile and broker connections.</p>
        </div>
        <button 
            onClick={() => loadData()}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
        >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-center gap-3 text-red-400 text-sm">
          <AlertCircle className="w-5 h-5" />
          {error}
        </div>
      )}

      {/* Deriv Connection Card */}
      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-slate-700 bg-slate-900/50 flex items-center justify-between">
            <div className="flex items-center gap-2">
                <LinkIcon className="w-4 h-4 text-cyan-400" />
                <h3 className="text-sm font-bold text-slate-300 uppercase tracking-wider">Deriv Broker Connection</h3>
            </div>
            {user?.deriv_connected && (
                <div className="flex items-center gap-1.5 text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-full border border-emerald-500/20">
                    <CheckCircle2 className="w-3 h-3" />
                    CONNECTED
                </div>
            )}
        </div>
        <div className="p-6 space-y-4">
            {user?.deriv_connected ? (
                <div className="flex items-center justify-between p-4 bg-slate-900/50 rounded-lg border border-slate-700">
                    <div>
                        <div className="text-xs text-slate-500 uppercase font-bold tracking-tight">Active Account ID</div>
                        <div className="text-lg font-mono text-white">{user.deriv_account_id}</div>
                    </div>
                    <button 
                        onClick={() => setDerivKey('') || setUser(prev => prev ? {...prev, deriv_connected: false} : null)}
                        className="text-xs text-red-400 hover:text-red-300 font-bold"
                    >
                        Disconnect
                    </button>
                </div>
            ) : (
                <div className="space-y-4">
                    <p className="text-sm text-slate-400">
                        To connect your Deriv account, go to <a href="https://app.deriv.com/account/api-token" target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline">Deriv API Token settings</a>, create a token with "Read" and "Trade" scopes, then paste it below.
                    </p>
                    <div className="flex gap-2">
                        <input 
                            type="password"
                            placeholder="Paste your Deriv API Token here..."
                            value={derivKey}
                            onChange={(e) => setDerivKey(e.target.value)}
                            className="flex-1 bg-slate-900 border border-slate-700 text-white text-sm rounded-lg px-4 py-2 outline-none focus:border-cyan-500"
                        />
                        <button 
                            onClick={handleConnectDeriv}
                            disabled={connecting || !derivKey}
                            className="bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white text-sm font-bold px-6 py-2 rounded-lg transition-colors flex items-center gap-2"
                        >
                            {connecting ? <RefreshCw className="w-4 h-4 animate-spin" /> : 'Connect'}
                        </button>
                    </div>
                </div>
            )}
        </div>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-slate-700 bg-slate-900/50">
            <h3 className="text-sm font-bold text-slate-300 uppercase tracking-wider">Global System Config</h3>
        </div>
        <div className="divide-y divide-slate-700">
          {config.filter(c => !['DERIV_APP_ID', 'DERIV_API_TOKEN', 'SECRET_KEY', 'DATABASE_URL', 'REDIS_URL'].includes(c.key)).map((item) => (
            <div key={item.key} className="p-4 sm:p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="flex-1">
                <div className="text-sm font-bold text-white mb-1">{item.key}</div>
                <div className="text-[10px] sm:text-xs text-slate-500">{item.description}</div>
              </div>
              <div className="flex items-center gap-3">
                <input 
                    type="text"
                    readOnly
                    defaultValue={item.value}
                    onBlur={(e) => {
                        if (e.target.value !== item.value) {
                            handleUpdate(item.key, e.target.value)
                        }
                    }}
                    className="flex-1 md:flex-none bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 outline-none focus:border-cyan-500 w-full md:w-32 font-mono text-right md:text-left"
                />
                {saving === item.key && <RefreshCw className="w-4 h-4 text-cyan-400 animate-spin flex-shrink-0" />}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="bg-slate-800/50 border border-slate-700 border-dashed rounded-xl p-6">
          <div className="flex items-start gap-3">
              <AlertCircle className="w-5 h-5 text-slate-500 mt-0.5" />
              <div>
                  <h4 className="text-sm font-bold text-slate-400">Environment Variables</h4>
                  <p className="text-xs text-slate-500 mt-1">
                      Sensitive keys (API tokens, database URLs) must be configured in the <code className="text-cyan-600 bg-cyan-500/10 px-1 rounded">.env</code> file 
                      and require a service restart to take effect.
                  </p>
              </div>
          </div>
      </div>
    </div>
  )
}
