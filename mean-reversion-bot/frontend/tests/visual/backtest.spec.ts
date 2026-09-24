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
      route.request().url().endsWith('/journal') ? [] : { connected: false, running: false, message: 'Test terminal disconnected' } }))
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
    const dialog = page.waitForEvent('dialog')
    await page.getByRole('button', { name: 'Run Combined Test' }).click()
    const alert = await dialog
    expect(alert.message()).toContain('Connect MT5 demo first'); await alert.accept()
    expect(requests[1].symbols).toEqual(['1HZ75V'])
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
