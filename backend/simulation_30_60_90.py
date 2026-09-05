#!/usr/bin/env python3
"""
30 / 60 / 90-Day Strategy Simulation by Market Regime, Strategy and Sector
==========================================================================

Full signal-level backtest + portfolio-level simulation of every strategy the
repo defines, over the most recent 30 / 60 / 90 calendar days.

Entries (signal at close of day i, execution at NEXT-DAY OPEN i+1 — no look-ahead):
  MR_V3       : RSI(2) < 10, ATR(14)% >= 3, price >= $10           (live V3.0 evaluator)
  MR_V24      : RSI(2) < 10, close > SMA50, volume > 1.5x avg20     (ATLAS V2.4 / CLAUDE.md)
  MR_CONNORS  : RSI(2) < 10, close > SMA200                         (Connors classic)
  MOM_V3      : Minervini 6/6 trend template + 20d return > 5%      (live V3.0 momentum)
  MOM_STRICT  : Minervini 6/6 + 20d return > 15% + volume > 1.5x    (original M1 scanner)
  BREAKOUT    : close > prior 20-day high, volume > 1.5x, > SMA50   (sector_strategies BREAKOUT)

Exits (evaluated on closes from the day after entry; unfinished trades are
marked-to-market at the last close and flagged OPEN):
  Fixed5d / Fixed10d / Fixed14d / Fixed21d / Fixed60d / Fixed90d
  SMA5   : first close above SMA5, max 10d                          (Connors exit)
  RSI65  : first RSI(2) > 65, max 21d
  SMA10  : first close below SMA10, max 60d                         (trend-break exit)
  TRAIL10: -10% from peak close OR -12% hard stop OR close < SMA50, max 90d (M1 exit)

Fees (broker schedule: 10 free actions per calendar month, then $1.50 per action):
  Portfolio simulation applies the schedule exactly (an action = one buy or one sell).
  Signal-level backtest works in %, so it deducts a worst-case $3.00 round-trip on a
  $10K/6 = $1,667 slot = 0.18% per trade. (The repo's older 0.30% assumed $1,000 slots.)
Trades are non-overlapping per ticker per (entry, exit) combination — same as the live cache.

Regimes (tagged at signal date):
  market_regime : api_v2 data-driven SPY/VIX regime (HEALTHY, DIP_BUY, PULLBACK, WEAK,
                  BELOW_SMA200, CORRECTION, DANGER, BEAR_BOUNCE, FEAR, CRISIS)
  trend_regime  : atlas_v2.regime.RegimeDetector on SPY (BULL/BEAR/SIDEWAYS/HIGH_VOL)
  stock_regime  : RegimeDetector on the stock itself

Usage:
  python3 simulation_30_60_90.py --db data/stock_cache.db --sectors data/sectors.json --out results/
"""

import argparse
import json
import math
import os
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

FEE_USD = 1.50          # per action (buy or sell) after the free allowance
FREE_ACTIONS_PER_MONTH = 10
MIN_PRICE = 10.0
MAX_POSITIONS = 6       # api_v2.MAX_POSITIONS
START_CAPITAL = 10_000.0
# Signal-level % fee: worst case every action is paid, on a one-slot position
FEE_PCT = round(2 * FEE_USD / (START_CAPITAL / MAX_POSITIONS) * 100, 3)   # 0.18%

ENTRY_RULES = ["MR_V3", "MR_V24", "MR_CONNORS", "MOM_V3", "MOM_STRICT", "BREAKOUT"]
EXIT_RULES = ["Fixed5d", "Fixed10d", "Fixed14d", "Fixed21d", "Fixed60d", "Fixed90d",
              "SMA5", "RSI65", "SMA10", "TRAIL10"]

# The exit each strategy actually uses in the live system / documented model
LIVE_COMBOS = {
    "MR_V3": "Fixed60d",
    "MR_V24": "Fixed14d",
    "MR_CONNORS": "SMA5",
    "MOM_V3": "Fixed90d",
    "MOM_STRICT": "TRAIL10",
    "BREAKOUT": "SMA10",
}
MR_RULES = {"MR_V3", "MR_V24", "MR_CONNORS"}

# ----------------------------------------------------------------------------
# Sector mapping (Finnhub finnhubIndustry -> GICS-style sector)
# ----------------------------------------------------------------------------
INDUSTRY_TO_SECTOR = [
    # (keyword in industry string, sector)
    ("semiconductor", "TECHNOLOGY"), ("software", "TECHNOLOGY"), ("technology", "TECHNOLOGY"),
    ("electronic", "TECHNOLOGY"), ("computers", "TECHNOLOGY"), ("communications equipment", "TECHNOLOGY"),
    ("it services", "TECHNOLOGY"),
    ("bank", "FINANCIALS"), ("financial", "FINANCIALS"), ("insurance", "FINANCIALS"),
    ("capital markets", "FINANCIALS"), ("consumer finance", "FINANCIALS"), ("thrifts", "FINANCIALS"),
    ("mortgage", "FINANCIALS"),
    ("pharmaceutical", "HEALTHCARE"), ("biotech", "HEALTHCARE"), ("health", "HEALTHCARE"),
    ("medical", "HEALTHCARE"), ("life sciences", "HEALTHCARE"),
    ("energy", "ENERGY"), ("oil", "ENERGY"), ("gas", "ENERGY"), ("coal", "ENERGY"),
    ("utilit", "UTILITIES"), ("electric utilit", "UTILITIES"), ("water", "UTILITIES"),
    ("retail", "CONSUMER_DISCRETIONARY"), ("auto", "CONSUMER_DISCRETIONARY"), ("hotel", "CONSUMER_DISCRETIONARY"),
    ("restaurant", "CONSUMER_DISCRETIONARY"), ("leisure", "CONSUMER_DISCRETIONARY"), ("textile", "CONSUMER_DISCRETIONARY"),
    ("apparel", "CONSUMER_DISCRETIONARY"), ("household durables", "CONSUMER_DISCRETIONARY"),
    ("consumer services", "CONSUMER_DISCRETIONARY"), ("distributors", "CONSUMER_DISCRETIONARY"),
    ("specialty", "CONSUMER_DISCRETIONARY"), ("internet", "CONSUMER_DISCRETIONARY"),
    ("food", "CONSUMER_STAPLES"), ("beverage", "CONSUMER_STAPLES"), ("tobacco", "CONSUMER_STAPLES"),
    ("household products", "CONSUMER_STAPLES"), ("personal products", "CONSUMER_STAPLES"),
    ("consumer products", "CONSUMER_STAPLES"), ("staples", "CONSUMER_STAPLES"),
    ("media", "COMMUNICATION"), ("entertainment", "COMMUNICATION"), ("telecom", "COMMUNICATION"),
    ("communication", "COMMUNICATION"), ("interactive", "COMMUNICATION"),
    ("real estate", "REAL_ESTATE"), ("reit", "REAL_ESTATE"),
    ("chemical", "MATERIALS"), ("metals", "MATERIALS"), ("mining", "MATERIALS"), ("packaging", "MATERIALS"),
    ("paper", "MATERIALS"), ("construction materials", "MATERIALS"), ("containers", "MATERIALS"),
    ("steel", "MATERIALS"), ("gold", "MATERIALS"),
    ("aerospace", "INDUSTRIALS"), ("defense", "INDUSTRIALS"), ("machinery", "INDUSTRIALS"),
    ("building", "INDUSTRIALS"), ("construction", "INDUSTRIALS"), ("airline", "INDUSTRIALS"),
    ("transport", "INDUSTRIALS"), ("logistics", "INDUSTRIALS"), ("industrial", "INDUSTRIALS"),
    ("electrical", "INDUSTRIALS"), ("commercial services", "INDUSTRIALS"), ("professional services", "INDUSTRIALS"),
    ("trading companies", "INDUSTRIALS"), ("marine", "INDUSTRIALS"), ("road", "INDUSTRIALS"),
    ("rail", "INDUSTRIALS"),
]

