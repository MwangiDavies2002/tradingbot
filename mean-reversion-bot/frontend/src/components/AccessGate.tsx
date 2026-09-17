import { useState, type ReactNode, type FormEvent } from 'react'
import { api, setAccessKey } from '../api/client'

export default function AccessGate({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<any>(null)
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setAccessKey(key.trim())
    try { setIdentity(await api.get('/api/auth/me')); setKey('') }
    catch (err) { setAccessKey(''); setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  if (!identity) return <main className="min-h-screen bg-slate-900 text-slate-100 grid place-items-center p-6">
    <form onSubmit={login} className="w-full max-w-sm space-y-4 bg-slate-800 p-6 rounded-xl">
      <h1 className="text-xl font-bold">Sign in to MR Bot</h1>
      <p className="text-sm text-slate-400">Enter the access key provided by your administrator. It stays in memory until you sign out or close this page.</p>
      <label className="block">Access key<input autoComplete="off" type="password" required value={key}
        onChange={e => setKey(e.target.value)} className="block w-full rounded p-2 mt-2 bg-slate-900" /></label>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      <button disabled={busy} className="bg-cyan-700 rounded px-4 py-2 disabled:opacity-50">{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </main>
  return <div>
    <div className="bg-slate-950 text-slate-300 text-sm px-4 py-2 flex justify-between">
      <span>{identity.demo ? 'Deriv demo' : 'Deriv LIVE'} · {identity.account_id || 'Account not configured'} · {identity.role}</span>
      <button onClick={() => { setAccessKey(''); setIdentity(null) }}>Sign out</button>
    </div>
    {children}
  </div>
}
