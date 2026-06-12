"""
Strategy Evaluator — Fast entry signal detection against cached prices.
=======================================================================
Runs BOTH mean reversion + momentum strategies on all cached stocks.
No API calls, no network — pure CPU against SQLite cache.

Architecture (V2 — backtest_cache accelerated):
  1. Load pre-computed backtest stats from backtest_cache table (instant)
  2. For each stock, check CURRENT RSI < 10 / momentum conditions (from last few bars)
  3. Look up pre-computed WR/return from backtest_cache (no inline backtest!)
  4. Apply VETO filters (WR < 55%, return < 3%, trades < 5)
  5. Return sorted signals

Speed target: < 5 seconds for 3000 stocks (was 10+ minutes with inline backtests).
"""

import sqlite3
import os
import json
import time
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stock_cache.db")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


@dataclass
class EntrySignal:
    ticker: str
    price: float
    strategy: str       # "MEAN_REVERSION", "MOMENTUM", "BOTH"
    strategy_label: str  # "RSI Dip", "Breakout", "RSI Dip + Breakout"
    # Unified score: expected_value = WR × avg_return (higher = better)
    score: float
    expected_return: float  # Backtest avg return for this signal type
    confidence: float       # Bayesian WR (0-100)
    trades: int             # Number of backtest trades backing this signal
    # Signal details
    rsi2: float = 0
    sma50_buffer: float = 0
    atr_pct: float = 0
    volume_ratio: float = 0
    ret_20d: float = 0
    ret_60d: float = 0
    pct_from_high: float = 0
    atr_squeeze: float = 0
    trend_score: int = 0
    # Validation (filled later for top candidates)
    analyst_consensus: str = ""
    sentiment_label: str = ""
    vetoed: bool = False
    veto_reason: str = ""
    # Meta
    data_date: str = ""     # When the price data is from


def _rsi2_arr(closes):
    n = len(closes)
    rsi = [50.0] * n
    for i in range(2, n):
        c1 = closes[i] - closes[i-1]; c2 = closes[i-1] - closes[i-2]
        ag = (max(0, c1) + max(0, c2)) / 2; al = (max(0, -c1) + max(0, -c2)) / 2
        rsi[i] = (100.0 - 100.0 / (1 + ag / al)) if al > 0 else (100.0 if ag > 0 else 50.0)
    return rsi


def _sma_arr(closes, period):
    n = len(closes); sma = [0.0] * n
    if n < period: return sma
    run = sum(closes[:period]); sma[period-1] = run / period
    for i in range(period, n): run += closes[i] - closes[i-period]; sma[i] = run / period
    return sma


# Universe prior for Bayesian WR
_UNIVERSE_WR = 53.5
_PRIOR_WEIGHT = 10
# Universe prior for Bayesian return (ret prior pulled to weighted-avg of MR+momentum
# returns across 26K trades; phantom weight is heavy because return variance is huge).
_UNIVERSE_RET = 2.85
_RET_PRIOR_WEIGHT = 20


def _bayesian_wr(wins, total):
    pw = _UNIVERSE_WR / 100 * _PRIOR_WEIGHT
    return (wins + pw) / (total + _PRIOR_WEIGHT) * 100


def _bayesian_ret(ret, trades):
    """Shrink observed return toward universe prior. Required by api_v2._ev_score."""
    return (ret * trades + _UNIVERSE_RET * _RET_PRIOR_WEIGHT) / (trades + _RET_PRIOR_WEIGHT)


# Momentum ret_20d zones
_MOM_ZONES = [(5, 10), (10, 20), (20, 30), (30, 999)]
_MOM_ZONE_LABELS = ["5-10%", "10-20%", "20-30%", "30%+"]
_MOM_HOLD_DAYS = 90  # Best exit from exit study: Fixed90d