ETF_TICKERS = {"SPY", "QQQ", "IWM", "XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLU", "XLB", "XLI", "XLRE", "XLC", "VIX"}
BENCH_SECTOR_ETF = {"TECHNOLOGY": "XLK", "ENERGY": "XLE", "FINANCIALS": "XLF", "HEALTHCARE": "XLV",
                    "CONSUMER_DISCRETIONARY": "XLY", "CONSUMER_STAPLES": "XLP", "UTILITIES": "XLU",
                    "MATERIALS": "XLB", "INDUSTRIALS": "XLI", "REAL_ESTATE": "XLRE", "COMMUNICATION": "XLC"}


# Exact Finnhub industry names (GICS-derived) -> sector. Checked before keyword fallback.
FINNHUB_INDUSTRY_EXACT = {
    "Biotechnology": "HEALTHCARE", "Pharmaceuticals": "HEALTHCARE", "Health Care": "HEALTHCARE",
    "Life Sciences Tools & Services": "HEALTHCARE", "Medical Devices": "HEALTHCARE",
    "Technology": "TECHNOLOGY", "Semiconductors": "TECHNOLOGY", "Software": "TECHNOLOGY",
    "Electronic Equipment, Instruments & Components": "TECHNOLOGY", "Communications Equipment": "TECHNOLOGY",
    "Financial Services": "FINANCIALS", "Insurance": "FINANCIALS", "Banking": "FINANCIALS",
    "Capital Markets": "FINANCIALS", "Consumer Finance": "FINANCIALS",
    "Real Estate": "REAL_ESTATE",
    "Electrical Equipment": "INDUSTRIALS", "Machinery": "INDUSTRIALS", "Aerospace & Defense": "INDUSTRIALS",
    "Building": "INDUSTRIALS", "Construction": "INDUSTRIALS", "Airlines": "INDUSTRIALS",
    "Commercial Services & Supplies": "INDUSTRIALS", "Professional Services": "INDUSTRIALS",
    "Trading Companies & Distributors": "INDUSTRIALS", "Road & Rail": "INDUSTRIALS",
    "Transportation Infrastructure": "INDUSTRIALS", "Logistics & Transportation": "INDUSTRIALS",
    "Industrial Conglomerates": "INDUSTRIALS", "Marine": "INDUSTRIALS",
    "Metals & Mining": "MATERIALS", "Chemicals": "MATERIALS", "Packaging": "MATERIALS",
    "Paper & Forest": "MATERIALS", "Construction Materials": "MATERIALS",
    "Retail": "CONSUMER_DISCRETIONARY", "Hotels, Restaurants & Leisure": "CONSUMER_DISCRETIONARY",
    "Auto Components": "CONSUMER_DISCRETIONARY", "Automobiles": "CONSUMER_DISCRETIONARY",
    "Diversified Consumer Services": "CONSUMER_DISCRETIONARY", "Distributors": "CONSUMER_DISCRETIONARY",
    "Textiles, Apparel & Luxury Goods": "CONSUMER_DISCRETIONARY", "Household Durables": "CONSUMER_DISCRETIONARY",
    "Leisure Products": "CONSUMER_DISCRETIONARY", "Consumer products": "CONSUMER_STAPLES",
    "Food Products": "CONSUMER_STAPLES", "Beverages": "CONSUMER_STAPLES", "Tobacco": "CONSUMER_STAPLES",
    "Household Products": "CONSUMER_STAPLES", "Personal Products": "CONSUMER_STAPLES",
    "Food & Staples Retailing": "CONSUMER_STAPLES",
    "Energy": "ENERGY", "Oil, Gas & Consumable Fuels": "ENERGY", "Energy Equipment & Services": "ENERGY",
    "Utilities": "UTILITIES",
    "Telecommunication": "COMMUNICATION", "Media": "COMMUNICATION", "Communications": "COMMUNICATION",
    "Entertainment": "COMMUNICATION", "Interactive Media & Services": "COMMUNICATION",
}


def industry_to_sector(industry: str) -> str:
    raw = (industry or "").strip()
    if not raw or raw.upper() == "N/A":
        return "UNKNOWN"
    if raw in FINNHUB_INDUSTRY_EXACT:
        return FINNHUB_INDUSTRY_EXACT[raw]
    s = raw.lower()
    if "biotech" in s:
        return "HEALTHCARE"
    for kw, sec in INDUSTRY_TO_SECTOR:
        if kw in s:
            return sec
    return "OTHER"


def load_sectors(path):
    sectors = {}
    if path and os.path.exists(path):
        raw = json.load(open(path))
        for t, d in raw.items():
            ind = d.get("industry", "") if isinstance(d, dict) else str(d)
            sectors[t] = industry_to_sector(ind)
    # Fallback: repo SECTOR_MAP for anything missing
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from atlas_v2.sector_strategies import SECTOR_MAP
        for t, sec in SECTOR_MAP.items():
            if sectors.get(t, "UNKNOWN") in ("UNKNOWN", "OTHER"):
                sectors[t] = sec.value
    except Exception:
        pass
    return sectors


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def load_prices(db_path):
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    table = "prices" if "prices" in tables else "daily_prices"
    rows = conn.execute(f"select ticker,date,open,high,low,close,volume from {table} order by ticker,date").fetchall()
    conn.close()
    data = {}
    cur, buf = None, []

    def flush():
        if cur and len(buf) >= 30:
            arr = np.array([(r[2], r[3], r[4], r[5], r[6]) for r in buf], dtype=float)
            data[cur] = {
                "dates": [r[1] for r in buf],
                "o": arr[:, 0], "h": arr[:, 1], "l": arr[:, 2], "c": arr[:, 3], "v": arr[:, 4],
            }
    for r in rows:
        if r[0] != cur:
            flush()
            cur, buf = r[0], []
        if r[5] is None or r[5] <= 0:
            continue
        buf.append(r)
    flush()
    return data


