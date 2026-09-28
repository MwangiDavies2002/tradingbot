import { test, expect } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`single-pair research candidate scanner at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const strategy = { symbol: 'EURUSD.a', timeframe: 'M15', min_confluence: 11,
      use_zscore: true, use_rsi: false, use_bb: false, risk_pct: .005 }
    const candidate = { run_id: 'validated-123', strategy, snapshot: { server: 'Demo', account: 1 } }
    let saved: any = null
    let candidateReady = false
    const posted: any[] = []
    await page.route('**/api/mt5/status', route => route.fulfill({ json: {
      research_validated: candidateReady, research_candidate: candidate, config: strategy, connected: true } }))
    await page.route('**/api/mt5/symbols', route => route.fulfill({ json: {
      symbols: [{ name: 'EURUSD.a', description: 'one exact pair', eligible: true },
                { name: 'XAUUSD', description: 'another pair', eligible: true }] } }))
    await page.route('**/api/scanner**', route => {
      const url = route.request().url()
      if (url.endsWith('/ledger')) return route.fulfill({ json: { observations: [], trades: [] } })
      if (url.endsWith('/analytics')) return route.fulfill({ json: {
        observations: 0, overall: { count: 0, sample: 'exploratory' }, groups: {}, states: {}, model: 'fixture' } })
      if (url.endsWith('/start')) {
        const body = route.request().postDataJSON(); posted.push(body)
        saved = { id:'scan-1', status:'running', created:Date.now()/1000, config:body }
      }
      if (url.endsWith('/stop') && saved) saved.status = 'stopped'
      return route.fulfill({ json: { run:saved, latest:[], execution_enabled:false } })
    })
    await page.goto('/scanner')
    await page.getByLabel('Access key').fill('visual-test-operator-key-0000000000000000')
    await page.getByRole('button', { name: 'Sign in', exact:true }).click()
    await page.getByRole('button', { name:'Use loaded research candidate' }).click()
    await expect(page.getByRole('alert')).toContainText('Load a passing single-pair candidate')
    candidateReady = true
    await page.getByRole('button', { name:'Use loaded research candidate' }).click()
    await expect(page.getByText(/Research candidate validated-123/)).toBeVisible()
    await expect(page.getByLabel('Timeframe')).toHaveValue('M15')
    await expect(page.getByLabel('Timeframe')).toBeDisabled()
    await expect(page.getByLabel('Minimum weighted score')).toHaveValue('11')
    await page.getByRole('button', { name:'Load broker symbols' }).click()
    await expect(page.getByRole('button', { name:'XAUUSD', exact:true })).toBeDisabled()
    await page.getByRole('button', { name:'Start paper scanner' }).click()
    expect(posted[0]).toMatchObject({ strategy_mode:'research_candidate', timeframe:'M15', threshold:11,
      assets:[{ symbol:'EURUSD.a' }], research_run_id:'validated-123' })
    await page.getByRole('button', { name:'Stop scanner' }).click()
    await page.getByRole('button', { name:'Use manual scanner settings' }).click()
    await expect(page.getByLabel('Timeframe')).toBeEnabled()
    await expect(page.getByRole('button', { name:'XAUUSD', exact:true })).toBeEnabled()
    expect(errors).toEqual([])
  })
}