def _backtest_momentum(closes, opens, highs, lows, sma50, sma150, sma200, n):
    """Backtest Minervini 6/6 momentum entries with Fixed90d exit.
    Returns: (trades, bayesian_wr, avg_return, zone_label, zone_wr, zone_ret, zone_trades)"""
    if n < 350:  # Need 252 lookback + 90 forward + buffer
        return 0, 50.0, 0.0, {}

    trades = []
    zone_trades = {zl: [] for zl in _MOM_ZONE_LABELS}
    last_exit = -1

    for i in range(252, n - _MOM_HOLD_DAYS - 2):
        if i <= last_exit:
            continue

        # Minervini 6/6
        if sma50[i] <= 0 or sma150[i] <= 0 or sma200[i] <= 0:
            continue
        if not (closes[i] > sma50[i] and closes[i] > sma150[i] and closes[i] > sma200[i]):
            continue
        if not (sma50[i] > sma150[i] > sma200[i]):
            continue

        high_52w = max(highs[max(0, i-252):i+1])
        low_52w = min(lows[max(0, i-252):i+1])
        if high_52w <= 0 or low_52w <= 0:
            continue
        if ((closes[i] / high_52w) - 1) * 100 < -25:
            continue
        if ((closes[i] / low_52w) - 1) * 100 < 30:
            continue

        if i < 20:
            continue
        ret_20d = ((closes[i] / closes[i - 20]) - 1) * 100
        if ret_20d < 5:
            continue

        # Entry at next-day open
        ep = opens[i + 1] if opens[i + 1] > 0 else closes[i]
        if ep < 10:
            continue

        # Fixed60d exit
        exit_idx = min(i + 1 + _MOM_HOLD_DAYS, n - 1)
        ret = ((closes[exit_idx] - ep) / ep) * 100 - 0.30
        trades.append(ret)
        last_exit = exit_idx

        # Zone
        for (zlo, zhi), zl in zip(_MOM_ZONES, _MOM_ZONE_LABELS):
            if zlo <= ret_20d < zhi:
                zone_trades[zl].append(ret)
                break

    if not trades:
        return 0, 50.0, 0.0, {}

    total = len(trades)
    wins = sum(1 for r in trades if r > 0)
    bwr = _bayesian_wr(wins, total)
    avg_ret = sum(trades) / total

    # Find current zone (last entry's zone, or use the zone with most trades)
    # We'll determine the current zone in the caller based on current ret_20d
    # Here just return per-zone data for the most relevant zone
    return total, bwr, avg_ret, zone_trades


def _get_mom_zone(ret_20d, zone_trades):
    """Get zone stats for current ret_20d."""
    for (zlo, zhi), zl in zip(_MOM_ZONES, _MOM_ZONE_LABELS):
        if zlo <= ret_20d < zhi:
            zt = zone_trades.get(zl, [])
            if len(zt) >= 3:
                zwr = sum(1 for r in zt if r > 0) / len(zt) * 100
                zret = sum(zt) / len(zt)
                return zl, zwr, zret, len(zt)
            return zl, 0.0, 0.0, len(zt)
    return "", 0.0, 0.0, 0


