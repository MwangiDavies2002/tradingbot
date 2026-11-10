import { useEffect, type ReactNode } from 'react'
import { setApiCredential } from '../api/client'
import { IdentityContext, type Identity } from '../auth/identity'

const PASSWORD_STORAGE = 'mr-bot-password'
const LEGACY_KEY_STORAGE = 'mr-bot-access-key'

export default function AccessGate({ children }: { children: ReactNode }) {
  const identity: Identity = { role: 'admin', demo: true }

  useEffect(() => {
    localStorage.removeItem(LEGACY_KEY_STORAGE)
    sessionStorage.removeItem(PASSWORD_STORAGE)
    sessionStorage.removeItem(LEGACY_KEY_STORAGE)
    setApiCredential('')
  }, [])

  return <IdentityContext.Provider value={identity}>{children}</IdentityContext.Provider>
}