# ----------------------------------------------------------------------------
# Indicators (mirror backtest_precompute.py / strategy_evaluator.py math)
# ----------------------------------------------------------------------------
def rsi2_simple(c):
    """Repo-style RSI(2): simple 2-bar average gain/loss (not Wilder)."""
    n = len(c)
    rsi = np.full(n, 50.0)
    d = np.diff(c)
    for i in range(2, n):
        c1, c2 = d[i - 1], d[i - 2]
        ag = (max(0.0, c1) + max(0.0, c2)) / 2
        al = (max(0.0, -c1) + max(0.0, -c2)) / 2
        if al > 0:
            rsi[i] = 100.0 - 100.0 / (1 + ag / al)
        elif ag > 0:
            rsi[i] = 100.0
        else:
            rsi[i] = 50.0
    return rsi


def sma(c, p):
    n = len(c)
    out = np.full(n, np.nan)
    if n >= p:
        cs = np.cumsum(np.insert(c, 0, 0.0))
        out[p - 1:] = (cs[p:] - cs[:-p]) / p
    return out


def rolling_max(x, p, inclusive=True):
    """Max of last p bars (inclusive of current bar if inclusive). Partial windows at the start use what exists."""
    n = len(x)
    out = np.full(n, np.nan)
    src = x if inclusive else np.concatenate(([np.nan], x[:-1]))
    cm = np.maximum.accumulate(np.nan_to_num(src, nan=-np.inf))
    lim = min(p, n)
    out[:lim] = cm[:lim]
    if n > p:
        out[p:] = np.max(np.lib.stride_tricks.sliding_window_view(src, p)[1:], axis=1) if inclusive else \
            np.max(np.lib.stride_tricks.sliding_window_view(src, p)[1:], axis=1)
    if not inclusive:
        out[0] = np.nan
    return out


def rolling_min(x, p):
    n = len(x)
    out = np.full(n, np.nan)
    cm = np.minimum.accumulate(x)
    lim = min(p, n)
    out[:lim] = cm[:lim]
    if n > p:
        out[p:] = np.min(np.lib.stride_tricks.sliding_window_view(x, p)[1:], axis=1)
    return out


def _rolling_max_ref(x, p, inclusive=True):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(n):
        lo = max(0, i - p + 1) if inclusive else max(0, i - p)
        hi = i + 1 if inclusive else i
        if hi > lo:
            out[i] = x[lo:hi].max()
    return out


def _rolling_min_ref(x, p):
    n = len(x)
    out = np.full(n, np.nan)
    for i in range(n):
        out[i] = x[max(0, i - p + 1):i + 1].min()
    return out


def atr_pct(h, l, c):
    """ATR(14)% exactly as backtest_precompute: mean TR of bars [i-13..i] / close[i]."""
    n = len(c)
    tr = np.zeros(n)
    tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    out = np.full(n, np.nan)
    for i in range(1, n):
        lo = max(1, i - 13)
        out[i] = tr[lo:i + 1].mean() / c[i] * 100 if c[i] > 0 else np.nan
    return out


def compute_indicators(d):
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]
    n = len(c)
    ind = {
        "rsi2": rsi2_simple(c),
        "sma5": sma(c, 5), "sma10": sma(c, 10), "sma50": sma(c, 50),
        "sma150": sma(c, 150), "sma200": sma(c, 200),
        "atr_pct": atr_pct(h, l, c),
        "hi52": rolling_max(h, 252), "lo52": rolling_min(l, 252),
        "hi20_prior": rolling_max(h, 20, inclusive=False),
        "vol20": sma(v, 20),
    }
    ret20 = np.full(n, np.nan)
    ret20[20:] = (c[20:] / c[:-20] - 1) * 100
    ind["ret20"] = ret20
    ret60 = np.full(n, np.nan)
    if n > 60:
        ret60[60:] = (c[60:] / c[:-60] - 1) * 100
    ind["ret60"] = ret60
    vr = np.full(n, np.nan)
    ok = ind["vol20"] > 0
    vr[ok] = v[ok] / ind["vol20"][ok]
    ind["vol_ratio"] = vr
    return ind


def minervini6(i, c, ind):
    s50, s150, s200 = ind["sma50"][i], ind["sma150"][i], ind["sma200"][i]
    if any(np.isnan(x) or x <= 0 for x in (s50, s150, s200)):
        return False
    if not (c[i] > s50 and c[i] > s150 and c[i] > s200):
        return False
    if not (s50 > s150 > s200):
        return False
    hi, lo = ind["hi52"][i], ind["lo52"][i]
    if hi <= 0 or lo <= 0:
        return False
    if (c[i] / hi - 1) * 100 < -25:
        return False
    if (c[i] / lo - 1) * 100 < 30:
        return False
    return True


def entry_signal(rule, i, d, ind):
    c = d["c"]
    if c[i] < MIN_PRICE:
        return False
    r2 = ind["rsi2"][i]
    if rule == "MR_V3":
        return r2 < 10 and ind["atr_pct"][i] >= 3
    if rule == "MR_V24":
        return r2 < 10 and c[i] > ind["sma50"][i] and ind["vol_ratio"][i] > 1.5
    if rule == "MR_CONNORS":
        return r2 < 10 and c[i] > ind["sma200"][i]
    if rule == "MOM_V3":
        return ind["ret20"][i] > 5 and minervini6(i, c, ind)
    if rule == "MOM_STRICT":
        return ind["ret20"][i] > 15 and ind["vol_ratio"][i] > 1.5 and minervini6(i, c, ind)
    if rule == "BREAKOUT":
        return (c[i] > ind["hi20_prior"][i] and ind["vol_ratio"][i] > 1.5
                and c[i] > ind["sma50"][i])
    raise ValueError(rule)