def evaluate_all(min_price: float = 10.0, held_tickers: set = None, live_prices: dict = None) -> List[EntrySignal]:
    """Evaluate all stocks in cache for MR + Momentum signals. No API calls.
    live_prices: dict of {ticker: price} from Finnhub — appended to historical data for today's RSI.
    RULE: Never show entries on stale data. If cache is >1 trading day old, flag it."""
    t0 = time.time()
    held = held_tickers or set()
    _live = live_prices or {}

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Get all tickers with enough data
    c.execute("SELECT ticker, MAX(date) as last_date, COUNT(*) as cnt FROM daily_prices GROUP BY ticker HAVING cnt >= 80")
    ticker_info = {r[0]: {"last_date": r[1], "cnt": r[2]} for r in c.fetchall()}

    signals = []
    mr_count = 0
    mom_count = 0

    for ticker, info in ticker_info.items():
        if ticker in held:
            continue

        # Load ONLY last 260 bars (enough for SMA200 + momentum checks)
        # NOT all 2500 bars — that's what made the evaluator take 10+ min
        c.execute("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? ORDER BY date DESC LIMIT 260", (ticker,))
        rows = list(reversed(c.fetchall()))
        if len(rows) < 80:
            continue

        dates = [r[0] for r in rows]
        opens = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = [r[4] for r in rows]
        volumes = [r[5] for r in rows]
        n = len(closes)

        # Append today's live price if available (for intraday RSI detection).
        # Weekday check: on weekends a phantom Saturday bar would shift RSI(2).
        if ticker in _live and _live[ticker] > 0 and datetime.now().weekday() < 5:
            live_px = _live[ticker]
            today_str = datetime.now().strftime('%Y-%m-%d')
            if dates[-1] != today_str:  # Don't double-append
                closes = closes + [live_px]
                opens = opens + [live_px]
                highs = highs + [live_px]
                lows = lows + [live_px]
                volumes = volumes + [volumes[-1] if volumes else 0]
                dates = dates + [today_str]
                n = len(closes)

        price = closes[-1]
        if price < min_price:
            continue

        data_date = dates[-1]

        # Pre-compute arrays (O(n) each)
        rsi2 = _rsi2_arr(closes)
        sma50 = _sma_arr(closes, 50)
        sma150 = _sma_arr(closes, 150) if n >= 150 else [0.0] * n
        sma200 = _sma_arr(closes, 200) if n >= 200 else [0.0] * n

        current_rsi = rsi2[-1]
        current_sma50 = sma50[-1]

        # ATR(14)
        atr_vals = []
        for j in range(max(1, n-14), n):
            tr = max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
            atr_vals.append(tr)
        atr_pct = (sum(atr_vals)/len(atr_vals)/price*100) if atr_vals and price > 0 else 0

        # Volume ratio
        avg_vol = sum(volumes[-20:])/20 if len(volumes) >= 20 and any(v > 0 for v in volumes[-20:]) else 0
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 0

        # SMA50 buffer
        sma50_buffer = ((price - current_sma50) / current_sma50 * 100) if current_sma50 > 0 else 0

        # Returns
        ret_5d = ((closes[-1]/closes[-6])-1)*100 if n >= 6 else 0
        ret_20d = ((closes[-1]/closes[-21])-1)*100 if n >= 21 else 0
        ret_60d = ((closes[-1]/closes[-61])-1)*100 if n >= 61 else 0

        # 52-week high/low
        high_52w = max(highs[-min(252,n):])
        low_52w = min(lows[-min(252,n):])
        pct_from_high = ((price/high_52w)-1)*100 if high_52w > 0 else -100
        pct_from_low = ((price/low_52w)-1)*100 if low_52w > 0 else 0

        # ATR squeeze
        atr_50_vals = []
        for j in range(max(1, n-50), n):
            tr = max(highs[j]-lows[j], abs(highs[j]-closes[j-1]), abs(lows[j]-closes[j-1]))
            atr_50_vals.append(tr)
        atr_50_avg = sum(atr_50_vals)/len(atr_50_vals) if atr_50_vals else 1
        atr_squeeze = (sum(atr_vals)/len(atr_vals))/atr_50_avg if atr_50_avg > 0 and atr_vals else 1

        # ═══════════════════════════════════════════
        # MEAN REVERSION CHECK (V3.0 — cache-accelerated)
        # ═══════════════════════════════════════════
        cache_row = None  # Will be loaded from backtest_cache if needed
        # Same gates as deep_scanner: RSI(2)<10, uptrend (price > SMA50),
        # ATR>=3%, price>=$10. The SMA50 filter was missing here — below-SMA50
        # stocks were emitted as MR signals and only caught on one serve path.
        is_mr = (current_rsi < 10 and atr_pct >= 3 and price >= 10
                 and current_sma50 > 0 and price > current_sma50)

        mr_score = 0
        mr_wr = 0
        mr_ret = 0
        mr_trades = 0

        if is_mr:
            # Look up pre-computed backtest stats from backtest_cache (instant)
            cache_row = c.execute(
                "SELECT mr_wr, mr_avg_return, mr_trades, mr_score FROM backtest_cache WHERE ticker=?",
                (ticker,)
            ).fetchone()
            if cache_row and cache_row[2] >= 5:
                mr_wr = cache_row[0]
                mr_ret = cache_row[1]
                mr_trades = cache_row[2]
                mr_score = cache_row[3]

        # ═══════════════════════════════════════════
        # MOMENTUM CHECK (Minervini Trend Template)
        # ═══════════════════════════════════════════
        trend_rules = [
            price > current_sma50 if current_sma50 > 0 else False,
            price > sma150[-1] if sma150[-1] > 0 else False,
            price > sma200[-1] if sma200[-1] > 0 else False,
            (sma50[-1] > sma150[-1] > sma200[-1]) if sma50[-1] > 0 and sma150[-1] > 0 and sma200[-1] > 0 else False,
            pct_from_high > -25,
            pct_from_low > 30,
        ]
        trend_score = sum(trend_rules)
        # Backtested: ret>5% + no vol filter = 51.7% WR, +1.56% avg (14,827 trades)
        # vs strict ret>15% + vol>1.5x = 49.3% WR (worse) but +1.92% avg (fewer signals)
        # Documented momentum VETOs (match momentum_scanner):
        #   parabolic spike — prior-day move >= 10% (45.4% WR cohort, gap study)
        #   5d return > 15% — chasing an extended move
        #   price > $200 — research-backed cap (-5% edge above $200)
        ret_1d = ((closes[-1] / closes[-2]) - 1) * 100 if n >= 2 and closes[-2] > 0 else 0
        is_mom = (trend_score == 6 and ret_20d > 5
                  and abs(ret_1d) < 10 and ret_5d <= 15 and price <= 200)

        mom_score = 0
        mom_wr = 0
        mom_ret = 0
        mom_trades = 0
        mom_zone_label = ""
        mom_zone_wr = 0
        mom_zone_ret = 0

        if is_mom:
            # Look up pre-computed momentum stats from backtest_cache (instant)
            if not cache_row:
                cache_row = c.execute(
                    "SELECT mr_wr, mr_avg_return, mr_trades, mr_score, mom_wr, mom_avg_return, mom_trades, mom_score FROM backtest_cache WHERE ticker=?",
                    (ticker,)
                ).fetchone()
            mom_cache = c.execute(
                "SELECT mom_wr, mom_avg_return, mom_trades, mom_score FROM backtest_cache WHERE ticker=?",
                (ticker,)
            ).fetchone()
            if mom_cache and mom_cache[2] >= 5:
                mom_wr = mom_cache[0]
                mom_ret = mom_cache[1]
                mom_trades = mom_cache[2]
                mom_score = mom_cache[3]

        # ═══════════════════════════════════════════
        # DETERMINE BEST STRATEGY + COMBINED SCORE
        # ═══════════════════════════════════════════
        # V3.3.1 (2026-06-03): When stock qualifies for BOTH, only use a side
        # whose sample meets the CLAUDE.md minimum (MR≥10 OR MOM≥15). Previously
        # CDNA (MR=28 / MOM=9) → BOTH picked MOM score (+47.98% on 9 trades),
        # inflating EV to 31 and ranking #1. Now MOM<15 disqualifies the MOM
        # side from being chosen; fall back to MR side stats.
        mom_qualified = mom_trades >= 15
        mr_qualified = mr_trades >= 10
        if is_mr and is_mom and mr_trades >= 5 and mom_trades >= 5:
            strategy = "BOTH"
            label = "RSI Dip + Breakout"
            # Pick whichever QUALIFIED side has higher score. If only one
            # qualifies, use it. If neither qualifies, fall through (will be
            # vetoed below).
            if mr_qualified and mom_qualified:
                use_mom = mom_score >= mr_score
            elif mom_qualified:
                use_mom = True
            elif mr_qualified:
                use_mom = False
            else:
                # Neither side has adequate sample — use MR by default (will
                # fail the V3.3 BOTH veto downstream regardless).
                use_mom = False
            if use_mom:
                score = mom_score; exp_ret = mom_ret; conf = mom_wr; trades_n = mom_trades
            else:
                score = mr_score; exp_ret = mr_ret; conf = mr_wr; trades_n = mr_trades
            mr_count += 1; mom_count += 1
        elif is_mr and mr_trades >= 5:
            strategy = "MEAN_REVERSION"
            label = "RSI Dip"
            score = mr_score
            exp_ret = mr_ret
            conf = mr_wr
            trades_n = mr_trades
            mr_count += 1
        elif is_mom and mom_trades >= 3:
            strategy = "MOMENTUM"
            label = f"Breakout ({mom_zone_label})" if mom_zone_label else "Breakout"
            score = mom_score
            exp_ret = mom_ret
            conf = mom_wr
            trades_n = mom_trades
            mom_count += 1
        else:
            continue  # No signal or insufficient backtest data

        # ═══ V3.3 ENTRY VALIDATION GATES (2026-06-03) ═══
        # Mirrors /analyze deep-validation. End-to-end QA on 2026-06-03 found
        # 85% of top-20 entries (17/20) were CAUTION or HOLD on /analyze.
        # Root causes: tiny MOM samples (8-11 trades inflated EV), expired
        # signals (RSI bounced), and aggregate cache WR hiding zone failures.
        # These gates close the gap so /scan/combined ≈ /analyze BUY criteria.
        vetoed = False
        veto_reason = ""
        if trades_n < 5:
            vetoed = True; veto_reason = f"Too few trades ({trades_n} < 5 minimum)"
        elif strategy == "MEAN_REVERSION":
            # MR: CLAUDE.md MANDATORY rule — trust backtests only with 10+ trades.
            # 2026-06-03 deep QA on top-10 candidates showed RKLB (7 trades,
            # /analyze BUY, +17% 30d avg, -40% worst case) ranked above APP
            # (13 trades, /analyze BUY, +19% 30d avg, -26% worst case) only
            # because EV uses 60d-cache numbers that inflate small samples.
            # Strict 10-trade gate aligns with CLAUDE.md and demotes RKLB/GRAL/
            # FEIM (5-7 trades each) below APP/IMVT/STX (13-24 trades).
            if mr_trades < 10:
                vetoed = True; veto_reason = f"Too few MR trades ({mr_trades} < 10 CLAUDE.md min)"
            elif conf < 55:
                vetoed = True; veto_reason = f"MR WR {conf:.0f}% < 55%"
            elif mr_ret < 3:
                vetoed = True; veto_reason = f"MR return {mr_ret:.1f}% < 3%"
            # NEW: signal-expired gate — RSI(2) > 30 means the dip already bounced.
            # MR entries are about catching the deep dip, not chasing the recovery.
            elif current_rsi > 30:
                vetoed = True; veto_reason = f"MR signal expired (RSI(2)={current_rsi:.0f} > 30)"
        elif strategy == "MOMENTUM":
            # MOM minimum raised from 5 → 15 trades. With 90d hold, MOM signals
            # fire ~4×/year; 5 trades = ~1yr of data, way too small for stable
            # statistics. 15 trades ≈ 4-5 years of history — meaningful sample.
            # 2026-06-03 QA: CDNA (9 trades, 65% WR cache vs 41.7% /analyze),
            # ENPH (8 trades, 57.5% vs 25% /analyze), AMR (11 trades, similar).
            # All would top the EV-sorted list yet fail /analyze's deeper check.
            if mom_trades < 15:
                vetoed = True; veto_reason = f"Too few momentum trades ({mom_trades} < 15)"
            elif conf < 55:
                vetoed = True; veto_reason = f"Momentum WR {conf:.0f}% < 55%"
            elif mom_ret < 2:
                vetoed = True; veto_reason = f"Momentum return {mom_ret:.1f}% < 2%"
        elif strategy == "BOTH":
            # BOTH: pass if EITHER side meets CLAUDE.md sample minimum
            # (MR>=10 OR MOM>=15). FEIM with only 7+6 trades correctly fails.
            if mr_trades < 10 and mom_trades < 15:
                vetoed = True; veto_reason = f"BOTH insufficient sample (MR={mr_trades}, MOM={mom_trades})"
            elif conf < 55:
                vetoed = True; veto_reason = f"BOTH WR {conf:.0f}% < 55%"
            elif exp_ret < 3:
                vetoed = True; veto_reason = f"BOTH return {exp_ret:.1f}% < 3%"

        signals.append(EntrySignal(
            ticker=ticker, price=round(price, 2),
            strategy=strategy, strategy_label=label,
            score=round(score, 2), expected_return=round(exp_ret, 2),
            confidence=round(conf, 1), trades=trades_n,
            rsi2=round(current_rsi, 1), sma50_buffer=round(sma50_buffer, 1),
            atr_pct=round(atr_pct, 2), volume_ratio=round(vol_ratio, 2),
            ret_20d=round(ret_20d, 2), ret_60d=round(ret_60d, 2),
            pct_from_high=round(pct_from_high, 1), atr_squeeze=round(atr_squeeze, 2),
            trend_score=trend_score,
            vetoed=vetoed, veto_reason=veto_reason,
            data_date=data_date,
        ))

    conn.close()

    # Sort: non-vetoed first, then by score
    signals.sort(key=lambda x: (not x.vetoed, x.score), reverse=True)

    elapsed = time.time() - t0
    valid = sum(1 for s in signals if not s.vetoed)
    print(f"[Evaluator] {len(ticker_info)} stocks evaluated in {elapsed:.1f}s")
    print(f"  MR signals: {mr_count} | Momentum: {mom_count} | Valid: {valid} | Vetoed: {len(signals)-valid}")

    return signals


