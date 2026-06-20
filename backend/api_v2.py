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
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from schemas_v2 import (
    BuyRequest, SellRequest, DepositRequest, TradeResult,
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
TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "6f632a60d6188ebc1b92221e83d4fba37e2a5c42")

# Shared state
_position_mgr = PositionManager(db_path=os.path.join(os.path.dirname(__file__), "data", "positions.db"))
_cache = DataCache()
_entry = EntryEngine()

# Cached results from background monitor
_health_cache: Optional[Dict] = None
_health_cache_time: Optional[datetime] = None
_scan_cache: Optional[Dict] = None
_scan_cache_time: Optional[datetime] = None

# Auto-refresh guard — prevents duplicate refreshes when cache is stale
_auto_refresh_running = False

# ── Centralized Quote Management ──
# Single source of truth for live prices. Background task refreshes every 30s.
# All endpoints read from here instead of hitting Finnhub directly.
_price_cache: Dict[str, Dict] = {}   # ticker -> last known good quote (persistent)
_quote_cache: Dict[str, tuple] = {}  # ticker -> (result, timestamp) — 30s TTL


def _fresh_live_px() -> Dict[str, float]:
    """Return {ticker: price} for quotes captured TODAY only.

    Stale-price fix (2026-06-18): _price_cache is persistent, so an entry left
    over from a prior session/day must NOT feed signal detection — a yesterday's
    close fed into evaluate_all manufactures phantom RSI2<10 dips (MOD/IMAX bug).
    Entries with no 'ts' (e.g. SQLite-seeded bar closes) are excluded — they are
    not intraday quotes and shouldn't drive 'today is oversold' decisions.
    """
    _today = datetime.now().date()
    out = {}
    for t, q in _price_cache.items():
        if q.get("price", 0) <= 0:
            continue
        ts = q.get("ts")
        if isinstance(ts, datetime) and ts.date() == _today:
            out[t] = q["price"]
    return out

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


# Broker-verified historical deposit baseline. Every DEPOSIT recorded via the
# /positions/deposit endpoint adds on top of this number through the DB ledger.
# Don't bump this constant for new deposits — they should flow through the DB.
HISTORICAL_DEPOSIT_BASELINE = 11891.58


def _sum_db_deposits() -> float:
    """Sum of DEPOSIT rows in the transactions ledger.
    Extends the historical baseline with deposits recorded via /positions/deposit."""
    import sqlite3 as _sql
    db_path = os.path.join(os.path.dirname(__file__), "data", "positions.db")
    conn = _sql.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(total),0) FROM transactions WHERE action='DEPOSIT'"
        ).fetchone()
    finally:
        conn.close()
    return float(row[0] or 0)


def _total_deposited_now() -> float:
    """Authoritative total deposited = broker-verified historical baseline + DB DEPOSITs."""
    return round(HISTORICAL_DEPOSIT_BASELINE + _sum_db_deposits(), 2)


def _compute_cash_balance(total_deposited: float) -> float:
    """Derive cash from the transaction ledger:
        cash = total_deposited
             − Σ(BUY.total + BUY.fee)
             + Σ(SELL.total − SELL.fee)
             − Σ(SPLIT.fee)
             − Σ(TAX.total)
    `total_deposited` should already include DB DEPOSITs (caller passes
    `_total_deposited_now()`). Fee column on each tx already respects the
    10-free-trades-per-month rule (set by `_calc_trade_fee` at trade time).
    Optional env override BROKER_CASH_OVERRIDE pins to a known broker balance
    when ledger drift happens. Negative results clamp to 0 (impossible in
    cash account; signals missing deposits or duplicate buys — tracked
    separately as data integrity).
    """
    override = os.environ.get("BROKER_CASH_OVERRIDE")
    if override:
        try:
            return float(override)
        except ValueError:
            pass
    import sqlite3 as _sql
    db_path = os.path.join(os.path.dirname(__file__), "data", "positions.db")
    conn = _sql.connect(db_path)
    try:
        cur = conn.cursor()
        buy_total, buy_fee = cur.execute(
            "SELECT COALESCE(SUM(total),0), COALESCE(SUM(fee),0) FROM transactions WHERE action='BUY'"
        ).fetchone()
        sell_total, sell_fee = cur.execute(
            "SELECT COALESCE(SUM(total),0), COALESCE(SUM(fee),0) FROM transactions WHERE action='SELL'"
        ).fetchone()
        split_fee = cur.execute(
            "SELECT COALESCE(SUM(fee),0) FROM transactions WHERE action='SPLIT'"
        ).fetchone()[0]
        tax_total = cur.execute(
            "SELECT COALESCE(SUM(total),0) FROM transactions WHERE action='TAX'"
        ).fetchone()[0]
    finally:
        conn.close()
    raw = total_deposited - buy_total - buy_fee + sell_total - sell_fee - split_fee - tax_total
    if raw < 0:
        # Surface the drift instead of clamping — the user wants to see the real
        # number so fee/tax mismatches with the broker are visible. Set
        # BROKER_CASH_OVERRIDE if you want to pin to the broker's authoritative
        # balance instead.
        print(f"[cash] computed cash {raw:.2f} < 0 (ledger drift, not clamped). "
              f"Set BROKER_CASH_OVERRIDE to pin to broker reality.")
    return round(raw, 2)


def _get_market_session() -> str:
    """Return current US market session based on ET time.
    PRE_MARKET:   4:00 AM - 9:30 AM ET (Mon-Fri)
    REGULAR:      9:30 AM - 4:00 PM ET (Mon-Fri)
    AFTER_HOURS:  4:00 PM - 8:00 PM ET (Mon-Fri)
    CLOSED:       Weekends + outside 4am-8pm
    """
    try:
        import zoneinfo
        et = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except (ImportError, Exception):
        try:
            import pytz
            et = datetime.now(pytz.timezone("US/Eastern"))
        except (ImportError, Exception):
            from datetime import timezone
            # DST-aware: March-Nov is UTC-4, else UTC-5
            utc_now = datetime.now(timezone.utc)
            month = utc_now.month
            offset = 4 if 3 <= month <= 11 else 5
            et = utc_now.replace(tzinfo=None) - timedelta(hours=offset)
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
    """DEPRECATED — kept as alias for callers that haven't migrated.
    Use _get_tiingo_quote (Tiingo IEX) instead. Tiingo is our sole price source.
    """
    return await _get_tiingo_quote(session, ticker)


async def _get_tiingo_quote(session: aiohttp.ClientSession, ticker: str) -> Optional[Dict]:
    """Get live quote from Tiingo IEX. 30s cache + last-known-good fallback.

    Single-ticker variant of _fetch_tiingo_iex_batch — used by /analyze and
    other on-demand callers that need one quote at request time. Bulk paths
    (warmup, scan/refresh) should call _fetch_tiingo_iex_batch directly to
    amortize the HTTP round-trip across many tickers.

    Tiingo Power plan: 10K req/hr, 100K req/day — well above what /analyze
    needs. No additional rate limiter required (the cache TTL handles bursts).
    """
    # Cache hit?
    if ticker in _quote_cache:
        cached_result, cached_time = _quote_cache[ticker]
        if (datetime.now() - cached_time).total_seconds() < QUOTE_CACHE_TTL:
            return cached_result

    if not TIINGO_KEY:
        return _price_cache.get(ticker)

    _timeout = 4 if os.environ.get("FLY_APP_NAME") else 8
    try:
        url = f"https://api.tiingo.com/iex/{ticker}?token={TIINGO_KEY}"
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=_timeout),
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                if isinstance(data, list) and data:
                    row = data[0]
                    last = row.get("tngoLast") or row.get("last") or 0
                    prev = row.get("prevClose") or row.get("open") or last
                    if last and last > 0:
                        result = {
                            "price": float(last),
                            "prev_close": float(prev),
                            "day_chg": (float(last) - float(prev)) / float(prev) * 100 if prev else 0,
                            "ts": datetime.now(),  # freshness stamp (2026-06-18 stale-price fix)
                        }
                        _price_cache[ticker] = result
                        _quote_cache[ticker] = (result, datetime.now())
                        return result
    except Exception:
        pass
    return _price_cache.get(ticker)


async def _fetch_tiingo_iex_batch(tickers: List[str], batch_size: int = 100) -> int:
    """Batch-fetch live quotes via Tiingo IEX. Updates _price_cache + _quote_cache.
    Returns number of tickers successfully updated. One request per batch_size tickers."""
    if not tickers:
        return 0
    tkey = os.environ.get("TIINGO_API_KEY", "6f632a60d6188ebc1b92221e83d4fba37e2a5c42")
    updated = 0
    for batch_start in range(0, len(tickers), batch_size):
        batch = tickers[batch_start:batch_start + batch_size]
        try:
            async with aiohttp.ClientSession() as session:
                url = f"https://api.tiingo.com/iex/?tickers={','.join(batch)}"
                headers = {"Authorization": f"Token {tkey}", "Content-Type": "application/json"}
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for d in data:
                            t = d.get("ticker", "").upper()
                            # Prefer the REAL intraday price. Tiingo's `last` is
                            # frequently null while `tngoLast` carries the live value.
                            # Do NOT fall back to prevClose as a "live" price — that
                            # stamps yesterday's close as today's quote and manufactures
                            # phantom oversold signals (2026-06-18 stale-price fix).
                            last = d.get("tngoLast") or d.get("last") or 0
                            prev = d.get("prevClose") or 0
                            if last and last > 0:
                                result = {
                                    "price": round(float(last), 2),
                                    "prev_close": round(float(prev), 2),
                                    "day_chg": round(((last - prev) / prev) * 100, 2) if prev > 0 else 0,
                                    "ts": datetime.now(),
                                }
                                _price_cache[t] = result
                                _quote_cache[t] = (result, datetime.now())
                                updated += 1
        except Exception as e:
            print(f"[TiingoIEX] Batch {batch_start//batch_size} error: {e}")
    return updated


async def _run_precompute_and_eval_subproc(held: set, live_px: dict, label: str = "Eval") -> int:
    """Run backtest_precompute + strategy_evaluator in a subprocess so the heavy
    pandas/numpy work can't starve the event loop on shared-1x Fly machines.
    Returns count of valid (non-vetoed) signals, or -1 on error/timeout."""
    import json as _json
    payload = _json.dumps({"held": sorted(held), "live_px": live_px})
    code = (
        "import json, sys\n"
        "from backtest_precompute import precompute_all\n"
        "from strategy_evaluator import evaluate_all, save_cache\n"
        "p = json.loads(sys.stdin.read())\n"
        "precompute_all()\n"
        "sigs = evaluate_all(10.0, set(p['held']), p['live_px'])\n"
        "save_cache(sigs)\n"
        "print(f'__VALID__ {sum(1 for s in sigs if not s.vetoed)}')\n"
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            cwd=os.path.dirname(__file__),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception as e:
        print(f"[{label}] Subprocess spawn failed: {e}")
        return -1
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=payload.encode()),
            timeout=900,
        )
    except asyncio.TimeoutError:
        proc.kill()
        print(f"[{label}] Subprocess timed out (>900s)")
        return -1
    if stderr:
        for line in stderr.decode().split("\n")[-10:]:
            if line.strip():
                print(f"[{label}:err] {line.strip()}")
    valid = -1
    for line in (stdout or b"").decode().split("\n"):
        if line.startswith("__VALID__"):
            try:
                valid = int(line.split()[1])
            except Exception:
                pass
    return valid


async def _auto_refresh_stale_cache() -> None:
    """Background task: refresh stale historical bars + re-run precompute + evaluator.
    Triggered when /scan/combined detects data_date is more than 1 trading day old.
    Non-blocking — the triggering request returns immediately with current data."""
    global _auto_refresh_running, _scan_cache, _scan_running
    if _auto_refresh_running:
        return
    _auto_refresh_running = True
    try:
        stale = _cache.get_stale_tickers()
        if stale:
            print(f"[AutoRefresh] Refreshing {len(stale)} stale tickers...")
            _system_status.update({"stage": "auto_refreshing", "message": f"Catching up {len(stale)} stale tickers...", "progress": 10})
            await _cache.refresh(stale)
            print(f"[AutoRefresh] Refresh done")

        _signal_cache.clear()
        _exit_strategy_cache.clear()

        try:
            _system_status.update({"stage": "auto_refreshing", "message": "Pre-computing backtests + evaluating...", "progress": 60})
            positions = _position_mgr._get_open_positions_sync()
            held = set(p["ticker"] for p in positions) if positions else set()
            live_px = _fresh_live_px()
            valid = await _run_precompute_and_eval_subproc(held, live_px, label="AutoRefresh")
            print(f"[AutoRefresh] Evaluator: {valid} valid entries")
            _system_status.update({"stage": "ready", "message": f"{valid} entries ready", "progress": 100})

            if not _scan_running:
                _scan_cache = None
                _scan_running = True
                asyncio.create_task(_background_scan())
        except Exception as e:
            print(f"[AutoRefresh] Precompute/eval error: {e}")
    except Exception as e:
        print(f"[AutoRefresh] Error: {e}")
    finally:
        _auto_refresh_running = False


async def _background_full_scan() -> None:
    """Evaluate + validate + save the entries cache OFF the request path.

    /scan/combined must never block on this (evaluate_all + validate_top_signals'
    ~15s of earnings/sentiment network calls can exceed the request timeout on a
    cold/new-day machine — that broke the entries tab on 2026-06-20). The endpoint
    triggers this in the background and serves the current/most-recent cache
    immediately; the next poll picks up the fresh result."""
    global _scan_running
    if _scan_running:
        return
    _scan_running = True
    try:
        from strategy_evaluator import evaluate_all, validate_top_signals, save_cache
        positions = _position_mgr._get_open_positions_sync()
        held = set(p["ticker"] for p in positions) if positions else set()
        live_px = _fresh_live_px()
        _system_status.update({"stage": "evaluating", "message": "Evaluating 3,000+ stocks...", "progress": 40})
        signals = await asyncio.to_thread(evaluate_all, 10.0, held, live_px)
        _system_status.update({"stage": "validating", "message": "Checking earnings, sentiment...", "progress": 70})
        signals = await validate_top_signals(signals, top_n=50)
        save_cache(signals)
        _system_status.update({"stage": "ready", "message": f"{sum(1 for s in signals if not s.vetoed)} entries ready", "progress": 100})
    except Exception as e:
        print(f"[BackgroundScan] error: {e}")
        _system_status.update({"stage": "error", "message": f"Scan failed: {e}", "progress": 0})
    finally:
        _scan_running = False


def _mom_stat(ticker: str, col: str) -> float:
    """Momentum backtest stat from backtest_cache, NULL-safe (NULL column → 0)."""
    row = _cache.conn.execute(f"SELECT {col} FROM backtest_cache WHERE ticker=?", (ticker,)).fetchone()
    return row[0] if row and row[0] is not None else 0


try:
    from zoneinfo import ZoneInfo as _ZoneInfo
    _ET_TZ = _ZoneInfo("America/New_York")
except Exception:  # tzdata missing in container — fall back to manual DST rule
    _ET_TZ = None


def _now_et() -> datetime:
    """Current time in US Eastern, DST-aware (UTC-4 in summer, UTC-5 in winter)."""
    from datetime import timezone, timedelta
    if _ET_TZ is not None:
        return datetime.now(_ET_TZ)
    # Manual rule: DST from 2nd Sunday of March to 1st Sunday of November
    utc = datetime.now(timezone.utc)
    year = utc.year

    def _nth_sunday(month: int, n: int) -> datetime:
        d = datetime(year, month, 1, 7, tzinfo=timezone.utc)  # 2am ET ≈ 7utc
        first_sunday = d + timedelta(days=(6 - d.weekday()) % 7)
        return first_sunday + timedelta(days=7 * (n - 1))

    is_dst = _nth_sunday(3, 2) <= utc < _nth_sunday(11, 1)
    return utc.astimezone(timezone(timedelta(hours=-4 if is_dst else -5)))


def _expected_last_trading_date() -> str:
    """Most recent trading-day close that should be in the cache, in ET.

    Mid-session (before 4pm ET): yesterday's close (today's bar doesn't exist yet).
    After 4:30pm ET on a weekday: today's close (Tiingo finalizes within ~30min).
    Weekends: last Friday.
    """
    from datetime import timezone, timedelta
    et = _now_et()
    d = et.date()
    if d.weekday() == 5:        # Sat → Fri
        d = d - timedelta(days=1)
    elif d.weekday() == 6:      # Sun → Fri
        d = d - timedelta(days=2)
    elif d.weekday() == 0 and (et.hour < 16 or (et.hour == 16 and et.minute < 30)):
        # Mon mid-session → Fri close
        d = d - timedelta(days=3)
    elif et.hour < 16 or (et.hour == 16 and et.minute < 30):
        # Tue–Fri mid-session → previous trading day
        d = d - timedelta(days=1)
    return d.strftime('%Y-%m-%d')


def _cache_is_stale(data_date_str: str, max_trading_days: int = 0) -> bool:
    """True if data_date is older than the most recent trading day's close
    (i.e. cache hasn't ingested the latest available bar)."""
    if not data_date_str:
        return True
    try:
        return data_date_str[:10] < _expected_last_trading_date()
    except Exception:
        return False


def _apply_live_overlay(item: dict) -> dict:
    """Overlay live price onto a signal/opportunity dict and recompute technicals.

    Mutates in place. Updates: price, price_is_live, rsi2, sma50_buffer, atr_pct.
    Applies vetoes: stale-data (>3d gap), below-SMA50, crash (-8%), penny (<$10).
    Safe on dicts from scanner or evaluator — uses universal fields.
    """
    try:
        ticker = item.get("ticker", "")
        if not ticker:
            return item

        live = _price_cache.get(ticker)
        # FRESHNESS GUARD (2026-06-18 stale-price fix): only treat a cached quote
        # as a live intraday price if it was captured TODAY. A stale entry (e.g.
        # yesterday's close left in _price_cache when the IEX batch didn't refresh
        # this ticker) must NOT masquerade as live — that stamped yesterday's price
        # as today's and produced phantom RSI2=0 dips (MOD/IMAX/CRVL bug).
        live_fresh = False
        if live and live.get("price", 0) > 0:
            _ts = live.get("ts")
            if isinstance(_ts, datetime) and _ts.date() == datetime.now().date():
                live_fresh = True
        if live_fresh:
            item["price"] = round(live["price"], 2)
            item["price_is_live"] = True
        else:
            item["price_is_live"] = False

        df = _cache.get(ticker, 365)
        if df is None or len(df) < 50:
            return item

        if not live_fresh:
            # No fresh live quote — fall back to the latest cached bar close so
            # RSI2/SMA50 are recomputed off real data, not a stale "live" value.
            item["price"] = round(float(df["Close"].iloc[-1]), 2)

        closes = df["Close"].dropna().tolist()

        last_cached_date = str(df.index[-1])[:10]
        today = datetime.now().strftime('%Y-%m-%d')
        try:
            cal_gap = (datetime.strptime(today, '%Y-%m-%d') - datetime.strptime(last_cached_date, '%Y-%m-%d')).days
            trading_gap = max(0, int(cal_gap * 5 / 7))
        except Exception:
            trading_gap = 0

        if trading_gap > 3:
            item["vetoed"] = True
            item["veto_reason"] = f"Stale data ({trading_gap}d gap, last: {last_cached_date})"
            item["is_upgrade"] = False
            item["beats_holdings"] = []
            return item

        live_px = item.get("price", 0)
        if live_px > 0 and closes[-1] > 0 and abs(live_px - closes[-1]) / closes[-1] > 0.001:
            closes = closes + [live_px]

        rsi2 = _entry.calc_rsi(closes, 2)
        item["rsi2"] = round(rsi2, 1)

        if len(closes) >= 50:
            sma50 = sum(closes[-50:]) / 50
            if live_px > 0 and sma50 > 0:
                item["sma50_buffer"] = round((live_px - sma50) / sma50 * 100, 1)
                if live_px < sma50:
                    item["vetoed"] = True
                    item["veto_reason"] = f"Below SMA50 (${live_px:.0f} < ${sma50:.0f})"
                    item["is_upgrade"] = False
                    item["beats_holdings"] = []
                    return item

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
                item["atr_pct"] = round(sum(atr_vals) / len(atr_vals) / df_closes[-1] * 100, 2)

        if len(closes) >= 2:
            prev_close = closes[-2]
            if prev_close > 0 and live_px > 0:
                day_chg_pct = (live_px / prev_close - 1) * 100
                if day_chg_pct < -8:
                    item["vetoed"] = True
                    item["veto_reason"] = f"Crash ({day_chg_pct:.1f}% today)"
                    item["is_upgrade"] = False
                    item["beats_holdings"] = []
                    return item

        if live_px > 0 and live_px < 10:
            item["vetoed"] = True
            item["veto_reason"] = f"Price too low (${live_px:.2f} < $10)"
            item["is_upgrade"] = False
            item["beats_holdings"] = []

    except Exception as e:
        print(f"[LiveOverlay] Error for {item.get('ticker', '?')}: {e}")

    return item


# ── Exit Strategy (V2.6 — Research-Backed) ──
# Studies (Connors, Alvarez, BuildAlpha) + our 307,446 trade mega-backtest confirm:
#   - Trailing stops HURT mean reversion (44% WR — worst of all strategies)
#   - Stop losses HURT mean reversion (Connors: "stops hurt performance on hundreds of thousands of trades")
#   - SMA/RSI exits too fast for volatile stocks (+0.38% avg vs Fixed60d +3.48%)
#   - ONLY Fixed time exits work for mean reversion
# V2.7: MR=Fixed60d, MOM=Fixed90d (validated on 48,849 trades + 2026 real-world)
#   - Fixed60d: +3.48% avg, 54.8% WR, PF 1.51 — best per-trade hold
#   - Per-stock WF unreliable on low-trade stocks (e.g., LIND got Trail5 = 3.7%)

_exit_strategy_cache: Dict[str, Dict] = {}  # ticker -> {strategy, wr, avg_ret, ...}
_EXIT_CACHE_TTL = 21600  # 6 hours

_EXIT_STRATEGIES = {
    "Fixed30d": {"type": "fixed", "days": 30},  # legacy V3.2 — kept for back-compat
    "Fixed60d": {"type": "fixed", "days": 60},  # MR / BOTH — V3.4 2026-06-17
    "Fixed90d": {"type": "fixed", "days": 90},  # MOM
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
    max_hold = 45
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



def _select_best_exit(ticker: str, closes: list, _unused_trades: list = None, current_rsi: float = 0, entry_price: float = 0, entry_date: str = "", opens: list = None, strategy: str = "MEAN_REVERSION") -> Dict:
    """Fixed60d exit for MR stocks, Fixed90d for MOMENTUM (V3.4 — 2026-06-17).
    strategy-aware as of 2026-06-19 (was hardcoded Fixed60d for all — MOM positions
    at the held-position endpoint were wrongly evaluated on a 60d timer).

    Switched from Fixed30d to Fixed60d after a clean 13-window rolling walk-forward
    (24mo IS / 6mo OOS / 6mo step) on 17,108 PROD-filtered entries with 487-ticker
    quarantine + survivorship-aware checks:
      Per-trade pooled OOS:    Fixed60d +1.98%/mo vs Fixed30d +2.07%/mo (~tied)
      OOS-2024 portfolio N=4:  Fixed60d +23.2% CAGR vs Fixed30d +6.3% CAGR
      Cross-period worst mo:   Fixed60d +0.94% vs Fixed30d -0.18% (never negative)
      OOS-2024 max drawdown:   Fixed60d -11.6% vs Fixed30d -35% (3× lower DD)
      OOS-2024 Sharpe:         Fixed60d 0.78 vs Fixed30d 0.59
    Dynamic regime-aware exits were tested honestly (HonestDyn family) and beaten by
    Fixed60d once portfolio capacity constraints were applied — longer holds with
    consistent capital deployment win on compounding.

    Logic: Hold exactly 60 trading days from next-day-open entry.
    Backtest per stock to compute WR/avg_ret for display.
    """
    # Key by ticker AND strategy — Fixed60d (MR/BOTH) and Fixed90d (MOM) are
    # different backtests; a shared key returned the MR result for a MOM position.
    cache_key = f"{ticker}:{strategy}"
    current_price = closes[-1] if closes else 0

    # Check cache with TTL
    if cache_key in _exit_strategy_cache:
        cached = _exit_strategy_cache[cache_key]
        cache_time = cached.get("_cached_at", 0)
        if cache_time > 0:
            age = (datetime.now() - datetime.fromtimestamp(cache_time)).total_seconds()
            if age < _EXIT_CACHE_TTL:
                return _evaluate_exit_trigger(cached, closes, current_rsi, current_price, entry_price=entry_price, entry_date=entry_date)

    # Backtest the strategy's fixed hold on this stock's historical data
    _FEE_PCT = 0.30
    hold_days = 90 if strategy == "MOMENTUM" else 60

    rsi2_arr = [50.0] * len(closes)
    for i in range(2, len(closes)):
        deltas = [closes[j] - closes[j-1] for j in range(max(0, i-1), i+1)]
        gains = sum(d for d in deltas if d > 0) / 2
        losses = -sum(d for d in deltas if d < 0) / 2
        rsi2_arr[i] = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)

    sma50_arr = [0.0] * len(closes)
    for i in range(49, len(closes)):
        sma50_arr[i] = sum(closes[i-49:i+1]) / 50

    # Full-sample backtest for Fixed60d stats
    full_trades = []
    last_exit = -1
    for i in range(50, len(closes) - hold_days - 2):
        if rsi2_arr[i] >= 10 or closes[i] <= sma50_arr[i] or sma50_arr[i] <= 0:
            continue
        if i <= last_exit:
            continue
        ed = i + 1
        if ed + hold_days >= len(closes):
            continue
        ep = opens[ed] if opens and ed < len(opens) and opens[ed] > 0 else closes[i]
        if ep <= 0:
            continue
        # exit on the hold_days-th trading bar after the entry open — matches the
        # live timer (_evaluate_exit_trigger fires at trading_days_held >= hold) and
        # the precompute cache (i+1+hold). Was ed+hold-1 (one bar short) (2026-06-19).
        exit_idx = ed + hold_days
        ret = ((closes[exit_idx] - ep) / ep) * 100 - _FEE_PCT
        full_trades.append(ret)
        last_exit = exit_idx

    n = len(full_trades)
    if n < 5:
        wr = 0
        avg_ret = 0
    else:
        wr = round(sum(1 for r in full_trades if r > 0) / n * 100, 1)
        avg_ret = round(sum(full_trades) / n, 2)
    ci_lo, ci_hi = _wilson_ci(sum(1 for r in full_trades if r > 0), n) if n > 0 else (0, 0)

    _strat_label = "Fixed90d" if strategy == "MOMENTUM" else "Fixed60d"
    result = {
        "strategy": _strat_label, "wr": wr,
        "avg_ret": avg_ret, "avg_hold": hold_days,
        "oos_wr": wr, "is_wr": wr,
        "overfitting_ratio": 1.0, "validation_note": f"{_strat_label}_V3.4",
        "overfit": 1.0, "validation": f"{_strat_label}_V3.4",
        "ci_lo": ci_lo, "ci_hi": ci_hi,
        "oos_ci_lo": ci_lo, "oos_ci_hi": ci_hi,
        "_cached_at": datetime.now().timestamp(),
    }
    _exit_strategy_cache[cache_key] = result

    return _evaluate_exit_trigger(result, closes, current_rsi, current_price, entry_price=entry_price, entry_date=entry_date)


