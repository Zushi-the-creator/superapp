"""
SQLite Data Cache for Historical Stock Data
============================================
Stores OHLCV data locally. Uses Tiingo API exclusively for fetching.

Usage:
    cache = DataCache()
    await cache.populate(['AAPL', 'MSFT', ...])  # One-time bulk load
    await cache.refresh()                         # Daily update (10-day window)
    df = cache.get('AAPL', 365)                   # Instant local read

    python3 data_cache.py                         # Populate full universe
    python3 data_cache.py --refresh               # Update today's data
    python3 data_cache.py --stats                 # Show cache stats

Tiingo limits (full access):
    - 10,000 requests/hour
    - 100,000 requests/day
    - 40 GB bandwidth/month
    - IMPORTANT: Use days=10 for refresh (~0.5KB/ticker), days=400 for populate (~20KB/ticker)
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
TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "6f632a60d6188ebc1b92221e83d4fba37e2a5c42")
POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
FMP_KEY = os.environ.get("FMP_API_KEY", "")
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "d5ed7a9r01qjckl3djkgd5ed7a9r01qjckl3djl0")


class DataCache:
    """SQLite-backed OHLCV cache — Tiingo only."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._local = __import__('threading').local()
        self._create_tables()

    @property
    def conn(self):
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

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

    def get(self, ticker: str, days: int = 730) -> Optional[pd.DataFrame]:
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

    def get_bulk(self, tickers: List[str], days: int = 730) -> Dict[str, pd.DataFrame]:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        upper_tickers = [t.upper() for t in tickers]
        placeholders = ','.join(['?'] * len(upper_tickers))
        rows = self.conn.execute(
            f'SELECT ticker, date, open, high, low, close, volume FROM daily_prices '
            f'WHERE ticker IN ({placeholders}) AND date >= ? ORDER BY ticker, date',
            upper_tickers + [cutoff]
        ).fetchall()
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in rows:
            grouped[r[0]].append(r[1:])
        result = {}
        for ticker, data_rows in grouped.items():
            if len(data_rows) < 50:
                continue
            df = pd.DataFrame(data_rows, columns=['Date', 'Open', 'High', 'Low', 'Close', 'Volume'])
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.set_index('Date')
            result[ticker] = df
        return result

    def get_cached_tickers(self) -> List[str]:
        rows = self.conn.execute('SELECT ticker FROM cache_meta').fetchall()
        return [r[0] for r in rows]

    def is_fresh(self, ticker: str) -> bool:
        today = datetime.now().strftime('%Y-%m-%d')
        row = self.conn.execute(
            'SELECT last_updated FROM cache_meta WHERE ticker = ?', (ticker.upper(),)
        ).fetchone()
        return row is not None and row[0] >= today

    def get_stale_tickers(self) -> List[str]:
        today = datetime.now().strftime('%Y-%m-%d')
        rows = self.conn.execute(
            'SELECT ticker FROM cache_meta WHERE last_updated < ?', (today,)
        ).fetchall()
        return [r[0] for r in rows]

    def stats(self) -> Dict:
        total = self.conn.execute('SELECT COUNT(DISTINCT ticker) FROM cache_meta').fetchone()[0]
        today = datetime.now().strftime('%Y-%m-%d')
        fresh = self.conn.execute('SELECT COUNT(*) FROM cache_meta WHERE last_updated >= ?', (today,)).fetchone()[0]
        total_rows = self.conn.execute('SELECT COUNT(*) FROM daily_prices').fetchone()[0]
        return {'total_tickers': total, 'fresh_today': fresh, 'stale': total - fresh, 'total_rows': total_rows}

    # ── Write ──

    def store(self, ticker: str, df: pd.DataFrame):
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
        self.conn.executemany('INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
        actual_count = self.conn.execute('SELECT COUNT(*) FROM daily_prices WHERE ticker = ?', (ticker,)).fetchone()[0]
        date_range = self.conn.execute('SELECT MIN(date), MAX(date) FROM daily_prices WHERE ticker = ?', (ticker,)).fetchone()
        self.conn.execute(
            'INSERT OR REPLACE INTO cache_meta VALUES (?, ?, ?, ?, ?)',
            (ticker, datetime.now().strftime('%Y-%m-%d'),
             date_range[0] or rows[0][1], date_range[1] or rows[-1][1], actual_count)
        )
        self.conn.commit()

    # ── Tiingo Fetch ──

    async def _fetch_tiingo(self, session: aiohttp.ClientSession,
                            ticker: str, days: int = 400,
                            min_rows: int = 0) -> Optional[pd.DataFrame]:
        """Fetch from Tiingo. Use days=10 for refresh, days=400 for populate."""
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end = datetime.now().strftime('%Y-%m-%d')
        url = f'https://api.tiingo.com/tiingo/daily/{ticker}/prices'
        params = {'startDate': start, 'endDate': end, 'token': TIINGO_KEY}
        headers = {'Content-Type': 'application/json'}
        required = min_rows if min_rows > 0 else (50 if days > 30 else 1)

        try:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 429:
                    await asyncio.sleep(2)
                    return None
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data or not isinstance(data, list) or len(data) < required:
                    return None
                df = pd.DataFrame(data)
                df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
                df = df.set_index('date').sort_index()
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

    # ── Bulk Operations ──

    async def populate(self, tickers: List[str], force: bool = False) -> Dict:
        """Bulk fetch via Tiingo (400d history, 20 concurrent)."""
        import time
        tickers = [t.upper() for t in tickers]
        cached = set() if force else set(self.get_cached_tickers())
        to_fetch = list(dict.fromkeys(t for t in tickers if t not in cached))

        if not to_fetch:
            print(f'[CACHE] All {len(tickers)} tickers already cached')
            return {'fetched': 0, 'cached': len(cached), 'failed': 0}

        print(f'[CACHE] Populate: {len(to_fetch)} tickers (Tiingo, 20 concurrent, 400d)')
        start_time = time.time()
        fetched = 0
        failed_tickers = set()
        sem = asyncio.Semaphore(20)

        async with aiohttp.ClientSession() as session:
            async def fetch_one(ticker):
                nonlocal fetched
                async with sem:
                    result = await self._fetch_tiingo(session, ticker, days=400)
                    if isinstance(result, pd.DataFrame):
                        self.store(ticker, result)
                        fetched += 1
                    else:
                        failed_tickers.add(ticker)

            for i in range(0, len(to_fetch), 100):
                batch = to_fetch[i:i + 100]
                await asyncio.gather(*[fetch_one(t) for t in batch])
                done = min(i + 100, len(to_fetch))
                elapsed = time.time() - start_time
                rate = fetched / elapsed * 60 if elapsed > 0 else 0
                eta = (len(to_fetch) - done) / rate if rate > 0 else 0
                print(f'  [{done}/{len(to_fetch)}] OK: {fetched} | '
                      f'Failed: {len(failed_tickers)} | {elapsed:.0f}s | ~{rate:.0f}/min | ETA: {eta:.1f}min')

        elapsed = time.time() - start_time
        print(f'[CACHE] Done in {elapsed:.0f}s: {fetched} fetched, {len(failed_tickers)} failed')
        return {'fetched': fetched, 'cached': len(cached), 'failed': len(failed_tickers)}

    async def refresh(self, tickers: Optional[List[str]] = None) -> Dict:
        """Daily refresh via Tiingo (10d window, 20 concurrent). Minimal bandwidth."""
        import time

        if tickers:
            stale = [t.upper() for t in tickers if not self.is_fresh(t)]
        else:
            stale = self.get_stale_tickers()

        if not stale:
            print('[CACHE] All tickers up to date')
            return {'refreshed': 0, 'failed': 0}

        print(f'[CACHE] Refresh: {len(stale)} stale tickers (Tiingo, 20 concurrent, 10d)')
        start_time = time.time()
        refreshed = 0
        failed_tickers = set()
        sem = asyncio.Semaphore(20)

        async with aiohttp.ClientSession() as session:
            async def refresh_one(ticker):
                nonlocal refreshed
                async with sem:
                    result = await self._fetch_tiingo(session, ticker, days=10, min_rows=1)
                    if isinstance(result, pd.DataFrame):
                        self.store(ticker, result)
                        refreshed += 1
                    else:
                        failed_tickers.add(ticker)

            for i in range(0, len(stale), 100):
                batch = stale[i:i + 100]
                await asyncio.gather(*[refresh_one(t) for t in batch])
                done = min(i + 100, len(stale))
                elapsed = time.time() - start_time
                rate = refreshed / elapsed * 60 if elapsed > 0 else 0
                eta = (len(stale) - done) / rate if rate > 0 else 0
                print(f'  [{done}/{len(stale)}] OK: {refreshed} | '
                      f'Failed: {len(failed_tickers)} | {elapsed:.0f}s | ~{rate:.0f}/min | ETA: {eta:.1f}min')

        elapsed = time.time() - start_time
        print(f'[CACHE] Refresh done in {elapsed:.0f}s: {refreshed} refreshed, {len(failed_tickers)} failed')
        return {'refreshed': refreshed, 'failed': len(failed_tickers)}

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


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
        print(f"Cache: {s['total_tickers']} tickers | Fresh: {s['fresh_today']} | Stale: {s['stale']} | Rows: {s['total_rows']}")
        return

    if args.refresh:
        result = await cache.refresh()
        print(f"Refreshed: {result['refreshed']}, Failed: {result['failed']}")
        return

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from deep_scanner import STOCK_UNIVERSE
    result = await cache.populate(STOCK_UNIVERSE, force=args.force)
    print(f"Populate complete: {result}")

    cache.close()


if __name__ == "__main__":
    asyncio.run(main())
