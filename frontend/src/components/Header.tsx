import type { HealthResponse, StatusResponse } from '../types'

interface HeaderProps {
  health: HealthResponse | null
  status: StatusResponse | null
  onReset: () => void
  onScan: () => void
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export default function Header({ health, status, onReset, onScan }: HeaderProps) {
  const btcPrice = status?.btc_current ?? 0
  const inTrade = health?.in_trade ?? false
  const uptime = health?.uptime_seconds ?? 0
  const isLive = health?.status === 'ok'

  return (
    <header className="sticky top-0 z-50 bg-surface-950/80 backdrop-blur-xl border-b border-surface-800/50">
      <div className="flex items-center justify-between px-4 py-3 max-w-7xl mx-auto">
        {/* Left: Brand */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-lg shadow-brand-500/20">
            <span className="text-lg">📈</span>
          </div>
          <div>
            <h1 className="text-base font-bold text-surface-100">BTC Leads Bot</h1>
            <p className="text-xs text-surface-500">Trading Engine v{health?.version ?? '...'}</p>
          </div>
        </div>

        {/* Center: BTC Price */}
        <div className="hidden md:flex items-center gap-6">
          <div className="text-center">
            <p className="text-xs text-surface-400 uppercase tracking-wider">BTCUSDT</p>
            <p className="text-xl font-bold font-mono text-surface-100">
              ${btcPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
          </div>

          <div className="w-px h-8 bg-surface-700" />

          {/* Status Indicators */}
          <div className="flex items-center gap-4">
            <StatusDot label="Server" active={isLive} color="green" />
            <StatusDot label="In Trade" active={inTrade} color={inTrade ? 'yellow' : 'green'} />
          </div>

          <div className="w-px h-8 bg-surface-700" />

          <div className="text-xs text-surface-400">
            <span className="font-mono">{formatUptime(uptime)}</span>
            <p className="text-surface-500">uptime</p>
          </div>
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          <button onClick={onScan} className="btn-secondary text-xs px-3 py-1.5">
            🔄 Scan
          </button>
          <button onClick={onReset} className="btn-secondary text-xs px-3 py-1.5 text-yellow-400">
            ⚠ Reset
          </button>
        </div>
      </div>
    </header>
  )
}

function StatusDot({ label, active, color }: { label: string; active: boolean; color: 'green' | 'yellow' | 'red' }) {
  const colors = {
    green: 'bg-green-500 shadow-green-500/50',
    yellow: 'bg-yellow-400 shadow-yellow-400/50',
    red: 'bg-red-500 shadow-red-500/50',
  }

  return (
    <div className="flex items-center gap-2">
      <span className={`w-2 h-2 rounded-full ${colors[color]} ${active ? 'shadow-lg animate-pulse-slow' : 'opacity-40'}`} />
      <div>
        <p className="text-xs text-surface-300">{label}</p>
        <p className={`text-xs font-medium ${active ? 'text-surface-100' : 'text-surface-500'}`}>
          {active ? 'Active' : 'Idle'}
        </p>
      </div>
    </div>
  )
}
