import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'

for (const width of [1440, 390]) {
  test(`forward scanner at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 })
    const errors: string[] = []
    page.on('pageerror', e => errors.push(e.message))
    let state: any = { run: null, latest: [], execution_enabled: false }
    const requests: any[] = []
    const observed = Date.now()/1000
    const row = { id:'signal1', symbol:'EURUSD.a', observed, regime:'RANGE', deviation:-2.1, score:40, direction:'buy', eligible:true, reasons:['zscore_reversion'] }
    await page.route('**/api/mt5/symbols', route => route.fulfill({ json: { symbols: ['EURUSD.a','XAUUSD','GER40.cash'].map(name => ({ name, description:name, eligible:true })) } }))
    await page.route('**/api/scanner**', async route => {
      const url=route.request().url()
      if (url.endsWith('/export')) return route.fulfill({ json: {schema_version:1,execution_enabled:false,runs:[state.run],observations:[row],trades:[]}, headers:{'Content-Disposition':'attachment; filename="scanner-evidence.json"'} })
      if (url.includes('/records?')) {
        const params=new URL(url).searchParams
        const older=params.has('before')
        if (older) { expect(params.get('through')).toBe('100'); expect(params.get('before')).toBe('100') }
        return route.fulfill({ json:{kind:params.get('kind'),items:[{...row,id:older?'old':'new',record_cursor:older?99:100,symbol:older?'GER40.cash':'EURUSD.a',scope:'Test-Demo:123',state:params.get('kind')==='trades'?'closed':undefined}],total:2,through:100,next_before:older?null:100} })
      }
      if (url.endsWith('/ledger')) return route.fulfill({ json: { observations:state.latest, trades:state.latest.length ? [{...row,state:'closed',entry:1.1,stop:1.09,target:1.12,r_multiple:1.9,exit_reason:'target'}] : [] } })
      if (url.endsWith('/analytics')) return route.fulfill({ json: { observations:state.latest.length, overall:{count:state.latest.length,sample:'exploratory'}, groups:{symbol:{'EURUSD.a':{count:1,mean_r:1.9,win_rate:1,sample:'exploratory'}}, news:{unknown:{count:1,mean_r:1.9,win_rate:1,sample:'exploratory'}}}, states:{closed:state.latest.length}, per_pair_policy:state.latest.length ? [{scope:'Test-Demo:123',symbol:'EURUSD.a',timeframe:'M5',policy_id:'policy1',research_run_id:'research1',run_ids:['scan1'],observations:2,count:1,mean_r:1.9,win_rate:1,sample:'exploratory',states:{closed:1,unresolved:1}}] : [], model:'Synthetic UI fixture; no broker orders.' } })
      if (url.endsWith('/start')) {
        const config=route.request().postDataJSON(); requests.push(config)
        state={run:{id:'scan1',created:observed,status:'running',config:{...config,poll_seconds:45,max_spread_atr:.15,slippage_atr:.03,max_hold_bars:7}},latest:[row,{...row,symbol:'XAUUSD',regime:'TREND',eligible:false,reasons:['Trend gate blocks mean reversion']}],execution_enabled:false}
      }
      if (url.endsWith('/stop')) state.run.status='stopped'
      return route.fulfill({json:state})
    })
    await page.goto('/scanner')
    await page.getByLabel('Access key').fill('visual-test-admin-key-0000000000000000')
    await page.getByRole('button',{name:'Sign in',exact:true}).click()
    await expect(page.getByRole('button',{name:'Start paper scanner'})).toBeDisabled()
    await page.getByRole('button',{name:'Load broker symbols'}).click()
    await page.getByRole('button',{name:'EURUSD.a',exact:true}).click()
    await page.getByRole('button',{name:'XAUUSD',exact:true}).click()
    await page.getByLabel('Paper spread model').selectOption('candle_proxy_v1')
    await page.getByRole('button',{name:'Start paper scanner'}).click()
    expect(requests[0].spread_model).toBe('candle_proxy_v1')
    await expect(page.getByLabel('Paper spread model')).toBeDisabled()
    expect(requests[0].assets).toEqual([{symbol:'EURUSD.a'},{symbol:'XAUUSD'}])
    await expect(page.getByRole('button',{name:'EURUSD.a',exact:true})).toBeDisabled()
    await expect(page.getByText('No trade: Trend gate blocks mean reversion')).toBeVisible()
    await expect(page.getByRole('heading',{name:'Forward evidence by pair and policy'})).toBeVisible()
    await expect(page.getByText('Test-Demo:123 / EURUSD.a')).toBeVisible()
    await expect(page.getByText('1 / 300 (exploratory)')).toBeVisible()
    await page.getByLabel('Break down by').selectOption('news')
    await expect(page.getByRole('cell',{name:'unknown',exact:true})).toBeVisible()
    await page.getByRole('button',{name:'Stop scanner'}).click()
    await expect(page.getByRole('button',{name:'Start paper scanner'})).toBeEnabled()
    await page.getByLabel('Minimum weighted score').fill('12')
    await page.getByLabel('Paper spread model').selectOption('fixed_quote')
    await page.getByRole('button',{name:'Load saved scanner settings'}).click()
    await expect(page.getByLabel('Minimum weighted score')).toHaveValue('6')
    await expect(page.getByLabel('Paper spread model')).toHaveValue('candle_proxy_v1')
    await page.getByRole('button',{name:'Start paper scanner'}).click()
    expect(requests[1]).toMatchObject({poll_seconds:45,max_spread_atr:.15,slippage_atr:.03,max_hold_bars:7})
    await page.getByRole('button',{name:'Stop scanner'}).click()
    const evidence=page.getByRole('region',{name:'Saved scanner evidence'})
    await evidence.getByRole('button',{name:'Latest records'}).click()
    await expect(evidence).toContainText('1 shown | 2 records in this browsing window')
    await evidence.getByRole('button',{name:'Older records'}).click()
    await expect(evidence).toContainText('GER40.cash')
    await expect(evidence.getByRole('button',{name:'Older records'})).toBeDisabled()
    await page.getByLabel('Record type').selectOption('trades')
    await evidence.getByRole('button',{name:'Latest records'}).click()
    await expect(evidence).toContainText('closed')
    const downloaded=page.waitForEvent('download')
    await page.getByRole('button',{name:'Download all evidence (JSON)',exact:true}).click()
    const file=await downloaded
    expect(file.suggestedFilename()).toBe('scanner-evidence.json')
    const exported=JSON.parse(await readFile((await file.path())!, 'utf8'))
    expect(exported.execution_enabled).toBe(false)
    expect(exported.observations[0].symbol).toBe('EURUSD.a')
    await evidence.scrollIntoViewIfNeeded()
    await page.screenshot({path:testInfo.outputPath('scanner-evidence.png')})
    await page.getByRole('heading',{name:'Forward scanner',exact:true}).scrollIntoViewIfNeeded()
    await page.screenshot({path:testInfo.outputPath('scanner.png'),fullPage:true})
    await page.getByRole('heading',{name:'Automatic paper ledger',exact:true}).scrollIntoViewIfNeeded()
    await page.screenshot({path:testInfo.outputPath('scanner-ledger.png')})
    expect(await page.locator('main').evaluate(el=>el.scrollWidth<=el.clientWidth)).toBe(true)
    expect(errors).toEqual([])
  })
}
