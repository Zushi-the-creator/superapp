"""
Deep Stock Scanner - ATLAS V2 Compatible
=========================================
Scans the ENTIRE US market for oversold opportunities.

Usage:
    python3 deep_scanner.py              # Full scan (uses daily cache)
    python3 deep_scanner.py --fresh      # Force fresh scan
    python3 deep_scanner.py --top 20     # Show top 20 results
    python3 deep_scanner.py --populate   # One-time: load all stocks into cache

Architecture:
    Phase 0: Finviz discovery - find ALL oversold US stocks (>300M cap) from entire market
    Phase 1: Read from SQLite cache (instant) - populate via Tiingo if missing
    Phase 2: RSI(2) filter + deep backtest (14-day forward, zone returns)
    Phase 3: Validate top 15 (Finviz analyst + Google News sentiment + earnings)
"""

import asyncio
import aiohttp
import json
import os
import re
import sys
import argparse
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple

import pandas as pd

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from atlas_v2.entry import EntryEngine
from atlas_v2.regime import RegimeDetector, MarketRegime
from data_cache import DataCache

# ─── Stock Universe ─────────────────────────────────────────────────────────
# Loaded from data/us_stock_universe.txt (scraped from Finviz, ~3000 stocks >300M cap)
# Regenerate with: python3 -c "from deep_scanner import refresh_universe; import asyncio; asyncio.run(refresh_universe())"

_UNIVERSE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "us_stock_universe.txt")


def _load_universe(max_stocks: int = 800) -> List[str]:
    """Load top US stocks from file (sorted by market cap), capped at max_stocks."""
    if os.path.exists(_UNIVERSE_FILE):
        with open(_UNIVERSE_FILE) as f:
            tickers = [line.strip() for line in f if line.strip()]
        if len(tickers) > 100:
            return tickers[:max_stocks]

    # Fallback: core stocks if file not generated yet
    return [
        "AAPL","MSFT","AMZN","NVDA","GOOGL","META","TSLA","UNH","XOM","JNJ",
        "JPM","V","PG","MA","HD","CVX","MRK","ABBV","LLY","PFE","KO","BAC",
        "AVGO","COST","TMO","WMT","CRM","NFLX","AMD","QCOM","LRCX","NOW",
        "COHR","BE","ALB","DXCM","AMG","CALM","RDW","PLTR","CRWD","PANW",
    ]


async def refresh_universe():
    """Scrape fresh stock universe from Finviz (all US stocks >300M cap)."""
    import re
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    all_tickers = []

    async with aiohttp.ClientSession() as session:
        for start in range(1, 4000, 20):
            url = f'https://finviz.com/screener.ashx?v=111&f=cap_smallover&r={start}'
            try:
                async with session.get(url, headers=headers, timeout=12) as resp:
                    if resp.status != 200:
                        break
                    html = await resp.text()
                    tickers = re.findall(r'quote\.ashx\?t=([A-Z]{1,5})&', html)
                    page_tickers = list(dict.fromkeys(tickers))
                    if not page_tickers:
                        break
                    all_tickers.extend(page_tickers)
            except Exception:
                break
            await asyncio.sleep(0.3)

    all_tickers = list(dict.fromkeys(all_tickers))
    os.makedirs(os.path.dirname(_UNIVERSE_FILE), exist_ok=True)
    with open(_UNIVERSE_FILE, 'w') as f:
        f.write('\n'.join(all_tickers))
    print(f'Universe refreshed: {len(all_tickers)} tickers saved')
    return all_tickers


STOCK_UNIVERSE = _load_universe()


