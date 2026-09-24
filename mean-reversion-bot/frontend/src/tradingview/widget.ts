// The iframe owns the asynchronous embed. Unmounting destroys its execution
// context instead of detaching the container of a still-pending script.
export function chartDocument(symbol: string, timeframe: string): string {
  const config = JSON.stringify({ autosize: true, symbol,
    interval: String(Number(timeframe.slice(1)) * (timeframe.startsWith('H') ? 60 : 1)),
    timezone: 'Etc/UTC', theme: 'dark', style: '1', locale: 'en',
    allow_symbol_change: false, hide_side_toolbar: false, calendar: false,
    support_host: 'https://www.tradingview.com',
  }).replace(/</g, '\\u003c')
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>html,body{height:100%;margin:0;background:#0f172a;color:#cbd5e1;font:14px system-ui}
    .tradingview-widget-container{height:100%;width:100%}
    #error{padding:20px;margin:0;color:#fcd34d}</style></head><body>
    <p id="error" role="alert" hidden>Chart could not load. Use Reload chart or open the full TradingView chart.</p>
    <div class="tradingview-widget-container"><div class="tradingview-widget-container__widget" style="height:100%;width:100%"></div>
    <script async src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
      onerror="document.getElementById('error').hidden=false;this.parentElement.hidden=true">${config}</script>
    </div></body></html>`
}
