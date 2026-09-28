import { test, expect } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`single-pair research, paper and demo evidence at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.route('https://s3.tradingview.com/**', route => route.abort())
    const strategy = { symbol: 'EURUSD.a', timeframe: 'M5', min_confluence: 7,
      risk_pct: .005, daily_loss_pct: .03 }
    const candidate = { run_id: 'research-one', strategy,
      snapshot: { server: 'Demo', account: 123, currency: 'USD' },
      research_baseline: { holdout: { total_trades: 25, total_pnl: 42, profit_factor: 1.8 } } }
    await page.route('**/api/mt5/status', route => route.fulfill({ json: {
      connected: true, running: false, account: 123, server: 'Demo', config: strategy,
      research_validated: true, research_candidate: candidate,
      research_comparison: { status: 'insufficient_sample', closed_trades: 3,
        total_pnl: -2, profit_factor: .8, minimum_sample: 20,
        incomplete_positions: 1, currency: 'USD' } } }))
    await page.route('**/api/mt5/journal', route => route.fulfill({ json: [] }))
    await page.route('**/api/mt5/symbols', route => route.fulfill({ json: { symbols: [
      { name: 'EURUSD.a', description: 'EURUSD.a', eligible: true } ] } }))
    await page.route('**/api/scanner/analytics', route => route.fulfill({ json: { per_pair_policy: [
      { scope: 'Demo:123', symbol: 'EURUSD.a', timeframe: 'M5', research_run_id: 'research-one',
        policy_id: 'matching-policy', count: 12, observations: 45, states: { unresolved: 2 }, mean_r: .2 },
      { scope: 'Demo:999', symbol: 'EURUSD.a', timeframe: 'M5', research_run_id: 'research-one',
        policy_id: 'wrong-account', count: 500, observations: 600, states: {}, mean_r: 1 }
    ] } }))
    await page.route('**/api/backtest/results', route => route.fulfill({ json: [] }))
    await page.goto('/backtest')
    await page.getByLabel('Access key').fill('visual-test-admin-key-0000000000000000')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await page.getByLabel('Platform', { exact: true }).selectOption('mt5')
    const evidence = page.getByRole('region', { name: 'Single-pair validation evidence' })
    await expect(evidence).toBeVisible()
    await expect(evidence).toContainText('Research research-one | Demo:123 | EURUSD.a | M5')
    await expect(evidence).toContainText('12/300 closed; 45 signals; 2 unresolved')
    await expect(evidence).toContainText('3 complete candidate-linked positions')
    await expect(evidence).toContainText('1 incomplete positions excluded')
    await expect(evidence).not.toContainText('500/300')
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}
