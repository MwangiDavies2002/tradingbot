import { test, expect } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`exact MT5 pair selection at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('https://s3.tradingview.com/**', route => route.abort())
    let state: any = { connected: false, running: false, account: 123, server: 'Test-Demo',
      config: { symbol: 'Volatility 75 (1s) Index', timeframe: 'M5', min_confluence: 6, risk_pct: .005, daily_loss_pct: .03 } }
    const starts: any[] = []
    await page.route('**/api/mt5/**', async route => {
      const action = route.request().url().split('/').pop()
      if (action === 'journal') return route.fulfill({ json: [] })
      if (action === 'symbols') return route.fulfill({ json: { symbols: ['EURUSD.a', 'XAUUSD'].map(name => ({ name, description: name, eligible: true })) } })
      if (action === 'connect') state.connected = true
      if (action === 'strategy') state.config = route.request().postDataJSON()
      if (action === 'start') { starts.push(route.request().postDataJSON()); state.running = true }
      if (action === 'stop') state.running = false
      return route.fulfill({ json: state })
    })
    await page.route('**/api/backtest/results', route => route.fulfill({ json: [] }))
    await page.goto('/backtest')
    await page.getByLabel('Access key').fill('visual-test-admin-key-0000000000000000')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByLabel('Platform', { exact: true }).selectOption('mt5')
    await page.getByRole('button', { name: 'Connect MT5 demo' }).click()
    const pair = page.getByRole('combobox', { name: 'MT5 broker pair', exact: true })
    await pair.selectOption('EURUSD.a')
    await expect(page.getByRole('button', { name: 'Start demo', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: 'Save lab selection' }).click()
    await page.getByRole('button', { name: 'Start demo', exact: true }).click()
    expect(starts).toEqual([{ symbol: 'EURUSD.a' }])
    await expect(pair).toBeDisabled()
    await page.getByRole('button', { name: 'Stop entries' }).click()
    await pair.selectOption('XAUUSD')
    await expect(page.getByRole('button', { name: 'Start demo', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: 'Save lab selection' }).click()
    await expect(page.getByRole('button', { name: 'Start demo', exact: true })).toBeEnabled()
    expect(state.config.symbol).toBe('XAUUSD')
    await page.getByRole('heading', { name: 'MT5 demo · XAUUSD' }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('mt5-pair.png') })
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}
