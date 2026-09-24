type Row = Record<string, string | number | boolean | null>
type Result = {
  ending_inventory: string; cash_change: string; fees: string; marked_pnl: string;
  ending_reservations: { buy: string; sell: string }; venue_online?: boolean;
  client_inventory?: string; client_reservations?: { buy: string; sell: string };
  pending_fill_acknowledgements?: number;
  client_connected?: boolean; pending_terminal_acknowledgements?: number; queued_cancellations?: number;
  fees_charged?: string; rebates_earned?: string;
  liquidation_projection?: { status: string; blockers: string[]; projected_exit_quantity?: string;
    projected_exit_price?: string | null; projected_remaining_inventory?: string; taker_fee?: string;
    execution_cost_vs_mark?: string; projected_marked_pnl_after_exit?: string };
  quote_decisions?: { at_ms: number; trigger?: string; expires_at_ms?: number | null; fair_price: string; client_inventory: string; bid: string | null; ask: string | null; actions: { buy: string; sell: string } }[];
  orders: Row[]; fills: Row[]; audit: Row[]; limitations: string[]
}

function Table({ title, rows, columns }: { title: string; rows: Row[]; columns: [string, string][] }) {
  return <section className="min-w-0 space-y-2"><h3 className="font-semibold">{title} <span className="text-slate-400">({rows.length})</span></h3>
    <div className="overflow-x-auto rounded border border-slate-700" tabIndex={0} aria-label={`${title} table`}>
      <table className="w-full text-left text-sm whitespace-nowrap"><thead className="bg-slate-900 text-slate-400"><tr>{columns.map(([key, label]) => <th key={key} className="px-3 py-2">{label}</th>)}</tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index} className="border-t border-slate-700">{columns.map(([key]) => <td key={key} className="px-3 py-2 font-mono">{['status', 'event'].includes(key) ? String(row[key] ?? '—').replace(/_/g, ' ') : String(row[key] ?? '—')}</td>)}</tr>)}</tbody>
      </table>{rows.length === 0 && <p className="p-3 text-slate-400">No {title.toLowerCase()} in this scenario.</p>}
    </div></section>
}

export default function LifecycleReport({ result }: { result: Record<string, unknown> }) {
  const data = result as unknown as Result
  const metrics = [['Ending inventory', data.ending_inventory], ['Marked P&L', data.marked_pnl],
    ['Cash change', data.cash_change], ['Net fees / rebates', data.fees], ['Reserved buys', data.ending_reservations.buy], ['Reserved sells', data.ending_reservations.sell]]
  return <div aria-label="Order lifecycle results" className="space-y-5 min-w-0">
    <p className="text-sm text-cyan-200">Venue at end: {data.venue_online === false ? 'Halted' : 'Online'} · Offline scenario</p>
    <div className="grid grid-cols-2 xl:grid-cols-3 gap-3">{metrics.map(([label, value]) => <div key={label} className="rounded bg-slate-900 p-3 min-w-0"><p className="text-xs text-slate-400">{label}</p><p className="font-mono text-sm sm:text-lg break-all">{value}</p></div>)}</div>
    {data.fees_charged !== undefined && <p className="text-sm text-slate-400">Resting-fill fees charged: {data.fees_charged}; rebates earned: {data.rebates_earned}. Negative net fees represent rebates.</p>}
    {data.client_inventory !== undefined && <section aria-label="Client acknowledgement state" className="rounded border border-cyan-800 p-3 text-sm space-y-2">
      <h3 className="font-semibold">Client acknowledgement state</h3>
      {data.client_connected !== undefined && <p>Order connection: <strong>{data.client_connected ? 'Connected' : 'Disconnected'}</strong>. Queued cancellations: {data.queued_cancellations}. Pending terminal confirmations: {data.pending_terminal_acknowledgements}.</p>}
      <p>Known inventory: <strong>{data.client_inventory}</strong>. Pending fill acknowledgements: <strong>{data.pending_fill_acknowledgements}</strong>.</p>
      <p>Client reserved buys: {data.client_reservations?.buy}; sells: {data.client_reservations?.sell}.</p>
      <p className="text-slate-400">Client reservations include unacknowledged fills. Order states and headline values show venue truth.</p>
    </section>}
    {data.liquidation_projection && <section aria-label="Exit cost projection" className="rounded border border-amber-800 p-3 text-sm space-y-2">
      <h3 className="font-semibold">Hypothetical exit costs</h3>
      <p>Projection status: {data.liquidation_projection.status}</p>
      {data.liquidation_projection.status === 'blocked' ? <ul className="list-disc pl-5">{data.liquidation_projection.blockers.map(reason => <li key={reason}>{reason.replace(/_/g, ' ')}</li>)}</ul> : <dl className="grid sm:grid-cols-2 gap-2">
        {Object.entries({ 'Exit quantity': data.liquidation_projection.projected_exit_quantity,
          'Exit price': data.liquidation_projection.projected_exit_price ?? 'No exit required',
          'Residual inventory': data.liquidation_projection.projected_remaining_inventory,
          'Taker fee': data.liquidation_projection.taker_fee,
          'Cost versus final mark': data.liquidation_projection.execution_cost_vs_mark,
          'Projected marked P&L after exit': data.liquidation_projection.projected_marked_pnl_after_exit }).map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-slate-400">{label}</dt><dd className="font-mono break-all">{value}</dd></div>)}
      </dl>}
      <p className="text-slate-400">Uses supplied liquidity, slippage and fees. The order ledger and headline inventory are unchanged; no closing order was executed.</p>
    </section>}
    <Table title="Orders" rows={data.orders} columns={[["order_id", "Order"], ["side", "Side"], ["status", "State"], ["quantity", "Quantity"], ["filled", "Filled"], ["remaining", "Remaining"]]} />
    {data.quote_decisions && <Table title="Quote decisions" rows={data.quote_decisions.map(row => ({ at_ms: row.at_ms, fair: row.fair_price,
      trigger: row.trigger ?? 'fair', expires: row.expires_at_ms ?? null,
      inventory: row.client_inventory, bid: row.bid, ask: row.ask, buy: row.actions.buy, sell: row.actions.sell }))}
      columns={[["at_ms", "Time (ms)"], ["trigger", "Trigger"], ["expires", "Expiry (ms)"], ["fair", "Fair"], ["inventory", "Known inventory"], ["bid", "Bid"], ["ask", "Ask"], ["buy", "Buy action"], ["sell", "Sell action"]]} />}
    <Table title="Fills" rows={data.fills} columns={[["at_ms", "Time (ms)"], ["order_id", "Order"], ["side", "Side"], ["quantity", "Quantity"], ["price", "Price"], ["fee", "Fee"], ["ack_at_ms", "Ack due (ms)"], ["delivered_at_ms", "Delivered (ms)"], ["acknowledged", "Acknowledged"]]} />
    <Table title="Event audit" rows={data.audit} columns={[["at_ms", "Time (ms)"], ["order_id", "Order"], ["event", "Event"], ["reason", "Reason"]]} />
    <details><summary className="cursor-pointer text-sm text-slate-300">Scenario assumptions</summary><ul className="mt-2 list-disc pl-5 text-sm text-slate-400 space-y-2">{data.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
  </div>
}