def save_cache(signals: List[EntrySignal]):
    """Save evaluated signals to disk."""
    path = os.path.join(CACHE_DIR, f"entries_{datetime.now().strftime('%Y-%m-%d')}.json")
    with open(path, "w") as f:
        json.dump([asdict(s) for s in signals], f, indent=2)
    print(f"[Evaluator] Saved {len(signals)} entries to {path}")
    return path


def load_cache() -> Optional[List[dict]]:
    """Load today's cached entries."""
    path = os.path.join(CACHE_DIR, f"entries_{datetime.now().strftime('%Y-%m-%d')}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def load_most_recent_cache():
    """Load the newest entries_YYYY-MM-DD.json regardless of date.
    Returns (signals_list, date_str, age_days) or (None, None, None)."""
    import glob, re
    files = sorted(glob.glob(os.path.join(CACHE_DIR, "entries_*.json")))
    if not files:
        return None, None, None
    latest = files[-1]
    m = re.search(r"entries_(\d{4}-\d{2}-\d{2})\.json$", latest)
    date_str = m.group(1) if m else ""
    age_days = 0
    try:
        if date_str:
            d_dt = datetime.strptime(date_str, "%Y-%m-%d")
            age_days = max(0, (datetime.now() - d_dt).days)
    except Exception:
        pass
    try:
        with open(latest) as f:
            return json.load(f), date_str, age_days
    except Exception:
        return None, date_str, age_days


async def validate_top_signals(signals: List[EntrySignal], top_n: int = 30) -> List[EntrySignal]:
    """Phase 3: Attach earnings / analyst / sentiment to top non-vetoed signals.
    Earnings within 10 days and analyst Hold/Sell are hard vetoes (CLAUDE.md V2.4).
    """
    import asyncio, aiohttp
    top = [s for s in signals if not s.vetoed][:top_n]
    if not top:
        return signals

    sem = asyncio.Semaphore(5)

    async def _check(sig: EntrySignal):
        async with sem:
            # Earnings veto via Tiingo News + Finnhub calendar union. Either
            # source alone has blind spots — Tiingo missed CAMT/CELC (small-cap
            # news gaps), Finnhub missed IREN (since fixed). The combined query
            # closes both gaps; this is the entries-tab call path that let CELC
            # through on 2026-05-08 with earnings 6 days out.
            try:
                from tiingo_earnings import earnings_window_combined
                async with aiohttp.ClientSession() as ses:
                    hit = await earnings_window_combined(ses, sig.ticker, days=10)
                if hit:
                    sig.vetoed = True
                    sig.veto_reason = (
                        f"Earnings {hit['direction']} ({hit['age_hours']:+.0f}h): "
                        f"{hit['title'][:60]}"
                    )
            except Exception:
                pass
            if not sig.vetoed:
                try:
                    from analyst_data import AnalystDataFetcher
                    a = await AnalystDataFetcher().fetch_analyst_data(sig.ticker)
                    if a:
                        sig.analyst_consensus = a.get("consensus", "") or ""
                        if sig.analyst_consensus in ("Hold", "Sell", "Strong Sell", "Underperform"):
                            sig.vetoed = True
                            sig.veto_reason = f"Analyst says {sig.analyst_consensus}"
                except Exception:
                    pass
            if not sig.vetoed:
                try:
                    from sentiment import SentimentEngine
                    s = await SentimentEngine().get_ticker_sentiment(sig.ticker)
                    if s:
                        sig.sentiment_label = s.get("sentiment_label", "") or ""
                except Exception:
                    pass

    await asyncio.gather(*[_check(s) for s in top], return_exceptions=True)
    return signals


if __name__ == "__main__":
    results = evaluate_all()
    save_cache(results)
    valid = [s for s in results if not s.vetoed]
    print(f"\nTOP 15 ENTRIES:")
    for i, s in enumerate(valid[:15], 1):
        print(f"  {i:>2}. {s.ticker:<7} ${s.price:>7.2f} [{s.strategy_label:<18}] "
              f"Score={s.score:>5.1f} WR={s.confidence:>4.0f}% Ret={s.expected_return:>+5.1f}% "
              f"({s.trades}t) Data:{s.data_date}")
