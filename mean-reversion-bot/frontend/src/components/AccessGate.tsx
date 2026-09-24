import { useEffect, useState, type ReactNode, type FormEvent } from 'react'
import { api, setAccessKey } from '../api/client'
import { IdentityContext } from '../auth/identity'

const ACCESS_KEY_STORAGE = 'mr-bot-access-key'

export default function AccessGate({ children }: { children: ReactNode }) {
  const [identity, setIdentity] = useState<any>(null)
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    const storedKey = localStorage.getItem(ACCESS_KEY_STORAGE)
    if (!storedKey) return
    setAccessKey(storedKey)
    api.get('/api/auth/me')
      .then(setIdentity)
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
      setIdentity(await api.get('/api/auth/me'))
      localStorage.setItem(ACCESS_KEY_STORAGE, submittedKey)
      setKey('')
    } catch (err) { setAccessKey(''); setError(err instanceof Error ? err.message : String(err)) }
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
      <button onClick={() => { setAccessKey(''); localStorage.removeItem(ACCESS_KEY_STORAGE); setIdentity(null) }}>Sign out</button>
    </div>
    <IdentityContext.Provider value={identity}>{children}</IdentityContext.Provider>
  </div>
}