def _evaluate_exit_trigger(cached: Dict, closes: list, current_rsi: float, current_price: float, entry_price: float = 0, entry_date: str = "") -> Dict:
    """Check if Hybrid21d exit is triggered RIGHT NOW.

    V3.1: Hybrid21d exit for MR. Hold 7d min, then trail -3% from peak
    if profit > 5%. Max 21 trading days.
    Backtested: 62.9% WR, +2.63% avg, PF 1.80, +0.164/day.

    MOM positions: Fixed60d exit (momentum needs time to play out).
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

    # NO HARD STOP — backtested on 46,829 trades: stops HURT mean reversion
    # With stop: WR 48.3%, avg +0.64% | Without: WR 50.1%, avg +0.98%
    # Connors/Alvarez/BuildAlpha research + our data all confirm

    # Determine hold target based on strategy
    is_hybrid = "Hybrid" in strategy
    hold_target = int(cached.get("avg_hold", 21)) if is_hybrid else _EXIT_STRATEGIES.get(strategy, {}).get("days", 60)
    # Fallback for unknown strategies
    if hold_target <= 0:
        hold_target = 21

    exit_price = round(current_price * (1 + cached.get("avg_ret", 0) / 100), 2)
    trading_days_held = 0

    if entry_date:
        try:
            from datetime import date as _date
            entry_d = _date.fromisoformat(entry_date)
            today_d = _date.today()
            trading_days_held = sum(
                1 for n in range((today_d - entry_d).days)
                if (entry_d + timedelta(days=n + 1)).weekday() < 5
            )

            # Hybrid21d: after day 7, trail -3% from peak if profit > 5%
            if is_hybrid and trading_days_held >= 7 and pnl_pct > 5.0:
                trail_level = round(peak_price * 0.97, 2)  # -3% from peak
                if current_price < trail_level:
                    triggered = True
                    exit_price = trail_level
                else:
                    exit_price = trail_level  # show trailing level

            # Max hold exit
            if not triggered and trading_days_held >= hold_target:
                triggered = True

        except Exception:
            triggered = False

    # ── MOMENTUM OVERRIDE (MOMENTUM/Fixed90d positions ONLY) ──
    # If the timer triggers but the stock is profitable (>5%) AND trending up
    # (price > SMA5), switch to an 8% trailing stop from peak to let it run.
    # GATED TO MOMENTUM (2026-06-19): a 32,607-trade backtest showed applying this
    # to MR/Fixed60d HURTS — it cuts the median affected MR trade by -3.0% (5,649
    # worse vs 3,147 better) and turns the OOS median negative (-0.22% vs +0.20%
    # pure Fixed60d), with only a tail-driven mean bump. Confirms "stops hurt mean
    # reversion." MR/BOTH now let the Fixed60d timer fire, as the strategy requires.
    MOMENTUM_PNL_THRESHOLD = 5.0
    TRAILING_STOP_PCT = 8.0

    if strategy == "Fixed90d" and triggered and pnl_pct >= MOMENTUM_PNL_THRESHOLD and current_price > sma5 > 0:
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
        "strategy": strategy, "wr": wr, "avg_ret": avg_ret, "avg_hold": hold_target,
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


def _ev_score(ret: float, wr: float, trades: int) -> float:
    """Unified expected-value score: Bayesian-shrunk (ret × WR / 100).
    Single source of truth — entries, holdings, /analyze, rotation all call this.
    Priors: universe ret 2.85%, universe WR 53.5%; phantom trades 20 (ret) / 10 (WR).
    Small samples pulled hard toward priors; 50+ trades ≈ face value."""
    if trades <= 0 or wr <= 0:
        return 0.0
    from strategy_evaluator import _bayesian_ret
    shrunk_ret = _bayesian_ret(ret, trades)
    wins = int(round(wr * trades / 100))
    shrunk_wr = _bayesian_wr(wins, trades)
    return round(shrunk_ret * shrunk_wr / 100, 2)


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
        # Fallback: try fetching from Tiingo directly (for cold cache on Fly)
        # Tiingo is primary — works on Fly.io unlike Stooq which is blocked
        try:
            _tiingo_key = os.environ.get("TIINGO_API_KEY", "6f632a60d6188ebc1b92221e83d4fba37e2a5c42")
            start_d = (datetime.now() - timedelta(days=800)).strftime('%Y-%m-%d')
            end_d = datetime.now().strftime('%Y-%m-%d')
            tiingo_url = f'https://api.tiingo.com/tiingo/daily/{ticker}/prices?startDate={start_d}&endDate={end_d}&token={_tiingo_key}'
            import requests
            resp = requests.get(tiingo_url, headers={'Content-Type': 'application/json'}, timeout=12)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) >= 60:
                    tiingo_df = pd.DataFrame(data)
                    tiingo_df['date'] = pd.to_datetime(tiingo_df['date']).dt.tz_localize(None)
                    tiingo_df = tiingo_df.set_index('date').sort_index()
                    if 'adjClose' in tiingo_df.columns:
                        col_map = {'adjOpen': 'Open', 'adjHigh': 'High',
                                   'adjLow': 'Low', 'adjClose': 'Close', 'adjVolume': 'Volume'}
                    else:
                        col_map = {'open': 'Open', 'high': 'High',
                                   'low': 'Low', 'close': 'Close', 'volume': 'Volume'}
                    tiingo_df = tiingo_df.rename(columns=col_map)
                    tiingo_df = tiingo_df[['Open', 'High', 'Low', 'Close', 'Volume']]
                    for col in tiingo_df.columns:
                        tiingo_df[col] = pd.to_numeric(tiingo_df[col], errors='coerce')
                    _cache.store(ticker, tiingo_df)
                    df = tiingo_df
                    print(f"[TechFallback] Fetched {ticker} from Tiingo: {len(df)} bars")
                else:
                    return {}
            else:
                return {}
        except Exception as e:
            print(f"[TechFallback] Tiingo failed for {ticker}: {e}")
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
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 0

    # ATR(14)% and 20d return — needed so holdings can be composite-scored with
    # the same inputs scan candidates get (rotation comparison).
    atr_pct = 0.0
    if len(closes) >= 15:
        trs = []
        for j in range(len(closes) - 14, len(closes)):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j - 1]),
                     abs(lows[j] - closes[j - 1]))
            trs.append(tr)
        atr = sum(trs) / 14
        atr_pct = atr / closes[-1] * 100 if closes[-1] > 0 else 0
    ret_20d = ((closes[-1] - closes[-21]) / closes[-21] * 100) if len(closes) >= 21 and closes[-21] > 0 else 0

    regime_info = RegimeDetector.detect(closes, highs, lows, volumes)
    regime = regime_info.regime.value if hasattr(regime_info, "regime") else str(regime_info)

    # Backtest (60-trading-day hold — matches live Fixed60d exit; RSI<10 entry,
    # next-day open, fee-adjusted, non-overlapping trades).
    # Uses pre-computed arrays: O(n) instead of O(n²) — 63x faster
    _FEE_PCT = 0.30
    _HOLD = 60  # entry at open i+1, exit at close i+1+_HOLD (= live Fixed60d)
    rsi2_arr = _rsi2_array(closes)
    sma50_arr = _sma_array(closes, 50)
    last_exit_day = -1
    trades = []
    for i in range(50, len(closes) - _HOLD - 2):
        if i <= last_exit_day:
            continue
        if rsi2_arr[i] < 10 and closes[i] >= 10:
            entry_p = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
            ret = ((closes[i + 1 + _HOLD] - entry_p) / entry_p) * 100 - _FEE_PCT
            trades.append({"return": ret, "win": ret > 0, "rsi": rsi2_arr[i]})
            last_exit_day = i + 1 + _HOLD

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

    # Exit zone analysis: forward 60-day returns at CURRENT RSI zone using ALL data points
    # This answers: "When this stock was at RSI X historically, what was the 60-day forward return?"
    # Fixed60d hold — consistent with the entry backtest above and the live exit.
    # Reuses pre-computed rsi2_arr from above (no recalculation)
    exit_zone_trades_list = []
    ez_last_exit = -1
    for i in range(50, len(closes) - _HOLD - 2):
        if i <= ez_last_exit:
            continue
        if zone_low <= rsi2_arr[i] < zone_high:
            entry_px = opens[i + 1] if opens and i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
            exit_px = closes[i + 1 + _HOLD]
            ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT
            exit_zone_trades_list.append({"return": ret, "win": ret > 0})
            ez_last_exit = i + 1 + _HOLD

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
        "price": round(closes[-1], 2),
        "atr_pct": round(atr_pct, 2),
        "volume_ratio": round(vol_ratio, 2),
        "ret_20d": round(ret_20d, 2),
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

    # Network-dependent rules disabled in the portfolio request path —
    # earnings/sentiment checks here added ~3s × N positions of latency every
    # time _signal_cache was cleared by cache_refresh_loop. Earnings warnings
    # are still surfaced via /analyze and the scanner Phase-3 veto, which is
    # the right gate for new entries.
    _run_network = False

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

    # Model EXIT signal: both overall WR AND exit zone WR fail 65% → valid early exit
    # Rule from CLAUDE.md: "Model EXIT signal (both ATLAS WR + zone WR fail 65%) — EXIT"
    _wr = tech.get("win_rate", 100)
    _ez_wr = tech.get("exit_zone_wr", 100)
    _ez_trades = tech.get("exit_zone_trades", 0)
    if _wr < MIN_WR and _ez_wr < MIN_WR and _ez_trades >= 5:
        exit_triggered = True
        issues.append(f"Model EXIT: WR {_wr:.0f}% + zone WR {_ez_wr:.0f}% both < {MIN_WR}%")

    # Determine signal from issues + hybrid exit strategy
    critical = [i for i in issues if any(k in i for k in ["Below SMA50", "BEAR regime", "CRASH", "Low WR", "Model EXIT"])]

    if any("CRASH" in i for i in critical):
        signal = "SELL"
    elif any("Model EXIT" in i for i in critical):
        signal = "EXIT"
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


# ── Strategy Health Monitor ──

def _strategy_health() -> dict:
    """Compare last 20 closed trades' rolling WR against backtest expectation.
    If live WR drops >15pp below backtest (53.5%), flag degradation.
    Research: catches regime shifts before they wipe out gains."""
    import sqlite3 as _sql
    db_path = os.path.join(os.path.dirname(__file__), "data", "positions.db")
    try:
        conn = _sql.connect(db_path)
        conn.row_factory = _sql.Row
        # Last 20 closed trades with realized P&L
        rows = conn.execute(
            "SELECT t.ticker, t.realized_pnl, t.date FROM transactions t "
            "WHERE t.action='SELL' AND t.realized_pnl IS NOT NULL "
            "ORDER BY t.date DESC LIMIT 20"
        ).fetchall()
        conn.close()

        if len(rows) < 5:
            return {"status": "INSUFFICIENT", "message": f"Only {len(rows)} closed trades (need 5+)",
                    "rolling_wr": 0, "expected_wr": 53.5, "trades_analyzed": len(rows)}

        # Filter out break-even / dust trades
        meaningful = [r for r in rows if abs(r["realized_pnl"]) > 1.0]
        if len(meaningful) < 5:
            meaningful = list(rows)

        wins = sum(1 for r in meaningful if r["realized_pnl"] > 0)
        losses = len(meaningful) - wins
        rolling_wr = wins / len(meaningful) * 100

        # Profit factor: total wins / total losses (more meaningful than WR for MR)
        gross_wins = sum(r["realized_pnl"] for r in meaningful if r["realized_pnl"] > 0)
        gross_losses = abs(sum(r["realized_pnl"] for r in meaningful if r["realized_pnl"] <= 0))
        pf = round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0
        net_pnl = round(sum(r["realized_pnl"] for r in meaningful), 2)

        expected_wr = 53.5  # Universe backtest WR
        gap = rolling_wr - expected_wr

        # Judge by BOTH WR and profit factor — low WR + high PF = strategy working (big winners)
        if pf >= 1.5:
            status = "HEALTHY"
            message = f"WR {rolling_wr:.0f}% low but PF {pf:.1f}x — big wins offset losses (${net_pnl:+,.0f})"
        elif pf >= 1.0:
            status = "OK"
            message = f"WR {rolling_wr:.0f}%, PF {pf:.1f}x — breakeven, monitor (${net_pnl:+,.0f})"
        elif gap < -20 and pf < 1.0:
            status = "DEGRADED"
            message = f"WR {rolling_wr:.0f}%, PF {pf:.1f}x — losing money (${net_pnl:+,.0f})"
        elif gap < -10:
            status = "WARNING"
            message = f"WR {rolling_wr:.0f}%, PF {pf:.1f}x — below expected (${net_pnl:+,.0f})"
        elif gap > 10:
            status = "OUTPERFORMING"
            message = f"WR {rolling_wr:.0f}%, PF {pf:.1f}x — strategy working well (${net_pnl:+,.0f})"
        else:
            status = "HEALTHY"
            message = f"WR {rolling_wr:.0f}%, PF {pf:.1f}x — within expected range (${net_pnl:+,.0f})"

        return {
            "status": status,
            "message": message,
            "rolling_wr": round(rolling_wr, 1),
            "expected_wr": expected_wr,
            "trades_analyzed": len(meaningful),
            "wins": wins,
            "losses": losses,
            "gap_pp": round(gap, 1),
            "profit_factor": pf,
            "net_pnl": net_pnl,
        }
    except Exception as e:
        return {"status": "ERROR", "message": str(e), "rolling_wr": 0, "expected_wr": 53.5, "trades_analyzed": 0}


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
            strategy_health=_strategy_health(),
        )

    # Use cached prices (SQLite-seeded or Finnhub-refreshed) — NEVER block on API calls.
    # Background quote_refresh_loop() keeps prices fresh every 60s.
    #
    # Upcoming-event lookups for the "Next Event" column. Both are 30-min cached
    # (first poll pays the batch fetch, the rest are instant) so this stays cheap
    # on a frequently-polled endpoint:
    #   - next_earnings: forward Finnhub calendar (when does it next report?)
    #   - catalysts: biotech trial readouts / FDA / PDUFA within ±14d
    held_tickers = [p["ticker"] for p in positions]
    try:
        next_earnings_map = await _portfolio_next_earnings_cached(held_tickers)
    except Exception:
        next_earnings_map = {}
    try:
        _cat = await _portfolio_catalysts_cached(held_tickers)
        catalyst_map = {h["ticker"]: h for h in _cat.get("upcoming", [])}
    except Exception:
        catalyst_map = {}

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

        # Re-evaluate exit trigger with current price.
        # V3.4 (2026-06-17): MR/BOTH positions use Fixed60d (was Fixed30d).
        # MOM positions use Fixed90d. _technicals_cache stores Fixed60d for ALL
        # tickers (strategy-agnostic) — so we override the cached strategy with
        # the position's actual strategy before evaluating, so MOM positions
        # don't hit the 60d cap when they should run to 90d.
        if tech and tech.get("exit_strategy"):
            df = _cache.get(ticker, 365)
            if df is not None and len(df) >= 10:
                closes_live = df["Close"].dropna().tolist()
                rsi_live = tech.get("rsi2", -1)
                pos_strategy_eval = pos.get("strategy", "MEAN_REVERSION") or "MEAN_REVERSION"
                expected_exit_strat = "Fixed90d" if pos_strategy_eval == "MOMENTUM" else "Fixed60d"
                # Use exit strategy cache if it matches the position's strategy;
                # otherwise build a fresh exit_cached with the right strategy
                # name so _evaluate_exit_trigger picks the correct hold target.
                exit_cached = _exit_strategy_cache.get(ticker)
                if not exit_cached or exit_cached.get("strategy") != expected_exit_strat:
                    exit_cached = {
                        "strategy": expected_exit_strat,
                        "wr": tech.get("exit_strategy_wr", 0),
                        "avg_ret": tech.get("exit_strategy_ret", 0),
                        "avg_hold": tech.get("exit_strategy_hold", 60 if expected_exit_strat == "Fixed60d" else 90),
                    }
                live_exit = _evaluate_exit_trigger(
                    exit_cached,
                    closes_live, rsi_live, live_price, entry_price,
                    entry_date=pos_entry_date
                )
                old_triggered = tech.get("exit_triggered", False)
                tech["exit_strategy"] = expected_exit_strat  # surface the right name in the UI
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

        # Check market regime for exit decisions
        _regime = _check_market_regime()
        _regime_name = _regime.get("regime", "HEALTHY")
        _is_true_bear = _regime_name == "BEAR"  # Only true bear (drawdown >20% or >5% below SMA200)

        # Trading-days held since entry — needed by the Model EXIT gate below.
        _days_held_for_exit = 0
        try:
            from datetime import date as _date
            _entry_d = _date.fromisoformat(pos.get("entry_date", ""))
            _today_d = _date.today()
            _days_held_for_exit = sum(
                1 for n in range((_today_d - _entry_d).days)
                if (_entry_d + timedelta(days=n + 1)).weekday() < 5
            )
        except Exception:
            pass

        # Priority 1: Fixed60d exit triggered
        if exit_triggered:
            signal = "EXIT"
            issues.append(f"Exit triggered ({tech.get('exit_strategy', '')}: {tech.get('exit_label', '')})")

        # Priority 2: Earnings within 7 days — binary event risk, always EXIT
        # (CLAUDE.md MANDATORY). Uses the FORWARD Finnhub/Tiingo calendar
        # (next_earnings_map ← next_earnings_batch), NOT the news-tag detector
        # which false-positives on ~all tickers. Wired 2026-06-19 (was only a
        # comment; the documented earnings exit never actually fired).
        elif ((next_earnings_map.get(ticker) or {}).get("days_to") is not None
              and 0 <= next_earnings_map[ticker]["days_to"] <= 7):
            signal = "EXIT"
            issues.append(f"Earnings in {next_earnings_map[ticker]['days_to']}d — exit before binary event")

        # Priority 3: TRUE bear market crash exit (only when regime = BEAR, not CORRECTION/CAUTION)
        # Backtested: 1,005 trades, 500 stocks, 5yr
        elif _is_true_bear and atlas_wr < 65 and pnl_pct < 0:
            signal = "EXIT"
            issues.append(f"BEAR EXIT: WR {atlas_wr:.0f}%<65% + losing {pnl_pct:+.1f}% in bear")
        elif _is_true_bear and pnl_pct >= 5:
            signal = "EXIT"
            issues.append(f"BEAR EXIT: Profitable {pnl_pct:+.1f}% in bear — lock gains")

        # Priority 4: Bad backtest stats (strong evidence, any regime).
        # Winner-protect: don't EXIT a profitable trade on historical stats —
        # the trade itself is already proving the stats wrong. Let the per-strategy
        # exit (Hybrid21d trail / Fixed90d timer) handle when to actually exit.
        elif (ez_trades >= 20 and ez_ret < -2 and atlas_wr < 50
              and pnl_pct < 5.0):  # winner-protect: don't exit a >5% trending winner
            signal = "EXIT"
            issues.append(f"Bad backtest ({ez_ret:+.1f}% zone, {atlas_wr:.0f}% WR on {atlas_trades}t)")

        # Priority 5: In correction/caution, just add info — don't force exit
        elif _is_true_bear and atlas_wr >= 65 and pnl_pct < 0:
            signal = "HOLD"
            issues.append(f"BEAR HOLD: WR {atlas_wr:.0f}%>=65% losing {pnl_pct:+.1f}% — hold (55% improve historically)")

        # Model EXIT: both ATLAS WR and zone WR fail 65% (CLAUDE.md rule).
        # Winner-protect: skip when up >5% — historical WR is clearly wrong
        # for this trade right now (it's winning). Let trail/timer handle exit.
        # Per CLAUDE.md "NOT valid: RSI rising (trade working)" — same idea.
        # Min-hold gate: don't fire on fresh positions. Hybrid21d MR exits have a
        # 7-day minimum; flagging a position bought today as EXIT contradicts the
        # entry filters that just approved it.
        elif (ez_trades >= 5 and atlas_trades >= 5
              and ez_wr < 65 and atlas_wr < 65
              and pnl_pct < 5.0
              and _days_held_for_exit >= 7):  # respect Hybrid21d's 7-day min
            signal = "EXIT"
            issues.append(f"Model EXIT: WR {atlas_wr:.0f}% + zone WR {ez_wr:.0f}% both < 65% ({pnl_pct:+.1f}%, {_days_held_for_exit}d held)")

        else:
            # Non-bear market: standard checks
            if not above_sma50:
                issues.append("Below SMA50")
            if rsi2 > 80:
                issues.append("Overbought (RSI > 80) — trade working")
            if atlas_trades > 0 and atlas_trades < 10:
                issues.append(f"Low sample ({atlas_trades} trades)")
            if ez_trades >= 10 and ez_wr < 65:
                issues.append(f"Zone WR {ez_wr:.0f}% below 65% ({ez_trades}t) — monitor")
            if atlas_trades >= 10 and atlas_wr < 55:
                issues.append(f"ATLAS WR {atlas_wr:.0f}% below 55% ({atlas_trades}t) — weak")

        # Crash day warning (informational only)
        if day_chg < -8 and not any("CRASH" in i for i in issues):
            issues.append(f"CRASH ({day_chg:.1f}% today)")

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

        # V4.2 Rotation — operational rules (CLAUDE.md "Rotation v3.1: min 15d hold
        # + protect winners >5% trending"). V4.0 backtest preferred 2d/no-protection
        # for raw return, but in practice it churns fresh entries and exits winners
        # mid-trend. Per CLAUDE.md operational rule, protect:
        #   1. Anything held < 15 trading days (trade hasn't had time to work)
        #   2. Anything up >5% (winner that's still trending)
        # Plus the V4.1 fixes: candidates trades>=10 (matches entries tab) and
        # both sides scored on composite_score 0-100 (apples-to-apples).
        ROTATION_SCORE_GAP = 15.0
        ROTATION_MIN_DAYS = 15
        ROTATION_MIN_TARGET_TRADES = 10
        ROTATION_WINNER_PROTECT_PCT = 5.0
        _rot_target = None
        _rot_gap = 0.0
        # Winner-protection veto — CLAUDE.md "protect winners >5% trending"
        _winner_protected = pnl_pct > ROTATION_WINNER_PROTECT_PCT
        if (days_held >= ROTATION_MIN_DAYS
                and not _winner_protected
                and _regime_name not in ("DANGER", "CRISIS")):
            try:
                # V3.4 SSOT (2026-06-17): rotation reads from strategy_evaluator's
                # entries cache — the SAME source as the Entries tab the user sees.
                # Previously read from /scan/opportunities cache which had a DIFFERENT
                # veto chain and used composite_score; that meant rotation could
                # suggest tickers NOT in the user's Entries tab — confusing UX.
                # Now: rotation candidates = whatever passes V3.3.1 gates + V3.4
                # BWR scoring (same fields, same logic, same SSOT).
                from strategy_evaluator import load_cache as _load_entries
                opps = _load_entries() or []
                _held_set = {p.get("ticker") for p in positions}
                _valid = [
                    o for o in opps
                    if not o.get("vetoed")
                    and o.get("ticker") != ticker
                    and (o.get("trades", 0) or 0) >= ROTATION_MIN_TARGET_TRADES
                    and o.get("ticker") not in _held_set
                ]
                if _valid and tech and tech.get("atr_pct") is not None:
                    # V3.4 SSOT: entries cache doesn't pre-compute composite_score
                    # (that's added by /scan/combined response handler). Compute
                    # it inline here so we can apples-to-apples vs the holding.
                    for _o in _valid:
                        _o_inputs = {
                            "price": _o.get("price", 0),
                            "rsi2": _o.get("rsi2", 50),
                            "atr_pct": _o.get("atr_pct", 0),
                            "sma50_buffer": _o.get("sma50_buffer", 0),
                            "volume_ratio": _o.get("volume_ratio", 0),
                            "ret_20d": _o.get("ret_20d", 0),
                            "win_rate": _o.get("confidence", 0),
                            "avg_return": _o.get("expected_return", 0),
                            "trades": _o.get("trades", 0),
                            "analyst_consensus": _o.get("analyst_consensus", ""),
                            "analyst_upside": 0,
                            "sentiment_score": 0,
                        }
                        _o["_inline_composite"], _ = _compute_composite_score(_o_inputs)
                    _best = max(_valid, key=lambda o: o.get("_inline_composite", 0) or 0)
                    # Composite-score the holding with the SAME inputs candidates
                    # get (price/ATR/volume now provided by _get_technicals).
                    # Skip the comparison entirely if technicals are missing —
                    # a zero-input score of ~20 vs real candidates at 60+ used
                    # to generate ROTATE on every healthy holding.
                    h_inputs = {
                        "price": live_price if live_price > 0 else tech.get("price", 0),
                        "rsi2": tech.get("rsi2", 50),
                        "atr_pct": tech.get("atr_pct", 0),
                        "sma50_buffer": tech.get("sma50_buffer", 0),
                        "volume_ratio": tech.get("volume_ratio", 0),
                        "ret_20d": tech.get("ret_20d", 0),
                        "win_rate": tech.get("win_rate", 0),
                        "avg_return": tech.get("avg_return", 0),
                        "trades": tech.get("total_trades", 0),
                        "zone_return": tech.get("zone_return", 0),
                        "zone_win_rate": tech.get("zone_wr", 0),
                        "zone_trades": tech.get("zone_trades", 0),
                        # Holdings carry no analyst/sentiment data; leave the
                        # same neutral defaults unvalidated candidates get.
                        "analyst_consensus": "",
                        "analyst_upside": 0,
                        "sentiment_score": 0,
                    }
                    h_score, _ = _compute_composite_score(h_inputs)
                    _best_comp = _best.get("_inline_composite", 0) or 0
                    _gap = _best_comp - h_score
                    if _gap > ROTATION_SCORE_GAP:
                        signal = "ROTATE"
                        _rot_target = _best["ticker"]
                        _rot_gap = round(_gap, 1)
                        issues.append(f"ROTATE to {_best['ticker']} (score {_best_comp:.0f} vs {h_score:.0f}, gap {_rot_gap})")
            except Exception:
                pass

        # Exit strategy V3.4 (2026-06-17): MR/BOTH=Fixed60d, MOM=Fixed90d.
        # Switched MR from Fixed30d after honest 13-window walk-forward portfolio sim
        # showed Fixed60d at N=4 delivers +17pp OOS-2024 CAGR with 3x lower drawdown.
        pos_strategy = pos.get("strategy", "MEAN_REVERSION") or "MEAN_REVERSION"
        if pos_strategy == "MOMENTUM":
            exit_strat_name = "Fixed90d"
            exit_target_days = 90
        else:
            exit_strat_name = "Fixed60d"
            exit_target_days = 60

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
            day_change_pct=round(day_chg, 2) if -30 <= day_chg <= 30 else 0,  # Cap: split-adjusted stale prev_close protection
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
            # For MOMENTUM positions, use momentum backtest stats (not MR)
            win_rate=_mom_stat(ticker, "mom_wr") if pos_strategy == "MOMENTUM" else (tech.get("win_rate", 0) if tech else 0),
            bayesian_wr=_mom_stat(ticker, "mom_wr") if pos_strategy == "MOMENTUM" else (tech.get("bayesian_wr", tech.get("win_rate", 0)) if tech else 0),
            wilson_lower=tech.get("wilson_lower", 0) if tech else 0,
            trades_per_year=tech.get("trades_per_year", 0) if tech else 0,
            total_trades=_mom_stat(ticker, "mom_trades") if pos_strategy == "MOMENTUM" else (tech.get("total_trades", 0) if tech else 0),
            avg_return=_mom_stat(ticker, "mom_avg_return") if pos_strategy == "MOMENTUM" else (tech.get("avg_return", 0) if tech else 0),
            zone_return=tech.get("zone_return", 0) if tech else 0,
            zone_wr=tech.get("zone_wr", 0) if tech else 0,
            zone_trades=tech.get("zone_trades", 0) if tech else 0,
            rsi_zone=tech.get("rsi_zone", "") if tech else "",
            strategy=pos_strategy,
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
            exit_strategy_validation=f"UNIVERSAL_FIXED{exit_target_days}D",
            exit_strategy_oos_ci_lo=tech.get("exit_strategy_oos_ci_lo", 0) if tech else 0,
            exit_strategy_oos_ci_hi=tech.get("exit_strategy_oos_ci_hi", 0) if tech else 0,
            sparkline=tech.get("sparkline", []) if tech else [],
            # 2yr safety gate
            wr_2yr=tech.get("wr_2yr", 0) if tech else 0,
            avg_ret_2yr=tech.get("avg_ret_2yr", 0) if tech else 0,
            trades_2yr=tech.get("trades_2yr", 0) if tech else 0,
            rotation_target=_rot_target,
            rotation_score_gap=_rot_gap,
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
        # Yahoo chart provides real extended hours prices when available
        ext = _extended_hours_cache.get(ticker)
        detail.market_session = _get_market_session()
        if ext and ext["ext_price"] > 0:
            detail.ext_price = ext["ext_price"]
            detail.ext_change_pct = ext["ext_change_pct"]
            detail.market_session = ext["session"]
            # ext_price is DISPLAY ONLY (CNBC pre-market/after-hours)
            # current_price + current_value use Tiingo IEX (matches broker)
            # Don't override P&L or value with CNBC — it diverges from broker
        # Even without ext data, fix day_chg if Finnhub quote has fresh prev_close
        elif quote and quote.get("price", 0) > 0:
            fh_prev = quote.get("prev_close", 0)
            if fh_prev > 0:
                detail.day_change_pct = round(((quote["price"] - fh_prev) / fh_prev) * 100, 2)

        # Upcoming events — next scheduled earnings + any biotech catalyst ahead.
        _ne = next_earnings_map.get(ticker)
        if _ne and _ne.get("date"):
            detail.next_earnings_date = _ne["date"]
            detail.days_to_earnings = _ne.get("days_to")
        _cat_hit = catalyst_map.get(ticker)
        if _cat_hit:
            detail.next_catalyst = _cat_hit.get("title", "")
            detail.next_catalyst_date = _cat_hit.get("date", "")
            detail.next_catalyst_type = _cat_hit.get("catalyst_type", "other")

        details.append(detail)

    # Portfolio value = sum of current_value (based on last regular close)
    # ext_price shown separately per position — NOT mixed into total
    total_value = sum(d.current_value for d in details)

    for d in details:
        d.weight = round(d.current_value / total_value * 100, 1) if total_value else 0

    total_cost = sum(d.cost_basis for d in details)
    total_pnl = total_value - total_cost
    wr_list = [d.win_rate for d in details if d.win_rate > 0]

    # Daily P&L: only during REGULAR session (actual trading day)
    # Pre-market/after-hours moves show via ext_price on each position, NOT as day P&L
    session = _get_market_session()
    day_pnl = 0
    if session == "REGULAR":
        for d in details:
            if d.day_change_pct != -100 and d.current_value > 0:
                day_pnl += d.current_value * d.day_change_pct / (100 + d.day_change_pct)
    # Outside regular hours: day P&L = 0 (trading hasn't happened yet)
    day_pnl_pct = (day_pnl / total_value * 100) if total_value > 0 else 0

    # Realized P&L from closed positions
    tx_summary = _position_mgr.get_transaction_summary()

    # Broker-verified balances
    _total_deposited = _total_deposited_now()  # baseline + DB DEPOSITs
    _total_fees_all = round(tx_summary.get("total_fees", 0), 2)
    _total_tax_all = round(tx_summary.get("total_tax", 0), 2)
    _realized = tx_summary.get("total_realized_pnl", 0)

    # Cash from live ledger (respects 10-free-trades/month rule via stored fee column).
    # Stays 0-floored even when formula goes negative due to ledger drift; pin via
    # BROKER_CASH_OVERRIDE env var if you want to anchor to broker reality.
    _cash = _compute_cash_balance(_total_deposited)

    # Total portfolio value = positions + cash
    total_value_with_cash = total_value + _cash

    # Yesterday P&L and 7-day P&L from price history
    _yesterday_pnl = 0.0
    _week_pnl = 0.0
    for d in details:
        ticker = d.ticker
        df = _cache.get(ticker, 365)
        if df is not None and len(df) >= 2:
            closes = df["Close"].values
            # Yesterday P&L = (close[-1] - close[-2]) * shares
            if len(closes) >= 2:
                _yesterday_pnl += (float(closes[-1]) - float(closes[-2])) * d.shares
            # 7-day P&L = (close[-1] - close[-6]) * shares (5 trading days)
            if len(closes) >= 6:
                _week_pnl += (float(closes[-1]) - float(closes[-6])) * d.shares
    _yesterday_pnl_pct = (_yesterday_pnl / (total_value - _yesterday_pnl) * 100) if total_value > _yesterday_pnl else 0
    _week_pnl_pct = (_week_pnl / (total_value - _week_pnl) * 100) if total_value > _week_pnl else 0

    summary = PortfolioSummary(
        total_value=round(total_value_with_cash, 2),
        total_cost=round(total_cost, 2),
        total_pnl=round(total_pnl, 2),
        total_pnl_pct=round(total_pnl / total_cost * 100, 2) if total_cost else 0,
        day_pnl=round(day_pnl, 2),
        day_pnl_pct=round(day_pnl_pct, 2),
        realized_pnl=round(_realized, 2),
        total_fees=_total_fees_all,
        total_tax=_total_tax_all,
        total_deposited=_total_deposited,
        position_count=len(details),
        max_positions=0,        # 0 = no cap; field kept for schema compat
        slots_available=0,      # uncapped — frontend doesn't surface this
        avg_win_rate=round(sum(wr_list) / len(wr_list), 1) if wr_list else 0,
        cash=_cash,
        yesterday_pnl=round(_yesterday_pnl, 2),
        yesterday_pnl_pct=round(_yesterday_pnl_pct, 2),
        week_pnl=round(_week_pnl, 2),
        week_pnl_pct=round(_week_pnl_pct, 2),
        market_session=_get_market_session(),
        timestamp=datetime.now().isoformat(),
    )

    return PortfolioResponse(summary=summary, positions=details, market_regime=_check_market_regime(), strategy_health=_strategy_health())


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

    # Backtest (60-day forward, V3.4: RSI<10, fee-adjusted)
    # Note: ILS Yahoo data has no Open column — use closes as entry proxy
    _FEE_PCT = 0.30
    _HOLD = 60  # match live Fixed60d exit
    last_exit_day = -1
    trades = []
    for i in range(50, len(closes) - _HOLD - 2):
        if i <= last_exit_day:
            continue
        hist = closes[:i + 1]
        h_rsi = _entry.calc_rsi(hist, 2)
        h_sma = _entry.calc_sma(hist, 50)
        if h_rsi < 10 and hist[-1] > h_sma:
            entry_px = closes[i]  # ILS data has no opens — use close as proxy
            exit_px = closes[i + 1 + _HOLD]
            ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT
            trades.append({"return": ret, "win": ret > 0, "rsi": h_rsi})
            last_exit_day = i + 1 + _HOLD

    wr = sum(1 for t in trades if t["win"]) / len(trades) * 100 if trades else 0
    avg_ret = sum(t["return"] for t in trades) / len(trades) if trades else 0

    # Zone analysis
    zone_lo = min(int(rsi2 // 10) * 10, 90)
    zone_hi = 101 if zone_lo == 90 else zone_lo + 10
    zt = [t for t in trades if zone_lo <= t["rsi"] < zone_hi]
    zone_ret = sum(t["return"] for t in zt) / len(zt) if zt else 0
    zone_wr = sum(1 for t in zt if t["win"]) / len(zt) * 100 if zt else 0

    # Exit zone analysis (all RSI values, fee-adjusted, Fixed60d hold)
    exit_zt = []
    for i in range(50, len(closes) - _HOLD - 2):
        hist = closes[:i + 1]
        h_rsi = _entry.calc_rsi(hist, 2)
        if zone_lo <= h_rsi < zone_hi:
            ret = ((closes[i + 1 + _HOLD] - closes[i]) / closes[i]) * 100 - _FEE_PCT
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
        "exit_strategy": "Fixed60d", "exit_strategy_wr": round(wr, 1),
        "exit_strategy_ret": round(avg_ret, 2), "exit_strategy_hold": 60.0,
        "exit_triggered": False, "exit_price": 0, "exit_price_pct": 0,
        "exit_label": f"Hold 60d | +{avg_ret:.1f}% WR {wr:.0f}%",
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

        # Staleness guard — bars older than last trading-day close OR scan file
        # from a prior day → kick off a background refresh (Tiingo bars →
        # precompute → scanner). Non-blocking: this request still returns
        # immediately with live overlays on the existing candidate list. The
        # next poll will pick up the freshly written scan_YYYY-MM-DD.json.
        freshness = result.get("data_freshness") or {}
        latest_close = freshness.get("latest_close") or ""
        bars_stale = _cache_is_stale(latest_close, max_trading_days=1) if latest_close else True
        scan_file_old = (
            _scan_cache_time is not None
            and _scan_cache_time.date() < datetime.now().date()
        )
        result["cache_stale"] = bool(bars_stale or scan_file_old)
        result["refreshing"] = _auto_refresh_running or _scan_running
        if result["cache_stale"] and not _auto_refresh_running:
            print(f"[Scan] cache_stale (bars_stale={bars_stale}, "
                  f"scan_file_old={scan_file_old}, latest_close={latest_close}) "
                  f"→ kicking off auto-refresh")
            asyncio.create_task(_auto_refresh_stale_cache())
            result["refreshing"] = True

        # Fetch live quotes for EVERY visible opportunity via Tiingo IEX batch.
        # _fetch_tiingo_iex_batch chunks into 100-ticker batches automatically,
        # so 200+ tickers is 2-3 HTTP calls (~200ms total). Force-refresh — don't
        # skip tickers already in _price_cache, since the cache can hold a stale
        # price from a prior fetch (e.g., APLD locked at Friday's $41.25 while
        # live is $45.35). Every visible row must have a valid live-recomputed
        # composite_score, not yesterday's reading.
        sorted_opps = sorted(opps, key=lambda o: o.get("composite_score", 0), reverse=True)
        tickers_need_quote = [o.get("ticker", "") for o in sorted_opps
                              if o.get("ticker") and not o.get("vetoed", False)]
        if tickers_need_quote:
            try:
                await _fetch_tiingo_iex_batch(tickers_need_quote)
            except Exception as e:
                print(f"[Scan] Tiingo IEX batch error: {e}")

        # Overlay live prices + recompute RSI(2), SMA50 buffer, ATR%, composite
        # against today's price. Flag stocks whose entry signal has already
        # played out — RSI(2) was <10 at the close that triggered the scan,
        # but if the live overlay shows RSI(2) > 30, the bounce already
        # happened and chasing in is dangerous.
        for opp in opps:
            scan_rsi2 = opp.get("rsi2", 0)
            _apply_live_overlay(opp)
            live_rsi2 = opp.get("rsi2", 0)
            # Signal-expired guard: entered on RSI<10, now RSI risen materially
            # → trade in progress, don't promote to BEST tier.
            if not opp.get("vetoed", False) and scan_rsi2 < 10 and live_rsi2 > 30:
                opp["signal_expired"] = True
                opp["signal_expired_reason"] = (
                    f"RSI(2) recovered from {scan_rsi2:.0f}→{live_rsi2:.0f} — "
                    f"bounce in progress"
                )
            if not opp.get("vetoed", False):
                opp["composite_score"], opp["ranking_factors"] = _compute_composite_score(opp)
                opp["quality_tier"] = _quality_tier(opp["composite_score"])
                # Cap expired signals at FAIR — they're not actionable as fresh entries.
                if opp.get("signal_expired") and opp["composite_score"] > 49:
                    opp["composite_score"] = 49
                    opp["quality_tier"] = _quality_tier(49)
                    opp["ranking_factors"] = (opp.get("ranking_factors") or "") + " EXPIRED:CAP49"
                opp["meets_strict"] = _meets_strict_criteria(opp)

        # Regime gate enforcement — these are all MR signals (deep scanner), so
        # both pause_entries (DANGER/CRISIS) and pause_mr (WEAK) veto them.
        # Self-correcting: the regime-gate veto is re-applied or cleared on every
        # request, and never touches vetoes set by the scanner itself.
        _apply_regime_gate(opps, result["market_regime"], mr_only=False)
        return result

    # No cache — trigger scan in subprocess (non-blocking)
    if not _scan_running:
        _scan_running = True
        asyncio.create_task(_background_scan())

    return {
        "timestamp": datetime.now().isoformat(),
        "total_scanned": 0, "passed": 0, "ranked_count": 0,
        "opportunities": [], "holdings_scores": [],
        "worst_holding": "", "worst_score": 0,
        "last_scan": "", "scanning": True,
        "cache_stale": True, "refreshing": True,
        "market_regime": _check_market_regime(),
    }


_REGIME_VETO_PREFIX = "Regime gate: "


def _apply_regime_gate(opps: list, regime: dict, mr_only: bool) -> None:
    """Enforce the regime pause flags on a signal list (mutates in place).

    pause_entries (DANGER/CRISIS) vetoes everything; pause_mr (WEAK) vetoes
    only MEAN_REVERSION (momentum and BOTH still qualify via the momentum leg).
    Regime vetoes are tagged with _REGIME_VETO_PREFIX so they can be cleared
    when the regime recovers, without un-vetoing scanner-set vetoes.
    """
    pause_all = bool(regime.get("pause_entries"))
    pause_mr = bool(regime.get("pause_mr"))
    for opp in opps:
        strat = opp.get("strategy", "MEAN_REVERSION") or "MEAN_REVERSION"
        if pause_all:
            paused = True
        elif pause_mr:
            paused = (strat == "MEAN_REVERSION") if mr_only else True
        else:
            paused = False
        already_regime_veto = str(opp.get("veto_reason", "")).startswith(_REGIME_VETO_PREFIX)
        if paused and not opp.get("vetoed", False):
            opp["vetoed"] = True
            opp["veto_reason"] = _REGIME_VETO_PREFIX + str(regime.get("reason", "entries paused"))
        elif not paused and opp.get("vetoed", False) and already_regime_veto:
            opp["vetoed"] = False
            opp["veto_reason"] = ""


def _check_market_regime() -> dict:
    """Multi-factor market regime detection.

    Uses composite scoring instead of binary thresholds. Research-backed:
      - Connors/Alvarez: stocks above SMA200 outperform, but crossing below
        doesn't mean instant bear. The DEPTH and DURATION of the breach matter.
      - Faber (2007): 200-day SMA timing works, but whipsaws near the line
        cause false signals. A buffer zone prevents overreaction.
      - Standard definition: Correction = -10% to -20% from peak.
        Bear market = -20%+ from peak. Don't call a -6% dip a bear.
      - VIX regime (Whaley): <20 calm, 20-30 elevated, 30-40 fear, >40 crisis.
      - Mean reversion research (our 7,032 trades): MR works when SPY bouncing
        from dip, breaks in sustained multi-week decline (5d + 20d both negative).

    Regime levels (by composite score):
      BEAR:       Drawdown >20% OR SPY >5% below SMA200    → PAUSE (0% size)
      CRISIS:     VIX >40                                    → PAUSE (0% size)
      CORRECTION: Drawdown 10-20% OR SPY 2-5% below SMA200  → 50% size
      CAUTION:    SPY below SMA50, mild drawdown              → 70% size
      HEALTHY:    SPY above SMA50, normal VIX                 → 100% size
    """
    result = {"regime": "UNKNOWN", "pause_entries": False, "reason": "No data",
              "vix": 0, "vix_regime": "UNKNOWN", "spy_5d_return": 0,
              "spy_below_sma50": False, "spy_below_sma200": False,
              "position_size_pct": 100, "drawdown_pct": 0}
    try:
        spy_df = _cache.get("SPY", 730)
        spy_price = 0
        sma50 = 0
        sma200 = 0
        if spy_df is not None and len(spy_df) >= 6:
            closes = spy_df["Close"].dropna().tolist()
            spy_price = closes[-1]
            ret_5d = ((closes[-1] - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 else 0
            ret_20d = ((closes[-1] - closes[-min(21, len(closes))]) / closes[-min(21, len(closes))]) * 100 if len(closes) >= 21 else 0
            sma50 = sum(closes[-min(50, len(closes)):]) / min(50, len(closes))
            sma200 = sum(closes[-min(200, len(closes)):]) / min(200, len(closes)) if len(closes) >= 200 else 0

            # Drawdown from 52-week high
            peak_window = min(252, len(closes))
            peak = max(closes[-peak_window:])
            drawdown = ((spy_price - peak) / peak) * 100

            # SMA200 gap (negative = below)
            sma200_gap = ((spy_price - sma200) / sma200 * 100) if sma200 > 0 else 0
            sma50_gap = ((spy_price - sma50) / sma50 * 100) if sma50 > 0 else 0

            result["spy_5d_return"] = round(ret_5d, 2)
            result["spy_20d_return"] = round(ret_20d, 2)
            result["spy_below_sma50"] = spy_price < sma50
            result["spy_below_sma200"] = spy_price < sma200 if sma200 > 0 else False
            result["spy_price"] = round(spy_price, 2)
            result["spy_sma50"] = round(sma50, 2)
            result["spy_sma200"] = round(sma200, 2)
            result["sma200_gap_pct"] = round(sma200_gap, 2)
            result["sma50_gap_pct"] = round(sma50_gap, 2)
            result["drawdown_pct"] = round(drawdown, 2)
            result["spy_peak"] = round(peak, 2)

        # Live price override
        live_spy = _price_cache.get("SPY", {}).get("price", 0)
        if live_spy > 0 and sma200 > 0:
            result["spy_price_live"] = round(live_spy, 2)
            spy_price = live_spy
            sma200_gap = ((live_spy - sma200) / sma200 * 100)
            sma50_gap = ((live_spy - sma50) / sma50 * 100) if sma50 > 0 else 0
            result["spy_below_sma200"] = live_spy < sma200
            result["spy_below_sma50"] = live_spy < sma50
            result["sma200_gap_pct"] = round(sma200_gap, 2)
            result["sma50_gap_pct"] = round(sma50_gap, 2)
            if peak > 0:
                drawdown = ((live_spy - peak) / peak) * 100
                result["drawdown_pct"] = round(drawdown, 2)

        # VIX
        vix_df = _cache.get("VIX", 365)
        vix = 0
        if vix_df is not None and len(vix_df) >= 1:
            vix_closes = vix_df["Close"].dropna().tolist() if "Close" in vix_df.columns else []
            if vix_closes:
                vix = vix_closes[-1]
        result["vix"] = round(vix, 2)

        # VIX regime
        if vix <= 0:
            result["vix_regime"] = "UNKNOWN"
        elif vix < 20:
            result["vix_regime"] = "LOW"
        elif vix < 25:
            result["vix_regime"] = "NORMAL"
        elif vix < 30:
            result["vix_regime"] = "ELEVATED"
        elif vix < 40:
            result["vix_regime"] = "FEAR"
        else:
            result["vix_regime"] = "CRISIS"

        # ── DATA-DRIVEN REGIME SCORING ──
        # Backtested on 10,421 trades across 500 stocks, 5 years.
        # Key finding: the DANGER ZONE is -10% to -15% drawdown (26% WR, -6.17% avg).
        # Deep bears (-20%+) actually bounce well (67% WR, +7.34%).
        # SPY near SMA200 (0% to -2% gap) is worst for MR (37% WR, -3.83%).
        if spy_price <= 0:
            # No SPY data — all gap/drawdown inputs are 0 and the chain below
            # would land in HEALTHY, silently disabling the safety gate.
            # Stay UNKNOWN at reduced size instead.
            result["position_size_pct"] = 50
            result["reason"] = "No SPY data — regime unknown, half size"
            return result
        drawdown = result.get("drawdown_pct", 0)
        sma200_gap = result.get("sma200_gap_pct", 0)
        sma50_gap = result.get("sma50_gap_pct", 0)
        spy_ret = result.get("spy_5d_return", 0)

        # 1. DANGER ZONE: Drawdown -7% to -15% — extended per V3.3 35K-trade backtest.
        #    Previously -10% to -15%. Widened on 2026-06-12 after dual-bucket
        #    backtest showed CORRECTION regime (-7% to -15% drawdown) returns
        #    +0.22% avg and 49% WR — below the 55% threshold required for entry.
        #    Walk-forward validation (train pre-2022, test 2022+): A-skip-CORRECTION
        #    returned +2.10%/trade vs +1.18% (always A), 78% bigger cumulative.
        if -15 <= drawdown <= -7:
            result["regime"] = "DANGER"
            result["pause_entries"] = True
            result["position_size_pct"] = 0
            result["reason"] = (f"DANGER — SPY {drawdown:+.1f}% from peak. "
                                f"Backtest: 49% WR, +0.22% avg in this zone (-7% to -15%). PAUSE entries.")

        # 2. CRISIS: VIX >40
        elif vix > 40:
            result["regime"] = "CRISIS"
            result["pause_entries"] = True
            result["position_size_pct"] = 0
            result["reason"] = f"VIX {vix:.0f} — crisis, entries paused"

        # 3. NEAR SMA200: SPY 0% to -2% below SMA200
        #    Backtested 102K trades: MR loses (-0.48%), Momentum works (+1.71%)
        #    PAUSE mean reversion only. Allow momentum entries at 50% size.
        elif -2 < sma200_gap < 0:
            result["regime"] = "WEAK"
            result["pause_entries"] = False  # Momentum still works
            result["pause_mr"] = True        # MR specifically paused
            result["position_size_pct"] = 50
            result["reason"] = (f"SPY {sma200_gap:+.1f}% vs SMA200 — WEAK. "
                                f"MR paused (48% WR, -0.48%). Momentum OK (54% WR, +1.71%). Half size.")

        # 4. CORRECTION: -15% to -20% drawdown — marginal (52% WR, +0.81%)
        elif -20 <= drawdown < -15:
            result["regime"] = "CORRECTION"
            result["pause_entries"] = False
            result["position_size_pct"] = 50
            result["reason"] = (f"Correction — SPY {drawdown:+.1f}% from peak. "
                                f"Backtest: 52% WR, +0.81% avg. Half size.")

        # 5. DEEP BEAR: >20% drawdown — actually GREAT for MR (67% WR, +7.34%)
        elif drawdown < -20:
            result["regime"] = "BEAR_BOUNCE"
            result["pause_entries"] = False
            result["position_size_pct"] = 100
            result["reason"] = (f"Deep bear bounce — SPY {drawdown:+.1f}% from peak. "
                                f"Backtest: 67% WR, +7.34% avg. FULL SIZE entries.")

        # 6. BELOW SMA200 (>2% gap): 10yr backtest 65% WR, +7.90% (6,056 trades)
        elif sma200_gap < -2:
            result["regime"] = "BELOW_SMA200"
            result["pause_entries"] = False
            result["position_size_pct"] = 100
            result["reason"] = (f"SPY {sma200_gap:+.1f}% below SMA200. "
                                f"Backtest: 65% WR, +7.90% avg. FULL SIZE (deep value).")

        # 7. BELOW SMA50 but above SMA200: 10yr backtest 56% WR, +3.53% (9,816 trades)
        elif sma50_gap < 0:
            result["regime"] = "PULLBACK"
            result["pause_entries"] = False
            result["position_size_pct"] = 100
            result["reason"] = (f"SPY below SMA50 ({sma50_gap:+.1f}%). "
                                f"Backtest: 56% WR, +3.53% avg. FULL SIZE.")

        # 8. DIP BUY: -7% to -3% drawdown — narrowed on 2026-06-12.
        #    Previously -3% to -10%; -7% to -10% moved to DANGER per V3.3 backtest.
        #    Remaining -3% to -7% range: still positive expectancy (60% WR, +4.09%).
        elif drawdown <= -3:
            result["regime"] = "DIP_BUY"
            result["pause_entries"] = False
            result["position_size_pct"] = 100
            result["reason"] = (f"Dip buy zone — SPY {drawdown:+.1f}% from peak. "
                                f"Backtest: 60% WR, +4.09% avg. FULL SIZE.")

        # 8b. SHARP_DROP: 5d return < -2% but drawdown not yet in pause range.
        #    Per V3.3 35K-trade backtest: Bucket A in SHARP_DROP returns +2.27% avg,
        #    57% WR — positive expectancy. Reduce size for variance management.
        elif spy_ret < -2:
            result["regime"] = "SHARP_DROP"
            result["pause_entries"] = False
            result["position_size_pct"] = 70
            result["reason"] = (f"SHARP_DROP — SPY {spy_ret:+.1f}% over 5d. "
                                f"Backtest: 57% WR, +2.27% avg. 70% size for risk mgmt.")

        # 9. FEAR: VIX elevated but structure OK
        elif vix > 30:
            result["regime"] = "FEAR"
            result["pause_entries"] = False
            result["position_size_pct"] = 50
            result["reason"] = f"VIX {vix:.0f} elevated — half size entries"

        # 10. HEALTHY: 10yr backtest 52% WR, +1.81% (42,929 trades) — reduced size
        else:
            result["regime"] = "HEALTHY"
            result["pause_entries"] = False
            result["position_size_pct"] = 70
            result["reason"] = f"Healthy — VIX {vix:.0f}, SPY {drawdown:+.1f}% from peak. 70% size."

    except Exception as e:
        result["reason"] = str(e)
    return result


def _try_load_scan_cache():
    """Load scan results from disk cache. Prefers today's file, falls back to most recent."""
    global _scan_cache, _scan_cache_time
    today = datetime.now().strftime('%Y-%m-%d')
    cache_path = os.path.join(os.path.dirname(__file__), "data", f"scan_{today}.json")
    if not os.path.exists(cache_path):
        # Fallback: find most recent scan file (within last 7 days)
        import glob
        pattern = os.path.join(os.path.dirname(__file__), "data", "scan_2026-*.json")
        files = sorted(glob.glob(pattern), reverse=True)
        cache_path = files[0] if files else None
    if not cache_path or not os.path.exists(cache_path):
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
    """Run scan in a SUBPROCESS so it can't block the event loop.
    The scan writes results to disk (scan_YYYY-MM-DD.json).
    We poll for the file and load it when ready."""
    global _scan_running, _scan_cache, _scan_cache_time
    try:
        print("[Scan] Starting scan in subprocess...")
        scan_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import asyncio; from deep_scanner import DeepScanner; asyncio.run(DeepScanner().run(fresh=True))",
            cwd=os.path.dirname(__file__),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(scan_proc.communicate(), timeout=600)
            # Print last 15 lines of output
            if stdout:
                for line in stdout.decode().split('\n')[-15:]:
                    if line.strip():
                        print(f"[Scan:out] {line.strip()}")
            if stderr:
                for line in stderr.decode().split('\n')[-10:]:
                    if line.strip():
                        print(f"[Scan:err] {line.strip()}")
            if scan_proc.returncode != 0:
                print(f"[Scan] Subprocess exited with code {scan_proc.returncode}")
        except asyncio.TimeoutError:
            scan_proc.kill()
            print("[Scan] Subprocess timed out after 10 min")

        # Load results from disk
        _try_load_scan_cache()
        if _scan_cache:
            print(f"[Scan] Loaded {len(_scan_cache.get('opportunities',[]))} opportunities from disk")
        else:
            print("[Scan] No results file found after subprocess")
    except Exception as e:
        import traceback
        print(f"[Scan] Subprocess error: {e}")
        traceback.print_exc()
    finally:
        _scan_running = False


