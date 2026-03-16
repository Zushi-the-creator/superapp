"""
V2 API Router - Live Portfolio Dashboard
=========================================
Wraps portfolio_check.py, deep_scanner.py, and positions.py into REST endpoints.
Background monitor runs health checks every 15 minutes.
"""

import asyncio
import aiohttp
import bisect
import json
import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schemas_v2 import (
    BuyRequest, SellRequest, TradeResult,
    PortfolioResponse, PortfolioSummary, PositionDetail,
    HealthCheckResponse, HealthIssue,
    ScanResponse, ScanOpportunity, HoldingScore,
    HistoryResponse, TransactionRecord,
    CacheStats,
    PerformanceResponse, TradePerformance, DailyPnL,
)
from positions import PositionManager
from data_cache import DataCache
from atlas_v2.entry import EntryEngine
from atlas_v2.regime import RegimeDetector

router = APIRouter(prefix="/api/v2", tags=["V2 Dashboard"])

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0")

# Shared state
_position_mgr = PositionManager(db_path=os.path.join(os.path.dirname(__file__), "data", "positions.db"))
_cache = DataCache()
_entry = EntryEngine()

# Cached results from background monitor
_health_cache: Optional[Dict] = None
_health_cache_time: Optional[datetime] = None
_scan_cache: Optional[Dict] = None
_scan_cache_time: Optional[datetime] = None

# ── Centralized Quote Management ──
# Single source of truth for live prices. Background task refreshes every 30s.
# All endpoints read from here instead of hitting Finnhub directly.
_price_cache: Dict[str, Dict] = {}   # ticker -> last known good quote (persistent)
_quote_cache: Dict[str, tuple] = {}  # ticker -> (result, timestamp) — 30s TTL

# ── Technicals Cache (background-computed, never blocks event loop) ──
_technicals_cache: Dict[str, Dict] = {}  # ticker -> full _get_technicals() result
# Evicted when positions close or after 1 hour of staleness
_technicals_computing: bool = False       # True while background loop is running
QUOTE_CACHE_TTL = 30  # seconds
_finnhub_calls_this_minute: int = 0
_finnhub_minute_start: Optional[datetime] = None
FINNHUB_MAX_PER_MIN = 50  # Leave headroom from 60/min limit

# ── Extended Hours (Pre-Market / After-Hours) ──
_extended_hours_cache: Dict[str, Dict] = {}  # ticker -> {ext_price, ext_change_pct, session, ts}


def _get_market_session() -> str:
    """Return current US market session based on ET time.
    PRE_MARKET:   4:00 AM - 9:30 AM ET (Mon-Fri)
    REGULAR:      9:30 AM - 4:00 PM ET (Mon-Fri)
    AFTER_HOURS:  4:00 PM - 8:00 PM ET (Mon-Fri)
    CLOSED:       Weekends + outside 4am-8pm
    """
    try:
        import pytz
        et = datetime.now(pytz.timezone("US/Eastern"))
    except ImportError:
        # Fallback: offset-based (close enough for ET)
        from datetime import timezone
        et = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=5)
    day = et.weekday()  # 0=Mon, 6=Sun
    if day >= 5:
        return "CLOSED"
    minutes = et.hour * 60 + et.minute
    if 240 <= minutes < 570:      # 4:00 AM - 9:30 AM
        return "PRE_MARKET"
    elif 570 <= minutes < 960:     # 9:30 AM - 4:00 PM
        return "REGULAR"
    elif 960 <= minutes < 1200:    # 4:00 PM - 8:00 PM
        return "AFTER_HOURS"
    return "CLOSED"


def _fetch_extended_quote_sync(ticker: str) -> Optional[Dict]:
    """Fetch pre-market or after-hours price from Yahoo Finance chart API.
    Uses the lightweight v8/chart endpoint (less rate-limited than v10/quoteSummary).
    Falls back to Finnhub if Yahoo fails."""
    import requests as _req
    session = _get_market_session()

    # Try Yahoo Finance chart API (provides actual PM/AH data)
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = _req.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?range=1d&interval=1m&includePrePost=true",
            headers=headers, timeout=8,
        )
        if resp.status_code == 200:
            chart = resp.json().get("chart", {}).get("result", [{}])[0]
            meta = chart.get("meta", {})
            reg_close = meta.get("chartPreviousClose", 0) or meta.get("previousClose", 0)
            reg_price = meta.get("regularMarketPrice", 0)

            ext_price = None
            if session == "PRE_MARKET":
                # During pre-market: regularMarketPrice is last close, current price from timestamps
                ts_data = chart.get("timestamp", [])
                closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                if ts_data and closes:
                    # Last non-null close in the series is the latest PM price
                    for i in range(len(closes) - 1, -1, -1):
                        if closes[i] is not None:
                            ext_price = closes[i]
                            break
                # Use reg_price as base (yesterday's close)
                base_price = reg_price or reg_close
            elif session == "AFTER_HOURS":
                ts_data = chart.get("timestamp", [])
                closes = chart.get("indicators", {}).get("quote", [{}])[0].get("close", [])
                if ts_data and closes:
                    for i in range(len(closes) - 1, -1, -1):
                        if closes[i] is not None:
                            ext_price = closes[i]
                            break
                base_price = reg_price  # today's close
            else:
                return None

            if ext_price and ext_price > 0 and base_price and base_price > 0:
                # Only return if ext_price differs from base (actual PM/AH activity)
                if abs(ext_price - base_price) / base_price > 0.001:  # > 0.1% diff
                    ext_change = round(((ext_price - base_price) / base_price) * 100, 2)
                    return {
                        "ext_price": round(ext_price, 2),
                        "ext_change_pct": ext_change,
                        "session": session,
                        "ts": datetime.now(),
                    }
    except Exception as e:
        print(f"[ExtHours] {ticker} Yahoo error: {e}")

    return None

# WebSocket connections for alerts
_ws_connections: List[WebSocket] = []


# ── Production Detection ──
_is_prod = bool(os.environ.get("FLY_APP_NAME"))

# ── Helpers ──

def _exit_targets_by_regime(regime: str) -> tuple:
    """Return (stop_pct, target_1_pct, target_2_pct) based on regime.
    V2.4: Removed tight stops — research proves they hurt mean reversion.
    Only catastrophic SMA50 break triggers exit. Targets kept for reference."""
    if regime == "BULL":
        return (-20.0, 10.0, 20.0)
    elif regime == "SIDEWAYS":
        return (-15.0, 5.0, 10.0)
    else:  # BEAR
        return (-12.0, 3.0, 6.0)


def _check_finnhub_rate() -> bool:
    """Check if we can make another Finnhub call. Returns True if under limit."""
    global _finnhub_calls_this_minute, _finnhub_minute_start
    now = datetime.now()
    if _finnhub_minute_start is None or (now - _finnhub_minute_start).total_seconds() >= 60:
        _finnhub_calls_this_minute = 0
        _finnhub_minute_start = now
    return _finnhub_calls_this_minute < FINNHUB_MAX_PER_MIN

def _record_finnhub_call():
    """Record a Finnhub API call."""
    global _finnhub_calls_this_minute
    _finnhub_calls_this_minute += 1

async def _get_finnhub_quote(session: aiohttp.ClientSession, ticker: str) -> Optional[Dict]:
    """Get live quote from Finnhub. 30s cache + rate limiter + last-known-good fallback."""
    # Return cached quote if fresh (avoids redundant API calls)
    if ticker in _quote_cache:
        cached_result, cached_time = _quote_cache[ticker]
        if (datetime.now() - cached_time).total_seconds() < QUOTE_CACHE_TTL:
            return cached_result

    # Check rate limit before calling
    if not _check_finnhub_rate():
        if ticker in _price_cache:
            return _price_cache[ticker]
        return None

    _timeout = 4 if os.environ.get("FLY_APP_NAME") else 8
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        _record_finnhub_call()
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=_timeout)) as resp:
            if resp.status == 429:
                if ticker in _price_cache:
                    _quote_cache[ticker] = (_price_cache[ticker], datetime.now())
                    return _price_cache[ticker]
                return None
            if resp.status == 200:
                data = await resp.json()
                if data.get("c", 0) > 0:
                    pc = data.get("pc", data["c"])
                    result = {
                        "price": data["c"],
                        "prev_close": pc,
                        "day_chg": (data["c"] - pc) / pc * 100 if pc else 0,
                    }
                    _price_cache[ticker] = result
                    _quote_cache[ticker] = (result, datetime.now())
                    return result
    except Exception:
        pass
    if ticker in _price_cache:
        return _price_cache[ticker]
    return None


# ── Exit Strategy (V2.6 — Research-Backed) ──
# Studies (Connors, Alvarez, BuildAlpha) + our 307,446 trade mega-backtest confirm:
#   - Trailing stops HURT mean reversion (44% WR — worst of all strategies)
#   - Stop losses HURT mean reversion (Connors: "stops hurt performance on hundreds of thousands of trades")
#   - SMA/RSI exits too fast for volatile stocks (+0.38% avg vs Fixed30d +4.31%)
#   - ONLY Fixed time exits work for mean reversion
# Walk-forward selection among Fixed14d/21d/30d ONLY:
#   - WF_Fixed: +3.80%, PF 2.27, 22.5d avg hold, 42.6% annualized (BEST)
#   - Fixed30d: +3.99%, PF 2.08, 30.0d avg hold, 33.5% annualized
#   - Per-stock pick: 46.7% get 30d, 27.8% get 21d, 25.5% get 14d

_exit_strategy_cache: Dict[str, Dict] = {}  # ticker -> {strategy, wr, avg_ret, ...}
_EXIT_CACHE_TTL = 21600  # 6 hours

_EXIT_STRATEGIES = {
    "Fixed30d": {"type": "fixed", "days": 30},
}


def _wilson_ci(wins: int, total: int, z: float = 1.96):
    """Wilson score confidence interval for win rate (as %).
    Returns (lower_bound_pct, upper_bound_pct)."""
    if total == 0:
        return 0.0, 0.0
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = z * (p * (1 - p) / total + z**2 / (4 * total**2)) ** 0.5 / denom
    return round(max(0, center - spread) * 100, 1), round(min(1, center + spread) * 100, 1)


def _backtest_one_strategy(name: str, strat: dict, closes: list, rsi2_arr, sma50_arr, start_idx: int, end_idx: int, opens: list = None) -> list:
    """Backtest a single exit strategy on a date range. Returns list of trade dicts.
    V2.4: RSI<10 entry, next-day open execution, fee-adjusted returns, non-overlapping."""
    trades = []
    max_hold = 30
    _FEE_PCT = 0.30  # $3 round-trip on $1000
    last_exit_day = -1  # Prevent overlapping trades
    for i in range(max(50, start_idx), min(end_idx, len(closes) - max_hold - 1)):  # -1 for entry day offset
        if i <= last_exit_day:
            continue
        if rsi2_arr[i] >= 10 or closes[i] <= sma50_arr[i] or sma50_arr[i] <= 0:
            continue
        # V2.4: Use next-day open for realistic execution
        if opens and i + 1 < len(opens) and opens[i + 1] > 0:
            entry_price = opens[i + 1]
        else:
            entry_price = closes[i]
        exit_price = None
        hold = 0

        # All exits are relative to entry day (i+1), not signal day (i)
        # d counts days AFTER entry: d=1 means first close after entry open
        if strat["type"] == "fixed":
            d = strat["days"]
            if i + 1 + d < len(closes):
                exit_price = closes[i + 1 + d]; hold = d

        elif strat["type"] == "sma":
            period = strat["period"]
            for d in range(1, max_hold + 1):
                if i + 1 + d >= len(closes): break
                start = max(0, i + 1 + d - period + 1)
                sl = closes[start:i + 1 + d + 1]
                sma_val = sum(sl) / len(sl) if len(sl) >= period else 0
                if closes[i + 1 + d] > sma_val > 0:
                    exit_price = closes[i + 1 + d]; hold = d; break
            if exit_price is None and i + 1 + max_hold < len(closes):
                exit_price = closes[i + 1 + max_hold]; hold = max_hold

        elif strat["type"] == "rsi_exit":
            threshold = strat["threshold"]
            for d in range(1, max_hold + 1):
                if i + 1 + d >= len(closes): break
                if rsi2_arr[i + 1 + d] > threshold:
                    exit_price = closes[i + 1 + d]; hold = d; break
            if exit_price is None and i + 1 + max_hold < len(closes):
                exit_price = closes[i + 1 + max_hold]; hold = max_hold

        elif strat["type"] == "stop_target":
            stop_pct = strat["stop_pct"]; target_pct = strat["target_pct"]
            for d in range(1, max_hold + 1):
                if i + 1 + d >= len(closes): break
                ret_d = (closes[i + 1 + d] - entry_price) / entry_price * 100
                if ret_d <= stop_pct or ret_d >= target_pct:
                    exit_price = closes[i + 1 + d]; hold = d; break
            if exit_price is None and i + 1 + max_hold < len(closes):
                exit_price = closes[i + 1 + max_hold]; hold = max_hold

        elif strat["type"] == "trailing":
            trail_pct = strat["trail_pct"]; peak = entry_price
            for d in range(1, max_hold + 1):
                if i + 1 + d >= len(closes): break
                peak = max(peak, closes[i + 1 + d])
                if closes[i + 1 + d] <= peak * (1 - trail_pct / 100):
                    exit_price = closes[i + 1 + d]; hold = d; break
            if exit_price is None and i + 1 + max_hold < len(closes):
                exit_price = closes[i + 1 + max_hold]; hold = max_hold

        if exit_price is not None:
            ret = (exit_price / entry_price - 1) * 100 - _FEE_PCT  # V2.4: fee-adjusted
            trades.append({"ret": ret, "hold": hold, "win": ret > 0})
            last_exit_day = i + 1 + hold  # Skip until this trade exits
    return trades



def _select_best_exit(ticker: str, closes: list, _unused_trades: list = None, current_rsi: float = 0, entry_price: float = 0, entry_date: str = "", opens: list = None) -> Dict:
    """Universal Fixed30d exit for all stocks (V2.6).

    Research (Connors/Alvarez/BuildAlpha) + our 307K trade mega-backtest:
    Fixed30d: +4.31% avg, 61.0% WR, PF 2.21 — best single strategy.
    Per-stock walk-forward selection removed — unreliable on low-trade stocks.
    """
    cache_key = ticker
    current_price = closes[-1] if closes else 0

    # Check cache with TTL
    if cache_key in _exit_strategy_cache:
        cached = _exit_strategy_cache[cache_key]
        cache_time = cached.get("_cached_at", 0)
        if cache_time > 0:
            age = (datetime.now() - datetime.fromtimestamp(cache_time)).total_seconds()
            if age < _EXIT_CACHE_TTL:
                return _evaluate_exit_trigger(cached, closes, current_rsi, current_price, entry_price=entry_price, entry_date=entry_date)

    # Backtest Fixed30d on this stock's historical data
    _FEE_PCT = 0.30
    days = 30

    rsi2_arr = [50.0] * len(closes)
    for i in range(2, len(closes)):
        deltas = [closes[j] - closes[j-1] for j in range(max(0, i-1), i+1)]
        gains = sum(d for d in deltas if d > 0) / 2
        losses = -sum(d for d in deltas if d < 0) / 2
        rsi2_arr[i] = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)

    sma50_arr = [0.0] * len(closes)
    for i in range(49, len(closes)):
        sma50_arr[i] = sum(closes[i-49:i+1]) / 50

    # Full-sample backtest for Fixed30d stats
    full_trades = []
    last_exit = -1
    for i in range(50, len(closes) - days - 2):
        if rsi2_arr[i] >= 10 or closes[i] <= sma50_arr[i] or sma50_arr[i] <= 0:
            continue
        if i <= last_exit:
            continue
        ed = i + 1
        if ed + days >= len(closes):
            continue
        ep = opens[ed] if opens and ed < len(opens) and opens[ed] > 0 else closes[i]
        if ep <= 0:
            continue
        ret = ((closes[ed + days] - ep) / ep) * 100 - _FEE_PCT
        full_trades.append(ret)
        last_exit = ed + days

    n = len(full_trades)
    wr = round(sum(1 for r in full_trades if r > 0) / n * 100, 1) if n > 0 else 0
    avg_ret = round(sum(full_trades) / n, 2) if n > 0 else 0
    ci_lo, ci_hi = _wilson_ci(sum(1 for r in full_trades if r > 0), n) if n > 0 else (0, 0)

    result = {
        "strategy": "Fixed30d", "wr": wr,
        "avg_ret": avg_ret, "avg_hold": 30,
        "oos_wr": wr, "is_wr": wr,
        "overfitting_ratio": 1.0, "validation_note": "UNIVERSAL_FIXED30D",
        "overfit": 1.0, "validation": "UNIVERSAL_FIXED30D",
        "ci_lo": ci_lo, "ci_hi": ci_hi,
        "oos_ci_lo": ci_lo, "oos_ci_hi": ci_hi,
        "_cached_at": datetime.now().timestamp(),
    }
    _exit_strategy_cache[cache_key] = result

    return _evaluate_exit_trigger(result, closes, current_rsi, current_price, entry_price=entry_price, entry_date=entry_date)


def _evaluate_exit_trigger(cached: Dict, closes: list, current_rsi: float, current_price: float, entry_price: float = 0, entry_date: str = "") -> Dict:
    """Check if Fixed30d exit is triggered RIGHT NOW.

    V2.6: Universal Fixed30d exit. No stops, no trailing stops, no RSI exits.
    Research (Connors/Alvarez/BuildAlpha) proves stops HURT mean reversion.

    MOMENTUM OVERRIDE: When 30d triggers but stock is profitable (>5%) AND
    trending up (price > SMA5), switch to -8% trailing stop from peak.
    """
    strategy = cached["strategy"]
    triggered = False
    exit_price = 0.0
    momentum_override = False

    # Pre-compute for momentum check
    sma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else 0
    pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0

    # Peak price since entry for momentum override trailing stop
    if entry_date:
        try:
            from datetime import date as _date
            days_held_for_peak = (_date.today() - _date.fromisoformat(entry_date)).days
            peak_window = max(1, min(days_held_for_peak + 1, len(closes)))
            peak_price = max(closes[-peak_window:]) if peak_window > 0 else current_price
            peak_price = max(peak_price, entry_price) if entry_price > 0 else peak_price
        except Exception:
            peak_price = max(closes[-20:]) if len(closes) >= 20 else current_price
    else:
        peak_price = max(closes[-20:]) if len(closes) >= 20 else current_price

    # Fixed exit: exit after N TRADING days from entry (14/21/30 per walk-forward)
    hold_target = _EXIT_STRATEGIES.get(strategy, {}).get("days", 30)
    exit_price = round(current_price * (1 + cached.get("avg_ret", 0) / 100), 2)
    if entry_date:
        try:
            from datetime import date as _date
            entry_d = _date.fromisoformat(entry_date)
            today_d = _date.today()
            trading_days_held = sum(
                1 for n in range((today_d - entry_d).days)
                if (entry_d + timedelta(days=n + 1)).weekday() < 5
            )
            triggered = trading_days_held >= hold_target
        except Exception:
            triggered = False

    # ── MOMENTUM OVERRIDE ──
    # If 30d exit triggers but stock is a profitable winner still trending up,
    # DON'T exit — switch to -8% trailing stop from peak instead.
    MOMENTUM_PNL_THRESHOLD = 5.0
    TRAILING_STOP_PCT = 8.0

    if triggered and pnl_pct >= MOMENTUM_PNL_THRESHOLD and current_price > sma5 > 0:
        trail_level = round(peak_price * (1 - TRAILING_STOP_PCT / 100), 2)
        if current_price > trail_level:
            momentum_override = True
            triggered = False
            exit_price = trail_level
        else:
            exit_price = trail_level

    exit_price_pct = round((exit_price - current_price) / current_price * 100, 2) if current_price > 0 and exit_price > 0 else 0

    # Build label
    wr = cached.get("wr", 0)
    avg_ret = cached.get("avg_ret", 0)

    if momentum_override:
        label = f"RIDING +{pnl_pct:.1f}% | Trail -8% ${exit_price:.0f}"
    else:
        label = f"Hold {hold_target}d | +{avg_ret:.1f}% WR {wr:.0f}%"

    if triggered:
        label = "EXIT NOW: " + label

    result = {
        "strategy": strategy, "wr": wr, "avg_ret": avg_ret, "avg_hold": 30,
        "triggered": triggered, "exit_price": exit_price, "exit_price_pct": exit_price_pct,
        "label": label,
        "momentum_override": momentum_override,
        "oos_wr": cached.get("oos_wr", 0),
        "is_wr": cached.get("is_wr", 0),
        "overfit": cached.get("overfit", 0),
        "validation": cached.get("validation", ""),
        "oos_ci_lo": cached.get("oos_ci_lo", 0),
        "oos_ci_hi": cached.get("oos_ci_hi", 0),
    }
    return result


