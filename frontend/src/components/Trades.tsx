import { useState, useMemo, useEffect } from 'react'
import type { Trade, TradeJournalResponse } from '../types'
import * as api from '../api'

interface TradesProps {
  trades: Trade[]
}

type SortKey = 'entry_time' | 'exit_time' | 'symbol' | 'pnl_usdt' | 'status'
type SortDir = 'asc' | 'desc'

type QuickFilter = 'all' | 'open' | 'closed' | 'won' | 'lost'

const EXIT_REASONS = ['', 'tp_hit', 'sl_hit', 'timeout', 'manual', 'error'] as const

// Get unique coins from the dataset for dropdown
function getUniqueCoins(trades: Trade[]): string[] {
  const coins = new Set(trades.map(t => t.symbol))
  return ['', ...Array.from(coins).sort()]
}

export default function Trades({ trades }: TradesProps) {
  const [sortKey, setSortKey] = useState<SortKey>('entry_time')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [filter, setFilter] = useState<QuickFilter>('all')
  
  // Journal filters
  const [coinFilter, setCoinFilter] = useState('')
  const [sideFilter, setSideFilter] = useState('')
  const [reasonFilter, setReasonFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [journalData, setJournalData] = useState<TradeJournalResponse | null>(null)
  const [page, setPage] = useState(0)
  const [journalLoading, setJournalLoading] = useState(false)
  const pageSize = 50

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  // Fetch journal data when filters change
  useEffect(() => {
    const hasJournalFilters = sideFilter || reasonFilter || dateFrom || dateTo || coinFilter
    if (!hasJournalFilters && filter === 'all') {
      setJournalData(null)
      return
    }
    
    const fetchJournal = async () => {
      setJournalLoading(true)
      try {
        const data = await api.getTradeJournal({
          limit: pageSize,
          offset: page * pageSize,
          coin: coinFilter || undefined,
          side: sideFilter || undefined,
          exit_reason: reasonFilter || undefined,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        })
        setJournalData(data)
      } catch {
        // Fall back to client-side filtering
        setJournalData(null)
      } finally {
        setJournalLoading(false)
      }
    }
    fetchJournal()
  }, [coinFilter, sideFilter, reasonFilter, dateFrom, dateTo, page, filter])

  const sortedTrades = useMemo(() => {
    const source = journalData?.trades ?? trades
    
    let filtered = source
    if (filter === 'open') filtered = source.filter(t => t.status === 'open')
    else if (filter === 'closed') filtered = source.filter(t => t.status === 'closed')
    else if (filter === 'won') filtered = source.filter(t => t.pnl_usdt != null && t.pnl_usdt > 0)
    else if (filter === 'lost') filtered = source.filter(t => t.pnl_usdt != null && t.pnl_usdt < 0)

    // Apply client-side filters only if no journal data
    if (!journalData) {
      if (coinFilter) filtered = filtered.filter(t => t.symbol === coinFilter)
      if (sideFilter) filtered = filtered.filter(t => t.side === sideFilter.toUpperCase())
    }

    return [...filtered].sort((a, b) => {
      let cmp = 0
      switch (sortKey) {
        case 'entry_time':
          cmp = a.entry_time.localeCompare(b.entry_time)
          break
        case 'exit_time':
          cmp = (a.exit_time ?? '').localeCompare(b.exit_time ?? '')
          break
        case 'symbol':
          cmp = a.symbol.localeCompare(b.symbol)
          break
        case 'pnl_usdt':
          cmp = (a.pnl_usdt ?? 0) - (b.pnl_usdt ?? 0)
          break
        case 'status':
          cmp = a.status.localeCompare(b.status)
          break
      }
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [trades, journalData, sortKey, sortDir, filter, coinFilter, sideFilter])

  const uniqueCoins = getUniqueCoins(trades)

  const totalEntries = journalData?.total ?? trades.length
  const totalPages = Math.ceil(totalEntries / pageSize)

  const SortHeader = ({ label, colKey }: { label: string; colKey: SortKey }) => (
    <th
      className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-surface-400 cursor-pointer hover:text-surface-200 transition-colors select-none"
      onClick={() => toggleSort(colKey)}
    >
      <div className="flex items-center gap-1">
        {label}
        {sortKey === colKey && (
          <span className="text-brand-400">{sortDir === 'asc' ? '↑' : '↓'}</span>
        )}
      </div>
    </th>
  )

  if (trades.length === 0) {
    return (
      <div className="card text-center py-12">
        <span className="text-4xl block mb-3">📋</span>
        <p className="text-surface-400 text-sm">No trades yet. Trades will appear here once executed.</p>
      </div>
    )
  }

  return (
    <div className="card !p-0 overflow-hidden">
      {/* Filter bar */}
      <div className="px-4 py-3 border-b border-surface-700/50 space-y-3">
        {/* Quick filters */}
        <div className="flex items-center gap-2 overflow-x-auto">
          <span className="text-xs text-surface-400 font-medium uppercase tracking-wider mr-1">Filter:</span>
          {(['all', 'open', 'closed', 'won', 'lost'] as const).map(f => (
            <button
              key={f}
              onClick={() => { setFilter(f); setPage(0) }}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${
                filter === f
                  ? 'bg-brand-600/20 text-brand-400'
                  : 'text-surface-400 hover:text-surface-200 hover:bg-surface-800/50'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
          <span className="text-xs text-surface-500 ml-auto">{sortedTrades.length} trades</span>
        </div>
        
        {/* Journal advanced filters */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-surface-400 font-medium uppercase tracking-wider mr-1">Journal:</span>
          
          {/* Coin filter */}
          <select
            value={coinFilter}
            onChange={e => { setCoinFilter(e.target.value); setPage(0) }}
            className="bg-surface-800 border border-surface-700 rounded-lg px-2 py-1 text-xs text-surface-200 focus:outline-none focus:border-brand-500"
          >
            <option value="">All Coins</option>
            {uniqueCoins.filter(Boolean).map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
          
          {/* Side filter */}
          <select
            value={sideFilter}
            onChange={e => { setSideFilter(e.target.value); setPage(0) }}
            className="bg-surface-800 border border-surface-700 rounded-lg px-2 py-1 text-xs text-surface-200 focus:outline-none focus:border-brand-500"
          >
            <option value="">All Sides</option>
            <option value="LONG">Long</option>
            <option value="SHORT">Short</option>
          </select>
          
          {/* Exit reason filter */}
          <select
            value={reasonFilter}
            onChange={e => { setReasonFilter(e.target.value); setPage(0) }}
            className="bg-surface-800 border border-surface-700 rounded-lg px-2 py-1 text-xs text-surface-200 focus:outline-none focus:border-brand-500"
          >
            <option value="">All Reasons</option>
            {EXIT_REASONS.filter(Boolean).map(r => (
              <option key={r} value={r}>{r.replace('_', ' ')}</option>
            ))}
          </select>
          
          {/* Date range */}
          <input
            type="date"
            value={dateFrom}
            onChange={e => { setDateFrom(e.target.value); setPage(0) }}
            className="bg-surface-800 border border-surface-700 rounded-lg px-2 py-1 text-xs text-surface-200 focus:outline-none focus:border-brand-500"
            placeholder="From"
          />
          <span className="text-surface-500 text-xs">—</span>
          <input
            type="date"
            value={dateTo}
            onChange={e => { setDateTo(e.target.value); setPage(0) }}
            className="bg-surface-800 border border-surface-700 rounded-lg px-2 py-1 text-xs text-surface-200 focus:outline-none focus:border-brand-500"
            placeholder="To"
          />
          
          {/* Clear filters */}
          {(coinFilter || sideFilter || reasonFilter || dateFrom || dateTo) && (
            <button
              onClick={() => {
                setCoinFilter(''); setSideFilter(''); setReasonFilter('')
                setDateFrom(''); setDateTo(''); setPage(0)
              }}
              className="text-xs text-brand-400 hover:text-brand-300 transition-colors"
            >
              Clear ×
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-surface-700/50 bg-surface-900/30">
              <SortHeader label="Time" colKey="entry_time" />
              <SortHeader label="Symbol" colKey="symbol" />
              <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-surface-400">Side</th>
              <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-surface-400">Entry</th>
              <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-surface-400">Exit</th>
              <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-surface-400">Qty</th>
              <SortHeader label="PnL" colKey="pnl_usdt" />
              <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-surface-400">PnL %</th>
              <SortHeader label="Status" colKey="status" />
              <th className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wider text-surface-400">Exit Reason</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-800/50">
            {sortedTrades.map(trade => (
              <tr
                key={trade.id}
                className="hover:bg-surface-800/30 transition-colors"
              >
                <td className="px-3 py-3 text-sm text-surface-300 whitespace-nowrap font-mono">
                  {trade.entry_time}
                </td>
                <td className="px-3 py-3">
                  <span className="text-sm font-medium text-surface-100">{trade.symbol}</span>
                </td>
                <td className="px-3 py-3">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                    trade.side === 'LONG' ? 'badge-green' : 'badge-red'
                  }`}>
                    {trade.side}
                  </span>
                </td>
                <td className="px-3 py-3 text-sm font-mono text-surface-300">
                  {trade.entry_price ? `$${trade.entry_price.toFixed(6)}` : '-'}
                </td>
                <td className="px-3 py-3 text-sm font-mono text-surface-300">
                  {trade.exit_price ? `$${trade.exit_price.toFixed(6)}` : '-'}
                </td>
                <td className="px-3 py-3 text-sm font-mono text-surface-300">
                  {trade.quantity != null ? trade.quantity.toFixed(4) : '-'}
                </td>
                <td className="px-3 py-3">
                  {trade.pnl_usdt != null ? (
                    <span className={`text-sm font-bold font-mono ${trade.pnl_usdt >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {trade.pnl_usdt >= 0 ? '+' : ''}${trade.pnl_usdt.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-surface-500 text-sm">-</span>
                  )}
                </td>
                <td className="px-3 py-3">
                  {trade.pnl_percent != null ? (
                    <span className={`text-sm font-mono ${trade.pnl_percent >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {trade.pnl_percent >= 0 ? '+' : ''}{trade.pnl_percent.toFixed(2)}%
                    </span>
                  ) : (
                    <span className="text-surface-500 text-sm">-</span>
                  )}
                </td>
                <td className="px-3 py-3">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                    trade.status === 'open' ? 'badge-yellow' : 'badge-green'
                  }`}>
                    {trade.status}
                  </span>
                </td>
                <td className="px-3 py-3 text-sm text-surface-400">
                  {trade.exit_reason ?? '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination + Summary bar */}
      <div className="px-4 py-3 border-t border-surface-700/50 bg-surface-900/30 flex items-center justify-between">
        <div className="flex items-center gap-4 text-xs text-surface-400">
          <span>Total: {totalEntries} trades</span>
          {journalData ? (
            <>
              <span className="text-green-400">Won: {journalData.summary.wins}</span>
              <span className="text-red-400">Lost: {journalData.summary.losses}</span>
              <span className={journalData.summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}>
                PnL: ${journalData.summary.total_pnl.toFixed(2)}
              </span>
            </>
          ) : (
            <>
              <span className="text-green-400">Won: {trades.filter(t => t.pnl_usdt != null && t.pnl_usdt > 0).length}</span>
              <span className="text-red-400">Lost: {trades.filter(t => t.pnl_usdt != null && t.pnl_usdt < 0).length}</span>
              <span>Open: {trades.filter(t => t.status === 'open').length}</span>
            </>
          )}
          {journalLoading && <span className="text-brand-400 animate-pulse">Loading...</span>}
        </div>
        
        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-2 py-1 rounded text-xs text-surface-400 hover:text-surface-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              ← Prev
            </button>
            <span className="text-xs text-surface-500 px-2">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-2 py-1 rounded text-xs text-surface-400 hover:text-surface-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
