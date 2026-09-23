import { useEffect, useState } from 'react'
import { api } from '../api/client'

type Report = { operation: string; report_id: string; result: Record<string, unknown> }
type Family = { family_id: string; name: string; hypothesis: string; trial_keys: string[] }
type Run = { run_id: string; family_id: string; trial_key: string; name: string; operation: string; status: string; created_at: string; error: string | null }
type ExportedRun = { registry: Run; input_payload: object; report: Report | null }
const newId = () => crypto.randomUUID().replace(/-/g, '')

export default function ResearchRegistry({ operation, input, disabled, onReport, onBusyChange }: {
  operation: string; input: string; disabled: boolean; onReport: (report: Report) => void; onBusyChange: (busy: boolean) => void
}) {
  const [families, setFamilies] = useState<Family[]>([])
  const [familyId, setFamilyId] = useState('')
  const [trial, setTrial] = useState('')
  const [familyName, setFamilyName] = useState('')
  const [hypothesis, setHypothesis] = useState('')
  const [trialKeys, setTrialKeys] = useState('baseline, variant')
  const [draftId, setDraftId] = useState(newId)
  const [runName, setRunName] = useState('')
  const [dataset, setDataset] = useState('synthetic-example-v1')
  const [parent, setParent] = useState('')
  const [runs, setRuns] = useState<Run[]>([])
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [manifest, setManifest] = useState<{ all_trials_terminal: boolean; unattempted_trial_keys: string[]; runs: Run[] } | null>(null)
  const control = 'block w-full mt-1 rounded bg-slate-950 border border-slate-600 p-2 text-sm'
  const selected = families.find(f => f.family_id === familyId)

  async function loadRuns(page = 0) {
    const query = new URLSearchParams({ q: search, limit: '25', offset: String(page) })
    if (status) query.set('status', status)
    const result = await api.get(`/api/research-registry/runs?${query}`) as { runs: Run[] }
    setRuns(result.runs); setOffset(page)
  }
  async function loadFamilies() {
    const result = await api.get('/api/research-registry/families?limit=100') as { families: Family[] }
    setFamilies(result.families)
  }
  async function act(action: () => Promise<void>) {
    setBusy(true); onBusyChange(true); setError(''); setMessage('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false); onBusyChange(false) }
  }
  useEffect(() => { void act(async () => { await loadFamilies(); await loadRuns() }) }, [])

  async function declare() {
    const keys = trialKeys.split(',').map(s => s.trim()).filter(Boolean)
    const result = await api.post('/api/research-registry/families', {
      family_id: draftId, name: familyName, hypothesis, trial_keys: keys,
    }) as Family
    await loadFamilies(); setFamilyId(result.family_id); setTrial(result.trial_keys[0]); setManifest(null)
    setDraftId(newId()); setMessage('Family declared. Its hypothesis and trial list are now immutable.')
  }
  async function saveRun() {
    const result = await api.post('/api/research-registry/runs', {
      family_id: familyId, trial_key: trial, name: runName, operation,
      dataset_version: dataset, parent_run_id: parent.trim() || null, payload: JSON.parse(input),
    }) as Run
    setMessage(`Trial ${result.trial_key}: ${result.status}. ${result.error || ''}`)
    await loadRuns()
    setManifest(await api.get(`/api/research-registry/families/${familyId}`) as typeof manifest)
    if (result.status === 'succeeded') {
      const saved = await api.get(`/api/research-registry/runs/${result.run_id}/export`) as ExportedRun
      if (saved.report) onReport(saved.report)
    }
  }
  async function exportRun(run: Run, display: boolean) {
    const saved = await api.get(`/api/research-registry/runs/${run.run_id}/export`) as ExportedRun
    if (display) {
      if (saved.report) onReport(saved.report)
      else setMessage(`Run ${run.run_id}: ${run.status}. ${run.error || 'No terminal report yet.'}`)
      return
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify(saved, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `research-${run.run_id}.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="bg-slate-800 rounded-xl p-5 space-y-4" aria-label="Research registry">
    <h2 className="font-semibold text-lg">Research registry</h2>
    <p className="text-sm text-slate-400">Declare the full trial family before running it. Saved requests and outcomes cannot be edited or deleted. Failed trials remain in history.</p>
    <fieldset disabled={busy || disabled} className="space-y-4">
    <details><summary className="cursor-pointer">Declare a new trial family</summary>
      <div className="grid md:grid-cols-2 gap-3 mt-3">
        <label>Family name<input className={control} value={familyName} maxLength={128} onChange={e => setFamilyName(e.target.value)} /></label>
        <label>Trial keys, comma-separated<input className={control} value={trialKeys} onChange={e => setTrialKeys(e.target.value)} /></label>
        <label className="md:col-span-2">Hypothesis<textarea className={control} value={hypothesis} maxLength={4000} onChange={e => setHypothesis(e.target.value)} /></label>
      </div>
      <button disabled={busy || disabled || !familyName || !hypothesis} onClick={() => void act(declare)} className="mt-3 px-4 py-2 rounded bg-slate-700 disabled:opacity-50">Declare family</button>
    </details>
    <div className="grid md:grid-cols-2 gap-3 text-sm">
      <label>Declared family<select className={control} value={familyId} onChange={e => {
        setFamilyId(e.target.value); setTrial(families.find(f => f.family_id === e.target.value)?.trial_keys[0] || ''); setManifest(null)
      }}><option value="">Select a family (latest 100)</option>{families.map(f => <option key={f.family_id} value={f.family_id}>{f.name} · {f.family_id.slice(0, 8)}</option>)}</select></label>
      <label>Trial<select className={control} value={trial} onChange={e => setTrial(e.target.value)}>{selected?.trial_keys.map(key => <option key={key}>{key}</option>)}</select></label>
      <label>Run name<input className={control} value={runName} maxLength={128} onChange={e => setRunName(e.target.value)} /></label>
      <label>Dataset/source version<input className={control} value={dataset} maxLength={256} onChange={e => setDataset(e.target.value)} /></label>
      <label className="md:col-span-2">Parent run ID (optional)<input className={control} value={parent} onChange={e => setParent(e.target.value)} /></label>
    </div>
    {selected && <p className="text-sm text-slate-300">Declared hypothesis: {selected.hypothesis}</p>}
    <div className="flex flex-wrap gap-2">
      <button disabled={busy || disabled || !familyId || !trial || !runName || !dataset} onClick={() => void act(saveRun)} className="px-4 py-2 rounded bg-cyan-700 disabled:opacity-50">Run current scenario &amp; save trial</button>
      <button disabled={busy || !familyId} onClick={() => void act(async () => setManifest(await api.get(`/api/research-registry/families/${familyId}`) as typeof manifest))} className="px-4 py-2 rounded bg-slate-700 disabled:opacity-50">Check family completeness</button>
    </div>
    {manifest && <p className="text-sm text-slate-300">{manifest.all_trials_terminal ? 'All declared trials have terminal outcomes.' : `Unattempted trials: ${manifest.unattempted_trial_keys.join(', ') || 'none'}. Pending: ${manifest.runs.filter(r => r.status === 'pending').length}.`} Completeness does not establish a valid strategy.</p>}
    <div className="flex flex-wrap gap-2 items-end">
      <label className="flex-1 text-sm">Search run name<input className={control} value={search} onChange={e => setSearch(e.target.value)} /></label>
      <label className="text-sm">Status<select className={control} value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option>{['pending', 'succeeded', 'failed', 'aborted'].map(s => <option key={s}>{s}</option>)}</select></label>
      <button disabled={busy} onClick={() => void act(() => loadRuns())} className="px-4 py-2 rounded bg-slate-700">Search / refresh</button>
    </div>
    {error && <p role="alert" className="text-red-300 text-sm whitespace-pre-wrap break-words">{error}</p>}
    {message && <p role="status" className="text-cyan-200 text-sm break-words">{message}</p>}
    <div className="overflow-auto"><table className="w-full text-sm text-left"><thead className="text-slate-400"><tr><th className="p-2">Run</th><th className="p-2">Trial</th><th className="p-2">Status</th><th className="p-2">Actions</th></tr></thead>
      <tbody>{runs.map(run => <tr key={run.run_id} className="border-t border-slate-700"><td className="p-2">{run.name}<div className="text-xs text-slate-400">{run.operation} · {run.created_at}</div><div className="text-xs font-mono">{run.run_id}</div></td><td className="p-2">{run.trial_key}</td><td className="p-2">{run.status}</td><td className="p-2 whitespace-nowrap"><button disabled={busy} onClick={() => void act(() => exportRun(run, true))} className="mr-3 text-cyan-300">View</button><button disabled={busy} onClick={() => void act(() => exportRun(run, false))} className="text-cyan-300">Export</button></td></tr>)}</tbody>
    </table></div>
    {!runs.length && <p className="text-sm text-slate-400">No matching saved trials.</p>}
    <div className="flex gap-3 text-sm"><button disabled={busy || offset === 0} onClick={() => void act(() => loadRuns(Math.max(0, offset - 25)))}>Previous</button><span>Page {offset / 25 + 1}</span><button disabled={busy || runs.length < 25} onClick={() => void act(() => loadRuns(offset + 25))}>Next</button></div>
    </fieldset>
  </section>
}
