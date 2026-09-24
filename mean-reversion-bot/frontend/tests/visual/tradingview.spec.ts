import { test, expect, type Page } from '@playwright/test'

const embedURL = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
// Mimics the provider's dependency on its current script's attached container.
const embed = `const script = document.currentScript;
const config = JSON.parse(script.textContent);
const widget = script.parentElement.querySelector('.tradingview-widget-container__widget');
widget.textContent = config.symbol + ' interval ' + config.interval;
widget.setAttribute('role', 'status');`

async function openLab(page: Page) {
  await page.route('**/api/mt5/**', route => route.fulfill({ json:
    route.request().url().endsWith('/journal') ? [] : { connected: false, running: false, message: 'Test terminal disconnected' } }))
  await page.route('**/api/backtest/results', route => route.fulfill({ json: [] }))
  await page.goto('/backtest')
  await page.getByLabel('Access key').fill('visual-test-admin-key-0000000000000000')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
}

for (const width of [1440, 390]) {
  test(`chart lifecycle and recovery at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    let mode: 'hold' | 'ok' | 'fail' = 'hold'
    const pending: (() => void)[] = []
    await page.route(embedURL, async route => {
      const action = mode
      if (action === 'hold') await new Promise<void>(resolve => pending.push(resolve))
      try {
        if (action === 'fail') await route.abort()
        else await route.fulfill({ contentType: 'application/javascript', body: embed })
      } catch { /* Disposed iframe requests can be cancelled by the browser. */ }
    })
    await openLab(page)
    await expect.poll(() => pending.length).toBeGreaterThan(0)
    await page.getByLabel('Platform', { exact: true }).selectOption('mt5')
    await expect(page.getByTitle('TradingView price chart')).toHaveCount(0)
    mode = 'ok'; pending.splice(0).forEach(release => release())
    await page.getByLabel('Platform', { exact: true }).selectOption('tradingview')
    const chart = page.frameLocator('iframe[title="TradingView price chart"]')
    await expect(chart.getByRole('status')).toContainText('interval 5')

    mode = 'hold'
    await page.getByLabel('Timeframe', { exact: true }).selectOption('M15')
    await expect.poll(() => pending.length).toBeGreaterThan(0)
    mode = 'ok'
    await page.getByLabel('Timeframe', { exact: true }).selectOption('H1')
    pending.splice(0).forEach(release => release())
    await expect(chart.getByRole('status')).toContainText('interval 60')
    await page.getByRole('button', { name: 'NAS100', exact: true }).click()
    await expect(chart.getByRole('status')).not.toContainText('VOLATILITY_75')
    await expect(page.getByTitle('TradingView price chart')).toHaveCount(1)

    mode = 'fail'
    await page.getByRole('button', { name: 'Reload chart', exact: true }).click()
    await expect(chart.getByRole('alert')).toBeVisible()
    await page.getByTitle('TradingView price chart').scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('chart-error.png') })
    mode = 'ok'
    await page.getByRole('button', { name: 'Reload chart', exact: true }).click()
    await expect(chart.getByRole('status')).toContainText('interval 60')
    await expect(chart.getByRole('alert')).toBeHidden()
    await page.screenshot({ path: testInfo.outputPath('chart-recovered.png') })
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}

test('public TradingView embed smoke', async ({ page }, testInfo) => {
  test.skip(process.env.UI_REAL_TV !== '1', 'Opt-in public CDN check; deterministic tests run without provider access')
  const errors: string[] = []
  page.on('pageerror', e => errors.push(e.message))
  await openLab(page)
  await page.getByLabel('Timeframe', { exact: true }).selectOption('M15')
  await page.getByLabel('Platform', { exact: true }).selectOption('mt5')
  await page.getByLabel('Platform', { exact: true }).selectOption('tradingview')
  const chart = page.frameLocator('iframe[title="TradingView price chart"]')
  await expect(chart.locator('iframe')).toBeVisible({ timeout: 30000 })
  const provider = chart.frameLocator('iframe')
  await expect(provider.locator('body')).toContainText('Constant Volatility of 75%', { timeout: 30000 })
  await expect(provider.locator('canvas').first()).toBeVisible()
  await testInfo.attach('provider-text', { body: await provider.locator('body').innerText(), contentType: 'text/plain' })
  await page.getByTitle('TradingView price chart').scrollIntoViewIfNeeded()
  await page.screenshot({ path: testInfo.outputPath('public-chart.png') })
  expect(errors).toEqual([])
})
