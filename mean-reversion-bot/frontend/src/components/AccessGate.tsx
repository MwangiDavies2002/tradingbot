import { useEffect, useState, type ReactNode, type FormEvent } from 'react'
import ThemeToggle from './ThemeToggle'
import { api, setAccessKey } from '../api/client'
import { IdentityContext, type Identity } from '../auth/identity'

const ACCESS_KEY_STORAGE = 'mr-bot-access-key'

export default function AccessGate({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const storedKey = localStorage.getItem(ACCESS_KEY_STORAGE)
    if (!storedKey) return
    setAccessKey(storedKey)
    api.get('/api/auth/me')
      .then(value => setIdentity(value as Identity))
      .catch(() => {
        setAccessKey('')
        localStorage.removeItem(ACCESS_KEY_STORAGE)
      })
  }, [])
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    const submittedKey = key.trim()
    setAccessKey(submittedKey)
    try {
      setIdentity(await api.get('/api/auth/me') as Identity)
      localStorage.setItem(ACCESS_KEY_STORAGE, submittedKey)
      setKey('')
    } catch (err) {
      setAccessKey('')
      const detail = err instanceof Error ? err.message : String(err)
      setError(detail.includes('Failed to fetch')
        ? 'Cannot reach the local API. Start backend/run_local.py, then try again.'
        : detail)
    }
    finally { setBusy(false) }
  }
  if (!identity) return <main className="box-border flex min-h-screen w-full items-center justify-center overflow-x-hidden bg-slate-900 p-4 text-slate-100">
    <form onSubmit={login} className="box-border w-full min-w-0 max-w-sm space-y-4 rounded-xl bg-slate-800 p-6">
      <div className="flex justify-end"><ThemeToggle /></div>
      <h1 className="text-xl font-bold">Sign in to Strategy Tester</h1>
      <p className="text-sm text-slate-400">Enter the access key for this deployment. Sign-in on localhost and Vercel are separate. After a successful sign-in, this browser remembers the key for this site until you sign out.</p>
      <label className="block">Access key<input autoComplete="off" type="password" required value={key}
        onChange={e => setKey(e.target.value)} className="box-border block w-full min-w-0 rounded p-2 mt-2 bg-slate-900" /></label>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      <button type="submit" disabled={busy} className="bg-cyan-700 rounded px-4 py-2 disabled:opacity-50">{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </main>
  return <div>
    <div className="bg-slate-950 text-slate-300 text-sm px-4 py-2 flex justify-between">
      <span>{identity.demo ? 'Deriv demo' : 'Deriv LIVE'} · {identity.account_id || 'Account not configured'} · {identity.role}</span>
      <div className="flex items-center gap-3"><ThemeToggle /><button type="button" onClick={() => { setAccessKey(''); localStorage.removeItem(ACCESS_KEY_STORAGE); setIdentity(null) }}>Sign out</button></div>
    </div>
    <IdentityContext.Provider value={identity}>{children}</IdentityContext.Provider>
  </div>
}