def _wilson_lower(wins: int, total: int, z: float = 1.96) -> float:
    """Wilson score lower bound — 95% CI floor for win rate."""
    if total == 0:
        return 0.0
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = z * ((p * (1 - p) + z**2 / (4 * total)) / total) ** 0.5 / denom
    return round(max(0, center - spread) * 100, 1)

# Universe prior for Bayesian shrinkage (from 27,877-trade mega-backtest)
_UNIVERSE_WR = 53.5  # pooled WR across 2,683 stocks
_BAYESIAN_PRIOR_WEIGHT = 10  # equivalent to 10 "phantom" trades at universe WR

def _bayesian_wr(wins: int, total: int) -> float:
    """Bayesian shrinkage: pull observed WR toward universe prior.
    Small samples get pulled hard; large samples trusted at face value."""
    prior_wins = _UNIVERSE_WR / 100 * _BAYESIAN_PRIOR_WEIGHT
    prior_losses = _BAYESIAN_PRIOR_WEIGHT - prior_wins
    return round((wins + prior_wins) / (total + _BAYESIAN_PRIOR_WEIGHT) * 100, 1)


def _rsi2_array(closes: list) -> list:
    """Pre-compute RSI(2) for ALL bars in O(n). Matches EntryEngine.calc_rsi exactly.
    63x faster than per-bar slicing (0.8ms vs 64ms for 1260 bars)."""
    n = len(closes)
    rsi = [50.0] * n
    for i in range(2, n):
        c1 = closes[i] - closes[i-1]
        c2 = closes[i-1] - closes[i-2]
        avg_gain = (max(0, c1) + max(0, c2)) / 2
        avg_loss = (max(0, -c1) + max(0, -c2)) / 2
        if avg_loss == 0:
            rsi[i] = 100.0 if avg_gain > 0 else 50.0
        else:
            rsi[i] = 100.0 - (100.0 / (1 + avg_gain / avg_loss))
    return rsi


def _sma_array(closes: list, period: int) -> list:
    """Pre-compute SMA for ALL bars in O(n). Rolling window."""
    n = len(closes)
    sma = [0.0] * n
    if n < period:
        return sma
    running = sum(closes[:period])
    sma[period-1] = running / period
    for i in range(period, n):
        running += closes[i] - closes[i - period]
        sma[i] = running / period
    return sma


def _get_technicals(ticker: str, entry_price: float = 0, entry_date: str = "") -> Dict:
    """Get RSI, SMA50, regime, backtest stats from cache.
    5yr (1260d) lookback for robust backtests.
    Uses pre-computed RSI/SMA arrays for 63x faster backtesting.
    """
    df = _cache.get(ticker, 1260)
    if df is None or len(df) < 60:
        # Fallback: try fetching from Stooq directly (for cold cache on Fly)
        try:
            stooq_url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&d1={(datetime.now() - timedelta(days=800)).strftime('%Y%m%d')}&d2={datetime.now().strftime('%Y%m%d')}&i=d"
            stooq_df = pd.read_csv(stooq_url)
            if len(stooq_df) >= 60:
                stooq_df['Date'] = pd.to_datetime(stooq_df['Date'])
                stooq_df = stooq_df.set_index('Date').sort_index()
                _cache.store(ticker, stooq_df)
                df = stooq_df
                print(f"[TechFallback] Fetched {ticker} from Stooq: {len(df)} bars")
            else:
                return {}
        except Exception as e:
            print(f"[TechFallback] Stooq failed for {ticker}: {e}")
            return {}

    # Drop NaN closes first, then extract all columns in sync to prevent misalignment
    df = df.dropna(subset=["Close"])
    if len(df) < 60:
        return {}
    closes = df["Close"].tolist()
    opens = df["Open"].tolist() if "Open" in df.columns else closes
    highs = df["High"].tolist() if "High" in df.columns else closes
    lows = df["Low"].tolist() if "Low" in df.columns else closes
    volumes = df["Volume"].tolist() if "Volume" in df.columns else [0] * len(closes)

    sma10 = _entry.calc_sma(closes, 10)
    sma50 = _entry.calc_sma(closes, 50)
    sma200 = _entry.calc_sma(closes, 200) if len(closes) >= 200 else 0
    rsi2 = _entry.calc_rsi(closes, 2)
    rsi14 = _entry.calc_rsi(closes, 14)
    avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 0
    vol_spike = volumes[-1] > 1.5 * avg_vol if avg_vol > 0 else False

    regime_info = RegimeDetector.detect(closes, highs, lows, volumes)
    regime = regime_info.regime.value if hasattr(regime_info, "regime") else str(regime_info)

    # Backtest (30-day forward returns — V2.6: RSI<10 entry, next-day open, fee-adjusted)
    # Uses pre-computed arrays: O(n) instead of O(n²) — 63x faster
    _FEE_PCT = 0.30
    rsi2_arr = _rsi2_array(closes)
    sma50_arr = _sma_array(closes, 50)
    last_exit_day = -1
    trades = []
    for i in range(50, len(closes) - 32):
        if i <= last_exit_day:
            continue
        if rsi2_arr[i] < 10 and closes[i] > sma50_arr[i]:
            entry_p = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
            ret = ((closes[i + 1 + 30] - entry_p) / entry_p) * 100 - _FEE_PCT
            trades.append({"return": ret, "win": ret > 0, "rsi": rsi2_arr[i]})
            last_exit_day = i + 1 + 30

    wins_count = sum(1 for t in trades if t["win"])
    wr = wins_count / len(trades) * 100 if trades else 0
    avg_ret = sum(t["return"] for t in trades) / len(trades) if trades else 0

    # 2yr safety gate removed — primary lookback is now 5yr (1260d)
    wr_2yr = 0.0
    avg_ret_2yr = 0.0
    trades_2yr = 0

    # RSI zone (buy-signal trades only — for entry analysis)
    zone_low = min(int(rsi2 // 10) * 10, 90)  # Cap at 90 so zone 90-100 includes RSI=100
    zone_high = 101 if zone_low == 90 else zone_low + 10  # 101 to include RSI=100 exactly
    zone_trades = [t for t in trades if zone_low <= t["rsi"] < zone_high]
    zone_ret = sum(t["return"] for t in zone_trades) / len(zone_trades) if zone_trades else 0
    zone_wr = sum(1 for t in zone_trades if t["win"]) / len(zone_trades) * 100 if zone_trades else 0

    # Exit zone analysis: forward 30-day returns at CURRENT RSI zone using ALL data points
    # This answers: "When this stock was at RSI X historically, what was the 30-day forward return?"
    # V2.6: Fixed30d universal exit — consistent with entry backtests
    # Reuses pre-computed rsi2_arr from above (no recalculation)
    exit_zone_trades_list = []
    ez_last_exit = -1
    for i in range(50, len(closes) - 32):
        if i <= ez_last_exit:
            continue
        if zone_low <= rsi2_arr[i] < zone_high:
            entry_px = opens[i + 1] if opens and i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
            exit_px = closes[i + 1 + 30]
            ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT
            exit_zone_trades_list.append({"return": ret, "win": ret > 0})
            ez_last_exit = i + 1 + 30

    exit_zone_ret = sum(t["return"] for t in exit_zone_trades_list) / len(exit_zone_trades_list) if exit_zone_trades_list else 0
    exit_zone_wr = sum(1 for t in exit_zone_trades_list if t["win"]) / len(exit_zone_trades_list) * 100 if exit_zone_trades_list else 0

    # Hybrid exit strategy: backtest all strategies per-stock, pick the winner
    current_price = closes[-1]
    exit_result = _select_best_exit(ticker, closes, trades, rsi2, entry_price=entry_price, entry_date=entry_date, opens=opens)

    # Sparkline (last 20 closes)
    sparkline = [round(c, 2) for c in closes[-20:]]

    # SMA50 buffer — strongest predictor (20%+ = +9.29% avg vs 0-5% = +2.76%)
    sma50_buffer = ((closes[-1] - sma50) / sma50 * 100) if sma50 > 0 else 0

    # Tier classification (EXTREME > STRONG > STANDARD > NONE)
    above_sma50 = closes[-1] > sma50
    above_sma200 = closes[-1] > sma200 if sma200 > 0 else False
    is_extreme = rsi2 < 5 and above_sma200
    is_strong = rsi2 < 10 and above_sma50 and (rsi14 < 40 or vol_spike)
    is_standard = rsi2 < 10 and above_sma50
    tier = "EXTREME" if is_extreme else ("STRONG" if is_strong else ("STANDARD" if is_standard else "NONE"))

    return {
        "rsi2": round(rsi2, 1),
        "rsi14": round(rsi14, 1),
        "sma10": round(sma10, 2),
        "sma50": round(sma50, 2),
        "sma200": round(sma200, 2),
        "above_sma50": above_sma50,
        "sma50_buffer": round(sma50_buffer, 1),
        "above_sma200": above_sma200,
        "vol_spike": vol_spike,
        "regime": regime,
        "tier": tier,
        "win_rate": round(wr, 1),
        "bayesian_wr": _bayesian_wr(wins_count, len(trades)),
        "wilson_lower": _wilson_lower(wins_count, len(trades)),
        "trades_per_year": round(len(trades) / max(len(closes) / 252, 0.5), 1),
        "total_trades": len(trades),
        "avg_return": round(avg_ret, 2),
        "zone_return": round(zone_ret, 2),
        "zone_wr": round(zone_wr, 1),
        "zone_trades": len(zone_trades),
        "rsi_zone": f"{zone_low}-{zone_high}",
        "exit_zone_return": round(exit_zone_ret, 2),
        "exit_zone_wr": round(exit_zone_wr, 1),
        "exit_zone_trades": len(exit_zone_trades_list),
        "exit_strategy": exit_result["strategy"],
        "exit_strategy_wr": exit_result["wr"],
        "exit_strategy_ret": exit_result["avg_ret"],
        "exit_strategy_hold": exit_result["avg_hold"],
        "exit_triggered": exit_result["triggered"],
        "exit_price": exit_result["exit_price"],
        "exit_price_pct": exit_result["exit_price_pct"],
        "exit_label": exit_result["label"],
        # Walk-forward validation
        "exit_strategy_oos_wr": exit_result.get("oos_wr", 0),
        "exit_strategy_is_wr": exit_result.get("is_wr", 0),
        "exit_strategy_overfitting": exit_result.get("overfit", 0),
        "exit_strategy_validation": exit_result.get("validation", ""),
        "exit_strategy_oos_ci_lo": exit_result.get("oos_ci_lo", 0),
        "exit_strategy_oos_ci_hi": exit_result.get("oos_ci_hi", 0),
        "sparkline": sparkline,
        # 2yr safety gate (validated on 23 past trades — catches regime changes)
        "wr_2yr": round(wr_2yr, 1),
        "avg_ret_2yr": round(avg_ret_2yr, 2),
        "trades_2yr": trades_2yr,
    }


# ── Signal Computation ──

_signal_cache: Dict[str, tuple] = {}  # ticker -> (signal, issues, timestamp)
SIGNAL_CACHE_TTL = 900  # 15 min


async def _compute_signal(session: aiohttp.ClientSession, ticker: str,
                          tech: dict, live_price: float, day_chg: float) -> tuple:
    """Compute signal using ATLAS V2 rules: SMA50, regime, RSI zone, sentiment, analyst, earnings.
    Returns (signal, issues_list). Cached for 15 min to avoid API spam."""
    # Return cached signal if fresh (network checks are expensive)
    if ticker in _signal_cache:
        cached_signal, cached_issues, cached_time = _signal_cache[ticker]
        if (datetime.now() - cached_time).total_seconds() < SIGNAL_CACHE_TTL:
            # Still apply real-time checks (crash, day change) on top of cached
            rt_issues = list(cached_issues)
            if day_chg < -8 and not any("CRASH" in i for i in rt_issues):
                rt_issues.append(f"CRASH ({day_chg:.1f}% today)")
                return "SELL", rt_issues
            return cached_signal, rt_issues

    issues = []
    rsi2 = tech.get("rsi2", -1)
    above_sma50 = tech.get("above_sma50", True)
    regime = tech.get("regime", "")
    wr = tech.get("win_rate", 0)
    # Exit zone: forward 7-day returns at CURRENT RSI zone (all data, not just RSI<20 entries)
    exit_zone_ret = tech.get("exit_zone_return", 0)
    exit_zone_wr = tech.get("exit_zone_wr", 0)
    exit_zone_trades = tech.get("exit_zone_trades", 0)

    # Rule 1: SMA50 trend check
    if not above_sma50:
        issues.append("Below SMA50 - broken uptrend")

    # Rule 2: Regime check
    if regime == "BEAR":
        issues.append("BEAR regime - consider exit")

    # Rule 3: Win rate check (65% minimum per tiered WR system)
    if wr < MIN_WR:
        issues.append(f"Low WR ({wr:.1f}% < {MIN_WR}%) - below minimum")

    # Rule 3b: 2yr safety gate — catches regime changes 1yr misses
    # Validated: 2yr caught VST(-4.8%), NVDA(-4.1%), BWA(-13%) that 1yr missed
    wr_2yr = tech.get("wr_2yr", 0)
    trades_2yr = tech.get("trades_2yr", 0)
    if trades_2yr >= 5 and wr_2yr < MIN_WR and wr >= MIN_WR:
        issues.append(f"2yr WR caution ({wr_2yr:.0f}% on {trades_2yr}t) - consider half size")

    # Rule 4: Crash detection
    if day_chg < -8:
        issues.append(f"CRASH ({day_chg:.1f}% today)")

    # Network-dependent rules (5-7)
    # In production: only run these from background warmup (skip_network=False).
    # In the request path: skip them to keep the endpoint fast.
    _net_timeout = 3.0 if _is_prod else 8.0

    # Only run network rules if called from warmup (not from HTTP request)
    # The signal cache check at the top means cached signals skip all of this
    if not _is_prod:
        # Local dev: always run network rules
        _run_network = True
    else:
        # Production: only run if this is background warmup (no active HTTP request)
        # Heuristic: if there's no cached signal yet, we're in warmup
        _run_network = ticker not in _signal_cache

    if _run_network:
        # Rule 5: Earnings check (Finnhub)
        try:
            from deep_scanner import DeepScanner
            ds = DeepScanner()
            earnings = await asyncio.wait_for(ds._check_earnings(session, ticker), timeout=_net_timeout)
            if earnings:
                issues.append(f"Earnings on {earnings['date']} (<7 days)")
        except (asyncio.TimeoutError, Exception):
            pass

        # Rule 6: Sentiment check (Google News + VADER)
        try:
            from sentiment import SentimentEngine
            se = SentimentEngine()
            sdata = await asyncio.wait_for(se.get_ticker_sentiment(ticker), timeout=_net_timeout)
            if sdata and sdata.get("sentiment_score", 0) < -0.3:
                issues.append(f"Negative sentiment ({sdata['sentiment_score']:.2f})")
        except (asyncio.TimeoutError, Exception):
            pass

        # Rule 7: Analyst overvaluation check
        try:
            from analyst_data import AnalystDataFetcher
            af = AnalystDataFetcher()
            adata = await asyncio.wait_for(af.fetch_analyst_data(ticker), timeout=_net_timeout)
            if adata and adata.get("price_target_avg", 0) > 0:
                target = adata["price_target_avg"]
                if live_price > target:
                    issues.append(f"Overvalued (${live_price:.0f} > target ${target:.0f})")
        except (asyncio.TimeoutError, Exception):
            pass

    # Rule 8: RSI zone expected return analysis (CRITICAL for exit decisions)
    # "When this stock was at this RSI zone historically, what was the 7-day forward return?"
    if exit_zone_trades >= 5:
        if exit_zone_ret < 1.0 and exit_zone_wr < MIN_WR:
            issues.append(f"Weak zone return (+{exit_zone_ret:.1f}%, {exit_zone_wr:.0f}% WR at RSI {int(rsi2)})")
        elif exit_zone_ret < 2.0:
            issues.append(f"Moderate zone return (+{exit_zone_ret:.1f}% at RSI {int(rsi2)})")

    # Hybrid exit strategy check
    exit_triggered = tech.get("exit_triggered", False)
    exit_strategy = tech.get("exit_strategy", "")
    if exit_triggered:
        issues.append(f"Exit triggered ({exit_strategy}: {tech.get('exit_label', '')})")

    # Determine signal from issues + hybrid exit strategy
    critical = [i for i in issues if any(k in i for k in ["Below SMA50", "BEAR regime", "CRASH", "Low WR"])]

    if any("CRASH" in i for i in critical):
        signal = "SELL"
    elif any("Below SMA50" in i for i in critical) and any("BEAR" in i for i in critical):
        signal = "SELL"
    elif any("Below SMA50" in i for i in critical):
        signal = "CAUTION"
    elif len(critical) > 0:
        signal = "CAUTION"
    elif exit_triggered:
        # Check if RSI re-entered oversold — fresh entry signal overrides exit
        # Selling + re-buying at same price wastes $3 in fees for nothing
        exit_strat_ret = tech.get("exit_strategy_ret", 0)
        zone_ret = tech.get("zone_return", 0)
        zone_wr = tech.get("zone_wr", 0)
        zone_trades = tech.get("zone_trades", 0)
        if rsi2 < 10 and zone_trades >= 5 and zone_ret > exit_strat_ret:
            signal = "HOLD"
            issues.append(f"Exit suppressed: RSI oversold ({rsi2:.0f}), zone +{zone_ret:.1f}% > exit +{exit_strat_ret:.1f}%")
        else:
            signal = "EXIT"
    elif rsi2 < 10 and above_sma50 and regime != "BEAR":
        # 2yr safety gate: if 1yr says BUY but 2yr WR fails, downgrade to CAUTION
        # Validated: avoids losses like VST(-4.8%), NVDA(-4.1%), BWA(-13%)
        if trades_2yr >= 5 and wr_2yr < MIN_WR:
            signal = "CAUTION"
            issues.append(f"BUY downgraded: 2yr WR {wr_2yr:.0f}% < {MIN_WR}% (half size)")
        else:
            signal = "BUY"
    else:
        signal = "HOLD"

    _signal_cache[ticker] = (signal, issues, datetime.now())
    return signal, issues


# ── Portfolio Endpoint ──

@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio():
    """Get portfolio with live prices, technicals, signals, and P&L."""
    positions = _position_mgr._get_open_positions_sync("USD")

    if not positions:
        return PortfolioResponse(
            summary=PortfolioSummary(
                total_value=0, total_cost=0, total_pnl=0, total_pnl_pct=0,
                position_count=0, avg_win_rate=0, timestamp=datetime.now().isoformat(),
            ),
            positions=[],
        )

    # Use cached prices (SQLite-seeded or Finnhub-refreshed) — NEVER block on API calls.
    # Background quote_refresh_loop() keeps prices fresh every 60s.
    details = []
    for pos in positions:
        ticker = pos["ticker"]
        shares = pos["shares"]
        entry_price = pos["entry_price"]
        cost = entry_price * shares

        # Price priority: _price_cache (live/SQLite) > SQLite last close > entry_price
        quote = _price_cache.get(ticker)
        if not quote:
            # Fallback: read last close from SQLite cache (instant, no API)
            df = _cache.get(ticker, 365)
            if df is not None and len(df) >= 2:
                close = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                quote = {
                    "price": close, "prev_close": prev,
                    "day_chg": round(((close - prev) / prev) * 100, 2) if prev > 0 else 0,
                }
                _price_cache[ticker] = quote
                _quote_cache[ticker] = (quote, datetime.now())
        live_price = quote["price"] if quote else entry_price
        day_chg = quote.get("day_chg", 0) if quote else 0
        value = live_price * shares
        pnl = value - cost
        pnl_pct = (pnl / cost * 100) if cost else 0

        # Read technicals from background-computed cache — NEVER block event loop
        pos_entry_date = pos.get("entry_date", "")
        tech = _technicals_cache.get(ticker)

        # Re-evaluate exit trigger with current price
        if tech and tech.get("exit_strategy"):
            df = _cache.get(ticker, 365)
            if df is not None and len(df) >= 10:
                closes_live = df["Close"].dropna().tolist()
                rsi_live = tech.get("rsi2", -1)
                # Use exit strategy cache if available; fallback to technicals cache
                exit_cached = _exit_strategy_cache.get(ticker)
                if not exit_cached and tech.get("exit_strategy"):
                    exit_cached = {"strategy": tech["exit_strategy"]}
                if not exit_cached:
                    exit_cached = {"strategy": ""}
                live_exit = _evaluate_exit_trigger(
                    exit_cached,
                    closes_live, rsi_live, live_price, entry_price,
                    entry_date=pos_entry_date
                )
                old_triggered = tech.get("exit_triggered", False)
                tech["exit_triggered"] = live_exit["triggered"]
                tech["exit_momentum_override"] = live_exit.get("momentum_override", False)
                tech["exit_price"] = live_exit["exit_price"]
                tech["exit_price_pct"] = live_exit["exit_price_pct"]
                tech["exit_label"] = live_exit["label"]
                if live_exit["triggered"] != old_triggered and ticker in _signal_cache:
                    del _signal_cache[ticker]

        # PORTFOLIO POSITIONS: Use exit-focused signals only (EXIT or HOLD).
        # Don't use _signal_cache — it has entry-focused signals (BUY/CAUTION/OVERBOUGHT)
        # from warmup which are WRONG for existing positions. See lesson #11/#25.
        signal = "HOLD"
        issues = []
        rsi2 = tech.get("rsi2", 50) if tech else 50
        sma50_val = tech.get("sma50", 0) if tech else 0
        above_sma50 = live_price > sma50_val if sma50_val > 0 else True
        exit_triggered = tech.get("exit_triggered", False) if tech else False
        ez_wr = tech.get("exit_zone_wr", 0) if tech else 0
        ez_ret = tech.get("exit_zone_return", 0) if tech else 0
        ez_trades = tech.get("exit_zone_trades", 0) if tech else 0
        atlas_wr = tech.get("win_rate", 0) if tech else 0
        atlas_trades = tech.get("total_trades", 0) if tech else 0
        if exit_triggered:
            signal = "EXIT"
            issues.append(f"Exit triggered ({tech.get('exit_strategy', '')}: {tech.get('exit_label', '')})")
        elif ez_trades >= 10 and ez_ret < 0 and atlas_wr < 65:
            signal = "EXIT"
            issues.append(f"Negative zone return ({ez_ret:+.1f}%, {ez_wr:.0f}% WR) + ATLAS {atlas_wr:.0f}% WR")
        elif ez_trades >= 10 and ez_wr < 65 and (atlas_trades < 10 or atlas_wr < 65):
            signal = "EXIT"
            issues.append(f"Zone WR {ez_wr:.0f}% + ATLAS WR {atlas_wr:.0f}% — both fail 65% VETO")
        else:
            # Existing positions: HOLD. Note issues but DON'T change signal.
            if not above_sma50:
                issues.append("Below SMA50")
            if rsi2 > 80:
                issues.append("Overbought (RSI > 80) — trade working")
            if atlas_trades > 0 and atlas_trades < 6:
                issues.append(f"Low sample ({atlas_trades} trades) — WR {atlas_wr:.0f}% may be unreliable")
        # Crash warning — note but DON'T override signal for existing positions.
        # Crash filter is for NEW entries (veto buying). For holdings, trust exit strategy.
        # See lesson #28: during broad crashes, selling on panic = emotional trading.
        if day_chg < -8 and not any("CRASH" in i for i in issues):
            issues.append(f"CRASH ({day_chg:.1f}% today) — exit strategy still active")

        # Days held calculation (trading days to match backtest bars)
        days_held = 0
        try:
            from datetime import date as _date
            entry_d = _date.fromisoformat(pos.get("entry_date", ""))
            today_d = _date.today()
            days_held = sum(
                1 for n in range((today_d - entry_d).days)
                if (entry_d + timedelta(days=n + 1)).weekday() < 5
            )
        except Exception:
            pass

        # Exit strategy target days — only for fixed-period exits (they have a real target)
        # RSI/SMA/trailing exits have no fixed target — showing avg hold as "target" is misleading
        exit_strat_name = tech.get("exit_strategy", "") if tech else ""
        exit_target_days = 0
        if exit_strat_name:
            strat_def = _EXIT_STRATEGIES.get(exit_strat_name, {})
            if strat_def.get("type") == "fixed":
                exit_target_days = strat_def.get("days", 0)

        # Exit targets based on regime
        regime = tech.get("regime", "BULL") if tech else "BULL"
        stop_pct, t1_pct, t2_pct = _exit_targets_by_regime(regime)
        stop_price = round(entry_price * (1 + stop_pct / 100), 2)
        target_1 = round(entry_price * (1 + t1_pct / 100), 2)
        target_2 = round(entry_price * (1 + t2_pct / 100), 2)

        detail = PositionDetail(
            id=pos["id"],
            ticker=ticker,
            shares=shares,
            entry_price=entry_price,
            entry_date=pos["entry_date"],
            current_price=round(live_price, 2),
            day_change_pct=round(day_chg, 2),
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 2),
            cost_basis=round(cost, 2),
            current_value=round(value, 2),
            rsi2=tech.get("rsi2", -1) if tech else -1,
            rsi14=tech.get("rsi14", -1) if tech else -1,
            sma10=tech.get("sma10", 0) if tech else 0,
            sma50=tech.get("sma50", 0) if tech else 0,
            above_sma50=live_price > tech.get("sma50", 0) if tech and tech.get("sma50", 0) > 0 else True,
            sma50_buffer=round((live_price - tech["sma50"]) / tech["sma50"] * 100, 1) if tech and tech.get("sma50", 0) > 0 else 0,
            above_sma10=live_price > tech.get("sma10", 0) if tech and tech.get("sma10", 0) > 0 else False,
            regime=regime,
            tier="NONE" if (tech and tech.get("exit_triggered", False)) else (tech.get("tier", "NONE") if tech else "NONE"),
            win_rate=tech.get("win_rate", 0) if tech else 0,
            bayesian_wr=tech.get("bayesian_wr", tech.get("win_rate", 0)) if tech else 0,
            wilson_lower=tech.get("wilson_lower", 0) if tech else 0,
            trades_per_year=tech.get("trades_per_year", 0) if tech else 0,
            total_trades=tech.get("total_trades", 0) if tech else 0,
            avg_return=tech.get("avg_return", 0) if tech else 0,
            zone_return=tech.get("zone_return", 0) if tech else 0,
            zone_wr=tech.get("zone_wr", 0) if tech else 0,
            zone_trades=tech.get("zone_trades", 0) if tech else 0,
            rsi_zone=tech.get("rsi_zone", "") if tech else "",
            days_held=days_held,
            exit_zone_return=tech.get("exit_zone_return", 0) if tech else 0,
            exit_zone_wr=tech.get("exit_zone_wr", 0) if tech else 0,
            exit_zone_trades=tech.get("exit_zone_trades", 0) if tech else 0,
            exit_strategy=exit_strat_name,
            exit_strategy_wr=tech.get("exit_strategy_wr", 0) if tech else 0,
            exit_strategy_ret=tech.get("exit_strategy_ret", 0) if tech else 0,
            exit_strategy_hold=tech.get("exit_strategy_hold", 0) if tech else 0,
            exit_strategy_target_days=exit_target_days,
            exit_triggered=tech.get("exit_triggered", False) if tech else False,
            exit_momentum_override=tech.get("exit_momentum_override", False) if tech else False,
            exit_price=tech.get("exit_price", 0) if tech else 0,
            exit_price_pct=tech.get("exit_price_pct", 0) if tech else 0,
            exit_label=tech.get("exit_label", "") if tech else "",
            # Walk-forward validation
            exit_strategy_oos_wr=tech.get("exit_strategy_oos_wr", 0) if tech else 0,
            exit_strategy_is_wr=tech.get("exit_strategy_is_wr", 0) if tech else 0,
            exit_strategy_overfitting=tech.get("exit_strategy_overfitting", 0) if tech else 0,
            exit_strategy_validation=tech.get("exit_strategy_validation", "") if tech else "",
            exit_strategy_oos_ci_lo=tech.get("exit_strategy_oos_ci_lo", 0) if tech else 0,
            exit_strategy_oos_ci_hi=tech.get("exit_strategy_oos_ci_hi", 0) if tech else 0,
            sparkline=tech.get("sparkline", []) if tech else [],
            # 2yr safety gate
            wr_2yr=tech.get("wr_2yr", 0) if tech else 0,
            avg_ret_2yr=tech.get("avg_ret_2yr", 0) if tech else 0,
            trades_2yr=tech.get("trades_2yr", 0) if tech else 0,
            signal=signal,
            issues=issues,
            stop_loss=stop_price,
            target_1=target_1,
            target_2=target_2,
            stop_pct=stop_pct,
            target_1_pct=t1_pct,
            target_2_pct=t2_pct,
        )

        # Extended hours data (pre-market / after-hours)
        ext = _extended_hours_cache.get(ticker)
        if ext:
            detail.ext_price = ext["ext_price"]
            detail.ext_change_pct = ext["ext_change_pct"]
            detail.market_session = ext["session"]
        else:
            detail.market_session = _get_market_session()

        details.append(detail)

    # Calculate weights
    total_value = sum(d.current_value for d in details)
    for d in details:
        d.weight = round(d.current_value / total_value * 100, 1) if total_value else 0

    total_cost = sum(d.cost_basis for d in details)
    total_pnl = total_value - total_cost
    wr_list = [d.win_rate for d in details if d.win_rate > 0]

    # Daily P&L: sum of each position's day change in dollars
    day_pnl = sum(
        d.current_value * d.day_change_pct / (100 + d.day_change_pct) if d.day_change_pct != -100 else 0
        for d in details
    )
    day_pnl_pct = (day_pnl / total_value * 100) if total_value > 0 else 0

    # Realized P&L from closed positions
    tx_summary = _position_mgr.get_transaction_summary()

    # Broker tax/fees paid outside per-trade commissions
    BROKER_TAX_FEES = 222.00
    _total_deposited = 11891.58
    _total_fees_all = round(tx_summary.get("total_fees", 0) + BROKER_TAX_FEES, 2)

    # Cash = deposits + realized P&L - fees - cost of open positions
    _realized = tx_summary.get("total_realized_pnl", 0)
    _cash = round(_total_deposited + _realized - _total_fees_all - total_cost, 2)
    if _cash < 0:
        _cash = 0  # Shouldn't go negative — rounding protection

    summary = PortfolioSummary(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl / total_cost * 100, 2) if total_cost else 0,
        day_pnl=round(day_pnl, 2),
        day_pnl_pct=round(day_pnl_pct, 2),
        realized_pnl=round(_realized, 2),
        total_fees=_total_fees_all,
        total_deposited=_total_deposited,
        position_count=len(details),
        avg_win_rate=round(sum(wr_list) / len(wr_list), 1) if wr_list else 0,
        cash=_cash,
        market_session=_get_market_session(),
        timestamp=datetime.now().isoformat(),
    )

    return PortfolioResponse(summary=summary, positions=details)


