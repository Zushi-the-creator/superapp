"""
V2 API Schemas - Pydantic models for request/response
"""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


# ── Request Models ──

class BuyRequest(BaseModel):
    ticker: str
    shares: float
    price: float
    notes: str = ""


class SellRequest(BaseModel):
    ticker: str
    shares: float
    price: float
    notes: str = ""


# ── Response Models ──

class PositionDetail(BaseModel):
    id: int
    ticker: str
    shares: float
    entry_price: float
    entry_date: str
    current_price: float = 0
    day_change_pct: float = 0
    pnl: float = 0
    pnl_pct: float = 0
    cost_basis: float = 0
    current_value: float = 0
    weight: float = 0  # % of portfolio
    # Technical
    rsi2: float = -1
    rsi14: float = -1
    sma10: float = 0
    sma50: float = 0
    above_sma50: bool = True
    sma50_buffer: float = 0  # % above SMA50 (strongest predictor: 20%+ = +9.29% avg)
    above_sma10: bool = False
    regime: str = ""
    tier: str = "NONE"  # EXTREME, STRONG, STANDARD, NONE
    # Backtest
    win_rate: float = 0
    total_trades: int = 0
    avg_return: float = 0
    zone_return: float = 0
    zone_wr: float = 0
    zone_trades: int = 0
    rsi_zone: str = ""
    # Exit zone analysis (forward returns at current RSI, any entry)
    exit_zone_return: float = 0
    exit_zone_wr: float = 0
    exit_zone_trades: int = 0
    # Hybrid exit strategy (per-stock optimal, backtested)
    days_held: int = 0  # days since entry
    exit_strategy: str = ""  # e.g. "SMA10", "RSI65", "Fixed14d"
    exit_strategy_wr: float = 0
    exit_strategy_ret: float = 0  # avg return per trade
    exit_strategy_hold: float = 0  # avg hold days
    exit_strategy_target_days: int = 0  # target hold days (e.g. 21 for Fixed21d)
    exit_triggered: bool = False  # True when exit condition is met NOW
    exit_momentum_override: bool = False  # True when exit overridden (winner still trending)
    # Exit price: dynamic level based on selected strategy
    exit_price: float = 0
    exit_price_pct: float = 0  # % from current price to exit price
    exit_label: str = ""  # e.g. "SMA(10) $180 | +4.8% WR 94%"
    # Walk-forward validation (OOS metrics)
    exit_strategy_oos_wr: float = 0  # out-of-sample win rate
    exit_strategy_is_wr: float = 0   # in-sample win rate
    exit_strategy_overfitting: float = 0  # IS/OOS ratio (>1.5 = overfitted)
    exit_strategy_validation: str = ""  # VALID / CAUTION / REJECTED / NO_DATA
    exit_strategy_oos_ci_lo: float = 0  # Wilson CI lower bound
    exit_strategy_oos_ci_hi: float = 0  # Wilson CI upper bound
    # Bayesian / statistical confidence
    bayesian_wr: float = 0
    wilson_lower: float = 0
    trades_per_year: float = 0
    # 2yr safety gate (legacy, kept for backward compat)
    wr_2yr: float = 0
    avg_ret_2yr: float = 0
    trades_2yr: int = 0
    # Extended hours (pre-market / after-hours)
    ext_price: Optional[float] = None  # pre-market or after-hours price
    ext_change_pct: Optional[float] = None  # change % from close
    market_session: str = "CLOSED"  # PRE_MARKET / REGULAR / AFTER_HOURS / CLOSED
    # Rotation (V3.0: score gap > 2, min 10d held)
    rotation_target: Optional[str] = None
    rotation_score_gap: float = 0
    # Signal
    signal: str = "HOLD"
    issues: List[str] = []
    # Sparkline (last 20 closes)
    sparkline: List[float] = []
    # Exit targets (based on regime)
    stop_loss: float = 0
    target_1: float = 0
    target_2: float = 0
    stop_pct: float = 0    # e.g. -8.0
    target_1_pct: float = 0  # e.g. +10.0
    target_2_pct: float = 0  # e.g. +20.0


class PortfolioSummary(BaseModel):
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float
    day_pnl: float = 0  # Today's P&L in dollars
    day_pnl_pct: float = 0  # Today's P&L percentage
    realized_pnl: float = 0  # Total realized P&L from closed positions
    total_fees: float = 0  # Total trading fees paid
    total_deposited: float = 0  # Total capital deposited
    position_count: int
    max_positions: int = 5
    slots_available: int = 5
    avg_win_rate: float
    cash: float = 0
    market_session: str = "CLOSED"
    timestamp: str


class PortfolioResponse(BaseModel):
    summary: PortfolioSummary
    positions: List[PositionDetail]
    market_regime: dict = {}
    strategy_health: dict = {}


class HealthIssue(BaseModel):
    ticker: str
    severity: str  # CRITICAL, WARNING, INFO, OPPORTUNITY
    signal: str
    price: float
    day_change: str
    pnl: str
    issues: List[str]
    summary: str


