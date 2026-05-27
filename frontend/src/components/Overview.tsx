import type { HealthResponse, StatusResponse, TradeStats } from '../types'

interface OverviewProps {
  health: HealthResponse | null
  status: StatusResponse | null
  stats: TradeStats | null
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) return `${h}h ${m}m ${s}s`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

export default function Overview({ health, status, stats }: OverviewProps) {
  const btcPrice = status?.btc_current ?? 0
  const inTrade = health?.in_trade ?? false
  const uptime = health?.uptime_seconds ?? 0
  const tradeCount = stats?.total_trades ?? 0
  const winRate = stats?.win_rate ?? 0
  const totalPnl = stats?.total_pnl ?? 0

  const quickCards = [
    {
      label: 'Total Trades',
      value: tradeCount.toString(),
      sub: `${stats?.winning_trades ?? 0} wins / ${stats?.losing_trades ?? 0} losses`,
      icon: '🔄',
    },
    {
      label: 'Win Rate',
      value: `${winRate.toFixed(1)}%`,
      sub: `${stats?.current_streak ?? 0} current streak`,
      icon: '🎯',
      highlight: true,
    },
    {
      label: 'Total PnL',
      value: `$${totalPnl.toFixed(2)}`,
      sub: `Avg: $${(stats?.avg_pnl ?? 0).toFixed(2)}`,
      icon: '💰',
      positive: totalPnl >= 0,
    },
    {
      label: 'Bot Uptime',
      value: formatUptime(uptime),
      sub: `v${health?.version ?? '...'}`,
      icon: '⏱️',
    },
  ]

  return (
    <div className="space-y-5">
      {/* BTC Hero Card */}
      <div className="card !p-6 bg-gradient-to-br from-surface-800 to-surface-900 border-surface-700/30">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-surface-400 font-medium">BTCUSDT — Current Price</p>
            <p className="text-4xl font-bold font-mono text-surface-100 mt-1">
              ${btcPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </p>
            <div className="flex items-center gap-3 mt-3">
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                inTrade ? 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20' : 'bg-green-500/10 text-green-400 border border-green-500/20'
              }`}>
                <span className={`w-1.5 h-1.5 rounded-full ${inTrade ? 'bg-yellow-400 animate-pulse' : 'bg-green-500'}`} />
                {inTrade ? 'In Trade' : 'No Active Trades'}
              </span>
              <span className="text-surface-500 text-xs">
                Health: {health?.status ?? 'unknown'}
              </span>
            </div>
          </div>
          <div className="hidden sm:block text-6xl opacity-20">
            {btcPrice > 0 ? '₿' : '📡'}
          </div>
        </div>
      </div>

      {/* Quick Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {quickCards.map((card, i) => (
          <div key={i} className="card animate-slide-up" style={{ animationDelay: `${i * 50}ms` } as React.CSSProperties}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-lg">{card.icon}</span>
              {card.highlight && winRate > 50 && (
                <span className="badge-green">Hot</span>
              )}
              {card.highlight && winRate <= 50 && tradeCount > 0 && (
                <span className="badge-yellow">Warm</span>
              )}
            </div>
            <p className="text-2xl font-bold text-surface-100">{card.value}</p>
            <p className="text-sm text-surface-400 mt-0.5">{card.label}</p>
            <p className={`text-xs mt-1 ${card.positive !== undefined ? (card.positive ? 'text-green-400' : 'text-red-400') : 'text-surface-500'}`}>
              {card.sub}
            </p>
          </div>
        ))}
      </div>

      {/* Status Cards Row */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Trade Status */}
        <div className="card">
          <p className="card-header">📋 Trade Status</p>
          <div className="space-y-2.5 mt-3">
            <StatusRow label="In Trade" value={inTrade ? 'Yes' : 'No'} active={inTrade} />
            <StatusRow label="Current Positions" value={status?.current_trade_count?.toString() ?? '0'} />
            <StatusRow label="Daily Trades" value={status?.daily_trade_count?.toString() ?? '0'} />
            <StatusRow label="Daily PnL" value={`$${(status?.daily_pnl ?? 0).toFixed(2)}`} positive={(status?.daily_pnl ?? 0) >= 0} />
            <StatusRow
              label="Circuit Breaker"
              value={status?.circuit_breaker_triggered ? 'TRIGGERED' : 'Normal'}
              active={!status?.circuit_breaker_triggered}
              danger={status?.circuit_breaker_triggered}
            />
          </div>
        </div>

        {/* Bot Info */}
        <div className="card">
          <p className="card-header">🤖 Bot Info</p>
          <div className="space-y-2.5 mt-3">
            <StatusRow label="Version" value={health?.version ?? '...'} />
            <StatusRow label="Uptime" value={formatUptime(uptime)} />
            <StatusRow label="Last Signal" value={status?.last_signal ?? 'None'} />
            <StatusRow label="Last Entry" value={status?.last_entry ?? 'None'} />
            <StatusRow label="Last Exit" value={status?.last_exit ?? 'None'} />
            <StatusRow label="Scan Pending" value={status?.weekly_scan_pending ? 'Yes' : 'No'} active={!status?.weekly_scan_pending} />
          </div>
        </div>
      </div>
    </div>
  )
}

function StatusRow({
  label,
  value,
  active,
  positive,
  danger,
}: {
  label: string
  value: string
  active?: boolean
  positive?: boolean
  danger?: boolean
}) {
  let colorClass = 'text-surface-100'
  if (active === true) colorClass = 'text-green-400'
  if (active === false) colorClass = 'text-yellow-400'
  if (positive === true) colorClass = 'text-green-400'
  if (positive === false) colorClass = 'text-red-400'
  if (danger === true) colorClass = 'text-red-400'

  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-surface-400">{label}</span>
      <span className={`text-sm font-medium ${colorClass}`}>{value}</span>
    </div>
  )
}
