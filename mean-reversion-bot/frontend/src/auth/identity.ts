import { createContext, useContext } from 'react'

export type Identity = { role: 'admin' | 'operator' | 'viewer'; demo: boolean; account_id?: string }
export const IdentityContext = createContext<Identity | null>(null)
export function usePermissions() {
  const role = useContext(IdentityContext)?.role
  return { role, canRunResearch: role === 'admin' || role === 'operator', canRegisterInstrument: role === 'admin' }
}
