import { useEffect, useState, type ReactNode, type FormEvent } from 'react'
import ThemeToggle from './ThemeToggle'
import { api, setApiCredential } from '../api/client'
import { IdentityContext, type Identity } from '../auth/identity'

const PASSWORD_STORAGE = 'mr-bot-password'
const LEGACY_KEY_STORAGE = 'mr-bot-access-key'

export default function AccessGate({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    localStorage.removeItem(LEGACY_KEY_STORAGE)
    const storedPassword = sessionStorage.getItem(PASSWORD_STORAGE)
    if (!storedPassword) return
    setApiCredential(storedPassword)
    api.get('/api/auth/me')
      .then(value => setIdentity(value as Identity))
      .catch(() => {
        setApiCredential('')
        sessionStorage.removeItem(PASSWORD_STORAGE)
      })
  }, [])
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    const submittedPassword = password
    setApiCredential(submittedPassword)
    try {
      setIdentity(await api.get('/api/auth/me') as Identity)
      sessionStorage.setItem(PASSWORD_STORAGE, submittedPassword)
      setPassword('')
    } catch (err) {
      setApiCredential('')
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
      <p className="text-sm text-slate-400">Enter the strong password assigned to your role for this deployment (at least 32 characters). Sign-in on localhost and Vercel are separate. This tab keeps your password only for the current browser session.</p>
      <label className="block">Password<input autoComplete="current-password" type="password" required minLength={32} value={password}
        onChange={e => setPassword(e.target.value)} className="box-border block w-full min-w-0 rounded p-2 mt-2 bg-slate-900" /></label>
      {error && <p role="alert" className="text-red-300">{error}</p>}
      <button type="submit" disabled={busy} className="bg-cyan-700 rounded px-4 py-2 disabled:opacity-50">{busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </main>
  return <div>
    <div className="bg-slate-950 text-slate-300 text-sm px-4 py-2 flex justify-between">
      <span>{identity.demo ? 'Deriv demo' : 'Deriv LIVE'} · {identity.account_id || 'Account not configured'} · {identity.role}</span>
      <div className="flex items-center gap-3"><ThemeToggle /><button type="button" onClick={() => { setApiCredential(''); sessionStorage.removeItem(PASSWORD_STORAGE); setIdentity(null) }}>Sign out</button></div>
    </div>
    <IdentityContext.Provider value={identity}>{children}</IdentityContext.Provider>
  </div>
}
