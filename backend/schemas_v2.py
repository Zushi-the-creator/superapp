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
    sma50: float = 0
    above_sma50: bool = True
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
    position_count: int
    avg_win_rate: float
    cash: float = 0
    timestamp: str


class PortfolioResponse(BaseModel):
    summary: PortfolioSummary
    positions: List[PositionDetail]


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
    hold_days: int = 7
    analyst_consensus: str = ""
    analyst_target: float = 0
    analyst_upside: float = 0
    sentiment_label: str = ""
    sentiment_score: float = 0
    vetoed: bool = False
    veto_reason: str = ""
    score: float = 0  # zone_return * win_rate / 100
    # Portfolio comparison
    beats_holdings: List[str] = []  # tickers in portfolio this stock beats
    is_upgrade: bool = False  # True if beats at least one holding


class HoldingScore(BaseModel):
    ticker: str
    score: float
    zone_return: float
    win_rate: float


class ScanResponse(BaseModel):
    timestamp: str
    total_scanned: int
    passed: int
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
