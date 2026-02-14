"""
Analyst Price Target and Consensus Data Fetcher
Fetches Wall Street analyst ratings, price targets, and recommendations

Sources (in order, all FREE and UNLIMITED):
1. Finviz - Web scraping (no API key, no rate limits)
2. Finnhub - Recommendations only (60 calls/min, no price targets on free tier)
"""

import asyncio
import aiohttp
import os
from typing import Optional, Dict
from datetime import datetime, timedelta
from bs4 import BeautifulSoup


class AnalystDataFetcher:
    """
    Fetches analyst consensus data from multiple free sources
    """

    def __init__(self):
        self.cache = {}
        self.cache_duration = timedelta(hours=24)  # Cache for 24 hours
        self.finnhub_key = os.environ.get("FINNHUB_API_KEY", "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0")

    async def fetch_analyst_data(self, ticker: str) -> Optional[Dict]:
        """
        Fetch analyst price targets and ratings

        Returns:
            {
                'ticker': str,
                'price_target_avg': float,
                'price_target_high': float,
                'price_target_low': float,
                'analyst_count': int,
                'buy_ratings': int,
                'hold_ratings': int,
                'sell_ratings': int,
                'consensus': str,  # 'Strong Buy', 'Buy', 'Hold', 'Sell', 'Strong Sell'
                'upside_potential': float,  # % from current price to target
                'last_updated': str
            }
        """
        # Check cache first
        if ticker in self.cache:
            cached_data, cached_time = self.cache[ticker]
            if datetime.now() - cached_time < self.cache_duration:
                return cached_data

        # Try sources in order (all free and unlimited)
        sources = [
            self._fetch_from_finviz,
            self._fetch_from_finnhub,
        ]

        for source_func in sources:
            try:
                data = await source_func(ticker)
                if data and data.get('analyst_count', 0) > 0:
                    # Cache the result
                    self.cache[ticker] = (data, datetime.now())
                    return data
            except Exception as e:
                print(f"  {ticker} analyst data from {source_func.__name__}: {type(e).__name__}")
                continue

        return None

    async def _fetch_from_finviz(self, ticker: str) -> Optional[Dict]:
        """PRIMARY: Scrape analyst data from Finviz (free, no API key, no rate limits)
        Returns price targets, recommendation score, and current price."""
        url = f"https://finviz.com/quote.ashx?t={ticker}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    return None

                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')

                # Parse the snapshot table
                raw = {}
                table = soup.find('table', class_='snapshot-table2')
                if not table:
                    return None

                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    for i in range(0, len(cells) - 1, 2):
                        label = cells[i].text.strip()
                        value = cells[i + 1].text.strip()
                        raw[label] = value

                # Extract key metrics
                current_price = self._parse_float(raw.get('Price', '0'))
                target_price = self._parse_float(raw.get('Target Price', '0'))
                rec_score = self._parse_float(raw.get('Recom', '0'))

                if current_price <= 0:
                    return None

                # Convert recommendation score (1-5 scale) to buy/hold/sell estimate
                # 1.0 = Strong Buy, 2.0 = Buy, 3.0 = Hold, 4.0 = Sell, 5.0 = Strong Sell
                buy_ratings, hold_ratings, sell_ratings = self._score_to_ratings(rec_score)
                total_ratings = buy_ratings + hold_ratings + sell_ratings
                consensus = self._score_to_consensus(rec_score)

                upside = self.calculate_upside_potential(current_price, target_price) if target_price > 0 else 0

                return {
                    'ticker': ticker,
                    'price_target_avg': round(target_price, 2),
                    'price_target_high': 0,
                    'price_target_low': 0,
                    'analyst_count': total_ratings,
                    'buy_ratings': buy_ratings,
                    'hold_ratings': hold_ratings,
                    'sell_ratings': sell_ratings,
                    'consensus': consensus,
                    'recommendation_score': round(rec_score, 2),
                    'upside_potential': round(upside, 1),
                    'current_price': round(current_price, 2),
                    'last_updated': datetime.now().isoformat(),
                    'source': 'finviz'
                }

    async def _fetch_from_finnhub(self, ticker: str) -> Optional[Dict]:
        """FALLBACK: Finnhub recommendations (free, 60 calls/min, no price targets)"""
        rec_url = f"https://finnhub.io/api/v1/stock/recommendation?symbol={ticker}&token={self.finnhub_key}"

        async with aiohttp.ClientSession() as session:
            async with session.get(rec_url, timeout=8) as resp:
                if resp.status != 200:
                    return None

                recs = await resp.json()
                if not recs or not isinstance(recs, list) or len(recs) == 0:
                    return None

                latest = recs[0]
                buy_ratings = latest.get('buy', 0) + latest.get('strongBuy', 0)
                hold_ratings = latest.get('hold', 0)
                sell_ratings = latest.get('sell', 0) + latest.get('strongSell', 0)
                total_ratings = buy_ratings + hold_ratings + sell_ratings

                if total_ratings == 0:
                    return None

                consensus, _ = self.get_consensus_score(buy_ratings, hold_ratings, sell_ratings)

                return {
                    'ticker': ticker,
                    'price_target_avg': 0,
                    'price_target_high': 0,
                    'price_target_low': 0,
                    'analyst_count': total_ratings,
                    'buy_ratings': buy_ratings,
                    'hold_ratings': hold_ratings,
                    'sell_ratings': sell_ratings,
                    'consensus': consensus,
                    'upside_potential': 0,
                    'last_updated': datetime.now().isoformat(),
                    'source': 'finnhub'
                }

    def _parse_float(self, value: str) -> float:
        """Safely parse a string to float"""
        try:
            return float(value.replace(',', '').replace('%', '').replace('$', '').strip())
        except (ValueError, AttributeError):
            return 0.0

    def _score_to_consensus(self, score: float) -> str:
        """Convert Finviz recommendation score (1-5) to consensus label"""
        if score <= 0:
            return 'No Data'
        elif score <= 1.5:
            return 'Strong Buy'
        elif score <= 2.5:
            return 'Buy'
        elif score <= 3.5:
            return 'Hold'
        elif score <= 4.5:
            return 'Sell'
        else:
            return 'Strong Sell'

    def _score_to_ratings(self, score: float) -> tuple:
        """Estimate buy/hold/sell breakdown from recommendation score"""
        if score <= 0:
            return 0, 0, 0
        # Approximate: distribute 30 analysts based on score
        total = 30
        if score <= 2.0:
            buy = int(total * (2.5 - score) / 2.0)
            sell = 0
            hold = total - buy
        elif score <= 3.0:
            buy = int(total * (3.0 - score) / 2.0)
            sell = int(total * (score - 2.0) / 4.0)
            hold = total - buy - sell
        else:
            buy = 0
            sell = int(total * (score - 2.5) / 2.0)
            hold = total - sell
        return max(buy, 0), max(hold, 0), max(sell, 0)

    def calculate_upside_potential(self, current_price: float, target_price: float) -> float:
        """Calculate percentage upside from current to target price"""
        if current_price <= 0:
            return 0
        return ((target_price - current_price) / current_price) * 100

    def get_consensus_score(self, buy_count: int, hold_count: int, sell_count: int) -> tuple:
        """
        Convert analyst ratings to consensus rating and score

        Returns:
            (consensus_label, consensus_score)
            consensus_score: 0-100 where 100 is unanimous strong buy
        """
        total = buy_count + hold_count + sell_count
        if total == 0:
            return 'No Data', 0

        buy_pct = buy_count / total
        hold_pct = hold_count / total
        sell_pct = sell_count / total

        # Calculate weighted score
        score = (buy_pct * 100) + (hold_pct * 50) + (sell_pct * 0)

        # Determine consensus label
        if buy_pct >= 0.8:
            consensus = 'Strong Buy'
        elif buy_pct >= 0.6:
            consensus = 'Buy'
        elif sell_pct >= 0.8:
            consensus = 'Strong Sell'
        elif sell_pct >= 0.6:
            consensus = 'Sell'
        else:
            consensus = 'Hold'

        return consensus, round(score, 1)


# Global instance
analyst_fetcher = AnalystDataFetcher()


async def get_analyst_data(ticker: str) -> Optional[Dict]:
    """Convenience function to fetch analyst data"""
    return await analyst_fetcher.fetch_analyst_data(ticker)
