import { test, expect } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`historical source selection at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    // This flow covers our MT5 controls, not the remote TradingView embed.
    await page.route('https://s3.tradingview.com/**', route => route.abort())
    // Stub broker-facing endpoints: never touch a desktop terminal during UI QA.
    await page.route('**/api/mt5/**', route => route.fulfill({ json:
      route.request().url().endsWith('/journal') ? [] : { connected: false, running: false, message: 'Test terminal disconnected', config: { symbol: 'EURUSD.a' } } }))
    await page.route('**/api/backtest/results', route => route.fulfill({ json: [] }))
    const requests: any[] = []
    await page.route('**/api/backtest/run', route => {
      const body = route.request().postDataJSON(); requests.push(body)
      return body.data_source === 'mt5' && !body.csv_data
        ? route.fulfill({ status: 422, json: { detail: 'Connect MT5 demo first' } })
        : route.fulfill({ json: [] })
    })
    await page.goto('/backtest')
    await page.getByLabel('Access key').fill('visual-test-admin-key-0000000000000000')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByLabel('Platform', { exact: true }).selectOption('mt5')
    const source = page.getByRole('combobox', { name: 'Historical data source', exact: true })
    await expect(source).toHaveValue('deriv')
    await page.getByRole('button', { name: 'Run Combined Test' }).click()
    await expect.poll(() => requests.length).toBe(1)
    expect(requests[0].data_source).toBe('deriv')
    await page.getByRole('button', { name: 'NAS100', exact: true }).click()
    await source.selectOption('mt5')
    await expect(page.getByRole('button', { name: 'NAS100', exact: true })).toBeDisabled()
    await page.getByRole('button', { name: 'Run Combined Test' }).click()
    await expect(page.getByRole('alert', { name: 'Backtest errors' })).toContainText('Connect MT5 demo first')
    expect(requests[1].symbols).toEqual(['EURUSD.a'])
    expect(requests[1].data_source).toBe('mt5')
    await page.locator('input[type=file]').setInputFiles({ name: 'candles.csv', mimeType: 'text/csv', buffer: Buffer.from('timestamp,open,high,low,close\n1700000000,100,101,99,100') })
    await expect.poll(() => requests.length).toBe(3)
    expect(requests[2].csv_data).toContain('1700000000')
    await expect(page.getByRole('button', { name: 'Run Combined Test' })).toBeEnabled()
    await page.getByRole('heading', { name: 'Strategy Lab', exact: true }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('backtest-source.png') })
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}

for (const width of [1440, 390]) {
  test(`multiple asset tests retain successes at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await page.route('https://s3.tradingview.com/**', route => route.abort())
    await page.route('**/api/mt5/**', route => route.fulfill({ json:
      route.request().url().endsWith('/journal') ? [] : { connected: false, running: false } }))
    await page.route('**/api/backtest/results', route => route.fulfill({ json: [] }))
    const requests: any[] = []
    await page.route('**/api/backtest/run', route => {
      const body = route.request().postDataJSON(); requests.push(body)
      const symbol = body.symbols[0]
      return symbol === 'NAS100'
        ? route.fulfill({ status: 422, json: { detail: 'History unavailable for this asset' } })
        : route.fulfill({ json: [{ symbol, run_id: symbol, data_source: 'deriv',
          sharpe_ratio: 0, total_pnl: 0, total_pnl_pct: 0, win_rate: 0,
          total_trades: 0, max_drawdown: 0, equity_curve: [] }] })
    })
    await page.goto('/backtest')
    await page.getByLabel('Access key').fill('visual-test-admin-key-0000000000000000')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByLabel('Platform', { exact: true }).selectOption('mt5')
    await expect(page.getByRole('checkbox', { name: 'High-impact news only' })).toBeDisabled()
    await expect(page.getByRole('combobox', { name: /implementation/ })).toHaveCount(0)
    await page.getByRole('button', { name: 'NAS100', exact: true }).click()
    await page.getByRole('button', { name: 'BOOM500', exact: true }).click()
    await expect(page.getByRole('button', { name: '1HZ75V', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('input[type=file]')).toBeDisabled()
    await page.getByRole('button', { name: 'Run Combined Test' }).click()
    await expect(page.getByRole('heading', { name: '1HZ75V Analysis' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'BOOM500 Analysis' })).toBeVisible()
    await expect(page.getByRole('alert', { name: 'Backtest errors' })).toContainText('NAS100: History unavailable')
    expect(requests.map(r => r.symbols)).toEqual([['1HZ75V'], ['NAS100'], ['BOOM500']])
    for (const request of requests) {
      expect(request.news_only).toBe(false)
      expect(request.strategy_versions).toEqual({})
      expect(request.initial_balance).toBe(10000)
    }
    await expect(page.getByRole('button', { name: 'Run Combined Test' })).toBeEnabled()
    await page.getByRole('heading', { name: '1HZ75V Analysis' }).scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('batch-results.png') })
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    await page.getByRole('button', { name: 'NAS100', exact: true }).click()
    await expect(page.getByRole('button', { name: 'NAS100', exact: true })).toHaveAttribute('aria-pressed', 'false')
    await page.getByRole('button', { name: 'BOOM500', exact: true }).click()
    await expect(page.locator('input[type=file]')).toBeEnabled()
    await page.getByRole('button', { name: '1HZ75V', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Run Combined Test' })).toBeDisabled()
    expect(errors).toEqual([])
  })
}
