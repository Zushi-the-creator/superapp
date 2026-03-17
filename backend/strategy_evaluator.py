"""
Strategy Evaluator — Fast entry signal detection against cached prices.
=======================================================================
Runs BOTH mean reversion + momentum strategies on all cached stocks.
No API calls, no network — pure CPU against SQLite cache.

Architecture:
  1. Read all stock prices from stock_cache.db (bulk SQL, ~2s)
  2. Evaluate MR signals: RSI(2) < 10, above SMA50, ATR >= 3%
  3. Evaluate Momentum signals: Trend Template + acceleration
  4. Score each with expected_value = backtest_WR × backtest_avg_return
  5. Rank by combined score, tag with strategy type
  6. Return top 50 for Phase 3 validation (analyst/sentiment)

Speed target: < 5 seconds for 3000 stocks.
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


def _bayesian_wr(wins, total):
    pw = _UNIVERSE_WR / 100 * _PRIOR_WEIGHT
    return (wins + pw) / (total + _PRIOR_WEIGHT) * 100


def evaluate_all(min_price: float = 10.0, held_tickers: set = None) -> List[EntrySignal]:
    """Evaluate all stocks in cache for MR + Momentum signals. No API calls."""
    t0 = time.time()
    held = held_tickers or set()

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

        # Load price data
        c.execute("SELECT date, open, high, low, close, volume FROM daily_prices WHERE ticker=? ORDER BY date", (ticker,))
        rows = c.fetchall()
        if len(rows) < 80:
            continue

        dates = [r[0] for r in rows]
        opens = [r[1] for r in rows]
        highs = [r[2] for r in rows]
        lows = [r[3] for r in rows]
        closes = [r[4] for r in rows]
        volumes = [r[5] for r in rows]
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
        # MEAN REVERSION CHECK
        # ═══════════════════════════════════════════
        is_mr = (current_rsi < 10 and price > current_sma50 and current_sma50 > 0 and atr_pct >= 3)

        mr_score = 0
        mr_wr = 0
        mr_ret = 0
        mr_trades = 0

        if is_mr:
            # Backtest: RSI<10 + above SMA50 + 30d hold
            trades = []; le = -1
            for i in range(50, n - 32):
                if i <= le: continue
                if rsi2[i] < 10 and closes[i] > sma50[i]:
                    ep = opens[i+1] if i+1 < len(opens) and opens[i+1] > 0 else closes[i]
                    ret = ((closes[i+1+30] - ep) / ep) * 100 - 0.30
                    trades.append(ret > 0)
                    mr_ret += ret
                    le = i + 31

            mr_trades = len(trades)
            if mr_trades >= 5:
                wins = sum(trades)
                mr_wr = _bayesian_wr(wins, mr_trades)
                mr_ret = mr_ret / mr_trades
                mr_score = mr_wr * mr_ret / 100  # Expected value

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
        is_mom = (trend_score == 6 and ret_20d > 15 and vol_ratio > 1.5)

        mom_score = 0
        if is_mom:
            # Momentum score: emphasize recent acceleration + volume
            squeeze_bonus = max(0, (1 - atr_squeeze)) * 2
            mom_score = ret_20d * vol_ratio * (1 + squeeze_bonus) / 10  # Normalize to similar range as MR

        # ═══════════════════════════════════════════
        # DETERMINE BEST STRATEGY + COMBINED SCORE
        # ═══════════════════════════════════════════
        if is_mr and is_mom:
            strategy = "BOTH"
            label = "RSI Dip + Breakout"
            score = max(mr_score, mom_score) * 1.2  # 20% bonus for dual signal
            exp_ret = mr_ret
            conf = mr_wr
            trades_n = mr_trades
            mr_count += 1; mom_count += 1
        elif is_mr and mr_trades >= 5:
            strategy = "MEAN_REVERSION"
            label = "RSI Dip"
            score = mr_score
            exp_ret = mr_ret
            conf = mr_wr
            trades_n = mr_trades
            mr_count += 1
        elif is_mom:
            strategy = "MOMENTUM"
            label = "Breakout"
            score = mom_score
            exp_ret = ret_20d  # Use recent momentum as expected return proxy
            conf = 50  # No backtest WR for momentum yet
            trades_n = 0
            mom_count += 1
        else:
            continue  # No signal

        # VETO: min trades for MR
        vetoed = False
        veto_reason = ""
        if strategy == "MEAN_REVERSION" and mr_trades < 10:
            vetoed = True
            veto_reason = f"Too few trades ({mr_trades})"
        if strategy == "MEAN_REVERSION" and conf < 55:
            vetoed = True
            veto_reason = f"Bayesian WR {conf:.0f}% < 55%"
        if strategy == "MEAN_REVERSION" and mr_ret < 3:
            vetoed = True
            veto_reason = f"Avg return {mr_ret:.1f}% < 3%"

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


if __name__ == "__main__":
    results = evaluate_all()
    save_cache(results)
    valid = [s for s in results if not s.vetoed]
    print(f"\nTOP 15 ENTRIES:")
    for i, s in enumerate(valid[:15], 1):
        print(f"  {i:>2}. {s.ticker:<7} ${s.price:>7.2f} [{s.strategy_label:<18}] "
              f"Score={s.score:>5.1f} WR={s.confidence:>4.0f}% Ret={s.expected_return:>+5.1f}% "
              f"({s.trades}t) Data:{s.data_date}")