def exit_index(rule, e, d, ind):
    """Return (exit_idx, is_open). e = entry bar index (entry at open[e])."""
    c = d["c"]
    n = len(c)
    last = n - 1
    if rule.startswith("Fixed"):
        k = int(rule[5:-1])
        x = e + k
        return (x, False) if x <= last else (last, True)
    max_hold = {"SMA5": 10, "RSI65": 21, "SMA10": 60, "TRAIL10": 90}[rule]
    peak = c[e]
    ep = d["o"][e]
    for j in range(e + 1, min(e + max_hold, last) + 1):
        peak = max(peak, c[j])
        if rule == "SMA5" and c[j] > ind["sma5"][j]:
            return j, False
        if rule == "RSI65" and ind["rsi2"][j] > 65:
            return j, False
        if rule == "SMA10" and c[j] < ind["sma10"][j]:
            return j, False
        if rule == "TRAIL10":
            if c[j] <= peak * 0.90 or c[j] <= ep * 0.88 or (not np.isnan(ind["sma50"][j]) and c[j] < ind["sma50"][j]):
                return j, False
        if j - e >= max_hold:
            return j, False
    return last, True


# ----------------------------------------------------------------------------
# Regimes
# ----------------------------------------------------------------------------
def trend_regime_at(c, i):
    """atlas_v2.regime.RegimeDetector.detect on closes[:i+1]."""
    closes = c[:i + 1]
    if len(closes) < 50:
        return "SIDEWAYS"
    price = closes[-1]
    s50 = closes[-50:].mean()
    s200 = closes[-200:].mean() if len(closes) >= 200 else s50
    if len(closes) >= 60:
        rv = statistics.stdev(closes[-20:].tolist())
        hv = statistics.stdev(closes[-60:].tolist())
        vol_ratio = rv / hv if hv > 0 else 1.0
    else:
        vol_ratio = 1.0
    if vol_ratio > 2.0:
        return "HIGH_VOL"
    if s50 > s200 and price > s50:
        return "BULL"
    if s50 < s200 and price < s50:
        return "BEAR"
    return "SIDEWAYS"


def market_regime_series(spy, vix):
    """Daily api_v2 regime for SPY. Returns dict date -> (regime, size_pct, pause_entries, pause_mr, metrics)."""
    c = spy["c"]
    dates = spy["dates"]
    vix_map = dict(zip(vix["dates"], vix["c"])) if vix else {}
    out = {}
    last_vix = 0.0
    for i, dt in enumerate(dates):
        last_vix = vix_map.get(dt, last_vix)
        closes = c[:i + 1]
        price = closes[-1]
        s50 = closes[-min(50, len(closes)):].mean()
        s200 = closes[-200:].mean() if len(closes) >= 200 else 0
        peak = closes[-min(252, len(closes)):].max()
        dd = (price - peak) / peak * 100
        gap200 = (price - s200) / s200 * 100 if s200 > 0 else 0
        gap50 = (price - s50) / s50 * 100 if s50 > 0 else 0
        v = last_vix
        pause, pause_mr = False, False
        if -15 <= dd < -10:
            reg, size, pause = "DANGER", 0, True
        elif v > 40:
            reg, size, pause = "CRISIS", 0, True
        elif -2 < gap200 < 0:
            reg, size, pause_mr = "WEAK", 50, True
        elif -20 <= dd < -15:
            reg, size = "CORRECTION", 50
        elif dd < -20:
            reg, size = "BEAR_BOUNCE", 100
        elif gap200 < -2:
            reg, size = "BELOW_SMA200", 100
        elif gap50 < 0:
            reg, size = "PULLBACK", 100
        elif dd < -3:
            reg, size = "DIP_BUY", 100
        elif v > 30:
            reg, size = "FEAR", 50
        else:
            reg, size = "HEALTHY", 70
        out[dt] = {"regime": reg, "size_pct": size, "pause_entries": pause, "pause_mr": pause_mr,
                   "trend": trend_regime_at(c, i), "spy": round(float(price), 2), "vix": round(float(v), 2),
                   "drawdown": round(float(dd), 2), "gap200": round(float(gap200), 2), "gap50": round(float(gap50), 2)}
    return out


# ----------------------------------------------------------------------------
# Signal-level backtest
# ----------------------------------------------------------------------------
def run_signal_backtest(data, sectors, regimes, start_date, end_date):
    trades = []
    for t, d in data.items():
        if t in ETF_TICKERS:
            continue
        dates = d["dates"]
        n = len(dates)
        if n < 60 or dates[-1] < end_date:
            continue  # stale / delisted series — cannot mark to market honestly
        ind = compute_indicators(d)
        i_start = next((k for k, dt in enumerate(dates) if dt >= start_date), None)
        if i_start is None:
            continue
        stock_reg_cache = {}
        for er in ENTRY_RULES:
            sig_idx = [i for i in range(max(i_start, 20), n - 1) if entry_signal(er, i, d, ind)]
            if not sig_idx:
                continue
            for xr in EXIT_RULES:
                last_exit = -1
                for i in sig_idx:
                    if i <= last_exit:
                        continue
                    e = i + 1
                    ep = d["o"][e] if d["o"][e] > 0 else d["c"][i]
                    if ep < MIN_PRICE:
                        continue
                    x, is_open = exit_index(xr, e, d, ind)
                    xp = d["c"][x]
                    ret = (xp / ep - 1) * 100 - FEE_PCT
                    if i not in stock_reg_cache:
                        stock_reg_cache[i] = trend_regime_at(d["c"], i)
                    mr = regimes.get(dates[i], {})
                    trades.append({
                        "ticker": t, "entry_rule": er, "exit_rule": xr,
                        "signal_date": dates[i], "entry_date": dates[e], "entry_px": round(float(ep), 4),
                        "exit_date": dates[x], "exit_px": round(float(xp), 4),
                        "ret": round(float(ret), 4), "days_held": int(x - e), "open": bool(is_open),
                        "market_regime": mr.get("regime", "NA"), "trend_regime": mr.get("trend", "NA"),
                        "stock_regime": stock_reg_cache[i], "sector": sectors.get(t, "UNKNOWN"),
                        "rsi2": round(float(ind["rsi2"][i]), 2),
                        "ret20": round(float(ind["ret20"][i]), 2) if not np.isnan(ind["ret20"][i]) else None,
                        "vol_ratio": round(float(ind["vol_ratio"][i]), 2) if not np.isnan(ind["vol_ratio"][i]) else None,
                        "atr_pct": round(float(ind["atr_pct"][i]), 2) if not np.isnan(ind["atr_pct"][i]) else None,
                    })
                    last_exit = x
    return trades


