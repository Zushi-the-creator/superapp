"""
Sector intelligence — pure logic, no FastAPI.

Powers the /api/v2/sectors endpoint upgrade:
- RRG (Relative Rotation Graph) math: RS-Ratio / RS-Momentum vs SPY + rotation trail
- 11x11 sector ETF correlation matrix
- Per-sector news narratives (Google News RSS + keyword sentiment)
- ticker -> GICS sector store (SQLite, Finnhub profile2 backfill)
- Portfolio impact vs sector leadership

INFORMATIONAL ONLY — nothing here feeds entry/exit signals or composite_score.
A sector-tilt entry factor would need its own walk-forward backtest first.
"""

import json
import math
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional

import pandas as pd

from data_cache import DB_PATH
from atlas_v2.sentiment_analyst import SentimentAnalyzer

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")

# ── Constants ──

SECTORS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Healthcare", "XLI": "Industrials", "XLY": "Consumer Disc",
    "XLP": "Consumer Staples", "XLB": "Materials", "XLU": "Utilities",
    "XLRE": "Real Estate", "XLC": "Communication",
}
SECTOR_NAME_TO_ETF = {name: etf for etf, name in SECTORS.items()}

# Google News queries per sector — sector-name phrasing, NOT ETF tickers
# (RSS results for "XLRE" etc. are garbage; plain-English sector terms work).
SECTOR_NEWS_QUERIES = {
    "XLK": "technology sector stocks",
    "XLF": "bank financial sector stocks",
    "XLE": "energy sector oil gas stocks",
    "XLV": "healthcare pharma sector stocks",
    "XLI": "industrials manufacturing sector stocks",
    "XLY": "consumer discretionary retail stocks",
    "XLP": "consumer staples stocks",
    "XLB": "materials chemicals mining sector",
    "XLU": "utilities sector stocks",
    "XLRE": "real estate REIT sector",
    "XLC": "communication services media stocks",
}