@router.post("/scan/refresh")
async def refresh_scan():
    """Force a FULLY fresh scan: refresh Tiingo prices first, then re-scan.
    Single canonical refresh button. 2026-04-25 audit: previously only re-ran
    the scanner against stale cached prices, silently producing outdated
    rankings. Now always pulls fresh prices before scoring."""
    global _scan_cache, _scan_running
    _scan_cache = None
    _scan_running = False
    _scan_running = True
    asyncio.create_task(_full_refresh_pipeline())
    return {"status": "refreshing",
            "message": "Refreshing prices (Tiingo) + scanning 3,000+ stocks. Poll GET /scan/opportunities."}


async def _full_refresh_pipeline():
    """Two-stage: refresh Tiingo prices (10d) → run scan → reload cache.
    Updates _system_status so the UI can show stage + progress."""
    global _scan_running, _scan_cache, _scan_cache_time
    try:
        # Stage 1 — refresh stale prices
        _system_status.update({"stage": "refreshing_prices",
                               "message": "Refreshing prices (Tiingo, 10d, 20-concurrent)...",
                               "progress": 10})
        print("[FullRefresh] Stage 1/2: refreshing Tiingo prices...")
        try:
            stale = _cache.get_stale_tickers()
            if stale:
                async with aiohttp.ClientSession() as session:
                    sem = asyncio.Semaphore(20)
                    async def _one(t):
                        async with sem:
                            try:
                                return await _cache._fetch_tiingo(session, t, days=10, min_rows=1)
                            except Exception:
                                return None
                    results = await asyncio.gather(*[_one(t) for t in stale])
                    refreshed = sum(1 for r in results if r)
                    print(f"[FullRefresh] Refreshed {refreshed}/{len(stale)} stale tickers")
            else:
                print("[FullRefresh] All tickers already fresh")
        except Exception as e:
            print(f"[FullRefresh] Price refresh error (proceeding with cached data): {e}")

        # Stage 2 — run scan against fresh prices
        _system_status.update({"stage": "scanning",
                               "message": "Scanning 3,000+ stocks against fresh prices...",
                               "progress": 50})
        print("[FullRefresh] Stage 2/2: running scan...")
        await _background_scan()

        _system_status.update({"stage": "ready",
                               "message": "Scan complete with fresh data.",
                               "progress": 100})
    except Exception as e:
        import traceback
        traceback.print_exc()
        _system_status.update({"stage": "error", "message": f"Refresh error: {e}", "progress": 0})
    finally:
        _scan_running = False


