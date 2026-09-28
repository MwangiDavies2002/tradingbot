import { test, expect } from '@playwright/test'

for (const width of [1440, 390]) {
  test(`unified paper evidence viewer at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    const requests: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    let fail = false
    let empty = false
    await page.route('**/api/paper-trades**', route => route.fulfill({ json: route.request().url().endsWith('/analytics') ? null : { trades: [] } }))
    await page.route('**/api/scanner/paper-evidence?**', async route => {
      expect(route.request().method()).toBe('GET')
      const url = new URL(route.request().url())
      const source = url.searchParams.get('source')!
      const cursor = url.searchParams.get('cursor')
      requests.push(`${source}:${cursor || 'first'}`)
      if (fail) return route.fulfill({ status: 503, json: { detail: 'Evidence temporarily unavailable' } })
      const row = { id: `${source}:same-id`, source_id: 'same-id', source, symbol: cursor ? 'OLDER.a' : source === 'manual' ? 'MANUAL.a' : 'SCANNER.a',
        timeframe: 'M5', direction: 'buy', state: source === 'manual' ? 'closed' : 'unresolved',
        recorded_at: '2026-09-27T10:00:00+00:00', entry: 100, stop: 99, target: 102, exit: source === 'manual' ? 102 : null,
        outcome: { value: source === 'manual' ? 4 : null, unit: source === 'manual' ? 'price_times_quantity_currency_unspecified' : 'R' },
        account_scope: source === 'manual' ? null : 'Synthetic-Demo:1', policy_id: source === 'manual' ? null : 'policy1',
        approval_status: source === 'manual' ? 'approved' : null, native: { original_evidence: true, source } }
      return route.fulfill({ json: { source, items: empty ? [] : [row], next_cursor: cursor || empty ? null : `${source}-older` } })
    })
    await page.goto('/paper-trades')
    await page.getByLabel('Access key').fill('visual-test-viewer-key-0000000000000000')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    const evidence = page.getByRole('region', { name: 'Unified paper evidence' })
    await expect(evidence.getByRole('cell', { name: 'buy unresolved' })).toBeVisible()
    await expect(evidence).toContainText('Unavailable')
    await expect(page.getByRole('button', { name: 'Record paper trade', exact: true })).toBeDisabled()
    await evidence.getByRole('button', { name: 'Older evidence' }).click()
    await expect(evidence).toContainText('OLDER.a')
    await expect(evidence.getByRole('button', { name: 'Older evidence' })).toBeDisabled()
    await evidence.getByLabel('Evidence source').selectOption('manual')
    await expect(evidence).toContainText('MANUAL.a')
    await expect(evidence).toContainText('Price × quantity; currency unspecified')
    await expect(evidence).toContainText('Manual label: approved')
    await expect(evidence).not.toContainText('SCANNER.a')
    await evidence.getByText('Original record', { exact: true }).click()
    await expect(evidence).toContainText('original_evidence')
    await evidence.scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('unified-paper.png') })
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    fail = true
    await evidence.getByRole('button', { name: 'Latest evidence' }).click()
    await expect(evidence.getByRole('alert')).toContainText('Evidence temporarily unavailable')
    await expect(evidence).not.toContainText('MANUAL.a')
    fail = false; empty = true
    await evidence.getByRole('button', { name: 'Latest evidence' }).click()
    await expect(evidence).toContainText('No evidence in this source.')
    expect(requests).toContain('scanner:scanner-older')
    expect(requests).toContain('manual:first')
    expect(errors).toEqual([])
  })
}
