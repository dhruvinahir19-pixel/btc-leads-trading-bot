import type { ConfigResponse } from '../types'

interface ConfigProps {
  config: ConfigResponse | null
}

function ConfigSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <p className="card-header">{title}</p>
      <div className="mt-3 space-y-2">{children}</div>
    </div>
  )
}

function ConfigRow({ label, value, highlight }: { label: string; value: React.ReactNode; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-surface-700/30 last:border-0">
      <span className="text-sm text-surface-400">{label}</span>
      <span className={`text-sm font-medium ${highlight ? 'text-brand-400' : 'text-surface-200'}`}>
        {value}
      </span>
    </div>
  )
}

function Badge({ ok }: { ok: boolean }) {
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
      ok ? 'badge-green' : 'badge-red'
    }`}>
      {ok ? 'Configured' : 'Not Set'}
    </span>
  )
}

export default function Config({ config }: ConfigProps) {
  if (!config) {
    return (
      <div className="card text-center py-12">
        <span className="text-4xl block mb-3">⚙️</span>
        <p className="text-surface-400 text-sm">Configuration not available.</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Strategy */}
      <ConfigSection title="📈 Strategy Parameters">
        <ConfigRow label="BTC Trigger" value={`${config.btc_trigger_pct}%`} highlight />
        <ConfigRow label="Take Profit" value={`${config.tp_pct}%`} />
        <ConfigRow label="Stop Loss" value={`${config.sl_pct}%`} />
        <ConfigRow label="Window" value={`${config.window_bars}H`} />
      </ConfigSection>

      {/* Position Sizing */}
      <ConfigSection title="💰 Position & Risk">
        <ConfigRow label="Position Size" value={`$${config.position_size_usdt}`} highlight />
        <ConfigRow label="Max Coins / Trade" value={config.max_coins_per_trade.toString()} />
        <ConfigRow label="Daily Loss Limit" value={`$${config.max_daily_loss_usdt}`} />
      </ConfigSection>

      {/* Coins */}
      <ConfigSection title="🪙 Trading Coins">
        <ConfigRow
          label="Fixed Coins"
          value={config.fixed_coins?.join(', ') || 'None'}
          highlight
        />
        <ConfigRow
          label="All Trading Coins"
          value={config.trading_coins.join(', ') || 'None'}
        />
        <ConfigRow
          label="Total Coins"
          value={config.trading_coins.length.toString()}
        />
      </ConfigSection>

      {/* Services */}
      <ConfigSection title="🔌 Services">
        <ConfigRow
          label="Binance Demo API"
          value={<Badge ok={config.demo_api_configured} />}
        />
        <ConfigRow
          label="SMTP Email"
          value={<Badge ok={config.smtp_configured} />}
        />
      </ConfigSection>
    </div>
  )
}