# ── ILS Portfolio Endpoint ──

_ils_quote_cache: Dict[str, dict] = {}  # ticker -> {price, day_chg, ts}

async def _fetch_yahoo_quote(session: aiohttp.ClientSession, ticker: str) -> Optional[dict]:
    """Fetch live quote from Yahoo Finance for .TA tickers."""
    cached = _ils_quote_cache.get(ticker)
    if cached and (datetime.now() - cached["ts"]).total_seconds() < 60:
        return cached

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": "1d", "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status != 200:
                return cached
            data = await resp.json()
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", 0)
            prev = meta.get("chartPreviousClose", price)
            day_chg = ((price - prev) / prev * 100) if prev > 0 else 0
            result = {"price": price, "day_chg": round(day_chg, 2), "ts": datetime.now()}
            _ils_quote_cache[ticker] = result
            return result
    except Exception:
        return cached


async def _fetch_yahoo_history(session: aiohttp.ClientSession, ticker: str) -> Optional[list]:
    """Fetch 1-year daily closes from Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": "1y", "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [c for c in closes if c is not None]
    except Exception:
        return None


def _get_ils_technicals(ticker: str, closes: list) -> dict:
    """Run same technical analysis as USD but for ILS stocks. Prices in Agorot."""
    if len(closes) < 60:
        return {}

    rsi2 = _entry.calc_rsi(closes, 2)
    rsi14 = _entry.calc_rsi(closes, 14)
    sma10 = _entry.calc_sma(closes, 10)
    sma50 = _entry.calc_sma(closes, 50)
    sma200 = _entry.calc_sma(closes, 200) if len(closes) >= 200 else 0
    above_sma50 = closes[-1] > sma50
    sma50_buffer = ((closes[-1] - sma50) / sma50 * 100) if sma50 > 0 else 0

    # Backtest (30-day forward, V2.6: RSI<10, fee-adjusted)
    # Note: ILS Yahoo data has no Open column — use closes as entry proxy
    _FEE_PCT = 0.30
    last_exit_day = -1
    trades = []
    for i in range(50, len(closes) - 32):
        if i <= last_exit_day:
            continue
        hist = closes[:i + 1]
        h_rsi = _entry.calc_rsi(hist, 2)
        h_sma = _entry.calc_sma(hist, 50)
        if h_rsi < 10 and hist[-1] > h_sma:
            entry_px = closes[i]  # ILS data has no opens — use close as proxy
            exit_px = closes[i + 1 + 30]
            ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT
            trades.append({"return": ret, "win": ret > 0, "rsi": h_rsi})
            last_exit_day = i + 1 + 30

    wr = sum(1 for t in trades if t["win"]) / len(trades) * 100 if trades else 0
    avg_ret = sum(t["return"] for t in trades) / len(trades) if trades else 0

    # Zone analysis
    zone_lo = min(int(rsi2 // 10) * 10, 90)
    zone_hi = 101 if zone_lo == 90 else zone_lo + 10
    zt = [t for t in trades if zone_lo <= t["rsi"] < zone_hi]
    zone_ret = sum(t["return"] for t in zt) / len(zt) if zt else 0
    zone_wr = sum(1 for t in zt if t["win"]) / len(zt) * 100 if zt else 0

    # Exit zone analysis (all RSI values, fee-adjusted, V2.6: 30-day hold)
    exit_zt = []
    for i in range(50, len(closes) - 32):
        hist = closes[:i + 1]
        h_rsi = _entry.calc_rsi(hist, 2)
        if zone_lo <= h_rsi < zone_hi:
            ret = ((closes[i + 1 + 30] - closes[i]) / closes[i]) * 100 - _FEE_PCT
            exit_zt.append({"return": ret, "win": ret > 0})
    exit_zone_ret = sum(t["return"] for t in exit_zt) / len(exit_zt) if exit_zt else 0
    exit_zone_wr = sum(1 for t in exit_zt if t["win"]) / len(exit_zt) * 100 if exit_zt else 0

    # Regime detection
    try:
        from atlas_v2.regime import RegimeDetector
        regime_info = RegimeDetector.detect(closes, closes, closes, [0] * len(closes))
        regime = regime_info.regime.value if hasattr(regime_info, "regime") else str(regime_info)
    except Exception:
        regime = "UNKNOWN"

    # Tier
    above_sma200 = closes[-1] > sma200 if sma200 > 0 else False
    is_extreme = rsi2 < 5 and above_sma200
    is_strong = rsi2 < 10 and above_sma50
    tier = "EXTREME" if is_extreme else ("STRONG" if is_strong else ("STANDARD" if rsi2 < 10 and above_sma50 else "NONE"))

    # Signal
    signal = "HOLD"
    issues = []
    if not above_sma50:
        signal = "CAUTION"
        issues.append("Below SMA50")
    elif rsi2 < 10 and above_sma50 and wr >= MIN_WR:
        signal = "BUY"
    elif rsi2 > 80:
        signal = "OVERBOUGHT"

    sparkline = [round(c, 2) for c in closes[-20:]]

    return {
        "rsi2": round(rsi2, 1), "rsi14": round(rsi14, 1),
        "sma10": round(sma10, 2), "sma50": round(sma50, 2), "sma200": round(sma200, 2),
        "above_sma50": above_sma50, "sma50_buffer": round(sma50_buffer, 1),
        "regime": regime, "tier": tier,
        "win_rate": round(wr, 1), "total_trades": len(trades),
        "avg_return": round(avg_ret, 2),
        "zone_return": round(zone_ret, 2), "zone_wr": round(zone_wr, 1),
        "zone_trades": len(zt), "rsi_zone": f"{zone_lo}-{zone_hi}",
        "exit_zone_return": round(exit_zone_ret, 2),
        "exit_zone_wr": round(exit_zone_wr, 1), "exit_zone_trades": len(exit_zt),
        "exit_strategy": "Fixed30d", "exit_strategy_wr": round(wr, 1),
        "exit_strategy_ret": round(avg_ret, 2), "exit_strategy_hold": 30.0,
        "exit_triggered": False, "exit_price": 0, "exit_price_pct": 0,
        "exit_label": f"Hold 30d | +{avg_ret:.1f}% WR {wr:.0f}%",
        "signal": signal, "issues": issues,
        "sparkline": sparkline,
    }


@router.get("/portfolio/ils")
async def get_ils_portfolio():
    """Get ILS portfolio with full technicals (same model as USD)."""
    positions = _position_mgr._get_open_positions_sync("ILS")
    if not positions:
        return {
            "summary": {
                "total_value": 0, "total_cost": 0, "total_pnl": 0, "total_pnl_pct": 0,
                "day_pnl": 0, "day_pnl_pct": 0, "position_count": 0, "avg_win_rate": 0,
                "cash": 0, "currency": "ILS", "timestamp": datetime.now().isoformat(),
            },
            "positions": [],
        }

    details = []
    total_value = 0
    total_cost = 0
    day_pnl_total = 0
    win_rates = []

    async with aiohttp.ClientSession() as session:
        for pos in positions:
            ticker = pos["ticker"]
            shares = pos["shares"]
            entry_price = pos["entry_price"]
            if shares <= 0:
                continue

            # Fetch live quote + history in parallel
            quote_task = _fetch_yahoo_quote(session, ticker)
            hist_task = _fetch_yahoo_history(session, ticker)
            quote, hist = await asyncio.gather(quote_task, hist_task)

            live_price = quote["price"] if quote else entry_price
            day_chg = quote["day_chg"] if quote else 0

            # Run technicals if we have history
            tech = _get_ils_technicals(ticker, hist) if hist and len(hist) > 60 else {}

            cost = entry_price * shares
            value = live_price * shares
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost > 0 else 0

            total_value += value
            total_cost += cost
            day_pnl_total += value * day_chg / 100

            if tech.get("win_rate", 0) > 0:
                win_rates.append(tech["win_rate"])

            # Convert Agorot prices to ILS for display
            price_ils = live_price / 100
            entry_ils = entry_price / 100
            sma50_ils = tech.get("sma50", 0) / 100

            details.append({
                "id": pos["id"],
                "ticker": ticker,
                "shares": shares,
                "entry_price": round(entry_ils, 2),
                "entry_date": pos.get("entry_date", ""),
                "current_price": round(price_ils, 2),
                "day_change_pct": day_chg,
                "pnl": round(pnl / 100, 2),  # ILS
                "pnl_pct": round(pnl_pct, 2),
                "cost_basis": round(cost / 100, 2),
                "current_value": round(value / 100, 2),
                "weight": 0,  # filled below
                "currency": "ILS",
                # Technicals
                "rsi2": tech.get("rsi2", -1),
                "rsi14": tech.get("rsi14", -1),
                "sma10": round(tech.get("sma10", 0) / 100, 2) if tech.get("sma10", 0) > 0 else 0,
                "sma50": round(sma50_ils, 2),
                "above_sma50": tech.get("above_sma50", True),
                "above_sma10": live_price > tech.get("sma10", 0) if tech.get("sma10", 0) > 0 else False,
                "sma50_buffer": tech.get("sma50_buffer", 0),
                "regime": tech.get("regime", ""),
                "tier": tech.get("tier", "NONE"),
                "win_rate": tech.get("win_rate", 0),
                "total_trades": tech.get("total_trades", 0),
                "avg_return": tech.get("avg_return", 0),
                "zone_return": tech.get("zone_return", 0),
                "zone_wr": tech.get("zone_wr", 0),
                "zone_trades": tech.get("zone_trades", 0),
                "rsi_zone": tech.get("rsi_zone", ""),
                "exit_zone_return": tech.get("exit_zone_return", 0),
                "exit_zone_wr": tech.get("exit_zone_wr", 0),
                "exit_zone_trades": tech.get("exit_zone_trades", 0),
                "exit_strategy": tech.get("exit_strategy", ""),
                "exit_strategy_wr": tech.get("exit_strategy_wr", 0),
                "exit_strategy_ret": tech.get("exit_strategy_ret", 0),
                "exit_strategy_hold": tech.get("exit_strategy_hold", 14),
                "exit_triggered": tech.get("exit_triggered", False),
                "exit_price": 0,
                "exit_price_pct": 0,
                "exit_label": tech.get("exit_label", ""),
                # Walk-forward validation (not available for ILS yet)
                "exit_strategy_oos_wr": 0,
                "exit_strategy_is_wr": 0,
                "exit_strategy_overfitting": 0,
                "exit_strategy_validation": "",
                "exit_strategy_oos_ci_lo": 0,
                "exit_strategy_oos_ci_hi": 0,
                "signal": tech.get("signal", "HOLD"),
                "issues": tech.get("issues", []),
                "sparkline": [round(v / 100, 2) for v in tech.get("sparkline", [])],
                "stop_loss": round(price_ils * 0.92, 2), "target_1": round(price_ils * 1.10, 2), "target_2": round(price_ils * 1.20, 2),
                "stop_pct": -8.0, "target_1_pct": 10.0, "target_2_pct": 20.0,
            })

    # Calculate weights
    for d in details:
        d["weight"] = round(d["current_value"] / (total_value / 100) * 100, 1) if total_value > 0 else 0

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

    return {
        "summary": {
            "total_value": round(total_value / 100, 2),
            "total_cost": round(total_cost / 100, 2),
            "total_pnl": round(total_pnl / 100, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "day_pnl": round(day_pnl_total / 100, 2),
            "day_pnl_pct": round(day_pnl_total / total_value * 100, 2) if total_value > 0 else 0,
            "position_count": len(details),
            "avg_win_rate": round(sum(win_rates) / len(win_rates), 1) if win_rates else 0,
            "cash": 0,
            "currency": "ILS",
            "timestamp": datetime.now().isoformat(),
        },
        "positions": details,
    }


# ── Health Check Endpoint ──

@router.get("/portfolio/health")
async def get_health():
    """Get cached health check results (updated by background monitor)."""
    global _health_cache, _health_cache_time

    if _health_cache:
        return {**_health_cache, "last_check": _health_cache_time.isoformat() if _health_cache_time else ""}

    # No cache yet - run now
    result = await _run_health_check()
    return {**result, "last_check": datetime.now().isoformat()}


@router.post("/portfolio/health/refresh")
async def refresh_health():
    """Force a fresh health check."""
    result = await _run_health_check()
    return {**result, "last_check": datetime.now().isoformat()}


async def _run_health_check() -> Dict:
    """Run full portfolio health check using portfolio_check.py logic."""
    global _health_cache, _health_cache_time

    positions = _position_mgr._get_open_positions_sync()
    if not positions:
        empty = {"timestamp": datetime.now().isoformat(), "portfolio_value": 0,
                 "portfolio_pnl": 0, "portfolio_pnl_pct": 0, "holdings": 0,
                 "alerts_count": 0, "has_critical": False, "alerts": [], "positions": []}
        _health_cache = empty
        _health_cache_time = datetime.now()
        return empty

    holdings = [
        {"ticker": p["ticker"], "shares": p["shares"], "entry": p["entry_price"]}
        for p in positions
    ]

    try:
        from portfolio_check import check_portfolio, results_to_json
        results = await check_portfolio(holdings)
        data = results_to_json(results)
        _health_cache = data
        _health_cache_time = datetime.now()
        return data
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


# ── Scanner Endpoint ──

_scan_running = False


@router.get("/scan/opportunities")
async def get_opportunities():
    """Get scanner results. Returns cache immediately; triggers background scan if empty."""
    global _scan_cache, _scan_cache_time, _scan_running

    # Try loading from today's on-disk cache if in-memory cache is empty
    if not _scan_cache:
        _try_load_scan_cache()

    if _scan_cache:
        # Overlay LIVE prices + recalculate RSI(2) — never show stale entry signals
        result = {**_scan_cache, "last_scan": _scan_cache_time.isoformat() if _scan_cache_time else ""}
        # Add market regime gate
        result["market_regime"] = _check_market_regime()
        opps = result.get("opportunities", [])

        # Fetch live quotes for top candidates — needed for crash detection + accurate RSI
        # Priority: highest composite score first (most likely to be shown to user)
        tickers_need_quote = []
        sorted_opps = sorted(opps, key=lambda o: o.get("composite_score", 0), reverse=True)
        for opp in sorted_opps:
            t = opp.get("ticker", "")
            if t and t not in _price_cache and not opp.get("vetoed", False):
                tickers_need_quote.append(t)
        if tickers_need_quote:
            try:
                async with aiohttp.ClientSession() as session:
                    for t in tickers_need_quote[:50]:  # Top 50 by score (was 15)
                        if not _check_finnhub_rate():
                            break
                        await _get_finnhub_quote(session, t)
                        await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[Scan] Live quote fetch error: {e}")

        # Now overlay live prices and recalculate RSI(2) with today's price
        for opp in opps:
          try:
            ticker = opp.get("ticker", "")
            live = _price_cache.get(ticker)
            scan_price = opp.get("price", 0)  # original scan price
            if live and live.get("price", 0) > 0:
                opp["price"] = round(live["price"], 2)
            # Recalculate RSI(2) with live price appended
            df = _cache.get(ticker, 365)
            if df is not None and len(df) >= 50:
                if not (live and live.get("price", 0) > 0):
                    opp["price"] = round(float(df["Close"].iloc[-1]), 2)
                closes = df["Close"].dropna().tolist()
                live_px = opp.get("price", 0)
                if live_px > 0 and abs(live_px - closes[-1]) / closes[-1] > 0.001:
                    closes = closes + [live_px]
                rsi2 = _entry.calc_rsi(closes, 2)
                opp["rsi2"] = round(rsi2, 1)
                # Update live technicals for ranking (no longer vetoing — ranking factors)
                if len(closes) >= 50:
                    sma50 = sum(closes[-50:]) / 50
                    live_px = opp.get("price", 0)
                    if live_px > 0 and sma50 > 0:
                        opp["sma50_buffer"] = round((live_px - sma50) / sma50 * 100, 1)
                # Update live ATR (use df arrays, not closes which may have appended live price)
                df_closes = df["Close"].dropna().tolist()
                if len(df_closes) >= 15:
                    highs_list = df["High"].dropna().tolist() if "High" in df.columns else df_closes
                    lows_list = df["Low"].dropna().tolist() if "Low" in df.columns else df_closes
                    min_len = min(len(df_closes), len(highs_list), len(lows_list))
                    atr_vals = []
                    for j in range(max(1, min_len - 14), min_len):
                        tr = max(highs_list[j] - lows_list[j],
                                 abs(highs_list[j] - df_closes[j - 1]),
                                 abs(lows_list[j] - df_closes[j - 1]))
                        atr_vals.append(tr)
                    if atr_vals and df_closes[-1] > 0:
                        opp["atr_pct"] = round(sum(atr_vals) / len(atr_vals) / df_closes[-1] * 100, 2)
                # Recalculate composite score + strict flag with live data
                opp["composite_score"], opp["ranking_factors"] = _compute_composite_score(opp)
                opp["quality_tier"] = _quality_tier(opp["composite_score"])
                opp["meets_strict"] = _meets_strict_criteria(opp)
                # Only veto if below SMA50 (not in uptrend) or penny stock
                if not opp.get("vetoed", False) and len(closes) >= 50:
                    sma50 = sum(closes[-50:]) / 50
                    live_px = opp.get("price", 0)
                    if live_px > 0 and live_px < sma50:
                        opp["vetoed"] = True
                        opp["veto_reason"] = f"Below SMA50 (${live_px:.0f} < ${sma50:.0f})"
                        opp["is_upgrade"] = False
                        opp["beats_holdings"] = []
            # Crash filter: veto if stock dropped > 8% today (wait for stabilization)
            if not opp.get("vetoed", False) and len(closes) >= 2:
                prev_close = closes[-2] if len(closes) > 1 else closes[-1]
                live_px = opp.get("price", 0)
                if prev_close > 0 and live_px > 0:
                    day_chg_pct = (live_px / prev_close - 1) * 100
                    if day_chg_pct < -8:
                        opp["vetoed"] = True
                        opp["veto_reason"] = f"Crash ({day_chg_pct:.1f}% today)"
                        opp["is_upgrade"] = False
                        opp["beats_holdings"] = []
            # Re-check price minimum with live price ($10 V2.6)
            if not opp.get("vetoed", False):
                live_px = opp.get("price", 0)
                if 0 < live_px < 10:
                    opp["vetoed"] = True
                    opp["veto_reason"] = f"Price too low (${live_px:.2f} < $10)"
                    opp["is_upgrade"] = False
                    opp["beats_holdings"] = []
          except Exception as e:
            print(f"[Scan] Live overlay error for {opp.get('ticker', '?')}: {e}")
        return result

    # No cache yet — trigger background scan, return empty placeholder
    if not _scan_running:
        _scan_running = True
        asyncio.create_task(_background_scan())

    return {
        "timestamp": datetime.now().isoformat(),
        "total_scanned": 0, "passed": 0, "ranked_count": 0,
        "opportunities": [], "holdings_scores": [],
        "worst_holding": "", "worst_score": 0,
        "last_scan": "", "scanning": True,
    }


def _check_market_regime() -> dict:
    """Check if broad market supports mean reversion entries.
    Returns regime info including whether to pause new entries."""
    try:
        spy_df = _cache.get("SPY", 30)
        if spy_df is None or len(spy_df) < 10:
            return {"regime": "UNKNOWN", "pause_entries": False, "reason": "No SPY data"}
        closes = spy_df["Close"].dropna().tolist()
        if len(closes) < 6:
            return {"regime": "UNKNOWN", "pause_entries": False, "reason": "Insufficient SPY data"}
        # 5-day rolling return
        ret_5d = ((closes[-1] - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 else 0
        # SMA50 check
        sma50 = sum(closes[-min(50, len(closes)):]) / min(50, len(closes))
        below_sma50 = closes[-1] < sma50
        # Pause if SPY 5d return < -1% (sustained decline)
        pause = ret_5d < -1.0
        regime = "DECLINING" if ret_5d < -1 else ("WEAK" if ret_5d < 0 else "HEALTHY")
        return {
            "regime": regime,
            "spy_5d_return": round(ret_5d, 2),
            "spy_below_sma50": below_sma50,
            "pause_entries": pause,
            "reason": f"SPY 5d: {ret_5d:+.1f}%" + (" — MEAN REVERSION SUSPENDED" if pause else ""),
        }
    except Exception as e:
        return {"regime": "UNKNOWN", "pause_entries": False, "reason": str(e)}


def _try_load_scan_cache():
    """Load today's scan results from on-disk cache file if available.
    Only loads fully-validated stocks (have analyst + sentiment data)."""
    global _scan_cache, _scan_cache_time
    today = datetime.now().strftime('%Y-%m-%d')
    cache_path = os.path.join(os.path.dirname(__file__), "data", f"scan_{today}.json")
    if not os.path.exists(cache_path):
        return
    try:
        with open(cache_path) as f:
            raw = json.load(f)
        if not isinstance(raw, list) or not raw:
            return

        holdings_scores, worst_ticker, worst_score = _get_holdings_scores()

        # Include ALL Phase 2 passers — Phase 3 validation handled in _dict_to_opportunity
        opportunities = []
        for r in raw:
            opp = _dict_to_opportunity(r, holdings_scores)
            opportunities.append(opp)
        opportunities.sort(key=lambda x: (x.is_upgrade, x.score), reverse=True)

        # total_scanned = actual stocks in cache, NOT just Phase 2 passers
        total_in_cache = _cache.stats().get("total_tickers", len(raw))
        result = _build_scan_result(opportunities, total_in_cache,
                                    holdings_scores, worst_ticker, worst_score)
        _scan_cache = result
        _scan_cache_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        print(f"[Scan] Loaded {len(raw)} stocks from {cache_path} (universe: {total_in_cache})")
    except Exception as e:
        print(f"[Scan] Failed to load cache: {e}")


async def _background_scan():
    """Run scan in background so endpoints don't block."""
    global _scan_running
    try:
        print("[Scan] Background scan started...")
        await _run_scan()
        print("[Scan] Background scan completed successfully")
    except Exception as e:
        import traceback
        print(f"[Scan] Background scan CRASHED: {e}")
        traceback.print_exc()
    finally:
        _scan_running = False


