import type {
  HealthResponse,
  StatusResponse,
  TradeStats,
  Trade,
  LogEntry,
  ConfigResponse,
  RiskStatus,
  PnLSnapshot,
  PnLBreakdown,
  TradeJournalResponse,
} from './types';

const BASE = '';  // Same origin, FastAPI handles it

async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Accept': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => 'Unknown error');
    throw new Error(`HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json();
}

export function getHealth(): Promise<HealthResponse> {
  return fetchJSON<HealthResponse>(`${BASE}/health`);
}

export function getStatus(): Promise<StatusResponse> {
  return fetchJSON<StatusResponse>(`${BASE}/api/status`);
}

export function getStats(): Promise<TradeStats> {
  return fetchJSON<TradeStats>(`${BASE}/api/stats`);
}

export function getTrades(limit = 50): Promise<{ trades: Trade[]; count: number }> {
  return fetchJSON<{ trades: Trade[]; count: number }>(`${BASE}/api/trades?limit=${limit}`);
}

export function getLogs(level?: string, limit = 100): Promise<{ logs: LogEntry[]; count: number }> {
  const params = new URLSearchParams();
  if (level) params.set('level', level);
  params.set('limit', String(limit));
  return fetchJSON<{ logs: LogEntry[]; count: number }>(`${BASE}/api/logs?${params}`);
}

export function getConfig(): Promise<ConfigResponse> {
  return fetchJSON<ConfigResponse>(`${BASE}/api/config`);
}

export function getTrading(): Promise<RiskStatus> {
  return fetchJSON<RiskStatus>(`${BASE}/api/trading`);
}

export function triggerScan(): Promise<any> {
  return fetchJSON<any>(`${BASE}/api/scan`, { method: 'POST' });
}

export function resetState(): Promise<{ status: string }> {
  return fetchJSON<{ status: string }>(`${BASE}/api/reset-state`, { method: 'POST' });
}

export function getEquityCurve(limit = 200): Promise<{ points: PnLSnapshot[]; count: number }> {
  return fetchJSON<{ points: PnLSnapshot[]; count: number }>(`${BASE}/api/equity-curve?limit=${limit}`);
}

export function getPnlBreakdown(days = 30): Promise<{ breakdown: PnLBreakdown[] }> {
  return fetchJSON<{ breakdown: PnLBreakdown[] }>(`${BASE}/api/pnl-breakdown?days=${days}`);
}

export function getTradeJournal(params: {
  limit?: number;
  offset?: number;
  coin?: string;
  side?: string;
  exit_reason?: string;
  date_from?: string;
  date_to?: string;
} = {}): Promise<TradeJournalResponse> {
  const qs = new URLSearchParams();
  if (params.limit) qs.set('limit', String(params.limit));
  if (params.offset) qs.set('offset', String(params.offset));
  if (params.coin) qs.set('coin', params.coin);
  if (params.side) qs.set('side', params.side);
  if (params.exit_reason) qs.set('exit_reason', params.exit_reason);
  if (params.date_from) qs.set('date_from', params.date_from);
  if (params.date_to) qs.set('date_to', params.date_to);
  return fetchJSON<TradeJournalResponse>(`${BASE}/api/trade-journal?${qs}`);
}
