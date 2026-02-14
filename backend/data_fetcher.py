"""
Multi-Source Stock Data Fetcher
Provides automatic fallback across multiple free stock data APIs
Returns LIVE DATA ONLY - no demo/fake data

Sources (prioritized by reliability):
1. Tiingo - FREE, 500 req/hr (PRIMARY for historical, most reliable)
2. Stooq - FREE, ~200/day (SECONDARY for historical)
3. Finnhub - FREE, 60 calls/min (PRIMARY for live quotes)
4. Twelve Data - FREE, 800 calls/day (FALLBACK for historical)
"""

import asyncio
import aiohttp
import pandas as pd
from typing import Optional, Dict
from datetime import datetime, timedelta
from io import StringIO


class MultiSourceDataFetcher:
    """
    Fetches stock data from multiple sources with automatic fallback
    All sources are FREE with no daily limits (except Twelve Data as fallback)
    """

    def __init__(self):
        self.polygon_key = "StsDd_iAxQgokTTsI9d16T3RQf4tNlDg"
        self.tiingo_key = "6f632a60d6188ebc1b92221e83d4fba37e2a5c42"
        self.fmp_key = "PETzQaEtgbqcVO3FWTtLD4lZCPuH58sa"
        self.twelve_data_key = "116ea8557206482e88c40543cec8128b"
        self.finnhub_key = "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0"

    async def fetch_stock_data(self, ticker: str, period_days: int = 30) -> Optional[pd.DataFrame]:
        """
        Fetch stock data with automatic fallback

        Args:
            ticker: Stock symbol
            period_days: Number of days of historical data

        Returns:
            DataFrame with OHLCV data or None if all sources fail
        """
        sources = [
            self._fetch_polygon,
            self._fetch_tiingo,
            self._fetch_fmp,
            self._fetch_stooq,
            self._fetch_finnhub,
            self._fetch_twelve_data,
        ]

        for source_func in sources:
            try:
                df = await source_func(ticker, period_days)
                if df is not None and not df.empty and len(df) >= 5:
                    return df
            except Exception as e:
                error_msg = str(e)
                if len(error_msg) > 100:
                    error_msg = error_msg[:100] + "..."
                print(f"  {ticker}: {source_func.__name__} failed - {type(e).__name__}: {error_msg}")
                continue

        print(f"  {ticker}: No live data available from any source")
        return None

    async def _fetch_polygon(self, ticker: str, period_days: int) -> Optional[pd.DataFrame]:
        """PRIMARY: Polygon.io - unlimited calls, full history"""
        end = datetime.now()
        start = end - timedelta(days=period_days + 30)
        url = (f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/'
               f'{start.strftime("%Y-%m-%d")}/{end.strftime("%Y-%m-%d")}')
        params = {'adjusted': 'true', 'sort': 'asc', 'limit': 5000,
                  'apiKey': self.polygon_key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                if data.get('resultsCount', 0) < 5 or 'results' not in data:
                    return None

                results = data['results']
                df = pd.DataFrame(results)
                df['date'] = pd.to_datetime(df['t'], unit='ms')
                df = df.set_index('date').sort_index()
                df = df.rename(columns={
                    'o': 'Open', 'h': 'High', 'l': 'Low',
                    'c': 'Close', 'v': 'Volume'
                })

                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                return df.tail(period_days)

    async def _fetch_tiingo(self, ticker: str, period_days: int) -> Optional[pd.DataFrame]:
        """PRIMARY: Tiingo (tiingo.com) - FREE, 500 req/hr, split-adjusted"""
        start = (datetime.now() - timedelta(days=period_days + 30)).strftime('%Y-%m-%d')
        end = datetime.now().strftime('%Y-%m-%d')
        url = f'https://api.tiingo.com/tiingo/daily/{ticker}/prices'
        params = {'startDate': start, 'endDate': end, 'token': self.tiingo_key}
        headers = {'Content-Type': 'application/json'}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=12) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                if not data or not isinstance(data, list) or len(data) < 5:
                    return None

                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
                df = df.set_index('date').sort_index()

                # Use split-adjusted prices
                col_map = {}
                if 'adjClose' in df.columns:
                    col_map = {'adjOpen': 'Open', 'adjHigh': 'High',
                               'adjLow': 'Low', 'adjClose': 'Close', 'adjVolume': 'Volume'}
                else:
                    col_map = {'open': 'Open', 'high': 'High',
                               'low': 'Low', 'close': 'Close', 'volume': 'Volume'}

                df = df.rename(columns=col_map)
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                return df.tail(period_days)

    async def _fetch_fmp(self, ticker: str, period_days: int) -> Optional[pd.DataFrame]:
        """FMP (financialmodelingprep.com) - 300 req/min, 5yr history"""
        url = 'https://financialmodelingprep.com/stable/historical-price-eod/full'
        params = {'symbol': ticker, 'apikey': self.fmp_key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                if not data or not isinstance(data, list) or len(data) < 5:
                    return None

                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
                df = df.rename(columns={
                    'open': 'Open', 'high': 'High',
                    'low': 'Low', 'close': 'Close', 'volume': 'Volume'
                })

                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                return df.tail(period_days)

    async def _fetch_stooq(self, ticker: str, period_days: int) -> Optional[pd.DataFrame]:
        """SECONDARY: Stooq (stooq.com) - FREE, ~200/day, no API key needed"""
        url = f"https://stooq.com/q/d/l/?s={ticker.lower()}.us&i=d"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as response:
                if response.status != 200:
                    return None

                text = await response.text()
                lines = text.strip().split('\n')
                if len(lines) < 10:
                    return None

                df = pd.read_csv(StringIO(text))
                if 'Date' not in df.columns:
                    return None

                df['Date'] = pd.to_datetime(df['Date'])
                df = df.set_index('Date').sort_index()

                # Standardize column names
                col_map = {}
                for col in df.columns:
                    cl = col.lower()
                    if cl == 'open': col_map[col] = 'Open'
                    elif cl == 'high': col_map[col] = 'High'
                    elif cl == 'low': col_map[col] = 'Low'
                    elif cl == 'close': col_map[col] = 'Close'
                    elif cl == 'volume': col_map[col] = 'Volume'
                if col_map:
                    df = df.rename(columns=col_map)

                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                return df.tail(period_days)

    async def _fetch_twelve_data(self, ticker: str, period_days: int) -> Optional[pd.DataFrame]:
        """FALLBACK: Twelve Data (twelvedata.com) - 800 calls/day"""
        url = "https://api.twelvedata.com/time_series"
        params = {
            "symbol": ticker,
            "interval": "1day",
            "outputsize": min(period_days, 365),
            "apikey": self.twelve_data_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return None

                data = await response.json()

                if "values" not in data:
                    return None

                df = pd.DataFrame(data["values"])
                df['datetime'] = pd.to_datetime(df['datetime'])
                df = df.set_index('datetime').sort_index()

                df = df.rename(columns={
                    "open": "Open",
                    "high": "High",
                    "low": "Low",
                    "close": "Close",
                    "volume": "Volume"
                })

                for col in df.columns:
                    df[col] = pd.to_numeric(df[col])

                return df

    async def _fetch_finnhub(self, ticker: str, period_days: int) -> Optional[pd.DataFrame]:
        """FALLBACK: Finnhub (finnhub.io) - 60 calls/min"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)

        url = "https://finnhub.io/api/v1/stock/candle"
        params = {
            "symbol": ticker,
            "resolution": "D",
            "from": int(start_date.timestamp()),
            "to": int(end_date.timestamp()),
            "token": self.finnhub_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return None

                data = await response.json()

                if data.get("s") != "ok":
                    return None

                df = pd.DataFrame({
                    "Open": data["o"],
                    "High": data["h"],
                    "Low": data["l"],
                    "Close": data["c"],
                    "Volume": data["v"]
                })

                df.index = pd.to_datetime(data["t"], unit='s')
                df = df.sort_index()

                return df

    async def _fetch_finnhub_quote(self, ticker: str) -> Optional[Dict]:
        """Get real-time quote from Finnhub (60 calls/min)"""
        url = "https://finnhub.io/api/v1/quote"
        params = {
            "symbol": ticker,
            "token": self.finnhub_key
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status != 200:
                        return None

                    data = await response.json()

                    if not data or data.get("c", 0) == 0:
                        return None

                    current = data.get("c", 0)
                    prev_close = data.get("pc", current)
                    change = current - prev_close
                    change_pct = (change / prev_close * 100) if prev_close else 0

                    return {
                        "symbol": ticker,
                        "price": round(float(current), 2),
                        "change": round(float(change), 2),
                        "change_pct": round(float(change_pct), 2),
                        "volume": 0,
                        "timestamp": datetime.now().isoformat(),
                        "source": "finnhub_realtime"
                    }
        except Exception as e:
            print(f"  Finnhub quote failed for {ticker}: {e}")
            return None

    async def get_quote(self, ticker: str) -> Dict:
        """
        Get current quote for a ticker (REAL-TIME)
        Uses Finnhub (60 calls/min, no daily limit)
        """
        quote = await self._fetch_finnhub_quote(ticker)
        if quote:
            return quote

        # Fallback to daily close from Stooq
        df = await self.fetch_stock_data(ticker, period_days=5)

        if df is None or df.empty:
            return None

        current_price = df['Close'].iloc[-1]
        prev_price = df['Close'].iloc[-2] if len(df) > 1 else current_price

        return {
            "symbol": ticker,
            "price": round(float(current_price), 2),
            "change": round(float(current_price - prev_price), 2),
            "change_pct": round(float((current_price - prev_price) / prev_price * 100), 2),
            "volume": int(df['Volume'].iloc[-1]),
            "timestamp": datetime.now().isoformat(),
            "source": "daily_close"
        }


# Singleton instance
_fetcher = None

def get_fetcher() -> MultiSourceDataFetcher:
    """Get singleton fetcher instance"""
    global _fetcher
    if _fetcher is None:
        _fetcher = MultiSourceDataFetcher()
    return _fetcher
