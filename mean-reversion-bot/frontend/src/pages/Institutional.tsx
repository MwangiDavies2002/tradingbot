import { useState } from 'react'
import { api } from '../api/client'
import ResearchRegistry from '../components/ResearchRegistry'
import LifecycleReport from '../components/LifecycleReport'

import exampleData from '../data/institutional-examples.json'

const examples: Record<string, { label: string; description: string; input: object }> = exampleData

type Report = { operation: string; report_id: string; result: Record<string, unknown> }

export default function Institutional() {
  const [operation, setOperation] = useState('route')
  const [input, setInput] = useState(JSON.stringify(examples.route.input, null, 2))
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [registryBusy, setRegistryBusy] = useState(false)
  const blocked = busy || registryBusy
  const [error, setError] = useState('')
  function change(value: string) {
    setOperation(value); setInput(JSON.stringify(examples[value].input, null, 2)); setReport(null); setError('')
  }
  async function run() {
    setBusy(true); setError(''); setReport(null)
    try {
      if (new TextEncoder().encode(input).length > 2000000) throw new Error('Scenario exceeds 2 MB. Use the offline CLI for larger inputs.')
      setReport(await api.post(`/api/institutional/${operation}`, JSON.parse(input)) as Report)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `institutional-${report?.operation}-${report?.report_id.slice(0, 12)}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const metrics = report ? Object.entries(report.result).filter(([, value]) => typeof value === 'number').slice(0, 8) : []
  return <div className="p-4 sm:p-6 max-w-6xl space-y-6 min-w-0">
    <header><h1 className="text-2xl font-bold">Institutional research lab</h1>
      <p className="text-slate-400 mt-2">Explore market data, execution, portfolio risk and models with reproducible offline analyses.</p></header>
    <p className="rounded-lg border border-amber-700/50 bg-amber-950/30 p-4 text-sm text-amber-200">Examples use synthetic data. These analyses produce research reports and never submit orders. Real feeds, costs and execution still require validation.</p>
    <div className="grid lg:grid-cols-[230px_1fr] gap-5">
      <nav aria-label="Research analyses" className="space-y-1">
        {Object.entries(examples).map(([key, value]) => <button key={key} disabled={blocked} onClick={() => change(key)} aria-pressed={key === operation}
          className={`block w-full text-left p-3 rounded-lg text-sm ${key === operation ? 'bg-cyan-900 text-cyan-200' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'} disabled:opacity-60`}>{value.label}</button>)}
      </nav>
      <section className="bg-slate-800 rounded-xl p-5 space-y-4 min-w-0">
        <h2 className="font-semibold text-lg">{examples[operation].label}</h2>
        <p className="text-sm text-slate-400">{examples[operation].description}</p>
        <p className="text-xs text-slate-400">Times are UTC epoch milliseconds. Prices and sizes use asset units; portfolio values must share one currency. Edit the example or import your scenario.</p>
        <label className="block text-sm">Import scenario JSON<input type="file" accept=".json" disabled={blocked} className="block mt-2" onChange={async e => {
          const file = e.target.files?.[0]; if (!file) return
          if (file.size > 2000000) { setError('Scenario exceeds 2 MB.'); return }
          try { setInput(await file.text()); setReport(null); setError('') }
          catch { setError('Could not read scenario file.') }
        }} /></label>
        <label className="block text-sm">Scenario<textarea aria-label="Scenario JSON" disabled={blocked} spellCheck={false} value={input} onChange={e => { setInput(e.target.value); setReport(null) }} className="mt-2 w-full h-72 rounded bg-slate-950 border border-slate-600 p-3 font-mono text-xs" /></label>
        <button disabled={blocked} onClick={run} className="rounded bg-cyan-700 px-4 py-2 disabled:opacity-50">{busy ? 'Analyzing...' : 'Run offline analysis'}</button>
        {error && <p role="alert" className="text-red-300 whitespace-pre-wrap break-words text-sm">{error}</p>}
      </section>
    </div>
    <ResearchRegistry operation={operation} input={input} disabled={busy} onReport={setReport} onBusyChange={setRegistryBusy} />
    {report && <section aria-label="Analysis report" className="bg-slate-800 rounded-xl p-5 space-y-4 min-w-0">
      <div className="flex flex-wrap gap-3 justify-between items-center"><h2 className="font-semibold text-lg">{examples[report.operation]?.label || report.operation} report</h2><button onClick={download} className="rounded bg-slate-700 px-4 py-2">Download reproducible report</button></div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{metrics.map(([name, value]) => <div key={name} className="bg-slate-900 rounded p-3"><div className="text-xs text-slate-400">{name.replace(/_/g, ' ')}</div><div className="text-lg font-mono mt-1">{Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 })}</div></div>)}</div>
      <p className="text-xs text-slate-400 break-all">Report ID: {report.report_id}</p>
      {report.operation === 'order-lifecycle' && <LifecycleReport result={report.result} />}
      <details open={report.operation !== 'order-lifecycle'}><summary className="cursor-pointer text-sm">Full results and assumptions</summary><pre className="mt-3 p-4 bg-slate-950 rounded text-xs overflow-auto max-h-[500px]">{JSON.stringify(report.result, null, 2)}</pre></details>
    </section>}
  </div>
}
