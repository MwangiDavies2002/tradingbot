import { test, expect } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`per-asset Monte Carlo results at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const holdout = { total_pnl: 42, total_trades: 25, profit_factor: 1.8,
      max_drawdown_pct: .12, sharpe_ratio: 1.1, sortino_ratio: 1.4,
      expectancy: 1.2, win_rate: .55 }
    const report = { assets: {
      'EURUSD.a': { status: 'validated', demo_candidate: false, validation: {
        holdout, checks: { holdout_positive: true }, note: 'fixture', oos_trades: 120,
        monte_carlo: { seed: 42, simulations: 1000, method: 'IID cash-PnL bootstrap',
          drawdown_p95: .18, ending_balance_p05: 8500, loss_probability: .23 } } },
      'XAUUSD': { status: 'insufficient_trades', demo_candidate: false, validation: {
        holdout, checks: { holdout_positive: false }, note: 'fixture', oos_trades: 0,
        monte_carlo: { status: 'insufficient_trades', seed: 42 } } }
    } }
    await page.route('**/api/analysis/runs/research-ui', route => route.fulfill({ json: {
      id: 'research-ui', status: 'completed', stage: 'finished', progress: 1, report } }))
    await page.route('**/api/analysis/runs', route => route.fulfill({ json: [
      { id: 'research-ui', status: 'completed', stage: 'finished', created: 1770000000 } ] }))
    await page.goto('/analyze')
    await page.getByLabel('Access key').fill('visual-test-admin-key-0000000000000000')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByRole('button', { name: /completed · finished/ }).click()
    const euro = page.getByRole('region', { name: 'EURUSD.a Monte Carlo risk' })
    const gold = page.getByRole('region', { name: 'XAUUSD Monte Carlo risk' })
    await expect(euro).toContainText('120 walk-forward out-of-sample trade outcomes')
    await expect(euro).toContainText('18.0%')
    await expect(euro).toContainText('8500.00')
    await expect(euro).toContainText('23.0%')
    await expect(gold).toContainText('Monte Carlo metrics are unavailable')
    await expect(gold).not.toContainText('8500.00')
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}