@router.post("/scan/refresh")
async def refresh_scan():
    """Force a fresh scan in background (non-blocking)."""
    global _scan_cache, _scan_running
    _scan_cache = None
    # Force reset if scan seems stuck (> 10 min)
    _scan_running = False
    _scan_running = True
    asyncio.create_task(_background_scan())
    return {"status": "scanning", "message": "Full scan started (3,000+ stocks). Results on GET /scan/opportunities."}


@router.get("/scan/best-replacement/{sell_ticker}")
async def get_best_replacement(sell_ticker: str):
    """Find the best validated replacement for a stock we want to sell.

    Architecture:
    1. Load pre-ranked backtested candidates from cache (instant)
    2. Pick top N that beat the stock being sold
    3. Run full validation (analyst + sentiment + earnings) ONLY on those
    4. Return the best validated replacement
    """
    sell_ticker = sell_ticker.upper()

    # Get the score of the stock we're selling
    holdings_scores, _, _ = _get_holdings_scores()
    sell_score = holdings_scores.get(sell_ticker, {}).get("score", 0)
    if sell_score == 0:
        # Not a current holding — just use 0 as baseline
        bt = _backtest_7day(sell_ticker)
        sell_score = bt.get("avg_return", 0) * bt.get("win_rate", 0) / 100

    # Load all backtested candidates from today's scan cache
    today = datetime.now().strftime('%Y-%m-%d')
    cache_path = os.path.join(os.path.dirname(__file__), "data", f"scan_{today}.json")
    if not os.path.exists(cache_path):
        raise HTTPException(404, "No scan data for today. Run /scan/refresh first.")

    with open(cache_path) as f:
        all_candidates = json.load(f)

    # Filter: price >= $20, not held, score beats the selling stock
    candidates = []
    for r in all_candidates:
        price = r.get("price", 0)
        ticker = r.get("ticker", "")
        if price < MIN_PRICE or ticker in holdings_scores or r.get("vetoed"):
            continue
        score = round(r.get("avg_return", 0) * r.get("win_rate", 0) / 100, 2)
        if score > sell_score:
            r["_score"] = score
            candidates.append(r)

    # Sort by zone_return (best replacement first)
    candidates.sort(key=lambda x: x.get("zone_return", 0), reverse=True)
    top_n = candidates[:10]  # Validate top 10

    if not top_n:
        return {"replacement": None, "message": f"No stock beats {sell_ticker} (score={sell_score:.2f})"}

    # Run full validation on these candidates
    from deep_scanner import DeepScanner, ScanResult as SR
    from dataclasses import asdict, fields as dc_fields
    scanner = DeepScanner()

    # Convert cache dicts back to ScanResult dataclasses for phase3_validate
    scan_results = []
    for r in top_n:
        kwargs = {}
        for f in dc_fields(SR):
            if f.name in r:
                kwargs[f.name] = r[f.name]
        scan_results.append(SR(**kwargs))

    validated = await scanner.phase3_validate(scan_results, top_n=len(scan_results))

    # Find best non-vetoed result
    best = None
    for r in validated:
        rd = asdict(r)
        if rd.get("vetoed"):
            continue
        if not rd.get("analyst_consensus") and not rd.get("sentiment_label"):
            continue  # Validation failed (no data)
        opp = _dict_to_opportunity(rd, holdings_scores)
        if opp.vetoed:
            continue
        if best is None or opp.score > best.score:
            best = opp

    if best:
        # Fetch live price
        live = _price_cache.get(best.ticker)
        if live and live.get("price", 0) > 0:
            best.price = round(live["price"], 2)
        return {
            "replacement": best.model_dump(),
            "sell_ticker": sell_ticker,
            "sell_score": round(sell_score, 2),
            "candidates_checked": len(top_n),
            "message": f"Best replacement for {sell_ticker}: {best.ticker} (score={best.score:.2f} vs {sell_score:.2f})"
        }
    else:
        return {
            "replacement": None,
            "sell_ticker": sell_ticker,
            "candidates_checked": len(top_n),
            "message": f"All {len(top_n)} candidates were vetoed (earnings/sentiment/analyst)"
        }


def _backtest_7day(ticker: str) -> dict:
    """Backtest using ATLAS V2.5: RSI<10 entry, 30-day fixed hold, price > SMA50.
    Fallback for holdings scoring when hybrid exit data unavailable."""
    df = _cache.get(ticker, 1260)
    if df is None or len(df) < 60:
        return {}

    # Drop NaN closes first to keep opens/closes aligned
    df = df.dropna(subset=["Close"])
    closes = df["Close"].tolist()
    if len(closes) < 60:
        return {}

    _FEE_PCT = 0.30
    opens = df["Open"].tolist() if "Open" in df.columns else closes
    rsi_arr = _rsi2_array(closes)
    sma_arr = _sma_array(closes, 50)
    last_exit_day = -1
    trades = []
    for i in range(50, len(closes) - 32):
        if i <= last_exit_day:
            continue
        if rsi_arr[i] < 10 and closes[i] > sma_arr[i]:
            entry_px = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
            exit_px = closes[i + 1 + 30]
            ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT
            trades.append({"return": ret, "win": ret > 0})
            last_exit_day = i + 1 + 30

    if len(trades) < 10:
        return {}

    wins_7d = sum(1 for t in trades if t["win"])
    wr = wins_7d / len(trades) * 100
    avg_ret = sum(t["return"] for t in trades) / len(trades)
    return {"win_rate": round(wr, 1), "avg_return": round(avg_ret, 2), "trades": len(trades),
            "bayesian_wr": _bayesian_wr(wins_7d, len(trades))}


def _get_holdings_scores() -> tuple:
    """Get current portfolio holdings scores using hybrid exit strategy.
    Each holding gets its best exit strategy's return, not fixed 7d.
    Also tracks exit_triggered so upgrades only suggest switching ready-to-exit positions."""
    positions = _position_mgr._get_open_positions_sync()
    holdings_scores = {}
    for pos in positions:
        ticker = pos["ticker"]
        tech = _technicals_cache.get(ticker)
        # Use hybrid strategy return if available, fallback to fixed 7d
        strat_ret = tech.get("exit_strategy_ret", 0) if tech else 0
        strat_wr = tech.get("exit_strategy_wr", 0) if tech else 0
        if tech and tech.get("bayesian_wr"):
            strat_wr = min(strat_wr, tech["bayesian_wr"])  # Use the more conservative estimate
        if strat_ret == 0 or strat_wr == 0:
            try:
                bt = _backtest_7day(ticker)
                strat_wr = bt.get("win_rate", 0)
                strat_ret = bt.get("avg_return", 0)
            except Exception:
                strat_wr = 50
                strat_ret = 0
        # Re-evaluate exit trigger with LIVE price (same as portfolio endpoint does)
        # Without this, exit_triggered can be stale from warmup cache
        exit_triggered = tech.get("exit_triggered", False) if tech else False
        if tech and tech.get("exit_strategy") and not exit_triggered:
            entry_price = pos.get("entry_price", 0)
            entry_date = pos.get("entry_date", "")
            live = _price_cache.get(ticker, {})
            live_price = live.get("price", 0) if live else 0
            try:
                df = _cache.get(ticker, 365)
            except Exception:
                df = None
            if df is not None and len(df) >= 10 and live_price > 0:
                closes_live = df["Close"].dropna().tolist()
                rsi_live = tech.get("rsi2", -1)
                exit_cached = _exit_strategy_cache.get(ticker)
                if not exit_cached:
                    exit_cached = {"strategy": tech["exit_strategy"]}
                live_exit = _evaluate_exit_trigger(
                    exit_cached, closes_live, rsi_live, live_price, entry_price,
                    entry_date=entry_date
                )
                exit_triggered = live_exit["triggered"]
                # Update cache so portfolio endpoint stays in sync
                tech["exit_triggered"] = exit_triggered
        below_sma50 = not tech.get("above_sma50", True) if tech else False
        # Backtest quality check: BOTH ATLAS and exit zone must fail for EXIT
        ez_wr = tech.get("exit_zone_wr", 0) if tech else 0
        ez_ret = tech.get("exit_zone_return", 0) if tech else 0
        ez_trades = tech.get("exit_zone_trades", 0) if tech else 0
        atlas_wr = tech.get("win_rate", 0) if tech else 0
        atlas_trades = tech.get("total_trades", 0) if tech else 0
        bad_backtest = ez_trades >= 10 and (ez_ret < 0 or ez_wr < 65) and \
                       (atlas_trades < 10 or atlas_wr < 65)
        signal = "EXIT" if (exit_triggered or bad_backtest) else "HOLD"
        if strat_wr > 0:
            score = strat_ret * strat_wr / 100
            holdings_scores[ticker] = {
                "score": round(score, 2),
                "zone_return": strat_ret,
                "win_rate": strat_wr,
                "exit_triggered": exit_triggered,
                "below_sma50": below_sma50,
                "bad_backtest": bad_backtest,
                "signal": signal,
            }
    worst_ticker = min(holdings_scores, key=lambda k: holdings_scores[k]["score"]) if holdings_scores else ""
    worst_score = holdings_scores[worst_ticker]["score"] if worst_ticker else 0
    return holdings_scores, worst_ticker, worst_score


MIN_PRICE = 10.0       # Filter low-priced stocks — too volatile/risky below $10
MIN_VOLUME_RATIO = 0.3  # Relaxed; volume spike checked in model
# Tiered WR thresholds: prefer 80%+, fallback to 70%, then 65%
WR_TIERS = [
    (80, "TIER1"),   # Best: +7.23% avg on 122-stock study
    (70, "TIER2"),   # Great: +5.81% avg
    (65, "TIER3"),   # Good: +5.36% avg, 96% profitable
]
MIN_WR = 65  # Hard floor — below 65% is not worth the risk