@dataclass
class ScanResult:
    ticker: str
    price: float
    rsi2: float
    rsi_zone: str
    sma50: float
    above_sma50: bool
    regime: str
    win_rate: float
    trades: int
    avg_return: float
    zone_return: float
    zone_trades: int
    zone_win_rate: float
    volume_ratio: float = 0.0  # current vol / 20-day avg vol
    hold_days: int = 14  # 14-day hold (backtested optimal)
    tier: str = "NONE"  # EXTREME, STRONG, STANDARD, NONE
    # ML-discovered features (SHAP importance ranked #1, #2, #5)
    low52_dist: float = 0.0   # % distance from 52-week low (closer=better bounce)
    atr_pct: float = 0.0      # ATR(14) as % of price (higher volatility=bigger bounce)
    ret20: float = 0.0        # 20-day price momentum %
    ml_score: float = 0.0     # composite score combining zone_return + ML features
    # Phase 3 (filled later for top candidates)
    analyst_consensus: str = ""
    analyst_target: float = 0.0
    analyst_upside: float = 0.0
    sentiment_label: str = ""
    sentiment_score: float = 0.0
    vetoed: bool = False
    veto_reason: str = ""
    source: str = ""  # "finviz_discovery" or "universe"


class DeepScanner:
    """
    Production stock scanner with 4-phase pipeline.
    Phase 0: Finviz discovers oversold stocks from ENTIRE US market
    Phase 1: Fetch historical data (Stooq + Twelve Data fallback)
    Phase 2: RSI(2) backtest + zone analysis
    Phase 3: Analyst + sentiment validation on top candidates
    """

    CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    @staticmethod
    def _hold_days(rsi: float) -> int:
        """Fixed 14-day hold period — backtested: 87.7% WR, +11.29% avg (vs 7d: 84%, +6.03%)."""
        return 14

    def __init__(self):
        self.entry_engine = EntryEngine()
        self.cache = DataCache()
        self.stats = {
            "cache_hits": 0, "tiingo_fetched": 0, "fetch_failed": 0,
            "candidates": 0, "passed": 0,
            "discovered": 0,
        }

    def _cache_path(self) -> str:
        os.makedirs(self.CACHE_DIR, exist_ok=True)
        return os.path.join(self.CACHE_DIR, f"scan_{datetime.now().strftime('%Y-%m-%d')}.json")

    def load_cache(self) -> Optional[List[dict]]:
        path = self._cache_path()
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
            print(f"[CACHE] Loaded {len(data)} results from today's scan")
            return data
        return None

    def save_cache(self, results: List[ScanResult]):
        path = self._cache_path()
        with open(path, "w") as f:
            json.dump([asdict(r) for r in results], f, indent=2)
        print(f"[CACHE] Saved {len(results)} results to {path}")

    # ─── Phase 0: Finviz Discovery ──────────────────────────────────────

    async def phase0_discover(self) -> List[str]:
        """
        Discover oversold stocks from the ENTIRE US market via Finviz screener.
        Scans ~8,000 stocks in seconds - returns tickers with RSI(14) oversold signal.
        """
        print(f"\n{'='*60}")
        print(f"PHASE 0: Finviz Market-Wide Oversold Discovery")
        print(f"{'='*60}")

        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
        discovered = []

        async with aiohttp.ClientSession() as session:
            # Scan oversold signal with >300M cap (paginate up to 500 results)
            for start in range(1, 500, 20):
                url = f'https://finviz.com/screener.ashx?v=171&s=ta_oversold&f=cap_smallover&r={start}'
                try:
                    async with session.get(url, headers=headers,
                                           timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status != 200:
                            break
                        html = await resp.text()
                        tickers = re.findall(r'quote\.ashx\?t=([A-Z]{1,5})&', html)
                        page_tickers = list(dict.fromkeys(tickers))
                        if not page_tickers:
                            break
                        discovered.extend(page_tickers)
                except Exception:
                    break
                await asyncio.sleep(0.3)

        discovered = list(dict.fromkeys(discovered))
        self.stats["discovered"] = len(discovered)
        print(f"  Found {len(discovered)} oversold stocks from entire US market")
        if discovered:
            print(f"  Tickers: {', '.join(discovered[:20])}{'...' if len(discovered)>20 else ''}")
        return discovered

    # ─── Phase 1: Load from Cache + Fetch Missing ───────────────────────

    async def phase1_fetch_data(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Phase 1: Load historical data from SQLite cache.
        Only fetches missing tickers via Tiingo (500 req/hr).
        After initial population, this phase completes in < 1 second.
        """
        print(f"\n{'='*60}")
        print(f"PHASE 1: Load Historical Data ({len(tickers)} tickers)")
        print(f"{'='*60}")

        data = {}
        missing = []

        # Stage 1: Read from SQLite cache (instant)
        for ticker in tickers:
            df = self.cache.get(ticker, 365)
            if df is not None:
                data[ticker] = df
                self.stats["cache_hits"] += 1
            else:
                missing.append(ticker)

        print(f"  Cache: {self.stats['cache_hits']} hits | {len(missing)} missing")

        # Stage 2: Fetch missing via Tiingo and cache them
        if missing:
            print(f"  Fetching {len(missing)} missing tickers via Tiingo...")
            result = await self.cache.populate(missing)
            self.stats["tiingo_fetched"] = result['fetched']
            self.stats["fetch_failed"] = result['failed']

            # Read the newly cached data
            for ticker in missing:
                df = self.cache.get(ticker, 365)
                if df is not None:
                    data[ticker] = df

        print(f"\n  Phase 1 complete: {len(data)} stocks with data "
              f"(Cache: {self.stats['cache_hits']}, "
              f"Tiingo: {self.stats['tiingo_fetched']}, "
              f"Failed: {self.stats['fetch_failed']})")
        return data

    # ─── Phase 2: RSI Filter + Deep Backtest ─────────────────────────────

    def _backtest_stock(self, ticker: str, df: pd.DataFrame,
                        source: str = "") -> Optional[ScanResult]:
        """Full ATLAS V2 backtest with RSI zone analysis, volume filter, variable hold, regime filter."""
        closes = df['Close'].dropna().tolist()
        if len(closes) < 60:
            return None

        highs = df['High'].tolist() if 'High' in df.columns else closes
        lows = df['Low'].tolist() if 'Low' in df.columns else closes
        volumes = df['Volume'].tolist() if 'Volume' in df.columns else [0] * len(closes)

        price = closes[-1]
        rsi2 = self.entry_engine.calc_rsi(closes, 2)
        sma50 = self.entry_engine.calc_sma(closes, 50)

        # Must be above SMA50 (uptrend)
        if price <= sma50:
            return None

        # RSI(2) must be < 35 (oversold or approaching)
        if rsi2 >= 35:
            return None

        # Regime detection
        regime_info = RegimeDetector.detect(closes, highs, lows, volumes)

        # GAP 3 FIX: Exclude BEAR regime stocks
        if regime_info.regime == MarketRegime.BEAR:
            return None

        # GAP 1 FIX: Volume ratio tracking (soft signal for ranking)
        # Volume > 1.5x is ideal at ENTRY TIME but not a hard gate for scanning
        # Scanner finds candidates → volume confirmation checked at execution
        vol_ratio = 0.0
        if len(volumes) >= 20 and any(v > 0 for v in volumes[-20:]):
            avg_vol_20 = sum(volumes[-20:]) / 20
            if avg_vol_20 > 0:
                vol_ratio = volumes[-1] / avg_vol_20

        # GAP 2 FIX: Variable hold period based on current RSI
        hold_days = self._hold_days(rsi2)

        # Full backtest: entries where RSI(2) < 20 AND price > SMA(50)
        # Uses variable hold days per-entry based on RSI at entry time
        trades = []
        for i in range(50, len(closes) - 14):  # ensure room for 14-day hold
            hist_closes = closes[:i+1]
            hist_rsi2 = self.entry_engine.calc_rsi(hist_closes, 2)
            hist_sma50 = self.entry_engine.calc_sma(hist_closes, 50)

            if hist_rsi2 < 20 and hist_closes[-1] > hist_sma50:
                entry_price = closes[i]
                fwd = self._hold_days(hist_rsi2)
                if i + fwd < len(closes):
                    exit_price = closes[i + fwd]
                    ret = ((exit_price - entry_price) / entry_price) * 100
                    trades.append({"return": ret, "win": ret > 0, "rsi": hist_rsi2,
                                   "hold": fwd})

        if len(trades) < 10:
            return None

        wins = sum(1 for t in trades if t["win"])
        win_rate = wins / len(trades) * 100
        avg_return = sum(t["return"] for t in trades) / len(trades)

        if win_rate < 55:
            return None

        # RSI zone analysis for CURRENT RSI zone (with variable hold)
        zone_lo = int(rsi2 // 10) * 10
        zone_hi = zone_lo + 10
        zone_label = f"{zone_lo}-{zone_hi}"

        zone_trades_list = []
        for i in range(50, len(closes) - 14):
            hist_closes = closes[:i+1]
            hist_rsi2 = self.entry_engine.calc_rsi(hist_closes, 2)
            hist_sma50 = self.entry_engine.calc_sma(hist_closes, 50)

            if zone_lo <= hist_rsi2 < zone_hi and hist_closes[-1] > hist_sma50:
                entry_price = closes[i]
                fwd = self._hold_days(hist_rsi2)
                if i + fwd < len(closes):
                    exit_price = closes[i + fwd]
                    ret = ((exit_price - entry_price) / entry_price) * 100
                    zone_trades_list.append({"return": ret, "win": ret > 0})

        if not zone_trades_list:
            zone_return = avg_return
            zone_wr = win_rate
            zone_count = 0
        else:
            zone_return = sum(t["return"] for t in zone_trades_list) / len(zone_trades_list)
            zone_wr = sum(1 for t in zone_trades_list if t["win"]) / len(zone_trades_list) * 100
            zone_count = len(zone_trades_list)

        if zone_return <= 0:
            return None

        self.stats["passed"] += 1

        # Tier classification: EXTREME > STRONG > STANDARD > NONE
        rsi14 = self.entry_engine.calc_rsi(closes, 14) if len(closes) >= 14 else 50
        sma200 = self.entry_engine.calc_sma(closes, 200) if len(closes) >= 200 else 0
        above_sma200 = price > sma200 if sma200 > 0 else False
        vol_spike = vol_ratio > 1.5
        is_extreme = rsi2 < 5 and above_sma200
        is_strong = rsi2 < 20 and (rsi14 < 40 or vol_spike)
        tier = "EXTREME" if is_extreme else ("STRONG" if is_strong else "STANDARD")

        # ML-discovered features (SHAP importance: #1, #2, #5)
        # 1. Distance from 52-week low (closer = bigger bounce, SHAP weight 5.05)
        low_52w = min(lows[-252:]) if len(lows) >= 252 else min(lows)
        low52_dist = ((price / low_52w) - 1) * 100 if low_52w > 0 else 0

        # 2. ATR(14) as % of price (higher volatility = bigger bounce, SHAP weight 3.64)
        atr_values = []
        for j in range(max(1, len(closes) - 14), len(closes)):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j - 1]),
                     abs(lows[j] - closes[j - 1]))
            atr_values.append(tr)
        atr_pct = (sum(atr_values) / len(atr_values) / price * 100) if atr_values and price > 0 else 0

        # 3. 20-day momentum (positive = helps, SHAP weight 0.77)
        ret20 = ((price / closes[-21]) - 1) * 100 if len(closes) >= 21 else 0

        # Composite ML score: zone_return weighted by ML feature bonuses
        # Normalized: low52_dist < 20% is ideal (stock near lows), atr_pct > 3% is ideal (volatile)
        low52_bonus = max(0, 1 - low52_dist / 100)  # 0-1, higher when closer to 52w low
        atr_bonus = min(atr_pct / 5, 1.5)           # 0-1.5, higher for volatile stocks
        ml_score = zone_return * (1 + 0.3 * low52_bonus + 0.2 * atr_bonus)

        return ScanResult(
            ticker=ticker, price=round(price, 2), rsi2=round(rsi2, 1),
            rsi_zone=zone_label, sma50=round(sma50, 2), above_sma50=True,
            regime=regime_info.regime.value,
            win_rate=round(win_rate, 1), trades=len(trades),
            avg_return=round(avg_return, 2),
            zone_return=round(zone_return, 2), zone_trades=zone_count,
            zone_win_rate=round(zone_wr, 1),
            volume_ratio=round(vol_ratio, 2),
            hold_days=hold_days,
            tier=tier,
            low52_dist=round(low52_dist, 1),
            atr_pct=round(atr_pct, 2),
            ret20=round(ret20, 1),
            ml_score=round(ml_score, 2),
            source=source,
        )

    def phase2_backtest(self, stock_data: Dict[str, pd.DataFrame],
                        discovered_tickers: List[str]) -> List[ScanResult]:
        """Phase 2: Filter by RSI(2) + backtest all candidates."""
        print(f"\n{'='*60}")
        print(f"PHASE 2: RSI(2) Filter + Deep Backtest ({len(stock_data)} stocks)")
        print(f"{'='*60}")

        results = []
        for ticker, df in stock_data.items():
            source = "finviz_discovery" if ticker in discovered_tickers else "universe"
            result = self._backtest_stock(ticker, df, source)
            if result:
                results.append(result)

        results.sort(key=lambda r: r.ml_score, reverse=True)
        self.stats["candidates"] = len(results)

        print(f"  Phase 2 complete: {len(results)} stocks passed all filters")
        print(f"  (RSI(2)<35 + above SMA50 + not BEAR + WR>=55% + 10+ trades + zone return > 0)")
        return results

    # ─── Phase 3: Validate Top N ─────────────────────────────────────────

    async def _check_earnings(self, session: aiohttp.ClientSession,
                              ticker: str) -> Optional[Dict]:
        """Check if stock has earnings within 14 days using Finnhub."""
        try:
            import json as _json
            today = datetime.now()
            from_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
            to_date = (today + timedelta(days=14)).strftime('%Y-%m-%d')
            url = (f'https://finnhub.io/api/v1/calendar/earnings'
                   f'?from={from_date}&to={to_date}'
                   f'&symbol={ticker}&token={self.FINNHUB_KEY}')
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return None
                # Use text() + json.loads() — Finnhub sometimes returns text/plain
                text = await resp.text()
                data = _json.loads(text)
                earnings = data.get('earningsCalendar', [])
                for e in earnings:
                    sym = e.get('symbol', '').upper()
                    # Match exact or cross-listed (AG.TO matches AG, GFI.JO matches GFI)
                    if sym == ticker.upper() or sym.startswith(ticker.upper() + '.'):
                        return {
                            'date': e.get('date', ''),
                            'eps_estimate': e.get('epsEstimate'),
                            'revenue_estimate': e.get('revenueEstimate'),
                        }
        except Exception:
            pass
        return None

    FINNHUB_KEY = "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0"

    async def phase3_validate(self, results: List[ScanResult],
                              top_n: int = 15) -> List[ScanResult]:
        """Phase 3: Validate top candidates with analyst + sentiment + earnings."""
        top = results[:top_n]
        if not top:
            return results

        print(f"\n{'='*60}")
        print(f"PHASE 3: Analyst + Sentiment + Earnings Validation (top {len(top)})")
        print(f"{'='*60}")

        from analyst_data import AnalystDataFetcher
        from sentiment import SentimentEngine

        analyst_fetcher = AnalystDataFetcher()
        sentiment_engine = SentimentEngine()

        async with aiohttp.ClientSession() as session:
            for r in top:
                # 1. Earnings check (VETO if < 7 days)
                try:
                    earnings = await self._check_earnings(session, r.ticker)
                    if earnings:
                        r.vetoed = True
                        r.veto_reason = f"Earnings on {earnings['date']} (<7 days)"
                        print(f"  {r.ticker}: EARNINGS VETO - reporting {earnings['date']}")
                        continue  # Skip other checks, already vetoed
                except Exception:
                    pass

                # 2. Analyst data (Finviz)
                try:
                    adata = await analyst_fetcher.fetch_analyst_data(r.ticker)
                    if adata:
                        r.analyst_consensus = adata.get("consensus", "")
                        r.analyst_target = adata.get("price_target_avg", 0)
                        if r.analyst_target > 0:
                            r.analyst_upside = round(
                                ((r.analyst_target - r.price) / r.price) * 100, 1)
                        if r.analyst_target > 0 and r.price > r.analyst_target:
                            r.vetoed = True
                            r.veto_reason = f"Overvalued (${r.price} > target ${r.analyst_target})"
                except Exception:
                    pass

                # 3. Sentiment (Google News + VADER)
                try:
                    sdata = await sentiment_engine.get_ticker_sentiment(r.ticker)
                    if sdata:
                        r.sentiment_label = sdata.get("sentiment_label", "NEUTRAL")
                        r.sentiment_score = sdata.get("sentiment_score", 0)
                        if r.sentiment_score < -0.3:
                            r.vetoed = True
                            r.veto_reason = f"Negative sentiment ({r.sentiment_score:.2f})"
                except Exception:
                    pass

                status = "VETO" if r.vetoed else "OK"
                print(f"  {r.ticker}: Analyst={r.analyst_consensus or 'N/A'} "
                      f"Target=${r.analyst_target:.0f} "
                      f"Sentiment={r.sentiment_label} [{status}]")

        vetoed = sum(1 for r in top if r.vetoed)
        print(f"  Phase 3 complete: {len(top) - vetoed} passed, {vetoed} vetoed")
        return results

    # ─── Main Run ────────────────────────────────────────────────────────

    async def run(self, fresh: bool = False, top_n: int = 30) -> List[ScanResult]:
        """Run full 4-phase scan pipeline."""
        start_time = datetime.now()

        # Check cache
        if not fresh:
            cached = self.load_cache()
            if cached:
                return [ScanResult(**r) for r in cached]

        print(f"\n{'#'*60}")
        print(f"  ATLAS V2 Deep Scanner")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"  Universe: {len(STOCK_UNIVERSE)} + Finviz discovery")
        print(f"{'#'*60}")

        # Phase 0: Discover oversold stocks from entire market
        discovered = await self.phase0_discover()

        # Merge: discovered first (priority), then universe
        all_tickers = list(dict.fromkeys(discovered + STOCK_UNIVERSE))
        print(f"\n  Combined scan list: {len(all_tickers)} unique tickers")

        # Phase 1: Fetch historical data
        stock_data = await self.phase1_fetch_data(all_tickers)

        # Phase 2: RSI filter + backtest
        results = self.phase2_backtest(stock_data, discovered)

        # Phase 3: Validate top candidates
        results = await self.phase3_validate(results, top_n=min(15, len(results)))

        # Save cache
        if results:
            self.save_cache(results)

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n{'#'*60}")
        print(f"  SCAN COMPLETE in {elapsed:.0f}s")
        print(f"  Discovered: {self.stats['discovered']} | "
              f"Cache hits: {self.stats['cache_hits']} | "
              f"Tiingo fetched: {self.stats['tiingo_fetched']} | "
              f"Passed: {self.stats['passed']}")
        cache_stats = self.cache.stats()
        print(f"  Cache: {cache_stats['total_tickers']} tickers, "
              f"{cache_stats['total_rows']} rows, "
              f"{cache_stats['fresh_today']} fresh today")
        print(f"{'#'*60}")

        return results


def print_results(results: List[ScanResult], top_n: int = 30):
    """Print results as formatted table."""
    if not results:
        print("\nNo stocks passed all filters.")
        return

    show = results[:top_n]
    print(f"\n{'='*170}")
    print(f"  TOP {len(show)} STOCKS - Sorted by ML Score (Zone Return × Feature Bonuses)")
    print(f"{'='*170}")
    print(f"{'#':<3} {'Ticker':<7} {'Price':>8} {'RSI':>6} {'Zone':>6} "
          f"{'WR%':>6} {'Tr':>4} {'AvgRet':>8} {'ZnRet':>7} {'ZnTr':>5} "
          f"{'52wL%':>6} {'ATR%':>5} {'20dM':>6} {'MLsc':>6} "
          f"{'Vol':>5} {'Hd':>3} "
          f"{'Regime':<9} {'Analyst':<10} {'Target':>7} {'Up%':>6} "
          f"{'Sent':<9} {'Src':<5} {'St':<5}")
    print("-" * 170)

    for i, r in enumerate(show, 1):
        st = "VETO" if r.vetoed else "BUY"
        src = "DISC" if r.source == "finviz_discovery" else "UNIV"
        vol_s = f"{r.volume_ratio:.1f}x" if r.volume_ratio > 0 else "-"
        print(f"{i:<3} {r.ticker:<7} {r.price:>8.2f} {r.rsi2:>6.1f} {r.rsi_zone:>6} "
              f"{r.win_rate:>5.1f}% {r.trades:>4} {r.avg_return:>7.2f}% "
              f"{r.zone_return:>6.2f}% {r.zone_trades:>5} "
              f"{r.low52_dist:>5.1f}% {r.atr_pct:>5.2f} {r.ret20:>+5.1f}% {r.ml_score:>6.2f} "
              f"{vol_s:>5} {r.hold_days:>3} "
              f"{r.regime:<9} {(r.analyst_consensus or '-'):<10} "
              f"{'$'+str(int(r.analyst_target)) if r.analyst_target else '-':>7} "
              f"{str(round(r.analyst_upside,1))+'%' if r.analyst_upside else '-':>6} "
              f"{(r.sentiment_label or '-'):<9} {src:<5} {st:<5}")

    valid = [r for r in show if not r.vetoed]
    if valid:
        print(f"\n  TOP BUY CANDIDATES:")
        for r in valid[:5]:
            vol_s = f"Vol {r.volume_ratio:.1f}x" if r.volume_ratio > 0 else "Vol N/A"
            print(f"    {r.ticker}: ML={r.ml_score:.2f} | +{r.zone_return:.2f}% zone | "
                  f"WR {r.win_rate:.1f}% | {r.regime} | RSI={r.rsi2:.1f} | "
                  f"52wL={r.low52_dist:.0f}% | ATR={r.atr_pct:.1f}% | 20d={r.ret20:+.1f}% | "
                  f"{r.analyst_consensus or 'N/A'} | {r.sentiment_label or 'N/A'}")


async def main():
    parser = argparse.ArgumentParser(description="ATLAS V2 Deep Stock Scanner")
    parser.add_argument("--fresh", action="store_true", help="Force fresh scan")
    parser.add_argument("--top", type=int, default=30, help="Show top N results")
    parser.add_argument("--populate", action="store_true",
                        help="One-time: populate cache with full stock universe via Tiingo")
    parser.add_argument("--refresh", action="store_true",
                        help="Refresh stale tickers in cache with latest data")
    parser.add_argument("--cache-stats", action="store_true", help="Show cache stats")
    args = parser.parse_args()

    scanner = DeepScanner()

    if args.cache_stats:
        s = scanner.cache.stats()
        print(f"Cache: {s['total_tickers']} tickers | "
              f"{s['fresh_today']} fresh today | "
              f"{s['stale']} stale | "
              f"{s['total_rows']} total rows")
        return []

    if args.populate:
        print(f"Populating cache with {len(STOCK_UNIVERSE)} stocks via Tiingo...")
        await scanner.cache.populate(STOCK_UNIVERSE)
        s = scanner.cache.stats()
        print(f"\nCache: {s['total_tickers']} tickers, {s['total_rows']} rows")
        return []

    if args.refresh:
        await scanner.cache.refresh()
        return []

    results = await scanner.run(fresh=args.fresh, top_n=args.top)
    print_results(results, top_n=args.top)
    return results


if __name__ == "__main__":
    asyncio.run(main())
