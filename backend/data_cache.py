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
import io
import asyncio
import aiohttp
import argparse
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List, Dict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'stock_cache.db')
POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "6f632a60d6188ebc1b92221e83d4fba37e2a5c42")
IS_FLY = bool(os.environ.get("FLY_APP_NAME"))
FMP_KEY = os.environ.get("FMP_API_KEY", "")


class DataCache:
    """SQLite-backed OHLCV cache with Tiingo bulk fetching."""

    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._local = __import__('threading').local()
        self._create_tables()

    @property
    def conn(self):
        """Thread-local SQLite connection — safe for concurrent access from asyncio executor threads."""
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

    def get_bulk(self, tickers: List[str], days: int = 730) -> Dict[str, pd.DataFrame]:
        """Bulk read cached data for many tickers - single SQL query, much faster than individual reads."""
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        upper_tickers = [t.upper() for t in tickers]

        # Single bulk query
        placeholders = ','.join(['?'] * len(upper_tickers))
        rows = self.conn.execute(
            f'SELECT ticker, date, open, high, low, close, volume FROM daily_prices '
            f'WHERE ticker IN ({placeholders}) AND date >= ? ORDER BY ticker, date',
            upper_tickers + [cutoff]
        ).fetchall()

        # Group by ticker
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in rows:
            grouped[r[0]].append(r[1:])  # (date, open, high, low, close, volume)

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
        # Get actual total row count for this ticker (not just inserted rows)
        actual_count = self.conn.execute(
            'SELECT COUNT(*) FROM daily_prices WHERE ticker = ?', (ticker,)
        ).fetchone()[0]
        # Get actual date range from stored data
        date_range = self.conn.execute(
            'SELECT MIN(date), MAX(date) FROM daily_prices WHERE ticker = ?', (ticker,)
        ).fetchone()
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
        """Fetch from Tiingo API. Full access: 10K req/hr, 100K req/day, 40GB/mo.
        IMPORTANT: Use days=10 for refresh, days=400 for populate (saves bandwidth).
        min_rows: minimum rows required (0 = use 50 for full fetch, 1 for refresh)."""
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end = datetime.now().strftime('%Y-%m-%d')
        url = f'https://api.tiingo.com/tiingo/daily/{ticker}/prices'
        params = {'startDate': start, 'endDate': end, 'token': TIINGO_KEY}
        headers = {'Content-Type': 'application/json'}
        required = min_rows if min_rows > 0 else (50 if days > 30 else 1)

        try:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    print(f"[Tiingo] Rate limited for {ticker}")
                    return None
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data or not isinstance(data, list) or len(data) < required:
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
        start = end - timedelta(days=800)
        url = (f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/'
               f'{start.strftime("%Y-%m-%d")}/{end.strftime("%Y-%m-%d")}')
        params = {'adjusted': 'true', 'sort': 'asc', 'limit': 5000,
                  'apiKey': POLYGON_KEY}

        try:
            async with session.get(url, params=params,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    print(f"[Polygon] Rate limited for {ticker}")
                    return None
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
                    print(f"[FMP] Rate limited for {ticker}")
                    return None
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

    # ── Stooq Fetch (unlimited, no API key) ──

    async def _fetch_stooq(self, session: aiohttp.ClientSession,
                           ticker: str, days: int = 800) -> Optional[pd.DataFrame]:
        """Fetch from Stooq (unlimited, no API key needed). Primary free source."""
        end = datetime.now()
        start = end - timedelta(days=days)
        url = (f"https://stooq.com/q/d/l/?s={ticker.lower()}.us"
               f"&d1={start.strftime('%Y%m%d')}&d2={end.strftime('%Y%m%d')}&i=d")
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
                if 'Date' not in text or len(text) < 100:
                    return None
                df = pd.read_csv(io.StringIO(text))
                if len(df) < 50:
                    return None
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.set_index('Date').sort_index()
                for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                    if col in df.columns:
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
            data = yf.download(batch_str, period="2y", progress=False,
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
        Multi-source parallel populate.

        Strategy: Tiingo PRIMARY (full access, high concurrency), yfinance fallback.
        - Tiingo: Full access (~500+/hr, 50 concurrent) — PRIMARY
        - yfinance: Bulk batches of 20 — FALLBACK (skipped on Fly.io where it's blocked)
        - Stooq/Polygon/FMP: Final fallback for remaining failures
        """
        import time
        tickers = [t.upper() for t in tickers]
        cached = set() if force else set(self.get_cached_tickers())
        to_fetch = list(dict.fromkeys(t for t in tickers if t not in cached))

        if not to_fetch:
            print(f'[CACHE] All {len(tickers)} tickers already cached')
            return {'fetched': 0, 'cached': len(cached), 'failed': 0}

        print(f'[CACHE] Populate: {len(to_fetch)} tickers to fetch '
              f'({len(cached)} already cached)')
        if IS_FLY:
            print(f'  Fly.io detected — skipping yfinance, Tiingo primary')
        print(f'  Sources: Tiingo (primary, 50 concurrent) → yfinance (fallback) → Stooq/Polygon/FMP')

        fetched = 0
        failed_tickers = set()
        fetched_tickers = set()
        start_time = time.time()

        # Phase 1: Tiingo bulk (PRIMARY — 20 concurrent to stay under 10K/hr)
        # Full access: 10K req/hr, 100K/day, 40GB/mo
        # 400 days history for populate (enough for SMA200 + backtest)
        if TIINGO_KEY:
            print(f'\n  [Phase 1] Tiingo bulk fetch ({len(to_fetch)} tickers, 20 concurrent, 400d)...')
            tiingo_sem = asyncio.Semaphore(20)
            tiingo_fetched = 0

            async with aiohttp.ClientSession() as session:
                async def fetch_tiingo_one(ticker):
                    nonlocal tiingo_fetched
                    async with tiingo_sem:
                        result = await self._fetch_tiingo(session, ticker, days=400)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            tiingo_fetched += 1
                            fetched_tickers.add(ticker)

                # Process in batches of 100 for progress reporting
                for i in range(0, len(to_fetch), 100):
                    batch = to_fetch[i:i + 100]
                    await asyncio.gather(*[fetch_tiingo_one(t) for t in batch])
                    done = min(i + 100, len(to_fetch))
                    elapsed = time.time() - start_time
                    rate = tiingo_fetched / elapsed * 60 if elapsed > 0 else 0
                    remaining_count = len(to_fetch) - done
                    eta_min = remaining_count / rate if rate > 0 else 0
                    print(f'    [{done}/{len(to_fetch)}] OK: {tiingo_fetched} | '
                          f'{elapsed:.0f}s | ~{rate:.0f}/min | ETA: {eta_min:.1f}min')

            fetched += tiingo_fetched
            print(f'  [Phase 1] Tiingo: {tiingo_fetched} fetched')

        # Phase 2: yfinance fallback (skipped on Fly.io where it's blocked)
        remaining = [t for t in to_fetch if t not in fetched_tickers]
        if remaining and not IS_FLY:
            print(f'\n  [Phase 2] yfinance fallback for {len(remaining)} remaining...')
            loop = asyncio.get_running_loop()
            yf_batch_size = 20
            yf_fetched = 0
            yf_consecutive_failures = 0

            for i in range(0, len(remaining), yf_batch_size):
                batch = remaining[i:i + yf_batch_size]
                batch_before = yf_fetched
                try:
                    results = await loop.run_in_executor(
                        None, self._fetch_yfinance_batch, batch)
                    for ticker, df in results.items():
                        self.store(ticker, df)
                        fetched_tickers.add(ticker)
                        yf_fetched += 1
                except Exception:
                    pass

                if yf_fetched == batch_before:
                    yf_consecutive_failures += 1
                else:
                    yf_consecutive_failures = 0

                if yf_consecutive_failures >= 3:
                    print(f'    yfinance blocked (3 consecutive failed batches). Skipping.')
                    break

                done = min(i + yf_batch_size, len(remaining))
                elapsed = time.time() - start_time
                rate = yf_fetched / elapsed * 60 if elapsed > 0 else 0
                if done % 100 == 0 or done == len(remaining):
                    print(f'    [{done}/{len(remaining)}] yfinance OK: {yf_fetched} | '
                          f'{elapsed:.0f}s | ~{rate:.0f}/min')

            fetched += yf_fetched
            print(f'  [Phase 2] yfinance: {yf_fetched} fetched')

        # Phase 3: Stooq/Polygon/FMP fallback for anything still missing
        remaining = [t for t in to_fetch if t not in fetched_tickers]
        if remaining:
            print(f'\n  [Phase 3] Stooq/API fallback for {len(remaining)} remaining...')
            api_fetched = 0
            stooq_sem = asyncio.Semaphore(10)

            async with aiohttp.ClientSession() as session:
                async def fetch_fallback(ticker):
                    nonlocal api_fetched
                    # Try Stooq first (unlimited, no key)
                    async with stooq_sem:
                        result = await self._fetch_stooq(session, ticker)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_fetched += 1
                            fetched_tickers.add(ticker)
                            return
                    # Try Polygon
                    if POLYGON_KEY:
                        result = await self._fetch_polygon(session, ticker)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_fetched += 1
                            fetched_tickers.add(ticker)
                            return
                    # Try FMP
                    if FMP_KEY:
                        result = await self._fetch_fmp(session, ticker)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_fetched += 1
                            fetched_tickers.add(ticker)
                            return
                    failed_tickers.add(ticker)

                for i in range(0, len(remaining), 50):
                    batch = remaining[i:i + 50]
                    await asyncio.gather(*[fetch_fallback(t) for t in batch])
                    done = min(i + 50, len(remaining))
                    elapsed = time.time() - start_time
                    if done % 100 == 0 or done == len(remaining):
                        print(f'    [{done}/{len(remaining)}] Fallback OK: {api_fetched} | '
                              f'Failed: {len(failed_tickers)} | {elapsed:.0f}s')

            fetched += api_fetched
            print(f'  [Phase 3] Fallback: {api_fetched} fetched, {len(failed_tickers)} failed')

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

        Strategy: Tiingo PRIMARY (50 concurrent, full access), yfinance fallback.
        On Fly.io: skip yfinance entirely (blocked).
        ~3,000 tickers in ~5-10 minutes with Tiingo full access.
        """
        import time

        if tickers:
            stale = [t.upper() for t in tickers if not self.is_fresh(t)]
        else:
            stale = self.get_stale_tickers()

        if not stale:
            print('[CACHE] All tickers already up to date')
            return {'refreshed': 0, 'failed': 0}

        print(f'[CACHE] Refresh: {len(stale)} stale tickers')
        if IS_FLY:
            print(f'  Fly.io detected — Tiingo only (skipping yfinance)')
        start_time = time.time()
        refreshed = 0
        refreshed_tickers = set()
        failed_tickers = set()

        # Phase 1: Tiingo bulk refresh (PRIMARY — 20 concurrent, 10-day window)
        # 10-day window = minimal bandwidth (~0.5KB per ticker vs ~20KB for full history)
        if TIINGO_KEY:
            print(f'  [Phase 1] Tiingo refresh ({len(stale)} tickers, 20 concurrent, 10d)...')
            tiingo_refreshed = 0
            tiingo_sem = asyncio.Semaphore(20)

            async with aiohttp.ClientSession() as session:
                async def refresh_tiingo(ticker):
                    nonlocal tiingo_refreshed
                    async with tiingo_sem:
                        result = await self._fetch_tiingo(session, ticker, days=10, min_rows=1)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            tiingo_refreshed += 1
                            refreshed_tickers.add(ticker)

                for i in range(0, len(stale), 100):
                    batch = stale[i:i + 100]
                    await asyncio.gather(*[refresh_tiingo(t) for t in batch])
                    done = min(i + 100, len(stale))
                    elapsed = time.time() - start_time
                    rate = tiingo_refreshed / elapsed * 60 if elapsed > 0 else 0
                    remaining_count = len(stale) - done
                    eta_min = remaining_count / rate if rate > 0 else 0
                    print(f'    [{done}/{len(stale)}] OK: {tiingo_refreshed} | '
                          f'{elapsed:.0f}s | ~{rate:.0f}/min | ETA: {eta_min:.1f}min')

            refreshed += tiingo_refreshed
            print(f'  [Phase 1] Tiingo: {tiingo_refreshed} refreshed')

        # Phase 2: yfinance fallback (skipped on Fly.io)
        remaining = [t for t in stale if t not in refreshed_tickers]
        if remaining and not IS_FLY:
            print(f'  [Phase 2] yfinance fallback for {len(remaining)} remaining...')
            loop = asyncio.get_running_loop()
            batch_size = 20
            yf_refreshed = 0
            yf_consecutive_failures = 0

            for i in range(0, len(remaining), batch_size):
                batch = remaining[i:i + batch_size]
                batch_before = yf_refreshed
                try:
                    results = await loop.run_in_executor(
                        None, self._refresh_yfinance_batch, batch)
                    for ticker, df in results.items():
                        self.store(ticker, df)
                        refreshed_tickers.add(ticker)
                        yf_refreshed += 1
                except Exception:
                    pass

                if yf_refreshed == batch_before:
                    yf_consecutive_failures += 1
                else:
                    yf_consecutive_failures = 0

                if yf_consecutive_failures >= 3:
                    print(f'    yfinance blocked (3 consecutive failed batches). Skipping.')
                    break

                done = min(i + batch_size, len(remaining))
                elapsed = time.time() - start_time
                rate = yf_refreshed / elapsed * 60 if elapsed > 0 else 0
                if done % 200 == 0 or done == len(remaining):
                    print(f'    [{done}/{len(remaining)}] yfinance OK: {yf_refreshed} | '
                          f'{elapsed:.0f}s | ~{rate:.0f}/min')

            refreshed += yf_refreshed
            print(f'  [Phase 2] yfinance: {yf_refreshed} refreshed')

        # Phase 3: Stooq/Polygon fallback for remaining
        remaining = [t for t in stale if t not in refreshed_tickers]
        if remaining:
            print(f'  [Phase 3] Stooq/API fallback for {len(remaining)} remaining...')
            api_refreshed = 0

            async with aiohttp.ClientSession() as session:
                sem = asyncio.Semaphore(10)

                async def refresh_fallback(ticker):
                    nonlocal api_refreshed
                    async with sem:
                        # Stooq (unlimited, no key)
                        result = await self._fetch_stooq(session, ticker, days=10)
                        if isinstance(result, pd.DataFrame):
                            self.store(ticker, result)
                            api_refreshed += 1
                            refreshed_tickers.add(ticker)
                            return
                        # Polygon
                        if POLYGON_KEY:
                            result = await self._fetch_polygon(session, ticker)
                            if isinstance(result, pd.DataFrame):
                                self.store(ticker, result)
                                api_refreshed += 1
                                refreshed_tickers.add(ticker)
                                return
                        failed_tickers.add(ticker)

                for i in range(0, len(remaining), 50):
                    batch = remaining[i:i + 50]
                    await asyncio.gather(*[refresh_fallback(t) for t in batch])
                    done = min(i + 50, len(remaining))
                    elapsed = time.time() - start_time
                    if done % 100 == 0 or done == len(remaining):
                        print(f'    [{done}/{len(remaining)}] Fallback OK: {api_refreshed} | '
                              f'Failed: {len(failed_tickers)} | {elapsed:.0f}s')

            refreshed += api_refreshed
            print(f'  [Phase 3] Fallback: {api_refreshed} refreshed, {len(failed_tickers)} failed')

        elapsed = time.time() - start_time
        print(f'\n[CACHE] Refresh done in {elapsed:.0f}s: {refreshed} refreshed, '
              f'{len(failed_tickers)} failed')
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
