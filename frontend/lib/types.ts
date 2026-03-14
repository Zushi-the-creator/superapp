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
  rsi14: number;
  sma10: number;
  sma50: number;
  above_sma50: boolean;
  sma50_buffer: number; // % above SMA50 (strongest predictor)
  above_sma10: boolean;
  regime: string;
  tier: string; // EXTREME, STRONG, STANDARD, NONE
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
  days_held: number;  // days since entry
  // Hybrid exit strategy (per-stock optimal)
  exit_strategy: string;  // e.g. "SMA10", "RSI65", "Fixed14d"
  exit_strategy_wr: number;
  exit_strategy_ret: number;
  exit_strategy_hold: number;
  exit_strategy_target_days: number;  // target hold days (e.g. 21 for Fixed21d)
  exit_triggered: boolean;
  exit_momentum_override: boolean;  // True when exit overridden (winner still trending)
  // Exit price: dynamic level based on selected strategy
  exit_price: number;
  exit_price_pct: number;
  exit_label: string;
  // Walk-forward validation (OOS metrics)
  exit_strategy_oos_wr: number;
  exit_strategy_is_wr: number;
  exit_strategy_overfitting: number;  // IS/OOS ratio (>1.5 = overfitted)
  exit_strategy_validation: string;   // VALID / CAUTION / REJECTED / NO_DATA
  exit_strategy_oos_ci_lo: number;
  exit_strategy_oos_ci_hi: number;
  // Extended hours
  ext_price: number | null;
  ext_change_pct: number | null;
  market_session: string; // PRE_MARKET / REGULAR / AFTER_HOURS / CLOSED
  // Bayesian stats
  bayesian_wr?: number;
  wilson_lower?: number;
  trades_per_year?: number;
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
  day_pnl: number;
  day_pnl_pct: number;
  realized_pnl: number;
  total_fees: number;
  total_deposited: number;
  position_count: number;
  avg_win_rate: number;
  cash: number;
  market_session: string; // PRE_MARKET / REGULAR / AFTER_HOURS / CLOSED
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
  tier: string; // EXTREME, STRONG, STANDARD, NONE
  win_rate: number;
  trades: number;
  avg_return: number;
  zone_return: number;
  zone_trades: number;
  zone_win_rate: number;
  volume_ratio: number;
  hold_days: number;
  atr_pct: number;
  sma50_buffer: number;
  analyst_consensus: string;
  analyst_target: number;
  analyst_upside: number;
  sentiment_label: string;
  sentiment_score: number;
  vetoed: boolean;
  veto_reason: string;
  score: number;
  wr_tier: string; // TIER1 (80%+), TIER2 (70%+), TIER3 (65%+)
  // Composite ranking
  quality_tier: string; // BEST, GOOD, FAIR, WEAK, POOR
  composite_score: number; // 0-100
  ranking_factors: string; // "ZR:8.2 WR:75 RSI:3 ATR:5.1 ..."
  meets_strict: boolean; // passes all original strict ATLAS V2.5 criteria
  bayesian_wr?: number;
  beats_holdings: string[];
  is_upgrade: boolean;
}

export interface HoldingScore {
  ticker: string;
  score: number;
  zone_return: number;
  win_rate: number;
  exit_triggered: boolean;
  signal: string;
}

export interface ScanResponse {
  timestamp: string;
  total_scanned: number;
  passed: number;
  ranked_count: number; // total stocks ranked (includes non-strict)
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

export interface OptimalEntry {
  tier: string;       // EXTREME, STRONG, STANDARD, SUPPORT
  label: string;      // "RSI < 5", "RSI 5-10", etc.
  price: number;      // target entry price
  drop_pct: number;   // median % drop from recent high
  avg_return: number;  // backtested avg 7d return at this zone
  win_rate: number;
  trades: number;
}

export interface StockAnalysis {
  ticker: string;
  live_price: number;
  day_change_pct: number;
  rsi2: number;
  rsi14: number;
  sma50: number;
  above_sma50: boolean;
  regime: string;
  tier: string; // EXTREME, STRONG, STANDARD, NONE
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
  optimal_entries: OptimalEntry[];
  former_holding: {
    was_held: boolean;
    entry_price: number;
    exit_price: number;
    exit_date: string;
    entry_date: string;
    exit_pnl_pct: number;
    post_exit_pnl_pct: number;
    missed_gain_per_share: number;
    missed_gain_total: number;
    mistake: boolean;
  } | null;
}

export interface ChartCandle {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  sma50: number | null;
}

export interface ChartSignal {
  date: string;
  type: "BUY" | "OVERBOUGHT";
  price: number;
  rsi: number;
}

export interface ChartData {
  ticker: string;
  candles: ChartCandle[];
  signals: ChartSignal[];
  position: { entry_price: number; entry_date: string; shares: number } | null;
}

export interface TradePerformance {
  ticker: string;
  status: string;
  entry_date: string;
  exit_date: string;
  hold_days: number;
  entry_price: number;
  exit_price: number;
  shares: number;
  cost: number;
  value: number;
  pnl: number;
  pnl_pct: number;
  result: string;
}

export interface DailyPnL {
  date: string;
  portfolio_value: number;
  total_cost: number;
  pnl: number;
  pnl_pct: number;
  positions: number;
}

export interface PerformanceResponse {
  trades: TradePerformance[];
  daily_pnl: DailyPnL[];
  total_realized: number;
  total_unrealized: number;
  total_fees: number;
  total_deposited: number;
  realized_pnl_pct: number;
  tax_rate: number;
  tax_amount: number;
  net_realized: number;
  net_pnl_pct: number;
  win_count: number;
  loss_count: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  best_trade: string;
  worst_trade: string;
}

export type TabId = "portfolio" | "opportunities" | "performance" | "history";