@router.get("/scan/best-replacement/{sell_ticker}")
async def get_best_replacement(sell_ticker: str):
    """Find the best validated replacement for a stock we want to sell.

    V3.3 SSOT: reads from the SAME entries source as /scan/combined
    (strategy_evaluator's entries_YYYY-MM-DD.json). No more dual-pipeline
    rotation that could disagree with the Entries tab.

    Logic:
      1. Load today's entries cache (already passes V3.3 gates: trades>=10/15,
         WR>=55%, not vetoed, earnings>7d, analyst not Hold/Sell, etc.)
      2. Filter to non-vetoed entries that aren't already held
      3. Score each candidate via _ev_score on the SAME numbers shown in UI
      4. Pick the best replacement that beats the selling stock's EV
    """
    sell_ticker = sell_ticker.upper()

    # Get the EV of the stock we're selling (matches Entries tab math)
    holdings_scores, _, _ = _get_holdings_scores()
    sell_score = holdings_scores.get(sell_ticker, {}).get("score", 0)
    if sell_score == 0:
        bt = _backtest_mr(sell_ticker)
        sell_score = _ev_score(bt.get("avg_return", 0), bt.get("win_rate", 0), bt.get("total_trades", 0))

    # Load TODAY's entries cache — the same file /scan/combined serves from.
    # This is the SSOT for entries; rotation must use the same dataset.
    from strategy_evaluator import load_cache
    cached = load_cache()
    if not cached:
        raise HTTPException(404, "No entries cache for today. Run /scan/refresh-all first.")

    # Filter: non-vetoed, not already held, price >= MIN_PRICE.
    # The strategy_evaluator cache already enforces V3.3 gates (trades>=10/15,
    # WR>=55%, ret>=3%/2%, signal not expired). All listed candidates are
    # validated entries; we just need to find the best EV improvement.
    candidates = []
    for r in cached:
        if r.get("vetoed"): continue
        ticker = r.get("ticker", "")
        price = r.get("price", 0)
        if price < MIN_PRICE or ticker in holdings_scores: continue
        # EV calculation identical to the entries-tab sort key
        ev = _ev_score(r.get("expected_return", 0), r.get("confidence", 0), r.get("trades", 0))
        if ev > sell_score:
            r["_ev"] = ev
            candidates.append(r)

    # Sort by EV (best replacement first) — same sort as the Entries tab
    candidates.sort(key=lambda x: x.get("_ev", 0), reverse=True)
    top_n = candidates[:10]

    if not top_n:
        return {"replacement": None, "message": f"No entries beat {sell_ticker} (EV={sell_score:.2f})"}

    # Pick the top candidate. It's already passed all V3.3 gates including
    # earnings/analyst/sentiment vetoes from validate_top_signals.
    best = top_n[0]
    # Live price overlay
    live = _price_cache.get(best["ticker"])
    if live and live.get("price", 0) > 0:
        best["price"] = round(live["price"], 2)
    return {
        "replacement": {
            "ticker": best["ticker"],
            "price": best["price"],
            "strategy": best.get("strategy"),
            "strategy_label": best.get("strategy_label"),
            "score": round(best.get("_ev", 0), 2),  # EV — matches Entries tab
            "expected_return": best.get("expected_return"),
            "confidence": best.get("confidence"),
            "trades": best.get("trades"),
            "rsi2": best.get("rsi2"),
            "atr_pct": best.get("atr_pct"),
            "sma50_buffer": best.get("sma50_buffer"),
            "analyst_consensus": best.get("analyst_consensus", ""),
            "sentiment_label": best.get("sentiment_label", ""),
        },
        "sell_ticker": sell_ticker,
        "sell_score": round(sell_score, 2),
        "candidates_checked": len(top_n),
        "message": f"Best replacement for {sell_ticker}: {best['ticker']} (EV={best['_ev']:.2f} vs {sell_score:.2f})"
    }


