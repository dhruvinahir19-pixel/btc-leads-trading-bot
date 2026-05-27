import { useState, useMemo, useRef, useEffect } from 'react'
import type { LogEntry } from '../types'

interface LogsProps {
  logs: LogEntry[]
}

const LEVELS = ['ALL', 'INFO', 'WARNING', 'ERROR'] as const

export default function Logs({ logs }: LogsProps) {
  const [filterLevel, setFilterLevel] = useState<string>('ALL')
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  const filteredLogs = useMemo(() => {
    if (filterLevel === 'ALL') return logs
    return logs.filter(l => l.level === filterLevel)
  }, [logs, filterLevel])

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [filteredLogs, autoScroll])

  const levelColors: Record<string, string> = {
    INFO: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
    WARNING: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
    ERROR: 'text-red-400 bg-red-500/10 border-red-500/20',
  }

  if (logs.length === 0) {
    return (
      <div className="card text-center py-12">
        <span className="text-4xl block mb-3">📝</span>
        <p className="text-surface-400 text-sm">No logs yet. Logs will appear here once the bot starts.</p>
      </div>
    )
  }

  return (
    <div className="card !p-0 overflow-hidden">
      {/* Controls */}
      <div className="px-4 py-3 border-b border-surface-700/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs text-surface-400 font-medium uppercase tracking-wider">Level:</span>
          {LEVELS.map(level => (
            <button
              key={level}
              onClick={() => setFilterLevel(level)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                filterLevel === level
                  ? 'bg-brand-600/20 text-brand-400'
                  : 'text-surface-400 hover:text-surface-200 hover:bg-surface-800/50'
              }`}
            >
              {level}
            </button>
          ))}
        </div>
        <button
          onClick={() => setAutoScroll(!autoScroll)}
          className={`text-xs px-2 py-1 rounded transition-colors ${
            autoScroll ? 'text-brand-400' : 'text-surface-500'
          }`}
        >
          {autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
        </button>
      </div>

      {/* Log entries */}
      <div
        ref={scrollRef}
        className="overflow-y-auto max-h-[600px] p-2 space-y-0.5 font-mono text-xs"
        onScroll={() => {
          if (scrollRef.current) {
            const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
            const isAtBottom = scrollHeight - scrollTop - clientHeight < 50
            setAutoScroll(isAtBottom)
          }
        }}
      >
        {filteredLogs.map(log => (
          <div
            key={log.id}
            className="flex items-start gap-2 px-3 py-1.5 rounded hover:bg-surface-800/30 transition-colors"
          >
            <span className="text-surface-500 whitespace-nowrap w-20 shrink-0">
              {log.timestamp?.split(' ')[1] ?? log.timestamp}
            </span>
            <span className={`shrink-0 px-1.5 rounded text-[10px] font-semibold uppercase tracking-wider border ${
              levelColors[log.level] ?? 'text-surface-400 bg-surface-800 border-surface-700'
            }`}>
              {log.level}
            </span>
            <span className="text-surface-500 shrink-0 w-16">{log.module}</span>
            <span className="text-surface-200 break-all">{log.message}</span>
          </div>
        ))}
      </div>

      {/* Count bar */}
      <div className="px-4 py-2 border-t border-surface-700/50 bg-surface-900/30">
        <div className="flex items-center gap-3 text-xs text-surface-500">
          <span>{filteredLogs.length} entries</span>
          <span className="text-blue-400">{logs.filter(l => l.level === 'INFO').length} INFO</span>
          <span className="text-yellow-400">{logs.filter(l => l.level === 'WARNING').length} WARN</span>
          <span className="text-red-400">{logs.filter(l => l.level === 'ERROR').length} ERR</span>
        </div>
      </div>
    </div>
  )
}
