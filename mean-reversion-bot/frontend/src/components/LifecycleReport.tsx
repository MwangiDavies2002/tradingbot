type Row = Record<string, string | number | boolean | null>
type Result = {
  ending_inventory: string; cash_change: string; fees: string; marked_pnl: string;
  ending_reservations: { buy: string; sell: string }; venue_online?: boolean;
  orders: Row[]; fills: Row[]; audit: Row[]; limitations: string[]
}

function Table({ title, rows, columns }: { title: string; rows: Row[]; columns: [string, string][] }) {
  return <section className="min-w-0 space-y-2"><h3 className="font-semibold">{title} <span className="text-slate-400">({rows.length})</span></h3>
    <div className="overflow-x-auto rounded border border-slate-700" tabIndex={0} aria-label={`${title} table`}>
      <table className="w-full text-left text-sm whitespace-nowrap"><thead className="bg-slate-900 text-slate-400"><tr>{columns.map(([key, label]) => <th key={key} className="px-3 py-2">{label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index} className="border-t border-slate-700">{columns.map(([key]) => <td key={key} className="px-3 py-2 font-mono">{String(row[key] ?? '—').replaceAll('_', ' ')}</td>)}</tr>)}</tbody>
      </table>{rows.length === 0 && <p className="p-3 text-slate-400">No {title.toLowerCase()} in this scenario.</p>}
    </div></section>
}

export default function LifecycleReport({ result }: { result: Record<string, unknown> }) {
  const data = result as unknown as Result
  const metrics = [['Ending inventory', data.ending_inventory], ['Marked P&L', data.marked_pnl],
    ['Cash change', data.cash_change], ['Fees', data.fees], ['Reserved buys', data.ending_reservations.buy], ['Reserved sells', data.ending_reservations.sell]]
  return <div aria-label="Order lifecycle results" className="space-y-5 min-w-0">
    <p className="text-sm text-cyan-200">Venue at end: {data.venue_online === false ? 'Halted' : 'Online'} · Offline scenario</p>
    <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">{metrics.map(([label, value]) => <div key={label} className="rounded bg-slate-900 p-3 min-w-0"><p className="text-xs text-slate-400">{label}</p><p className="font-mono text-lg break-all">{value}</p></div>)}</div>
    <Table title="Orders" rows={data.orders} columns={[["order_id", "Order"], ["side", "Side"], ["status", "State"], ["quantity", "Quantity"], ["filled", "Filled"], ["remaining", "Remaining"]]} />
    <Table title="Fills" rows={data.fills} columns={[["at_ms", "Time (ms)"], ["order_id", "Order"], ["side", "Side"], ["quantity", "Quantity"], ["price", "Price"], ["fee", "Fee"]]} />
    <Table title="Event audit" rows={data.audit} columns={[["at_ms", "Time (ms)"], ["order_id", "Order"], ["event", "Event"], ["reason", "Reason"]]} />
    <details><summary className="cursor-pointer text-sm text-slate-300">Scenario assumptions</summary><ul className="mt-2 list-disc pl-5 text-sm text-slate-400 space-y-2">{data.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
  </div>
}
