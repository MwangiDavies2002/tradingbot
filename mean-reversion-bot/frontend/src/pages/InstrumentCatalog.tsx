import { useEffect, useState } from 'react'
import { api } from '../api/client'
import examples from '../data/institutional-examples.json'

type Revision = { spec_hash: string; instrument_id: string; venue: string; venue_symbol: string; revision: string; registered_at: string }
type Plan = { catalog: Revision; catalog_observed_by_decision: boolean; note: string;
  report: { request: object; report_id: string; result: Record<string, unknown> } }
const { instrument: exampleSpec, ...examplePlan } = examples['instrument-plan'].input

export default function InstrumentCatalog() {
  const [spec, setSpec] = useState(JSON.stringify(exampleSpec, null, 2))
  const [scenario, setScenario] = useState(JSON.stringify(examplePlan, null, 2))
  const [rows, setRows] = useState<Revision[]>([])
  const [selected, setSelected] = useState<Revision | null>(null)
  const [report, setReport] = useState<Plan | null>(null)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  async function act(action: () => Promise<void>) {
    setBusy(true); setError(''); setMessage('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  async function load(page = 0) {
    const query = new URLSearchParams({ q: search, limit: '25', offset: String(page) })
    const data = await api.get(`/api/instruments/revisions?${query}`) as { revisions: Revision[] }
    setRows(data.revisions); setOffset(page)
  }
  useEffect(() => { void act(() => load()) }, [])
  async function select(row: Revision) {
    const data = await api.get(`/api/instruments/revisions/${row.spec_hash}`) as Revision & { spec: object }
    setSelected(row); setSpec(JSON.stringify(data.spec, null, 2)); setReport(null)
  }
  async function register() {
    const row = await api.post('/api/instruments/revisions', JSON.parse(spec)) as Revision
    setSelected(row); setReport(null); await load()
    setMessage('Revision registered. Changes require a new revision identifier.')
  }
  async function plan() {
    setReport(null)
    setReport(await api.post('/api/instruments/plans', { ...JSON.parse(scenario), spec_hash: selected?.spec_hash }) as Plan)
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `instrument-plan-${report?.report.report_id.slice(0, 12)}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const editor = 'block w-full mt-2 h-72 p-3 font-mono text-xs bg-slate-950 border border-slate-600 rounded'
  return <div className="p-6 max-w-6xl space-y-6">
    <header><h1 className="text-2xl font-bold">Instrument catalog</h1><p className="text-slate-400 mt-2">Preserve instrument revisions and build execution plans against their exact rules.</p></header>
    <p className="rounded-lg border border-amber-700/50 bg-amber-950/30 p-4 text-sm text-amber-200">The prefilled specification and book are synthetic. Register provider-verified metadata before using real data. Plans are offline projections and never submit orders.</p>
    <fieldset disabled={busy} className="space-y-6">
      <section className="bg-slate-800 rounded-xl p-5 space-y-3">
        <h2 className="font-semibold text-lg">Stored revisions</h2>
        <div className="flex gap-3"><input aria-label="Search instrument ID" placeholder="Search instrument ID" className="flex-1 bg-slate-950 rounded p-2 border border-slate-600" value={search} onChange={e => setSearch(e.target.value)} /><button className="px-4 py-2 bg-slate-700 rounded" onClick={() => void act(() => load())}>Search / refresh</button></div>
        <div className="overflow-auto"><table className="w-full text-left text-sm"><thead className="text-slate-400"><tr><th className="p-2">Instrument</th><th className="p-2">Venue</th><th className="p-2">Revision</th><th className="p-2">Select</th></tr></thead><tbody>
          {rows.map(row => <tr key={row.spec_hash} className="border-t border-slate-700"><td className="p-2">{row.instrument_id}<div className="text-xs text-slate-400">{row.venue_symbol}</div></td><td className="p-2">{row.venue}</td><td className="p-2">{row.revision}</td><td className="p-2"><button onClick={() => void act(() => select(row))} className="text-cyan-300">{selected?.spec_hash === row.spec_hash ? 'Selected' : 'Use revision'}</button></td></tr>)}
        </tbody></table></div>
        {!rows.length && <p className="text-sm text-slate-400">No matching revisions. An administrator can register a specification below.</p>}
        <div className="flex gap-3 text-sm"><button disabled={offset === 0} onClick={() => void act(() => load(Math.max(0, offset - 25)))}>Previous</button><span>Page {offset / 25 + 1}</span><button disabled={rows.length < 25} onClick={() => void act(() => load(offset + 25))}>Next</button></div>
      </section>
      <div className="grid lg:grid-cols-2 gap-5">
        <section className="bg-slate-800 rounded-xl p-5 space-y-3 min-w-0"><h2 className="font-semibold">Register a specification (admin)</h2>
          <p className="text-sm text-slate-400">Publication and validity times, sessions, contract size and grids must come from the provider. Stored revisions cannot be edited or deleted.</p>
          <label className="block text-sm">Specification JSON<textarea aria-label="Instrument specification JSON" className={editor} spellCheck={false} value={spec} onChange={e => setSpec(e.target.value)} /></label>
          <button onClick={() => void act(register)} className="bg-slate-700 px-4 py-2 rounded">Register revision</button>
        </section>
        <section className="bg-slate-800 rounded-xl p-5 space-y-3 min-w-0"><h2 className="font-semibold">Plan against selected revision</h2>
          <p className="text-sm text-slate-400">Book quantities use native lots/contracts. Prices use quote currency per underlying unit. The selected stored revision is used; edits in the specification editor do not alter it.</p>
          <p className="text-xs break-all text-cyan-200">{selected ? `Pinned: ${selected.venue_symbol} / ${selected.revision} / ${selected.spec_hash}` : 'Select or register a revision first.'}</p>
          <label className="block text-sm">Order and native book JSON<textarea aria-label="Order planning JSON" className={editor} spellCheck={false} value={scenario} onChange={e => { setScenario(e.target.value); setReport(null) }} /></label>
          <button disabled={!selected} onClick={() => void act(plan)} className="bg-cyan-700 px-4 py-2 rounded disabled:opacity-50">Generate offline plan</button>
        </section>
      </div>
    </fieldset>
    {busy && <p role="status" className="text-slate-400">Working...</p>}
    {error && <p role="alert" className="text-red-300 whitespace-pre-wrap break-words text-sm">{error}</p>}
    {message && <p role="status" className="text-cyan-200 text-sm">{message}</p>}
    {report && <section className="bg-slate-800 rounded-xl p-5 space-y-4">
      <div className="flex justify-between flex-wrap gap-3"><h2 className="font-semibold text-lg">Instrument execution plan</h2><button onClick={download} className="rounded bg-slate-700 px-4 py-2">Download plan &amp; specification</button></div>
      {!report.catalog_observed_by_decision && <p className="text-amber-200 text-sm">This catalog revision was registered after the scenario decision time. The plan uses backfilled metadata.</p>}
      <p className="text-sm text-slate-400">{report.note}</p>
      <pre className="bg-slate-950 p-4 rounded text-xs overflow-auto max-h-[600px]">{JSON.stringify(report.report.result, null, 2)}</pre>
    </section>}
  </div>
}
