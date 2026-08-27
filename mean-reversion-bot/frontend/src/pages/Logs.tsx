import { useEffect, useState, useCallback, useRef } from 'react'
import { FileText, RefreshCw, Terminal, Download, Trash2 } from 'lucide-react'

// System logs are often best served via WebSocket or a dedicated log endpoint
// For now, we'll implement a placeholder that could be wired to a real log tailer
const BASE = (import.meta as any).env?.VITE_API_URL ?? ''

interface LogEntry {
  ts: string
  level: 'INFO' | 'WARNING' | 'ERROR' | 'DEBUG'
  logger: string
  message: string
}

export default function Logs() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const logContainerRef = useRef<HTMLDivElement>(null)

  // Simulate logs for now or wire to a real endpoint if it exists
  // The backend seems to use standard logging, we could add an endpoint to read log files
  const fetchLogs = useCallback(async () => {
     // Placeholder: In a real app, this would fetch from /api/logs
     const mockLogs: LogEntry[] = [
         { ts: new Date().toISOString(), level: 'INFO', logger: 'app.bot', message: 'Monitoring R_75... '},
         { ts: new Date().toISOString(), level: 'INFO', logger: 'app.engine', message: 'Signal engine initialised with balance $1000.00'},
     ]
     setLogs(prev => [...prev, ...mockLogs].slice(-100))
  }, [])

  useEffect(() => {
    const timer = setInterval(fetchLogs, 5000)
    return () => clearInterval(timer)
  }, [fetchLogs])

  useEffect(() => {
    if (autoScroll && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
    }
  }, [logs, autoScroll])

  return (
    <div className="p-6 h-full flex flex-col space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">System Logs</h1>
          <p className="text-slate-400 text-sm">Live output from bot and API processes</p>
        </div>
        <div className="flex items-center gap-3">
            <button 
                onClick={() => setAutoScroll(!autoScroll)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                    autoScroll ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'
                }`}
            >
                Auto-scroll: {autoScroll ? 'ON' : 'OFF'}
            </button>
            <button 
                onClick={() => setLogs([])}
                className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
                title="Clear"
            >
                <Trash2 className="w-5 h-5" />
            </button>
        </div>
      </div>

      <div className="flex-1 bg-slate-950 border border-slate-800 rounded-xl overflow-hidden font-mono text-xs flex flex-col">
          <div className="bg-slate-900 px-4 py-2 border-b border-slate-800 flex items-center gap-2 text-slate-400">
              <Terminal className="w-4 h-4" />
              <span>mrbot_service.log</span>
          </div>
          <div 
            ref={logContainerRef}
            className="flex-1 overflow-y-auto p-4 space-y-1"
          >
              {logs.length === 0 ? (
                  <div className="text-slate-700 italic">Waiting for log entries...</div>
              ) : (
                  logs.map((log, i) => (
                      <div key={i} className="flex gap-4 hover:bg-white/5 py-0.5 px-1 rounded group">
                          <span className="text-slate-600 shrink-0">{new Date(log.ts).toLocaleTimeString()}</span>
                          <span className={`font-bold shrink-0 w-12 ${
                              log.level === 'ERROR' ? 'text-red-500' : 
                              log.level === 'WARNING' ? 'text-yellow-500' : 
                              log.level === 'DEBUG' ? 'text-slate-500' : 'text-cyan-500'
                          }`}>
                              {log.level}
                          </span>
                          <span className="text-slate-500 shrink-0">[{log.logger}]</span>
                          <span className="text-slate-300 break-all">{log.message}</span>
                      </div>
                  ))
              )}
          </div>
      </div>
      
      <div className="bg-slate-800/30 rounded-lg p-4 text-xs text-slate-500 flex items-start gap-3">
          <FileText className="w-4 h-4 mt-0.5 shrink-0" />
          <p>
              Logs are persisted to <code className="text-slate-400 bg-slate-800 px-1 rounded">backend/logs/</code>. 
              In production, use <code className="text-slate-400 bg-slate-800 px-1 rounded">docker compose logs -f</code> for full historical output.
          </p>
      </div>
    </div>
  )
}