class HealthCheckResponse(BaseModel):
    timestamp: str
    portfolio_value: float
    portfolio_pnl: float
    portfolio_pnl_pct: float
    holdings: int
    alerts_count: int
    has_critical: bool
    alerts: List[HealthIssue]
    positions: List[dict]
    last_check: str = ""


class ScanOpportunity(BaseModel):
    ticker: str
    price: float
    rsi2: float
    rsi_zone: str
    regime: str
    tier: str = "NONE"  # EXTREME, STRONG, STANDARD, NONE
    win_rate: float
    trades: int
    avg_return: float
    zone_return: float
    zone_trades: int
    zone_win_rate: float
    volume_ratio: float = 0
    hold_days: int = 30
    # ML-discovered features
    low52_dist: float = 0  # % distance from 52-week low
    atr_pct: float = 0     # ATR(14) as % of price
    sma50_buffer: float = 0  # % above SMA50 (V2.5: must be >= 10%)
    ret20: float = 0       # 20-day price momentum %
    ml_score: float = 0    # composite ML-weighted score
    bayesian_wr: float = 0
    analyst_consensus: str = ""
    analyst_target: float = 0
    analyst_upside: float = 0
    sentiment_label: str = ""
    sentiment_score: float = 0
    vetoed: bool = False
    veto_reason: str = ""
    score: float = 0  # zone_return * win_rate / 100
    wr_tier: str = ""  # TIER1 (80%+), TIER2 (70%+), TIER3 (65%+)
    # Composite ranking (loose filters)
    quality_tier: str = ""        # BEST/GOOD/FAIR/WEAK/POOR
    composite_score: float = 0    # 0-100 continuous ranking score
    ranking_factors: str = ""     # "ZR:8.2 WR:75 RSI:3 ATR:5.1 ..."
    meets_strict: bool = False    # passes all original strict ATLAS V2.5 criteria
    # Portfolio comparison
    beats_holdings: List[str] = []  # tickers in portfolio this stock beats
    is_upgrade: bool = False  # True if beats at least one holding


class HoldingScore(BaseModel):
    ticker: str
    score: float
    zone_return: float
    win_rate: float
    exit_triggered: bool = False
    signal: str = "HOLD"


class ScanResponse(BaseModel):
    timestamp: str
    total_scanned: int
    passed: int
    ranked_count: int = 0  # total stocks ranked (includes non-strict)
    opportunities: List[ScanOpportunity]
    holdings_scores: List[HoldingScore] = []  # current portfolio scores for comparison
    worst_holding: str = ""
    worst_score: float = 0
    last_scan: str = ""


class TransactionRecord(BaseModel):
    id: int
    ticker: str
    action: str  # BUY or SELL
    date: str
    price: float
    shares: float
    total: float
    fee: float = 1.50
    realized_pnl: Optional[float] = None
    notes: str = ""


class HistoryResponse(BaseModel):
    transactions: List[TransactionRecord]
    total_fees: float
    total_realized_pnl: float
    trade_count: int


class CacheStats(BaseModel):
    total_tickers: int
    total_rows: int
    last_updated: str
    stale_count: int


class TradeResult(BaseModel):
    success: bool
    message: str
    transaction_id: Optional[int] = None
    ticker: str = ""
    shares: float = 0
    price: float = 0
    total: float = 0
    fee: float = 1.50


class TradePerformance(BaseModel):
    ticker: str
    status: str  # OPEN or CLOSED
    entry_date: str
    exit_date: str  # "" if still open
    hold_days: int
    entry_price: float
    exit_price: float  # current_price if open
    shares: float
    cost: float
    value: float
    pnl: float
    pnl_pct: float
    result: str  # WIN, LOSS, OPEN


class DailyPnL(BaseModel):
    date: str
    portfolio_value: float
    total_cost: float
    pnl: float
    pnl_pct: float
    positions: int


class PerformanceResponse(BaseModel):
    trades: List[TradePerformance]
    daily_pnl: List[DailyPnL]
    total_realized: float
    total_unrealized: float
    total_fees: float
    total_deposited: float
    realized_pnl_pct: float
    tax_rate: float
    tax_amount: float
    net_realized: float
    net_pnl_pct: float
    win_count: int
    loss_count: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    best_trade: str
    worst_trade: str
    cagr: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_hold_days: float = 0.0
    total_trades: int = 0


class MomentumSignalResponse(BaseModel):
    ticker: str
    price: float
    trend_score: int = 0
    pct_from_high: float = 0
    pct_from_low: float = 0
    ret_5d: float = 0
    ret_20d: float = 0
    ret_60d: float = 0
    volume_ratio: float = 0
    atr_pct: float = 0
    atr_squeeze: float = 0
    momentum_score: float = 0
    analyst_consensus: str = ""
    sentiment_label: str = ""
    vetoed: bool = False
    veto_reason: str = ""
