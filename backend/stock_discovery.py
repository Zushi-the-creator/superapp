"""
Stock Discovery Engine
Finds trending, hot, and high-potential stocks from multiple sources
Then runs our hybrid model to find the best opportunities
"""

import asyncio
import aiohttp
import os
import urllib.request
import json
import re
from datetime import datetime
from typing import List, Dict, Set
from bs4 import BeautifulSoup


class StockDiscovery:
    """
    Discovers stocks from multiple sources:
    1. Yahoo Finance - Most Active, Gainers, Losers
    2. Finviz - Screener (unusual volume, new highs/lows)
    3. News Sentiment - Trending in news
    4. Social Buzz - Reddit, Twitter mentions
    """

    def __init__(self):
        self.discovered_tickers: Set[str] = set()
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    async def discover_all(self) -> Dict[str, List[str]]:
        """
        Run all discovery methods and return categorized tickers
        """
        results = {
            "most_active": [],
            "gainers": [],
            "losers": [],
            "unusual_volume": [],
            "news_trending": [],
            "oversold_rsi": [],
            "near_52w_low": [],
        }

        # Run all discovery methods
        print("🔍 Discovering stocks from multiple sources...")

        # 1. Yahoo Finance Movers
        try:
            yahoo_data = await self._fetch_yahoo_movers()
            results["most_active"] = yahoo_data.get("most_active", [])
            results["gainers"] = yahoo_data.get("gainers", [])
            results["losers"] = yahoo_data.get("losers", [])
            print(f"   ✅ Yahoo Finance: {len(results['most_active'])} active, {len(results['gainers'])} gainers, {len(results['losers'])} losers")
        except Exception as e:
            print(f"   ❌ Yahoo Finance failed: {e}")

        # 2. Finviz Screener
        try:
            finviz_data = await self._fetch_finviz_screener()
            results["unusual_volume"] = finviz_data.get("unusual_volume", [])
            results["oversold_rsi"] = finviz_data.get("oversold", [])
            results["near_52w_low"] = finviz_data.get("near_low", [])
            print(f"   ✅ Finviz: {len(results['unusual_volume'])} unusual volume, {len(results['oversold_rsi'])} oversold")
        except Exception as e:
            print(f"   ❌ Finviz failed: {e}")

        # 3. News trending
        try:
            news_tickers = await self._fetch_news_trending()
            results["news_trending"] = news_tickers
            print(f"   ✅ News Trending: {len(news_tickers)} tickers mentioned")
        except Exception as e:
            print(f"   ❌ News trending failed: {e}")

        # Collect all unique tickers
        all_tickers = set()
        for category, tickers in results.items():
            all_tickers.update(tickers)

        self.discovered_tickers = all_tickers
        print(f"\n📊 Total unique tickers discovered: {len(all_tickers)}")

        return results

    async def _fetch_yahoo_movers(self) -> Dict[str, List[str]]:
        """Fetch most active, gainers, losers from Yahoo Finance"""
        results = {"most_active": [], "gainers": [], "losers": []}

        urls = {
            "most_active": "https://finance.yahoo.com/most-active",
            "gainers": "https://finance.yahoo.com/gainers",
            "losers": "https://finance.yahoo.com/losers"
        }

        for category, url in urls.items():
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    html = response.read().decode('utf-8')
                    # Extract tickers using regex
                    # Yahoo uses data-symbol attribute
                    tickers = re.findall(r'data-symbol="([A-Z]{1,5})"', html)
                    # Remove duplicates and limit
                    unique_tickers = list(dict.fromkeys(tickers))[:25]
                    results[category] = unique_tickers
            except Exception as e:
                print(f"      Error fetching {category}: {e}")

        return results

    async def _fetch_finviz_screener(self) -> Dict[str, List[str]]:
        """Fetch stocks from Finviz screener"""
        results = {"unusual_volume": [], "oversold": [], "near_low": []}

        screens = {
            # Unusual volume (relative volume > 2)
            "unusual_volume": "https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o500,sh_relvol_o2&ft=4",
            # Oversold RSI < 30
            "oversold": "https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o500,ta_rsi_os30&ft=4",
            # Near 52-week low (within 5%)
            "near_low": "https://finviz.com/screener.ashx?v=111&f=sh_avgvol_o500,ta_highlow52w_a5h&ft=4"
        }

        for category, url in screens.items():
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=10) as response:
                    html = response.read().decode('utf-8')
                    # Finviz uses class="screener-link-primary"
                    tickers = re.findall(r'class="screener-link-primary"[^>]*>([A-Z]{1,5})</a>', html)
                    unique_tickers = list(dict.fromkeys(tickers))[:30]
                    results[category] = unique_tickers
            except Exception as e:
                print(f"      Error fetching {category}: {e}")

        return results

    async def _fetch_news_trending(self) -> List[str]:
        """Extract stock tickers from trending news"""
        tickers = set()

        # Common stock ticker patterns in news
        # Fetch from Google Finance or Yahoo Finance news

        try:
            url = "https://finance.yahoo.com/topic/stock-market-news"
            req = urllib.request.Request(url, headers=self.headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                html = response.read().decode('utf-8')
                # Find tickers mentioned in news
                found = re.findall(r'\(([A-Z]{1,5})\)', html)
                tickers.update(found[:20])
        except:
            pass

        return list(tickers)

    def get_sp500_tickers(self) -> List[str]:
        """Return S&P 500 component tickers"""
        # Top 100 S&P 500 by weight
        return [
            "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "GOOG", "BRK.B", "TSLA", "UNH",
            "XOM", "JNJ", "JPM", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV",
            "LLY", "PEP", "COST", "KO", "AVGO", "WMT", "MCD", "CSCO", "TMO", "ACN",
            "ABT", "CRM", "DHR", "BAC", "PFE", "NKE", "CMCSA", "VZ", "DIS", "ADBE",
            "TXN", "NFLX", "WFC", "PM", "NEE", "RTX", "BMY", "ORCL", "COP", "HON",
            "UNP", "LOW", "QCOM", "UPS", "MS", "INTC", "IBM", "SPGI", "ELV", "CAT",
            "AMGN", "GE", "BA", "DE", "INTU", "AMD", "SBUX", "ISRG", "GS", "BLK",
            "AXP", "LMT", "MDLZ", "GILD", "PLD", "ADI", "BKNG", "SYK", "TJX", "VRTX",
            "REGN", "C", "ADP", "CVS", "MMC", "CB", "SCHW", "MO", "ZTS", "SO",
            "TMUS", "CI", "BDX", "DUK", "PNC", "LRCX", "CME", "EOG", "CL", "ITW"
        ]

    def get_nasdaq100_tickers(self) -> List[str]:
        """Return NASDAQ 100 component tickers"""
        return [
            "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "GOOG", "TSLA", "AVGO", "COST",
            "PEP", "CSCO", "ADBE", "NFLX", "AMD", "CMCSA", "INTC", "INTU", "QCOM", "TXN",
            "AMGN", "HON", "SBUX", "ISRG", "BKNG", "GILD", "ADI", "MDLZ", "VRTX", "REGN",
            "ADP", "LRCX", "PANW", "MU", "KLAC", "PYPL", "SNPS", "CDNS", "MELI", "ORLY",
            "MAR", "ASML", "ABNB", "CHTR", "CTAS", "MNST", "FTNT", "AEP", "PAYX", "MCHP",
            "ADSK", "KDP", "PCAR", "AZN", "KHC", "NXPI", "CPRT", "DXCM", "MRNA", "ROST",
            "MRVL", "ODFL", "IDXX", "LULU", "BIIB", "CSGP", "WDAY", "EA", "ILMN", "EXC",
            "XEL", "SIRI", "FAST", "VRSK", "CTSH", "DLTR", "BKR", "WBD", "FANG", "CEG",
            "ANSS", "ZS", "DDOG", "TEAM", "GEHC", "TTWO", "WBA", "ON", "GFS", "CDW",
            "ALGN", "ENPH", "JD", "LCID", "RIVN", "ZM", "CRWD", "OKTA", "SPLK", "DOCU"
        ]

    def get_high_volume_tickers(self) -> List[str]:
        """Return commonly high-volume traded stocks"""
        return [
            # Mega caps (always liquid)
            "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA",
            # Popular trading stocks
            "AMD", "PLTR", "SOFI", "NIO", "RIVN", "LCID", "F", "GM",
            "BAC", "C", "WFC", "JPM",
            # ETFs
            "SPY", "QQQ", "IWM", "DIA", "ARKK", "XLF", "XLE", "XLK",
            # Meme/retail favorites
            "GME", "AMC", "BB", "BBBY", "WISH", "CLOV",
            # Biotech/volatile
            "MRNA", "BNTX", "PFE", "JNJ",
            # Crypto-related
            "COIN", "MSTR", "RIOT", "MARA",
            # Chinese ADRs
            "BABA", "JD", "PDD", "NIO", "BIDU", "LI",
        ]


class TrendingStockScanner:
    """
    Comprehensive scanner that:
    1. Discovers trending stocks from multiple sources
    2. Runs our hybrid model on all discovered stocks
    3. Returns ranked opportunities
    """

    def __init__(self):
        self.discovery = StockDiscovery()
        self.alpha_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "2DYORCDF5694R9MO")
        self.twelve_key = os.environ.get("TWELVEDATA_API_KEY", "116ea8557206482e88c40543cec8128b")

    async def scan_all(self, max_stocks: int = 100) -> List[Dict]:
        """
        Comprehensive scan of discovered stocks

        Returns list of opportunities sorted by model accuracy
        """
        # Step 1: Discover stocks
        discovered = await self.discovery.discover_all()

        # Step 2: Combine with known universes
        all_tickers = set()

        # Add discovered stocks
        for category, tickers in discovered.items():
            all_tickers.update(tickers)

        # Add S&P 500 (always scan these)
        all_tickers.update(self.discovery.get_sp500_tickers()[:50])

        # Add NASDAQ 100
        all_tickers.update(self.discovery.get_nasdaq100_tickers()[:50])

        # Add high volume stocks
        all_tickers.update(self.discovery.get_high_volume_tickers())

        # Limit to max_stocks
        tickers_to_scan = list(all_tickers)[:max_stocks]

        print(f"\n📊 Scanning {len(tickers_to_scan)} stocks...")

        # Step 3: Run hybrid model on each
        opportunities = []

        for i, ticker in enumerate(tickers_to_scan):
            if (i + 1) % 10 == 0:
                print(f"   Progress: {i+1}/{len(tickers_to_scan)}")

            # This would call the hybrid model
            # For now, we'll return the ticker list

        return tickers_to_scan


