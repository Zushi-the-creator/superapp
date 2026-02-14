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

# Last known good prices (never show 0 P&L due to Finnhub failures)
_price_cache: Dict[str, Dict] = {}

# WebSocket connections for alerts
_ws_connections: List[WebSocket] = []


# ── Helpers ──

async def _get_finnhub_quote(session: aiohttp.ClientSession, ticker: str) -> Optional[Dict]:
    """Get live quote from Finnhub. Caches last known good price to prevent P&L=0 on failures."""
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={FINNHUB_KEY}"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("c", 0) > 0:
                    pc = data.get("pc", data["c"])
                    result = {
                        "price": data["c"],
                        "prev_close": pc,
                        "day_chg": (data["c"] - pc) / pc * 100 if pc else 0,
                    }
                    # Cache this good price
                    _price_cache[ticker] = result
                    return result
    except Exception:
        pass
    # On failure, return last known good price instead of None
    if ticker in _price_cache:
        return _price_cache[ticker]
    return None


def _get_technicals(ticker: str) -> Dict:
    """Get RSI, SMA50, regime, backtest stats from cache."""
    df = _cache.get(ticker, 365)
    if df is None or len(df) < 60:
        return {}

    closes = df["Close"].dropna().tolist()
    highs = df["High"].tolist() if "High" in df.columns else closes
    lows = df["Low"].tolist() if "Low" in df.columns else closes
    volumes = df["Volume"].tolist() if "Volume" in df.columns else [0] * len(closes)

    sma50 = _entry.calc_sma(closes, 50)
    rsi2 = _entry.calc_rsi(closes, 2)

    regime_info = RegimeDetector.detect(closes, highs, lows, volumes)
    regime = regime_info.regime.value if hasattr(regime_info, "regime") else str(regime_info)

    # Backtest
    trades = []
    for i in range(50, len(closes) - 7):
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        hist_sma = _entry.calc_sma(hist_closes, 50)
        if hist_rsi < 20 and hist_closes[-1] > hist_sma:
            ret = ((closes[i + 7] - closes[i]) / closes[i]) * 100
            trades.append({"return": ret, "win": ret > 0, "rsi": hist_rsi})

    wr = sum(1 for t in trades if t["win"]) / len(trades) * 100 if trades else 0
    avg_ret = sum(t["return"] for t in trades) / len(trades) if trades else 0

    # RSI zone (buy-signal trades only — for entry analysis)
    zone_low = int(rsi2 // 10) * 10
    zone_high = zone_low + 10
    zone_trades = [t for t in trades if zone_low <= t["rsi"] < zone_high]
    zone_ret = sum(t["return"] for t in zone_trades) / len(zone_trades) if zone_trades else 0
    zone_wr = sum(1 for t in zone_trades if t["win"]) / len(zone_trades) * 100 if zone_trades else 0

    # Exit zone analysis: forward 7-day returns at CURRENT RSI zone using ALL data points
    # This answers: "When this stock was at RSI X historically, what was the 7-day forward return?"
    # Critical for exit decisions — the buy-zone trades above are empty for RSI > 20
    exit_zone_trades_list = []
    for i in range(50, len(closes) - 7):
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        if zone_low <= hist_rsi < zone_high:
            ret = ((closes[i + 7] - closes[i]) / closes[i]) * 100
            exit_zone_trades_list.append({"return": ret, "win": ret > 0})

    exit_zone_ret = sum(t["return"] for t in exit_zone_trades_list) / len(exit_zone_trades_list) if exit_zone_trades_list else 0
    exit_zone_wr = sum(1 for t in exit_zone_trades_list if t["win"]) / len(exit_zone_trades_list) * 100 if exit_zone_trades_list else 0

    # Sparkline (last 20 closes)
    sparkline = [round(c, 2) for c in closes[-20:]]

    return {
        "rsi2": round(rsi2, 1),
        "sma50": round(sma50, 2),
        "above_sma50": closes[-1] > sma50,
        "regime": regime,
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

    # Rule 5: Earnings check (Finnhub)
    try:
        from deep_scanner import DeepScanner
        ds = DeepScanner()
        earnings = await ds._check_earnings(session, ticker)
        if earnings:
            issues.append(f"Earnings on {earnings['date']} (<7 days)")
    except Exception:
        pass

    # Rule 6: Sentiment check (Google News + VADER)
    try:
        from sentiment import SentimentEngine
        se = SentimentEngine()
        sdata = await se.get_ticker_sentiment(ticker)
        if sdata and sdata.get("sentiment_score", 0) < -0.3:
            issues.append(f"Negative sentiment ({sdata['sentiment_score']:.2f})")
    except Exception:
        pass

    # Rule 7: Analyst overvaluation check
    try:
        from analyst_data import AnalystDataFetcher
        af = AnalystDataFetcher()
        adata = await af.fetch_analyst_data(ticker)
        if adata and adata.get("price_target_avg", 0) > 0:
            target = adata["price_target_avg"]
            if live_price > target:
                issues.append(f"Overvalued (${live_price:.0f} > target ${target:.0f})")
    except Exception:
        pass

    # Rule 8: RSI zone expected return analysis (CRITICAL for exit decisions)
    # "When this stock was at this RSI zone historically, what was the 7-day forward return?"
    if exit_zone_trades >= 5:
        if exit_zone_ret < 1.0 and exit_zone_wr < 55:
            issues.append(f"Weak zone return (+{exit_zone_ret:.1f}%, {exit_zone_wr:.0f}% WR at RSI {int(rsi2)})")
        elif exit_zone_ret < 2.0:
            issues.append(f"Moderate zone return (+{exit_zone_ret:.1f}% at RSI {int(rsi2)})")

    # Determine signal from issues + exit zone analysis
    critical = [i for i in issues if any(k in i for k in ["Below SMA50", "BEAR regime", "CRASH", "Low WR"])]
    warnings = [i for i in issues if i not in critical]

    if any("CRASH" in i for i in critical):
        signal = "SELL"
    elif any("Below SMA50" in i for i in critical) and any("BEAR" in i for i in critical):
        signal = "SELL"
    elif any("Below SMA50" in i for i in critical):
        signal = "CAUTION"
    elif len(critical) > 0:
        signal = "CAUTION"
    elif rsi2 > 80:
        # Don't assume overbought = sell — use exit zone return (all historical data at this RSI)
        if exit_zone_trades >= 5 and exit_zone_ret > 3:
            signal = "HOLD"  # Strong zone return even at overbought
        elif exit_zone_trades >= 5 and exit_zone_ret > 1:
            signal = "HOLD"  # Decent zone return
        elif exit_zone_trades >= 5 and exit_zone_ret <= 1 and exit_zone_wr < 55:
            signal = "ROTATION"  # Weak expected return at overbought → rotate
        elif exit_zone_trades < 5:
            signal = "HOLD"  # Not enough data, default hold
        else:
            signal = "OVERBOUGHT"
    elif rsi2 >= 20:
        # Mid-range RSI: check exit zone return for rotation signals
        if exit_zone_trades >= 5 and exit_zone_ret < 1.0 and exit_zone_wr < 55:
            signal = "ROTATION"  # Weak expected return → consider selling
        elif rsi2 < 30 and above_sma50 and regime != "BEAR":
            signal = "BUY"  # Near buy zone
        else:
            signal = "HOLD"
    elif rsi2 < 20 and above_sma50 and regime != "BEAR":
        signal = "BUY"
    else:
        signal = "HOLD"

    _signal_cache[ticker] = (signal, issues, datetime.now())
    return signal, issues


# ── Portfolio Endpoint ──

@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio():
    """Get portfolio with live prices, technicals, signals, and P&L."""
    positions = _position_mgr._get_open_positions_sync()

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

            # Real signal using ATLAS V2 rules + sentiment + analyst + earnings
            signal, issues = await _compute_signal(session, ticker, tech, live_price, day_chg)

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
                sma50=tech.get("sma50", 0),
                above_sma50=tech.get("above_sma50", True),
                regime=tech.get("regime", ""),
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
                sparkline=tech.get("sparkline", []),
                signal=signal,
                issues=issues,
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

    summary = PortfolioSummary(
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl / total_cost * 100, 2) if total_cost else 0,
        position_count=len(details),
        avg_win_rate=round(sum(wr_list) / len(wr_list), 1) if wr_list else 0,
        timestamp=datetime.now().isoformat(),
    )

    return PortfolioResponse(summary=summary, positions=details)


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
        return {**_scan_cache, "last_scan": _scan_cache_time.isoformat() if _scan_cache_time else ""}

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
    """Get current portfolio holdings scores using SAME backtest as scanner.
    Uses variable hold periods to match DeepScanner methodology exactly."""
    positions = _position_mgr._get_open_positions_sync()
    holdings_scores = {}
    for pos in positions:
        bt = _backtest_7day(pos["ticker"])
        wr = bt.get("win_rate", 0)
        avg_ret = bt.get("avg_return", 0)
        if wr > 0:
            score = avg_ret * wr / 100
            holdings_scores[pos["ticker"]] = {
                "score": round(score, 2),
                "zone_return": avg_ret,
                "win_rate": wr,
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
    if not vetoed and price < MIN_PRICE:
        vetoed = True
        veto_reason = f"Penny stock (${price:.2f} < ${MIN_PRICE:.0f})"
    if not vetoed and 0 < vol_ratio < MIN_VOLUME_RATIO:
        vetoed = True
        veto_reason = f"Low volume ({vol_ratio:.1f}x < {MIN_VOLUME_RATIO}x)"

    # Which holdings does this stock beat? Strict filters to avoid false upgrades:
    # - Must not be held or vetoed
    # - Score must be 30%+ higher (covers $3 round-trip fee)
    # - Must have 10+ trades (not 5) for upgrade confidence
    # - Negative sentiment disqualifies
    # - SIDEWAYS regime with earnings proximity = risky
    sentiment_label = r.get("sentiment_label", "")
    if ticker in holdings_scores or vetoed:
        beats = []
    elif sentiment_label == "NEGATIVE":
        beats = []
    elif r.get("trades", 0) < 10:
        beats = []
    else:
        beats = [
            h_ticker for h_ticker, h_data in holdings_scores.items()
            if score > h_data["score"] * 1.3  # 30% better minimum
            and r.get("zone_trades", 0) >= 5
        ]

    return ScanOpportunity(
        ticker=ticker,
        price=price,
        rsi2=r.get("rsi2", 0),
        rsi_zone=r.get("rsi_zone", ""),
        regime=r.get("regime", ""),
        win_rate=r.get("win_rate", 0),
        trades=r.get("trades", 0),
        avg_return=r.get("avg_return", 0),
        zone_return=r.get("zone_return", 0),
        zone_trades=r.get("zone_trades", 0),
        zone_win_rate=r.get("zone_win_rate", 0),
        volume_ratio=vol_ratio,
        hold_days=r.get("hold_days", 7),
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
    fee = 1.50

    # Add position
    result = _position_mgr._add_position_sync(
        ticker=ticker,
        entry_date=datetime.now().strftime("%Y-%m-%d"),
        entry_price=req.price,
        shares=req.shares,
        notes=req.notes,
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

    # 3. Live quote
    async with aiohttp.ClientSession() as session:
        quote = await _get_finnhub_quote(session, ticker)
        live_price = quote["price"] if quote else 0
        day_chg = quote["day_chg"] if quote else 0

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

    return {
        "ticker": ticker,
        "live_price": round(live_price, 2),
        "day_change_pct": round(day_chg, 2),
        "rsi2": tech.get("rsi2", -1),
        "sma50": tech.get("sma50", 0),
        "above_sma50": above_sma50,
        "regime": regime,
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

async def background_monitor():
    """Runs every 15 minutes: health check + scan refresh + email alerts."""
    await asyncio.sleep(10)  # Wait for startup
    while True:
        try:
            print(f"\n[Monitor] Running health check at {datetime.now().strftime('%H:%M')}")
            health = await _run_health_check()

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

            # Email alerts for health issues
            try:
                from email_alerts import send_health_alert, send_signal_alert, send_upgrade_alert
                if health.get("alerts"):
                    send_health_alert(health["alerts"])

                # Check signals on all positions for sell/rotation alerts
                signals = []
                for pos in health.get("positions", []):
                    signal = pos.get("signal", "HOLD")
                    if signal in ("SELL", "ROTATION"):
                        signals.append({
                            "ticker": pos.get("ticker", "?"),
                            "action": signal,
                            "price": pos.get("price", 0),
                            "reason": "; ".join(pos.get("issues", [])),
                        })
                if signals:
                    send_signal_alert(signals)

                # Check scan cache for upgrades
                if _scan_cache:
                    upgrades = [
                        {"ticker": o["ticker"], "beats": o.get("beats_holdings", []),
                         "score": o.get("score", 0), "win_rate": o.get("win_rate", 0),
                         "zone_return": o.get("zone_return", 0)}
                        for o in _scan_cache.get("opportunities", [])
                        if o.get("is_upgrade") and not o.get("vetoed")
                    ]
                    if upgrades:
                        send_upgrade_alert(upgrades)
            except Exception as e:
                print(f"[Monitor] Email alert error: {e}")

            print(f"[Monitor] Health check complete: {health.get('alerts_count', 0)} alerts")
        except Exception as e:
            print(f"[Monitor] Error: {e}")

        await asyncio.sleep(900)  # 15 minutes
