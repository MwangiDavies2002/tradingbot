const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const ts = require('typescript')
const source = fs.readFileSync(path.join(__dirname, '../src/tradingview/strategy.ts'), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const mod = { exports: {} }
vm.runInNewContext(compiled, { exports: mod.exports, module: mod })
const { buildPineStrategy, selectionError, DEFAULT_SELECTION } = mod.exports

test('thresholds 1, 2 and 3 are exported without a mandatory six', () => {
  for (const value of [1, 2, 3]) {
    const pine = buildPineStrategy(DEFAULT_SELECTION, value)
    assert.ok(pine.includes(`threshold = input.int(${value},`))
  }
})
test('single Bollinger indicator supports one point', () => {
  assert.equal(selectionError({ use_bb: true }, 1), null)
  assert.ok(buildPineStrategy({ use_bb: true }, 1).includes('useBb = input.bool(true,'))
  assert.throws(() => buildPineStrategy({ use_bb: true }, 2), /1 to 1/)
})
test('context-only, invalid and unsupported configurations are rejected', () => {
  for (const value of [0, -1, 1.5, 21, NaN]) assert.ok(selectionError(DEFAULT_SELECTION, value))
  assert.match(selectionError({ use_volume: true }, 1), /directional/)
  assert.match(selectionError({ use_lsl: true, use_bb: true }, 1), /does not implement LSL/)
})
test('indicator toggles are exported and the symbol is restricted', () => {
  const pine = buildPineStrategy({ use_rsi: true }, 2)
  assert.ok(pine.includes('useZ = input.bool(false,'))
  assert.ok(pine.includes('useRsi = input.bool(true,'))
  assert.ok(pine.includes('syminfo.tickerid != "DERIV:VOLATILITY_75_1S_INDEX"'))
  assert.ok(pine.includes('barstate.isconfirmed'))
  assert.ok(pine.includes('strategy.exit('))
})
