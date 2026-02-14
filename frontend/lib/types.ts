// V2 API Types - mirrors backend schemas_v2.py

export interface PositionDetail {
  id: number;
  ticker: string;
  shares: number;
  entry_price: number;
  entry_date: string;
  current_price: number;
  day_change_pct: number;
  pnl: number;
  pnl_pct: number;
  cost_basis: number;
  current_value: number;
  weight: number;
  // Technical
  rsi2: number;
  sma50: number;
  above_sma50: boolean;
  regime: string;
  // Backtest
  win_rate: number;
  total_trades: number;
  avg_return: number;
  zone_return: number;
  zone_wr: number;
  zone_trades: number;
  rsi_zone: string;
  // Exit zone analysis (forward returns at current RSI, any entry)
  exit_zone_return: number;
  exit_zone_wr: number;
  exit_zone_trades: number;
  // Signal
  signal: string;
  issues: string[];
  // Sparkline
  sparkline: number[];
  // Exit targets
  stop_loss: number;
  target_1: number;
  target_2: number;
  stop_pct: number;
  target_1_pct: number;
  target_2_pct: number;
}

export interface PortfolioSummary {
  total_value: number;
  total_cost: number;
  total_pnl: number;
  total_pnl_pct: number;
  position_count: number;
  avg_win_rate: number;
  cash: number;
  timestamp: string;
}

export interface PortfolioResponse {
  summary: PortfolioSummary;
  positions: PositionDetail[];
}

export interface HealthIssue {
  severity: string;
  ticker: string;
  signal: string;
  price: number;
  day_change: string;
  pnl: string;
  issues: string[];
  summary: string;
}

export interface HealthCheckResponse {
  timestamp: string;
  portfolio_value: number;
  portfolio_pnl: number;
  portfolio_pnl_pct: number;
  holdings: number;
  alerts_count: number;
  has_critical: boolean;
  alerts: HealthIssue[];
  positions: Record<string, unknown>[];
  last_check: string;
}

export interface ScanOpportunity {
  ticker: string;
  price: number;
  rsi2: number;
  rsi_zone: string;
  regime: string;
  win_rate: number;
  trades: number;
  avg_return: number;
  zone_return: number;
  zone_trades: number;
  zone_win_rate: number;
  volume_ratio: number;
  hold_days: number;
  analyst_consensus: string;
  analyst_target: number;
  analyst_upside: number;
  sentiment_label: string;
  sentiment_score: number;
  vetoed: boolean;
  veto_reason: string;
  score: number;
  beats_holdings: string[];
  is_upgrade: boolean;
}

export interface HoldingScore {
  ticker: string;
  score: number;
  zone_return: number;
  win_rate: number;
}

export interface ScanResponse {
  timestamp: string;
  total_scanned: number;
  passed: number;
  opportunities: ScanOpportunity[];
  holdings_scores: HoldingScore[];
  worst_holding: string;
  worst_score: number;
  last_scan: string;
}

export interface TransactionRecord {
  id: number;
  ticker: string;
  action: string;
  date: string;
  price: number;
  shares: number;
  total: number;
  fee: number;
  realized_pnl: number | null;
  notes: string;
}

export interface HistoryResponse {
  transactions: TransactionRecord[];
  total_fees: number;
  total_realized_pnl: number;
  trade_count: number;
}

export interface TradeResult {
  success: boolean;
  message: string;
  transaction_id?: number;
  ticker: string;
  shares: number;
  price: number;
  total: number;
  fee: number;
}

export interface StockAnalysis {
  ticker: string;
  live_price: number;
  day_change_pct: number;
  rsi2: number;
  sma50: number;
  above_sma50: boolean;
  regime: string;
  win_rate: number;
  total_trades: number;
  avg_return: number;
  exit_zone_return: number;
  exit_zone_wr: number;
  exit_zone_trades: number;
  rsi_zone: string;
  score: number;
  sentiment_label: string;
  sentiment_score: number;
  headlines: string[];
  analyst_consensus: string;
  analyst_target: number;
  analyst_upside: number;
  earnings_date: string | null;
  signal: string;
  issues: string[];
  stop_loss: number;
  target_1: number;
  target_2: number;
  sparkline: number[];
}

export type TabId = "portfolio" | "history";