def stats(rets):
    rets = [r for r in rets if r is not None]
    n = len(rets)
    if n == 0:
        return {"trades": 0}
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gp = sum(wins)
    gl = -sum(losses)
    mean = sum(rets) / n
    sd = statistics.pstdev(rets) if n > 1 else 0.0
    tstat = mean / (sd / math.sqrt(n)) if sd > 0 and n > 1 else 0.0
    return {
        "trades": n, "wr": round(len(wins) / n * 100, 1), "avg": round(mean, 2),
        "median": round(statistics.median(rets), 2),
        "pf": round(gp / gl, 2) if gl > 0 else (99.0 if gp > 0 else 0.0),
        "total": round(sum(rets), 1), "tstat": round(tstat, 2),
        "best": round(max(rets), 1), "worst": round(min(rets), 1),
    }


def group_stats(trades, keys, include_open=True, min_trades=1):
    g = defaultdict(list)
    for tr in trades:
        if not include_open and tr["open"]:
            continue
        g[tuple(tr[k] for k in keys)].append(tr["ret"])
    out = {}
    for k, v in g.items():
        if len(v) >= min_trades:
            s = stats(v)
            s["open_pct"] = 0
            out[k] = s
    # open share
    cnt_open = defaultdict(int)
    cnt_all = defaultdict(int)
    for tr in trades:
        k = tuple(tr[k2] for k2 in keys)
        cnt_all[k] += 1
        cnt_open[k] += tr["open"]
    for k in out:
        out[k]["open_pct"] = round(cnt_open[k] / cnt_all[k] * 100, 0) if cnt_all[k] else 0
    return out


# ----------------------------------------------------------------------------
# Portfolio simulation (live system mechanics)
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Portfolio simulation (live system mechanics)
# ----------------------------------------------------------------------------
_UNIVERSE_WR = 53.5      # backtest_precompute.py Bayesian prior
_PRIOR_WEIGHT = 10


def _bayes_wr(wins, total):
    pw = _UNIVERSE_WR / 100 * _PRIOR_WEIGHT
    return (wins + pw) / (total + _PRIOR_WEIGHT) * 100


def precompute_stock_cache(data, ind_cache, cutoff_date):
    """Per-stock MR (MR_V3/Fixed60d) and MOM (MOM_V3/Fixed90d) stats using ONLY trades that
    exited before cutoff_date — the same numbers the live backtest_cache would hold, minus the
    look-ahead. Returns {ticker: {"mr": score|None, "mom": score|None, ...}} where score is
    bayes_wr x avg_ret / 100 and None means the live VETO applies (trades<5, WR<55%, ret<3%/2%)."""
    out = {}
    for t, d in data.items():
        ind = ind_cache[t]
        dates = d["dates"]
        cut = next((k for k, dt in enumerate(dates) if dt >= cutoff_date), len(dates))
        rec = {}
        for fam, er, hold, min_ret in (("mr", "MR_V3", 60, 3.0), ("mom", "MOM_V3", 90, 2.0)):
            trades, wins, tot = 0, 0, 0.0
            last_exit = -1
            for i in range(20, cut - hold - 1):
                if i <= last_exit or not entry_signal(er, i, d, ind):
                    continue
                e = i + 1
                ep = d["o"][e] if d["o"][e] > 0 else d["c"][i]
                if ep < MIN_PRICE:
                    continue
                x = e + hold
                ret = (d["c"][x] / ep - 1) * 100 - FEE_PCT
                trades += 1
                wins += ret > 0
                tot += ret
                last_exit = x
            if trades >= 5:
                bw = _bayes_wr(wins, trades)
                avg = tot / trades
                rec[fam] = (bw * avg / 100) if (bw >= 55 and avg >= min_ret) else None
                rec[fam + "_stats"] = (trades, round(bw, 1), round(avg, 2))
            else:
                rec[fam] = None
                rec[fam + "_stats"] = (trades, None, None)
        out[t] = rec
    return out


def build_stock_cache_from_db(db_path, cutoff_date, out_path):
    """Stream every ticker from db_path (ideally 10 years, like the live backtest_cache),
    compute MR/MOM cache stats using only trades exited before cutoff_date, write JSON."""
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    table = "prices" if "prices" in tables else "daily_prices"
    tickers = [r[0] for r in conn.execute(f"select distinct ticker from {table}")]
    out = {}
    for n_done, t in enumerate(tickers):
        if t in ETF_TICKERS:
            continue
        rows = conn.execute(f"select date,open,high,low,close,volume from {table} where ticker=? and date<? order by date",
                            (t, cutoff_date)).fetchall()
        rows = [r for r in rows if r[4] and r[4] > 0]
        if len(rows) < 100:
            continue
        arr = np.array([(r[1], r[2], r[3], r[4], r[5]) for r in rows], dtype=float)
        d = {"dates": [r[0] for r in rows], "o": arr[:, 0], "h": arr[:, 1], "l": arr[:, 2], "c": arr[:, 3], "v": arr[:, 4]}
        ind = compute_indicators(d)
        rec = precompute_stock_cache({t: d}, {t: ind}, cutoff_date)[t]
        out[t] = rec
        if n_done % 300 == 0:
            print(f"  cache {n_done}/{len(tickers)}", flush=True)
    conn.close()
    json.dump(out, open(out_path, "w"))
    nv = {fam: sum(1 for r in out.values() if r.get(fam) is not None) for fam in ("mr", "mom")}
    print(f"  wrote {out_path}: {len(out)} stocks, validated MR={nv['mr']} MOM={nv['mom']}", flush=True)
    return out


def precompute_signals(data, ind_cache, dates_span):
    """{entry_rule: {date: [(ticker, k)]}} for every trading date in dates_span."""
    date_set = set(dates_span)
    sig = {er: defaultdict(list) for er in ENTRY_RULES}
    for t, d in data.items():
        ind = ind_cache[t]
        for k, dt in enumerate(d["dates"]):
            if dt not in date_set or k < 20 or k >= len(d["dates"]) - 1:
                continue
            for er in ENTRY_RULES:
                if entry_signal(er, k, d, ind):
                    sig[er][dt].append((t, k))
    return sig


