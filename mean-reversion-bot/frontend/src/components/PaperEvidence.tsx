import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'

type Source = 'manual' | 'scanner'
type Evidence = {
  id: string; source: Source; source_id: string; symbol: string; timeframe: string | null;
  direction: string; state: string; recorded_at: string | null; entry: number | null;
  stop: number | null; target: number | null; exit: number | null;
  outcome: { value: number | null; unit: string }; account_scope: string | null;
  policy_id: string | null; approval_status: string | null; native: unknown;
}
type Page = { source: Source; items: Evidence[]; next_cursor: string | null }
const button = 'px-3 py-2 rounded bg-slate-700 disabled:opacity-40'

export default function PaperEvidence() {
  const [source, setSource] = useState<Source>('scanner')
  const [page, setPage] = useState<Page | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const requestId = useRef(0)
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)

  async function load(cursor?: string) {
    const id = ++requestId.current
    setBusy(true); setError('')
    try {
      const result = await api.get(`/api/scanner/paper-evidence?source=${source}&limit=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`) as Page
      if (id === requestId.current) setPage(result)
    } catch (err) {
      if (id === requestId.current) { setPage(null); setError(String(err)) }
    } finally { if (id === requestId.current) setBusy(false) }
  }
  useEffect(() => {
    setPage(null)
    if (local) void load()
    return () => { requestId.current += 1 }
  }, [source])

  return <section aria-label="Unified paper evidence" className="bg-slate-800 rounded-xl p-5 space-y-4">
    <h2 className="font-semibold">Unified paper evidence</h2>
    <p className="text-sm text-slate-400">Browse manual entries and automatic scanner outcomes in one read-only view. Manual results use price change × quantity with unspecified currency; scanner results use R. Their returns are not pooled.</p>
    {!local ? <p>Open the local app to include the scanner journal.</p> : <>
      <div className="flex flex-wrap items-end gap-3">
        <label>Evidence source<select className="block mt-1 bg-slate-900 p-2 rounded" value={source} onChange={e => setSource(e.target.value as Source)}><option value="scanner">Automatic scanner</option><option value="manual">Manual entries</option></select></label>
        <button className={button} disabled={busy} onClick={() => void load()}>Latest evidence</button>
        <button className={button} disabled={busy || page?.source !== source || !page?.next_cursor} onClick={() => void load(page?.next_cursor || undefined)}>Older evidence</button>
        {busy && <span role="status">Loading evidence…</span>}
      </div>
      {error && <p role="alert" className="text-red-300 break-words">{error}</p>}
      {page && page.source === source && <>
        <p className="text-sm text-slate-400">{page.items.length} records shown. States may update during browsing. Approval labels never authorize broker orders.</p>
        <div className="overflow-x-auto"><table className="w-full min-w-[950px] text-sm text-left [&_th]:p-2 [&_td]:p-2">
          <thead><tr>{['Source / instrument', 'Recorded', 'Side / state', 'Entry / exit', 'Stop / target', 'Outcome', 'Provenance'].map(h => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{page.items.map(row => <tr key={row.id} className="border-t border-slate-700">
            <td>{row.source === 'manual' ? 'Manual' : 'Scanner'}<strong className="block">{row.symbol}</strong>{row.timeframe || 'Unknown timeframe'}</td>
            <td>{row.recorded_at ? new Date(row.recorded_at).toLocaleString() : 'Unknown'}</td>
            <td>{row.direction}<span className="block">{row.state}</span></td>
            <td>{row.entry ?? '—'} / {row.exit ?? '—'}</td><td>{row.stop ?? '—'} / {row.target ?? '—'}</td>
            <td>{row.outcome.value == null ? 'Unavailable' : row.outcome.value.toFixed(3)}<span className="block text-xs text-slate-400">{row.outcome.unit === 'R' ? 'R' : 'Price × quantity; currency unspecified'}</span></td>
            <td className="max-w-xs break-words">{row.account_scope || 'Account not recorded'}{row.approval_status && <p>Manual label: {row.approval_status}</p>}<details><summary className="text-cyan-300 cursor-pointer">Original record</summary><p>Source ID: {row.source_id}</p><p>Policy: {row.policy_id || 'Not recorded'}</p><pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(row.native, null, 2)}</pre></details></td>
          </tr>)}</tbody>
        </table></div>
        {!page.items.length && <p>No evidence in this source.</p>}
      </>}
    </>}
  </section>
}
