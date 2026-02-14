"""
SQLite Data Cache for Historical Stock Data
============================================
Stores OHLCV data locally, making scans instant after initial population.

Usage:
    cache = DataCache()
    await cache.populate(['AAPL', 'MSFT', ...])  # One-time bulk load via Tiingo
    await cache.refresh()                         # Daily update (latest day only)
    df = cache.get('AAPL', 365)                   # Instant local read

    python3 data_cache.py                         # Populate full universe
    python3 data_cache.py --refresh               # Update today's data
    python3 data_cache.py --stats                 # Show cache stats
"""

import sqlite3
import os
import sys
import asyncio
import aiohttp
import argparse
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stock_cache.db')
POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "StsDd_iAxQgokTTsI9d16T3RQf4tNlDg")
TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "6f632a60d6188ebc1b92221e83d4fba37e2a5c42")
FMP_KEY = os.environ.get("FMP_API_KEY", "PETzQaEtgbqcVO3FWTtLD4lZCPuH58sa")


class DataCache:
    """SQLite-backed OHLCV cache with Tiingo bulk fetching."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS daily_prices (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL, volume REAL,
                PRIMARY KEY (ticker, date)
            )
        ''')
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS cache_meta (
                ticker TEXT PRIMARY KEY,
                last_updated TEXT,
                data_start TEXT,
                data_end TEXT,
                row_count INTEGER
            )
        ''')
        self.conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_prices_ticker ON daily_prices(ticker)'
        )
        self.conn.commit()

    # ── Read ──

    def get(self, ticker: str, days: int = 365) -> Optional[pd.DataFrame]:
        """Read cached data - INSTANT, no API calls."""
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        rows = self.conn.execute(
            'SELECT date, open, high, low, close, volume FROM daily_prices '
            'WHERE ticker = ? AND date >= ? ORDER BY date',
            (ticker.upper(), cutoff)
        ).fetchall()

        if not rows or len(rows) < 50:
            return None

        df = pd.DataFrame(rows, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.set_index('Date')
        return df

    def get_cached_tickers(self) -> List[str]:
        """List all tickers in cache."""
        rows = self.conn.execute('SELECT ticker FROM cache_meta').fetchall()
        return [r[0] for r in rows]

    def is_fresh(self, ticker: str) -> bool:
        """Check if ticker was updated today."""
        today = datetime.now().strftime('%Y-%m-%d')
        row = self.conn.execute(
            'SELECT last_updated FROM cache_meta WHERE ticker = ?', (ticker.upper(),)
        ).fetchone()
        return row is not None and row[0] >= today

    def get_stale_tickers(self) -> List[str]:
        """Tickers that haven't been updated today."""
        today = datetime.now().strftime('%Y-%m-%d')
        rows = self.conn.execute(
            'SELECT ticker FROM cache_meta WHERE last_updated < ?', (today,)
        ).fetchall()
        return [r[0] for r in rows]

    def stats(self) -> Dict:
        """Cache statistics."""
        total = self.conn.execute(
            'SELECT COUNT(DISTINCT ticker) FROM cache_meta'
        ).fetchone()[0]
        today = datetime.now().strftime('%Y-%m-%d')
        fresh = self.conn.execute(
            'SELECT COUNT(*) FROM cache_meta WHERE last_updated >= ?', (today,)
        ).fetchone()[0]
        total_rows = self.conn.execute(
            'SELECT COUNT(*) FROM daily_prices'
        ).fetchone()[0]
        return {
            'total_tickers': total,
            'fresh_today': fresh,
            'stale': total - fresh,
            'total_rows': total_rows,
        }

    # ── Write ──

    def store(self, ticker: str, df: pd.DataFrame):
        """Store OHLCV data in cache (upsert)."""
        ticker = ticker.upper()
        rows = []
        for date, row in df.iterrows():
            date_str = date.strftime('%Y-%m-%d') if hasattr(date, 'strftime') else str(date)[:10]
            rows.append((
                ticker, date_str,
                float(row.get('Open', 0)), float(row.get('High', 0)),
                float(row.get('Low', 0)), float(row.get('Close', 0)),
                float(row.get('Volume', 0))
            ))

        if not rows:
            return

        self.conn.executemany(
            'INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?)', rows
        )
        self.conn.execute(
            'INSERT OR REPLACE INTO cache_meta VALUES (?, ?, ?, ?, ?)',
            (ticker, datetime.now().strftime('%Y-%m-%d'),
             rows[0][1], rows[-1][1], len(rows))
        )
        self.conn.commit()

    # ── Tiingo Fetch ──

    async def _fetch_tiingo(self, session: aiohttp.ClientSession,
                            ticker: str, days: int = 400) -> Optional[pd.DataFrame]:
        """Fetch from Tiingo API (500 req/hr free tier). Returns None on rate limit."""
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end = datetime.now().strftime('%Y-%m-%d')
        url = f'https://api.tiingo.com/tiingo/daily/{ticker}/prices'
        params = {'startDate': start, 'endDate': end, 'token': TIINGO_KEY}
        headers = {'Content-Type': 'application/json'}

        try:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    return "RATE_LIMITED"
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data or not isinstance(data, list) or len(data) < 50:
                    return None

                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
                df = df.set_index('date').sort_index()

                # Use split-adjusted prices
                if 'adjClose' in df.columns:
                    col_map = {'adjOpen': 'Open', 'adjHigh': 'High',
                               'adjLow': 'Low', 'adjClose': 'Close', 'adjVolume': 'Volume'}
                else:
                    col_map = {'open': 'Open', 'high': 'High',
                               'low': 'Low', 'close': 'Close', 'volume': 'Volume'}

                df = df.rename(columns=col_map)
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                for col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df
        except Exception:
            return None

    async def _fetch_polygon(self, session: aiohttp.ClientSession,
                             ticker: str) -> Optional[pd.DataFrame]:
        """Fetch from Polygon.io - unlimited calls, full history."""
        end = datetime.now()
        start = end - timedelta(days=400)
        url = (f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/'
               f'{start.strftime("%Y-%m-%d")}/{end.strftime("%Y-%m-%d")}')
        params = {'adjusted': 'true', 'sort': 'asc', 'limit': 5000,
                  'apiKey': POLYGON_KEY}

        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    return "RATE_LIMITED"
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get('resultsCount', 0) < 50 or 'results' not in data:
                    return None

                results = data['results']
                df = pd.DataFrame(results)
                df['date'] = pd.to_datetime(df['t'], unit='ms')
                df = df.set_index('date').sort_index()
                df = df.rename(columns={
                    'o': 'Open', 'h': 'High', 'l': 'Low',
                    'c': 'Close', 'v': 'Volume'
                })
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                for col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df
        except Exception:
            return None

    async def _fetch_fmp(self, session: aiohttp.ClientSession,
                         ticker: str) -> Optional[pd.DataFrame]:
        """Fetch from FMP API (300 req/min). Fast bulk fetcher."""
        url = 'https://financialmodelingprep.com/stable/historical-price-eod/full'
        params = {'symbol': ticker, 'apikey': FMP_KEY}

        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    return "RATE_LIMITED"
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data or not isinstance(data, list) or len(data) < 50:
                    return None

                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['date'])
                df = df.set_index('date').sort_index()
                df = df.rename(columns={
                    'open': 'Open', 'high': 'High',
                    'low': 'Low', 'close': 'Close', 'volume': 'Volume'
                })
                df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
                for col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df
        except Exception:
            return None

    # ── yfinance Fetch (sync, called from async via executor) ──

    def _fetch_yfinance_batch(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """Fetch batch of tickers via yfinance (no rate limit). Returns {ticker: df}."""
        try:
            import yfinance as yf
        except ImportError:
            return {}

        results = {}
        batch_str = " ".join(tickers)
        try:
            data = yf.download(batch_str, period="1y", progress=False,
                             timeout=30, group_by="ticker", threads=True)
            if data.empty:
                return {}

            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        df = data.copy()
                        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    else:
                        if ticker not in data.columns.get_level_values(0):
                            continue
                        df = data[ticker].dropna(how='all')

                    if len(df) > 30:
                        results[ticker] = df
                except Exception:
                    pass
        except Exception:
            pass
        return results

    # ── Bulk Operations ──

    async def populate(self, tickers: List[str], force: bool = False) -> Dict:
        """
        Multi-source parallel populate using ALL free APIs simultaneously.

        Strategy: Split tickers across sources for maximum throughput.
        - yfinance: Bulk batches of 20 (no rate limit, ~200/min)
        - Polygon: 5/min free tier (slow but reliable)
        - Tiingo: 500/hr (~8/min)
        - FMP: 250/day (~4/min)
        Fallback chain: yfinance → Polygon → Tiingo → FMP
        """
        import time
        tickers = [t.upper() for t in tickers]
        cached = set() if force else set(self.get_cached_tickers())
        to_fetch = list(dict.fromkeys(t for t in tickers if t not in cached))

        if not to_fetch:
            print(f'[CACHE] All {len(tickers)} tickers already cached')
            return {'fetched': 0, 'cached': len(cached), 'failed': 0}

        print(f'[CACHE] Multi-source fetch: {len(to_fetch)} tickers '
              f'({len(cached)} already cached)')
        print(f'  Sources: yfinance (bulk) + Polygon (5/min) + Tiingo (8/min) + FMP (4/min)')

        fetched = 0
        failed_tickers = set()
        fetched_tickers = set()
        start_time = time.time()

        # Phase 1: yfinance bulk (fastest - handles most tickers)
        print(f'\n  [Phase 1] yfinance bulk fetch...')
        loop = asyncio.get_event_loop()
        yf_batch_size = 20

        for i in range(0, len(to_fetch), yf_batch_size):
            batch = to_fetch[i:i + yf_batch_size]
            try:
                results = await loop.run_in_executor(
                    None, self._fetch_yfinance_batch, batch)
                for ticker, df in results.items():
                    self.store(ticker, df)
                    fetched_tickers.add(ticker)
                    fetched += 1
            except Exception:
                pass

            done = min(i + yf_batch_size, len(to_fetch))
            elapsed = time.time() - start_time
            rate = fetched / elapsed * 60 if elapsed > 0 else 0
            if done % 100 == 0 or done == len(to_fetch):
                print(f'    [{done}/{len(to_fetch)}] OK: {fetched} | '
                      f'{elapsed:.0f}s | ~{rate:.0f}/min')

        print(f'  [Phase 1] yfinance: {fetched} fetched')

        # Phase 2: API fallback for yfinance failures
        remaining = [t for t in to_fetch if t not in fetched_tickers]
        if remaining:
            print(f'\n  [Phase 2] API fallback for {len(remaining)} remaining...')

            # Rate limit semaphores per source
            polygon_sem = asyncio.Semaphore(1)  # 5/min → 1 at a time with delay
            tiingo_sem = asyncio.Semaphore(2)   # 500/hr → 2 concurrent
            fmp_sem = asyncio.Semaphore(1)      # 250/day → 1 at a time

            api_fetched = 0

            async with aiohttp.ClientSession() as session:
                async def fetch_with_fallback(ticker):
                    nonlocal api_fetched
                    # Try Polygon
                    async with polygon_sem:
                        result = await self._fetch_polygon(session, ticker)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_fetched += 1
                            fetched_tickers.add(ticker)
                            return
                        await asyncio.sleep(12)  # 5/min = 12s between calls

                    # Try Tiingo
                    async with tiingo_sem:
                        result = await self._fetch_tiingo(session, ticker)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_fetched += 1
                            fetched_tickers.add(ticker)
                            return
                        await asyncio.sleep(7)  # ~8/min

                    # Try FMP
                    async with fmp_sem:
                        result = await self._fetch_fmp(session, ticker)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_fetched += 1
                            fetched_tickers.add(ticker)
                            return
                        await asyncio.sleep(15)

                    failed_tickers.add(ticker)

                # Process in batches of 10 for API fallback
                for i in range(0, len(remaining), 10):
                    batch = remaining[i:i + 10]
                    await asyncio.gather(*[fetch_with_fallback(t) for t in batch])
                    done = min(i + 10, len(remaining))
                    if done % 50 == 0 or done == len(remaining):
                        print(f'    [{done}/{len(remaining)}] API fetched: {api_fetched} | '
                              f'Failed: {len(failed_tickers)}')

            fetched += api_fetched
            print(f'  [Phase 2] APIs: {api_fetched} fetched, {len(failed_tickers)} failed')

        elapsed = time.time() - start_time
        print(f'\n[CACHE] Done in {elapsed:.0f}s: {fetched} fetched, '
              f'{len(failed_tickers)} failed, {len(cached)} were cached')
        if failed_tickers and len(failed_tickers) <= 30:
            print(f'  Failed: {", ".join(sorted(failed_tickers))}')
        return {'fetched': fetched, 'cached': len(cached),
                'failed': len(failed_tickers)}

    def _refresh_yfinance_batch(self, tickers: List[str]) -> Dict[str, pd.DataFrame]:
        """Fetch last 5 days for a batch of tickers via yfinance."""
        try:
            import yfinance as yf
        except ImportError:
            return {}

        results = {}
        batch_str = " ".join(tickers)
        try:
            data = yf.download(batch_str, period="5d", progress=False,
                             timeout=30, group_by="ticker", threads=True)
            if data.empty:
                return {}

            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        df = data.copy()
                        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    else:
                        if ticker not in data.columns.get_level_values(0):
                            continue
                        df = data[ticker].dropna(how='all')

                    if len(df) >= 1:
                        results[ticker] = df
                except Exception:
                    pass
        except Exception:
            pass
        return results

    async def refresh(self, tickers: Optional[List[str]] = None) -> Dict:
        """
        Multi-source parallel refresh for all stale tickers.

        Strategy: yfinance bulk (5-day window) for speed, API fallback for failures.
        ~3,000 tickers in ~10-15 minutes vs 6+ hours with old single-source method.
        """
        import time

        if tickers:
            stale = [t.upper() for t in tickers if not self.is_fresh(t)]
        else:
            stale = self.get_stale_tickers()

        if not stale:
            print('[CACHE] All tickers already up to date')
            return {'refreshed': 0, 'failed': 0}

        print(f'[CACHE] Multi-source refresh: {len(stale)} stale tickers')
        start_time = time.time()
        refreshed = 0
        refreshed_tickers = set()
        failed_tickers = set()

        # Phase 1: yfinance bulk (fast - 20 tickers per batch, 5-day window)
        print(f'  [Phase 1] yfinance bulk refresh (5-day window)...')
        loop = asyncio.get_event_loop()
        batch_size = 20

        for i in range(0, len(stale), batch_size):
            batch = stale[i:i + batch_size]
            try:
                results = await loop.run_in_executor(
                    None, self._refresh_yfinance_batch, batch)
                for ticker, df in results.items():
                    self.store(ticker, df)
                    refreshed_tickers.add(ticker)
                    refreshed += 1
            except Exception:
                pass

            done = min(i + batch_size, len(stale))
            elapsed = time.time() - start_time
            rate = refreshed / elapsed * 60 if elapsed > 0 else 0
            if done % 200 == 0 or done == len(stale):
                print(f'    [{done}/{len(stale)}] Refreshed: {refreshed} | '
                      f'{elapsed:.0f}s | ~{rate:.0f}/min')

        print(f'  [Phase 1] yfinance: {refreshed} refreshed')

        # Phase 2: API fallback for yfinance failures
        remaining = [t for t in stale if t not in refreshed_tickers]
        if remaining:
            print(f'  [Phase 2] API fallback for {len(remaining)} remaining...')
            api_refreshed = 0

            async with aiohttp.ClientSession() as session:
                sem = asyncio.Semaphore(5)

                async def refresh_one(ticker):
                    nonlocal api_refreshed
                    async with sem:
                        # Try Tiingo (best for incremental updates)
                        result = await self._fetch_tiingo(session, ticker, days=10)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_refreshed += 1
                            refreshed_tickers.add(ticker)
                            return
                        await asyncio.sleep(1)

                        # Try Polygon
                        result = await self._fetch_polygon(session, ticker)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_refreshed += 1
                            refreshed_tickers.add(ticker)
                            return

                        failed_tickers.add(ticker)

                for i in range(0, len(remaining), 20):
                    batch = remaining[i:i + 20]
                    await asyncio.gather(*[refresh_one(t) for t in batch])
                    done = min(i + 20, len(remaining))
                    if done % 100 == 0 or done == len(remaining):
                        print(f'    [{done}/{len(remaining)}] API refreshed: {api_refreshed} | '
                              f'Failed: {len(failed_tickers)}')

            refreshed += api_refreshed
            print(f'  [Phase 2] APIs: {api_refreshed} refreshed, {len(failed_tickers)} failed')

        elapsed = time.time() - start_time
        print(f'\n[CACHE] Refresh done in {elapsed:.0f}s: {refreshed} refreshed, '
              f'{len(failed_tickers)} failed')
        return {'refreshed': refreshed, 'failed': len(failed_tickers)}

    def close(self):
        self.conn.close()


# ── CLI ──

async def main():
    parser = argparse.ArgumentParser(description="Stock Data Cache Manager")
    parser.add_argument("--refresh", action="store_true", help="Refresh stale tickers")
    parser.add_argument("--stats", action="store_true", help="Show cache stats")
    parser.add_argument("--force", action="store_true", help="Force re-fetch all")
    args = parser.parse_args()

    cache = DataCache()

    if args.stats:
        s = cache.stats()
        print(f"Cache Stats:")
        print(f"  Tickers: {s['total_tickers']}")
        print(f"  Fresh today: {s['fresh_today']}")
        print(f"  Stale: {s['stale']}")
        print(f"  Total rows: {s['total_rows']}")
        return

    if args.refresh:
        result = await cache.refresh()
        print(f"Refreshed: {result['refreshed']}")
        return

    # Default: populate full universe
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from deep_scanner import STOCK_UNIVERSE
    result = await cache.populate(STOCK_UNIVERSE, force=args.force)
    print(f"\nPopulate complete: {result}")

    cache.close()


if __name__ == "__main__":
    asyncio.run(main())
