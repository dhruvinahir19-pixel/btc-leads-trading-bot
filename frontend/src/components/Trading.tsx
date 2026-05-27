import type { RiskStatus } from '../types'

interface TradingProps {
  trading: RiskStatus | null
  onRefresh: () => void
}

export default function Trading({ trading, onRefresh }: TradingProps) {
  if (!trading) {
    return (
      <div className="card text-center py-12">
        <span className="text-4xl block mb-3">🛡️</span>
        <p className="text-surface-400 text-sm">Trading status not available.</p>
      </div>
    )
  }

  const dailyPnlPct = trading.max_daily_loss > 0
    ? Math.min(Math.abs(trading.daily_pnl) / trading.max_daily_loss * 100, 100)
    : 0

  const dailyTradePct = Math.min(trading.daily_trade_count / 10 * 100, 100)
  const consecutiveLossPct = trading.max_consecutive_losses > 0
    ? Math.min(trading.consecutive_losses / trading.max_consecutive_losses * 100, 100)
    : 0

  return (
    <div className="space-y-4">
      {/* Status Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatusCard
          label="Can Trade"
          value={trading.can_trade ? 'Yes' : 'No'}
          ok={trading.can_trade}
          icon="✅"
        />
        <StatusCard
          label="In Trade"
          value={trading.in_trade ? 'Yes' : 'No'}
          ok={!trading.in_trade}
          icon="📊"
        />
        <StatusCard
          label="Circuit Breaker"
          value={trading.circuit_breaker_triggered ? 'TRIGGERED' : 'Normal'}
          ok={!trading.circuit_breaker_triggered}
          icon="⚡"
        />
        <StatusCard
          label="Trade Window"
          value={trading.trade_window_open ? 'Open' : 'Closed'}
          ok={trading.trade_window_open}
          icon="🕐"
        />
      </div>

      {/* Progress Bars */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Daily Loss */}
        <div className="card">
          <p className="card-header">📉 Daily Loss Limit</p>
          <div className="mt-3">
            <div className="flex justify-between text-sm mb-1.5">
              <span className="text-surface-400">
                ${Math.abs(trading.daily_pnl).toFixed(2)} / ${trading.max_daily_loss.toFixed(2)}
              </span>
              <span className={trading.daily_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                ${trading.daily_pnl.toFixed(2)}
              </span>
            </div>
            <div className="h-3 bg-surface-900 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  trading.daily_pnl >= 0
                    ? 'bg-green-500/40'
                    : dailyPnlPct > 80
                      ? 'bg-red-500/60'
                      : 'bg-yellow-500/40'
                }`}
                style={{ width: `${Math.min(dailyPnlPct, 100)}%` }}
              />
            </div>
          </div>
        </div>

        {/* Daily Trades */}
        <div className="card">
          <p className="card-header">🔄 Daily Trades</p>
          <div className="mt-3">
            <div className="flex justify-between text-sm mb-1.5">
              <span className="text-surface-400">{trading.daily_trade_count} / 10 trades</span>
              <span className="text-surface-300">{trading.daily_trade_count > 0 ? `${dailyTradePct.toFixed(0)}%` : '0%'}</span>
            </div>
            <div className="h-3 bg-surface-900 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  dailyTradePct > 80 ? 'bg-yellow-500/40' : 'bg-blue-500/40'
                }`}
                style={{ width: `${dailyTradePct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Consecutive Losses */}
        <div className="card">
          <p className="card-header">⚠️ Consecutive Losses</p>
          <div className="mt-3">
            <div className="flex justify-between text-sm mb-1.5">
              <span className="text-surface-400">
                {trading.consecutive_losses} / {trading.max_consecutive_losses}
              </span>
              <span className={trading.consecutive_losses >= trading.max_consecutive_losses ? 'text-red-400' : 'text-surface-300'}>
                {consecutiveLossPct.toFixed(0)}%
              </span>
            </div>
            <div className="h-3 bg-surface-900 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  consecutiveLossPct > 80 ? 'bg-red-500/60' : 'bg-orange-500/40'
                }`}
                style={{ width: `${Math.min(consecutiveLossPct, 100)}%` }}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Status Breakdown */}
      <div className="card">
        <p className="card-header">🔍 Detailed Status</p>
        <div className="mt-3 space-y-2">
          <StatusRow2 label="Balance OK" value={trading.balance_ok ? 'Yes' : 'No'} ok={trading.balance_ok} />
          <StatusRow2 label="Trade Window Open" value={trading.trade_window_open ? 'Yes' : 'No'} ok={trading.trade_window_open} />
          <StatusRow2 label="Circuit Breaker" value={trading.circuit_breaker_triggered ? 'TRIGGERED' : 'Normal'} ok={!trading.circuit_breaker_triggered} danger={trading.circuit_breaker_triggered} />
          <StatusRow2 label="Daily Loss Limit" value={`$${Math.abs(trading.daily_pnl).toFixed(2)} / $${trading.max_daily_loss.toFixed(2)}`} ok={trading.daily_pnl >= 0 || Math.abs(trading.daily_pnl) < trading.max_daily_loss} danger={trading.daily_pnl < 0 && Math.abs(trading.daily_pnl) >= trading.max_daily_loss} />
          <StatusRow2 label="Consecutive Losses" value={`${trading.consecutive_losses} / ${trading.max_consecutive_losses}`} ok={trading.consecutive_losses < trading.max_consecutive_losses} danger={trading.consecutive_losses >= trading.max_consecutive_losses} />
        </div>
      </div>

      {/* Refresh button */}
      <div className="text-center">
        <button onClick={onRefresh} className="btn-secondary">
          🔄 Refresh Status
        </button>
      </div>
    </div>
  )
}

function StatusCard({ label, value, ok, icon }: { label: string; value: string; ok: boolean; icon: string }) {
  return (
    <div className={`card ${ok ? 'border-green-500/10' : 'border-red-500/20 bg-red-500/5'}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-lg">{icon}</span>
        <span className={`w-2 h-2 rounded-full ${ok ? 'bg-green-500' : 'bg-red-500'} ${!ok ? 'animate-pulse' : ''}`} />
      </div>
      <p className={`text-xl font-bold ${ok ? 'text-green-400' : 'text-red-400'}`}>{value}</p>
      <p className="text-xs text-surface-400 mt-0.5">{label}</p>
    </div>
  )
}

function StatusRow2({ label, value, ok, danger }: { label: string; value: string; ok?: boolean; danger?: boolean }) {
  let color = 'text-surface-200'
  if (ok === false || danger) color = 'text-red-400'
  if (ok === true) color = 'text-green-400'

  return (
    <div className="flex items-center justify-between py-1.5 border-b border-surface-700/30 last:border-0">
      <span className="text-sm text-surface-400">{label}</span>
      <span className={`text-sm font-mono font-medium ${color}`}>{value}</span>
    </div>
  )
}
