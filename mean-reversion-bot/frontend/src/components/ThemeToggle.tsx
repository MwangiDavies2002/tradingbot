import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { STORAGE_KEY } from '../theme'

export default function ThemeToggle() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'dark')
  const light = theme === 'light'
  return <button type="button" aria-label={light ? 'Switch to dark mode' : 'Switch to light mode'}
    title={light ? 'Switch to dark mode' : 'Switch to light mode'}
    onClick={() => {
      const next = light ? 'dark' : 'light'
      document.documentElement.dataset.theme = next
      setTheme(next)
      try { localStorage.setItem(STORAGE_KEY, next) } catch { /* Still switch when storage is unavailable. */ }
    }} className="inline-flex items-center gap-2 rounded px-2 py-1 text-slate-300 hover:bg-slate-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-500">
    {light ? <Moon size={16} /> : <Sun size={16} />}
    <span>{light ? 'Dark mode' : 'Light mode'}</span>
  </button>
}