# Quick fetch functions for scanning
async def get_trending_stocks() -> Dict[str, List[str]]:
    """Quick function to get all trending stocks"""
    discovery = StockDiscovery()
    return await discovery.discover_all()


async def get_scan_universe() -> List[str]:
    """Get complete list of stocks to scan"""
    discovery = StockDiscovery()

    all_tickers = set()

    # S&P 500
    all_tickers.update(discovery.get_sp500_tickers())

    # NASDAQ 100
    all_tickers.update(discovery.get_nasdaq100_tickers())

    # High volume
    all_tickers.update(discovery.get_high_volume_tickers())

    # Discovered trending
    discovered = await discovery.discover_all()
    for tickers in discovered.values():
        all_tickers.update(tickers)

    return list(all_tickers)


if __name__ == "__main__":
    async def main():
        print("=" * 70)
        print("🔍 STOCK DISCOVERY ENGINE")
        print("=" * 70)

        discovery = StockDiscovery()
        results = await discovery.discover_all()

        print("\n📊 DISCOVERED STOCKS BY CATEGORY:")
        print("-" * 70)

        for category, tickers in results.items():
            if tickers:
                print(f"\n{category.upper().replace('_', ' ')} ({len(tickers)}):")
                print(f"   {', '.join(tickers[:15])}")
                if len(tickers) > 15:
                    print(f"   ... and {len(tickers) - 15} more")

    asyncio.run(main())
