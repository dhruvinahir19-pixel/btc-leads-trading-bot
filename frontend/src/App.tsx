import { useState, useEffect, useCallback } from 'react'
import type { TabId, HealthResponse, StatusResponse, TradeStats, ConfigResponse, RiskStatus, Trade, LogEntry, PnLSnapshot, PnLBreakdown } from './types'
import * as api from './api'
import Header from './components/Header'
import Overview from './components/Overview'
import Stats from './components/Stats'
import Trades from './components/Trades'
import Logs from './components/Logs'
import Config from './components/Config'
import Trading from './components/Trading'
import Performance from './components/Performance'

const TABS: { id: TabId; label: string; icon: string }[] = [
  { id: 'overview', label: 'Overview', icon: '📊' },
  { id: 'stats', label: 'Stats', icon: '📈' },
  { id: 'trades', label: 'Trades', icon: '📋' },
  { id: 'performance', label: 'Performance', icon: '📉' },
  { id: 'logs', label: 'Logs', icon: '📝' },
  { id: 'config', label: 'Config', icon: '⚙️' },
  { id: 'trading', label: 'Trading', icon: '🛡️' },
]

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>('overview')
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<StatusResponse | null>(null)
  const [stats, setStats] = useState<TradeStats | null>(null)
  const [config, setConfig] = useState<ConfigResponse | null>(null)
  const [trading, setTrading] = useState<RiskStatus | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [equityCurve, setEquityCurve] = useState<PnLSnapshot[]>([])
  const [pnlBreakdown, setPnlBreakdown] = useState<PnLBreakdown[]>([])
  const [loading, setLoading] = useState(true)
  const [loadingPerf, setLoadingPerf] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    try {
      const [h, s, st, c, tr, tds, lgs] = await Promise.all([
        api.getHealth(),
        api.getStatus(),
        api.getStats(),
        api.getConfig(),
        api.getTrading(),
        api.getTrades(50),
        api.getLogs(undefined, 100),
      ])
      setHealth(h)
      setStatus(s)
      setStats(st)
      setConfig(c)
      setTrading(tr)
      setTrades(tds.trades)
      setLogs(lgs.logs)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch data')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchPerformance = useCallback(async () => {
    setLoadingPerf(true)
    try {
      const [eq, pnl] = await Promise.all([
        api.getEquityCurve(200),
        api.getPnlBreakdown(30),
      ])
      setEquityCurve(eq.points)
      setPnlBreakdown(pnl.breakdown)
    } catch {
      // Silently fail — performance data is non-critical
    } finally {
      setLoadingPerf(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    fetchPerformance()
    const interval = setInterval(fetchAll, 5000)
    const perfInterval = setInterval(fetchPerformance, 60000) // Refresh perf every 60s
    return () => {
      clearInterval(interval)
      clearInterval(perfInterval)
    }
  }, [fetchAll, fetchPerformance])

  const handleReset = async () => {
    await api.resetState()
    fetchAll()
  }

  const handleScan = async () => {
    await api.triggerScan()
    fetchAll()
  }

  return (
    <div className="min-h-screen bg-surface-950">
      {/* Header */}
      <Header
        health={health}
        status={status}
        onReset={handleReset}
        onScan={handleScan}
      />

      {/* Error Banner */}
      {error && (
        <div className="mx-4 mt-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-400 text-sm">
          {error}
          <button
            onClick={fetchAll}
            className="ml-3 text-red-300 hover:text-red-200 underline"
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="flex items-center justify-center h-64">
          <div className="flex flex-col items-center gap-3">
            <div className="w-8 h-8 border-2 border-brand-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-surface-400 text-sm">Loading dashboard...</span>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      {!loading && (
        <div className="mx-4 mt-4">
          <nav className="flex gap-1 p-1 bg-surface-900/50 rounded-xl border border-surface-800/50 overflow-x-auto">
            {TABS.map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`tab-btn whitespace-nowrap flex items-center gap-1.5 ${
                  activeTab === tab.id ? 'tab-btn-active' : 'tab-btn-inactive'
                }`}
              >
                <span className="text-base">{tab.icon}</span>
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      )}

      {/* Tab Content */}
      <main className="mx-4 mt-4 mb-8">
        {!loading && (
          <div className="animate-fade-in">
            {activeTab === 'overview' && (
              <Overview health={health} status={status} stats={stats} />
            )}
            {activeTab === 'stats' && <Stats stats={stats} />}
            {activeTab === 'trades' && <Trades trades={trades} />}
            {activeTab === 'logs' && <Logs logs={logs} />}
            {activeTab === 'config' && <Config config={config} />}
            {activeTab === 'trading' && <Trading trading={trading} onRefresh={fetchAll} />}
            {activeTab === 'performance' && (
              <Performance
                equityCurve={equityCurve}
                pnlBreakdown={pnlBreakdown}
                loading={loadingPerf}
              />
            )}
          </div>
        )}
      </main>
    </div>
  )
}