def _backtest_mr(ticker: str) -> dict:
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
    _HOLD = 60  # match live Fixed60d exit
    opens = df["Open"].tolist() if "Open" in df.columns else closes
    rsi_arr = _rsi2_array(closes)
    sma_arr = _sma_array(closes, 50)
    last_exit_day = -1
    trades = []
    for i in range(50, len(closes) - _HOLD - 2):
        if i <= last_exit_day:
            continue
        if rsi_arr[i] < 10 and closes[i] > sma_arr[i]:
            entry_px = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
            exit_px = closes[i + 1 + _HOLD]
            ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT
            trades.append({"return": ret, "win": ret > 0})
            last_exit_day = i + 1 + _HOLD

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
                bt = _backtest_mr(ticker)
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
            # Unified scoring — same _ev_score used for entries
            _trades_for_shrink = tech.get("total_trades", 0) if tech else 0
            score = _ev_score(strat_ret, strat_wr, _trades_for_shrink)
            holdings_scores[ticker] = {
                "score": score,
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
    Returns (score, factors_str) for display.

    2026-05-18 audit — 376-signal walk-forward across 4 anchors confirmed:
    EV (Spearman ρ=-0.009, inverted in 3/4 anchors) and WR-tier (bucket Pearson
    r=-0.310) are anti-predictive. Both were dropped from the points contribution
    (computations retained for the factors string only). Volume reshaped from
    linear ramp to U-shape after backtest showed vol<0.5 delivers +11.58% / 57%
    WR (highest return) and vol 1.0-1.5 delivers +7.7% / 71% WR (best WR), while
    the "uncommitted" middle (0.5-1.0) underperforms.

    Active weights:
      - ATR% (15-40pts)    — high-ATR rewarded (tail/skew = ROI); >=15% hard-vetoed (2026-06-19)
      - Analyst (15pts)    — +1.19% edge on 95K signals
      - BOTH bonus (0-12)  — NEW 2026-06-02: ret_20d>5% + atr>=4 (10yr +4.14%/trd)
      - Sentiment (10pts)  — informational
      - Volume (0-10pts U-shape) — extremes reward, middle penalized
      - Price (10pts)      — sweet spot $10-25
      - RSI depth (3pts), SMA buffer (2pts) — minor
      - EV (0pts), WR-tier (0pts) — dropped 2026-05-18 audit

    Caps: only the absolute floor remains — lost money on 10+ trades caps at 49.
    """
    pts = 0.0
    factors = []

    zone_ret = r.get("zone_return", 0)
    zone_wr = r.get("zone_win_rate", 0)
    zone_trades = r.get("zone_trades", 0)
    wr = r.get("win_rate", 0)
    total_trades = r.get("trades", 0)
    rsi2 = r.get("rsi2", 25)
    atr_pct = r.get("atr_pct", 0)
    sma50_buffer = r.get("sma50_buffer", 0)
    vol_ratio = r.get("volume_ratio", 0)
    analyst_cons = r.get("analyst_consensus", "")
    analyst_upside = r.get("analyst_upside", 0)
    sentiment_score = r.get("sentiment_score", 0)
    price = r.get("price", 0)

    # 1. EV (0 pts — informational only). Walk-forward audit 2026-05-18 on
    # 376 historical signals across 4 anchors showed EV is anti-predictive:
    # Spearman ρ=-0.009 overall, top-EV quartile UNDERPERFORMED bottom-EV
    # quartile in 3 of 4 anchors. Kept the computation for the factors string
    # so debugging output is unchanged; dropped the pts contribution.
    if zone_trades >= 3 and zone_wr > 0:
        ev = _ev_score(zone_ret, zone_wr, zone_trades)
    else:
        ev = _ev_score(r.get("avg_return", 0), wr, total_trades)
    factors.append(f"EV:{ev:.1f}")

    # 2. WR tier (0 pts — informational only). Same 2026-05-18 audit: bucket
    # Pearson r=-0.310 with future return at decile level (counter-predictive).
    # Computation retained for the UNVALIDATED:CAP49 logic below (which still
    # uses eff_wr) and factors string.
    if zone_trades >= 5 and zone_wr > 0:
        eff_wr = _bayesian_wr(int(round(zone_wr * zone_trades / 100)), zone_trades)
    elif total_trades >= 5 and wr > 0:
        eff_wr = _bayesian_wr(int(round(wr * total_trades / 100)), total_trades)
    else:
        eff_wr = 0
    factors.append(f"WR:{eff_wr:.0f}")

    # 3. ATR% volatility (max 40 pts). NOTE on the "peak": a 2026-06-19 per-trade
    # study (32,653 non-overlap MR trades) found that by WIN RATE/MEDIAN the band
    # 4-8% looks best and 8-10% is a WR trough (~46%). BUT a head-to-head A/B of
    # the composite as a RANKING function (top-10, 60d hold, 232 anchors,
    # _composite_ab_test.py) showed demoting the 8-15% band REDUCES realized
    # top-10 return: OLD +3.82% vs reweight-to-4-8% +2.54-3.06% (worse OOS too).
    # Reason: this strategy's edge is positive-skew/tail-driven, and the tail
    # lives in high-ATR names — so rewarding 8-15% ATR is correct for the
    # maximize-ROI objective even though its per-trade WR is lower. The weights
    # below are therefore KEPT as tuned; only the catastrophic >=15% cohort
    # (29% WR / -12.6% avg, no tail benefit) is removed, now via a HARD VETO in
    # _dict_to_opportunity (this -5 is just a backstop).
    if atr_pct >= 15:
        atr_pts = -5    # backstop — hard-vetoed upstream in _dict_to_opportunity
    elif atr_pct >= 10:
        atr_pts = 35    # high skew — tail winners that carry a concentrated book
    elif atr_pct >= 8:
        atr_pts = 40    # strong (per-trade WR dips here but top-10 ROI is best)
    elif atr_pct >= 6:
        atr_pts = 35    # best per-trade RETURN band (+7-9%)
    elif atr_pct >= 5:
        atr_pts = 30
    elif atr_pct >= 4:
        atr_pts = 20
    elif atr_pct >= 3:
        atr_pts = 15    # minimum acceptable
    else:
        atr_pts = max(0, atr_pct * 4)
    pts += atr_pts
    factors.append(f"ATR:{atr_pct:.1f}")

    # 4. RSI(2) depth (3 pts) — statistically insignificant (IC=0.0004, p=0.80)
    rsi_pts = 3 if rsi2 < 5 else (2 if rsi2 < 10 else 0)
    pts += rsi_pts
    factors.append(f"RSI:{rsi2:.0f}")

    # 5. SMA50 buffer (2 pts) — slightly inverse predictor (IC=-0.008)
    buf_pts = 2 if sma50_buffer >= 5 else (1 if sma50_buffer >= 0 else 0)
    pts += buf_pts
    factors.append(f"BUF:{sma50_buffer:.0f}")

    # 5b. BOTH-strategy bonus (0-12 pts) — NEW 2026-06-02. The 10-year backtest
    # showed stocks qualifying for BOTH mean-reversion AND momentum entry
    # produce +4.14%/trade @ 30d vs MR's +2.62% and MOM's +1.60%. Top-25%-ATR
    # BOTH cohort produced +9.08%/mo (the strongest single-cohort return found).
    # Proxy for BOTH detection from /scan/opportunities (no strategy field):
    #   In MR scanner already → MR side qualified
    #   ret_20d > 5% AND atr_pct >= 4% → momentum side likely qualified
    # +8 pts for standard BOTH, +12 for strong BOTH (ret>10% + atr>=5%).
    ret_20d = r.get("ret20", 0) or r.get("ret_20d", 0)
    # Gate BOTH bonus on ATR sanity — catastrophic vol (>15%) already disqualifies
    if atr_pct >= 15:
        both_pts = 0  # don't reward "BOTH" when the vol is too extreme to trade
    elif ret_20d > 10 and atr_pct >= 5:
        both_pts = 12
        factors.append(f"BOTH+:{ret_20d:.0f}/{atr_pct:.0f}:+12")
    elif ret_20d > 5 and atr_pct >= 4:
        both_pts = 8
        factors.append(f"BOTH:{ret_20d:.0f}/{atr_pct:.0f}:+8")
    else:
        both_pts = 0
    pts += both_pts

    # 6. Analyst consensus + upside (15 pts) — backtest: +1.19% edge on 95K
    # signals, genuinely external signal that isn't captured by price history.
    analyst_map = {"Buy": 10, "Strong Buy": 10, "Outperform": 8, "Overweight": 8,
                   "": 4, "Hold": -3, "Sell": -10, "Underperform": -6}
    a_pts = max(-10, analyst_map.get(analyst_cons, 4))
    if analyst_upside > 10:
        a_pts += 5  # meaningful upside to target
    elif analyst_upside < 0:
        a_pts -= 5  # already above target = overvalued
    pts += a_pts

    # 7. Sentiment (10 pts) — note CLAUDE.md removed sentiment VETO 2026-04-17
    # (-0.43% edge as a veto), but small positive weight in ranking is fine.
    if sentiment_score > 0.3:
        s_pts = 10
    elif sentiment_score > 0:
        s_pts = 5
    elif sentiment_score > -0.3:
        s_pts = 0
    else:
        s_pts = -10
    pts += s_pts

    # 8. Volume ratio (0-10 pts) — RESHAPED 2026-05-18 audit. Old linear ramp
    # gave +10/+7 for vol>=1.5 / >=1.0 and 0 otherwise based on a +6.88% claim
    # that doesn't reproduce. Actual 21d realized returns by bucket:
    #   vol<0.5: +11.58% / 57% WR    (quiet accumulation — best return)
    #   0.5-1.0: +5.4%  / 62% WR    (uncommitted — penalize)
    #   1.0-1.5: +7.7%  / 71% WR    (confirmation — best WR + good return)
    #   1.5+:    +5.4%  / 66% WR    (over-extended — neutral)
    # New U-shape: reward extremes (accumulation or confirmation), penalize middle.
    if vol_ratio < 0.5:
        v_pts = 8   # quiet accumulation
    elif vol_ratio < 1.0:
        v_pts = 0   # uncommitted
    elif vol_ratio < 1.5:
        v_pts = 10  # active confirmation
    else:
        v_pts = 5   # over-extended but still ok
    pts += v_pts

    # 9. Price factor (10 pts) — backtested: $10-25 = +8.83%, $200+ = +0.20%
    if 10 <= price <= 25:
        p_pts = 10  # sweet spot
    elif price <= 50:
        p_pts = 8
    elif price <= 100:
        p_pts = 5
    elif price <= 200:
        p_pts = 2
    elif price <= 500:
        p_pts = -3
    else:
        p_pts = -5
    pts += p_pts
    factors.append(f"PX:{price:.0f}")

    composite = max(0, min(100, pts))

    # High-avg_return boost — toned down 2026-05-13 audit. Previous +25 saturated
    # too many tickers at the 100 ceiling, eliminating discrimination at the top
    # of the entries list. Now +12 max for ≥10% avg-ret, scaled so only stocks
    # ALSO at high ATR get the full bump (vol ⨯ historical-return is the
    # combination that predicted in the walk-forward).
    eff_ret = zone_ret if zone_trades >= 5 else r.get("avg_return", 0)
    if eff_ret >= 10 and atr_pct >= 5:
        composite = min(100, composite + 12)
        factors.append(f"RET+{eff_ret:.0f}:+12")
    elif eff_ret >= 10:
        composite = min(100, composite + 6)
        factors.append(f"RET+{eff_ret:.0f}:+6")
    elif eff_ret >= 5:
        composite = min(100, composite + 5)
        factors.append(f"RET+{eff_ret:.0f}:+5")
    elif eff_ret >= 2:
        composite = min(100, composite + 2)

    # Soft veto: no volume confirmation (vol_ratio < 1.0x) caps at FAIR — but
    # only when prior avg_return is also weak (<5%). High-historical-return
    # stocks at low-volume dip days are exactly the setups we want to keep
    # visible (the avg_return signal carries the edge, not the day's volume).
    if vol_ratio < 1.0 and eff_ret < 5 and composite > 50:
        composite = 50
        factors.append("VOL<1x:CAP50")

    # Floor cap only — keep the absolute "lost money on 10+ trades" guard.
    # 2026-05-18 audit dropped the broader UNVALIDATED:CAP49 rule (which capped
    # weak_combo = prior_WR<55 + ATR<5 + analyst not supportive). Walk-forward
    # showed the strict-pass proxy (WR≥65 + trades≥10 + avg≥3 + ATR≥3) actually
    # UNDERPERFORMS non-strict by -0.80% at 21d / -2.09% at 14d, so capping
    # non-strict signals was the wrong direction. Only the unambiguous "lost
    # money historically on 10+ samples" floor remains.
    val_trades = max(zone_trades, total_trades)
    val_ret = zone_ret if zone_trades >= 5 else r.get("avg_return", 0)
    if val_trades >= 10 and val_ret <= 0 and composite >= 50:
        composite = 49
        factors.append("LOSING:CAP49")
    return round(composite, 1), " ".join(factors)


def _quality_tier(score: float) -> str:
    """Map composite score to quality tier.
    Calibrated on 488K-trade backtest: BEST=+8.1%, GOOD=+3.5%, FAIR=+1.7%."""
    if score >= 65:
        return "BEST"
    elif score >= 50:
        return "GOOD"
    elif score >= 35:
        return "FAIR"
    elif score >= 20:
        return "WEAK"
    return "POOR"


def _meets_strict_criteria(r: dict) -> bool:
    """Check if stock passes ALL original strict ATLAS V2.5 entry criteria.
    Bug 5 fix (2026-06-03): vetoed stocks NEVER meet strict criteria, regardless
    of underlying metrics. Previously APP could be vetoed=True + meets_strict=True
    simultaneously which was misleading."""
    if r.get("vetoed"):
        return False
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
            and trades >= 10  # align with the live MR gate + CLAUDE.md 10-trade mandate
            and zone_ret > 0  # (was 6 — a 6-trade stock got a "strict BUY" badge but
            and avg_ret >= 3)  # was vetoed on the entries tab; 2026-06-19 consistency fix


def _check_correlation(ticker: str, existing_tickers: list, threshold: float = 0.7) -> dict:
    """Check if a new stock is too correlated with existing holdings.
    Uses 30-day daily return correlation. Rejects if > threshold with any holding.
    Research: positions with >0.7 correlation act as single risk unit."""
    if not existing_tickers:
        return {"correlated": False, "max_corr": 0, "corr_with": ""}

    # Get daily returns for candidate
    df_new = _cache.get(ticker, 60)
    if df_new is None or len(df_new) < 30:
        return {"correlated": False, "max_corr": 0, "corr_with": "", "reason": "insufficient data"}

    new_closes = df_new["Close"].dropna().tolist()[-30:]
    if len(new_closes) < 20:
        return {"correlated": False, "max_corr": 0, "corr_with": ""}

    new_returns = [(new_closes[i] - new_closes[i-1]) / new_closes[i-1]
                   for i in range(1, len(new_closes))]

    max_corr = 0.0
    corr_with = ""

    for existing in existing_tickers:
        df_ex = _cache.get(existing, 60)
        if df_ex is None or len(df_ex) < 30:
            continue
        ex_closes = df_ex["Close"].dropna().tolist()[-30:]
        if len(ex_closes) < 20:
            continue
        ex_returns = [(ex_closes[i] - ex_closes[i-1]) / ex_closes[i-1]
                      for i in range(1, len(ex_closes))]

        # Align lengths
        min_len = min(len(new_returns), len(ex_returns))
        if min_len < 15:
            continue
        nr = new_returns[-min_len:]
        er = ex_returns[-min_len:]

        # Pearson correlation (pure Python — no numpy dependency)
        n = len(nr)
        mean_nr = sum(nr) / n
        mean_er = sum(er) / n
        cov = sum((nr[i] - mean_nr) * (er[i] - mean_er) for i in range(n)) / n
        std_nr = (sum((x - mean_nr) ** 2 for x in nr) / n) ** 0.5
        std_er = (sum((x - mean_er) ** 2 for x in er) / n) ** 0.5

        if std_nr > 0 and std_er > 0:
            corr = cov / (std_nr * std_er)
            if abs(corr) > abs(max_corr):
                max_corr = corr
                corr_with = existing

    return {
        "correlated": abs(max_corr) > threshold,
        "max_corr": round(max_corr, 3),
        "corr_with": corr_with,
    }


def _dict_to_opportunity(r: dict, holdings_scores: dict) -> ScanOpportunity:
    """Convert a scan result dict to ScanOpportunity with composite ranking.
    Uses composite score (0-100) for ranking. Only 3 hard vetos remain."""
    zone_ret = r.get("zone_return", 0)
    zone_wr = r.get("zone_win_rate", 0)
    zone_trades = r.get("zone_trades", 0)
    if zone_trades >= 5 and zone_wr > 0:
        score = _ev_score(zone_ret, zone_wr, zone_trades)
    else:
        score = _ev_score(r.get("avg_return", 0), r.get("win_rate", 0), r.get("trades", 0))

    ticker = r.get("ticker", "")
    price = r.get("price", 0)
    vol_ratio = r.get("volume_ratio", 0)
    vetoed = r.get("vetoed", False)
    veto_reason = r.get("veto_reason", "")

    # VETO filters — 2026-04-24 audit removed prior-stat filters that failed
    # walk-forward (37K MR + 25K MOM signals over 10yr):
    #   trades<10, zone_wr<65%, avg_return<3%, score<3, "not validated".
    # Each invalidated filter REJECTED on average higher-return signals.
    # Live-impact: 7 of our 14 wins would have been blocked; 80% of market's
    # top-50 52w winners had first signal blocked. See backtest_veto_*.py.
    # Kept: point-in-time + exogenous checks only.
    trades_count = r.get("trades", 0)
    # 1. Price minimum (point-in-time — exchange liquidity)
    if not vetoed and price < 10:
        vetoed = True
        veto_reason = f"Price too low (${price:.2f} < $10)"
    # 1b. Catastrophic volatility (point-in-time). 2026-06-19 validation on
    #     32,653 non-overlap MR trades (10.5yr, IS+OOS consistent): ATR>=15%
    #     entries return 29% WR / -12.6% avg (-4.0% even OOS) — the worst cohort
    #     by a wide margin. The composite's soft -5pt penalty was too weak (a
    #     high-prior-return stock could still surface). Hard veto instead.
    atr_pct_v = r.get("atr_pct", 0)
    if not vetoed and atr_pct_v >= 15:
        vetoed = True
        veto_reason = f"Volatility too high (ATR {atr_pct_v:.0f}% ≥ 15 — 29% WR, -12.6% avg)"
    # 2. Earnings veto (set in Phase 3 if applicable — binary event risk)
    # 3. Analyst consensus Hold/Sell (backtested +1.19% edge, stays)
    analyst_con = r.get("analyst_consensus", "")
    if not vetoed and analyst_con in ("Hold", "Sell", "Underperform", "Strong Sell"):
        vetoed = True
        veto_reason = f"Analyst says {analyst_con}"
    # 4. Correlation check — avoid concentrating risk in correlated holdings
    if not vetoed and holdings_scores:
        _corr = _check_correlation(ticker, list(holdings_scores.keys()))
        if _corr["correlated"]:
            vetoed = True
            veto_reason = f"Correlated {_corr['max_corr']:.0%} with {_corr['corr_with']}"

    # 5. V2.7 VALIDATION GATE (CLAUDE.md mandate): WR > 55% AND 10+ trades.
    # The 2026-04-24 audit removed avg_return<3 as a HARD veto (it rejected
    # future winners). But CLAUDE.md still requires WR > 55 for "validation"
    # before recommending any entry. Apply Bayesian-shrunk WR so single-sample
    # noise doesn't game the gate. Stocks failing this fall to the "Vetoed"
    # section and don't pollute the main entries list.
    # Require BOTH conditions (the mandate is conjunctive): >=10 trades AND WR>55.
    # Previously the WR check only ran when trades>=10, so a 6-9 trade stock with a
    # terrible WR skipped validation entirely and was emitted as a clean entry —
    # insufficient sample must FAIL, not get a free pass (2026-06-19 fix).
    _trades_n = trades_count
    if not vetoed:
        if _trades_n < 10:
            vetoed = True
            veto_reason = f"V2.7 validation: {_trades_n} trades < 10 (insufficient sample)"
        else:
            _wins_n = int(round(r.get("win_rate", 0) * _trades_n / 100))
            _bwr = _bayesian_wr(_wins_n, _trades_n)
            if _bwr <= 55:
                vetoed = True
                veto_reason = f"V2.7 validation: WR {_bwr:.0f}% ≤ 55 (need > 55)"

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
        hold_days=r.get("hold_days", 60),
        low52_dist=r.get("low52_dist", 0),
        atr_pct=r.get("atr_pct", 0),
        sma50_buffer=r.get("sma50_buffer", 0),
        ret20=r.get("ret20", 0),
        ml_score=r.get("ml_score", 0),
        bayesian_wr=_bayesian_wr(
            int(r.get("win_rate", 0) * r.get("trades", 0) / 100),
            r.get("trades", 0)
        ) if r.get("trades", 0) >= 5 else r.get("win_rate", 0),
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
        # True = actionable upgrade over the current book. If no holdings yet,
        # any non-vetoed entry meeting the EV floor counts (nothing to beat).
        is_upgrade=not vetoed and score >= 3.0 and (bool(beats) or not holdings_scores),
    )


def _build_scan_result(opportunities: list, total_scanned: int,
                       holdings_scores: dict, worst_ticker: str, worst_score: float) -> Dict:
    """Build the scan response dict. Sort by composite_score descending.
    Includes data_freshness so the frontend can show how stale the prices are."""
    # Sort by composite score (best first), vetoed last
    opportunities.sort(key=lambda x: (not x.vetoed, x.composite_score), reverse=True)

    h_scores = [
        HoldingScore(
            ticker=t, score=d["score"], zone_return=d["zone_return"], win_rate=d["win_rate"],
            exit_triggered=d.get("exit_triggered", False), signal=d.get("signal", "HOLD"),
        ).model_dump()
        for t, d in holdings_scores.items()
    ]

    # Data freshness — most recent close in cache + how stale that is in trading days
    freshness = {"latest_close": None, "trading_days_stale": None, "is_fresh": False}
    try:
        import sqlite3 as _sql_fresh
        conn = _sql_fresh.connect(os.path.join(os.path.dirname(__file__), "data", "stock_cache.db"))
        latest = conn.execute("SELECT MAX(date) FROM daily_prices").fetchone()[0]
        conn.close()
        if latest:
            freshness["latest_close"] = latest
            today = datetime.now().date()
            last_dt = datetime.strptime(latest, "%Y-%m-%d").date()
            cal_days = (today - last_dt).days
            # Approximate trading-day gap (5/7 of calendar days)
            tdg = max(0, int(cal_days * 5 / 7))
            freshness["trading_days_stale"] = tdg
            freshness["is_fresh"] = tdg <= 1  # today's or yesterday's close = fresh
    except Exception:
        pass

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
        "data_freshness": freshness,
        "system_status": _system_status.copy(),
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
                    score = _ev_score(r_dict.get("zone_return", 0), r_dict.get("zone_win_rate", 0), zt)
                else:
                    score = _ev_score(r_dict.get("avg_return", 0), r_dict.get("win_rate", 0), r_dict.get("trades", 0))
                scored.append((score, r))

            scored.sort(key=lambda x: x[0], reverse=True)
            print(f"[Scan] {len(scored)} candidates (price >= ${MIN_PRICE:.0f}, not held)")

            # Phase 3: 2026-04-24 behavior — validate top 50 by EV score only.
            # Anything beyond rank 50 has near-zero or negative ev_score and isn't
            # worth surfacing. Without this cap, low-ranked negative-ret stocks
            # would get analyst/sentiment data and pass the deployed frontend filter.
            top_to_validate = [r for _, r in scored][:50]
            print(f"[Scan] Phase 3: validating top {len(top_to_validate)} of {len(scored)} candidates")

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

def _calc_trade_fee(ticker: str) -> float:
    """Calculate trade fee: ILS = free, USD = first 10 trades/month free, then $1.50."""
    if ticker.endswith(".TA"):
        return 0.0
    # Count trades this calendar month
    import sqlite3 as _sq
    _db = os.path.join(os.path.dirname(__file__), "data", "positions.db")
    conn = _sq.connect(_db)
    try:
        month_start = datetime.now().strftime("%Y-%m-01")
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE date >= ?", (month_start,)
        ).fetchone()[0]
    finally:
        conn.close()
    return 0.0 if count < 10 else 1.50


@router.post("/positions/buy", response_model=TradeResult)
async def buy_position(req: BuyRequest):
    """Record a buy and create position + transaction.

    V3.3 (2026-06-12): If the buy is being made in a regime where pause_entries
    is set (DANGER zone -7% to -15% drawdown, CRISIS, etc.) the trade is
    allowed (user agency) but a `regime_warning` is attached to the response so
    the UI can flag it. Walk-forward backtest showed skipping DANGER trades
    improves per-trade return from +1.18% to +2.10%.
    """
    ticker = req.ticker.upper()
    total = req.price * req.shares
    fee = _calc_trade_fee(ticker)
    currency = "ILS" if ticker.endswith(".TA") else "USD"

    # Regime gate — informational warning if buying in a pause zone.
    regime = _check_market_regime()
    regime_warning = None
    if regime.get("pause_entries"):
        regime_warning = (
            f"⚠ Regime {regime.get('regime')}: entries are statistically paused. "
            f"{regime.get('reason','')} Trade allowed but backtest discourages it."
        )
    elif regime.get("position_size_pct", 100) < 100:
        # Soft size warning — check if this position exceeds the suggested cap
        try:
            positions = _position_mgr._get_open_positions_sync()
            current_value = sum(
                (p.get("entry_price", 0) * p.get("shares", 0)) for p in positions
            ) if positions else 0
            # Approximate portfolio total (positions + this new buy as proxy)
            portfolio_estimate = current_value + total
            if portfolio_estimate > 0:
                max_per_position = portfolio_estimate * 0.12 * regime["position_size_pct"] / 100
                if total > max_per_position * 1.05:  # 5% tolerance
                    regime_warning = (
                        f"⚠ Position size ${total:.0f} exceeds regime-adjusted cap "
                        f"${max_per_position:.0f} ({regime['position_size_pct']}% sizing in {regime.get('regime')})."
                    )
        except Exception:
            pass

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

    # Invalidate caches so signals/exit strategies/perf history reflect the new position.
    # IMPORTANT: do NOT nullify _scan_cache here. _try_load_scan_cache() rebuilds 155+
    # opportunities × 8 holdings = 1,240 _check_correlation calls synchronously inside
    # the next /scan/opportunities request handler — that blocks the event loop for
    # 20-60s on shared-1x Fly and tanks the whole backend until rebuild completes.
    # The opportunities list is unchanged by a new holding; only `beats_holdings` and
    # correlation flags shift. Background scan loop refreshes those on schedule.
    _signal_cache.clear()
    _exit_strategy_cache.clear()
    _technicals_cache.pop(ticker, None)  # next request recomputes for this ticker
    global _perf_cache, _perf_cache_time, _health_cache, _health_cache_time, _momentum_cache, _momentum_cache_time
    _perf_cache = None          # /performance must include the new trade
    _perf_cache_time = None
    _health_cache = None        # strategy health depends on portfolio composition
    _health_cache_time = None
    _momentum_cache = None      # correlation veto depends on holdings
    _momentum_cache_time = None

    # Kick off a non-blocking background scan refresh — runs in subprocess so it
    # can't starve the event loop. Existing _scan_cache continues serving until
    # the new scan completes (typically 1-3 min).
    global _scan_running
    if not _scan_running:
        _scan_running = True
        asyncio.create_task(_background_scan())

    message = f"Bought {req.shares} shares of {ticker} @ ${req.price:.2f}"
    if regime_warning:
        message = f"{message} | {regime_warning}"
    return TradeResult(
        success=True,
        message=message,
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
    fee = _calc_trade_fee(ticker)

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

    # Invalidate caches so signals/exit strategies/perf history reflect the closed position.
    # See buy_position for why _scan_cache is NOT nullified here (avoid blocking
    # the event loop on the next request via _try_load_scan_cache rebuild).
    _signal_cache.clear()
    _exit_strategy_cache.clear()
    _technicals_cache.pop(ticker, None)
    global _perf_cache, _perf_cache_time, _health_cache, _health_cache_time, _momentum_cache, _momentum_cache_time
    _perf_cache = None
    _perf_cache_time = None
    _health_cache = None
    _momentum_cache = None
    _momentum_cache_time = None

    # Background scan refresh — non-blocking. Existing _scan_cache keeps serving.
    global _scan_running
    if not _scan_running:
        _scan_running = True
        asyncio.create_task(_background_scan())

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


@router.post("/positions/deposit")
async def record_deposit(req: DepositRequest):
    """Record a cash deposit. Inserts a DEPOSIT row in the transactions ledger
    so cash + total_deposited update everywhere immediately."""
    amount = float(req.amount)
    if amount <= 0:
        return {"success": False, "message": "Deposit amount must be positive"}

    deposit_date = (req.date or datetime.now().strftime("%Y-%m-%d")).strip()[:10]
    try:
        # Validate ISO date
        from datetime import date as _date
        _date.fromisoformat(deposit_date)
    except ValueError:
        return {"success": False, "message": f"Invalid date '{deposit_date}' (expected YYYY-MM-DD)"}

    import sqlite3 as _sql
    db_path = os.path.join(os.path.dirname(__file__), "data", "positions.db")
    conn = _sql.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO transactions (position_id, ticker, action, date, price, shares, total, fee, realized_pnl, notes, created_at) "
            "VALUES (NULL, '_CASH', 'DEPOSIT', ?, ?, 1, ?, 0, NULL, ?, ?)",
            (deposit_date, amount, amount, req.notes or "", datetime.now().isoformat()),
        )
        tx_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    # Bust caches that depend on cash / deposit total / equity curve.
    _signal_cache.clear()
    _exit_strategy_cache.clear()
    global _perf_cache, _perf_cache_time, _health_cache, _health_cache_time
    _perf_cache = None
    _perf_cache_time = None
    _health_cache = None
    _health_cache_time = None

    new_total = _total_deposited_now()
    return {
        "success": True,
        "message": f"Recorded deposit ${amount:,.2f} on {deposit_date}",
        "transaction_id": tx_id,
        "amount": amount,
        "date": deposit_date,
        "total_deposited": new_total,
    }


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


# ── Sector Analysis Endpoint ──

@router.get("/sectors")
async def get_sectors():
    """Sector analysis: performance, MR opportunity, portfolio exposure, correlations."""
    SECTORS = {
        "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
        "XLV": "Healthcare", "XLI": "Industrials", "XLY": "Consumer Disc",
        "XLP": "Consumer Staples", "XLB": "Materials", "XLU": "Utilities",
        "XLRE": "Real Estate", "XLC": "Communication",
    }

    # Approximate sector mapping for common stocks
    STOCK_SECTORS = {
        "FIGS": "Healthcare", "EFXT": "Energy", "MTRN": "Industrials",
        "WDC": "Technology", "PDS": "Energy", "LRCX": "Technology",
        "MKSI": "Technology", "LIND": "Industrials", "MAMA": "Communication",
        "HXL": "Industrials", "DBD": "Technology",
        "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AVGO": "Technology",
        "GOOGL": "Communication", "META": "Communication", "NFLX": "Communication",
        "AMZN": "Consumer Disc", "TSLA": "Consumer Disc",
        "JPM": "Financials", "BAC": "Financials", "GS": "Financials",
        "XOM": "Energy", "CVX": "Energy", "OXY": "Energy",
        "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare",
        "CAT": "Industrials", "GE": "Industrials", "HON": "Industrials",
        "PG": "Consumer Staples", "KO": "Consumer Staples", "PEP": "Consumer Staples",
        "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
        "LIN": "Materials", "APD": "Materials", "SHW": "Materials",
        "PLD": "Real Estate", "AMT": "Real Estate", "EQIX": "Real Estate",
    }

    sectors = []

    # Fetch missing sector ETFs from Yahoo (one-time, then cached in SQLite)
    missing_etfs = [etf for etf in SECTORS if _cache.get(etf, 365) is None or len(_cache.get(etf, 365) or []) < 50]
    if missing_etfs:
        def _fetch_etfs():
            import requests as _req
            for etf in missing_etfs:
                try:
                    r = _req.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{etf}?range=5y&interval=1d",
                                headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                    if r.status_code != 200: continue
                    chart = r.json().get("chart",{}).get("result",[{}])[0]
                    ts = chart.get("timestamp",[]); q = chart.get("indicators",{}).get("quote",[{}])[0]
                    if not ts or not q.get("close"): continue
                    from datetime import datetime as _dt
                    dates = [_dt.utcfromtimestamp(t).strftime('%Y-%m-%d') for t in ts]
                    df = pd.DataFrame({"Date": dates, "Open": q.get("open",[]), "High": q.get("high",[]),
                                       "Low": q.get("low",[]), "Close": q.get("close",[]), "Volume": q.get("volume",[])})
                    df["Date"] = pd.to_datetime(df["Date"])
                    df = df.set_index("Date").sort_index().dropna(subset=["Close"])
                    if len(df) >= 50:
                        _cache.store(etf, df)
                except Exception: pass
        try:
            await asyncio.wait_for(asyncio.to_thread(_fetch_etfs), timeout=30)
        except Exception: pass

    for etf, name in SECTORS.items():
        df = _cache.get(etf, 365)
        if df is None or len(df) < 50:
            sectors.append({"etf": etf, "name": name, "price": 0, "ret_5d": 0, "ret_20d": 0, "ret_60d": 0, "ret_ytd": 0,
                           "mr_wr": 0, "mr_trades": 0, "mr_avg_ret": 0, "trend": "UNKNOWN", "rsi14": 50, "above_sma50": False})
            continue

        closes = df["Close"].dropna().tolist()
        opens = df["Open"].tolist() if "Open" in df.columns else closes
        if not closes:
            continue

        price = closes[-1]
        ret_5d = ((closes[-1] / closes[-6]) - 1) * 100 if len(closes) >= 6 else 0
        ret_20d = ((closes[-1] / closes[-21]) - 1) * 100 if len(closes) >= 21 else 0

        # YTD
        dates = df.index.strftime('%Y-%m-%d').tolist() if hasattr(df.index, 'strftime') else []
        ytd_idx = next((i for i, d in enumerate(dates) if d >= '2026-01-02'), 0)
        ret_ytd = ((closes[-1] / closes[ytd_idx]) - 1) * 100 if ytd_idx > 0 and ytd_idx < len(closes) else 0

        # MR backtest on the ETF itself (Fixed60d — matches live exit)
        rsi_arr = _rsi2_array(closes)
        sma_arr = _sma_array(closes, 50)
        trades = []
        le = -1
        for i in range(50, len(closes) - 62):
            if i <= le:
                continue
            if rsi_arr[i] < 10 and closes[i] > sma_arr[i]:
                ep = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
                if i + 1 + 60 < len(closes):
                    ret = ((closes[i + 1 + 60] - ep) / ep) * 100 - 0.30
                    trades.append(ret)
                    le = i + 1 + 60

        mr_wr = sum(1 for t in trades if t > 0) / len(trades) * 100 if trades else 0
        mr_avg = sum(trades) / len(trades) if trades else 0

        # Momentum: 60d return
        ret_60d = ((closes[-1] / closes[-61]) - 1) * 100 if len(closes) >= 61 else 0

        # RSI(14) for sector trend
        rsi14_vals = _entry.calc_rsi(closes, 14) if len(closes) >= 15 else 50

        # Above SMA50?
        sma50_val = sma_arr[-1] if len(sma_arr) > 0 else 0
        above_sma50 = closes[-1] > sma50_val if sma50_val > 0 else False

        # Trend: BULL if above SMA50 + 20d > 0, BEAR if below + 20d < 0
        if above_sma50 and ret_20d > 0:
            trend = "BULL"
        elif not above_sma50 and ret_20d < 0:
            trend = "BEAR"
        else:
            trend = "SIDEWAYS"

        # Live price from Finnhub
        live = _price_cache.get(etf)
        if live and live.get("price", 0) > 0:
            price = live["price"]

        sectors.append({
            "etf": etf, "name": name, "price": round(price, 2),
            "ret_5d": round(ret_5d, 2), "ret_20d": round(ret_20d, 2), "ret_60d": round(ret_60d, 2), "ret_ytd": round(ret_ytd, 2),
            "mr_wr": round(mr_wr, 1), "mr_trades": len(trades), "mr_avg_ret": round(mr_avg, 2),
            "rsi14": round(rsi14_vals, 1) if isinstance(rsi14_vals, float) else 50,
            "above_sma50": above_sma50, "trend": trend,
        })

    # Portfolio sector exposure
    positions = _position_mgr._get_open_positions_sync()
    exposure = {}
    for pos in positions:
        ticker = pos["ticker"]
        sector = STOCK_SECTORS.get(ticker, "Unknown")
        if sector not in exposure:
            exposure[sector] = {"tickers": [], "cost": 0, "value": 0}
        live = _price_cache.get(ticker, {})
        price = live.get("price", pos["entry_price"]) if live else pos["entry_price"]
        exposure[sector]["tickers"].append(ticker)
        exposure[sector]["cost"] += pos["entry_price"] * pos["shares"]
        exposure[sector]["value"] += price * pos["shares"]

    total_value = sum(e["value"] for e in exposure.values())
    portfolio_exposure = [
        {"sector": sec, "tickers": data["tickers"], "cost": round(data["cost"], 2),
         "value": round(data["value"], 2), "weight": round(data["value"] / total_value * 100, 1) if total_value else 0}
        for sec, data in sorted(exposure.items(), key=lambda x: -x[1]["value"])
    ]

    # Sort sectors by YTD (leaders first)
    sectors.sort(key=lambda x: x["ret_ytd"], reverse=True)

    return {
        "timestamp": datetime.now().isoformat(),
        "sectors": sectors,
        "portfolio_exposure": portfolio_exposure,
        "total_sectors_used": len(exposure),
        "total_sectors": len(SECTORS),
        "market_regime": _check_market_regime(),
    }


# ── Momentum Scanner Endpoints ──

_momentum_cache: Optional[Dict] = None
_momentum_cache_time: Optional[datetime] = None
_momentum_running: bool = False

# Global scan/refresh status — frontend polls this to show progress
_system_status: Dict = {"stage": "idle", "message": "", "progress": 0}


@router.get("/momentum/opportunities")
async def get_momentum_opportunities():
    """Get momentum breakout signals."""
    global _momentum_cache, _momentum_cache_time, _momentum_running

    if _momentum_cache:
        return {**_momentum_cache, "last_scan": _momentum_cache_time.isoformat() if _momentum_cache_time else ""}

    # Try loading from disk cache
    from momentum_scanner import MomentumScanner, MomentumSignal, CACHE_DIR
    from dataclasses import asdict
    cache_path = os.path.join(CACHE_DIR, f"momentum_{datetime.now().strftime('%Y-%m-%d')}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                raw = json.load(f)
            signals = [MomentumSignal(**r) for r in raw]
            valid = [r for r in signals if not r.vetoed]
            _momentum_cache = {
                "timestamp": datetime.now().isoformat(),
                "total_scanned": len(raw),
                "valid": len(valid),
                "signals": [asdict(r) for r in signals],
            }
            _momentum_cache_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
            return {**_momentum_cache, "last_scan": _momentum_cache_time.isoformat()}
        except Exception as e:
            print(f"[Momentum] Cache load error: {e}")

    # No cache — trigger momentum scan in subprocess (non-blocking)
    if not _momentum_running:
        _momentum_running = True
        asyncio.create_task(_run_momentum_scan())

    return {"timestamp": datetime.now().isoformat(), "total_scanned": 0, "valid": 0,
            "signals": [], "scanning": True}


async def _run_momentum_scan():
    """Run momentum scan in subprocess — non-blocking."""
    global _momentum_cache, _momentum_cache_time, _momentum_running
    try:
        print("[Momentum] Starting scan in subprocess...")
        import subprocess
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            "import asyncio; from momentum_scanner import MomentumScanner; asyncio.run(MomentumScanner().run(fresh=True))",
            cwd=os.path.dirname(__file__),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            if stdout:
                for line in stdout.decode().split('\n')[-5:]:
                    if line.strip():
                        print(f"[Momentum] {line.strip()}")
        except asyncio.TimeoutError:
            proc.kill()
            print("[Momentum] Subprocess timed out")

        # Load from disk
        from momentum_scanner import MomentumSignal, CACHE_DIR
        from dataclasses import asdict
        cache_path = os.path.join(CACHE_DIR, f"momentum_{datetime.now().strftime('%Y-%m-%d')}.json")
        if os.path.exists(cache_path):
            with open(cache_path) as f:
                raw = json.load(f)
            signals = [MomentumSignal(**r) for r in raw]
            valid = [r for r in signals if not r.vetoed]
            _momentum_cache = {
                "timestamp": datetime.now().isoformat(),
                "total_scanned": len(raw),
                "valid": len(valid),
                "signals": [asdict(r) for r in signals],
            }
            _momentum_cache_time = datetime.now()
            print(f"[Momentum] Scan complete: {len(valid)} valid signals")
        else:
            print(f"[Momentum] No cache file found after subprocess")
    except Exception as e:
        import traceback
        print(f"[Momentum] Scan error: {e}")
        traceback.print_exc()
    finally:
        _momentum_running = False


@router.post("/momentum/refresh")
async def refresh_momentum():
    """Force a fresh momentum scan."""
    global _momentum_cache, _momentum_running
    _momentum_cache = None
    _momentum_running = True
    asyncio.create_task(_run_momentum_scan())
    return {"status": "scanning", "message": "Momentum scan started."}


# ── KDE Adaptive Cascade strategy lane ─────────────────────────────────────────
_kde_engine = None
_kde_engine_label = "default"


def _get_kde_engine():
    global _kde_engine
    if _kde_engine is None:
        try:
            from atlas_v2.kde_strategy import KDEStrategyEngine
            _kde_engine = KDEStrategyEngine(label=_kde_engine_label)
        except FileNotFoundError as e:
            return None, str(e)
        except Exception as e:
            return None, f"KDE engine init failed: {e}"
    return _kde_engine, None


@router.get("/scan/kde")
async def scan_kde(limit: int = 30, min_price: float = 5.0):
    """KDE Adaptive Cascade signals — third strategy lane.

    Backtest (500 tickers, 6.2yr walk-forward, 20 slots, no stop):
      $14K → $224K, CAGR +56.2%, Sharpe 1.82, max DD -66.9%

    Sizing recommendation: 5% per position (target 20 slots), max 10% concentration cap,
    14d same-name cooldown, NO stop-loss (kills momentum upside).
    """
    engine, err = _get_kde_engine()
    if engine is None:
        return {"status": "no_model", "error": err,
                "hint": "Run: python3 -m atlas_v2.kde_train --tickers 500"}
    held = {p["ticker"] for p in (_position_mgr._get_open_positions_sync() or [])}
    t0 = time.time()
    signals = engine.score_universe(min_price=min_price, held_tickers=held, limit=limit)
    return {
        "timestamp": datetime.now().isoformat(),
        "elapsed_sec": round(time.time() - t0, 2),
        "model_meta": engine.meta(),
        "n_signals": len(signals),
        "signals": [
            {
                "ticker": s.ticker, "price": s.price, "score": round(s.score, 4),
                "expected_return_pct": round(s.expected_return_pct, 2),
                "p_big_winner": round(s.p_big_winner, 3),
                "best_horizon_days": s.best_horizon_days,
                "regime": s.regime,
                "rsi2": s.rsi2, "atr_pct": s.atr_pct,
                "sma50_buf_pct": s.sma50_buf_pct, "mom20_pct": s.mom20_pct,
                "data_date": s.data_date,
                "horizon_breakdown": s.horizon_breakdown,
            } for s in signals
        ],
        "sizing_hint": {
            "target_slots": 20,
            "position_size_pct_of_book": 5.0,
            "max_concentration_pct": 10.0,
            "cooldown_days": 14,
            "stop_loss": None,  # Intentionally none
            "rationale": "Best-practice diversification; KDE picks fat-tail momentum names that need to ride deep drawdowns.",
        },
    }


@router.post("/scan/kde/retrain")
async def retrain_kde():
    """Trigger KDE model retraining in background (subprocess)."""
    import subprocess
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "atlas_v2.kde_train",
        "--tickers", "500", "--label", _kde_engine_label,
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    # Reset engine so next scan reloads new bundle
    global _kde_engine
    _kde_engine = None
    return {"status": "training_started", "pid": proc.pid,
            "message": "KDE retrain in progress. Refresh /scan/kde in ~10 minutes."}


@router.get("/system/status")
async def get_system_status():
    """Current system status — what's running, what stage."""
    return {**_system_status, "timestamp": datetime.now().isoformat()}


@router.get("/data/status")
async def get_data_status():
    """Data freshness dashboard — shows cache age, quote freshness, market session."""
    from datetime import date as _date

    today_str = _date.today().isoformat()

    # 1. Historical cache freshness
    positions = _position_mgr._get_open_positions_sync()
    holding_tickers = [p["ticker"] for p in positions] if positions else []
    cache_status = {}
    stale_count = 0
    for t in holding_tickers + ["SPY", "QQQ", "VIX"]:
        df = _cache.get(t, 365)
        is_fresh = _cache.is_fresh(t)
        latest = str(df.index[-1].date()) if df is not None and len(df) > 0 else None
        rows = len(df) if df is not None else 0
        if not is_fresh:
            stale_count += 1
        cache_status[t] = {"latest": latest, "rows": rows, "fresh": is_fresh}

    # 2. Live quote freshness
    quote_status = {}
    for t in holding_tickers:
        q = _price_cache.get(t, {})
        quote_status[t] = {
            "price": q.get("price", 0),
            "ts": q.get("ts", ""),
            "age_sec": (datetime.now() - q["ts"]).total_seconds() if isinstance(q.get("ts"), datetime) else None,
        }

    # 3. Extended hours
    ext_status = {}
    session = _get_market_session()
    for t in holding_tickers:
        ext = _extended_hours_cache.get(t, {})
        if ext:
            ext_status[t] = {
                "ext_price": ext.get("ext_price"),
                "session": ext.get("session"),
                "ts": ext.get("ts").isoformat() if isinstance(ext.get("ts"), datetime) else None,
            }

    # 4. Market regime
    regime = _check_market_regime()

    # 5. Scan cache age — use entries file (combined scanner), not old scan cache
    scan_age_min = None
    entries_path = os.path.join(os.path.dirname(__file__), "data", f"entries_{today_str}.json")
    if os.path.exists(entries_path):
        scan_age_min = (datetime.now().timestamp() - os.path.getmtime(entries_path)) / 60
    elif _scan_cache_time:
        scan_age_min = (datetime.now() - _scan_cache_time).total_seconds() / 60

    # 6. Portfolio earnings warnings (Tiingo News, tags=earnings, ±7d window).
    # Cached for 30 min — earnings news doesn't move that fast and Tiingo's
    # news endpoint costs us API calls we don't want to burn on every poll.
    earnings_status = await _portfolio_earnings_cached(holding_tickers)

    # 6b. Portfolio biotech catalyst warnings — Tiingo News regex for clinical
    # trial readouts, FDA decisions, PDUFA dates, NDA/BLA filings. Built after
    # 2026-06-02 when we held CELC through a Phase 3 readout (-24.6%) that the
    # earnings detector couldn't see. Same UI shape as earnings: upcoming
    # (WARN) vs reported (INFO).
    catalysts_status = await _portfolio_catalysts_cached(holding_tickers)

    # 7. Backtest cache freshness — this is the WR/zone_return source for every
    # ranking decision. We discovered on 2026-05-27 it can sit 9 days stale
    # during quiet market periods (cache_refresh_loop skips precompute when
    # `stale_tickers` is empty even after-close). Surface its age prominently
    # so users see when ranking is operating on old data.
    backtest_cache_age_hours = None
    backtest_cache_last_computed = None
    backtest_cache_rows = 0
    try:
        import sqlite3
        _sc_db = os.path.join(os.path.dirname(__file__), "data", "stock_cache.db")
        _bt_conn = sqlite3.connect(_sc_db)
        _bt_cur = _bt_conn.cursor()
        _bt_cur.execute("SELECT MAX(last_computed), COUNT(*) FROM backtest_cache")
        _row = _bt_cur.fetchone()
        _bt_conn.close()
        if _row and _row[0]:
            backtest_cache_last_computed = _row[0]
            backtest_cache_rows = _row[1] or 0
            # last_computed is YYYY-MM-DD; treat as midnight ET on that date
            _last = datetime.fromisoformat(_row[0] + "T00:00:00")
            backtest_cache_age_hours = round((datetime.now() - _last).total_seconds() / 3600, 1)
    except Exception:
        pass

    return {
        "timestamp": datetime.now().isoformat(),
        "today": today_str,
        "market_session": session,
        "cache": {
            "stale_count": stale_count,
            "total_checked": len(cache_status),
            "tickers": cache_status,
        },
        "quotes": {
            "cached_count": len([q for q in quote_status.values() if q["price"] > 0]),
            "tickers": quote_status,
        },
        "extended_hours": {
            "available": len(ext_status),
            "session": session,
            "tickers": ext_status,
        },
        "market_regime": regime,
        "scan_cache_age_min": round(scan_age_min, 1) if scan_age_min else None,
        "backtest_cache": {
            "last_computed": backtest_cache_last_computed,
            "age_hours": backtest_cache_age_hours,
            "rows": backtest_cache_rows,
        },
        "system": _system_status,
        "portfolio_earnings": earnings_status,
        "portfolio_catalysts": catalysts_status,
    }


# Cache for portfolio earnings — 30 min TTL, keyed by sorted ticker tuple.
_earnings_cache: Dict[tuple, tuple] = {}  # (tickers,) -> (result_dict, datetime)
_catalysts_cache: Dict[tuple, tuple] = {}  # same shape, biotech catalyst hits
_next_earnings_cache: Dict[tuple, tuple] = {}  # {ticker: {date, days_to}} per held set
_EARNINGS_CACHE_TTL_SEC = 1800  # 30 min


async def _portfolio_next_earnings_cached(tickers: list) -> dict:
    """Forward-looking NEXT-earnings date per holding (Finnhub calendar), cached 30 min.

    Powers the positions-table "Next Event" column — answers "when does this
    stock next report?" even when the date is weeks out (the ±14d earnings
    warning helper above can't see that far). Returns {ticker: {date, days_to}}.
    """
    if not tickers:
        return {}
    key = tuple(sorted(tickers))
    cached = _next_earnings_cache.get(key)
    if cached:
        result, ts = cached
        if (datetime.now() - ts).total_seconds() < _EARNINGS_CACHE_TTL_SEC:
            return result
    try:
        from tiingo_earnings import next_earnings_batch
        async with aiohttp.ClientSession() as ses:
            result = await next_earnings_batch(ses, list(tickers), forward_days=80)
    except Exception:
        result = {}
    _next_earnings_cache[key] = (result, datetime.now())
    return result


async def _portfolio_earnings_cached(tickers: list) -> dict:
    """Tiingo News earnings check for portfolio holdings, cached 30 min.

    Splits hits into two semantically-distinct groups:
      - upcoming: forward-event articles ("earnings preview", "set to report",
        "Before May 20 Earnings"). These are WARNINGS — binary event risk
        ahead, per CLAUDE.md "earnings within 7 days = VETO" rule.
      - reported: just-released results ("Q3 Earnings Call Highlights",
        "Reports first quarter"). These are INFO — event already happened,
        market has digested it; no further binary risk.

    Frontend pill shows upcoming prominently and reported as muted info.
    """
    if not tickers:
        return {"count": 0, "upcoming": [], "reported": []}
    key = tuple(sorted(tickers))
    cached = _earnings_cache.get(key)
    if cached:
        result, ts = cached
        if (datetime.now() - ts).total_seconds() < _EARNINGS_CACHE_TTL_SEC:
            return result
    try:
        from tiingo_earnings import earnings_window_batch
        async with aiohttp.ClientSession() as ses:
            hits = await earnings_window_batch(ses, list(tickers), days=14)
        upcoming = []
        reported = []
        for tk, h in sorted(hits.items()):
            entry = {
                "ticker": tk,
                "kind": h.get("kind", ""),
                "direction": h.get("direction", ""),
                "age_hours": h.get("age_hours", 0),
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "date": h.get("date", ""),
            }
            if entry["kind"] == "upcoming":
                upcoming.append(entry)
            else:
                reported.append(entry)
        result = {
            "count": len(upcoming) + len(reported),
            "upcoming": upcoming,
            "reported": reported,
        }
    except Exception as e:
        result = {"count": 0, "upcoming": [], "reported": [], "error": str(e)}
    _earnings_cache[key] = (result, datetime.now())
    return result


async def _portfolio_catalysts_cached(tickers: list) -> dict:
    """Tiingo News biotech-catalyst check for portfolio holdings, cached 30 min.

    Same shape as `_portfolio_earnings_cached` so the frontend can render both
    pills identically:
      - upcoming: scheduled trial readouts, conference calls, PDUFA dates ahead.
        These should fire the EXIT trigger on held biotechs (binary risk ahead).
      - reported: just-disclosed trial results or FDA decisions. Informational;
        the binary event has already happened.

    Built after the CELC -24.6% Phase 3 readout on 2026-06-02 and PRAX trial
    setback on 2026-06-01 — both class events that our earnings detector
    couldn't see. See `tiingo_biotech_catalyst.py` for the regex specifics.
    """
    if not tickers:
        return {"count": 0, "upcoming": [], "reported": []}
    key = tuple(sorted(tickers))
    cached = _catalysts_cache.get(key)
    if cached:
        result, ts = cached
        if (datetime.now() - ts).total_seconds() < _EARNINGS_CACHE_TTL_SEC:
            return result
    try:
        from tiingo_biotech_catalyst import catalyst_window_batch
        async with aiohttp.ClientSession() as ses:
            hits = await catalyst_window_batch(ses, list(tickers), days=14)
        upcoming = []
        reported = []
        for tk, h in sorted(hits.items()):
            entry = {
                "ticker": tk,
                "kind": h.get("kind", ""),
                "direction": h.get("direction", ""),
                "age_hours": h.get("age_hours", 0),
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "date": h.get("date", ""),
                "catalyst_type": h.get("catalyst_type", "other"),
            }
            if entry["kind"] == "upcoming":
                upcoming.append(entry)
            else:
                reported.append(entry)
        result = {
            "count": len(upcoming) + len(reported),
            "upcoming": upcoming,
            "reported": reported,
        }
    except Exception as e:
        result = {"count": 0, "upcoming": [], "reported": [], "error": str(e)}
    _catalysts_cache[key] = (result, datetime.now())
    return result


@router.post("/backtest/refresh")
async def refresh_backtest_cache():
    """Re-run backtest precompute + evaluator. ~20s total."""
    from backtest_precompute import precompute_all
    _system_status.update({"stage": "precomputing", "message": "Pre-computing backtests...", "progress": 50})
    result = await asyncio.to_thread(precompute_all, force=True)
    _system_status.update({"stage": "evaluating", "message": "Fast scan...", "progress": 90})
    from strategy_evaluator import evaluate_all, save_cache
    positions = _position_mgr._get_open_positions_sync()
    held = set(p["ticker"] for p in positions) if positions else set()
    live_px = _fresh_live_px()
    signals = await asyncio.to_thread(evaluate_all, 10.0, held, live_px)
    save_cache(signals)
    valid = sum(1 for s in signals if not s.vetoed)
    _system_status.update({"stage": "ready", "message": f"{valid} entries ready", "progress": 100})
    return {"status": "ok", "precompute": result, "entries": valid}


@router.post("/cache/populate")
async def populate_cache(days: int = 10, ticker: Optional[str] = None):
    """Fetch historical data via Tiingo. days=10 for daily refresh, days=2600 for 10yr backfill.
    Pass ticker=XYZ to backfill only one stock (cheap, ~20KB per ticker)."""
    label = f"{days}d" if days <= 30 else f"{days//365}yr"
    _system_status.update({"stage": "populating", "message": f"Fetching {label} history for all stocks...", "progress": 0})
    try:
        if ticker:
            targets = [ticker.upper()]
        else:
            stale = _cache.get_stale_tickers()
            all_tickers = _cache.get_cached_tickers()
            # For long backfill, re-fetch ALL tickers (not just stale)
            targets = all_tickers if days > 30 else stale
        if not targets:
            return {"status": "ok", "message": "All tickers already fresh"}

        # Fetch with specified lookback
        import time as _time
        sem = asyncio.Semaphore(20)
        refreshed = 0
        failed = 0
        t0 = _time.time()

        async with aiohttp.ClientSession() as session:
            async def fetch_one(ticker):
                nonlocal refreshed, failed
                async with sem:
                    result = await _cache._fetch_tiingo(session, ticker, days=days, min_rows=1 if days <= 30 else 50)
                    if isinstance(result, pd.DataFrame):
                        _cache.store(ticker, result)
                        refreshed += 1
                    else:
                        failed += 1

            for i in range(0, len(targets), 100):
                batch = targets[i:i + 100]
                await asyncio.gather(*[fetch_one(t) for t in batch])
                done = min(i + 100, len(targets))
                elapsed = _time.time() - t0
                rate = refreshed / elapsed * 60 if elapsed > 0 else 0
                _system_status.update({
                    "stage": "populating",
                    "message": f"Fetching {label}: {done}/{len(targets)} ({refreshed} OK, {elapsed:.0f}s)",
                    "progress": int(done / len(targets) * 80)
                })

        result = {"refreshed": refreshed, "failed": failed}
        # Also re-run evaluator
        _system_status.update({"stage": "evaluating", "message": "Re-evaluating...", "progress": 80})
        from strategy_evaluator import evaluate_all as _eval_all, save_cache as _save_eval
        positions = _position_mgr._get_open_positions_sync()
        held = set(p["ticker"] for p in positions) if positions else set()
        live_px = _fresh_live_px()
        signals = await asyncio.to_thread(_eval_all, 10.0, held, live_px)
        _save_eval(signals)
        valid = sum(1 for s in signals if not s.vetoed)
        _system_status.update({"stage": "ready", "message": f"{valid} entries ready", "progress": 100})
        return {"status": "ok", "refreshed": result.get("refreshed", 0), "failed": result.get("failed", 0), "entries": valid}
    except Exception as e:
        _system_status.update({"stage": "error", "message": str(e), "progress": 0})
        return {"status": "error", "message": str(e)}


@router.get("/scan/combined")
async def get_combined_opportunities():
    """Fresh entry signals — ensures historical data is up-to-date before evaluating.

    Pipeline:
    1. Check if entries cache exists and is fresh (today, < 30 min old)
    2. If stale: refresh historical data for ALL stale tickers via Tiingo (10d window)
    3. Evaluate 3,000+ stocks for MR + Momentum signals (~5s)
    4. Validate top 30 with earnings/sentiment/analyst (~15s)
    5. Overlay live intraday prices via Tiingo IEX batch
    6. Cache results to disk for subsequent requests

    RULE: Never show entries based on stale historical data. Every entry must have
    yesterday's close at minimum. This prevents phantom RSI signals from price gaps.
    """
    from strategy_evaluator import evaluate_all, validate_top_signals, load_cache, load_most_recent_cache, save_cache, EntrySignal
    from dataclasses import asdict

    # Try disk cache first — but only if from TODAY and < 30 min old
    cached = load_cache()
    cache_age_min = 999
    cache_stale = False
    cache_date_str = datetime.now().strftime("%Y-%m-%d")
    import os as _os
    cache_path = _os.path.join(_os.path.dirname(__file__), "data", f"entries_{datetime.now().strftime('%Y-%m-%d')}.json")
    if cached and _os.path.exists(cache_path):
        cache_age_min = (datetime.now().timestamp() - _os.path.getmtime(cache_path)) / 60

    needs_refresh = (not cached or cache_age_min > 30
                     or (cached and len(cached) < 20))

    if needs_refresh:
        # NON-BLOCKING (2026-06-20 fix): never run evaluate_all + validate_top_signals
        # inline — that ~15s+ of work can exceed the request timeout on a cold/new-day
        # machine and made the entries tab fail to load entirely. Instead, kick off a
        # background scan and serve whatever cache we have RIGHT NOW. The frontend polls
        # every 60s, so the fresh result appears within a poll or two. This also lets the
        # machine auto-stop safely (the wake request returns fast instead of hanging).
        if not _scan_running:
            asyncio.create_task(_background_full_scan())
        if not cached:
            # No cache for today — serve the most recent so the tab isn't empty while
            # the background build runs. (cache_stale flags it in the UI.)
            fallback, fallback_date, age_days = load_most_recent_cache()
            if fallback:
                cached = fallback
                cache_stale = True
                cache_date_str = fallback_date or cache_date_str
                cache_age_min = (age_days or 0) * 24 * 60
                _system_status.update({"stage": "building", "message": f"Building today's scan… serving {fallback_date}", "progress": 30})
            else:
                # Nothing cached anywhere (first-ever boot) — return fast with a
                # building status; the background scan fills it in shortly.
                _system_status.update({"stage": "building", "message": "Building first scan…", "progress": 10})
                return {
                    "timestamp": datetime.now().isoformat(),
                    "total": 0, "mean_reversion": 0, "momentum": 0, "both": 0,
                    "passed": 0, "upgrades": 0,
                    "tier_counts": {"BEST": 0, "GOOD": 0, "FAIR": 0, "WEAK": 0, "POOR": 0},
                    "ranked_count": 0, "total_scanned": 0,
                    "holdings_scores": [], "worst_holding": "", "worst_score": 0,
                    "data_date": "", "cache_age_min": 0, "cache_stale": True,
                    "refreshing": True, "scanning": True,
                    "live_prices": 0, "stale_tickers": len(_cache.get_stale_tickers()),
                    "signals": [], "system_status": _system_status,
                    "market_regime": _check_market_regime(),
                }
        # else: today's cache exists but is stale/>30min — serve it now; the background
        # scan above refreshes it for the next poll.

    if cached:
        # Regime gate enforcement (over the FULL cached list so a recovered
        # regime can clear its own vetoes): DANGER/CRISIS pause everything,
        # WEAK pauses MEAN_REVERSION only — momentum and BOTH still qualify.
        _regime_now = _check_market_regime()
        _apply_regime_gate(cached, _regime_now, mr_only=True)
        valid = [s for s in cached if not s.get("vetoed")]

        # Step 4: Fetch live prices via Tiingo IEX batch, then overlay + recompute technicals
        session_now = _get_market_session()
        live_count = 0

        if session_now in ("REGULAR", "PRE_MARKET", "AFTER_HOURS") and valid:
            all_entry_tickers = list({s["ticker"] for s in valid})
            try:
                await _fetch_tiingo_iex_batch(all_entry_tickers)
            except Exception as e:
                print(f"[Combined] Tiingo IEX batch error: {e}")

        # Preserve the scan price, then overlay live + recompute RSI/SMA50/ATR.
        # Overlay can introduce new vetoes (stale data, crash, below-SMA50) — refilter.
        for s in valid:
            s["scan_price"] = s["price"]
            _apply_live_overlay(s)
            if s.get("price_is_live"):
                live_count += 1
        valid = [s for s in valid if not s.get("vetoed")]

        # NOTE: tiingo_earnings.earnings_window_combined returns ANY news article
        # mentioning the ticker — not actual earnings reports (verified 2026-06-03:
        # AAPL flagged for WWDC article, APP for unrelated app news, etc — 94% FP).
        # The earnings VETO must run at cache-write time via validate_top_signals
        # which uses a different (stricter) check. The per-request re-check is
        # too noisy. Bug 4 needs a different fix (real earnings calendar query).

        # ═══ V3.2 SINGLE SOURCE OF TRUTH (2026-06-03) ═══
        # Enrich every signal with composite_score / quality_tier / meets_strict /
        # beats_holdings / is_upgrade — same fields that /scan/opportunities returns.
        # Frontend Entries tab can now consume ONLY /scan/combined and get a fully
        # ranked list. No more dual-endpoint merge, no scale-mixing bug.
        try:
            holdings_scores, worst_h, worst_s = _get_holdings_scores()
        except Exception as _e:
            holdings_scores = {}; worst_h = ""; worst_s = 0
        for s in valid:
            # Build the dict shape _compute_composite_score expects. Map the
            # EntrySignal fields to the opp-style keys (avg_return ← expected_return,
            # win_rate ← confidence). Zone fields are absent in /scan/combined,
            # so the composite_score logic falls back to the per-stock backtest
            # numbers (which is the right behavior).
            score_input = {
                "rsi2": s.get("rsi2", 0),
                "atr_pct": s.get("atr_pct", 0),
                "sma50_buffer": s.get("sma50_buffer", 0),
                "volume_ratio": s.get("volume_ratio", 0),
                "analyst_consensus": s.get("analyst_consensus", ""),
                "analyst_upside": s.get("analyst_upside", 0),  # not currently populated
                "sentiment_label": s.get("sentiment_label", ""),
                "sentiment_score": s.get("sentiment_score", 0),  # not currently populated
                "price": s.get("price", 0),
                # Per-stock backtest stats from the cached signal
                "avg_return": s.get("expected_return", 0),
                "win_rate": s.get("confidence", 0),
                "trades": s.get("trades", 0),
                # Zone fields absent here — composite_score will skip zone-specific paths
                "zone_return": 0,
                "zone_win_rate": 0,
                "zone_trades": 0,
                # BOTH-strategy bonus needs ret_20d (already in EntrySignal as ret_20d)
                "ret_20d": s.get("ret_20d", 0),
                "ret20": s.get("ret_20d", 0),
            }
            composite, factors = _compute_composite_score(score_input)
            s["composite_score"] = composite
            s["ranking_factors"] = factors
            s["quality_tier"] = _quality_tier(composite)
            s["meets_strict"] = _meets_strict_criteria(score_input)
            # Holdings comparison: does this candidate's EV beat any current holding?
            if holdings_scores:
                cand_ev = _ev_score(score_input["avg_return"], score_input["win_rate"], score_input["trades"])
                beats = []
                for h_tkr, h_data in holdings_scores.items():
                    h_score = h_data.get("score", 0) or 0
                    if h_score > 0 and cand_ev > h_score * 1.10:  # 10% margin
                        beats.append(h_tkr)
                s["beats_holdings"] = beats
                s["is_upgrade"] = bool(beats) and not s.get("vetoed", False)
            else:
                s["beats_holdings"] = []
                s["is_upgrade"] = False

        mr = sum(1 for s in valid if s.get("strategy") == "MEAN_REVERSION")
        mom = sum(1 for s in valid if s.get("strategy") == "MOMENTUM")
        both = sum(1 for s in valid if s.get("strategy") == "BOTH")
        passed = sum(1 for s in valid if s.get("meets_strict"))
        upgrades = sum(1 for s in valid if s.get("is_upgrade"))
        data_date = cached[0].get("data_date", "") if cached else ""
        stale_left = len(_cache.get_stale_tickers())

        # Quality tier counts (for header chips) — V3.3 SSOT
        tier_counts = {"BEST": 0, "GOOD": 0, "FAIR": 0, "WEAK": 0, "POOR": 0}
        for s in valid:
            t = s.get("quality_tier", "POOR")
            if t in tier_counts:
                tier_counts[t] += 1

        # Holdings scores + worst holding (was previously only on /scan/opportunities).
        # Embed here so the frontend never has to call two endpoints.
        try:
            holdings_scores_dict, worst_h_tkr, worst_h_score = _get_holdings_scores()
            holdings_scores_list = [
                {"ticker": tkr, "score": d.get("score", 0),
                 "zone_return": d.get("zone_return", 0), "win_rate": d.get("win_rate", 0),
                 "exit_triggered": d.get("exit_triggered", False),
                 "signal": d.get("signal", "HOLD")}
                for tkr, d in (holdings_scores_dict or {}).items()
            ]
        except Exception as _e:
            print(f"[Combined] holdings_scores error: {_e}")
            holdings_scores_list = []; worst_h_tkr = ""; worst_h_score = 0

        # Auto-refresh guard: if bars are >1 trading day stale, kick off a background
        # refresh. Non-blocking — this request returns now; next request gets fresh data.
        if data_date and _cache_is_stale(data_date, max_trading_days=1) and not _auto_refresh_running:
            print(f"[Combined] data_date {data_date} is stale, triggering background refresh")
            asyncio.create_task(_auto_refresh_stale_cache())
        return {
            "timestamp": datetime.now().isoformat(),
            "total": len(valid), "mean_reversion": mr, "momentum": mom, "both": both,
            "passed": passed,            # meets_strict count for header chip
            "upgrades": upgrades,        # is_upgrade count
            "tier_counts": tier_counts,  # V3.3 SSOT — BEST/GOOD/FAIR/WEAK/POOR
            "ranked_count": len(valid),  # V3.3 SSOT — alias for "total" (frontend reads either)
            "total_scanned": len(cached) if cached else 0,  # V3.3 SSOT — universe size
            "holdings_scores": holdings_scores_list,  # V3.3 SSOT — was on /scan/opportunities only
            "worst_holding": worst_h_tkr,             # V3.3 SSOT
            "worst_score": worst_h_score,             # V3.3 SSOT
            "data_date": data_date,
            "cache_age_min": round(cache_age_min, 1),
            "cache_stale": cache_stale,
            "cache_date": cache_date_str,
            "refreshing": _auto_refresh_running or _scan_running,  # V3.3 SSOT
            "scanning": _scan_running,                              # V3.3 SSOT
            "live_prices": live_count,
            "stale_tickers": stale_left,
            "market_session": session_now,  # so the UI only flags "stale" prices when market is OPEN
            "signals": valid,
            "system_status": _system_status,
            "market_regime": _regime_now,
        }

@router.post("/scan/refresh-all")
async def refresh_all_scans():
    """Full refresh: update stale historical data, then re-evaluate all strategies."""
    from strategy_evaluator import evaluate_all, validate_top_signals, save_cache, load_cache
    import os as _os

    # Clear today's cache
    cache_path = _os.path.join(_os.path.dirname(__file__), "data", f"entries_{datetime.now().strftime('%Y-%m-%d')}.json")
    if _os.path.exists(cache_path):
        _os.remove(cache_path)

    # Data freshness handled by background cache_refresh_loop.
    # Staleness guard in evaluator skips stocks with >3d old data.
    refreshed_count = 0
    _system_status.update({"stage": "evaluating", "message": "Evaluating 3,000+ stocks...", "progress": 50})
    positions = _position_mgr._get_open_positions_sync()
    held = set(p["ticker"] for p in positions) if positions else set()
    live_px = _fresh_live_px()
    signals = await asyncio.to_thread(evaluate_all, 10.0, held, live_px)

    # Step 3: Validate top 30
    _system_status.update({"stage": "validating", "message": "Checking earnings, sentiment, analyst...", "progress": 75})
    signals = await validate_top_signals(signals, top_n=50)
    save_cache(signals)
    valid = [s for s in signals if not s.vetoed]
    _system_status.update({"stage": "ready", "message": f"{len(valid)} entries ready", "progress": 100})
    return {
        "status": "done",
        "message": f"Refreshed {refreshed_count} tickers, evaluated {len(signals)} stocks, {len(valid)} valid entries",
        "total": len(valid), "refreshed": refreshed_count,
    }


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

        # Skip dust trades (fractional share leftovers)
        if status == "CLOSED" and shares < 0.1 and abs(pnl) < 1:
            continue

        if status != "CLOSED":
            result = "OPEN"
        elif abs(pnl) < 0.01:
            result = "BREAK_EVEN"
        elif pnl > 0:
            result = "WIN"
        else:
            result = "LOSS"

        trades.append(TradePerformance(
            ticker=ticker, status="OPEN" if status != "CLOSED" else "CLOSED",
            entry_date=entry_date, exit_date=exit_date, hold_days=hold_days,
            entry_price=round(entry_price, 2), exit_price=round(exit_price, 2),
            shares=round(shares, 4), cost=round(cost, 2), value=round(value, 2),
            pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2), result=result,
        ))

    # Historical deposits (broker-verified, baked into the curve before the
    # /positions/deposit endpoint existed). New deposits live in the DB.
    _deposits = [
        ("2026-01-04", 1500.00),
        ("2026-01-07", 1500.00),
        ("2026-01-08", 200.00),
        ("2026-01-15", 500.00),
        ("2026-01-30", 1500.21),
        ("2026-02-13", 3213.37),
        ("2026-02-27", 3478.00),
    ]
    # Merge in any DEPOSIT rows from the ledger so the curve picks up new
    # deposits recorded via /positions/deposit.
    try:
        for _r in conn.execute(
            "SELECT date, COALESCE(SUM(total),0) FROM transactions "
            "WHERE action='DEPOSIT' GROUP BY date"
        ).fetchall():
            _deposits.append((_r[0], float(_r[1])))
    except Exception:
        pass
    total_deposited = round(sum(d[1] for d in _deposits), 2)

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

        # Build cumulative realized P&L + fees + tax by date from transactions.
        # TAX rows (action='TAX') represent broker withholdings — they reduce
        # the daily P&L curve from the date they're recorded.
        tx_rows = conn.execute(
            "SELECT date, action, fee, total, realized_pnl FROM transactions ORDER BY date"
        ).fetchall()
        daily_realized = {}  # date -> cumulative realized P&L
        daily_fees = {}      # date -> cumulative fees
        daily_tax = {}       # date -> cumulative tax (broker withholdings)
        cum_realized = 0.0
        cum_fees = 0.0
        cum_tax = 0.0
        for tx in tx_rows:
            tx_date = tx["date"]
            rpnl = tx["realized_pnl"]
            if rpnl is not None:
                cum_realized += rpnl
            fee = tx["fee"] or 0
            cum_fees += fee
            if tx["action"] == "TAX":
                cum_tax += tx["total"] or 0
            daily_realized[tx_date] = cum_realized
            daily_fees[tx_date] = cum_fees
            daily_tax[tx_date] = cum_tax

        # Pre-sort realized dates for efficient forward-fill
        last_realized = 0.0
        last_fees = 0.0
        last_tax = 0.0

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

        # Only include today if regular market is open (not pre-market/closed)
        _perf_session = _get_market_session()
        end_date = today if _perf_session == "REGULAR" else today - timedelta(days=1)
        # Skip weekends for end_date
        while end_date.weekday() >= 5:
            end_date -= timedelta(days=1)

        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            # Forward-fill cumulative deposits up to this date
            while dep_idx < len(deposit_dates_iter) and deposit_dates_iter[dep_idx] <= date_str:
                deposited_so_far = _cum_deposits[deposit_dates_iter[dep_idx]]
                dep_idx += 1

            # Forward-fill cumulative realized P&L, fees, and tax up to this date
            while real_idx < len(realized_dates_list) and realized_dates_list[real_idx] <= date_str:
                d = realized_dates_list[real_idx]
                last_realized = daily_realized[d]
                last_fees = daily_fees[d]
                last_tax = daily_tax.get(d, last_tax)
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

            # Total P&L = realized + unrealized − fees − broker tax
            total_pnl = last_realized + unrealized - last_fees - last_tax
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
    total_fees = round(tx_summary.get("total_fees", 0), 2)
    realized_pnl_pct = round(total_realized / total_deposited * 100, 2) if total_deposited > 0 else 0

    # Advanced metrics from daily P&L curve
    _cagr = 0.0
    _max_dd = 0.0
    _sharpe = 0.0
    _pf = 0.0
    _avg_hold = 0.0

    if len(daily_pnl) >= 2:
        days_span = (date.fromisoformat(daily_pnl[-1].date) - date.fromisoformat(daily_pnl[0].date)).days
        years_span = days_span / 365.25 if days_span > 0 else 1

        # CAGR: based on P&L % relative to deposited capital (not absolute portfolio value,
        # which includes deposits and would give absurd numbers like +47,000%)
        last_pnl_pct = daily_pnl[-1].pnl_pct  # total P&L as % of deposited
        if years_span > 0.1:  # Need at least ~5 weeks for meaningful annualization
            # Convert total return % to CAGR: (1 + total_return)^(1/years) - 1
            total_return = last_pnl_pct / 100  # e.g. -2% = -0.02
            if total_return > -1:  # Can't CAGR a >100% loss
                _cagr = round(((1 + total_return) ** (1 / years_span) - 1) * 100, 1)
        else:
            # Too short to annualize — just show raw return
            _cagr = round(last_pnl_pct, 1)

        # Max Drawdown from daily curve
        pv_vals = [d.portfolio_value for d in daily_pnl]
        peak = pv_vals[0]
        for v in pv_vals:
            if v > peak:
                peak = v
            dd = ((v - peak) / peak) * 100 if peak > 0 else 0
            if dd < _max_dd:
                _max_dd = dd
        _max_dd = round(_max_dd, 2)

        # Sharpe (daily P&L% changes, annualized)
        pnl_pcts = [d.pnl_pct for d in daily_pnl]
        daily_rets = []
        for i in range(1, len(pnl_pcts)):
            daily_rets.append(pnl_pcts[i] - pnl_pcts[i-1])  # Daily change in P&L%
        if daily_rets and len(daily_rets) > 5:
            avg_dr = sum(daily_rets) / len(daily_rets)
            std_dr = (sum((r - avg_dr)**2 for r in daily_rets) / len(daily_rets)) ** 0.5
            _sharpe = round((avg_dr / std_dr) * (252 ** 0.5), 2) if std_dr > 0 else 0

    # Profit Factor
    gross_wins = sum(t.pnl for t in closed if t.pnl > 0)
    gross_losses = abs(sum(t.pnl for t in closed if t.pnl <= 0))
    _pf = round(gross_wins / gross_losses, 2) if gross_losses > 0 else 0

    # Avg hold days
    if closed:
        _avg_hold = round(sum(t.hold_days for t in closed) / len(closed), 1)

    _perf_total_tax = round(tx_summary.get("total_tax", 0), 2)
    result = PerformanceResponse(
        trades=sorted(trades, key=lambda t: t.entry_date, reverse=True),
        daily_pnl=daily_pnl,
        tax_rate=0,
        tax_amount=_perf_total_tax,    # broker tax withholdings, used by frontend Total P&L formula
        net_realized=round(total_realized, 2),
        net_pnl_pct=round(total_realized / total_deposited * 100, 2) if total_deposited > 0 else 0,

        total_realized=total_realized,
        total_unrealized=round(sum(t.pnl for t in open_trades), 2),
        total_fees=total_fees,
        total_deposited=total_deposited,
        realized_pnl_pct=realized_pnl_pct,
        win_count=len(wins),
        loss_count=len(losses),
        win_rate=round(len(wins) / (len(wins) + len(losses)) * 100, 1) if (wins or losses) else 0,
        avg_win_pct=round(sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else 0,
        avg_loss_pct=round(sum(t.pnl_pct for t in losses) / len(losses), 2) if losses else 0,
        best_trade=max(closed, key=lambda t: t.pnl_pct).ticker if closed else "",
        worst_trade=min(closed, key=lambda t: t.pnl_pct).ticker if closed else "",
        cagr=_cagr,
        max_drawdown=_max_dd,
        sharpe_ratio=_sharpe,
        profit_factor=_pf,
        avg_hold_days=_avg_hold,
        total_trades=len(closed),
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
    for i in range(50, len(closes) - 62):  # room for i+1+60
        hist_closes = closes[:i + 1]
        hist_rsi = _entry.calc_rsi(hist_closes, 2)
        hist_sma = _entry.calc_sma(hist_closes, 50)

        # Only consider valid buy signals (above SMA50)
        if hist_closes[-1] <= hist_sma:
            continue

        # % drop from recent 10-day high
        recent_high = max(closes[max(0, i - 10):i + 1])
        pct_drop = ((closes[i] - recent_high) / recent_high) * 100

        # 60-day forward return, next-day open entry, fee-adjusted (Fixed60d)
        entry_px = opens[i + 1] if i + 1 < len(opens) and opens[i + 1] > 0 else closes[i]
        exit_px = closes[i + 1 + 60]  # True 60-trading-day hold from entry
        ret = ((exit_px - entry_px) / entry_px) * 100 - _FEE_PCT

        for key, z in zones.items():
            if z["rsi_lo"] <= hist_rsi < z["rsi_hi"] and i > zone_last_exit[key]:
                z["trades"].append({"return": ret, "win": ret > 0})
                z["drops"].append(pct_drop)
                zone_last_exit[key] = i + 1 + 60

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
    bt = _backtest_mr(ticker)

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

        # 4. Earnings check — only upcoming (forward-event) hits set the VETO.
        # Reported earnings stay informational; setting earnings_date here would
        # mis-fire HELD→EXIT and NEW→WAIT signals after the event has cleared.
        earnings_date = None
        try:
            from deep_scanner import DeepScanner
            ds = DeepScanner()
            earnings = await ds._check_earnings(session, ticker)
            if earnings and earnings.get("kind") == "upcoming":
                earnings_date = earnings["date"]
        except Exception:
            pass

        # 4b. Biotech-catalyst check — Phase 1/2/3 readouts, PDUFA dates, FDA
        # decisions, NDA/BLA filings. Same VETO/EXIT semantics as earnings:
        # only `kind == "upcoming"` blocks new entries / triggers HELD exits.
        # Built after CELC -24.6% Phase 3 readout (2026-06-02) and PRAX trial
        # setback (2026-06-01) — both events the earnings detector missed.
        catalyst_warning = None
        try:
            from tiingo_biotech_catalyst import catalyst_window
            cat = await catalyst_window(session, ticker, days=14)
            if cat and cat.get("kind") == "upcoming":
                catalyst_warning = {
                    "date": cat.get("date"),
                    "title": cat.get("title"),
                    "catalyst_type": cat.get("catalyst_type", "other"),
                }
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
    if catalyst_warning:
        # Biotech catalyst — same priority/UI as earnings. Always surface as a
        # critical issue since trial readouts have wiped 25-50% in a session.
        issues.append(f"Biotech catalyst: {catalyst_warning['title'][:80]}")
    # Sentiment and analyst-target flags removed from issues — backtest (95K
    # signals, PIT data) shows both filters HURT edge on RSI(2)<10 entries.
    if exit_zt >= 5 and exit_zr < 1.0 and exit_zwr < 55:
        issues.append(f"Weak zone return (+{exit_zr:.1f}%, {exit_zwr:.0f}% WR)")

    # Check if this ticker is a current holding → apply hybrid exit strategy
    exit_strategy_info = {}
    former_holding_info = {}
    held_position_info = None
    try:
        import sqlite3
        _pos_db = os.path.join(os.path.dirname(__file__), "data", "positions.db")
        conn = sqlite3.connect(_pos_db)

        # Check current open position
        row = conn.execute("SELECT shares, entry_price, entry_date, strategy FROM positions WHERE ticker=? AND status='OPEN'", (ticker,)).fetchone()
        if row:
            # Held position: check hybrid exit
            pos_shares, pos_entry_price, pos_entry_date = row[0], row[1], row[2] or ""
            pos_strategy = row[3] if len(row) > 3 else "MR"
            # Calculate P&L and days held
            pnl = round((live_price - pos_entry_price) * pos_shares, 2) if live_price > 0 and pos_entry_price > 0 else 0
            pnl_pct = round(((live_price - pos_entry_price) / pos_entry_price) * 100, 2) if pos_entry_price > 0 else 0
            from datetime import date as _date
            try:
                # Weekday-count to match the trading-day exit target (was calendar
                # days, which ran the days-remaining counter ~40% fast) (2026-06-19).
                _ed = _date.fromisoformat(pos_entry_date) if pos_entry_date else _date.today()
                days_held = sum(
                    1 for n in range((_date.today() - _ed).days)
                    if (_ed + timedelta(days=n + 1)).weekday() < 5
                )
            except Exception:
                days_held = 0

            held_position_info = {
                "is_held": True,
                "entry_price": pos_entry_price,
                "entry_date": pos_entry_date,
                "shares": pos_shares,
                "cost_basis": round(pos_entry_price * pos_shares, 2),
                "current_value": round(live_price * pos_shares, 2) if live_price > 0 else 0,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "days_held": days_held,
                "strategy": pos_strategy,
            }

            df_hist = _cache.get(ticker, 365)
            if df_hist is not None and len(df_hist) >= 50:
                closes_list = df_hist["Close"].dropna().tolist()
                bt_data = _backtest_mr(ticker)
                best_exit = _select_best_exit(ticker, closes_list, bt_data.get("trades", 0) if bt_data else 0, rsi2, strategy=pos_strategy)
                if best_exit:
                    triggered = _evaluate_exit_trigger(
                        best_exit, closes_list, rsi2, live_price,
                        entry_price=pos_entry_price, entry_date=pos_entry_date,
                    )
                    exit_strategy_info = {
                        "exit_strategy": best_exit.get("strategy", ""),
                        "exit_strategy_wr": best_exit.get("wr", 0),
                        "exit_strategy_ret": best_exit.get("avg_ret", 0),
                        "exit_strategy_hold": best_exit.get("avg_hold", 60),
                        "exit_triggered": triggered.get("triggered", False),
                        "exit_price": triggered.get("exit_price", 0),
                        "exit_label": triggered.get("label", ""),
                        "entry_price": pos_entry_price,
                        "shares": pos_shares,
                    }
                    held_position_info["exit_triggered"] = triggered.get("triggered", False)
                    held_position_info["exit_label"] = triggered.get("label", "")
                    _tgt = 90 if pos_strategy == "MOMENTUM" else 60  # Fixed90d for MOM, Fixed60d else
                    held_position_info["target_hold_days"] = _tgt
                    held_position_info["days_remaining"] = max(0, _tgt - days_held)
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

    # Determine action — HELD positions use exit strategy logic, not entry analysis
    if held_position_info:
        # HELD: only valid exits are exit_triggered, earnings, stock-specific negative sentiment
        if exit_strategy_info.get("exit_triggered", False):
            exit_strat_ret = exit_strategy_info.get("exit_strategy_ret", 0)
            zone_ret = tech.get("zone_return", 0)
            zone_trades = tech.get("zone_trades", 0)
            if rsi2 < 10 and zone_trades >= 5 and zone_ret > exit_strat_ret:
                signal = "HOLD"
                issues.append(f"Exit suppressed: RSI oversold ({rsi2:.0f}), zone +{zone_ret:.1f}% > exit +{exit_strat_ret:.1f}%")
            else:
                signal = "EXIT"
        elif catalyst_warning:
            # Biotech catalyst overrides everything else for HELD positions —
            # this is the same severity as earnings ahead. CELC -24.6% on
            # 2026-06-02 happened because we held through this exact scenario.
            signal = "EXIT"
            issues.insert(0, f"EXIT: Biotech catalyst ({catalyst_warning['catalyst_type']}) — {catalyst_warning['title'][:60]}")
        elif earnings_date:
            signal = "EXIT"
            issues.insert(0, f"EXIT: Earnings on {earnings_date} — binary event risk")
        else:
            signal = "HOLD"
            # Clear misleading issues for held positions (current RSI zone WR is irrelevant)
            issues = [i for i in issues if "Low WR" not in i and "Weak zone" not in i]
    else:
        # NEW entry analysis
        has_critical = any(k in str(issues) for k in ["Below SMA50", "BEAR", "Low WR"])
        if has_critical and not above_sma50 and regime == "BEAR":
            signal = "AVOID"
        elif has_critical:
            signal = "CAUTION"
        elif catalyst_warning:
            # Same VETO for new entries — block any buy when a biotech catalyst
            # is scheduled within the next 14 days. Mirrors earnings VETO logic.
            signal = "WAIT"
            issues.insert(0, f"WAIT: Biotech catalyst ahead ({catalyst_warning['catalyst_type']})")
        elif earnings_date:
            signal = "WAIT"
        elif sentiment_label == "NEGATIVE":
            signal = "WAIT"
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

    # Score = Bayesian-shrunk EV via unified _ev_score. Prefer exit_zone data
    # (more trades, includes all bars in zone, not just RSI<10 entries).
    # Fall back to entry-zone, then overall stats.
    if exit_zt >= 5 and exit_zwr > 0:
        score = _ev_score(exit_zr, exit_zwr, exit_zt)
    elif tech.get("zone_trades", 0) >= 5 and tech.get("zone_wr", 0) > 0:
        score = _ev_score(tech.get("zone_return", 0), tech.get("zone_wr", 0), tech.get("zone_trades", 0))
    else:
        score = _ev_score(avg_ret, wr, tech.get("total_trades", 0))

    # 8. Optimal entry prices — backtest zone returns at RSI 0-5, 5-10, 10-20
    optimal_entries = _calc_optimal_entries(ticker, live_price)

    # 9. Proposed strategy — always compute for any stock (not just held)
    proposed_strategy = None
    if not exit_strategy_info:
        # Not a held position — compute proposed exit strategy anyway
        try:
            df_hist = _cache.get(ticker, 365)
            if df_hist is not None and len(df_hist) >= 50:
                closes_list = df_hist["Close"].dropna().tolist()
                opens_list = df_hist["Open"].dropna().tolist() if "Open" in df_hist.columns else None
                best_exit = _select_best_exit(ticker, closes_list, None, rsi2, opens=opens_list)
                if best_exit:
                    proposed_strategy = {
                        "exit_strategy": best_exit.get("strategy", "Fixed60d"),
                        "exit_strategy_wr": round(best_exit.get("wr", 0), 1),
                        "exit_strategy_ret": round(best_exit.get("avg_ret", 0), 2),
                        "exit_strategy_hold": best_exit.get("avg_hold", 60),
                        "validation": best_exit.get("validation", ""),
                    }
        except Exception as e:
            print(f"[Analyze] Proposed strategy error for {ticker}: {e}")
    else:
        proposed_strategy = {
            "exit_strategy": exit_strategy_info.get("exit_strategy", ""),
            "exit_strategy_wr": round(exit_strategy_info.get("exit_strategy_wr", 0), 1),
            "exit_strategy_ret": round(exit_strategy_info.get("exit_strategy_ret", 0), 2),
            "exit_strategy_hold": exit_strategy_info.get("exit_strategy_hold", 60),
            "validation": "HELD_POSITION",
        }

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
        "catalyst_warning": catalyst_warning,
        "signal": signal,
        "issues": issues,
        "stop_loss": stop_loss,
        "target_1": target_1,
        "target_2": target_2,
        "sparkline": tech.get("sparkline", []),
        "optimal_entries": optimal_entries,
        "former_holding": former_holding_info if former_holding_info else None,
        "proposed_strategy": proposed_strategy,
        "held_position": held_position_info,
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
                "score": _ev_score(p.get("avg_return", 0), p.get("win_rate", 0), p.get("total_trades", 0)),
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
    last_updated = ""
    try:
        row = _cache.conn.execute(
            "SELECT MAX(last_updated) FROM cache_meta"
        ).fetchone()
        last_updated = (row[0] or "") if row else ""
    except Exception:
        pass
    return CacheStats(
        total_tickers=stats.get("total_tickers", 0),
        total_rows=stats.get("total_rows", 0),
        last_updated=last_updated,
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
    await asyncio.sleep(300)  # Wait 5 min before first health check — let server stabilize first
    while True:
        try:
            # Reload dedup state (resets daily)
            _dedup = _load_dedup()

            print(f"\n[Monitor] Running health check at {datetime.now().strftime('%H:%M')}")
            try:
                health = await asyncio.wait_for(_run_health_check(), timeout=120)
            except (asyncio.TimeoutError, Exception) as _hc_err:
                print(f"[Monitor] Health check failed/timeout: {_hc_err}")
                health = {}

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
    """Centralized quote refresher via Tiingo IEX batch API.
    ONE request for ALL tickers every 30s. Replaces per-ticker Finnhub calls.
    Tiingo IEX: real-time prices, batch endpoint, 10K req/hr."""
    await asyncio.sleep(3)
    _tiingo_key = os.environ.get("TIINGO_API_KEY", "6f632a60d6188ebc1b92221e83d4fba37e2a5c42")
    print("[QuoteRefresh] Started — Tiingo IEX batch every 30s")

    while True:
        try:
            positions = _position_mgr._get_open_positions_sync()
            if not positions:
                await asyncio.sleep(30)
                continue

            tickers = [p["ticker"] for p in positions]
            # Also fetch live quotes for top scan candidates (entries tab)
            try:
                from strategy_evaluator import load_cache as _load_eval
                _eval = _load_eval()
                if _eval:
                    _top = sorted([e for e in _eval if not e.get("vetoed")],
                                  key=lambda x: x.get("score", 0), reverse=True)[:30]
                    for e in _top:
                        t = e.get("ticker", "")
                        if t and t not in tickers:
                            tickers.append(t)
            except Exception:
                pass
            tickers_str = ",".join(tickers)

            async with aiohttp.ClientSession() as session:
                # Single batch request for ALL holdings
                url = f"https://api.tiingo.com/iex/?tickers={tickers_str}"
                headers = {"Authorization": f"Token {_tiingo_key}", "Content-Type": "application/json"}
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        updated = {}
                        for d in data:
                            ticker = d.get("ticker", "").upper()
                            # Prefer the real intraday price (tngoLast); never fall back
                            # to prevClose as a "live" price — with ts=today that stamps
                            # yesterday's close as today's quote and manufactures phantom
                            # oversold (RSI2=0) signals. Mirrors _fetch_tiingo_iex_batch
                            # (2026-06-19 fix — this path had re-introduced the bug).
                            last = d.get("tngoLast") or d.get("last") or 0
                            prev = d.get("prevClose") or 0
                            if last and last > 0:
                                result = {
                                    "price": round(float(last), 2),
                                    "prev_close": round(float(prev), 2),
                                    "day_chg": round(((last - prev) / prev) * 100, 2) if prev > 0 else 0,
                                    "ts": datetime.now(),
                                }
                                _price_cache[ticker] = result
                                _quote_cache[ticker] = (result, datetime.now())
                                updated[ticker] = round(float(last), 2)

                        if updated:
                            print(f"[QuoteRefresh] Tiingo IEX batch: {updated} | {len(updated)} tickers in 1 request")
                    else:
                        # Fallback: seed from SQLite if Tiingo fails
                        for pos in positions:
                            ticker = pos["ticker"]
                            if ticker not in _price_cache:
                                try:
                                    import sqlite3 as _sql3
                                    _cdb = _sql3.connect(os.path.join(os.path.dirname(__file__), "data", "stock_cache.db"))
                                    _rows = _cdb.execute("SELECT close FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 2", (ticker.upper(),)).fetchall()
                                    _cdb.close()
                                    if len(_rows) >= 2:
                                        close, prev = _rows[0][0], _rows[1][0]
                                        _price_cache[ticker] = {"price": close, "prev_close": prev, "day_chg": round(((close - prev) / prev) * 100, 2) if prev > 0 else 0}
                                except Exception:
                                    pass

        except Exception as e:
            print(f"[QuoteRefresh] Error: {e}")

        await asyncio.sleep(30)  # Tiingo IEX: 1 request per 30s = 120/hr (well under 10K limit)


async def extended_hours_refresh_loop():
    """Fetch pre-market/after-hours prices via CNBC quote API.
    CNBC provides real-time extended hours prices for ALL stocks (including small caps).
    Free, no auth, JSON response with ExtendedMktQuote field.
    Tested: returns accurate PM prices matching Google Finance."""
    await asyncio.sleep(30)
    print("[ExtHoursRefresh] Started (Nasdaq API)")

    _first_run = True
    while True:
        try:
            session = _get_market_session()
            if session == "REGULAR" and not _first_run:
                # During market hours, clear ext cache — regular prices are live via Finnhub
                if _extended_hours_cache:
                    _extended_hours_cache.clear()
                await asyncio.sleep(120)
                continue
            if session == "CLOSED" and not _first_run:
                # Keep last known ext prices visible, refresh every 5 min to catch late AH prints
                if not _extended_hours_cache:
                    # No ext prices cached yet — do a fetch
                    pass
                else:
                    await asyncio.sleep(300)
                    continue
            # First run: always fetch once so we have prices after deploy/restart
            # PRE_MARKET / AFTER_HOURS: keep refreshing every 60s

            positions = _position_mgr._get_open_positions_sync()
            if not positions:
                await asyncio.sleep(120)
                continue

            tickers = [p["ticker"] for p in positions]
            updated = 0

            # Nasdaq API: real PM/AH prices for ALL stocks including small caps
            # Primary source — covers stocks that CNBC misses (AMR, APEI, etc.)
            _nasdaq_headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain"}
            async with aiohttp.ClientSession() as ext_session:
                for t in tickers:
                    try:
                        url = f"https://api.nasdaq.com/api/quote/{t}/info?assetclass=stocks"
                        async with ext_session.get(url, headers=_nasdaq_headers,
                                                   timeout=aiohttp.ClientTimeout(total=6)) as resp:
                            if resp.status != 200:
                                continue
                            data = await resp.json(content_type=None)
                            d = data.get("data", {})
                            if not d:
                                continue

                            primary = d.get("primaryData", {})
                            secondary = d.get("secondaryData", {})
                            mkt_status = d.get("marketStatus", "")

                            # primaryData.lastSalePrice = PM/AH price (e.g. "$59.30")
                            # secondaryData.lastSalePrice = regular close (e.g. "$57.19")
                            ext_str = primary.get("lastSalePrice", "")
                            close_str = secondary.get("lastSalePrice", "")

                            # Strip $ and parse
                            ext_price = float(ext_str.replace("$", "").replace(",", "")) if ext_str else 0
                            reg_close = float(close_str.replace("$", "").replace(",", "")) if close_str else 0

                            if ext_price <= 0 or reg_close <= 0:
                                continue

                            ext_change = round(((ext_price - reg_close) / reg_close) * 100, 2)
                            _extended_hours_cache[t] = {
                                "ext_price": round(ext_price, 2),
                                "ext_change_pct": ext_change,
                                "session": session,
                                "ts": datetime.now(),
                            }
                            _price_cache[t] = {
                                "price": round(ext_price, 2),
                                "prev_close": reg_close,
                                "day_chg": ext_change,
                                "ts": datetime.now(),
                            }
                            updated += 1
                    except Exception:
                        pass
                    await asyncio.sleep(0.5)

            if updated:
                prices = {t: f"${r['ext_price']:.2f} ({r['ext_change_pct']:+.2f}%)" for t, r in _extended_hours_cache.items()}
                print(f"[ExtHoursRefresh] {session}: {updated}/{len(tickers)} updated: {prices}")
            if _first_run:
                print(f"[ExtHoursRefresh] Initial fetch done ({session}): {updated} prices cached")
                _first_run = False

        except Exception as e:
            print(f"[ExtHoursRefresh] Error: {e}")

        # During active ext hours: refresh every 60s. Otherwise: sleep longer.
        await asyncio.sleep(60 if session in ("PRE_MARKET", "AFTER_HOURS") else 300)


async def cache_refresh_loop():
    """Daily historical data refresh. Holdings first (fast), then scanner universe later.
    Keeps stock_cache.db up to date so scanner/backtest use fresh data."""
    global _scan_cache, _scan_running
    await asyncio.sleep(30)  # Wait for uvicorn to be fully ready before heavy I/O

    first_run = True
    while True:
        try:
            positions = _position_mgr._get_open_positions_sync()
            holding_tickers = [p["ticker"] for p in positions] if positions else []

            # VIX fetcher — defined outside `first_run` so subsequent loops can re-fetch
            # (Tiingo doesn't carry ^VIX; Yahoo's chart endpoint is the working source on Fly.io)
            def _fetch_vix():
                import requests as _req
                try:
                    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=60d&interval=1d"
                    r = _req.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                    if r.status_code == 200:
                        chart = r.json().get("chart", {}).get("result", [{}])[0]
                        ts = chart.get("timestamp", [])
                        q = chart.get("indicators", {}).get("quote", [{}])[0]
                        if ts and q.get("close") and len(ts) >= 5:
                            from datetime import datetime as _dt
                            dates = [_dt.utcfromtimestamp(t).strftime('%Y-%m-%d') for t in ts]
                            df = pd.DataFrame({"Date": dates, "Open": q["open"], "High": q["high"],
                                               "Low": q["low"], "Close": q["close"], "Volume": q.get("volume", [0]*len(ts))})
                            df["Date"] = pd.to_datetime(df["Date"])
                            df = df.set_index("Date").sort_index().dropna(subset=["Close"])
                            if len(df) >= 5:
                                _cache.store("VIX", df)
                                return len(df)
                except Exception:
                    pass
                return 0

            # SPY (Tiingo) + VIX (Yahoo) — refresh whenever stale, not just on first_run.
            # Previously VIX was inside `if first_run:` and could stay stale for days if the
            # boot-time Yahoo call failed (observed: VIX cache 12 days behind regime calc).
            if not _cache.is_fresh("SPY"):
                try:
                    async with aiohttp.ClientSession() as _sess:
                        _spy_df = await _cache._fetch_tiingo(_sess, "SPY", days=400)
                        if _spy_df is not None:
                            _cache.store("SPY", _spy_df)
                            print(f"[CacheRefresh] SPY: {len(_spy_df)} bars via Tiingo")
                except Exception as _e:
                    print(f"[CacheRefresh] SPY fetch failed: {_e}")

            if not _cache.is_fresh("VIX"):
                try:
                    n = await asyncio.wait_for(asyncio.to_thread(_fetch_vix), timeout=15)
                    if n: print(f"[CacheRefresh] VIX: {n} bars via Yahoo")
                except (asyncio.TimeoutError, Exception) as _e:
                    print(f"[CacheRefresh] VIX fetch failed: {_e}")

            if first_run:

                # FIRST RUN: Populate holdings with NO data, refresh stale ones
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

                # DAILY PRICE UPDATE: Tiingo only (20 concurrent, 10-day window)
                _system_status.update({"stage": "updating_prices", "message": "Refreshing stale stock prices...", "progress": 0})
                stale_tickers = _cache.get_stale_tickers()
                print(f"[CacheRefresh] {len(stale_tickers)} stale tickers to refresh")

                try:
                    if stale_tickers:
                        _result = await asyncio.wait_for(_cache.refresh(stale_tickers), timeout=900)
                        _upd = _result.get("refreshed", 0)
                        _fail = _result.get("failed", 0)
                        print(f"[CacheRefresh] Daily prices updated: {_upd} stocks, {_fail} failed")
                    else:
                        _upd = 0
                        print(f"[CacheRefresh] All stocks already fresh")

                    # Pre-compute + evaluator run in subprocess so they can't block the event loop
                    _system_status.update({"stage": "precomputing", "message": "Pre-computing backtests + evaluating (subprocess)...", "progress": 70})
                    _held = set(p["ticker"] for p in positions) if positions else set()
                    _live_px = _fresh_live_px()
                    _valid = await _run_precompute_and_eval_subproc(_held, _live_px, label="CacheRefresh")
                    print(f"[CacheRefresh] Evaluator: {_valid} valid entries (subprocess)")
                    _system_status.update({"stage": "ready", "message": f"{_valid} entries ready", "progress": 100})
                except (asyncio.TimeoutError, Exception) as _e:
                    import traceback; traceback.print_exc()
                    print(f"[CacheRefresh] Daily update error: {_e}")
                    _system_status.update({"stage": "error", "message": str(_e), "progress": 0})

                await asyncio.sleep(60)

                # POPULATE FULL UNIVERSE: Check how many are missing from cache
                from deep_scanner import STOCK_UNIVERSE
                cached_set = set(_cache.get_cached_tickers())
                uncached = [t for t in STOCK_UNIVERSE if t not in cached_set]
                if uncached and len(uncached) > 30:
                    # Only populate if many stocks missing (fresh install). Skip if <30 — those are unfetchable tickers
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
            if uncached and len(uncached) > 30:
                print(f"[CacheRefresh] {len(uncached)} new universe stocks to populate...")
                batch_size = 100
                for i in range(0, len(uncached), batch_size):
                    batch = uncached[i:i + batch_size]
                    await _cache.populate(batch)
                    await asyncio.sleep(5)

            # V3.3.1 (2026-06-03): backtest_cache freshness check moved OUT of
            # the "all bars fresh" branch. Previously stale tickers would block
            # this check forever (16-day cache staleness observed in production).
            # Now: if backtest_cache is >24h old, ALWAYS run precompute, even
            # if some bars are still stale — better stale-but-recent than nothing.
            try:
                import sqlite3 as _sql3
                _bt_db_check = os.path.join(os.path.dirname(__file__), "data", "stock_cache.db")
                _bt_c = _sql3.connect(_bt_db_check)
                _row = _bt_c.execute("SELECT MAX(last_computed) FROM backtest_cache").fetchone()
                _bt_c.close()
                if _row and _row[0]:
                    _age_h_global = (datetime.now() - datetime.fromisoformat(_row[0] + "T00:00:00")).total_seconds() / 3600
                    if _age_h_global > 24:
                        print(f"[CacheRefresh] backtest_cache is {_age_h_global:.1f}h old — forcing precompute")
                        _held = set(p["ticker"] for p in positions) if positions else set()
                        _live_px = _fresh_live_px()
                        _valid = await _run_precompute_and_eval_subproc(_held, _live_px, label="StalenessGuard")
                        print(f"[CacheRefresh] Staleness-guard precompute: {_valid} valid entries")
            except Exception as _stale_err:
                print(f"[CacheRefresh] Staleness guard error: {_stale_err}")

            if not stale and not uncached:
                # All bars are fresh — but the backtest_cache (WR / zone_return
                # source for entries-tab ranking) is a SEPARATE derived table
                # that needs its own staleness check. Discovered 2026-05-27:
                # cache stayed 9 days behind because this branch always took
                # the fast path. If backtest_cache is older than 24h, force a
                # precompute run against the existing (fresh) bars so rankings
                # stay current with whatever recent moves changed the WR.
                _bt_stale = False
                try:
                    import sqlite3 as _sql3
                    _bt_db = os.path.join(os.path.dirname(__file__), "data", "stock_cache.db")
                    _bt_c = _sql3.connect(_bt_db)
                    _row = _bt_c.execute("SELECT MAX(last_computed) FROM backtest_cache").fetchone()
                    _bt_c.close()
                    if _row and _row[0]:
                        _age_h = (datetime.now() - datetime.fromisoformat(_row[0] + "T00:00:00")).total_seconds() / 3600
                        _bt_stale = _age_h > 24
                except Exception:
                    pass

                if _bt_stale:
                    print(f"[CacheRefresh] Bars fresh but backtest_cache stale — re-running precompute")
                    try:
                        _held = set(p["ticker"] for p in positions) if positions else set()
                        _live_px = _fresh_live_px()
                        _valid = await _run_precompute_and_eval_subproc(_held, _live_px, label="BacktestRefresh")
                        print(f"[CacheRefresh] Backtest precompute: {_valid} valid entries")
                    except Exception as _bt_err:
                        print(f"[CacheRefresh] Backtest precompute error: {_bt_err}")
                else:
                    print(f"[CacheRefresh] All {len(cached_set)} tickers up to date, backtest cache fresh")
                await asyncio.sleep(14400)  # 4 hours
                continue

            if stale:
                print(f"[CacheRefresh] {len(stale)} stale tickers, refreshing...")

                priority = [t for t in holding_tickers if t in stale]
                rest = [t for t in stale if t not in priority]
                ordered = priority + rest

                try:
                    # Bound the refresh (was unbounded — could run for many minutes if
                    # the whole universe is flagged stale). Holdings are refreshed first
                    # so they always complete even if the tail times out. (2026-06-19)
                    result = await asyncio.wait_for(_cache.refresh(ordered), timeout=900)
                    print(f"[CacheRefresh] Done: {result.get('refreshed', 0)} refreshed, "
                          f"{result.get('failed', 0)} failed")
                except asyncio.TimeoutError:
                    print(f"[CacheRefresh] Refresh timed out (>900s) over {len(ordered)} stale tickers")

            # Invalidate signal + exit strategy caches so next request uses fresh data
            _signal_cache.clear()
            _exit_strategy_cache.clear()

            # Decide whether to re-run the heavy precompute + scan. During market
            # hours the daily Tiingo bar isn't complete (today's row is partial
            # or missing — we already saw 0/52 succeed at noon ET) so re-running
            # precompute against the same data wastes CPU and triggers timeout
            # cycles (~10min subprocess on shared-1x Fly). Only run heavy work
            # when daily-bar refresh actually fetched new rows OR we're past the
            # post-close window where Tiingo has the day's final close.
            from datetime import datetime as _dt2
            _et_now = _now_et()
            _et_hour = _et_now.hour
            _is_after_close = _et_hour >= 16 or _et_hour < 4  # 16 ET–04 ET next day
            _refresh_made_progress = (result.get("refreshed", 0) > 0) if 'result' in dir() else False
            _should_run_heavy = _is_after_close or _refresh_made_progress

            if _should_run_heavy:
                try:
                    print(f"[CacheRefresh] Re-computing backtests + evaluating (subprocess)...")
                    _held = set(p["ticker"] for p in positions) if positions else set()
                    _live_px = _fresh_live_px()
                    _valid = await _run_precompute_and_eval_subproc(_held, _live_px, label="CacheRefresh")
                    print(f"[CacheRefresh] Evaluator: {_valid} valid entries")
                    _system_status.update({"stage": "ready", "message": f"{_valid} entries ready", "progress": 100})

                    # Trigger full deep scan only if we have fresh data AND the
                    # last scan is older than 4 hours (avoid back-to-back scans).
                    _scan_age_min = (
                        (_dt2.now() - _scan_cache_time).total_seconds() / 60
                        if _scan_cache_time else 9999
                    )
                    if not _scan_running and _scan_age_min > 240:
                        _scan_cache = None
                        _scan_running = True
                        asyncio.create_task(_background_scan())
                        print(f"[CacheRefresh] Full scan triggered (last scan {_scan_age_min:.0f}min ago)")
                    else:
                        print(f"[CacheRefresh] Skipping scan (running={_scan_running}, age={_scan_age_min:.0f}min)")
                except Exception as _precomp_err:
                    print(f"[CacheRefresh] Precompute/eval error: {_precomp_err}")
            else:
                print(f"[CacheRefresh] Skipping heavy work (market hours, no new daily bars). "
                      f"Live IEX overlay handles intraday prices.")

        except Exception as e:
            import traceback
            print(f"[CacheRefresh] Error: {e}")
            traceback.print_exc()

        # Sleep until next refresh window
        # Cadence:
        #   Pre-market 4-9 ET:    skip (Tiingo doesn't have intraday for most until open)
        #   Market hours 9-16 ET: every 60 min (keeps entries tab live during trading)
        #   Post-close 16-18 ET:  1h wait then refresh (Tiingo finalizes)
        #   Overnight 18-4 ET:    long sleep until 5pm ET next day
        # Target: refresh at ~5pm ET daily for final close + hourly during the
        # trading day so the user doesn't see yesterday's data midday.
        _now = _now_et()
        _hour = _now.hour
        _wday = _now.weekday()  # 0=Mon, 6=Sun
        if _wday >= 5:
            # Weekend — sleep until Monday 9 ET
            _days_to_mon = (7 - _wday) % 7 or 1
            _sleep = max(3600, _days_to_mon * 24 * 3600 - _hour * 3600)
        elif 16 <= _hour < 18:
            # Just after close — wait 1h for Tiingo to finalize daily bars
            _sleep = 3600
        elif _hour >= 18 or _hour < 4:
            # Evening/overnight — next check at 5pm ET (or next morning)
            _hours_until_5pm = (17 - _hour) % 24
            _sleep = max(3600, _hours_until_5pm * 3600)
        elif 4 <= _hour < 9:
            # Pre-market — wait until 9 ET when intraday data starts flowing
            _sleep = max(900, (9 - _hour) * 3600)
        else:
            # Market hours (9-16 ET) — refresh every 60 min so the entries tab
            # uses today's live prices, not yesterday's close. Tiingo refresh of
            # ~3K stale tickers + precompute is well within the 10K/hr quota.
            _sleep = 3600
        print(f"[CacheRefresh] Next refresh in {_sleep//60}min (ET {_hour}:00 {'wkd' if _wday<5 else 'wknd'})")
        await asyncio.sleep(_sleep)


async def signal_tracker_loop():
    """Daily snapshot of top-20 Entries-tab picks + backfill stale forward returns.

    Runs every 4 hours. Real work only fires after market close (>= 16:30 ET) so
    today's entries snapshot is finalized. Idempotent — re-snapshot just overwrites
    today's row; backfill skips rows that already have returns.

    Persists to backend/data/signal_tracker.db (queryable, survives deploys via mount).
    """
    await asyncio.sleep(180)  # let other loops boot first

    while True:
        try:
            _et = _now_et()
            _et_hour = _et.hour
            _wday = _et.weekday()

            # Only do real work after market close on weekdays
            if _wday < 5 and _et_hour >= 17:
                import signal_tracker_update as _stu
                try:
                    inserted = await asyncio.to_thread(_stu.snapshot_today)
                    print(f"[SignalTracker] Snapshot: {inserted} top-{_stu.TOP_N} picks captured for today")
                except Exception as _e:
                    print(f"[SignalTracker] Snapshot error: {_e}")
                try:
                    updated = await asyncio.to_thread(_stu.backfill_returns)
                    print(f"[SignalTracker] Backfilled forward returns on {updated} rows")
                except Exception as _e:
                    print(f"[SignalTracker] Backfill error: {_e}")
            else:
                print(f"[SignalTracker] ET {_et_hour}:00 — outside snapshot window, skipping")
        except Exception as e:
            import traceback
            print(f"[SignalTracker] Error: {e}")
            traceback.print_exc()

        # Every 4 hours — catches the post-close window without thrashing
        await asyncio.sleep(4 * 3600)
