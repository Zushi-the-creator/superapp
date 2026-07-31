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
  // Strategy (V3.0: MR=45d, MOM=60d hold)
  strategy: string; // "MEAN_REVERSION" | "MOMENTUM" | "BOTH"
  // Rotation (V3.0: score gap > 2, min 10d held)
  rotation_target: string | null;
  rotation_score_gap: number;
  // Upcoming events ("Next Event" column)
  next_earnings_date?: string | null;   // 'YYYY-MM-DD' next scheduled earnings
  days_to_earnings?: number | null;     // calendar days until earnings
  next_catalyst?: string | null;        // biotech catalyst title (trial / FDA / PDUFA)
  next_catalyst_date?: string | null;   // ISO date of upcoming catalyst
  next_catalyst_type?: string | null;   // phase / pdufa / fda / nda / conference / other
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
  total_tax: number;
  total_deposited: number;
  position_count: number;
  max_positions: number;
  slots_available: number;
  avg_win_rate: number;
  cash: number;
  yesterday_pnl: number;
  yesterday_pnl_pct: number;
  week_pnl: number;
  week_pnl_pct: number;
  market_session: string;
  timestamp: string;
}

export interface MarketRegime {
  regime: string;
  vix: number;
  vix_regime: string;
  spy_5d_return: number;
  spy_price?: number;
  spy_sma200?: number;
  sma200_gap_pct?: number;
  drawdown_pct?: number;
  position_size_pct: number;
  pause_entries: boolean;
  pause_mr?: boolean;
  reason: string;
}

export interface StrategyHealth {
  status: string;
  message: string;
  rolling_wr: number;
  expected_wr: number;
  trades_analyzed: number;
  wins?: number;
  losses?: number;
  gap_pp: number;
}

export interface PortfolioResponse {
  summary: PortfolioSummary;
  positions: PositionDetail[];
  market_regime?: MarketRegime;
  strategy_health?: StrategyHealth;
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
  ranking_factors: string; // "EV:3.4 WR:67 ATR:3.7 RSI:9 BUF:21 PX:51 [VOL<1x:CAP50]"
  meets_strict: boolean; // passes all original strict ATLAS V2.5 criteria
  bayesian_wr?: number;
  // Backend ScanOpportunity also ships these (schemas_v2.py:184-188); FE renders may want them.
  low52_dist?: number;
  ret20?: number;
  ml_score?: number;
  beats_holdings: string[];
  is_upgrade: boolean; // beats at least one holding (or no holdings yet) and not vetoed
}

export interface HoldingScore {
  ticker: string;
  score: number;
  zone_return: number;
  win_rate: number;
  exit_triggered: boolean;
  signal: string;
}

export interface DataFreshness {
  latest_close: string | null;          // YYYY-MM-DD of most recent close in cache
  trading_days_stale: number | null;    // approximate trading-day gap from today
  is_fresh: boolean;                    // true if today's or yesterday's close
}

