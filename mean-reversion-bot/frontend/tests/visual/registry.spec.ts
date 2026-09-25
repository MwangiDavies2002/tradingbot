import { test, expect, type Page } from '@playwright/test'
import fs from 'node:fs/promises'

const keys = {
  operator: 'visual-test-operator-key-0000000000000000',
  viewer: 'visual-test-viewer-key-0000000000000000',
}
async function login(page: Page, role: keyof typeof keys) {
  await page.getByLabel('Access key').fill(keys[role])
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Institutional research lab' })).toBeVisible()
}

for (const width of [1440, 390]) {
  test(`saved trials and role permissions at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    await page.goto('/institutional')
    await login(page, 'operator')
    const registry = page.getByRole('region', { name: 'Research registry', exact: true })
    await expect(registry.getByRole('button', { name: 'Search / refresh' })).toBeEnabled()
    const name = `UI trials ${width} ${Date.now()}`
    await registry.getByText('Declare a new trial family', { exact: true }).click()
    await registry.getByLabel('Family name', { exact: true }).fill(name)
    await registry.getByLabel('Hypothesis', { exact: true }).fill('Synthetic scenario comparison; not trading evidence.')
    await registry.getByRole('button', { name: 'Declare family', exact: true }).click()
    await expect(registry.getByRole('status')).toContainText('Family declared')
    const familyId = await registry.getByLabel('Declared family', { exact: true }).inputValue()
    await registry.getByLabel('Run name', { exact: true }).fill(`${name} baseline`)
    const save = registry.getByRole('button', { name: 'Run current scenario & save trial', exact: true })
    await save.click()
    await expect(registry.getByRole('status')).toContainText('baseline: succeeded')
    await expect(page.getByRole('region', { name: 'Analysis report', exact: true })).toBeVisible()
    await expect(registry).toContainText('Unattempted trials: variant')
    const table = registry.getByRole('table', { name: 'Saved trials' })
    const baseline = table.getByRole('row').filter({ hasText: `${name} baseline` })
    const download = page.waitForEvent('download')
    await baseline.getByRole('button', { name: 'Export', exact: true }).click()
    const artifact = JSON.parse(await fs.readFile((await (await download).path())!, 'utf8'))
    expect(artifact.registry.family_id).toBe(familyId)
    expect(artifact.registry.status).toBe('succeeded')
    expect(artifact.report.live_authorized).toBe(false)

    await page.getByRole('textbox', { name: 'Scenario JSON', exact: true }).fill('{}')
    await registry.getByLabel('Trial', { exact: true }).selectOption('variant')
    await registry.getByLabel('Run name', { exact: true }).fill(`${name} failed`)
    await save.click()
    await expect(registry.getByRole('status')).toContainText('variant: failed')
    await expect(page.getByRole('region', { name: 'Analysis report', exact: true })).toHaveCount(0)
    await expect(registry).toContainText('All declared trials have terminal outcomes.')
    await baseline.getByRole('button', { name: 'View', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Analysis report', exact: true })).toBeVisible()
    await table.getByRole('row').filter({ hasText: `${name} failed` }).getByRole('button', { name: 'View', exact: true }).click()
    await expect(registry.getByRole('status')).toContainText('failed')
    await expect(page.getByRole('region', { name: 'Analysis report', exact: true })).toHaveCount(0)

    await registry.getByLabel('Search run name', { exact: true }).fill(name)
    await registry.getByLabel('Status', { exact: true }).selectOption('failed')
    await registry.getByRole('button', { name: 'Search / refresh' }).click()
    await expect(table.getByRole('row')).toHaveCount(2)
    await expect(table).toContainText(`${name} failed`)
    await registry.getByLabel('Search run name', { exact: true }).fill('no-such-trial-000')
    await registry.getByRole('button', { name: 'Search / refresh' }).click()
    await expect(registry).toContainText('No matching saved trials.')

    await page.getByRole('link', { name: 'Instrument catalog', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Register revision', exact: true })).toBeDisabled()
    const deniedOperator = await page.request.post('http://127.0.0.1:8017/api/instruments/revisions', {
      headers: { Authorization: `Bearer ${keys.operator}` }, data: {},
    })
    expect(deniedOperator.status()).toBe(403)
    await page.getByRole('link', { name: 'Institutional lab', exact: true }).click()
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await login(page, 'viewer')
    await expect(page.getByRole('button', { name: 'Run offline analysis', exact: true })).toBeDisabled()
    await registry.getByText('Declare a new trial family', { exact: true }).click()
    await registry.getByLabel('Family name', { exact: true }).fill('Viewer cannot submit')
    await registry.getByLabel('Hypothesis', { exact: true }).fill('All required fields are populated.')
    await expect(registry.getByRole('button', { name: 'Declare family', exact: true })).toBeDisabled()
    await registry.getByLabel('Declared family', { exact: true }).selectOption(familyId)
    await registry.getByLabel('Run name', { exact: true }).fill('Viewer cannot run')
    await expect(save).toBeDisabled()
    await registry.getByRole('button', { name: 'Check family completeness' }).click()
    await expect(registry).toContainText('All declared trials have terminal outcomes.')
    await registry.getByLabel('Search run name', { exact: true }).fill(name)
    await registry.getByRole('button', { name: 'Search / refresh' }).click()
    await expect(table.getByRole('row')).toHaveCount(3)
    await baseline.getByRole('button', { name: 'View', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Analysis report', exact: true })).toBeVisible()
    const viewerDownload = page.waitForEvent('download')
    await baseline.getByRole('button', { name: 'Export', exact: true }).click()
    const viewerArtifact = JSON.parse(await fs.readFile((await (await viewerDownload).path())!, 'utf8'))
    expect(viewerArtifact).toEqual(artifact)
    for (const path of ['/api/research-registry/families', '/api/research-registry/runs', '/api/institutional/route']) {
      const response = await page.request.post(`http://127.0.0.1:8017${path}`, {
        headers: { Authorization: `Bearer ${keys.viewer}` }, data: {},
      })
      expect(response.status()).toBe(403)
    }
    await registry.scrollIntoViewIfNeeded()
    await page.screenshot({ path: testInfo.outputPath('viewer-registry.png') })
    expect(await page.locator('main').evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}