def portfolio_sim(data, ind_cache, regimes, spy_dates, start_date, end_date, strategies, signals,
                  stock_cache=None, rank_mode="live", seed=0, max_pos=MAX_POSITIONS, use_regime_sizing=True):
    """Simulate the live system: max 6 slots, equal weight, regime sizing, next-open entries,
    exit on the strategy's own rule, broker fee schedule (10 free actions/month then $1.50).

    rank_mode:
      "live"    — rank by per-stock backtest expected value (bayes WR x avg return) from
                  stock_cache, with the live VETO thresholds (how strategy_evaluator.py ranks)
      "deepest" — MR by deepest RSI(2) then SMA50 buffer; momentum by 20d return x volume ratio
      "random"  — uniform random among qualifying signals (Monte Carlo baseline)
    """
    import random as _random
    rng = _random.Random(seed)
    days = [dt for dt in spy_dates if start_date <= dt <= end_date]
    date_idx = {t: {dt: k for k, dt in enumerate(d["dates"])} for t, d in data.items()}
    cash = START_CAPITAL
    positions = {}
    pending = []
    equity_curve = []
    closed = []
    actions_by_month = defaultdict(int)
    fees_paid = 0.0

    def fee_for_action(dt):
        nonlocal fees_paid
        m = dt[:7]
        actions_by_month[m] += 1
        f = 0.0 if actions_by_month[m] <= FREE_ACTIONS_PER_MONTH else FEE_USD
        fees_paid += f
        return f

    for di, dt in enumerate(days):
        # 1. execute pending buys at today's open
        for p in pending:
            t = p["ticker"]
            k = date_idx[t].get(dt)
            if k is None or t in positions:
                continue
            px = data[t]["o"][k]
            if px <= 0:
                continue
            size = min(p["size"], cash - FEE_USD)
            if size < 100:
                continue
            shares = size / px
            fee = fee_for_action(dt)
            cash -= size + fee
            positions[t] = {"ticker": t, "entry_idx": k, "entry_px": px, "shares": shares, "entry_date": dt,
                            "entry_rule": p["entry_rule"], "exit_rule": p["exit_rule"], "peak": px,
                            "signal_date": p["signal_date"], "market_regime": p["market_regime"],
                            "entry_fee": fee}
        pending = []
        # 2. exits at today's close
        for t in list(positions):
            pos = positions[t]
            d = data[t]
            k = date_idx[t].get(dt)
            if k is None:
                continue
            ind = ind_cache[t]
            e = pos["entry_idx"]
            held = k - e
            c = d["c"][k]
            pos["peak"] = max(pos["peak"], c)
            xr = pos["exit_rule"]
            do_exit = False
            if xr.startswith("Fixed"):
                do_exit = held >= int(xr[5:-1])
            elif held >= 1:
                if xr == "SMA5":
                    do_exit = c > ind["sma5"][k] or held >= 10
                elif xr == "RSI65":
                    do_exit = ind["rsi2"][k] > 65 or held >= 21
                elif xr == "SMA10":
                    do_exit = c < ind["sma10"][k] or held >= 60
                elif xr == "TRAIL10":
                    do_exit = (c <= pos["peak"] * 0.90 or c <= pos["entry_px"] * 0.88
                               or (not np.isnan(ind["sma50"][k]) and c < ind["sma50"][k]) or held >= 90)
            if do_exit:
                fee = fee_for_action(dt)
                proceeds = pos["shares"] * c - fee
                cash += proceeds
                cost = pos["shares"] * pos["entry_px"]
                pnl = proceeds - cost - pos["entry_fee"]
                closed.append({k2: v for k2, v in pos.items() if k2 not in ("peak", "entry_idx", "entry_fee")}
                              | {"exit_date": dt, "exit_px": round(float(c), 4), "pnl": round(pnl, 2),
                                 "ret": round(pnl / cost * 100, 2), "days_held": held})
                del positions[t]
        # 3. mark equity
        mv = 0.0
        for t, pos in positions.items():
            k = date_idx[t].get(dt)
            mv += pos["shares"] * (data[t]["c"][k] if k is not None else pos["entry_px"])
        equity = cash + mv
        equity_curve.append((dt, round(equity, 2), len(positions)))
        # 4. new signals at close -> pending for next open (not on the last day)
        if di == len(days) - 1:
            break
        reg = regimes.get(dt, {})
        if use_regime_sizing and reg.get("pause_entries"):
            continue
        slots = max_pos - len(positions)
        if slots <= 0:
            continue
        size_pct = reg.get("size_pct", 100) if use_regime_sizing else 100
        target = equity / max_pos * size_pct / 100
        if target < 100:
            continue
        cands = []
        for er, xr in strategies:
            if use_regime_sizing and reg.get("pause_mr") and er in MR_RULES:
                continue
            fam = "mr" if er in MR_RULES else "mom"
            for t, k in signals[er].get(dt, ()):
                if t in positions:
                    continue
                ind = ind_cache[t]
                d = data[t]
                if rank_mode == "live":
                    score = (stock_cache.get(t) or {}).get(fam)
                    if score is None:
                        continue  # live VETO: no validated edge for this stock
                elif rank_mode == "random":
                    score = rng.random()
                else:
                    if er in MR_RULES:
                        buf = (d["c"][k] / ind["sma50"][k] - 1) * 100 if not np.isnan(ind["sma50"][k]) else 0
                        score = (10 - ind["rsi2"][k]) * 10 + buf
                    else:
                        vr = ind["vol_ratio"][k] if not np.isnan(ind["vol_ratio"][k]) else 1
                        score = ind["ret20"][k] * vr
                cands.append((score, er, xr, t))
        # round-robin across rules so no single rule hogs all slots
        by_rule = defaultdict(list)
        for cnd in sorted(cands, key=lambda x: -x[0]):
            by_rule[cnd[1]].append(cnd)
        picked, taken = [], set()
        while len(picked) < slots and any(by_rule.values()):
            for er in list(by_rule):
                if by_rule[er] and len(picked) < slots:
                    cnd = by_rule[er].pop(0)
                    if cnd[3] not in taken:
                        picked.append(cnd)
                        taken.add(cnd[3])
        for score, er, xr, t in picked:
            pending.append({"ticker": t, "size": target, "entry_rule": er, "exit_rule": xr,
                            "signal_date": dt, "market_regime": reg.get("regime")})
    final_equity = equity_curve[-1][1]
    peak, mdd = 0, 0
    for _, eq, _ in equity_curve:
        peak = max(peak, eq)
        mdd = min(mdd, (eq - peak) / peak * 100)
    open_mtm = []
    for t, pos in positions.items():
        k = date_idx[t].get(days[-1])
        c = data[t]["c"][k] if k is not None else pos["entry_px"]
        open_mtm.append({"ticker": t, "entry_rule": pos["entry_rule"], "entry_date": pos["entry_date"],
                         "entry_px": round(float(pos["entry_px"]), 4), "last_px": round(float(c), 4),
                         "ret": round((c / pos["entry_px"] - 1) * 100, 2),
                         "days_held": (k - pos["entry_idx"]) if k is not None else 0})
    return {
        "return_pct": round((final_equity / START_CAPITAL - 1) * 100, 2),
        "final_equity": final_equity, "max_dd": round(mdd, 2),
        "closed_trades": len(closed), "closed_stats": stats([c["ret"] for c in closed]),
        "open_positions": open_mtm, "equity_curve": equity_curve, "closed": closed,
        "fees_paid": round(fees_paid, 2), "actions": sum(actions_by_month.values()),
        "actions_by_month": dict(actions_by_month),
    }


