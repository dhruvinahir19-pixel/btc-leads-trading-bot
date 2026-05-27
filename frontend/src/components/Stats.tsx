import type { TradeStats } from '../types'

interface StatsProps {
  stats: TradeStats | null
}

export default function Stats({ stats }: StatsProps) {
  if (!stats || stats.total_trades === 0 || stats.total_pnl == null) {
    return (
      <div className="card text-center py-12">
        <span className="text-4xl block mb-3">📊</span>
        <p className="text-surface-400 text-sm">No trade data yet. Start trading to see statistics.</p>
      </div>
    )
  }

  const safe = (v: number | null | undefined, fallback = 0) => v ?? fallback
  const pnlBarWidth = Math.min(Math.abs(safe(stats.total_pnl)) / 100 * 100, 100)
  const winRatePct = safe(stats.win_rate)
  const lossRatePct = 100 - winRatePct

  return (
    <div className="space-y-5">
      {/* Key Metrics Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Total Trades"
          value={(stats.total_trades ?? 0).toString()}
          icon="🔄"
          color="blue"
        />
        <MetricCard
          label="Win Rate"
          value={`${winRatePct.toFixed(1)}%`}
          icon="🎯"
          color={winRatePct >= 50 ? 'green' : 'yellow'}
        />
        <MetricCard
          label="Total P&L"
          value={`$${safe(stats.total_pnl).toFixed(2)}`}
          icon="💰"
          color={safe(stats.total_pnl) >= 0 ? 'green' : 'red'}
        />
        <MetricCard
          label="Avg P&L / Trade"
          value={`$${safe(stats.avg_pnl).toFixed(2)}`}
          icon="📊"
          color={safe(stats.avg_pnl) >= 0 ? 'green' : 'red'}
        />
      </div>

      {/* Detailed Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Win/Loss Distribution */}
        <div className="card">
          <p className="card-header">📊 Win / Loss Distribution</p>
          <div className="mt-4">
            <div className="flex h-8 rounded-lg overflow-hidden">
              <div
                className="bg-green-500/30 border-r border-green-500/40 transition-all duration-500"
                style={{ width: `${winRatePct}%` }}
              />
              <div
                className="bg-red-500/30 transition-all duration-500"
                style={{ width: `${lossRatePct}%` }}
              />
            </div>
            <div className="flex justify-between mt-2 text-sm">
              <span className="text-green-400">
                Wins: {stats.winning_trades ?? 0} ({winRatePct.toFixed(0)}%)
              </span>
              <span className="text-red-400">
                Losses: {stats.losing_trades ?? 0} ({lossRatePct.toFixed(0)}%)
              </span>
            </div>
          </div>
        </div>

        {/* P&L Bar */}
        <div className="card">
          <p className="card-header">📈 Performance Metrics</p>
          <div className="space-y-3 mt-4">
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-surface-400">Best Trade</span>
                <span className="text-green-400 font-medium">+${safe(stats.max_pnl).toFixed(2)}</span>
              </div>
            </div>
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-surface-400">Worst Trade</span>
                <span className="text-red-400 font-medium">${safe(stats.min_pnl).toFixed(2)}</span>
              </div>
            </div>
            <div className="pt-2 border-t border-surface-700/50">
              <div className="flex items-center justify-between">
                <span className="text-sm text-surface-400">Streaks</span>
                <div className="flex gap-4 text-sm">
                  <span className="text-green-400">Best: {stats.best_streak ?? 0}</span>
                  <span className="text-red-400">Worst: {stats.worst_streak ?? 0}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* P&L Visualization */}
      <div className="card">
        <p className="card-header">💰 P&L Overview</p>
        <div className="mt-4">
          <div className="relative h-12 bg-surface-900 rounded-lg overflow-hidden">
            {/* Zero line */}
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-surface-600 z-10" />
            {/* Positive bar */}
            {safe(stats.total_pnl) > 0 && (
              <div
                className="absolute left-1/2 top-1 bottom-1 bg-gradient-to-r from-green-500/30 to-green-400/40 rounded-r transition-all duration-700"
                style={{ width: `${Math.min(pnlBarWidth, 48)}%` }}
              />
            )}
            {/* Negative bar */}
            {safe(stats.total_pnl) < 0 && (
              <div
                className="absolute right-1/2 top-1 bottom-1 bg-gradient-to-l from-red-500/30 to-red-400/40 rounded-l transition-all duration-700"
                style={{ width: `${Math.min(pnlBarWidth, 48)}%` }}
              />
            )}
          </div>
          <div className="flex justify-between mt-2 text-sm">
            <span className="text-surface-500">Loss</span>
            <span className={`font-bold ${safe(stats.total_pnl) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
              ${safe(stats.total_pnl).toFixed(2)}
            </span>
            <span className="text-surface-500">Profit</span>
          </div>
        </div>
      </div>
    </div>
  )
}

function MetricCard({
  label,
  value,
  icon,
  color,
}: {
  label: string
  value: string
  icon: string
  color: 'green' | 'red' | 'yellow' | 'blue'
}) {
  const borderColors = {
    green: 'border-green-500/20',
    red: 'border-red-500/20',
    yellow: 'border-yellow-500/20',
    blue: 'border-blue-500/20',
  }
  const bgColors = {
    green: 'bg-green-500/5',
    red: 'bg-red-500/5',
    yellow: 'bg-yellow-500/5',
    blue: 'bg-blue-500/5',
  }
  const textColors = {
    green: 'text-green-400',
    red: 'text-red-400',
    yellow: 'text-yellow-400',
    blue: 'text-blue-400',
  }

  return (
    <div className={`card ${borderColors[color]} ${bgColors[color]}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-lg">{icon}</span>
      </div>
      <p className={`text-2xl font-bold ${textColors[color]}`}>{value}</p>
      <p className="text-xs text-surface-400 mt-0.5">{label}</p>
    </div>
  )
}
