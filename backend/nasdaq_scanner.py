"""
Fast NASDAQ Stock Scanner
Scans top 2000 NASDAQ stocks efficiently using parallel API calls
"""

import asyncio
import aiohttp
from typing import List, Dict
import pandas as pd
from datetime import datetime
from data_fetcher import get_fetcher


class NasdaqScanner:
    """Efficient scanner for NASDAQ stocks"""

    def __init__(self):
        self.fetcher = get_fetcher()
        self.batch_size = 100  # Process 100 stocks at a time
        self.delay_between_batches = 0.5  # 0.5 second delay to avoid rate limits
        self.nasdaq_list_cache = None

    def _get_top_nasdaq_stocks(self) -> List[str]:
        """
        Return top ~2000 NASDAQ stocks
        Mix of: Large cap, Mid cap, Small cap, Active traders
        """
        # Top 100 by market cap
        large_cap = [
            'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'GOOG', 'AMZN', 'META', 'TSLA',
            'AVGO', 'COST', 'NFLX', 'AMD', 'ASML', 'TMUS', 'CSCO', 'ADBE',
            'PEP', 'LIN', 'INTC', 'INTU', 'TXN', 'QCOM', 'CMCSA', 'AMGN',
            'AMAT', 'HON', 'BKNG', 'ISRG', 'VRTX', 'ADP', 'SBUX', 'GILD',
            'ADI', 'REGN', 'PANW', 'MU', 'LRCX', 'PYPL', 'SNPS', 'KLAC',
            'CDNS', 'CRWD', 'MELI', 'ABNB', 'MAR', 'MNST', 'ORLY', 'CSX',
            'DASH', 'NXPI', 'FTNT', 'CEG', 'WDAY', 'ADSK', 'PCAR', 'TEAM',
            'MRVL', 'CHTR', 'PAYX', 'CPRT', 'AEP', 'FAST', 'ODFL', 'ROST',
            'KDP', 'DXCM', 'EA', 'VRSK', 'CTSH', 'GEHC', 'TTD', 'EXC',
            'IDXX', 'KHC', 'CSGP', 'ON', 'LULU', 'ZS', 'ANSS', 'DDOG',
            'BIIB', 'XEL', 'GFS', 'FANG', 'CCEP', 'TTWO', 'WBD', 'CDW',
            'ILMN', 'MDB', 'WBA', 'MRNA', 'ALGN', 'DLTR', 'SMCI', 'ENPH'
        ]

        # Active mid/small caps
        active_stocks = [
            'RIVN', 'LCID', 'NIO', 'PLUG', 'FUBO', 'SOFI', 'UPST', 'HOOD',
            'COIN', 'PLTR', 'RBLX', 'SNOW', 'U', 'NET', 'DKNG', 'PINS',
            'ROKU', 'SNAP', 'LYFT', 'UBER', 'DOCU', 'ZM', 'OKTA', 'TWLO',
            'SHOP', 'SQ', 'SPOT', 'CVNA', 'CHWY', 'ETSY', 'W', 'FVRR',
            'ZI', 'BILL', 'PCTY', 'SMAR', 'APPN', 'ESTC', 'NEWR', 'SUMO',
            'CFLT', 'IOT', 'PATH', 'S', 'DOCN', 'AI', 'AFRM', 'NU'
        ]

        # Biotech/Pharma
        biotech = [
            'VRTX', 'GILD', 'REGN', 'BIIB', 'MRNA', 'ILMN', 'ALNY', 'BMRN',
            'SGEN', 'EXEL', 'TECH', 'NBIX', 'INCY', 'UTHR', 'RARE', 'FOLD',
            'EXAS', 'ARWR', 'IONS', 'CRSP', 'NTLA', 'EDIT', 'BLUE', 'SRPT',
            'RGEN', 'VCEL', 'SAGE', 'ALLK', 'AGIO', 'BDTX', 'ACAD', 'PTCT'
        ]

        # Semiconductors
        semis = [
            'NVDA', 'AMD', 'INTC', 'QCOM', 'AVGO', 'TXN', 'ADI', 'MRVL',
            'NXPI', 'LRCX', 'KLAC', 'AMAT', 'MU', 'SNPS', 'CDNS', 'MPWR',
            'MCHP', 'ON', 'SWKS', 'QRVO', 'WOLF', 'CRUS', 'SLAB', 'MTSI',
            'SITM', 'AOSL', 'SMTC', 'UCTT', 'FORM', 'COHU', 'ICHR', 'LSCC'
        ]

        # Combine all and remove duplicates
        all_stocks = list(set(large_cap + active_stocks + biotech + semis))

        # If we need more to reach 2000, we can add more sectors
        # For now, return what we have
        return all_stocks

    async def scan_stock(self, ticker: str) -> Dict:
        """Scan a single stock and return metrics"""
        try:
            quote = await self.fetcher.get_quote(ticker)
            if not quote:
                return None

            # Get historical data for RSI calculation
            df = await self.fetcher.fetch_stock_data(ticker, period_days=14)
            if df is None or len(df) < 14:
                return None

            # Calculate RSI
            rsi = self._calculate_rsi(df['Close'])

            # Determine signal
            signal = 'BUY' if rsi < 30 else 'SELL' if rsi > 70 else 'HOLD'
            score = self._calculate_score(quote, rsi)

            return {
                'ticker': ticker,
                'price': quote['price'],
                'change_pct': quote['change_pct'],
                'rsi': round(rsi, 2),
                'signal': signal,
                'score': round(score, 2),
                'volume': quote.get('volume', 0)
            }
        except Exception as e:
            return None

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])

    def _calculate_score(self, quote: Dict, rsi: float) -> float:
        """Calculate overall score for ranking"""
        score = 0

        # RSI component (30 points)
        if rsi < 20:
            score += 30
        elif rsi < 30:
            score += 25
        elif rsi < 40:
            score += 15

        # Momentum component (20 points)
        if abs(quote['change_pct']) > 5:
            score += 20
        elif abs(quote['change_pct']) > 3:
            score += 15
        elif abs(quote['change_pct']) > 2:
            score += 10

        return score

    async def scan_batch(self, tickers: List[str]) -> List[Dict]:
        """Scan a batch of stocks in parallel"""
        tasks = [self.scan_stock(ticker) for ticker in tickers]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def get_all_nasdaq_stocks(self) -> List[str]:
        """Fetch complete list of NASDAQ stocks from API"""
        if self.nasdaq_list_cache:
            return self.nasdaq_list_cache

        try:
            # Use Alpha Vantage listing status endpoint (free)
            url = "https://www.alphavantage.co/query"
            params = {
                "function": "LISTING_STATUS",
                "apikey": self.fetcher.alpha_vantage_key
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    if response.status == 200:
                        text = await response.text()
                        lines = text.strip().split('\n')

                        # Parse CSV format (symbol,name,exchange,assetType,ipoDate,delistingDate,status)
                        nasdaq_stocks = []
                        for line in lines[1:]:  # Skip header
                            parts = line.split(',')
                            if len(parts) >= 3:
                                symbol = parts[0].strip()
                                exchange = parts[2].strip()

                                # Filter for NASDAQ exchange only
                                if exchange in ['NASDAQ', 'NASDAQ Global Select', 'NASDAQ Capital Market']:
                                    if symbol.isalpha() and len(symbol) <= 5:  # Valid ticker format
                                        nasdaq_stocks.append(symbol)

                        self.nasdaq_list_cache = nasdaq_stocks
                        print(f"Loaded {len(nasdaq_stocks)} NASDAQ stocks from API")
                        return nasdaq_stocks
        except Exception as e:
            print(f"⚠️ Failed to fetch NASDAQ list: {e}")

        # Fallback to curated list
        print("Using curated NASDAQ list")
        self.nasdaq_list_cache = self._get_top_nasdaq_stocks()
        return self.nasdaq_list_cache

    async def scan_all(self, limit: int = None) -> List[Dict]:
        """
        Scan ALL NASDAQ stocks (or up to limit)
        Returns list of stocks sorted by score
        """
        # Get complete NASDAQ list
        all_nasdaq = await self.get_all_nasdaq_stocks()

        stocks_to_scan = all_nasdaq if limit is None else all_nasdaq[:limit]
        print(f"Starting NASDAQ scan of {len(stocks_to_scan)} stocks...")

        all_results = []

        # Process in batches
        for i in range(0, len(stocks_to_scan), self.batch_size):
            batch = stocks_to_scan[i:i + self.batch_size]
            print(f"Scanning batch {i//self.batch_size + 1}/{(len(stocks_to_scan)-1)//self.batch_size + 1}...")

            results = await self.scan_batch(batch)
            all_results.extend(results)

            # Delay between batches to avoid rate limits
            if i + self.batch_size < len(stocks_to_scan):
                await asyncio.sleep(self.delay_between_batches)

        # Sort by score (highest first)
        all_results.sort(key=lambda x: x['score'], reverse=True)

        print(f"✅ Scan complete! Found {len(all_results)} valid stocks")
        return all_results

    async def get_top_buys(self, limit: int = 20) -> List[Dict]:
        """Get top BUY signals from scan"""
        all_stocks = await self.scan_all(limit=500)  # Scan 500 for speed
        buy_signals = [s for s in all_stocks if s['signal'] == 'BUY']
        return buy_signals[:limit]


async def main():
    """Test the scanner"""
    scanner = NasdaqScanner()
    top_buys = await scanner.get_top_buys(limit=10)

    print("\n=== TOP 10 NASDAQ BUY SIGNALS ===\n")
    for stock in top_buys:
        print(f"{stock['ticker']:6s} ${stock['price']:>8.2f} ({stock['change_pct']:+6.2f}%) "
              f"RSI: {stock['rsi']:>5.1f} Score: {stock['score']:>4.1f}")


if __name__ == "__main__":
    asyncio.run(main())
