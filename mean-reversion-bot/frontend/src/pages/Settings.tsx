import { useEffect, useState, useCallback } from 'react'
import { Settings as SettingsIcon, Save, RefreshCw, AlertCircle } from 'lucide-react'

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

export default function Settings() {
  const [config, setConfig] = useState<ConfigItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)

  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${BASE}/api/config`)
      if (!res.ok) throw new Error('Failed to fetch config')
      const data = await res.json()
      setConfig(data.config)
      setError(null)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadConfig()
  }, [loadConfig])

  const handleUpdate = async (key: string, newValue: string) => {
    setSaving(key)
    try {
      const res = await fetch(`${BASE}/api/config/${key}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
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
    <div className="p-6 space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">System Settings</h1>
          <p className="text-slate-400 text-sm">Configure trading parameters and risk limits</p>
        </div>
        <button 
            onClick={() => loadConfig()}
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

      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="p-4 border-b border-slate-700 bg-slate-900/50">
            <h3 className="text-sm font-bold text-slate-300 uppercase tracking-wider">Trading Strategy</h3>
        </div>
        <div className="divide-y divide-slate-700">
          {config.filter(c => !['DERIV_APP_ID', 'DERIV_API_TOKEN', 'SECRET_KEY', 'DATABASE_URL', 'REDIS_URL'].includes(c.key)).map((item) => (
            <div key={item.key} className="p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="flex-1">
                <div className="text-sm font-bold text-white mb-1">{item.key}</div>
                <div className="text-xs text-slate-500">{item.description}</div>
              </div>
              <div className="flex items-center gap-3">
                <input 
                    type="text"
                    defaultValue={item.value}
                    onBlur={(e) => {
                        if (e.target.value !== item.value) {
                            handleUpdate(item.key, e.target.value)
                        }
                    }}
                    className="bg-slate-900 border border-slate-700 text-slate-200 text-sm rounded-lg px-3 py-2 outline-none focus:border-cyan-500 w-32 font-mono"
                />
                {saving === item.key && <RefreshCw className="w-4 h-4 text-cyan-400 animate-spin" />}
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