def _compute_composite_score(r: dict) -> Tuple[float, str]:
    """Compute 0-100 composite ranking score from multiple factors.
    Returns (score, factors_str) for display."""
    pts = 0.0
    factors = []

    zone_ret = r.get("zone_return", 0)
    zone_wr = r.get("zone_win_rate", 0)
    zone_trades = r.get("zone_trades", 0)
    wr = r.get("win_rate", 0)
    rsi2 = r.get("rsi2", 25)
    atr_pct = r.get("atr_pct", 0)
    sma50_buffer = r.get("sma50_buffer", 0)
    vol_ratio = r.get("volume_ratio", 0)
    analyst_cons = r.get("analyst_consensus", "")
    sentiment_score = r.get("sentiment_score", 0)

    # 1. Zone return quality (30 pts) — zone_ret * zone_wr / 100, scaled
    if zone_trades >= 3 and zone_wr > 0:
        zr_score = zone_ret * zone_wr / 100
    else:
        zr_score = r.get("avg_return", 0) * wr / 100
    zr_pts = min(30, max(0, zr_score * 3))  # 10 score = 30 pts
    pts += zr_pts
    factors.append(f"ZR:{zr_score:.1f}")

    # 2. Win rate (20 pts)
    effective_wr = zone_wr if zone_trades >= 5 else wr
    if effective_wr >= 80:
        wr_pts = 20
    elif effective_wr >= 65:
        wr_pts = 12
    elif effective_wr >= 50:
        wr_pts = 5
    else:
        wr_pts = 0
    pts += wr_pts
    factors.append(f"WR:{effective_wr:.0f}")

    # 3. RSI(2) depth (15 pts) — deeper oversold = higher score
    rsi_pts = max(0, min(15, (50 - rsi2) / 50 * 15))
    pts += rsi_pts
    factors.append(f"RSI:{rsi2:.0f}")

    # 4. ATR% volatility (10 pts) — higher = more bounce potential
    atr_pts = min(10, atr_pct * 2)  # 5% ATR = 10 pts
    pts += atr_pts
    factors.append(f"ATR:{atr_pct:.1f}")

    # 5. SMA50 buffer (10 pts) — higher = stronger uptrend
    buf_pts = min(10, max(0, sma50_buffer * 0.5))  # 20% buffer = 10 pts
    pts += buf_pts
    factors.append(f"BUF:{sma50_buffer:.0f}")

    # 6. Analyst consensus (5 pts)
    analyst_map = {"Buy": 5, "Strong Buy": 5, "Outperform": 4, "Overweight": 4,
                   "": 2, "Hold": -1, "Sell": -5, "Underperform": -3}
    a_pts = max(-5, analyst_map.get(analyst_cons, 2))
    pts += a_pts

    # 7. Sentiment (5 pts)
    if sentiment_score > 0.2:
        s_pts = 5
    elif sentiment_score > -0.1:
        s_pts = 2
    else:
        s_pts = -5
    pts += s_pts

    # 8. Volume ratio (5 pts)
    if vol_ratio >= 1.5:
        v_pts = 5
    elif vol_ratio >= 1.0:
        v_pts = 3
    elif vol_ratio > 0 and vol_ratio < 0.3:
        v_pts = 0
    else:
        v_pts = 2  # unknown volume = neutral
    pts += v_pts

    composite = max(0, min(100, pts))
    return round(composite, 1), " ".join(factors)


def _quality_tier(score: float) -> str:
    """Map composite score to quality tier."""
    if score >= 70:
        return "BEST"
    elif score >= 55:
        return "GOOD"
    elif score >= 40:
        return "FAIR"
    elif score >= 25:
        return "WEAK"
    return "POOR"


def _meets_strict_criteria(r: dict) -> bool:
    """Check if stock passes ALL original strict ATLAS V2.5 entry criteria."""
    rsi2 = r.get("rsi2", 99)
    atr_pct = r.get("atr_pct", 0)
    sma50_buffer = r.get("sma50_buffer", 0)
    zone_wr = r.get("zone_win_rate", 0)
    zone_trades = r.get("zone_trades", 0)
    wr = r.get("win_rate", 0)
    trades = r.get("trades", 0)
    zone_ret = r.get("zone_return", 0)
    avg_ret = r.get("avg_return", 0)
    effective_wr = zone_wr if zone_trades >= 5 else wr

    return (rsi2 < 10
            and atr_pct >= 3
            and sma50_buffer >= 5
            and effective_wr >= 65
            and trades >= 6
            and zone_ret > 0
            and avg_ret >= 3)


def _dict_to_opportunity(r: dict, holdings_scores: dict) -> ScanOpportunity:
    """Convert a scan result dict to ScanOpportunity with composite ranking.
    Uses composite score (0-100) for ranking. Only 3 hard vetos remain."""
    zone_ret = r.get("zone_return", 0)
    zone_wr = r.get("zone_win_rate", 0)
    zone_trades = r.get("zone_trades", 0)
    if zone_trades >= 5 and zone_wr > 0:
        score = round(zone_ret * zone_wr / 100, 2)
    else:
        score = round(r.get("avg_return", 0) * r.get("win_rate", 0) / 100, 2)

    ticker = r.get("ticker", "")
    price = r.get("price", 0)
    vol_ratio = r.get("volume_ratio", 0)
    vetoed = r.get("vetoed", False)
    veto_reason = r.get("veto_reason", "")

    # VETO filters — aligned with CLAUDE.md V2.6 + research best practices
    trades_count = r.get("trades", 0)
    # 0. Minimum 10 trades (below this, WR is statistically meaningless)
    if not vetoed and trades_count < 10:
        vetoed = True
        veto_reason = f"Too few trades ({trades_count} < 10 minimum)"
    # 1. Price minimum
    if not vetoed and price < 10:
        vetoed = True
        veto_reason = f"Price too low (${price:.2f} < $10)"
    # 2. Earnings veto (already set in Phase 3 if applicable)
    # 3. Negative sentiment (unified threshold: -0.3)
    if not vetoed and r.get("sentiment_score", 0) < -0.3:
        vetoed = True
        veto_reason = f"Negative sentiment ({r.get('sentiment_score', 0):.2f})"
    # 4. Zone WR < 55% Bayesian (shrunk toward universe prior)
    if not vetoed and zone_trades >= 5:
        _bayes_zone = _bayesian_wr(int(zone_wr * zone_trades / 100), zone_trades)
        if _bayes_zone < 55:
            vetoed = True
            veto_reason = f"Bayesian zone WR too low ({_bayes_zone:.0f}% < 55%, raw {zone_wr:.0f}%)"
    # 5. Zone trades < 5 (insufficient sample)
    if not vetoed and zone_trades < 5 and r.get("trades", 0) < 10:
        vetoed = True
        veto_reason = f"Insufficient data ({r.get('trades', 0)} trades, {zone_trades} zone)"
    # 6. Average return < 3%
    avg_ret_check = r.get("avg_return", 0)
    if not vetoed and avg_ret_check < 3:
        vetoed = True
        veto_reason = f"Avg return too low ({avg_ret_check:.1f}% < 3%)"
    # 7. Score < 3.0
    if not vetoed and score < 3.0:
        vetoed = True
        veto_reason = f"Score too low ({score:.1f} < 3.0)"
    # 8. Analyst consensus Hold/Sell
    analyst_con = r.get("analyst_consensus", "")
    if not vetoed and analyst_con in ("Hold", "Sell", "Underperform", "Strong Sell"):
        vetoed = True
        veto_reason = f"Analyst says {analyst_con}"
    # 9. Missing validation — stock skipped Phase 3 (no analyst OR sentiment data)
    if not vetoed and not analyst_con and not r.get("sentiment_label"):
        vetoed = True
        veto_reason = "Not validated (no analyst/sentiment data)"

    # Composite ranking score
    composite, ranking_factors = _compute_composite_score(r)
    quality = _quality_tier(composite)
    strict = _meets_strict_criteria(r)

    # Which holdings does this stock beat?
    tier = r.get("tier", "NONE")
    sentiment_label = r.get("sentiment_label", "")
    if ticker in holdings_scores or vetoed:
        beats = []
    elif sentiment_label == "NEGATIVE":
        beats = []
    elif r.get("trades", 0) < 6:
        beats = []
    else:
        premium = 1.0 if tier == "EXTREME" else (1.1 if tier == "STRONG" else 1.3)
        beats = [
            h_ticker for h_ticker, h_data in holdings_scores.items()
            if score > h_data["score"] * premium
            and r.get("zone_trades", 0) >= 5
            and (h_data.get("exit_triggered", False) or h_data.get("bad_backtest", False))
        ]

    return ScanOpportunity(
        ticker=ticker,
        price=price,
        rsi2=r.get("rsi2", 0),
        rsi_zone=r.get("rsi_zone", ""),
        regime=r.get("regime", ""),
        tier=r.get("tier", "NONE"),
        win_rate=r.get("win_rate", 0),
        trades=r.get("trades", 0),
        avg_return=r.get("avg_return", 0),
        zone_return=r.get("zone_return", 0),
        zone_trades=r.get("zone_trades", 0),
        zone_win_rate=r.get("zone_win_rate", 0),
        volume_ratio=vol_ratio,
        hold_days=r.get("hold_days", 21),
        low52_dist=r.get("low52_dist", 0),
        atr_pct=r.get("atr_pct", 0),
        sma50_buffer=r.get("sma50_buffer", 0),
        ret20=r.get("ret20", 0),
        ml_score=r.get("ml_score", 0),
        analyst_consensus=r.get("analyst_consensus", ""),
        analyst_target=r.get("analyst_target", 0),
        analyst_upside=r.get("analyst_upside", 0),
        sentiment_label=r.get("sentiment_label", ""),
        sentiment_score=r.get("sentiment_score", 0),
        vetoed=vetoed,
        veto_reason=veto_reason,
        score=score,
        wr_tier=next((t for wr_min, t in WR_TIERS if (zone_wr if zone_trades >= 5 else r.get("win_rate", 0)) >= wr_min), ""),
        quality_tier=quality,
        composite_score=composite,
        ranking_factors=ranking_factors,
        meets_strict=strict,
        beats_holdings=beats,
        is_upgrade=len(beats) > 0,
    )


def _build_scan_result(opportunities: list, total_scanned: int,
                       holdings_scores: dict, worst_ticker: str, worst_score: float) -> Dict:
    """Build the scan response dict. Sort by composite_score descending."""
    # Sort by composite score (best first), vetoed last
    opportunities.sort(key=lambda x: (not x.vetoed, x.composite_score), reverse=True)

    h_scores = [
        HoldingScore(
            ticker=t, score=d["score"], zone_return=d["zone_return"], win_rate=d["win_rate"],
            exit_triggered=d.get("exit_triggered", False), signal=d.get("signal", "HOLD"),
        ).model_dump()
        for t, d in holdings_scores.items()
    ]

    non_vetoed = [o for o in opportunities if not o.vetoed]
    return {
        "timestamp": datetime.now().isoformat(),
        "total_scanned": total_scanned,
        "passed": len([o for o in non_vetoed if o.meets_strict]),
        "ranked_count": len(non_vetoed),
        "opportunities": [o.model_dump() for o in opportunities],  # ALL stocks, no limit
        "holdings_scores": h_scores,
        "worst_holding": worst_ticker,
        "worst_score": worst_score,
    }


async def _run_scan() -> Dict:
    """Run full stock scan: Phase 2 on 3,000+ stocks, Phase 3 on top candidates.

    Pipeline (V2.6 loose ranked):
    1. Bulk-read all cached historical data (3,000+ tickers, ~2s)
    2. Phase 2: backtest all — loose filters (RSI<25, above SMA50, ATR>1.5%)
    3. Composite ranking score (0-100) + quality tiers (BEST/GOOD/FAIR/WEAK/POOR)
    4. Phase 3: validate top 15 candidates with analyst + sentiment + earnings
    5. Return ALL ranked stocks sorted by composite_score
    """
    global _scan_cache, _scan_cache_time

    try:
        from deep_scanner import DeepScanner
        from dataclasses import asdict

        holdings_scores, worst_ticker, worst_score = _get_holdings_scores()
        scanner = DeepScanner()

        # Phase 0: Discover currently oversold stocks from Finviz
        from deep_scanner import STOCK_UNIVERSE
        discovered = await scanner.phase0_discover()

        # Build combined ticker list: discovered (priority) + full universe
        all_tickers = list(dict.fromkeys(discovered + STOCK_UNIVERSE))
        print(f"[Scan] Combined scan list: {len(all_tickers)} unique tickers "
              f"({len(discovered)} discovered oversold)")

        # Phase 1: Load from cache + fetch missing from ALL APIs
        stock_data = await scanner.phase1_fetch_data(all_tickers)
        total_scanned = len(stock_data)
        print(f"[Scan] Phase 2: scanning {total_scanned} stocks...")

        # Phase 2: backtest all (V2.5: RSI<10, SMA50 buf>10%, ATR>5%, WR>=65%)
        # Run in thread to avoid blocking the event loop (gunicorn heartbeat)
        results = await asyncio.to_thread(scanner.phase2_backtest, stock_data, discovered)
        print(f"[Scan] Phase 2 done: {len(results)} passed all filters")

        if results:
            # Rank ALL candidates: filter price + not held, sort by score
            scored = []
            for r in results:
                r_dict = asdict(r)
                price = r_dict.get("price", 0)
                ticker = r_dict.get("ticker", "")
                if price < MIN_PRICE:
                    continue
                if ticker in holdings_scores:
                    continue
                zt = r_dict.get("zone_trades", 0)
                if zt >= 5 and r_dict.get("zone_win_rate", 0) > 0:
                    score = round(r_dict.get("zone_return", 0) * r_dict.get("zone_win_rate", 0) / 100, 2)
                else:
                    score = round(r_dict.get("avg_return", 0) * r_dict.get("win_rate", 0) / 100, 2)
                scored.append((score, r))

            scored.sort(key=lambda x: x[0], reverse=True)
            print(f"[Scan] {len(scored)} candidates (price >= ${MIN_PRICE:.0f}, not held)")

            # Phase 3: validate ALL candidates — every stock shown must be fully checked
            # (earnings, analyst consensus, sentiment). No stale data in upgrades tab.
            top_to_validate = [r for _, r in scored]
            print(f"[Scan] Phase 3: validating all {len(top_to_validate)} candidates")

            if top_to_validate:
                validated = await scanner.phase3_validate(top_to_validate, top_n=len(top_to_validate))
                # Merge validated data back into full results
                validated_map = {r.ticker: r for r in validated}
                for i, r in enumerate(results):
                    if r.ticker in validated_map:
                        results[i] = validated_map[r.ticker]

        # Save to disk AFTER Phase 3 so validated data persists across restarts
        scanner.save_cache(results)

        # Convert to opportunities
        opportunities = []
        for r in results:
            r_dict = asdict(r)
            opp = _dict_to_opportunity(r_dict, holdings_scores)
            opportunities.append(opp)

        # Update prices with live quotes + recalculate technicals for ranking
        for opp in opportunities:
            live = _price_cache.get(opp.ticker)
            if live and live.get("price", 0) > 0:
                opp.price = round(live["price"], 2)
                df = _cache.get(opp.ticker, 365)
                if df is not None and len(df) >= 50:
                    closes = df["Close"].dropna().tolist()
                    if abs(live["price"] - closes[-1]) / closes[-1] > 0.001:
                        closes = closes + [live["price"]]
                    rsi2 = _entry.calc_rsi(closes, 2)
                    opp.rsi2 = round(rsi2, 1)
                    # Update SMA50 buffer with live price
                    if len(closes) >= 50:
                        sma50 = sum(closes[-50:]) / 50
                        if sma50 > 0:
                            opp.sma50_buffer = round((live["price"] - sma50) / sma50 * 100, 1)
                    # Only veto if below SMA50 (not in uptrend)
                    if not opp.vetoed and len(closes) >= 50:
                        sma50 = sum(closes[-50:]) / 50
                        if live["price"] < sma50:
                            opp.vetoed = True
                            opp.veto_reason = f"Below SMA50 (${live['price']:.0f} < ${sma50:.0f})"
                            opp.is_upgrade = False
                            opp.beats_holdings = []
                    # Recalculate composite score with live data
                    opp_dict = opp.model_dump()
                    opp.composite_score, opp.ranking_factors = _compute_composite_score(opp_dict)
                    opp.quality_tier = _quality_tier(opp.composite_score)
                    opp.meets_strict = _meets_strict_criteria(opp_dict)
                # Crash filter: veto if stock dropped > 8% today
                if not opp.vetoed and len(closes) >= 2:
                    prev_close = closes[-2] if len(closes) > 1 else closes[-1]
                    live_px = live["price"]
                    if prev_close > 0 and live_px > 0:
                        day_chg_pct = (live_px / prev_close - 1) * 100
                        if day_chg_pct < -8:
                            opp.vetoed = True
                            opp.veto_reason = f"Crash ({day_chg_pct:.1f}% today)"
                            opp.is_upgrade = False
                            opp.beats_holdings = []
                # Re-check penny stock with live price
                if not opp.vetoed and live["price"] < 5:
                    opp.vetoed = True
                    opp.veto_reason = f"Penny stock (${live['price']:.2f} < $5)"
                    opp.is_upgrade = False
                    opp.beats_holdings = []

        # Sort by composite score
        opportunities.sort(key=lambda x: (not x.vetoed, x.composite_score), reverse=True)

        result = _build_scan_result(opportunities, total_scanned,
                                    holdings_scores, worst_ticker, worst_score)
        _scan_cache = result
        _scan_cache_time = datetime.now()
        return result

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": str(e), "timestamp": datetime.now().isoformat(),
                "total_scanned": 0, "passed": 0, "opportunities": [],
                "holdings_scores": [], "worst_holding": "", "worst_score": 0}


# ── Buy/Sell Endpoints ──

@router.post("/positions/buy", response_model=TradeResult)
async def buy_position(req: BuyRequest):
    """Record a buy and create position + transaction."""
    ticker = req.ticker.upper()
    total = req.price * req.shares
    fee = 1.50 if not ticker.endswith(".TA") else 0  # No fee tracking for ILS
    currency = "ILS" if ticker.endswith(".TA") else "USD"

    # Add position
    result = _position_mgr._add_position_sync(
        ticker=ticker,
        entry_date=datetime.now().strftime("%Y-%m-%d"),
        entry_price=req.price,
        shares=req.shares,
        notes=req.notes,
        currency=currency,
    )

    if "error" in result:
        return TradeResult(success=False, message=result["error"], ticker=ticker)

    # Record transaction
    tx = _position_mgr.add_transaction(
        ticker=ticker, action="BUY", price=req.price, shares=req.shares,
        fee=fee, notes=req.notes, position_id=result.get("position_id"),
    )

    # Invalidate caches so signals/exit strategies are recalculated with new position
    _signal_cache.clear()
    _exit_strategy_cache.clear()
    global _scan_cache
    _scan_cache = None  # Force scan cache rebuild (holdings changed)

    return TradeResult(
        success=True,
        message=f"Bought {req.shares} shares of {ticker} @ ${req.price:.2f}",
        transaction_id=tx.get("transaction_id"),
        ticker=ticker,
        shares=req.shares,
        price=req.price,
        total=total,
        fee=fee,
    )


