"""
ATLAS M1 — Momentum/Breakout Scanner
=====================================
Finds stocks in Stage 2 uptrends with acceleration signals.
Based on Minervini SEPA + Jegadeesh-Titman momentum research.

Entry: Trend template (6 rules) + acceleration (20d ret >15%, vol >1.5x)
Exit: Trailing stop -10% from peak, hard stop -12%, MA breakdown
"""

import os
import sys
import json
import time
import asyncio
import aiohttp
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_cache import DataCache

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


@dataclass
class MomentumSignal:
    ticker: str
    price: float
    # Trend template
    above_sma50: bool
    above_sma150: bool
    above_sma200: bool
    sma_stacked: bool  # 50 > 150 > 200
    pct_from_high: float  # % from 52-week high (should be > -25)
    pct_from_low: float   # % from 52-week low (should be > 30)
    trend_score: int  # How many of the 6 trend rules pass (0-6)
    # Acceleration
    ret_5d: float
    ret_20d: float
    ret_60d: float
    volume_ratio: float
    # Quality
    atr_pct: float
    atr_squeeze: float  # Current ATR / 50d avg ATR (< 0.7 = contracting)
    # Scoring
    momentum_score: float  # Composite ranking score
    # Validation (filled in Phase 3)
    analyst_consensus: str = ""
    analyst_target: float = 0
    sentiment_label: str = ""
    sentiment_score: float = 0
    vetoed: bool = False
    veto_reason: str = ""


