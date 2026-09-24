import { defineConfig } from '@playwright/test'
import path from 'node:path'

export default defineConfig({
  testDir: './tests/visual', workers: 1, timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:4173', channel: process.env.UI_BROWSER_CHANNEL || 'msedge',
    headless: true, screenshot: 'only-on-failure', trace: 'retain-on-failure' },
  webServer: [
    { command: `"${process.env.UI_PYTHON || path.resolve('../backend/.venv/Scripts/python.exe')}" ../backend/tests/visual_api.py`,
      url: 'http://127.0.0.1:8017/health', reuseExistingServer: false },
    { command: 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
      url: 'http://127.0.0.1:4173', reuseExistingServer: false,
      env: { VITE_API_URL: 'http://127.0.0.1:8017' } },
  ],
})
