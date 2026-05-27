export interface HealthResponse {
  status: string;
  timestamp: string;
  uptime_seconds: number;
  in_trade: boolean;
  version: string;
}

export interface StatusResponse {
  health: string;
  btc_current: number;
  in_trade: boolean;
  current_trade_count: number;
  trade_ids: string[];
  daily_trade_count: number;
  daily_pnl: number;
  max_daily_loss: number;
  consecutive_losses: number;
  circuit_breaker_triggered: boolean;
  last_signal: string | null;
  last_entry: string | null;
  last_exit: string | null;
  weekly_scan_pending: boolean;
  position_state: any;
}

export interface TradeStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  max_pnl: number;
  min_pnl: number;
  current_streak: number;
  best_streak: number;
  worst_streak: number;
}

export interface Trade {
  id: number;
  trade_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  exit_price: number | null;
  quantity: number;
  pnl_usdt: number | null;
  pnl_percent: number | null;
  entry_time: string;
  exit_time: string | null;
  status: string;
  exit_reason: string | null;
}

export interface LogEntry {
  id: number;
  level: string;
  module: string;
  message: string;
  timestamp: string;
}

export interface ConfigResponse {
  btc_trigger_pct: number;
  tp_pct: number;
  sl_pct: number;
  window_bars: number;
  position_size_usdt: number;
  max_coins_per_trade: number;
  max_daily_loss_usdt: number;
  fixed_coins: string[];
  trading_coins: string[];
  demo_api_configured: boolean;
  smtp_configured: boolean;
}

export interface RiskStatus {
  in_trade: boolean;
  daily_trade_count: number;
  daily_pnl: number;
  max_daily_loss: number;
  consecutive_losses: number;
  max_consecutive_losses: number;
  circuit_breaker_triggered: boolean;
  can_trade: boolean;
  trade_window_open: boolean;
  balance_ok: boolean;
}

export interface PnLSnapshot {
  id: number;
  timestamp: string;
  total_pnl: number;
  today_pnl: number;
  total_trades: number;
  in_trade: number;
}

export interface PnLBreakdown {
  day: string;
  coin: string;
  side: string;
  trade_count: number;
  total_pnl: number;
  avg_pnl: number;
  wins: number;
  losses: number;
}

export interface TradeJournalResponse {
  trades: Trade[];
  total: number;
  returned: number;
  offset: number;
  limit: number;
  summary: {
    count: number;
    wins: number;
    losses: number;
    total_pnl: number;
  };
}

export type TabId = 'overview' | 'stats' | 'trades' | 'logs' | 'config' | 'trading' | 'performance';
