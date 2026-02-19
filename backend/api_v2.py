"""
V2 API Router - Live Portfolio Dashboard
=========================================
Wraps portfolio_check.py, deep_scanner.py, and positions.py into REST endpoints.
Background monitor runs health checks every 15 minutes.
"""

import asyncio
import aiohttp
import json
import os
import sys
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schemas_v2 import (
    BuyRequest, SellRequest, TradeResult,
    PortfolioResponse, PortfolioSummary, PositionDetail,
    HealthCheckResponse, HealthIssue,
    ScanResponse, ScanOpportunity, HoldingScore,
    HistoryResponse, TransactionRecord,
    CacheStats,
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
QUOTE_CACHE_TTL = 30  # seconds
_finnhub_calls_this_minute: int = 0
_finnhub_minute_start: Optional[datetime] = None
FINNHUB_MAX_PER_MIN = 50  # Leave headroom from 60/min limit

# WebSocket connections for alerts
_ws_connections: List[WebSocket] = []


# ── Production Detection ──
_is_prod = bool(os.environ.get("FLY_APP_NAME"))

# ── Helpers ──

def _exit_targets_by_regime(regime: str) -> tuple:
    """Return (stop_pct, target_1_pct, target_2_pct) based on regime."""
    if regime == "BULL":
        return (-8.0, 10.0, 20.0)
    elif regime == "SIDEWAYS":
        return (-5.0, 5.0, 10.0)
    else:  # BEAR
        return (-4.0, 3.0, 6.0)


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


# ── Hybrid Exit Strategy Selector ──
# Backtests 6 exit strategies per stock, caches result for the day

_exit_strategy_cache: Dict[str, Dict] = {}  # ticker -> {strategy, wr, avg_ret, ...}

_EXIT_STRATEGIES = {
    "Fixed3d":  {"type": "fixed", "days": 3},
    "Fixed7d":  {"type": "fixed", "days": 7},
    "Fixed14d": {"type": "fixed", "days": 14},
    "Fixed21d": {"type": "fixed", "days": 21},
    "SMA5":     {"type": "sma", "period": 5},
    "SMA10":    {"type": "sma", "period": 10},
    "RSI50":    {"type": "rsi_exit", "threshold": 50},
    "RSI65":    {"type": "rsi_exit", "threshold": 65},
    "RSI80":    {"type": "rsi_exit", "threshold": 80},
    "RSI90":    {"type": "rsi_exit", "threshold": 90},
    "Stop8T10": {"type": "stop_target", "stop_pct": -8, "target_pct": 10},
    "Trail5":   {"type": "trailing", "trail_pct": 5},
}


def _backtest_exit_strategies(closes: list) -> Dict[str, Dict]:
    """Backtest all exit strategies on a stock. Returns {name: {trades, wr, avg_ret, avg_hold, annual}}."""
    results = {}
    for name, strat in _EXIT_STRATEGIES.items():
        trade_rets = []
        total_days = 0

        for i in range(50, len(closes) - 30):
            hist = closes[:i + 1]
            rsi2 = _entry.calc_rsi(hist, 2)
            sma50 = sum(hist[-50:]) / 50
            if rsi2 >= 20 or hist[-1] <= sma50:
                continue
            entry_price = closes[i]

            if strat["type"] == "fixed":
                hold = strat["days"]
                if i + hold < len(closes):
                    ret = (closes[i + hold] - entry_price) / entry_price * 100
                    trade_rets.append(ret)
                    total_days += hold

            elif strat["type"] == "sma":
                period = strat["period"]
                exited = False
                for d in range(1, 31):
                    if i + d >= len(closes):
                        break
                    start_idx = max(0, i + d - period + 1)
                    sma_slice = closes[start_idx:i + d + 1]
                    sma_val = sum(sma_slice) / len(sma_slice) if len(sma_slice) >= period else 0
                    if closes[i + d] > sma_val > 0:
                        ret = (closes[i + d] - entry_price) / entry_price * 100
                        trade_rets.append(ret)
                        total_days += d
                        exited = True
                        break
                if not exited and i + 30 < len(closes):
                    ret = (closes[i + 30] - entry_price) / entry_price * 100
                    trade_rets.append(ret)
                    total_days += 30

            elif strat["type"] == "rsi_exit":
                threshold = strat["threshold"]
                exited = False
                for d in range(1, 31):
                    if i + d >= len(closes):
                        break
                    rsi_now = _entry.calc_rsi(closes[:i + d + 1], 2)
                    if rsi_now > threshold:
                        ret = (closes[i + d] - entry_price) / entry_price * 100
                        trade_rets.append(ret)
                        total_days += d
                        exited = True
                        break
                if not exited and i + 30 < len(closes):
                    ret = (closes[i + 30] - entry_price) / entry_price * 100
                    trade_rets.append(ret)
                    total_days += 30

            elif strat["type"] == "stop_target":
                stop_pct = strat["stop_pct"]
                target_pct = strat["target_pct"]
                exited = False
                for d in range(1, 31):
                    if i + d >= len(closes):
                        break
                    ret_d = (closes[i + d] - entry_price) / entry_price * 100
                    if ret_d <= stop_pct or ret_d >= target_pct:
                        trade_rets.append(ret_d)
                        total_days += d
                        exited = True
                        break
                if not exited and i + 30 < len(closes):
                    ret = (closes[i + 30] - entry_price) / entry_price * 100
                    trade_rets.append(ret)
                    total_days += 30

            elif strat["type"] == "trailing":
                trail_pct = strat["trail_pct"]
                peak = entry_price
                exited = False
                for d in range(1, 31):
                    if i + d >= len(closes):
                        break
                    peak = max(peak, closes[i + d])
                    trail_stop = peak * (1 - trail_pct / 100)
                    if closes[i + d] <= trail_stop:
                        ret = (closes[i + d] - entry_price) / entry_price * 100
                        trade_rets.append(ret)
                        total_days += d
                        exited = True
                        break
                if not exited and i + 30 < len(closes):
                    ret = (closes[i + 30] - entry_price) / entry_price * 100
                    trade_rets.append(ret)
                    total_days += 30

        if len(trade_rets) >= 5:
            avg_ret = sum(trade_rets) / len(trade_rets)
            wr = sum(1 for r in trade_rets if r > 0) / len(trade_rets) * 100
            avg_hold = total_days / len(trade_rets)
            annual = avg_ret * (252 / avg_hold) if avg_hold > 0 else 0
            results[name] = {
                "trades": len(trade_rets), "wr": round(wr, 1),
                "avg_ret": round(avg_ret, 2), "avg_hold": round(avg_hold, 1),
                "annual": round(annual, 1),
            }
    return results


def _select_best_exit(ticker: str, closes: list, entry_trades: list, current_rsi: float) -> Dict:
    """Select the best exit strategy for a stock. Locked per position (stable across days)."""
    cache_key = ticker  # Stable key — strategy doesn't flip-flop daily
    current_price = closes[-1] if closes else 0

    # Check cache — strategy is locked once selected until app restart or explicit cache clear
    if cache_key in _exit_strategy_cache:
        cached = _exit_strategy_cache[cache_key]
        # Re-evaluate trigger with fresh price/RSI (trigger changes, strategy doesn't)
        return _evaluate_exit_trigger(cached, closes, current_rsi, current_price)

    # Backtest all strategies
    strat_results = _backtest_exit_strategies(closes)

    if not strat_results:
        result = {
            "strategy": "Fixed7d", "wr": 0, "avg_ret": 0, "avg_hold": 7,
            "triggered": False, "exit_price": 0, "exit_price_pct": 0,
            "label": "No data",
        }
        _exit_strategy_cache[cache_key] = result
        return result

    # Pick winner by risk-adjusted score (avg_ret × wr/100) — balances return and reliability
    best_name = max(strat_results, key=lambda n: strat_results[n]["avg_ret"] * strat_results[n]["wr"] / 100)
    best = strat_results[best_name]

    result = {
        "strategy": best_name, "wr": best["wr"],
        "avg_ret": best["avg_ret"], "avg_hold": best["avg_hold"],
        "all_strategies": strat_results,  # keep for debugging
    }
    _exit_strategy_cache[cache_key] = result

    return _evaluate_exit_trigger(result, closes, current_rsi, current_price)


def _evaluate_exit_trigger(cached: Dict, closes: list, current_rsi: float, current_price: float) -> Dict:
    """Check if exit condition is triggered RIGHT NOW for the selected strategy."""
    strategy = cached["strategy"]
    strat_def = _EXIT_STRATEGIES.get(strategy, {})
    triggered = False
    exit_price = 0.0

    if strat_def.get("type") == "sma":
        period = strat_def["period"]
        sma_val = sum(closes[-period:]) / period if len(closes) >= period else 0
        exit_price = round(sma_val, 2)
        triggered = current_price > sma_val > 0

    elif strat_def.get("type") == "rsi_exit":
        threshold = strat_def["threshold"]
        triggered = current_rsi > threshold
        # RSI exits are NOT price-based — don't show a dollar target (confuses users)
        # e.g. COHR "EXIT at $237" when price is $226 — user thinks it's a price target
        exit_price = 0  # No price target for RSI exits

    elif strat_def.get("type") == "fixed":
        # Fixed hold: can't determine exit price from technicals alone (need entry_date)
        # Show expected exit return instead
        exit_price = round(current_price * (1 + cached.get("avg_ret", 0) / 100), 2)
        triggered = False  # Determined by days held, checked in signal logic

    elif strat_def.get("type") == "stop_target":
        stop_price = round(current_price * (1 + strat_def["stop_pct"] / 100), 2)
        target_price = round(current_price * (1 + strat_def["target_pct"] / 100), 2)
        exit_price = target_price  # show target as the exit price
        triggered = False  # Would need entry price to know if stop/target hit

    elif strat_def.get("type") == "trailing":
        # Trailing stop: show the current trail level
        exit_price = round(current_price * (1 - strat_def["trail_pct"] / 100), 2)
        triggered = False  # Trail updates dynamically

    exit_price_pct = round((exit_price - current_price) / current_price * 100, 2) if current_price > 0 and exit_price > 0 else 0

    # Build label
    strat_name = strategy
    wr = cached.get("wr", 0)
    avg_ret = cached.get("avg_ret", 0)
    avg_hold = cached.get("avg_hold", 0)

    if strat_def.get("type") == "sma":
        label = f"SMA({strat_def['period']}) ${exit_price:.0f} | +{avg_ret:.1f}% WR {wr:.0f}% ~{avg_hold:.0f}d"
    elif strat_def.get("type") == "rsi_exit":
        threshold = strat_def['threshold']
        if triggered:
            label = f"RSI({current_rsi:.0f})>{threshold} | +{avg_ret:.1f}% WR {wr:.0f}% ~{avg_hold:.0f}d"
        else:
            label = f"RSI>{threshold} (now {current_rsi:.0f}) | +{avg_ret:.1f}% WR {wr:.0f}% ~{avg_hold:.0f}d"
    elif strat_def.get("type") == "stop_target":
        stop_pct = abs(strat_def['stop_pct'])
        target_pct = strat_def['target_pct']
        label = f"Stop -{stop_pct}% / Target +{target_pct}% | +{avg_ret:.1f}% WR {wr:.0f}% ~{avg_hold:.0f}d"
    elif strat_def.get("type") == "trailing":
        trail_pct = strat_def['trail_pct']
        label = f"Trail {trail_pct}% (${exit_price:.0f}) | +{avg_ret:.1f}% WR {wr:.0f}% ~{avg_hold:.0f}d"
    else:
        label = f"Hold {strat_def.get('days', 7)}d | +{avg_ret:.1f}% WR {wr:.0f}%"

    if triggered:
        label = "EXIT NOW: " + label

    return {
        "strategy": strat_name, "wr": wr, "avg_ret": avg_ret, "avg_hold": avg_hold,
        "triggered": triggered, "exit_price": exit_price, "exit_price_pct": exit_price_pct,
        "label": label,
    }


def _get_technicals(ticker: str) -> Dict:
    """Get RSI, SMA50, regime, backtest stats from cache."""
    df = _cache.get(ticker, 365)
    if df is None or len(df) < 60:
        return {}

    closes = df["Close"].dropna().tolist()
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

    # Backtest (14-day forward returns — backtested: 87.7% WR, +11.29% avg vs 7d 84%/+6.03%)
    trades = []
    for i in range(50, len(closes) - 14):
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        hist_sma = _entry.calc_sma(hist_closes, 50)
        if hist_rsi < 20 and hist_closes[-1] > hist_sma:
            ret = ((closes[i + 14] - closes[i]) / closes[i]) * 100
            trades.append({"return": ret, "win": ret > 0, "rsi": hist_rsi})

    wr = sum(1 for t in trades if t["win"]) / len(trades) * 100 if trades else 0
    avg_ret = sum(t["return"] for t in trades) / len(trades) if trades else 0

    # RSI zone (buy-signal trades only — for entry analysis)
    zone_low = min(int(rsi2 // 10) * 10, 90)  # Cap at 90 so zone 90-100 includes RSI=100
    zone_high = 101 if zone_low == 90 else zone_low + 10  # 101 to include RSI=100 exactly
    zone_trades = [t for t in trades if zone_low <= t["rsi"] < zone_high]
    zone_ret = sum(t["return"] for t in zone_trades) / len(zone_trades) if zone_trades else 0
    zone_wr = sum(1 for t in zone_trades if t["win"]) / len(zone_trades) * 100 if zone_trades else 0

    # Exit zone analysis: forward 14-day returns at CURRENT RSI zone using ALL data points
    # This answers: "When this stock was at RSI X historically, what was the 14-day forward return?"
    # Critical for exit decisions — the buy-zone trades above are empty for RSI > 20
    exit_zone_trades_list = []
    for i in range(50, len(closes) - 14):
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        if zone_low <= hist_rsi < zone_high:
            ret = ((closes[i + 14] - closes[i]) / closes[i]) * 100
            exit_zone_trades_list.append({"return": ret, "win": ret > 0})

    exit_zone_ret = sum(t["return"] for t in exit_zone_trades_list) / len(exit_zone_trades_list) if exit_zone_trades_list else 0
    exit_zone_wr = sum(1 for t in exit_zone_trades_list if t["win"]) / len(exit_zone_trades_list) * 100 if exit_zone_trades_list else 0

    # Hybrid exit strategy: backtest all strategies per-stock, pick the winner
    current_price = closes[-1]
    exit_result = _select_best_exit(ticker, closes, trades, rsi2)

    # Sparkline (last 20 closes)
    sparkline = [round(c, 2) for c in closes[-20:]]

    # SMA50 buffer — strongest predictor (20%+ = +9.29% avg vs 0-5% = +2.76%)
    sma50_buffer = ((closes[-1] - sma50) / sma50 * 100) if sma50 > 0 else 0

    # Tier classification (EXTREME > STRONG > STANDARD > NONE)
    above_sma50 = closes[-1] > sma50
    above_sma200 = closes[-1] > sma200 if sma200 > 0 else False
    is_extreme = rsi2 < 5 and above_sma200
    is_strong = rsi2 < 20 and above_sma50 and (rsi14 < 40 or vol_spike)
    is_standard = rsi2 < 20 and above_sma50
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
        "sparkline": sparkline,
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

    # Rule 3: Win rate check
    if wr < 55:
        issues.append(f"Low WR ({wr:.1f}%) - weak backtest")

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
        if exit_zone_ret < 1.0 and exit_zone_wr < 55:
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
        if rsi2 < 20 and zone_trades >= 5 and zone_ret > exit_strat_ret:
            signal = "HOLD"
            issues.append(f"Exit suppressed: RSI oversold ({rsi2:.0f}), zone +{zone_ret:.1f}% > exit +{exit_strat_ret:.1f}%")
        else:
            signal = "EXIT"
    elif rsi2 < 20 and above_sma50 and regime != "BEAR":
        signal = "BUY"
    elif rsi2 < 30 and above_sma50 and regime != "BEAR":
        signal = "BUY"  # Near buy zone
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

    # Fetch live quotes + compute real signals
    details = []
    async with aiohttp.ClientSession() as session:
        for pos in positions:
            ticker = pos["ticker"]
            shares = pos["shares"]
            entry_price = pos["entry_price"]
            cost = entry_price * shares

            # Live quote
            quote = await _get_finnhub_quote(session, ticker)
            live_price = quote["price"] if quote else entry_price
            day_chg = quote["day_chg"] if quote else 0
            value = live_price * shares
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost else 0

            # Technicals from cache
            tech = _get_technicals(ticker)

            # Re-evaluate exit trigger with LIVE price (cached uses stale historical close)
            if tech and tech.get("exit_strategy"):
                df = _cache.get(ticker, 365)
                if df is not None and len(df) >= 10:
                    closes_live = df["Close"].dropna().tolist()
                    rsi_live = tech.get("rsi2", -1)
                    live_exit = _evaluate_exit_trigger(
                        _exit_strategy_cache.get(ticker, tech),
                        closes_live, rsi_live, live_price
                    )
                    old_triggered = tech.get("exit_triggered", False)
                    tech["exit_triggered"] = live_exit["triggered"]
                    tech["exit_price"] = live_exit["exit_price"]
                    tech["exit_price_pct"] = live_exit["exit_price_pct"]
                    tech["exit_label"] = live_exit["label"]
                    # Invalidate signal cache if exit trigger state changed
                    if live_exit["triggered"] != old_triggered and ticker in _signal_cache:
                        del _signal_cache[ticker]

            # Real signal using ATLAS V2 rules + sentiment + analyst + earnings
            signal, issues = await _compute_signal(session, ticker, tech, live_price, day_chg)

            # Exit targets based on regime
            regime = tech.get("regime", "BULL")
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
                rsi2=tech.get("rsi2", -1),
                rsi14=tech.get("rsi14", -1),
                sma10=tech.get("sma10", 0),
                sma50=tech.get("sma50", 0),
                above_sma50=tech.get("above_sma50", True),
                sma50_buffer=tech.get("sma50_buffer", 0),
                above_sma10=live_price > tech.get("sma10", 0) if tech.get("sma10", 0) > 0 else False,
                regime=regime,
                # Tier must reflect live price reality, not stale cached RSI
                # If exit is triggered (stock bounced), tier is NONE
                tier="NONE" if tech.get("exit_triggered", False) else tech.get("tier", "NONE"),
                win_rate=tech.get("win_rate", 0),
                total_trades=tech.get("total_trades", 0),
                avg_return=tech.get("avg_return", 0),
                zone_return=tech.get("zone_return", 0),
                zone_wr=tech.get("zone_wr", 0),
                zone_trades=tech.get("zone_trades", 0),
                rsi_zone=tech.get("rsi_zone", ""),
                exit_zone_return=tech.get("exit_zone_return", 0),
                exit_zone_wr=tech.get("exit_zone_wr", 0),
                exit_zone_trades=tech.get("exit_zone_trades", 0),
                exit_strategy=tech.get("exit_strategy", ""),
                exit_strategy_wr=tech.get("exit_strategy_wr", 0),
                exit_strategy_ret=tech.get("exit_strategy_ret", 0),
                exit_strategy_hold=tech.get("exit_strategy_hold", 0),
                exit_triggered=tech.get("exit_triggered", False),
                exit_price=tech.get("exit_price", 0),
                exit_price_pct=tech.get("exit_price_pct", 0),
                exit_label=tech.get("exit_label", ""),
                sparkline=tech.get("sparkline", []),
                signal=signal,
                issues=issues,
                stop_loss=stop_price,
                target_1=target_1,
                target_2=target_2,
                stop_pct=stop_pct,
                target_1_pct=t1_pct,
                target_2_pct=t2_pct,
            )
            details.append(detail)
            await asyncio.sleep(0.3)  # Finnhub rate limit

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
    day_pnl_pct = (day_pnl / (total_value - day_pnl) * 100) if (total_value - day_pnl) > 0 else 0

    summary = PortfolioSummary(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl / total_cost * 100, 2) if total_cost else 0,
        day_pnl=round(day_pnl, 2),
        day_pnl_pct=round(day_pnl_pct, 2),
        position_count=len(details),
        avg_win_rate=round(sum(wr_list) / len(wr_list), 1) if wr_list else 0,
        timestamp=datetime.now().isoformat(),
    )

    return PortfolioResponse(summary=summary, positions=details)


# ── ILS Portfolio Endpoint ──

_ils_quote_cache: Dict[str, dict] = {}  # ticker -> {price, day_chg, ts}

async def _fetch_yahoo_quote(session: aiohttp.ClientSession, ticker: str) -> Optional[dict]:
    """Fetch live quote from Yahoo Finance for .TA tickers."""
    cached = _ils_quote_cache.get(ticker)
    if cached and (datetime.now() - cached["ts"]).seconds < 60:
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

    # Backtest (14-day forward, RSI<30 for Israeli market)
    trades = []
    for i in range(50, len(closes) - 14):
        hist = closes[:i + 1]
        h_rsi = _entry.calc_rsi(hist, 2)
        h_sma = _entry.calc_sma(hist, 50)
        if h_rsi < 30 and hist[-1] > h_sma:
            ret = ((closes[i + 14] - closes[i]) / closes[i]) * 100
            trades.append({"return": ret, "win": ret > 0, "rsi": h_rsi})

    wr = sum(1 for t in trades if t["win"]) / len(trades) * 100 if trades else 0
    avg_ret = sum(t["return"] for t in trades) / len(trades) if trades else 0

    # Zone analysis
    zone_lo = min(int(rsi2 // 10) * 10, 90)
    zone_hi = 101 if zone_lo == 90 else zone_lo + 10
    zt = [t for t in trades if zone_lo <= t["rsi"] < zone_hi]
    zone_ret = sum(t["return"] for t in zt) / len(zt) if zt else 0
    zone_wr = sum(1 for t in zt if t["win"]) / len(zt) * 100 if zt else 0

    # Exit zone analysis (all RSI values, not just entry signals)
    exit_zt = []
    for i in range(50, len(closes) - 14):
        hist = closes[:i + 1]
        h_rsi = _entry.calc_rsi(hist, 2)
        if zone_lo <= h_rsi < zone_hi:
            ret = ((closes[i + 14] - closes[i]) / closes[i]) * 100
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
    is_strong = rsi2 < 30 and above_sma50
    tier = "EXTREME" if is_extreme else ("STRONG" if is_strong else ("STANDARD" if above_sma50 else "NONE"))

    # Signal
    signal = "HOLD"
    issues = []
    if not above_sma50:
        signal = "CAUTION"
        issues.append("Below SMA50")
    elif rsi2 < 30 and above_sma50 and wr >= 55:
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
        "exit_strategy": "Fixed14d", "exit_strategy_wr": round(wr, 1),
        "exit_strategy_ret": round(avg_ret, 2), "exit_strategy_hold": 14.0,
        "exit_triggered": False, "exit_price": 0, "exit_price_pct": 0,
        "exit_label": f"Hold 14d | +{avg_ret:.1f}% WR {wr:.0f}%",
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

    if _scan_cache:
        # Overlay live/recent prices on cached scan results
        result = {**_scan_cache, "last_scan": _scan_cache_time.isoformat() if _scan_cache_time else ""}
        for opp in result.get("opportunities", []):
            ticker = opp.get("ticker", "")
            live = _price_cache.get(ticker)
            if live and live.get("price", 0) > 0:
                opp["price"] = round(live["price"], 2)
            else:
                # Fallback: latest close from historical cache
                df = _cache.get(ticker, 365)
                if df is not None and len(df) >= 50:
                    opp["price"] = round(float(df["Close"].iloc[-1]), 2)
        return result

    # No cache yet — trigger background scan, return empty placeholder
    if not _scan_running:
        _scan_running = True
        asyncio.create_task(_background_scan())

    return {
        "timestamp": datetime.now().isoformat(),
        "total_scanned": 0, "passed": 0,
        "opportunities": [], "holdings_scores": [],
        "worst_holding": "", "worst_score": 0,
        "last_scan": "", "scanning": True,
    }


async def _background_scan():
    """Run scan in background so endpoints don't block."""
    global _scan_running
    try:
        await _run_scan()
    finally:
        _scan_running = False


@router.post("/scan/refresh")
async def refresh_scan():
    """Force a fresh scan (clears cache first)."""
    global _scan_cache
    _scan_cache = None  # Clear so _run_scan does a full re-scan
    result = await _run_scan()
    return {**result, "last_scan": datetime.now().isoformat()}


def _backtest_7day(ticker: str) -> dict:
    """Backtest using ATLAS V2 core model: RSI<20 entry, 7-day fixed hold, price > SMA50.
    Same methodology that found COHR/BE/ALB/VRT."""
    df = _cache.get(ticker, 365)
    if df is None or len(df) < 60:
        return {}

    closes = df["Close"].dropna().tolist()
    if len(closes) < 60:
        return {}

    trades = []
    for i in range(50, len(closes) - 7):
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        hist_sma = _entry.calc_sma(hist_closes, 50)
        if hist_rsi < 20 and hist_closes[-1] > hist_sma:
            ret = ((closes[i + 7] - closes[i]) / closes[i]) * 100
            trades.append({"return": ret, "win": ret > 0})

    if len(trades) < 5:
        return {}

    wr = sum(1 for t in trades if t["win"]) / len(trades) * 100
    avg_ret = sum(t["return"] for t in trades) / len(trades)
    return {"win_rate": round(wr, 1), "avg_return": round(avg_ret, 2), "trades": len(trades)}


def _get_holdings_scores() -> tuple:
    """Get current portfolio holdings scores using hybrid exit strategy.
    Each holding gets its best exit strategy's return, not fixed 7d."""
    positions = _position_mgr._get_open_positions_sync()
    holdings_scores = {}
    for pos in positions:
        ticker = pos["ticker"]
        tech = _get_technicals(ticker)
        # Use hybrid strategy return if available, fallback to fixed 7d
        strat_ret = tech.get("exit_strategy_ret", 0) if tech else 0
        strat_wr = tech.get("exit_strategy_wr", 0) if tech else 0
        if strat_ret == 0 or strat_wr == 0:
            bt = _backtest_7day(ticker)
            strat_wr = bt.get("win_rate", 0)
            strat_ret = bt.get("avg_return", 0)
        if strat_wr > 0:
            score = strat_ret * strat_wr / 100
            holdings_scores[ticker] = {
                "score": round(score, 2),
                "zone_return": strat_ret,
                "win_rate": strat_wr,
            }
    worst_ticker = min(holdings_scores, key=lambda k: holdings_scores[k]["score"]) if holdings_scores else ""
    worst_score = holdings_scores[worst_ticker]["score"] if worst_ticker else 0
    return holdings_scores, worst_ticker, worst_score


MIN_PRICE = 10.0       # No penny stocks
MIN_VOLUME_RATIO = 0.8  # No low-volume stocks


def _dict_to_opportunity(r: dict, holdings_scores: dict) -> ScanOpportunity:
    """Convert a scan result dict to ScanOpportunity with portfolio comparison.
    Score uses avg_return (overall) * win_rate to match holdings scoring."""
    score = round(r.get("avg_return", 0) * r.get("win_rate", 0) / 100, 2)
    ticker = r.get("ticker", "")
    price = r.get("price", 0)
    vol_ratio = r.get("volume_ratio", 0)
    vetoed = r.get("vetoed", False)
    veto_reason = r.get("veto_reason", "")

    # Hard filters: penny stocks and low volume
    # V2.2: EXTREME tier gets relaxed volume (0.3x) since RSI<5 + >SMA200 is very selective
    tier = r.get("tier", "NONE")
    vol_threshold = 0.3 if tier == "EXTREME" else MIN_VOLUME_RATIO
    if not vetoed and price < MIN_PRICE:
        vetoed = True
        veto_reason = f"Penny stock (${price:.2f} < ${MIN_PRICE:.0f})"
    if not vetoed and 0 < vol_ratio < vol_threshold:
        vetoed = True
        veto_reason = f"Low volume ({vol_ratio:.1f}x < {vol_threshold}x)"

    # Which holdings does this stock beat?
    # V2.2 tier-adjusted thresholds:
    #   EXTREME: just beat the holding (highest conviction, RSI<5 + >SMA200)
    #   STRONG:  10% better (good conviction, dual-TF or vol spike)
    #   STANDARD: 30% better (covers $3 round-trip fee)
    # Common filters: not held, not vetoed, 10+ trades, no negative sentiment
    tier = r.get("tier", "NONE")
    sentiment_label = r.get("sentiment_label", "")
    if ticker in holdings_scores or vetoed:
        beats = []
    elif sentiment_label == "NEGATIVE":
        beats = []
    elif r.get("trades", 0) < 10:
        beats = []
    else:
        # Tier-based premium: EXTREME=0%, STRONG=10%, STANDARD/NONE=30%
        premium = 1.0 if tier == "EXTREME" else (1.1 if tier == "STRONG" else 1.3)
        beats = [
            h_ticker for h_ticker, h_data in holdings_scores.items()
            if score > h_data["score"] * premium
            and r.get("zone_trades", 0) >= 5
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
        hold_days=r.get("hold_days", 14),
        analyst_consensus=r.get("analyst_consensus", ""),
        analyst_target=r.get("analyst_target", 0),
        analyst_upside=r.get("analyst_upside", 0),
        sentiment_label=r.get("sentiment_label", ""),
        sentiment_score=r.get("sentiment_score", 0),
        vetoed=vetoed,
        veto_reason=veto_reason,
        score=score,
        beats_holdings=beats,
        is_upgrade=len(beats) > 0,
    )


def _build_scan_result(opportunities: list, total_scanned: int,
                       holdings_scores: dict, worst_ticker: str, worst_score: float) -> Dict:
    """Build the scan response dict."""
    opportunities.sort(key=lambda x: x.score, reverse=True)

    h_scores = [
        HoldingScore(ticker=t, score=d["score"], zone_return=d["zone_return"], win_rate=d["win_rate"]).model_dump()
        for t, d in holdings_scores.items()
    ]

    return {
        "timestamp": datetime.now().isoformat(),
        "total_scanned": total_scanned,
        "passed": len([o for o in opportunities if not o.vetoed]),
        "opportunities": [o.model_dump() for o in opportunities[:50]],
        "holdings_scores": h_scores,
        "worst_holding": worst_ticker,
        "worst_score": worst_score,
    }


async def _run_scan() -> Dict:
    """Run stock scan using ALL cached tickers (2,984+) with portfolio comparison."""
    global _scan_cache, _scan_cache_time

    try:
        from deep_scanner import DeepScanner

        holdings_scores, worst_ticker, worst_score = _get_holdings_scores()
        scanner = DeepScanner()

        # ALWAYS use the full SQLite cache (2,984 tickers), not the partial JSON cache
        cached_tickers = scanner.cache.get_cached_tickers()
        stock_data = {}
        for t in cached_tickers:
            df = scanner.cache.get(t, 365)
            if df is not None:
                stock_data[t] = df

        total_scanned = len(stock_data)
        print(f"[Scan] Scanning {total_scanned} cached stocks...")

        results = scanner.phase2_backtest(stock_data, [])
        print(f"[Scan] {len(results)} passed filters")

        if results:
            from dataclasses import asdict

            # Identify which stocks are potential upgrades BEFORE Phase 3
            # so we can ensure they ALL get validated
            upgrade_tickers = set()
            for r in results:
                r_dict = asdict(r)
                score = round(r_dict.get("avg_return", 0) * r_dict.get("win_rate", 0) / 100, 2)
                ticker = r_dict.get("ticker", "")
                if ticker not in holdings_scores:
                    for h_data in holdings_scores.values():
                        if score > h_data["score"]:
                            upgrade_tickers.add(ticker)
                            break

            # Phase 3 validation: top 30 by zone_return + ALL upgrade candidates
            # Reorder results so upgrade candidates are in the validated set
            upgrade_results = [r for r in results if r.ticker in upgrade_tickers]
            other_results = [r for r in results if r.ticker not in upgrade_tickers]
            # Put upgrades first so they're always validated
            reordered = upgrade_results + other_results
            validate_n = max(30, len(upgrade_results))
            print(f"[Scan] Validating {validate_n} stocks (including {len(upgrade_results)} potential upgrades)")

            results = await scanner.phase3_validate(reordered, top_n=min(validate_n, len(reordered)))

        # Convert to opportunities with portfolio comparison
        from dataclasses import asdict
        opportunities = []
        for r in results:
            r_dict = asdict(r)
            opp = _dict_to_opportunity(r_dict, holdings_scores)
            opportunities.append(opp)

        # Post-scan earnings check: veto any upgrade candidate with earnings <14 days
        # Scanner Phase 3 uses resp.json() which fails on Finnhub text/plain responses
        # We use json.loads(resp.text()) which is more robust
        async with aiohttp.ClientSession() as session:
            from datetime import timedelta
            today = datetime.now().strftime('%Y-%m-%d')
            end_14d = (datetime.now() + timedelta(days=14)).strftime('%Y-%m-%d')
            for opp in opportunities:
                if opp.is_upgrade and not opp.vetoed:
                    try:
                        url = (f"https://finnhub.io/api/v1/calendar/earnings"
                               f"?symbol={opp.ticker}&from={today}&to={end_14d}"
                               f"&token={FINNHUB_KEY}")
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            text = await resp.text()
                            edata = json.loads(text)
                            ec = edata.get("earningsCalendar", [])
                            if ec:
                                edate = ec[0].get("date", "")
                                opp.vetoed = True
                                opp.veto_reason = f"Earnings on {edate} (<14 days)"
                                opp.beats_holdings = []
                                opp.is_upgrade = False
                                print(f"[Scan] VETOED upgrade {opp.ticker}: earnings {edate}")
                        await asyncio.sleep(1.1)  # Finnhub rate limit
                    except Exception as e:
                        print(f"[Scan] Earnings check failed for {opp.ticker}: {e}")

        # Update prices with live quotes (scan uses stale historical close)
        for opp in opportunities:
            live = _price_cache.get(opp.ticker)
            if live and live.get("price", 0) > 0:
                opp.price = round(live["price"], 2)

        # Sort: upgrades first (stocks that beat holdings), then by score
        opportunities.sort(key=lambda x: (x.is_upgrade, x.score), reverse=True)

        scanner.save_cache(results)

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
    """Record a sell, close position, and log transaction."""
    ticker = req.ticker.upper()
    total = req.price * req.shares
    fee = 1.50

    # Find open position for this ticker
    positions = _position_mgr._get_open_positions_sync()
    pos = next((p for p in positions if p["ticker"] == ticker), None)

    if not pos:
        return TradeResult(success=False, message=f"No open position for {ticker}", ticker=ticker)

    # Calculate realized P&L
    realized_pnl = (req.price - pos["entry_price"]) * req.shares - fee

    # Close position
    result = _position_mgr._close_position_sync(
        position_id=pos["id"],
        exit_date=datetime.now().strftime("%Y-%m-%d"),
        exit_price=req.price,
    )

    # Record transaction
    tx = _position_mgr.add_transaction(
        ticker=ticker, action="SELL", price=req.price, shares=req.shares,
        fee=fee, realized_pnl=realized_pnl, notes=req.notes,
        position_id=pos["id"],
    )

    return TradeResult(
        success=True,
        message=f"Sold {req.shares} shares of {ticker} @ ${req.price:.2f} (P&L: ${realized_pnl:+.2f})",
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
            notes=tx.get("notes", ""),
        ).model_dump()
        for tx in txs
    ]

    return HistoryResponse(
        transactions=transactions,
        total_fees=summary["total_fees"],
        total_realized_pnl=summary["total_realized_pnl"],
        trade_count=summary["trade_count"],
    )


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

    closes = df["Close"].dropna().tolist()

    # Collect all data points with their RSI and % from recent 10-day high
    zones = {
        "EXTREME": {"rsi_lo": 0, "rsi_hi": 5, "label": "RSI < 5", "trades": [], "drops": []},
        "STRONG":  {"rsi_lo": 5, "rsi_hi": 10, "label": "RSI 5-10", "trades": [], "drops": []},
        "STANDARD": {"rsi_lo": 10, "rsi_hi": 20, "label": "RSI 10-20", "trades": [], "drops": []},
    }

    for i in range(50, len(closes) - 7):
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        hist_sma = _entry.calc_sma(hist_closes, 50)

        # Only consider valid buy signals (above SMA50)
        if hist_closes[-1] <= hist_sma:
            continue

        # % drop from recent 10-day high
        recent_high = max(closes[max(0, i - 10):i + 1])
        pct_drop = ((closes[i] - recent_high) / recent_high) * 100

        # 7-day forward return
        ret = ((closes[i + 7] - closes[i]) / closes[i]) * 100

        for key, z in zones.items():
            if z["rsi_lo"] <= hist_rsi < z["rsi_hi"]:
                z["trades"].append({"return": ret, "win": ret > 0})
                z["drops"].append(pct_drop)

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

    # 1. Technicals + backtest from cache (try fetching on-demand if not cached)
    tech = _get_technicals(ticker)
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
                        tech = _get_technicals(ticker)
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
    wr = bt.get("win_rate", 0) if bt else tech.get("win_rate", 0)
    avg_ret = bt.get("avg_return", 0) if bt else tech.get("avg_return", 0)
    exit_zr = tech.get("exit_zone_return", 0)
    exit_zwr = tech.get("exit_zone_wr", 0)
    exit_zt = tech.get("exit_zone_trades", 0)

    # Build issues and signal
    issues = []
    if not above_sma50:
        issues.append("Below SMA50 - broken uptrend")
    if regime == "BEAR":
        issues.append("BEAR regime")
    if wr < 55:
        issues.append(f"Low WR ({wr:.1f}%)")
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
    try:
        import sqlite3
        _pos_db = os.path.join(os.path.dirname(__file__), "data", "positions.db")
        conn = sqlite3.connect(_pos_db)
        row = conn.execute("SELECT shares, entry_price FROM positions WHERE ticker=? AND shares>0", (ticker,)).fetchone()
        conn.close()
        if row:
            # Held position: check hybrid exit
            df_hist = _cache.get(ticker, 365)
            if df_hist is not None and len(df_hist) >= 50:
                closes_list = df_hist["Close"].dropna().tolist()
                bt_data = _backtest_7day(ticker)
                best_exit = _select_best_exit(ticker, closes_list, bt_data.get("trades", 0) if bt_data else 0, rsi2)
                if best_exit:
                    triggered = _evaluate_exit_trigger(best_exit, closes_list, rsi2, live_price)
                    exit_strategy_info = {
                        "exit_strategy": best_exit.get("strategy", ""),
                        "exit_strategy_wr": best_exit.get("wr", 0),
                        "exit_strategy_ret": best_exit.get("avg_ret", 0),
                        "exit_strategy_hold": best_exit.get("hold_days", 0),
                        "exit_triggered": triggered.get("triggered", False),
                        "exit_price": triggered.get("exit_price", 0),
                        "exit_label": triggered.get("label", ""),
                        "entry_price": row[1],
                        "shares": row[0],
                    }
                    if triggered.get("triggered", False):
                        issues.append(f"Exit triggered ({best_exit.get('strategy', '')}: {triggered.get('label', '')})")
    except Exception:
        pass

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
        if rsi2 < 20 and zone_trades >= 5 and zone_ret > exit_strat_ret:
            signal = "HOLD"
            issues.append(f"Exit suppressed: RSI oversold ({rsi2:.0f}), zone +{zone_ret:.1f}% > exit +{exit_strat_ret:.1f}%")
        else:
            signal = "EXIT"
    elif rsi2 < 20 and above_sma50 and regime != "BEAR" and wr >= 55:
        signal = "BUY"
    elif rsi2 < 30 and above_sma50 and regime != "BEAR" and wr >= 55:
        signal = "BUY"
    elif exit_zt >= 5 and exit_zr < 1.0 and exit_zwr < 55:
        signal = "ROTATION"
    else:
        signal = "HOLD"

    # BULL exit strategy
    entry_est = live_price  # Use live as reference
    stop_loss = round(entry_est * 0.92, 2)
    target_1 = round(entry_est * 1.10, 2)
    target_2 = round(entry_est * 1.20, 2)

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
        "total_trades": bt.get("trades", 0) if bt else tech.get("total_trades", 0),
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

    # Buy signals: RSI(2) < 20 and price > SMA50
    signals = []
    for i in range(50, len(closes)):
        hist_closes = closes[:i + 1]
        rsi2 = _entry.calc_rsi(hist_closes, 2)
        sma = sum(closes[i-49:i+1]) / 50
        if rsi2 < 20 and closes[i] > sma:
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
    ok = send_test_email()
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

    ok = send_portfolio_report(positions, buy_signals, upgrades)
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

    levels = []
    async with aiohttp.ClientSession() as session:
        for pos in positions:
            ticker = pos["ticker"]
            entry = pos["entry_price"]
            quote = await _get_finnhub_quote(session, ticker)
            price = quote["price"] if quote else entry

            tech = _get_technicals(ticker)
            regime = tech.get("regime", "BULL")
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
            await asyncio.sleep(0.3)

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
                print("[Monitor] Health check timed out, skipping this cycle")
                await asyncio.sleep(900)
                continue

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
                        send_health_alert(new_health)
                        for a in new_health:
                            sent_health.add(f"{a.get('ticker','')}-{a.get('signal','')}")

                # Signal alerts: only send when signal CHANGES for a ticker
                new_signals = []
                current_signals = {}
                for pos in health.get("positions", []):
                    ticker = pos.get("ticker", "?")
                    signal = pos.get("signal", "HOLD")
                    current_signals[ticker] = signal
                    if signal in ("SELL", "ROTATION"):
                        prev = sent_signals.get(ticker)
                        if prev != signal:
                            new_signals.append({
                                "ticker": ticker,
                                "action": signal,
                                "price": pos.get("price", 0),
                                "reason": "; ".join(pos.get("issues", [])),
                            })
                if new_signals:
                    send_signal_alert(new_signals)

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
                        send_upgrade_alert(upgrades)
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

                tech = _get_technicals(ticker)
                regime = tech.get("regime", "BULL")
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
                    send_price_level_alert(triggered)
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


async def warmup_signal_cache():
    """Pre-cache signals for all positions at startup so first request is fast.
    On production: only cache technicals (no network calls) to avoid worker timeout."""
    await asyncio.sleep(15)  # Wait for app to be fully ready
    positions = _position_mgr._get_open_positions_sync()
    if not positions:
        return

    if _is_prod:
        # Production: just warm technicals cache, skip network-heavy signal computation
        print(f"[Warmup] Production mode - caching technicals for {len(positions)} positions...")
        for pos in positions:
            ticker = pos["ticker"]
            try:
                tech = _get_technicals(ticker)
                # Pre-fill signal cache with basic signal (no network rules)
                signal = "HOLD"
                issues = []
                rsi2 = tech.get("rsi2", 50)
                above_sma50 = tech.get("above_sma50", True)
                if rsi2 < 20 and above_sma50:
                    signal = "BUY"
                elif rsi2 > 80:
                    signal = "OVERBOUGHT"
                elif not above_sma50:
                    signal = "CAUTION"
                    issues.append("Below SMA50")
                _signal_cache[ticker] = (signal, issues, datetime.now())
                print(f"[Warmup] {ticker}: {signal} (RSI={rsi2:.0f})")
            except Exception as e:
                print(f"[Warmup] {ticker} error: {e}")
        print("[Warmup] Technicals cached - ready to serve requests")
    else:
        # Local dev: full warmup with network calls
        print(f"[Warmup] Pre-caching signals for {len(positions)} positions...")
        async with aiohttp.ClientSession() as session:
            for pos in positions:
                ticker = pos["ticker"]
                try:
                    quote = await _get_finnhub_quote(session, ticker)
                    live_price = quote["price"] if quote else pos["entry_price"]
                    day_chg = quote["day_chg"] if quote else 0
                    tech = _get_technicals(ticker)
                    await _compute_signal(session, ticker, tech, live_price, day_chg)
                    print(f"[Warmup] {ticker} cached")
                except Exception as e:
                    print(f"[Warmup] {ticker} error: {e}")
                await asyncio.sleep(0.5)
        print("[Warmup] Signal cache ready")


async def quote_refresh_loop():
    """Centralized quote refresher. Fetches all position quotes every 30s.
    All other code reads from _quote_cache instead of hitting Finnhub directly.
    This is the ONLY recurring Finnhub caller — avoids rate limit exhaustion."""
    await asyncio.sleep(5)  # Wait for app startup
    print("[QuoteRefresh] Started — refreshing position quotes every 30s")

    while True:
        try:
            positions = _position_mgr._get_open_positions_sync()
            if not positions:
                await asyncio.sleep(30)
                continue

            async with aiohttp.ClientSession() as session:
                for pos in positions:
                    ticker = pos["ticker"]
                    quote = await _get_finnhub_quote(session, ticker)
                    if quote:
                        # Also fall back to historical if Finnhub returns stale/zero
                        if quote.get("price", 0) <= 0:
                            df = _cache.get(ticker, 365)
                            if df is not None and len(df) >= 2:
                                close = float(df["Close"].iloc[-1])
                                prev = float(df["Close"].iloc[-2])
                                _price_cache[ticker] = {
                                    "price": close,
                                    "prev_close": prev,
                                    "day_chg": round(((close - prev) / prev) * 100, 2) if prev > 0 else 0,
                                }
                                _quote_cache[ticker] = (_price_cache[ticker], datetime.now())
                    await asyncio.sleep(1.2)  # ~50 calls/min max with 5 tickers = safe

            # Log status
            prices = {t: _price_cache.get(t, {}).get("price", 0) for t in [p["ticker"] for p in positions]}
            print(f"[QuoteRefresh] Updated: {prices} | API calls: {_finnhub_calls_this_minute}/min")

        except Exception as e:
            print(f"[QuoteRefresh] Error: {e}")

        await asyncio.sleep(30)


async def cache_refresh_loop():
    """Daily historical data refresh. Runs at startup if stale, then every 4 hours.
    Keeps stock_cache.db up to date so scanner/backtest use fresh data."""
    await asyncio.sleep(30)  # Wait for app startup

    while True:
        try:
            stale = _cache.get_stale_tickers()
            if not stale:
                print(f"[CacheRefresh] All {len(_cache.get_cached_tickers())} tickers up to date")
                await asyncio.sleep(14400)  # 4 hours
                continue

            print(f"[CacheRefresh] {len(stale)} stale tickers, refreshing...")

            # Priority: refresh holdings first, then scanner universe
            positions = _position_mgr._get_open_positions_sync()
            holding_tickers = [p["ticker"] for p in positions] if positions else []
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
            global _scan_cache
            _scan_cache = None

        except Exception as e:
            import traceback
            print(f"[CacheRefresh] Error: {e}")
            traceback.print_exc()

        await asyncio.sleep(14400)  # 4 hours
