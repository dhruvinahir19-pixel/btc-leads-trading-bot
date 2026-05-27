import { useMemo, useState } from 'react'
import {
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Area, AreaChart,
  BarChart, Bar, Cell,
} from 'recharts'
import type { PnLSnapshot, PnLBreakdown } from '../types'

interface PerformanceProps {
  equityCurve: PnLSnapshot[]
  pnlBreakdown: PnLBreakdown[]
  loading: boolean
}

// ─── Custom Tooltip ──────────────────────────────────────

function EquityTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  const data = payload[0].payload
  return (
    <div className="bg-surface-800 border border-surface-700 rounded-lg p-3 shadow-xl text-sm">
      <p className="text-surface-400 text-xs mb-1">{data.timestamp}</p>
      <p className="text-surface-100 font-bold font-mono">
        ${data.total_pnl.toFixed(2)}
      </p>
      <p className="text-xs text-surface-400 mt-0.5">
        Trades: {data.total_trades} · Today: ${data.today_pnl.toFixed(2)}
      </p>
    </div>
  )
}

function PnlBarTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-surface-800 border border-surface-700 rounded-lg p-3 shadow-xl text-sm">
      <p className="text-surface-400 text-xs mb-1">{label}</p>
      {payload.map((entry: any, idx: number) => (
        <div key={idx} className="flex items-center gap-2 text-xs mt-1">
          <span className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-surface-100">{entry.name}</span>
          <span className={`font-mono font-medium ${entry.value >= 0 ? 'text-green-400' : 'text-red-400'}`}>
            ${entry.value.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  )
}

// ─── Component ───────────────────────────────────────────

export default function Performance({ equityCurve, pnlBreakdown, loading }: PerformanceProps) {
  const [chartRange, setChartRange] = useState<'all' | '50' | '30' | '7'>('all')

  const filteredEquity = useMemo(() => {
    if (chartRange === 'all') return equityCurve
    const n = parseInt(chartRange)
    return equityCurve.slice(-n)
  }, [equityCurve, chartRange])

  // Aggregate PnL breakdown by day for the bar chart
  const dailyPnl = useMemo(() => {
    const dailyMap: Record<string, number> = {}
    for (const b of pnlBreakdown) {
      dailyMap[b.day] = (dailyMap[b.day] || 0) + b.total_pnl
    }
    return Object.entries(dailyMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .slice(-30)
      .map(([day, total]) => ({
        day: day.slice(5), // Show MM-DD
        pnl: Math.round(total * 100) / 100,
      }))
  }, [pnlBreakdown])

  // Top coins by PnL
  const topCoins = useMemo(() => {
    const coinMap: Record<string, { pnl: number; wins: number; losses: number; trades: number }> = {}
    for (const b of pnlBreakdown) {
      let entry = coinMap[b.coin]
      if (!entry) {
        entry = { pnl: 0, wins: 0, losses: 0, trades: 0 }
        coinMap[b.coin] = entry
      }
      entry.pnl += b.total_pnl
      entry.wins += b.wins
      entry.losses += b.losses
      entry.trades += b.trade_count
    }
    return Object.entries(coinMap)
      .sort(([, a], [, b]) => b.pnl - a.pnl)
      .slice(0, 10)
      .map(([coin, data]) => ({
        coin,
        ...data,
        pnl: Math.round(data.pnl * 100) / 100,
        winRate: data.trades > 0 ? Math.round(data.wins / data.trades * 100) : 0,
      }))
  }, [pnlBreakdown])

  // Summary calculations
  const lastPoint = equityCurve.length > 0 ? equityCurve[equityCurve.length - 1] : null
  const totalPnl = lastPoint?.total_pnl ?? 0
  const totalTrades = lastPoint?.total_trades ?? 0
  const isPositive = totalPnl >= 0

  const allPnlValues = filteredEquity.length > 0 ? filteredEquity.map(p => p.total_pnl) : [0]
  const equityLow = Math.min(...allPnlValues)
  const equityHigh = Math.max(...allPnlValues)
  const drawdown = equityLow < 0 ? Math.abs(equityLow) : 0
  const peakToCurrent = equityHigh > 0 ? ((totalPnl - equityHigh) / equityHigh * 100) : 0

  if (loading) {
    return (
      <div className="card text-center py-12">
        <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-surface-400 text-sm">Loading performance data...</p>
      </div>
    )
  }

  if (equityCurve.length === 0) {
    return (
      <div className="card text-center py-12">
        <span className="text-4xl block mb-3">📊</span>
        <p className="text-surface-400 text-sm">Not enough data yet. PnL snapshots are taken hourly — check back after a few hours of trading.</p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Key Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard label="Total P&L" value={`$${totalPnl.toFixed(2)}`} icon="💰" color={isPositive ? 'green' : 'red'} />
        <MetricCard label="Total Trades" value={totalTrades.toString()} icon="🔄" color="blue" />
        <MetricCard label="Max Drawdown" value={`$${drawdown.toFixed(2)}`} icon="📉" color={drawdown > 0 ? 'red' : 'green'} />
        <MetricCard label="Peak-to-Current" value={`${peakToCurrent.toFixed(1)}%`} icon="📈" color={peakToCurrent >= 0 ? 'green' : 'red'} />
      </div>

      {/* Equity Curve Chart */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <p className="card-header !mb-0">📈 Equity Curve</p>
          <div className="flex gap-1">
            {(['all', '50', '30', '7'] as const).map(r => (
              <button
                key={r}
                onClick={() => setChartRange(r)}
                className={`px-2 py-1 rounded text-xs font-medium transition-all ${
                  chartRange === r
                    ? 'bg-brand-600/20 text-brand-400'
                    : 'text-surface-500 hover:text-surface-300'
                }`}
              >
                {r === 'all' ? 'All' : `${r} pts`}
              </button>
            ))}
          </div>
        </div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={filteredEquity} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
              <defs>
                <linearGradient id="pnlGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity={0.3} />
                  <stop offset="95%" stopColor={isPositive ? '#22c55e' : '#ef4444'} stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.3} />
              <XAxis
                dataKey="timestamp"
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickFormatter={(v) => v?.split(' ')[1]?.slice(0, 5) || v}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: '#64748b', fontSize: 11 }}
                tickFormatter={(v) => `$${v}`}
                axisLine={{ stroke: '#334155' }}
                tickLine={false}
              />
              <Tooltip content={<EquityTooltip />} />
              <Area
                type="monotone"
                dataKey="total_pnl"
                stroke={isPositive ? '#22c55e' : '#ef4444'}
                strokeWidth={2}
                fill="url(#pnlGradient)"
                dot={false}
                activeDot={{ r: 4, strokeWidth: 0 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Daily PnL Bar Chart */}
      {dailyPnl.length > 0 && (
        <div className="card">
          <p className="card-header">📊 Daily P&L (Last 30 Days)</p>
          <div className="h-64 mt-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={dailyPnl} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" strokeOpacity={0.3} />
                <XAxis
                  dataKey="day"
                  tick={{ fill: '#64748b', fontSize: 10 }}
                  axisLine={{ stroke: '#334155' }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: '#64748b', fontSize: 11 }}
                  tickFormatter={(v) => `$${v}`}
                  axisLine={{ stroke: '#334155' }}
                  tickLine={false}
                />
                <Tooltip content={<PnlBarTooltip />} />
                <Bar
                  dataKey="pnl"
                  name="PnL"
                  radius={[3, 3, 0, 0]}
                  maxBarSize={24}
                >
                  {dailyPnl.map((entry, idx) => (
                    <Cell
                      key={idx}
                      fill={entry.pnl >= 0 ? '#22c55e' : '#ef4444'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Top Coins by PnL */}
      {topCoins.length > 0 && (
        <div className="card">
          <p className="card-header">🪙 Top Coins by P&L</p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-surface-700/50">
                  <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider text-surface-400">Coin</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-surface-400">Total P&L</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-surface-400">Trades</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-surface-400">Win Rate</th>
                  <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wider text-surface-400">W / L</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-800/50">
                {topCoins.map(c => (
                  <tr key={c.coin} className="hover:bg-surface-800/30 transition-colors">
                    <td className="px-3 py-2.5 text-sm font-medium text-surface-100">{c.coin}</td>
                    <td className={`px-3 py-2.5 text-sm font-mono font-bold text-right ${c.pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {c.pnl >= 0 ? '+' : ''}${c.pnl.toFixed(2)}
                    </td>
                    <td className="px-3 py-2.5 text-sm text-surface-300 text-right">{c.trades}</td>
                    <td className="px-3 py-2.5 text-right">
                      <span className={`text-sm font-medium ${c.winRate >= 50 ? 'text-green-400' : 'text-yellow-400'}`}>
                        {c.winRate}%
                      </span>
                    </td>
                    <td className="px-3 py-2.5 text-sm text-right">
                      <span className="text-green-400">{c.wins}</span>
                      <span className="text-surface-500"> / </span>
                      <span className="text-red-400">{c.losses}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function MetricCard({ label, value, icon, color }: { label: string; value: string; icon: string; color: 'green' | 'red' | 'blue' | 'yellow' }) {
  const textColors = {
    green: 'text-green-400',
    red: 'text-red-400',
    blue: 'text-blue-400',
    yellow: 'text-yellow-400',
  }
  const borderColors = {
    green: 'border-green-500/20',
    red: 'border-red-500/20',
    blue: 'border-blue-500/20',
    yellow: 'border-yellow-500/20',
  }

  return (
    <div className={`card ${borderColors[color]}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-lg">{icon}</span>
      </div>
      <p className={`text-2xl font-bold ${textColors[color]}`}>{value}</p>
      <p className="text-xs text-surface-400 mt-0.5">{label}</p>
    </div>
  )
}