def summarize_mc(runs):
    rets = sorted(r["return_pct"] for r in runs)
    dds = [r["max_dd"] for r in runs]
    n = len(rets)
    q = lambda p: rets[min(n - 1, int(p * n))]
    return {"runs": n, "median": round(statistics.median(rets), 2), "mean": round(sum(rets) / n, 2),
            "p10": round(q(0.10), 2), "p90": round(q(0.90), 2), "min": rets[0], "max": rets[-1],
            "pct_positive": round(sum(1 for r in rets if r > 0) / n * 100, 0),
            "avg_max_dd": round(sum(dds) / n, 2),
            "avg_closed_trades": round(sum(r["closed_trades"] for r in runs) / n, 1)}


# Main
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(__file__), "data", "stock_cache.db"))
    ap.add_argument("--sectors", default=os.path.join(os.path.dirname(__file__), "data", "sectors.json"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__), "data", "simulation_30_60_90"))
    ap.add_argument("--end", default=None, help="last trading date (default: last SPY date in DB)")
    ap.add_argument("--no-portfolio", action="store_true")
    ap.add_argument("--positions-db", default=os.path.join(os.path.dirname(__file__), "data", "positions.db"))
    ap.add_argument("--stock-cache", default=None,
                    help="JSON from --build-cache (per-stock MR/MOM expected value, like the live backtest_cache)")
    ap.add_argument("--build-cache", default=None, metavar="DB10Y",
                    help="build the stock cache from this (10-year) price DB and exit")
    args = ap.parse_args()
    if args.build_cache:
        spy_end = args.end
        if not spy_end:
            conn = sqlite3.connect(args.db)
            spy_end = conn.execute("select max(date) from prices where ticker='SPY'").fetchone()[0]
            conn.close()
        cutoff = (datetime.strptime(spy_end, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        os.makedirs(args.out, exist_ok=True)
        build_stock_cache_from_db(args.build_cache, cutoff, args.stock_cache or os.path.join(args.out, "stock_cache.json"))
        return
    os.makedirs(args.out, exist_ok=True)

    print("Loading prices...", flush=True)
    data = load_prices(args.db)
    sectors = load_sectors(args.sectors)
    spy = data["SPY"]
    vix = data.get("VIX")
    end_date = args.end or spy["dates"][-1]
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    windows = {w: (end_dt - timedelta(days=w)).strftime("%Y-%m-%d") for w in (30, 60, 90)}
    print(f"Universe: {len(data)} series, end={end_date}, windows={windows}", flush=True)

    regimes = market_regime_series(spy, vix)
    print("Running signal-level backtest (90-day window covers 30/60)...", flush=True)
    trades = run_signal_backtest(data, sectors, regimes, windows[90], end_date)
    print(f"  {len(trades)} trades across {len(ENTRY_RULES)}x{len(EXIT_RULES)} combos", flush=True)

    # Benchmarks per window
    def bench(t, start):
        d = data.get(t)
        if not d:
            return None
        i0 = next((k for k, dt in enumerate(d["dates"]) if dt >= start), None)
        if i0 is None:
            return None
        return round((d["c"][-1] / d["c"][i0] - 1) * 100, 2)

    results = {"end_date": end_date, "windows": windows, "universe_size": len(data),
               "regime_timeline": {dt: r for dt, r in regimes.items() if dt >= windows[90]},
               "benchmarks": {}, "signal": {}, "portfolio": {}}
    for w, start in windows.items():
        results["benchmarks"][w] = {t: bench(t, start) for t in ["SPY", "QQQ", "IWM"] + list(BENCH_SECTOR_ETF.values())}

    for w, start in windows.items():
        tw = [t for t in trades if t["signal_date"] >= start]
        live = [t for t in tw if LIVE_COMBOS[t["entry_rule"]] == t["exit_rule"]]
        results["signal"][w] = {
            "n_trades_all_combos": len(tw),
            "live_by_strategy": {k[0]: v for k, v in group_stats(live, ["entry_rule"]).items()},
            "live_by_strategy_closed_only": {k[0]: v for k, v in group_stats(live, ["entry_rule"], include_open=False).items()},
            "grid_entry_exit": {f"{k[0]}|{k[1]}": v for k, v in group_stats(tw, ["entry_rule", "exit_rule"]).items()},
            "grid_entry_exit_closed_only": {f"{k[0]}|{k[1]}": v for k, v in group_stats(tw, ["entry_rule", "exit_rule"], include_open=False).items()},
            "by_market_regime": {f"{k[0]}|{k[1]}": v for k, v in group_stats(live, ["entry_rule", "market_regime"]).items()},
            "by_trend_regime": {f"{k[0]}|{k[1]}": v for k, v in group_stats(live, ["entry_rule", "trend_regime"]).items()},
            "by_stock_regime": {f"{k[0]}|{k[1]}": v for k, v in group_stats(live, ["entry_rule", "stock_regime"]).items()},
            "by_sector": {f"{k[0]}|{k[1]}": v for k, v in group_stats(live, ["entry_rule", "sector"]).items()},
            "sector_all_strategies": {k[0]: v for k, v in group_stats(live, ["sector"]).items()},
            "regime_days": dict(defaultdict(int, {})),
        }
        rd = defaultdict(int)
        td = defaultdict(int)
        for dt, r in regimes.items():
            if start <= dt <= end_date:
                rd[r["regime"]] += 1
                td[r["trend"]] += 1
        results["signal"][w]["regime_days"] = dict(rd)
        results["signal"][w]["trend_regime_days"] = dict(td)
        # month-by-month (signal month) for live combos
        results["signal"][w]["by_month"] = {f"{k[0]}|{k[1]}": v for k, v in
                                            group_stats([dict(t, month=t["signal_date"][:7]) for t in live], ["entry_rule", "month"]).items()}
        # MR_V3 diagnostics: ATR bucket x RSI depth, and excluding the single biggest signal day
        mr3 = [t for t in live if t["entry_rule"] == "MR_V3"]
        def atr_bucket(t):
            a = t["atr_pct"] or 0
            return "ATR 3-5%" if a < 5 else ("ATR 5-8%" if a < 8 else "ATR >8%")
        results["signal"][w]["mr_v3_atr_buckets"] = {k[0]: v for k, v in group_stats([dict(t, b=atr_bucket(t)) for t in mr3], ["b"]).items()}
        results["signal"][w]["mr_v3_rsi_depth"] = {k[0]: v for k, v in group_stats([dict(t, b=("RSI(2)=0" if t["rsi2"] == 0 else "RSI(2) 0-5" if t["rsi2"] < 5 else "RSI(2) 5-10")) for t in mr3], ["b"]).items()}
        if mr3:
            big_day = max(set(t["signal_date"] for t in mr3), key=lambda d: sum(1 for t in mr3 if t["signal_date"] == d))
            results["signal"][w]["mr_v3_biggest_day"] = {"date": big_day,
                                                          "on_day": stats([t["ret"] for t in mr3 if t["signal_date"] == big_day]),
                                                          "excluding_day": stats([t["ret"] for t in mr3 if t["signal_date"] != big_day])}
        # every strategy by ATR bucket (volatility of the stock at signal)
        results["signal"][w]["by_atr_bucket"] = {f"{k[0]}|{k[1]}": v for k, v in group_stats([dict(t, b=atr_bucket(t)) for t in live], ["entry_rule", "b"]).items()}

    if not args.no_portfolio:
        print("Running portfolio simulations...", flush=True)
        ind_cache = {t: compute_indicators(d) for t, d in data.items() if t not in ETF_TICKERS and d["dates"][-1] >= end_date}
        data_ok = {t: d for t, d in data.items() if t in ind_cache}
        span = [dt for dt in spy["dates"] if windows[90] <= dt <= end_date]
        signals = precompute_signals(data_ok, ind_cache, span)
        if args.stock_cache and os.path.exists(args.stock_cache):
            stock_cache = json.load(open(args.stock_cache))
            results["stock_cache_source"] = args.stock_cache
        else:
            stock_cache = precompute_stock_cache(data_ok, ind_cache, windows[90])
            results["stock_cache_source"] = "in-sample DB (history before 90d window only)"
        n_valid = {fam: sum(1 for r in stock_cache.values() if r.get(fam) is not None) for fam in ("mr", "mom")}
        print(f"  stock cache (history before {windows[90]}): validated MR stocks={n_valid['mr']}, MOM stocks={n_valid['mom']}", flush=True)
        results["stock_cache_validated"] = n_valid
        port_sets = {
            "LIVE_MR+MOM": [("MR_V3", "Fixed60d"), ("MOM_V3", "Fixed90d")],
            "MR_V3_only": [("MR_V3", "Fixed60d")],
            "MOM_V3_only": [("MOM_V3", "Fixed90d")],
            "MR_V24_14d": [("MR_V24", "Fixed14d")],
            "MR_CONNORS_SMA5": [("MR_CONNORS", "SMA5")],
            "MOM_STRICT_TRAIL": [("MOM_STRICT", "TRAIL10")],
            "BREAKOUT_SMA10": [("BREAKOUT", "SMA10")],
            "MR_V3_10d": [("MR_V3", "Fixed10d")],
            "MR_V3_SMA5": [("MR_V3", "SMA5")],
            "MR_V24_21d": [("MR_V24", "Fixed21d")],
        }
        MC_RUNS = 100
        for w, start in windows.items():
            results["portfolio"][w] = {}
            for name, strat in port_sets.items():
                entry = {}
                for mode in ("live", "deepest"):
                    r = portfolio_sim(data_ok, ind_cache, regimes, spy["dates"], start, end_date, strat, signals,
                                      stock_cache=stock_cache, rank_mode=mode)
                    entry[mode] = {k: v for k, v in r.items() if k not in ("equity_curve",)}
                    entry[mode]["equity_curve"] = r["equity_curve"][::5] + [r["equity_curve"][-1]]
                runs = [portfolio_sim(data_ok, ind_cache, regimes, spy["dates"], start, end_date, strat, signals,
                                      rank_mode="random", seed=s) for s in range(MC_RUNS)]
                entry["random_mc"] = summarize_mc(runs)
                results["portfolio"][w][name] = entry
                print(f"  {w}d {name:18s} live={entry['live']['return_pct']:+6.2f}% (closed {entry['live']['closed_trades']}) "
                      f"deepest={entry['deepest']['return_pct']:+6.2f}%  MC median={entry['random_mc']['median']:+6.2f}% "
                      f"[p10 {entry['random_mc']['p10']:+.1f}, p90 {entry['random_mc']['p90']:+.1f}] pos%={entry['random_mc']['pct_positive']:.0f}", flush=True)
            r = portfolio_sim(data_ok, ind_cache, regimes, spy["dates"], start, end_date, port_sets["LIVE_MR+MOM"], signals,
                              stock_cache=stock_cache, rank_mode="live", use_regime_sizing=False)
            results["portfolio"][w]["LIVE_MR+MOM_noRegimeSizing"] = {"live": {k: v for k, v in r.items() if k not in ("equity_curve",)}}

    # Current open positions (positions.db) marked to market with adjusted closes
    if args.positions_db and os.path.exists(args.positions_db):
        try:
            pconn = sqlite3.connect(args.positions_db)
            rows = pconn.execute("select ticker, entry_date, entry_price, shares, strategy from positions where status='OPEN'").fetchall()
            pconn.close()
            open_pos = []
            for t, ed, ep, sh, strat in rows:
                d = data.get(t)
                if not d:
                    open_pos.append({"ticker": t, "entry_date": ed, "note": "no price data"})
                    continue
                def close_on_or_before(dt):
                    k = max((i for i, x in enumerate(d["dates"]) if x <= dt), default=None)
                    return d["c"][k] if k is not None else None
                last = d["c"][-1]
                e_px = close_on_or_before(ed)
                rec = {"ticker": t, "entry_date": ed, "strategy": strat, "entry_close_adj": round(float(e_px), 2) if e_px else None,
                       "last_close": round(float(last), 2), "since_entry_pct": round((last / e_px - 1) * 100, 1) if e_px else None,
                       "value": round(float(last * sh), 0) if sh else None, "days_held": len([x for x in d["dates"] if x > ed])}
                for w, start in windows.items():
                    p0 = close_on_or_before(start)
                    rec[f"ret_{w}d"] = round((last / p0 - 1) * 100, 1) if p0 else None
                open_pos.append(rec)
            results["open_positions_mtm"] = open_pos
        except Exception as ex:
            results["open_positions_mtm"] = [{"error": str(ex)}]

    json.dump(results, open(os.path.join(args.out, "results.json"), "w"), indent=1, default=str)
    json.dump(trades, open(os.path.join(args.out, "trades.json"), "w"), default=str)
    print(f"Saved to {args.out}/results.json and trades.json", flush=True)


if __name__ == "__main__":
    main()