# Moved from api_v2.py (was STOCK_SECTORS inside get_sectors) — seeds ticker_sectors.
STATIC_STOCK_SECTORS = {
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

# Finnhub `finnhubIndustry` -> our 11 GICS names. Exact (lowercased) matches first,
# then keyword heuristics in map_industry_to_gics for strings not listed here.
FINNHUB_TO_GICS = {
    "technology": "Technology", "semiconductors": "Technology", "software": "Technology",
    "computers": "Technology", "electronic equipment & instruments": "Technology",
    "it services": "Technology", "communications equipment": "Technology",
    "technology hardware, storage & peripherals": "Technology",
    "banking": "Financials", "financial services": "Financials", "insurance": "Financials",
    "capital markets": "Financials", "consumer finance": "Financials",
    "diversified financial services": "Financials",
    "energy": "Energy", "oil & gas": "Energy", "energy equipment & services": "Energy",
    "pharmaceuticals": "Healthcare", "biotechnology": "Healthcare",
    "health care equipment & supplies": "Healthcare",
    "health care providers & services": "Healthcare",
    "life sciences tools & services": "Healthcare",
    "machinery": "Industrials", "aerospace & defense": "Industrials",
    "airlines": "Industrials", "industrial conglomerates": "Industrials",
    "electrical equipment": "Industrials", "building": "Industrials",
    "construction & engineering": "Industrials", "road & rail": "Industrials",
    "logistics & transportation": "Industrials", "marine": "Industrials",
    "commercial services & supplies": "Industrials", "professional services": "Industrials",
    "trading companies & distributors": "Industrials", "transportation infrastructure": "Industrials",
    "retail": "Consumer Disc", "automobiles": "Consumer Disc", "auto components": "Consumer Disc",
    "hotels restaurants & leisure": "Consumer Disc", "household durables": "Consumer Disc",
    "leisure products": "Consumer Disc", "textiles apparel & luxury goods": "Consumer Disc",
    "distributors": "Consumer Disc", "diversified consumer services": "Consumer Disc",
    "specialty retail": "Consumer Disc",
    "food products": "Consumer Staples", "beverages": "Consumer Staples",
    "household products": "Consumer Staples", "tobacco": "Consumer Staples",
    "food & staples retailing": "Consumer Staples", "consumer products": "Consumer Staples",
    "personal products": "Consumer Staples",
    "chemicals": "Materials", "metals & mining": "Materials", "packaging": "Materials",
    "paper & forest": "Materials", "construction materials": "Materials",
    "containers & packaging": "Materials",
    "utilities": "Utilities", "electric utilities": "Utilities", "gas utilities": "Utilities",
    "water utilities": "Utilities", "multi-utilities": "Utilities",
    "real estate": "Real Estate", "equity real estate investment trusts (reits)": "Real Estate",
    "real estate management & development": "Real Estate",
    "media": "Communication", "entertainment": "Communication", "internet": "Communication",
    "telecommunication": "Communication", "communications": "Communication",
    "interactive media & services": "Communication", "wireless telecommunication services": "Communication",
    "diversified telecommunication services": "Communication",
}

_GICS_KEYWORD_HEURISTICS = [
    (("semiconductor", "software", "computer", "technology", "electronic"), "Technology"),
    (("bank", "insurance", "financial", "capital market", "asset management"), "Financials"),
    (("oil", "gas", "energy", "drilling", "coal"), "Energy"),
    (("pharma", "biotech", "health", "medical", "life science"), "Healthcare"),
    (("aerospace", "defense", "machinery", "industrial", "airline", "rail",
      "transport", "construction", "engineering", "logistics"), "Industrials"),
    (("retail", "automobile", "auto ", "apparel", "leisure", "hotel", "restaurant"), "Consumer Disc"),
    (("food", "beverage", "staple", "tobacco", "household product"), "Consumer Staples"),
    (("chemical", "mining", "metal", "material", "packaging", "paper"), "Materials"),
    (("utilit",), "Utilities"),
    (("real estate", "reit"), "Real Estate"),
    (("media", "telecom", "communication", "entertainment", "internet"), "Communication"),
]


def map_industry_to_gics(industry: str) -> str:
    """Map a Finnhub finnhubIndustry string to one of our 11 GICS sector names."""
    if not industry:
        return "Unknown"
    low = industry.strip().lower()
    if low in FINNHUB_TO_GICS:
        return FINNHUB_TO_GICS[low]
    for keywords, sector in _GICS_KEYWORD_HEURISTICS:
        if any(kw in low for kw in keywords):
            return sector
    return "Unknown"


# ── Sector metadata + news store (SQLite, same DB file as the OHLCV cache) ──

class SectorStore:
    """ticker -> sector mapping + persisted sector news, in stock_cache.db."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._local = threading.local()
        self._create_tables()
        self._seed_static()

    @property
    def conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _create_tables(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS ticker_sectors (
                ticker TEXT PRIMARY KEY,
                sector TEXT NOT NULL,
                finnhub_industry TEXT,
                source TEXT,
                updated TEXT
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS sector_news (
                etf TEXT PRIMARY KEY,
                payload TEXT,
                updated TEXT
            )
        ''')
        self.conn.commit()

    def _seed_static(self):
        now = datetime.now().isoformat()
        self.conn.executemany(
            "INSERT OR IGNORE INTO ticker_sectors (ticker, sector, finnhub_industry, source, updated) "
            "VALUES (?, ?, NULL, 'static', ?)",
            [(t, s, now) for t, s in STATIC_STOCK_SECTORS.items()],
        )
        self.conn.commit()

    def get_sector(self, ticker: str) -> str:
        row = self.conn.execute(
            "SELECT sector FROM ticker_sectors WHERE ticker = ?", (ticker.upper(),)
        ).fetchone()
        if row:
            return row[0]
        return STATIC_STOCK_SECTORS.get(ticker.upper(), "Unknown")

    def get_all_sectors(self, tickers: List[str]) -> Dict[str, str]:
        return {t: self.get_sector(t) for t in tickers}

    def store_sector(self, ticker: str, sector: str, industry: Optional[str], source: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO ticker_sectors (ticker, sector, finnhub_industry, source, updated) "
            "VALUES (?, ?, ?, ?, ?)",
            (ticker.upper(), sector, industry, source, datetime.now().isoformat()),
        )
        self.conn.commit()

    def unmapped(self, tickers: List[str]) -> List[str]:
        """Tickers with no row in ticker_sectors (Unknown rows count as mapped —
        already fetched, don't re-hit Finnhub for them)."""
        out = []
        for t in {t.upper() for t in tickers}:
            row = self.conn.execute(
                "SELECT 1 FROM ticker_sectors WHERE ticker = ?", (t,)
            ).fetchone()
            if not row:
                out.append(t)
        return sorted(out)

    def load_news(self) -> Dict[str, dict]:
        rows = self.conn.execute("SELECT etf, payload FROM sector_news").fetchall()
        out = {}
        for etf, payload in rows:
            try:
                out[etf] = json.loads(payload)
            except Exception:
                pass
        return out

    def store_news(self, etf: str, payload: dict):
        self.conn.execute(
            "INSERT OR REPLACE INTO sector_news (etf, payload, updated) VALUES (?, ?, ?)",
            (etf, json.dumps(payload), datetime.now().isoformat()),
        )
        self.conn.commit()


# ── RRG math ──

def compute_rrg(
    etf_closes: pd.Series,
    spy_closes: pd.Series,
    ratio_window: int = 63,
    mom_window: int = 10,
    trail_points: int = 8,
    trail_step: int = 5,
) -> dict:
    """Simplified JdK-style RRG coordinates for one sector ETF vs SPY.

    RS-Ratio    = 100 * (etf/spy) / SMA(etf/spy, ratio_window)  -> >100 = outperforming
    RS-Momentum = 100 + %change of RS-Ratio over mom_window days
    Not the full JdK z-score normalization — deterministic and defensible from
    cached daily closes, which is all we need for quadrant placement + trail.
    """
    neutral = {"rs_ratio": 100.0, "rs_momentum": 100.0, "quadrant": "Unknown",
               "leadership_score": 0.0, "trail": []}
    try:
        df = pd.concat(
            [etf_closes.rename("etf"), spy_closes.rename("spy")],
            axis=1, join="inner",
        ).dropna()
    except Exception:
        return neutral

    min_bars = ratio_window + mom_window + (trail_points - 1) * trail_step
    if len(df) < min_bars:
        return neutral

    rs_raw = df["etf"] / df["spy"]
    rs_ratio = 100.0 * rs_raw / rs_raw.rolling(ratio_window).mean()
    rs_mom = 100.0 + (rs_ratio / rs_ratio.shift(mom_window) - 1.0) * 100.0

    trail = []
    last = len(df) - 1
    for k in range(trail_points - 1, -1, -1):  # oldest -> newest
        i = last - k * trail_step
        r, m = rs_ratio.iloc[i], rs_mom.iloc[i]
        if math.isnan(r) or math.isnan(m):
            continue
        trail.append({
            "date": df.index[i].strftime("%Y-%m-%d"),
            "rs_ratio": round(float(r), 2),
            "rs_momentum": round(float(m), 2),
        })

    if not trail:
        return neutral

    ratio, mom = trail[-1]["rs_ratio"], trail[-1]["rs_momentum"]
    if ratio >= 100 and mom >= 100:
        quadrant = "Leading"
    elif ratio >= 100:
        quadrant = "Weakening"
    elif mom >= 100:
        quadrant = "Improving"
    else:
        quadrant = "Lagging"

    return {
        "rs_ratio": ratio,
        "rs_momentum": mom,
        "quadrant": quadrant,
        "leadership_score": round((ratio - 100.0) + 0.5 * (mom - 100.0), 2),
        "trail": trail,
    }


# ── Correlation matrix ──

def compute_correlation_matrix(close_map: Dict[str, pd.Series], window: int = 60) -> Optional[dict]:
    """Pearson correlation of daily returns across sector ETFs (last `window` bars)."""
    import numpy as np

    series = {etf: s.dropna() for etf, s in close_map.items() if s is not None and len(s.dropna()) >= window + 1}
    if len(series) < 2:
        return None

    df = pd.concat(series.values(), axis=1, join="inner")
    df.columns = list(series.keys())
    rets = df.pct_change().dropna().tail(window)
    if len(rets) < 20:
        return None

    mat = np.corrcoef(rets.values.T)
    etfs = list(df.columns)
    matrix = [[round(float(v), 2) for v in row] for row in mat]

    pairs = [
        {"a": etfs[i], "b": etfs[j], "corr": matrix[i][j]}
        for i in range(len(etfs)) for j in range(i + 1, len(etfs))
    ]
    pairs.sort(key=lambda p: -p["corr"])
    return {
        "window_days": window,
        "etfs": etfs,
        "matrix": matrix,
        "high_pairs": pairs[:5],
        "low_pairs": pairs[-5:][::-1],
    }


# ── Sector news ──

_analyzer = SentimentAnalyzer()


def fetch_sector_headlines(etf: str) -> List[str]:
    """Blocking Google News RSS fetch for one sector — caller wraps in a thread."""
    import requests
    from urllib.parse import quote

    query = SECTOR_NEWS_QUERIES.get(etf)
    if not query:
        return []
    try:
        url = (f"https://news.google.com/rss/search?q={quote(query + ' when:2d')}"
               f"&hl=en-US&gl=US&ceid=US:en")
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            return []
        headlines = re.findall(r"<title>(.*?)</title>", resp.text)[2:12]
        return [h.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
                for h in headlines]
    except Exception:
        return []


def score_headline(headline: str) -> float:
    """-1 / 0 / +1 keyword score, same first-match-per-list rule as SentimentAnalyzer.analyze."""
    low = headline.lower()
    neg = any(kw in low for kw in _analyzer.NEGATIVE_KEYWORDS)
    pos = any(kw in low for kw in _analyzer.POSITIVE_KEYWORDS)
    if neg and pos:
        return 0.0
    if neg:
        return -1.0
    if pos:
        return 1.0
    return 0.0


def build_sector_news(etf: str, headlines: List[str]) -> dict:
    scored = [{"title": h, "sentiment": score_headline(h)} for h in headlines]
    for item in scored:
        s = item["sentiment"]
        item["label"] = "POSITIVE" if s > 0.1 else "NEGATIVE" if s < -0.1 else "NEUTRAL"

    pos = sum(1 for i in scored if i["sentiment"] > 0)
    neg = sum(1 for i in scored if i["sentiment"] < 0)
    avg = round(sum(i["sentiment"] for i in scored) / len(scored), 2) if scored else 0.0
    label = "POSITIVE" if avg > 0.1 else "NEGATIVE" if avg < -0.1 else "NEUTRAL"

    # Surface the most opinionated headlines first (|sentiment| desc, stable order)
    top = sorted(scored, key=lambda i: -abs(i["sentiment"]))[:5]

    return {
        "etf": etf,
        "avg_sentiment": avg,
        "label": label,
        "pos_count": pos,
        "neg_count": neg,
        "neutral_count": len(scored) - pos - neg,
        "headlines": top,
        "updated": datetime.now().isoformat(),
    }


def refresh_all_sector_news(store: SectorStore, delay_between: float = 0.5) -> Dict[str, dict]:
    """Blocking: fetch + score + persist news for all 11 sectors. Run in a worker thread."""
    out = {}
    for etf in SECTORS:
        headlines = fetch_sector_headlines(etf)
        payload = build_sector_news(etf, headlines)
        if headlines:  # don't overwrite a good cache with an empty fetch
            store.store_news(etf, payload)
            out[etf] = payload
        time.sleep(delay_between)
    return out


# ── Finnhub sector backfill ──

def fetch_finnhub_sector(ticker: str) -> Optional[dict]:
    """Blocking Finnhub profile2 lookup -> {sector, industry} or None on error.
    Caller is responsible for rate limiting and threading."""
    import requests

    if not FINNHUB_KEY:
        return None
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/stock/profile2",
            params={"symbol": ticker.upper(), "token": FINNHUB_KEY},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        industry = (resp.json() or {}).get("finnhubIndustry", "")
        return {"sector": map_industry_to_gics(industry), "industry": industry or None}
    except Exception:
        return None


# ── Portfolio impact ──

def build_portfolio_impact(
    positions: List[dict],
    price_lookup: Callable[[str], float],
    sector_lookup: Callable[[str], str],
    sector_rows: List[dict],
    corr: Optional[dict],
) -> dict:
    """Portfolio tilt vs sector leadership. sector_rows = per-sector dicts that
    already carry name/etf/quadrant/leadership_score from compute_rrg."""
    by_name = {row["name"]: row for row in sector_rows}

    holdings = []
    total_value = 0.0
    for pos in positions:
        price = price_lookup(pos["ticker"]) or pos["entry_price"]
        value = price * pos["shares"]
        total_value += value
        holdings.append({"ticker": pos["ticker"], "value": value})

    sector_weights: Dict[str, float] = {}
    quadrant_weights = {"leading": 0.0, "improving": 0.0, "weakening": 0.0,
                        "lagging": 0.0, "unknown": 0.0}
    leadership_score = 0.0
    unmapped_count = 0

    for h in holdings:
        sector = sector_lookup(h["ticker"])
        row = by_name.get(sector)
        quadrant = row["quadrant"] if row else "Unknown"
        weight = (h["value"] / total_value * 100.0) if total_value else 0.0

        h.update({
            "sector": sector,
            "etf": row["etf"] if row else None,
            "weight": round(weight, 1),
            "quadrant": quadrant,
        })
        del h["value"]

        sector_weights[sector] = sector_weights.get(sector, 0.0) + weight
        quadrant_weights[quadrant.lower() if quadrant.lower() in quadrant_weights else "unknown"] += weight
        if row:
            leadership_score += (weight / 100.0) * row.get("leadership_score", 0.0)
        if sector == "Unknown":
            unmapped_count += 1

    quadrant_weights = {k: round(v, 1) for k, v in quadrant_weights.items()}

    hhi = int(round(sum(w ** 2 for w in sector_weights.values())))
    concentration_label = "LOW" if hhi < 1500 else "MODERATE" if hhi <= 2500 else "HIGH"

    # Mean pairwise correlation among ETFs of held sectors
    avg_corr = None
    if corr and corr.get("matrix"):
        held_etfs = [SECTOR_NAME_TO_ETF[s] for s in sector_weights
                     if s in SECTOR_NAME_TO_ETF and SECTOR_NAME_TO_ETF[s] in corr["etfs"]]
        idx = {etf: corr["etfs"].index(etf) for etf in held_etfs}
        vals = [corr["matrix"][idx[a]][idx[b]]
                for i, a in enumerate(held_etfs) for b in held_etfs[i + 1:]]
        if vals:
            avg_corr = round(sum(vals) / len(vals), 2)

    flags = []
    lagging_pct = quadrant_weights["lagging"] + quadrant_weights["weakening"]
    if quadrant_weights["lagging"] >= 25:
        flags.append(f"{quadrant_weights['lagging']:.0f}% of portfolio is in Lagging sectors")
    elif lagging_pct >= 40:
        flags.append(f"{lagging_pct:.0f}% of portfolio is in Weakening/Lagging sectors")
    for sector, weight in sorted(sector_weights.items(), key=lambda x: -x[1]):
        if sector != "Unknown" and weight > 30:
            flags.append(f"{sector} is {weight:.0f}% of portfolio (>30% concentration cap)")
    if avg_corr is not None and avg_corr >= 0.7:
        flags.append(f"Held sectors avg correlation {avg_corr:.2f} — low diversification")
    if unmapped_count:
        flags.append(f"{unmapped_count} holding(s) unmapped (Unknown sector)")

    return {
        "holdings": sorted(holdings, key=lambda h: -h["weight"]),
        "quadrant_weights": quadrant_weights,
        "leadership_score": round(leadership_score, 2),
        "concentration_hhi": hhi,
        "concentration_label": concentration_label,
        "avg_held_sector_correlation": avg_corr,
        "flags": flags,
    }
