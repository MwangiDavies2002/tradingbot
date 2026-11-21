export const STORAGE_KEY = 'mr-bot-theme'

export function initializeTheme() {
  let theme: 'dark' | 'light'
  try {
    theme = localStorage.getItem(STORAGE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    theme = 'dark'
  }
  document.documentElement.dataset.theme = theme
}