class MomentumScanner:
    """Scan for momentum breakout opportunities."""

    FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0")

    def __init__(self):
        self.cache = DataCache()

    def scan_stock(self, ticker: str, df: pd.DataFrame) -> Optional[MomentumSignal]:
        """Check if a stock passes the Minervini Trend Template + acceleration."""
        df = df.dropna(subset=['Close'])
        closes = df['Close'].tolist()
        if len(closes) < 252:  # Need 1yr for 52-week high/low
            return None

        highs = df['High'].tolist() if 'High' in df.columns else closes
        lows = df['Low'].tolist() if 'Low' in df.columns else closes
        volumes = df['Volume'].tolist() if 'Volume' in df.columns else [0] * len(closes)

        price = closes[-1]
        if price < 10:
            return None

        # Moving averages
        n = len(closes)
        sma50 = sum(closes[-50:]) / 50 if n >= 50 else 0
        sma150 = sum(closes[-150:]) / 150 if n >= 150 else 0
        sma200 = sum(closes[-200:]) / 200 if n >= 200 else 0

        # 52-week high/low
        high_52w = max(highs[-252:])
        low_52w = min(lows[-252:])
        pct_from_high = ((price / high_52w) - 1) * 100 if high_52w > 0 else -100
        pct_from_low = ((price / low_52w) - 1) * 100 if low_52w > 0 else 0

        # Trend template (6 rules)
        above_sma50 = price > sma50 if sma50 > 0 else False
        above_sma150 = price > sma150 if sma150 > 0 else False
        above_sma200 = price > sma200 if sma200 > 0 else False
        sma_stacked = (sma50 > sma150 > sma200) if (sma50 > 0 and sma150 > 0 and sma200 > 0) else False
        near_high = pct_from_high > -25
        above_low = pct_from_low > 30

        trend_score = sum([above_sma50, above_sma150, above_sma200, sma_stacked, near_high, above_low])

        # Must pass ALL 6 trend rules
        if trend_score < 6:
            return None

        # Momentum (returns)
        ret_5d = ((closes[-1] / closes[-6]) - 1) * 100 if n >= 6 else 0
        ret_20d = ((closes[-1] / closes[-21]) - 1) * 100 if n >= 21 else 0
        ret_60d = ((closes[-1] / closes[-61]) - 1) * 100 if n >= 61 else 0

        # Acceleration trigger: 20d return > 15%
        if ret_20d < 15:
            return None

        # Volume ratio
        avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 and any(v > 0 for v in volumes[-20:]) else 0
        vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 0

        # Volume confirmation: > 1.5x average
        if vol_ratio < 1.5:
            return None

        # ATR
        atr_vals = []
        for j in range(max(1, n - 14), n):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j-1]),
                     abs(lows[j] - closes[j-1]))
            atr_vals.append(tr)
        atr14 = sum(atr_vals) / len(atr_vals) if atr_vals else 0
        atr_pct = (atr14 / price * 100) if price > 0 else 0

        # ATR squeeze (current ATR vs 50-day avg ATR)
        atr_50_vals = []
        for j in range(max(1, n - 50), n):
            tr = max(highs[j] - lows[j],
                     abs(highs[j] - closes[j-1]),
                     abs(lows[j] - closes[j-1]))
            atr_50_vals.append(tr)
        atr_50_avg = sum(atr_50_vals) / len(atr_50_vals) if atr_50_vals else atr14
        atr_squeeze = atr14 / atr_50_avg if atr_50_avg > 0 else 1.0

        # Composite momentum score
        # Higher momentum + higher volume + tighter squeeze = better
        squeeze_bonus = max(0, (1 - atr_squeeze)) * 2  # 0-1, higher when squeezed
        momentum_score = ret_20d * vol_ratio * (1 + squeeze_bonus)

        return MomentumSignal(
            ticker=ticker, price=round(price, 2),
            above_sma50=above_sma50, above_sma150=above_sma150,
            above_sma200=above_sma200, sma_stacked=sma_stacked,
            pct_from_high=round(pct_from_high, 1),
            pct_from_low=round(pct_from_low, 1),
            trend_score=trend_score,
            ret_5d=round(ret_5d, 2), ret_20d=round(ret_20d, 2),
            ret_60d=round(ret_60d, 2), volume_ratio=round(vol_ratio, 2),
            atr_pct=round(atr_pct, 2), atr_squeeze=round(atr_squeeze, 2),
            momentum_score=round(momentum_score, 2),
        )

    def scan_universe(self, stock_data: Dict[str, pd.DataFrame]) -> List[MomentumSignal]:
        """Phase 1+2: Scan all stocks for trend template + acceleration."""
        results = []
        for ticker, df in stock_data.items():
            signal = self.scan_stock(ticker, df)
            if signal:
                results.append(signal)
        results.sort(key=lambda r: r.momentum_score, reverse=True)
        return results

    async def validate(self, results: List[MomentumSignal], top_n: int = 30) -> List[MomentumSignal]:
        """Phase 3: Validate top candidates with analyst + sentiment + earnings."""
        top = results[:top_n]
        if not top:
            return results

        from analyst_data import AnalystDataFetcher
        from sentiment import SentimentEngine

        analyst_fetcher = AnalystDataFetcher()
        sentiment_engine = SentimentEngine()

        async with aiohttp.ClientSession() as session:
            sem = asyncio.Semaphore(5)

            async def _validate_one(r):
                async with sem:
                    # Earnings check
                    try:
                        today = datetime.now()
                        url = (f'https://finnhub.io/api/v1/calendar/earnings'
                               f'?from={today.strftime("%Y-%m-%d")}'
                               f'&to={(today + timedelta(days=7)).strftime("%Y-%m-%d")}'
                               f'&symbol={r.ticker}&token={self.FINNHUB_KEY}')
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                            if resp.status == 200:
                                import json as _json
                                data = _json.loads(await resp.text())
                                for e in data.get('earningsCalendar', []):
                                    if e.get('symbol', '').upper() == r.ticker.upper():
                                        r.vetoed = True
                                        r.veto_reason = f"Earnings on {e.get('date')} (within 7 days)"
                                        return
                    except Exception:
                        pass

                    # Analyst data
                    try:
                        adata = await analyst_fetcher.fetch_analyst_data(r.ticker)
                        if adata:
                            r.analyst_consensus = adata.get("consensus", "")
                            r.analyst_target = adata.get("price_target_avg", 0)
                            if r.analyst_consensus in ("Sell", "Strong Sell", "Underperform"):
                                r.vetoed = True
                                r.veto_reason = f"Analyst says {r.analyst_consensus}"
                                return
                    except Exception:
                        pass

                    # Sentiment
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

            await asyncio.gather(*[_validate_one(r) for r in top])

        return results

    async def run(self, fresh: bool = False) -> List[MomentumSignal]:
        """Run full momentum scan pipeline."""
        # Check cache
        cache_path = os.path.join(CACHE_DIR, f"momentum_{datetime.now().strftime('%Y-%m-%d')}.json")
        if not fresh and os.path.exists(cache_path):
            with open(cache_path) as f:
                data = json.load(f)
            return [MomentumSignal(**r) for r in data]

        print(f"\n{'#'*60}")
        print(f"  ATLAS M1 Momentum Scanner")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'#'*60}")

        # Load data from cache
        from deep_scanner import STOCK_UNIVERSE
        all_tickers = STOCK_UNIVERSE[:3000]
        stock_data = self.cache.get_bulk(all_tickers, 730)
        print(f"  Loaded {len(stock_data)} stocks from cache")

        # Phase 1+2: Scan
        results = self.scan_universe(stock_data)
        print(f"  Phase 1+2: {len(results)} pass trend template + acceleration")

        # Phase 3: Validate
        results = await self.validate(results, top_n=30)
        valid = [r for r in results if not r.vetoed]
        print(f"  Phase 3: {len(valid)} validated ({len(results) - len(valid)} vetoed)")

        # Save cache
        with open(cache_path, "w") as f:
            json.dump([asdict(r) for r in results], f, indent=2)

        return results


if __name__ == "__main__":
    async def main():
        scanner = MomentumScanner()
        results = await scanner.run(fresh=True)
        valid = [r for r in results if not r.vetoed]
        print(f"\nTOP MOMENTUM SIGNALS ({len(valid)} validated):")
        for i, r in enumerate(valid[:20], 1):
            print(f"  {i}. {r.ticker:<7} ${r.price:>7.2f} 20d={r.ret_20d:+.1f}% Vol={r.volume_ratio:.1f}x "
                  f"Score={r.momentum_score:.0f} Hi={r.pct_from_high:+.0f}% Lo={r.pct_from_low:+.0f}%")

    asyncio.run(main())