export interface SystemStatus {
  stage: string;     // idle / refreshing_prices / scanning / ready / error
  message: string;
  progress: number;  // 0-100
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
  market_regime?: MarketRegime;
  data_freshness?: DataFreshness;
  system_status?: SystemStatus;
  cache_stale?: boolean;
  refreshing?: boolean;
  scanning?: boolean;
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
  proposed_strategy: {
    exit_strategy: string;
    exit_strategy_wr: number;
    exit_strategy_ret: number;
    exit_strategy_hold: number;
    validation: string;
  } | null;
  held_position: {
    is_held: boolean;
    entry_price: number;
    entry_date: string;
    shares: number;
    cost_basis: number;
    current_value: number;
    pnl: number;
    pnl_pct: number;
    days_held: number;
    strategy: string;
    exit_triggered: boolean;
    exit_label: string;
    target_hold_days: number;
    days_remaining: number;
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
  break_even_count?: number;
  win_rate: number;
  avg_win_pct: number;
  avg_loss_pct: number;
  best_trade: string;
  worst_trade: string;
  // Advanced metrics (V3.0)
  cagr: number;
  max_drawdown: number;
  sharpe_ratio: number;
  profit_factor: number;
  avg_hold_days: number;
  total_trades: number;
}

export type RRGQuadrant = "Leading" | "Weakening" | "Lagging" | "Improving" | "Unknown";

export interface RRGPoint {
  date: string;
  rs_ratio: number;
  rs_momentum: number;
}

export interface SectorData {
  etf: string;
  name: string;
  price: number;
  ret_5d: number;
  ret_20d: number;
  ret_60d: number;
  ret_ytd: number;
  mr_wr: number;
  mr_trades: number;
  mr_avg_ret: number;
  rsi14: number;
  above_sma50: boolean;
  trend: string;
  // RRG (relative rotation vs SPY)
  rs_ratio: number;
  rs_momentum: number;
  quadrant: RRGQuadrant;
  leadership_score: number;
  rank: number;
  trail: RRGPoint[];
}

export interface PortfolioSectorExposure {
  sector: string;
  tickers: string[];
  cost: number;
  value: number;
  weight: number;
  quadrant: RRGQuadrant;
}

export interface SectorCorrelation {
  window_days: number;
  etfs: string[];
  matrix: number[][];
  high_pairs: { a: string; b: string; corr: number }[];
  low_pairs: { a: string; b: string; corr: number }[];
}

export interface SectorHeadline {
  title: string;
  sentiment: number;
  label: "POSITIVE" | "NEUTRAL" | "NEGATIVE";
}

export interface SectorNews {
  etf: string;
  avg_sentiment: number;
  label: string;
  pos_count: number;
  neg_count: number;
  neutral_count: number;
  headlines: SectorHeadline[];
  updated: string;
}

export interface PortfolioImpactHolding {
  ticker: string;
  sector: string;
  etf: string | null;
  weight: number;
  quadrant: RRGQuadrant;
}

export interface PortfolioImpact {
  holdings: PortfolioImpactHolding[];
  quadrant_weights: {
    leading: number;
    improving: number;
    weakening: number;
    lagging: number;
    unknown: number;
  };
  leadership_score: number;
  concentration_hhi: number;
  concentration_label: "LOW" | "MODERATE" | "HIGH";
  avg_held_sector_correlation: number | null;
  flags: string[];
}

export interface SectorsResponse {
  timestamp: string;
  sectors: SectorData[];
  portfolio_exposure: PortfolioSectorExposure[];
  total_sectors_used: number;
  total_sectors: number;
  market_regime?: MarketRegime;
  rrg: {
    benchmark: string;
    ratio_window: number;
    momentum_window: number;
    as_of: string | null;
  };
  correlation: SectorCorrelation | null;
  news: Record<string, SectorNews> | null;
  news_refreshing?: boolean;
  portfolio_impact: PortfolioImpact;
}

export interface DataStatus {
  timestamp: string;
  today: string;
  market_session: string;
  cache: {
    stale_count: number;
    total_checked: number;
    universe_stale?: number;
    universe_total?: number;
    tickers: Record<string, { latest: string | null; rows: number; fresh: boolean }>;
  };
  quotes: {
    cached_count: number;
    tickers: Record<string, { price: number; age_sec: number | null }>;
  };
  extended_hours: {
    available: number;
    session: string;
    tickers: Record<string, { ext_price: number | null; session: string }>;
  };
  market_regime: {
    regime: string;
    pause_entries: boolean;
    position_size_pct?: number;
    reason?: string;
    spy_5d_return?: number;
    spy_price?: number;
    spy_price_live?: number;
    vix?: number;
  };
  scan_cache_age_min: number | null;
  backtest_cache?: {
    last_computed: string | null;
    age_hours: number | null;
    rows: number;
  };
  system: { stage: string; message: string; progress: number };
  portfolio_earnings?: {
    count: number;
    upcoming: Array<{
      ticker: string;
      kind: "upcoming" | "reported";
      direction: "past" | "future";
      age_hours: number;
      title: string;
      url: string;
      date: string;
    }>;
    reported: Array<{
      ticker: string;
      kind: "upcoming" | "reported";
      direction: "past" | "future";
      age_hours: number;
      title: string;
      url: string;
      date: string;
    }>;
    error?: string;
  };
  portfolio_catalysts?: {
    count: number;
    upcoming: Array<{
      ticker: string;
      kind: "upcoming" | "reported";
      direction: "past" | "future";
      age_hours: number;
      title: string;
      url: string;
      date: string;
      catalyst_type: "phase" | "pdufa" | "fda" | "nda" | "conference" | "other";
    }>;
    reported: Array<{
      ticker: string;
      kind: "upcoming" | "reported";
      direction: "past" | "future";
      age_hours: number;
      title: string;
      url: string;
      date: string;
      catalyst_type: "phase" | "pdufa" | "fda" | "nda" | "conference" | "other";
    }>;
    error?: string;
  };
}

export interface CombinedSignal {
  ticker: string;
  price: number;
  strategy: "MEAN_REVERSION" | "MOMENTUM" | "BOTH";
  strategy_label: string;
  score: number;
  expected_return: number;
  confidence: number;   // Bayesian WR
  trades: number;
  // Signal details
  rsi2: number;
  sma50_buffer: number;
  atr_pct: number;
  volume_ratio: number;
  ret_20d: number;
  ret_60d: number;
  pct_from_high: number;
  atr_squeeze: number;
  trend_score: number;
  // Validation
  analyst_consensus: string;
  sentiment_label: string;
  vetoed: boolean;
  veto_reason: string;
  data_date: string;       // When backtest evaluation ran
  scan_price?: number;     // Price when evaluation ran
  price_is_live?: boolean; // true = Finnhub live, false = cached
}

export interface CombinedResponse {
  timestamp: string;
  total: number;
  mean_reversion: number;
  momentum: number;
  both: number;
  data_date?: string;
  signals: CombinedSignal[];
  market_regime?: MarketRegime;
  system_status?: Record<string, unknown>;
  live_prices?: number; // count of updated prices
  cache_age_min?: number;
}

export type TabId = "portfolio" | "opportunities" | "trade" | "performance" | "history" | "sectors" | "sim";

// ── Simulator ($100k autonomous multi-strategy paper book) ──
export interface SimPosition {
  id: number;
  ticker: string;
  sleeve: "CORE" | "ALPHA";
  strategy: string;
  strategy_label: string;
  strategy_short: string;
  strategy_tier: string;
  exit_rule: string;
  origin: "MODEL" | "MANUAL";
  entry_date: string;
  entry_price: number;
  shares: number;
  cost_basis: number;
  hold_days: number;
  entry_composite: number;
  rationale: string;
  current_price: number;
  value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  days_held: number;
  days_remaining: number | null;
  weight_pct: number;
  price_stale: boolean;
}

export interface SimTradeStats {
  closed_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  avg_return_pct: number;
  best_trade_pct: number;
  worst_trade_pct: number;
  realized_pnl: number;
  profit_factor: number | null;
}

export interface SimStats extends SimTradeStats {
  max_drawdown_pct: number;
  snapshots: number;
  by_strategy: Record<string, SimTradeStats>;
  by_origin: Record<string, SimTradeStats>;
}

export interface SimStrategy {
  id: string;
  label: string;
  short: string;
  tier: "A" | "B" | "C";
  kind: "CORE" | "ALPHA";
  source: string;
  exit_rule: string;
  thesis: string;
  evidence: string;
  enabled: boolean;
  slots: number;
  open_positions: number;
  value: number;
  weight_pct: number;
  unrealized_pnl: number;
  target_pct: number | null;
  stats: SimTradeStats;
}

export interface SimCandidate {
  ticker: string;
  price: number;
  signal_strategy: string;
  composite_score: number;
  quality_tier: string;
  rsi2: number;
  atr_pct: number;
  sma50_buffer: number;
  ret_20d: number;
  high52_dist: number | null;
  win_rate: number;
  trades: number;
  expected_return: number;
  analyst_consensus: string;
  sentiment_label: string;
  held: boolean;
  eligible_strategies: string[];
  blocked_reason: string;
}

export interface SimCandidatesResponse {
  candidates: SimCandidate[];
  regime: Record<string, unknown>;
  rotation_ranks: string[];
  market_session: string;
}

export interface SimConfig {
  enabled: number;
  starting_capital: number;
  cycle_minutes: number;
  core_ticker: string;
  core_target_pct: number;
  core_band_pct: number;
  strategy_enabled: Record<string, number>;
  strategy_slots: Record<string, number>;
  max_position_pct: number;
  min_position_usd: number;
  min_composite: number;
  max_per_sector: number;
  rotation_enabled: number;
  rotation_min_gap: number;
  rotation_min_days: number;
  commission_usd: number;
  slippage_bps: number;
  cash_floor_usd: number;
}

export interface SimEquityPoint {
  date: string;
  equity: number;
  cash: number;
  positions_value: number;
  core_value: number;
  alpha_value: number;
  open_positions: number;
  bench_price: number;
  bench_equity: number;
  regime: string;
}

export interface SimDecision {
  id: number;
  ts: string;
  cycle_id: string;
  kind: "CYCLE" | "ENTRY" | "EXIT" | "HOLD" | "SKIP" | "REBALANCE" | "PAUSE" | "SWITCH" | "MANUAL" | "CONFIG";
  ticker: string;
  action: string;
  strategy: string;
  strategy_label: string;
  origin: "MODEL" | "MANUAL";
  reason: string;
  regime: string;
  composite: number;
  detail: Record<string, unknown>;
}

export interface SimState {
  timestamp: string;
  inception: string | null;
  days_live: number;
  starting_capital: number;
  equity: number;
  cash: number;
  positions_value: number;
  core_value: number;
  alpha_value: number;
  core_pct: number;
  alpha_pct: number;
  cash_pct: number;
  total_pnl: number;
  roi_pct: number;
  bench_ticker: string;
  bench_equity: number;
  bench_roi_pct: number;
  alpha_vs_bench_pp: number;
  positions: SimPosition[];
  config: SimConfig;
  strategies: SimStrategy[];
  stats: SimStats;
  regime: Record<string, unknown>;
  equity_curve: SimEquityPoint[];
  market_session: string;
  cycle_running: boolean;
}

export interface SimClosedPosition {
  id: number;
  ticker: string;
  strategy: string;
  origin: string;
  entry_date: string;
  entry_price: number;
  exit_date: string;
  exit_price: number;
  shares: number;
  cost_basis: number;
  exit_reason: string;
  realized_pnl: number;
}

export interface SimHistoryResponse {
  closed_positions: SimClosedPosition[];
  transactions: Array<{
    id: number;
    ts: string;
    date: string;
    ticker: string;
    action: string;
    price: number;
    shares: number;
    fee: number;
    cash_delta: number;
    realized_pnl: number | null;
    sleeve: string;
    strategy: string;
    origin: string;
    reason: string;
  }>;
  stats: SimStats;
}


// ── MIX9 engine ──
export interface Mix9Pick { ticker: string; target_usd: number; price: number; shares: number }
export interface Mix9Trade {
  ticker: string; side: string; usd: number; current_usd: number; target_usd: number;
}
export interface Mix9State {
  pending?: boolean; message?: string; computed_at?: string;
  target?: {
    asof: string; regime: string; active_strategy: string; dd_pct: number;
    dd_stop_pct: number; parked: boolean; equity_usd: number; sleeve_usd: number;
    core: { ticker: string; target_usd: number; price: number; shares: number };
    sleeve: Mix9Pick[]; preview_sleeve?: Mix9Pick[];
    components: Record<string, { dd_pct: number; parked: boolean }>;
  };
  trades?: Mix9Trade[];
  engine?: { core_ticker: string; enabled: boolean; dd_stop_pct: number; note: string };
}