@router.post("/positions/sell", response_model=TradeResult)
async def sell_position(req: SellRequest):
    """Record a sell (full or partial), update position, and log transaction."""
    ticker = req.ticker.upper()
    total = req.price * req.shares
    # ILS positions (.TA tickers) have no commission fee
    fee = 0.0 if ticker.endswith(".TA") else 1.50

    # Find open position for this ticker
    positions = _position_mgr._get_open_positions_sync()
    pos = next((p for p in positions if p["ticker"] == ticker), None)

    if not pos:
        return TradeResult(success=False, message=f"No open position for {ticker}", ticker=ticker)

    # Validate share count
    if req.shares > pos["shares"] + 0.0001:  # Small epsilon for float rounding
        return TradeResult(
            success=False,
            message=f"Cannot sell {req.shares} shares — only {pos['shares']} held",
            ticker=ticker,
        )

    # Calculate realized P&L
    realized_pnl = (req.price - pos["entry_price"]) * req.shares - fee

    # Partial vs full sell
    remaining_shares = pos["shares"] - req.shares
    if remaining_shares < 0.001:
        # Full sell — close position entirely
        _position_mgr._close_position_sync(
            position_id=pos["id"],
            exit_date=datetime.now().strftime("%Y-%m-%d"),
            exit_price=req.price,
        )
        sell_msg = f"Sold ALL {req.shares:.4f} shares of {ticker}"
    else:
        # Partial sell — reduce shares, keep position open
        import sqlite3 as _sqlite3
        _pos_db = os.path.join(os.path.dirname(__file__), "data", "positions.db")
        conn = _sqlite3.connect(_pos_db)
        try:
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                "UPDATE positions SET shares = ? WHERE id = ?",
                (round(remaining_shares, 4), pos["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        sell_msg = f"Sold {req.shares:.4f} of {pos['shares']:.4f} shares of {ticker} ({remaining_shares:.4f} remaining)"

    # Record transaction
    tx = _position_mgr.add_transaction(
        ticker=ticker, action="SELL", price=req.price, shares=req.shares,
        fee=fee, realized_pnl=realized_pnl, notes=req.notes,
        position_id=pos["id"],
    )

    # Invalidate caches so signals/exit strategies are recalculated without sold position
    _signal_cache.clear()
    _exit_strategy_cache.clear()
    global _scan_cache
    _scan_cache = None  # Force scan cache rebuild (holdings changed)

    return TradeResult(
        success=True,
        message=f"{sell_msg} @ ${req.price:.2f} (P&L: ${realized_pnl:+.2f})",
        transaction_id=tx.get("transaction_id"),
        ticker=ticker,
        shares=req.shares,
        price=req.price,
        total=total,
        fee=fee,
    )


# ── History Endpoint ──

@router.get("/positions/history")
async def get_history(ticker: str = None, limit: int = 100):
    """Get transaction history."""
    txs = _position_mgr.get_transactions(ticker=ticker, limit=limit)
    summary = _position_mgr.get_transaction_summary()

    transactions = [
        TransactionRecord(
            id=tx["id"],
            ticker=tx["ticker"],
            action=tx["action"],
            date=tx["date"],
            price=tx["price"],
            shares=tx["shares"],
            total=tx["total"],
            fee=tx.get("fee", 1.50),
            realized_pnl=tx.get("realized_pnl"),
            notes=tx.get("notes") or "",
        )
        for tx in txs
    ]

    return HistoryResponse(
        transactions=transactions,
        total_fees=summary["total_fees"],
        total_realized_pnl=summary["total_realized_pnl"],
        trade_count=summary["trade_count"],
    )


_perf_cache: Optional[Dict] = None
_perf_cache_time: Optional[datetime] = None

@router.get("/performance", response_model=PerformanceResponse)
async def get_performance():
    """Trade performance: win/loss table + daily P&L chart. Cached 5 min."""
    global _perf_cache, _perf_cache_time
    import sqlite3
    from datetime import date

    # Return cached response if fresh (< 5 min)
    if _perf_cache and _perf_cache_time and (datetime.now() - _perf_cache_time).total_seconds() < 300:
        return _perf_cache

    db_path = os.path.join(os.path.dirname(__file__), "data", "positions.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get ALL positions (open + closed) for USD
    rows = conn.execute(
        "SELECT id, ticker, shares, entry_price, entry_date, exit_date, exit_price, status "
        "FROM positions WHERE currency='USD' ORDER BY entry_date"
    ).fetchall()

    trades = []
    for r in rows:
        ticker = r["ticker"]
        entry_price = r["entry_price"]
        shares = r["shares"] if r["shares"] else 0
        entry_date = r["entry_date"]
        status = r["status"]

        if status == "CLOSED":
            exit_date = r["exit_date"] or ""
            exit_price = r["exit_price"] or 0

            if exit_price and exit_price > 0:
                # For closed positions, shares may be 0 — recover from transactions
                if shares == 0:
                    # Sum all buy shares (handles positions with multiple adds)
                    buy_sum = conn.execute(
                        "SELECT SUM(shares) as total_shares FROM transactions WHERE position_id=? AND action='BUY'",
                        (r["id"],)
                    ).fetchone()
                    if buy_sum and buy_sum["total_shares"]:
                        shares = buy_sum["total_shares"]
                    elif entry_price > 0:
                        sell_tx = conn.execute(
                            "SELECT shares FROM transactions WHERE position_id=? AND action='SELL' LIMIT 1",
                            (r["id"],)
                        ).fetchone()
                        if sell_tx:
                            shares = sell_tx["shares"]

                pnl = (exit_price - entry_price) * shares
                # Override with actual realized P&L from transaction if available
                tx = conn.execute(
                    "SELECT SUM(realized_pnl) as total_rpnl FROM transactions WHERE position_id=? AND action='SELL' AND realized_pnl IS NOT NULL",
                    (r["id"],)
                ).fetchone()
                if tx and tx["total_rpnl"] is not None:
                    pnl = tx["total_rpnl"]
            else:
                # Legacy positions with no exit price — skip (pre-system trades)
                continue
        else:
            exit_date = ""
            quote = _price_cache.get(ticker)
            if quote:
                exit_price = quote["price"]
            else:
                # Direct SQL fallback — no pandas overhead
                try:
                    _cache_conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "data", "stock_cache.db"))
                    _row = _cache_conn.execute(
                        "SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
                        (ticker.upper(),)
                    ).fetchone()
                    exit_price = _row[0] if _row else entry_price
                    _cache_conn.close()
                except Exception:
                    exit_price = entry_price
            pnl = (exit_price - entry_price) * shares

        cost = entry_price * shares
        value = exit_price * shares
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0

        # Hold days (trading days to match backtest bars)
        try:
            d1 = date.fromisoformat(entry_date)
            d2 = date.fromisoformat(exit_date) if exit_date else date.today()
            hold_days = sum(
                1 for n in range((d2 - d1).days)
                if (d1 + timedelta(days=n + 1)).weekday() < 5
            )
        except (ValueError, TypeError):
            hold_days = 0

        result = "OPEN" if status != "CLOSED" else ("WIN" if pnl > 0 else "LOSS")

        trades.append(TradePerformance(
            ticker=ticker, status="OPEN" if status != "CLOSED" else "CLOSED",
            entry_date=entry_date, exit_date=exit_date, hold_days=hold_days,
            entry_price=round(entry_price, 2), exit_price=round(exit_price, 2),
            shares=round(shares, 4), cost=round(cost, 2), value=round(value, 2),
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2), result=result,
        ))

    # Deposits by date (broker-verified) — used for P&L %
    _deposits = [
        ("2026-01-04", 1500.00),
        ("2026-01-07", 1500.00),
        ("2026-01-08", 200.00),
        ("2026-01-15", 500.00),
        ("2026-01-30", 1500.21),
        ("2026-02-13", 3213.37),
        ("2026-02-27", 3478.00),
    ]
    total_deposited = sum(d[1] for d in _deposits)  # $11,891.58

    # Build cumulative deposits by date for daily PnL curve
    _cum_deposits = {}
    _cum = 0.0
    for d_date, d_amt in sorted(_deposits):
        _cum += d_amt
        _cum_deposits[d_date] = _cum
    _deposit_dates_sorted = sorted(_cum_deposits.keys())

    # Daily P&L curve: reconstruct from positions + historical prices + realized gains
    daily_pnl = []

    all_dates = [t.entry_date for t in trades]
    if all_dates:
        start = min(all_dates)
        try:
            start_date = date.fromisoformat(start)
        except (ValueError, TypeError):
            start_date = date.today()

        today = date.today()

        # Build price cache using direct SQL (no pandas overhead)
        all_tickers = list(set(t.ticker for t in trades))
        price_data = {}
        cache_db_path = os.path.join(os.path.dirname(__file__), "data", "stock_cache.db")
        try:
            cache_conn = sqlite3.connect(cache_db_path)
            for ticker in all_tickers:
                rows = cache_conn.execute(
                    "SELECT date, close FROM daily_prices WHERE ticker=? AND date>=? ORDER BY date",
                    (ticker.upper(), start)
                ).fetchall()
                if rows:
                    price_data[ticker] = {r[0]: r[1] for r in rows}
            cache_conn.close()
        except Exception:
            pass

        # Build cumulative realized P&L + fees by date from transactions
        tx_rows = conn.execute(
            "SELECT date, action, fee, realized_pnl FROM transactions ORDER BY date"
        ).fetchall()
        daily_realized = {}  # date -> cumulative realized P&L
        daily_fees = {}      # date -> cumulative fees
        cum_realized = 0.0
        cum_fees = 0.0
        for tx in tx_rows:
            tx_date = tx["date"]
            rpnl = tx["realized_pnl"]
            if rpnl is not None:
                cum_realized += rpnl
            fee = tx["fee"] or 0
            cum_fees += fee
            daily_realized[tx_date] = cum_realized
            daily_fees[tx_date] = cum_fees

        # Pre-sort realized dates for efficient forward-fill
        last_realized = 0.0
        last_fees = 0.0

        # Use index-based iteration instead of list.pop(0) which is O(n)
        deposit_dates_iter = list(_deposit_dates_sorted)
        dep_idx = 0
        deposited_so_far = 0.0

        realized_dates_list = sorted(daily_realized.keys())
        real_idx = 0

        # --- OPTIMIZATION: Pre-build sweep-line events for O(days + trades) ---
        # Instead of checking every trade on every day O(days * trades),
        # build sorted entry/exit events and maintain a running active set.

        # Build entry events: (entry_date, trade_index) sorted by entry_date
        # Build exit events: (exit_date, trade_index) sorted by exit_date
        # Only include trades with shares > 0
        entry_events = []  # (date_str, trade_idx)
        exit_events = []   # (date_str, trade_idx)
        for i, t in enumerate(trades):
            if t.shares <= 0:
                continue
            entry_events.append((t.entry_date, i))
            if t.exit_date:
                # Trade is active on [entry_date, exit_date) — exit ON exit_date
                exit_events.append((t.exit_date, i))
            # Open trades (no exit_date) stay active forever — no exit event needed

        entry_events.sort(key=lambda x: x[0])
        exit_events.sort(key=lambda x: x[0])
        entry_ev_idx = 0
        exit_ev_idx = 0
        active_trades = set()  # set of trade indices currently active

        # Supplement with live prices for today (stock_cache.db may not have today yet)
        today_str = today.isoformat()
        for ticker in all_tickers:
            quote = _price_cache.get(ticker)
            if quote and "price" in quote:
                if ticker not in price_data:
                    price_data[ticker] = {}
                price_data[ticker][today_str] = quote["price"]

        # Pre-compute sorted price date lists per ticker for O(log n) forward-fill
        # instead of re-sorting on every miss
        price_dates_sorted = {}
        for ticker in price_data:
            price_dates_sorted[ticker] = sorted(price_data[ticker].keys())

        current = start_date
        while current <= today:
            date_str = current.isoformat()
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            # Forward-fill cumulative deposits up to this date
            while dep_idx < len(deposit_dates_iter) and deposit_dates_iter[dep_idx] <= date_str:
                deposited_so_far = _cum_deposits[deposit_dates_iter[dep_idx]]
                dep_idx += 1

            # Forward-fill cumulative realized P&L and fees up to this date
            while real_idx < len(realized_dates_list) and realized_dates_list[real_idx] <= date_str:
                d = realized_dates_list[real_idx]
                last_realized = daily_realized[d]
                last_fees = daily_fees[d]
                real_idx += 1

            # Sweep-line: add trades that entered on or before this date
            while entry_ev_idx < len(entry_events) and entry_events[entry_ev_idx][0] <= date_str:
                active_trades.add(entry_events[entry_ev_idx][1])
                entry_ev_idx += 1

            # Sweep-line: remove trades that exited on or before this date
            # (exit_date is exclusive — trade is NOT active on exit_date)
            while exit_ev_idx < len(exit_events) and exit_events[exit_ev_idx][0] <= date_str:
                active_trades.discard(exit_events[exit_ev_idx][1])
                exit_ev_idx += 1

            # Calculate unrealized P&L of active positions on this date
            unrealized = 0
            total_cost = 0
            pos_count = 0

            for idx in active_trades:
                t = trades[idx]
                ticker = t.ticker
                sh = t.shares

                prices = price_data.get(ticker, {})
                price = prices.get(date_str)
                if not price:
                    # Binary search for most recent price <= date_str
                    sorted_dates = price_dates_sorted.get(ticker, [])
                    if sorted_dates:
                        bi = bisect.bisect_right(sorted_dates, date_str) - 1
                        price = prices[sorted_dates[bi]] if bi >= 0 else t.entry_price
                    else:
                        price = t.entry_price

                unrealized += (price - t.entry_price) * sh
                total_cost += t.entry_price * sh
                pos_count += 1

            # Total P&L = realized gains + unrealized gains - fees - broker tax
            total_pnl = last_realized + unrealized - last_fees - 222.00
            dep = deposited_so_far if deposited_so_far > 0 else total_deposited
            portfolio_value = dep + total_pnl
            pnl_pct = (total_pnl / dep * 100) if dep > 0 else 0

            if pos_count > 0 or last_realized != 0:
                daily_pnl.append(DailyPnL(
                    date=date_str,
                    portfolio_value=round(portfolio_value, 2),
                    total_cost=round(dep, 2),
                    pnl=round(total_pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    positions=pos_count,
                ))

            current += timedelta(days=1)

    conn.close()

    # Summary stats
    closed = [t for t in trades if t.status == "CLOSED"]
    wins = [t for t in closed if t.result == "WIN"]
    losses = [t for t in closed if t.result == "LOSS"]
    open_trades = [t for t in trades if t.status == "OPEN"]

    tx_summary = _position_mgr.get_transaction_summary()
    total_realized = round(tx_summary.get("total_realized_pnl", 0), 2)
    # Broker tax/fees paid outside of per-trade commissions (tax withholding, platform fees)
    BROKER_TAX_FEES = 222.00
    total_fees = round(tx_summary.get("total_fees", 0) + BROKER_TAX_FEES, 2)
    realized_pnl_pct = round(total_realized / total_deposited * 100, 2) if total_deposited > 0 else 0

    result = PerformanceResponse(
        trades=sorted(trades, key=lambda t: t.entry_date, reverse=True),
        daily_pnl=daily_pnl,
        # Tax: actual broker tax paid ($222), not theoretical 25%
        tax_rate=25.0,
        tax_amount=BROKER_TAX_FEES,
        net_realized=round(total_realized - BROKER_TAX_FEES, 2),
        net_pnl_pct=round((total_realized - BROKER_TAX_FEES) / total_deposited * 100, 2) if total_deposited > 0 else 0,

        total_realized=total_realized,
        total_unrealized=round(sum(t.pnl for t in open_trades), 2),
        total_fees=total_fees,
        total_deposited=total_deposited,
        realized_pnl_pct=realized_pnl_pct,
        win_count=len(wins),
        loss_count=len(losses),
        win_rate=round(len(wins) / len(closed) * 100, 1) if closed else 0,
        avg_win_pct=round(sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else 0,
        avg_loss_pct=round(sum(t.pnl_pct for t in losses) / len(losses), 2) if losses else 0,
        best_trade=max(closed, key=lambda t: t.pnl_pct).ticker if closed else "",
        worst_trade=min(closed, key=lambda t: t.pnl_pct).ticker if closed else "",
    )
    _perf_cache = result
    _perf_cache_time = datetime.now()
    return result


def _calc_optimal_entries(ticker: str, current_price: float) -> List[Dict]:
    """Calculate optimal buy prices by analyzing historical RSI(2) zones.

    For each zone (0-5, 5-10, 10-20), finds:
    - The avg % drop from recent high that triggers that RSI level
    - Backtested win rate and avg return at that zone
    - The resulting price target based on current price action
    """
    df = _cache.get(ticker, 365)
    if df is None or len(df) < 60:
        return []

    # Drop NaN closes first to keep opens/closes aligned
    df = df.dropna(subset=["Close"])
    closes = df["Close"].tolist()
    opens = df["Open"].tolist() if "Open" in df.columns else closes
    if len(closes) < 60:
        return []

    # Collect all data points with their RSI and % from recent 10-day high
    # V2.5: 21-day forward, next-day open, fee-adjusted
    _FEE_PCT = 0.30
    zones = {
        "EXTREME": {"rsi_lo": 0, "rsi_hi": 5, "label": "RSI < 5", "trades": [], "drops": []},
        "STRONG":  {"rsi_lo": 5, "rsi_hi": 10, "label": "RSI 5-10", "trades": [], "drops": []},
        "STANDARD": {"rsi_lo": 10, "rsi_hi": 20, "label": "RSI 10-20", "trades": [], "drops": []},
    }

    # Track last exit day per zone to prevent overlapping trades
    zone_last_exit = {key: -1 for key in zones}
    for i in range(50, len(closes) - 32):  # -32 to ensure room for i+1+30
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        hist_sma = _entry.calc_sma(hist_closes, 50)

        # Only consider valid buy signals (above SMA50)
        if hist_closes[-1] <= hist_sma:
            continue

        # % drop from recent 10-day high
        recent_high = max(closes[max(0, i - 10):i + 1])
        pct_drop = ((closes[i] - recent_high) / recent_high) * 100

        # V2.6: 30-day forward return, next-day open entry, fee-adjusted
        entry_px = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
        exit_px = closes[i + 1 + 30]  # True 30-day hold from entry
        ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT

        for key, z in zones.items():
            if z["rsi_lo"] <= hist_rsi < z["rsi_hi"] and i > zone_last_exit[key]:
                z["trades"].append({"return": ret, "win": ret > 0})
                z["drops"].append(pct_drop)
                zone_last_exit[key] = i + 1 + 30

    # Calculate price targets from current 10-day high
    recent_10d_high = max(closes[-10:]) if len(closes) >= 10 else closes[-1]

    results = []
    for key in ["EXTREME", "STRONG", "STANDARD"]:
        z = zones[key]
        if not z["trades"]:
            continue
        n = len(z["trades"])
        wr = sum(1 for t in z["trades"] if t["win"]) / n * 100
        avg_ret = sum(t["return"] for t in z["trades"]) / n
        avg_drop = sum(z["drops"]) / len(z["drops"])
        median_drop = sorted(z["drops"])[len(z["drops"]) // 2]
        # Use median drop to estimate entry price (more robust than mean)
        entry_price = round(recent_10d_high * (1 + median_drop / 100), 2)
        # Don't suggest entry above current price
        if entry_price > current_price:
            entry_price = round(current_price * (1 + median_drop / 100), 2)

        results.append({
            "tier": key,
            "label": z["label"],
            "price": entry_price,
            "drop_pct": round(median_drop, 1),
            "avg_return": round(avg_ret, 2),
            "win_rate": round(wr, 1),
            "trades": n,
        })

    # Add SMA50 as support level
    sma50 = _entry.calc_sma(closes, 50)
    if sma50 > 0:
        results.append({
            "tier": "SUPPORT",
            "label": "SMA50 Support",
            "price": round(sma50, 2),
            "drop_pct": round(((sma50 - current_price) / current_price) * 100, 1) if current_price > 0 else 0,
            "avg_return": 0,
            "win_rate": 0,
            "trades": 0,
        })

    return results


# ── Stock Analysis Endpoint ──

@router.get("/analyze/{ticker}")
async def analyze_stock(ticker: str):
    """Full ATLAS V2 analysis: technicals, backtest, exit zone, sentiment, analyst, earnings."""
    ticker = ticker.upper()

    # 1. Technicals + backtest (run in thread to avoid blocking event loop)
    tech = _technicals_cache.get(ticker)
    if not tech:
        tech = await asyncio.to_thread(_get_technicals, ticker)
    if not tech:
        # Attempt on-demand fetch via Tiingo → Polygon → FMP
        async with aiohttp.ClientSession() as fetch_session:
            for fetch_attempt in [
                lambda s, t: _cache._fetch_tiingo(s, t, days=400),
                lambda s, t: _cache._fetch_polygon(s, t),
                lambda s, t: _cache._fetch_fmp(s, t),
            ]:
                try:
                    result = await fetch_attempt(fetch_session, ticker)
                    if isinstance(result, pd.DataFrame) and len(result) >= 50:
                        _cache.store(ticker, result)
                        tech = await asyncio.to_thread(_get_technicals, ticker)
                        break
                except Exception:
                    continue
        if not tech:
            raise HTTPException(status_code=404, detail=f"No data for {ticker}. Could not fetch historical prices.")

    # 2. 7-day fixed hold backtest
    bt = _backtest_7day(ticker)

    # 3. Live quote (fall back to latest historical close if market closed)
    async with aiohttp.ClientSession() as session:
        quote = await _get_finnhub_quote(session, ticker)
        live_price = quote["price"] if quote else 0
        day_chg = quote["day_chg"] if quote else 0
        if live_price <= 0:
            # Market closed or Finnhub down — use latest close from cache
            df_fallback = _cache.get(ticker, 365)
            if df_fallback is not None and len(df_fallback) >= 2:
                live_price = float(df_fallback["Close"].iloc[-1])
                prev_close = float(df_fallback["Close"].iloc[-2])
                day_chg = round(((live_price - prev_close) / prev_close) * 100, 2) if prev_close > 0 else 0

        # 4. Earnings check
        earnings_date = None
        try:
            from deep_scanner import DeepScanner
            ds = DeepScanner()
            earnings = await ds._check_earnings(session, ticker)
            if earnings:
                earnings_date = earnings["date"]
        except Exception:
            pass

        # 5. Sentiment
        sentiment_label = "N/A"
        sentiment_score = 0.0
        headlines = []
        try:
            from sentiment import SentimentEngine
            se = SentimentEngine()
            sdata = await se.get_ticker_sentiment(ticker)
            if sdata:
                sentiment_label = sdata.get("sentiment_label", "N/A")
                sentiment_score = sdata.get("sentiment_score", 0)
                headlines = sdata.get("headlines", [])[:5]
        except Exception:
            pass

        # 6. Analyst
        analyst_consensus = "N/A"
        analyst_target = 0.0
        analyst_upside = 0.0
        try:
            from analyst_data import AnalystDataFetcher
            af = AnalystDataFetcher()
            adata = await af.fetch_analyst_data(ticker)
            if adata:
                analyst_consensus = adata.get("consensus", "N/A")
                analyst_target = adata.get("price_target_avg", 0)
                if analyst_target > 0 and live_price > 0:
                    analyst_upside = round(((analyst_target - live_price) / live_price) * 100, 1)
        except Exception:
            pass

    # 7. Compute signal
    rsi2 = tech.get("rsi2", -1)
    above_sma50 = tech.get("above_sma50", True)
    regime = tech.get("regime", "")
    # Use 21-day WR from _get_technicals (matches scanner)
    wr = tech.get("win_rate", 0)
    avg_ret = tech.get("avg_return", 0)
    exit_zr = tech.get("exit_zone_return", 0)
    exit_zwr = tech.get("exit_zone_wr", 0)
    exit_zt = tech.get("exit_zone_trades", 0)

    # Build issues and signal
    issues = []
    if not above_sma50:
        issues.append("Below SMA50 - broken uptrend")
    if regime == "BEAR":
        issues.append("BEAR regime")
    if wr < MIN_WR:
        issues.append(f"Low WR ({wr:.1f}% < {MIN_WR}%)")
    if earnings_date:
        issues.append(f"Earnings on {earnings_date}")
    if sentiment_label == "NEGATIVE":
        issues.append(f"Negative sentiment ({sentiment_score:.2f})")
    if analyst_target > 0 and live_price > analyst_target:
        issues.append(f"Overvalued (${live_price:.0f} > target ${analyst_target:.0f})")
    if exit_zt >= 5 and exit_zr < 1.0 and exit_zwr < 55:
        issues.append(f"Weak zone return (+{exit_zr:.1f}%, {exit_zwr:.0f}% WR)")

    # Check if this ticker is a current holding → apply hybrid exit strategy
    exit_strategy_info = {}
    former_holding_info = {}
    try:
        import sqlite3
        _pos_db = os.path.join(os.path.dirname(__file__), "data", "positions.db")
        conn = sqlite3.connect(_pos_db)

        # Check current open position
        row = conn.execute("SELECT shares, entry_price, entry_date FROM positions WHERE ticker=? AND status='OPEN'", (ticker,)).fetchone()
        if row:
            # Held position: check hybrid exit
            pos_shares, pos_entry_price, pos_entry_date = row[0], row[1], row[2] or ""
            df_hist = _cache.get(ticker, 365)
            if df_hist is not None and len(df_hist) >= 50:
                closes_list = df_hist["Close"].dropna().tolist()
                bt_data = _backtest_7day(ticker)
                best_exit = _select_best_exit(ticker, closes_list, bt_data.get("trades", 0) if bt_data else 0, rsi2)
                if best_exit:
                    triggered = _evaluate_exit_trigger(
                        best_exit, closes_list, rsi2, live_price,
                        entry_price=pos_entry_price, entry_date=pos_entry_date,
                    )
                    exit_strategy_info = {
                        "exit_strategy": best_exit.get("strategy", ""),
                        "exit_strategy_wr": best_exit.get("wr", 0),
                        "exit_strategy_ret": best_exit.get("avg_ret", 0),
                        "exit_strategy_hold": best_exit.get("hold_days", 0),
                        "exit_triggered": triggered.get("triggered", False),
                        "exit_price": triggered.get("exit_price", 0),
                        "exit_label": triggered.get("label", ""),
                        "entry_price": pos_entry_price,
                        "shares": pos_shares,
                    }
                    if triggered.get("triggered", False):
                        issues.append(f"Exit triggered ({best_exit.get('strategy', '')}: {triggered.get('label', '')})")
        else:
            # Check if this is a FORMER holding — learn from past trades
            closed_row = conn.execute("""
                SELECT entry_price, exit_price, exit_date, entry_date, shares
                FROM positions
                WHERE ticker=? AND status='CLOSED' AND exit_price > 0
                ORDER BY exit_date DESC LIMIT 1
            """, (ticker,)).fetchone()
            if closed_row:
                ex_entry, ex_exit, ex_date, en_date, ex_shares = closed_row
                exit_pnl_pct = ((ex_exit - ex_entry) / ex_entry * 100) if ex_entry > 0 else 0
                post_exit_pnl_pct = ((live_price - ex_exit) / ex_exit * 100) if ex_exit > 0 else 0
                # Was it a mistake to exit?
                mistake = post_exit_pnl_pct > 5  # Stock rose 5%+ after we sold
                former_holding_info = {
                    "was_held": True,
                    "entry_price": ex_entry,
                    "exit_price": ex_exit,
                    "exit_date": ex_date,
                    "entry_date": en_date,
                    "exit_pnl_pct": round(exit_pnl_pct, 1),
                    "post_exit_pnl_pct": round(post_exit_pnl_pct, 1),
                    "missed_gain_per_share": round(live_price - ex_exit, 2),
                    "missed_gain_total": round((live_price - ex_exit) * ex_shares, 2),
                    "mistake": mistake,
                }
                if mistake:
                    issues.insert(0, f"FORMER HOLDING: Sold at ${ex_exit:.2f} on {ex_date}, now ${live_price:.2f} (+{post_exit_pnl_pct:.1f}% missed). Exit was premature.")
                elif post_exit_pnl_pct < -5:
                    issues.insert(0, f"FORMER HOLDING: Good exit at ${ex_exit:.2f} on {ex_date}, now ${live_price:.2f} ({post_exit_pnl_pct:+.1f}%). Exit was correct.")
                else:
                    issues.insert(0, f"FORMER HOLDING: Sold at ${ex_exit:.2f} on {ex_date}, now ${live_price:.2f} ({post_exit_pnl_pct:+.1f}%).")

        conn.close()
    except Exception as e:
        print(f"[Analyze] Position check error for {ticker}: {e}")

    # Determine action
    has_critical = any(k in str(issues) for k in ["Below SMA50", "BEAR", "Low WR"])
    if has_critical and not above_sma50 and regime == "BEAR":
        signal = "AVOID"
    elif has_critical:
        signal = "CAUTION"
    elif earnings_date:
        signal = "WAIT"
    elif sentiment_label == "NEGATIVE":
        signal = "WAIT"
    elif exit_strategy_info.get("exit_triggered", False):
        # Held position with exit triggered — check RSI override
        exit_strat_ret = exit_strategy_info.get("exit_strategy_ret", 0)
        zone_ret = tech.get("zone_return", 0)
        zone_trades = tech.get("zone_trades", 0)
        if rsi2 < 10 and zone_trades >= 5 and zone_ret > exit_strat_ret:
            signal = "HOLD"
            issues.append(f"Exit suppressed: RSI oversold ({rsi2:.0f}), zone +{zone_ret:.1f}% > exit +{exit_strat_ret:.1f}%")
        else:
            signal = "EXIT"
    elif rsi2 < 10 and above_sma50 and regime != "BEAR" and wr >= MIN_WR:
        signal = "BUY"
    elif exit_zt >= 5 and exit_zr < 1.0 and exit_zwr < MIN_WR:
        signal = "ROTATION"
    else:
        signal = "HOLD"

    # V2.4: Use regime-based exit targets
    entry_est = live_price  # Use live as reference
    stop_pct, tgt1_pct, tgt2_pct = _exit_targets_by_regime(regime)
    stop_loss = round(entry_est * (1 + stop_pct / 100), 2)
    target_1 = round(entry_est * (1 + tgt1_pct / 100), 2)
    target_2 = round(entry_est * (1 + tgt2_pct / 100), 2)

    # Score = zone_return × zone_WR / 100 (what matters at CURRENT RSI)
    # Prefer exit_zone data (more trades, includes all bars in zone, not just RSI<10 entries)
    # Fall back to entry-zone, then overall stats
    if exit_zt >= 5 and exit_zwr > 0:
        score = round(exit_zr * exit_zwr / 100, 2)
    elif tech.get("zone_trades", 0) >= 5 and tech.get("zone_wr", 0) > 0:
        score = round(tech.get("zone_return", 0) * tech.get("zone_wr", 0) / 100, 2)
    else:
        score = round(avg_ret * wr / 100, 2) if wr > 0 else 0

    # 8. Optimal entry prices — backtest zone returns at RSI 0-5, 5-10, 10-20
    optimal_entries = _calc_optimal_entries(ticker, live_price)

    return {
        "ticker": ticker,
        "live_price": round(live_price, 2),
        "day_change_pct": round(day_chg, 2),
        "rsi2": tech.get("rsi2", -1),
        "rsi14": tech.get("rsi14", -1),
        "sma50": tech.get("sma50", 0),
        "above_sma50": above_sma50,
        "regime": regime,
        "tier": tech.get("tier", "NONE"),
        "win_rate": round(wr, 1),
        "total_trades": tech.get("total_trades", 0),  # Use 21-day backtest count (matches WR/avg_ret)
        "avg_return": round(avg_ret, 2),
        "exit_zone_return": round(exit_zr, 2),
        "exit_zone_wr": round(exit_zwr, 1),
        "exit_zone_trades": exit_zt,
        "rsi_zone": tech.get("rsi_zone", ""),
        "score": score,
        "sentiment_label": sentiment_label,
        "sentiment_score": round(sentiment_score, 2),
        "headlines": headlines,
        "analyst_consensus": analyst_consensus,
        "analyst_target": round(analyst_target, 2),
        "analyst_upside": analyst_upside,
        "earnings_date": earnings_date,
        "signal": signal,
        "issues": issues,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "sparkline": tech.get("sparkline", []),
        "optimal_entries": optimal_entries,
        "former_holding": former_holding_info if former_holding_info else None,
    }


# ── Chart Data Endpoint ──

@router.get("/chart/{ticker}")
async def get_chart_data(ticker: str, days: int = 90):
    """Return OHLCV candles + SMA50 line + buy/sell signal markers for charting."""
    ticker = ticker.upper()
    days = min(days, 365)

    df = _cache.get(ticker, days)
    if df is None or len(df) < 20:
        raise HTTPException(status_code=404, detail=f"No chart data for {ticker}")

    closes = df["Close"].tolist()
    highs = df["High"].tolist() if "High" in df.columns else closes
    lows = df["Low"].tolist() if "Low" in df.columns else closes
    opens = df["Open"].tolist() if "Open" in df.columns else closes
    volumes = df["Volume"].tolist() if "Volume" in df.columns else [0] * len(closes)
    dates = [d.strftime("%Y-%m-%d") for d in df.index]

    # SMA50 line
    sma50_values = []
    for i in range(len(closes)):
        if i >= 49:
            sma50_values.append(round(sum(closes[i-49:i+1]) / 50, 2))
        else:
            sma50_values.append(None)

    # Buy signals: RSI(2) < 10 and price > SMA50 (V2.4)
    signals = []
    for i in range(50, len(closes)):
        hist_closes = closes[:i + 1]
        rsi2 = _entry.calc_rsi(hist_closes, 2)
        sma = sum(closes[i-49:i+1]) / 50
        if rsi2 < 10 and closes[i] > sma:
            signals.append({"date": dates[i], "type": "BUY", "price": round(closes[i], 2), "rsi": round(rsi2, 1)})
        elif rsi2 > 80:
            signals.append({"date": dates[i], "type": "OVERBOUGHT", "price": round(closes[i], 2), "rsi": round(rsi2, 1)})

    # Current position info
    pos = None
    open_positions = _position_mgr._get_open_positions_sync()
    for p in open_positions:
        if p["ticker"] == ticker:
            pos = {"entry_price": p["entry_price"], "entry_date": p.get("entry_date", ""), "shares": p["shares"]}
            break

    # Build candles array
    candles = []
    for i in range(len(dates)):
        candles.append({
            "date": dates[i],
            "open": round(opens[i], 2),
            "high": round(highs[i], 2),
            "low": round(lows[i], 2),
            "close": round(closes[i], 2),
            "volume": int(volumes[i]),
            "sma50": sma50_values[i],
        })

    return {
        "ticker": ticker,
        "candles": candles,
        "signals": signals,
        "position": pos,
    }


# ── Email Alert Settings ──

@router.get("/alerts/config")
async def get_alert_config():
    """Get email alert configuration (password redacted)."""
    from email_alerts import load_config
    cfg = load_config()
    # Redact password for frontend
    redacted = {**cfg}
    if redacted.get("smtp_password"):
        redacted["smtp_password"] = "••••••••"
    return redacted


@router.post("/alerts/config")
async def update_alert_config(config: Dict):
    """Update email alert configuration."""
    from email_alerts import load_config, save_config
    current = load_config()
    # Don't overwrite password if redacted placeholder sent
    if config.get("smtp_password") == "••••••••":
        config["smtp_password"] = current.get("smtp_password", "")
    updated = {**current, **config}
    save_config(updated)
    return {"success": True, "message": "Alert config saved"}


@router.post("/alerts/test")
async def test_alert_email():
    """Send a test email to verify configuration."""
    from email_alerts import send_test_email
    ok = await send_test_email()
    if ok:
        return {"success": True, "message": "Test email sent"}
    raise HTTPException(status_code=500, detail="Failed to send test email. Check SMTP config.")



@router.post("/alerts/send-report")
async def send_report():
    """Send portfolio report with all holdings, BUY signals, and upgrades."""
    from email_alerts import send_portfolio_report

    # Get current portfolio positions
    portfolio = await get_portfolio()
    positions = [p.dict() if hasattr(p, 'dict') else p for p in portfolio.positions]

    # BUY signals = positions with BUY signal + scanner opportunities with good scores
    buy_signals = []
    for p in positions:
        if p.get("signal") == "BUY":
            buy_signals.append({
                "ticker": p["ticker"], "price": p.get("current_price", 0),
                "win_rate": p.get("win_rate", 0), "zone_return": p.get("zone_return", 0),
                "score": round(p.get("avg_return", 0) * p.get("win_rate", 0) / 100, 2),
                "reason": "Portfolio holding - BUY signal active",
            })

    # Add scanner BUY opportunities (non-vetoed, score > 3)
    if _scan_cache:
        for o in _scan_cache.get("opportunities", []):
            if not o.get("vetoed") and o.get("score", 0) >= 3:
                buy_signals.append({
                    "ticker": o["ticker"], "price": o.get("price", 0),
                    "win_rate": o.get("win_rate", 0), "zone_return": o.get("zone_return", 0),
                    "score": o.get("score", 0),
                    "reason": f"Scanner: {o.get('regime', '')} regime, {o.get('trades', 0)} trades",
                })

    # Upgrades
    upgrades = []
    if _scan_cache:
        upgrades = [
            {"ticker": o["ticker"], "beats": o.get("beats_holdings", []),
             "score": o.get("score", 0), "win_rate": o.get("win_rate", 0),
             "zone_return": o.get("zone_return", 0)}
            for o in _scan_cache.get("opportunities", [])
            if o.get("is_upgrade") and not o.get("vetoed")
        ]

    ok = await send_portfolio_report(positions, buy_signals, upgrades)
    if ok:
        return {"success": True, "message": "Report sent", "positions": len(positions),
                "buy_signals": len(buy_signals), "upgrades": len(upgrades)}
    raise HTTPException(status_code=500, detail="Failed to send report. Check alert config.")


# ── Cache Stats ──

@router.get("/cache/stats")
async def get_cache_stats():
    """Get data cache statistics."""
    stats = _cache.stats()
    stale = _cache.get_stale_tickers()
    return CacheStats(
        total_tickers=stats.get("tickers", 0),
        total_rows=stats.get("rows", 0),
        last_updated=stats.get("last_updated", ""),
        stale_count=len(stale) if stale else 0,
    )


# ── Price Levels Endpoint ──

@router.get("/portfolio/levels")
async def get_price_levels():
    """Get stop loss and target prices for all positions."""
    positions = _position_mgr._get_open_positions_sync()
    if not positions:
        return {"levels": []}

    # Fetch all quotes in parallel instead of sequentially
    async with aiohttp.ClientSession() as session:
        async def _fetch_quote(pos):
            ticker = pos["ticker"]
            quote = await _get_finnhub_quote(session, ticker)
            return ticker, quote
        quote_tasks = [_fetch_quote(pos) for pos in positions]
        quote_results = await asyncio.gather(*quote_tasks, return_exceptions=True)

    quotes = {}
    for result in quote_results:
        if isinstance(result, tuple):
            quotes[result[0]] = result[1]

    levels = []
    for pos in positions:
        ticker = pos["ticker"]
        entry = pos["entry_price"]
        quote = quotes.get(ticker)
        price = quote["price"] if quote else entry

        tech = _technicals_cache.get(ticker)
        regime = tech.get("regime", "BULL") if tech else "BULL"
        stop_pct, t1_pct, t2_pct = _exit_targets_by_regime(regime)

        levels.append({
            "ticker": ticker,
            "entry_price": entry,
            "current_price": round(price, 2),
            "regime": regime,
            "stop_loss": round(entry * (1 + stop_pct / 100), 2),
            "target_1": round(entry * (1 + t1_pct / 100), 2),
            "target_2": round(entry * (1 + t2_pct / 100), 2),
            "stop_pct": stop_pct,
            "target_1_pct": t1_pct,
            "target_2_pct": t2_pct,
            "pnl_pct": round((price - entry) / entry * 100, 2),
            "stop_triggered": price <= entry * (1 + stop_pct / 100),
            "target_1_hit": price >= entry * (1 + t1_pct / 100),
            "target_2_hit": price >= entry * (1 + t2_pct / 100),
        })

    return {"levels": levels, "timestamp": datetime.now().isoformat()}


# ── WebSocket for alerts ──

@router.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    """WebSocket endpoint for real-time portfolio alerts."""
    await websocket.accept()
    _ws_connections.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        if websocket in _ws_connections:
            _ws_connections.remove(websocket)


async def _broadcast_alert(alert: Dict):
    """Broadcast alert to all connected WebSocket clients."""
    disconnected = []
    for ws in _ws_connections:
        try:
            await ws.send_json(alert)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in _ws_connections:
            _ws_connections.remove(ws)


# ── Background Monitor ──

# Track previously sent alerts to avoid duplicates (persisted to disk)
_DEDUP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "alert_dedup.json")

def _load_dedup() -> dict:
    """Load dedup state from disk. Resets if date changed."""
    try:
        with open(_DEDUP_FILE, "r") as f:
            state = json.load(f)
        if state.get("date") != datetime.now().strftime("%Y-%m-%d"):
            return {"date": datetime.now().strftime("%Y-%m-%d"), "signals": {}, "health": [], "upgrades": [], "price_alerts": {}}
        return state
    except Exception:
        return {"date": datetime.now().strftime("%Y-%m-%d"), "signals": {}, "health": [], "upgrades": [], "price_alerts": {}}

def _save_dedup(state: dict):
    """Persist dedup state to disk."""
    try:
        os.makedirs(os.path.dirname(_DEDUP_FILE), exist_ok=True)
        state["date"] = datetime.now().strftime("%Y-%m-%d")
        with open(_DEDUP_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"[Dedup] Failed to save: {e}")

_dedup = _load_dedup()

async def background_monitor():
    """Runs every 15 minutes: health check + email alerts only on CHANGES (persisted to disk)."""
    global _dedup
    await asyncio.sleep(120 if _is_prod else 60)  # Production: wait longer for worker stability
    while True:
        try:
            # Reload dedup state (resets daily)
            _dedup = _load_dedup()

            print(f"\n[Monitor] Running health check at {datetime.now().strftime('%H:%M')}")
            try:
                health = await asyncio.wait_for(_run_health_check(), timeout=90 if _is_prod else 300)
            except asyncio.TimeoutError:
                print("[Monitor] Health check timed out, continuing to exit trigger check")
                health = {}  # Don't skip exit checks just because health timed out

            # Broadcast critical alerts via WebSocket
            if health.get("has_critical"):
                for alert in health.get("alerts", []):
                    if alert.get("severity") == "CRITICAL":
                        await _broadcast_alert({
                            "type": "health_alert",
                            "severity": "CRITICAL",
                            "data": alert,
                            "timestamp": datetime.now().isoformat(),
                        })

            # Check exit strategy triggers on all positions
            try:
                from email_alerts import send_exit_trigger_alert
                sent_exits = set(_dedup.get("exit_triggers", []))
                exit_triggers = []

                for pos in _position_mgr._get_open_positions_sync():
                    ticker = pos["ticker"]
                    tech = _technicals_cache.get(ticker)
                    if not tech:
                        continue

                    if tech.get("exit_triggered") and ticker not in sent_exits:
                        quote = _price_cache.get(ticker)
                        live_price = quote["price"] if quote else 0
                        if not live_price:
                            # Fallback: use latest close from cache
                            _df = _cache.get(ticker, 30)
                            live_price = float(_df['Close'].iloc[-1]) if _df is not None and len(_df) > 0 else tech.get("sma50", 0)
                        entry = pos["entry_price"]
                        pnl_pct = (live_price - entry) / entry * 100 if entry > 0 else 0

                        exit_triggers.append({
                            "ticker": ticker,
                            "strategy": tech.get("exit_strategy", "?"),
                            "price": live_price,
                            "entry_price": entry,
                            "pnl_pct": pnl_pct,
                            "oos_wr": tech.get("exit_strategy_oos_wr", 0),
                            "is_wr": tech.get("exit_strategy_is_wr", 0),
                            "overfit": tech.get("exit_strategy_overfitting", 0),
                            "validation": tech.get("exit_strategy_validation", ""),
                            "ci_lo": tech.get("exit_strategy_oos_ci_lo", 0),
                            "ci_hi": tech.get("exit_strategy_oos_ci_hi", 0),
                            "label": tech.get("exit_label", ""),
                        })
                        sent_exits.add(ticker)

                if exit_triggers:
                    await send_exit_trigger_alert(exit_triggers)
                    print(f"[Monitor] Exit triggers: {', '.join(t['ticker'] for t in exit_triggers)}")
                    # Broadcast via WebSocket too
                    for t in exit_triggers:
                        await _broadcast_alert({
                            "type": "exit_trigger",
                            "ticker": t["ticker"],
                            "strategy": t["strategy"],
                            "price": t["price"],
                            "pnl_pct": t["pnl_pct"],
                            "validation": t["validation"],
                            "timestamp": datetime.now().isoformat(),
                        })

                _dedup["exit_triggers"] = list(sent_exits)
            except Exception as e:
                print(f"[Monitor] Exit trigger check error: {e}")

            # Email alerts — only send on CHANGES (deduped + persisted)
            try:
                from email_alerts import send_health_alert, send_signal_alert, send_upgrade_alert

                sent_health = set(_dedup.get("health", []))
                sent_signals = _dedup.get("signals", {})
                sent_upgrades = set(_dedup.get("upgrades", []))

                # Health alerts: only send when signal CHANGES (keyed by ticker-signal)
                if health.get("alerts"):
                    new_health = [a for a in health["alerts"]
                                  if f"{a.get('ticker','')}-{a.get('signal','')}" not in sent_health]
                    if new_health:
                        await send_health_alert(new_health)
                        for a in new_health:
                            sent_health.add(f"{a.get('ticker','')}-{a.get('signal','')}")

                # Signal alerts: only send when signal CHANGES for a ticker
                new_signals = []
                current_signals = {}
                for pos in health.get("positions", []):
                    ticker = pos.get("ticker", "?")
                    signal = pos.get("signal", "HOLD")
                    current_signals[ticker] = signal
                    if signal in ("SELL", "ROTATION", "CAUTION", "CRASH", "SELL BEFORE EARNINGS"):
                        prev = sent_signals.get(ticker)
                        if prev != signal:
                            new_signals.append({
                                "ticker": ticker,
                                "action": signal,
                                "price": pos.get("live", 0),
                                "reason": "; ".join(pos.get("issues", [])),
                            })
                if new_signals:
                    await send_signal_alert(new_signals)

                # Upgrade alerts: only send new upgrade tickers
                if _scan_cache:
                    upgrades = [
                        {"ticker": o["ticker"], "beats": o.get("beats_holdings", []),
                         "score": o.get("score", 0), "win_rate": o.get("win_rate", 0),
                         "zone_return": o.get("zone_return", 0)}
                        for o in _scan_cache.get("opportunities", [])
                        if o.get("is_upgrade") and not o.get("vetoed")
                        and o["ticker"] not in sent_upgrades
                    ]
                    if upgrades:
                        await send_upgrade_alert(upgrades)
                        for u in upgrades:
                            sent_upgrades.add(u["ticker"])

                # Persist dedup state to disk
                _dedup["health"] = list(sent_health)
                _dedup["signals"] = current_signals
                _dedup["upgrades"] = list(sent_upgrades)
                _save_dedup(_dedup)

            except Exception as e:
                print(f"[Monitor] Email alert error: {e}")

            print(f"[Monitor] Health check complete: {health.get('alerts_count', 0)} alerts")
        except Exception as e:
            print(f"[Monitor] Error: {e}")

        await asyncio.sleep(900)  # 15 minutes


# ── Price Level Monitor (Stop Loss / Target) ──

async def price_level_monitor():
    """Check live prices against stop loss and target levels every 60s. Email on breach. Dedup persisted."""
    global _dedup
    await asyncio.sleep(45)  # Wait for startup + warmup
    print("[PriceMonitor] Started - checking stops/targets every 60s")

    while True:
        try:
            _dedup = _load_dedup()
            price_alerts = _dedup.get("price_alerts", {})

            positions = _position_mgr._get_open_positions_sync()
            if not positions:
                await asyncio.sleep(60)
                continue

            triggered = []
            for pos in positions:
                ticker = pos["ticker"]
                entry = pos["entry_price"]
                shares = pos["shares"]

                # Read from centralized quote cache — NO direct Finnhub calls
                quote = _price_cache.get(ticker)
                if not quote:
                    continue
                price = quote["price"]
                if price <= 0:
                    continue

                tech = _technicals_cache.get(ticker)
                regime = tech.get("regime", "BULL") if tech else "BULL"
                stop_pct, t1_pct, t2_pct = _exit_targets_by_regime(regime)

                stop_price = entry * (1 + stop_pct / 100)
                target_1 = entry * (1 + t1_pct / 100)
                target_2 = entry * (1 + t2_pct / 100)
                pnl_pct = (price - entry) / entry * 100

                prev_alert = price_alerts.get(ticker)

                if price <= stop_price and prev_alert != "STOP_LOSS":
                    triggered.append({
                        "ticker": ticker, "alert_type": "STOP_LOSS",
                        "price": price, "level": stop_price,
                        "entry_price": entry, "pnl_pct": pnl_pct, "shares": shares,
                    })
                    price_alerts[ticker] = "STOP_LOSS"
                elif price >= target_2 and prev_alert != "TARGET_2":
                    triggered.append({
                        "ticker": ticker, "alert_type": "TARGET_2",
                        "price": price, "level": target_2,
                        "entry_price": entry, "pnl_pct": pnl_pct, "shares": shares,
                    })
                    price_alerts[ticker] = "TARGET_2"
                elif price >= target_1 and prev_alert not in ("TARGET_1", "TARGET_2"):
                    triggered.append({
                        "ticker": ticker, "alert_type": "TARGET_1",
                        "price": price, "level": target_1,
                        "entry_price": entry, "pnl_pct": pnl_pct, "shares": shares,
                    })
                    price_alerts[ticker] = "TARGET_1"

            # Persist price alert dedup
            _dedup["price_alerts"] = price_alerts
            _save_dedup(_dedup)

            if triggered:
                try:
                    from email_alerts import send_price_level_alert
                    await send_price_level_alert(triggered)
                    for t in triggered:
                        print(f"[PriceMonitor] {t['alert_type']} {t['ticker']} @ ${t['price']:.2f} (level ${t['level']:.2f})")
                    # Broadcast via WebSocket too
                    for t in triggered:
                        await _broadcast_alert({
                            "type": "price_level_alert",
                            "alert_type": t["alert_type"],
                            "ticker": t["ticker"],
                            "price": t["price"],
                            "level": t["level"],
                            "pnl_pct": t["pnl_pct"],
                            "timestamp": datetime.now().isoformat(),
                        })
                except Exception as e:
                    print(f"[PriceMonitor] Alert error: {e}")

        except Exception as e:
            print(f"[PriceMonitor] Error: {e}")

        await asyncio.sleep(60)  # Check every 60 seconds


def _warmup_one_position(pos: dict):
    """Sync helper: compute technicals for one position. Runs in thread pool."""
    ticker = pos["ticker"]
    try:
        tech = _get_technicals(ticker, entry_price=pos.get("entry_price", 0), entry_date=pos.get("entry_date", ""))
        return ticker, tech, None
    except Exception as e:
        return ticker, None, str(e)


async def warmup_signal_cache():
    """Pre-cache signals + prices from SQLite at startup. NO API calls.
    Heavy backtesting runs in thread pool so event loop stays responsive.
    Live quotes come from quote_refresh_loop() which starts shortly after."""
    await asyncio.sleep(1)  # Brief wait for app readiness
    positions = _position_mgr._get_open_positions_sync()
    if not positions:
        return

    # Phase 1: Seed prices from SQLite immediately (fast, non-blocking)
    print(f"[Warmup] Phase 1: Seeding prices for {len(positions)} positions from SQLite...")
    for pos in positions:
        ticker = pos["ticker"]
        if ticker not in _price_cache:
            try:
                import sqlite3 as _sql3
                _cdb = _sql3.connect(os.path.join(os.path.dirname(__file__), "data", "stock_cache.db"))
                _rows = _cdb.execute(
                    "SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 2",
                    (ticker.upper(),)
                ).fetchall()
                _cdb.close()
                if len(_rows) >= 2:
                    close, prev = _rows[0][0], _rows[1][0]
                    _price_cache[ticker] = {
                        "price": close,
                        "prev_close": prev,
                        "day_chg": round(((close - prev) / prev) * 100, 2) if prev > 0 else 0,
                    }
                    _quote_cache[ticker] = (_price_cache[ticker], datetime.now())
            except Exception:
                pass
        # Set default HOLD signal so portfolio endpoint works immediately
        _signal_cache[ticker] = ("HOLD", [], datetime.now())
    print(f"[Warmup] Phase 1 done — API ready with cached prices")

    # Phase 2: Delegated to technicals_refresh_loop() background task.
    # That task runs _get_technicals() in a worker thread (asyncio.to_thread) so the event loop
    # stays responsive. Portfolio endpoint reads from _technicals_cache instead of computing.
    print("[Warmup] Phase 2 delegated to technicals_refresh_loop background task")


async def technicals_refresh_loop():
    """Background loop: compute _get_technicals() for each portfolio position in a worker thread.
    Results cached in _technicals_cache. Portfolio/monitor endpoints read from cache — NEVER block event loop.
    Follows the same pattern as quote_refresh_loop for prices."""
    global _technicals_computing
    await asyncio.sleep(3)  # Wait for warmup Phase 1 to seed prices
    print("[TechRefresh] Started — computing technicals in background thread")

    while True:
        try:
            positions = _position_mgr._get_open_positions_sync()
            if not positions:
                await asyncio.sleep(60)
                continue

            # Evict stale entries (positions that closed or unknown tickers)
            open_tickers = set(p["ticker"] for p in positions) if positions else set()
            stale = [t for t in _technicals_cache if t not in open_tickers]
            for t in stale:
                del _technicals_cache[t]

            _technicals_computing = True
            for pos in positions:
                ticker = pos["ticker"]
                entry_price = pos.get("entry_price", 0)
                entry_date = pos.get("entry_date", "")
                try:
                    # Run CPU-heavy backtest in worker thread — event loop stays free
                    tech = await asyncio.to_thread(
                        _get_technicals, ticker, entry_price, entry_date
                    )
                    if tech:
                        _technicals_cache[ticker] = tech
                except Exception as e:
                    print(f"[TechRefresh] Error for {ticker}: {e}")

                # Yield between positions so event loop can process HTTP requests
                await asyncio.sleep(0.1)

            _technicals_computing = False
            cached_tickers = list(_technicals_cache.keys())
            print(f"[TechRefresh] Cached technicals for {len(cached_tickers)} positions: {cached_tickers}")

        except Exception as e:
            _technicals_computing = False
            print(f"[TechRefresh] Loop error: {e}")

        await asyncio.sleep(300)  # Refresh every 5 minutes


async def quote_refresh_loop():
    """Centralized quote refresher. Fetches position quotes every 60s.
    All other code reads from _quote_cache instead of hitting Finnhub directly.
    This is the ONLY recurring Finnhub caller — conserves rate limit."""
    await asyncio.sleep(3)  # Brief wait for warmup Phase 1 to seed SQLite prices
    print("[QuoteRefresh] Started — refreshing position quotes every 60s")

    while True:
        try:
            positions = _position_mgr._get_open_positions_sync()
            if not positions:
                await asyncio.sleep(60)
                continue

            async with aiohttp.ClientSession() as session:
                for pos in positions:
                    ticker = pos["ticker"]
                    if not _check_finnhub_rate():
                        print(f"[QuoteRefresh] Finnhub rate limit — skipping remaining")
                        break
                    quote = await _get_finnhub_quote(session, ticker)
                    if quote:
                        if quote.get("price", 0) <= 0:
                            # Finnhub returned stale/zero — use direct SQL (no pandas)
                            if ticker not in _price_cache:
                                try:
                                    import sqlite3 as _sql3
                                    _cdb = _sql3.connect(os.path.join(os.path.dirname(__file__), "data", "stock_cache.db"))
                                    _rows = _cdb.execute(
                                        "SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 2",
                                        (ticker.upper(),)
                                    ).fetchall()
                                    _cdb.close()
                                    if len(_rows) >= 2:
                                        close, prev = _rows[0][0], _rows[1][0]
                                        _price_cache[ticker] = {
                                            "price": close,
                                            "prev_close": prev,
                                            "day_chg": round(((close - prev) / prev) * 100, 2) if prev > 0 else 0,
                                        }
                                        _quote_cache[ticker] = (_price_cache[ticker], datetime.now())
                                except Exception:
                                    pass
                    await asyncio.sleep(1.5)  # ~40 calls/min with 5 tickers = conservative

            prices = {t: _price_cache.get(t, {}).get("price", 0) for t in [p["ticker"] for p in positions]}
            print(f"[QuoteRefresh] Updated: {prices} | API calls: {_finnhub_calls_this_minute}/min")

            # Limit price cache to 500 entries (prevent unbounded growth)
            if len(_price_cache) > 500:
                # Keep only tickers that are current positions or recent quotes
                keep = set(p["ticker"] for p in positions) if positions else set()
                _price_cache.update({t: v for t, v in list(_price_cache.items()) if t in keep})

        except Exception as e:
            print(f"[QuoteRefresh] Error: {e}")

        await asyncio.sleep(60)


async def extended_hours_refresh_loop():
    """Fetch pre-market/after-hours prices for portfolio positions via Finnhub.
    Runs every 120s during extended hours only. Clears cache during regular/closed hours."""
    await asyncio.sleep(20)  # Wait for other startup tasks
    print("[ExtHoursRefresh] Started — monitoring extended hours sessions")

    while True:
        try:
            session = _get_market_session()

            if session not in ("PRE_MARKET", "AFTER_HOURS"):
                # Clear ext cache during regular hours and closed
                if _extended_hours_cache:
                    _extended_hours_cache.clear()
                    print(f"[ExtHoursRefresh] Session={session}, cleared ext cache")
                await asyncio.sleep(120)
                continue

            positions = _position_mgr._get_open_positions_sync()
            if not positions:
                await asyncio.sleep(120)
                continue

            tickers = [p["ticker"] for p in positions]
            print(f"[ExtHoursRefresh] Session={session}, fetching {len(tickers)} tickers...")

            # Yahoo chart API — run one at a time with delay to avoid 429
            from concurrent.futures import ThreadPoolExecutor
            loop = asyncio.get_event_loop()
            results = []
            with ThreadPoolExecutor(max_workers=1) as pool:
                for t in tickers:
                    r = await loop.run_in_executor(pool, _fetch_extended_quote_sync, t)
                    results.append(r)
                    await asyncio.sleep(2)  # 2s between tickers to avoid rate limiting

            updated = 0
            for ticker, result in zip(tickers, results):
                if result:
                    _extended_hours_cache[ticker] = result
                    updated += 1

            if updated:
                prices = {t: f"${r['ext_price']:.2f} ({r['ext_change_pct']:+.2f}%)" for t, r in _extended_hours_cache.items()}
                print(f"[ExtHoursRefresh] Updated {updated}/{len(tickers)}: {prices}")
            else:
                print(f"[ExtHoursRefresh] Updated 0/{len(tickers)} ext quotes")

        except Exception as e:
            print(f"[ExtHoursRefresh] Error: {e}")

        await asyncio.sleep(120)


async def cache_refresh_loop():
    """Daily historical data refresh. Holdings first (fast), then scanner universe later.
    Keeps stock_cache.db up to date so scanner/backtest use fresh data."""
    global _scan_cache
    await asyncio.sleep(10)  # Brief wait for app startup

    first_run = True
    while True:
        try:
            positions = _position_mgr._get_open_positions_sync()
            holding_tickers = [p["ticker"] for p in positions] if positions else []

            if first_run:
                # FIRST RUN: Populate holdings with NO data, refresh stale ones
                # Cold cache (empty stock_cache.db) needs full 800-day history, not just 5 days
                empty_holdings = [t for t in holding_tickers if _cache.get(t, 365) is None]
                stale_holdings = [t for t in holding_tickers if t not in empty_holdings and not _cache.is_fresh(t)]

                if empty_holdings:
                    print(f"[CacheRefresh] Cold cache: populating {len(empty_holdings)} holdings with full history: {empty_holdings}")
                    result = await _cache.populate(empty_holdings, force=True)
                    print(f"[CacheRefresh] Populate done: {result.get('fetched', 0)} fetched")

                if stale_holdings:
                    print(f"[CacheRefresh] First run: refreshing {len(stale_holdings)} stale holdings...")
                    result = await _cache.refresh(stale_holdings)
                    print(f"[CacheRefresh] Holdings done: {result.get('refreshed', 0)} refreshed")
                    # Invalidate caches so portfolio picks up fresh data
                    _signal_cache.clear()
                    _exit_strategy_cache.clear()
                else:
                    print(f"[CacheRefresh] Holdings already fresh")
                first_run = False

                # Start populating full universe in background (don't block early)
                await asyncio.sleep(60)

                # POPULATE FULL UNIVERSE: Check how many are missing from cache
                from deep_scanner import STOCK_UNIVERSE
                cached_set = set(_cache.get_cached_tickers())
                uncached = [t for t in STOCK_UNIVERSE if t not in cached_set]
                if uncached:
                    print(f"[CacheRefresh] Universe population: {len(uncached)} stocks not in cache "
                          f"(out of {len(STOCK_UNIVERSE)} total). Populating in batches of 100...")
                    batch_size = 100
                    total_fetched = 0
                    for i in range(0, len(uncached), batch_size):
                        batch = uncached[i:i + batch_size]
                        result = await _cache.populate(batch)
                        batch_fetched = result.get('fetched', 0)
                        total_fetched += batch_fetched
                        print(f"[CacheRefresh] Batch {i//batch_size + 1}: "
                              f"{batch_fetched}/{len(batch)} fetched "
                              f"(total: {total_fetched}/{len(uncached)})")
                        # Brief pause between batches to not overwhelm APIs
                        await asyncio.sleep(5)
                    print(f"[CacheRefresh] Universe population complete: {total_fetched} new stocks cached")
                    # Clear scan cache so next scan uses full universe
                    _scan_cache = None
                else:
                    print(f"[CacheRefresh] Full universe already cached ({len(cached_set)} tickers)")
                continue

            # SUBSEQUENT RUNS: Full universe refresh + populate any new uncached stocks
            stale = _cache.get_stale_tickers()

            # Also check for any uncached universe stocks (new stocks added to universe file)
            from deep_scanner import STOCK_UNIVERSE
            cached_set = set(_cache.get_cached_tickers())
            uncached = [t for t in STOCK_UNIVERSE if t not in cached_set]
            if uncached:
                print(f"[CacheRefresh] {len(uncached)} new universe stocks to populate...")
                batch_size = 100
                for i in range(0, len(uncached), batch_size):
                    batch = uncached[i:i + batch_size]
                    await _cache.populate(batch)
                    await asyncio.sleep(5)

            if not stale and not uncached:
                print(f"[CacheRefresh] All {len(cached_set)} tickers up to date")
                await asyncio.sleep(14400)  # 4 hours
                continue

            if stale:
                print(f"[CacheRefresh] {len(stale)} stale tickers, refreshing...")

                priority = [t for t in holding_tickers if t in stale]
                rest = [t for t in stale if t not in priority]
                ordered = priority + rest

                result = await _cache.refresh(ordered)
                print(f"[CacheRefresh] Done: {result.get('refreshed', 0)} refreshed, "
                      f"{result.get('failed', 0)} failed")

            # Invalidate signal + exit strategy caches so next request uses fresh data
            _signal_cache.clear()
            _exit_strategy_cache.clear()

            # Clear scan cache — will be rebuilt with fresh data on next request
            _scan_cache = None

        except Exception as e:
            import traceback
            print(f"[CacheRefresh] Error: {e}")
            traceback.print_exc()

        await asyncio.sleep(14400)  # 4 hours
