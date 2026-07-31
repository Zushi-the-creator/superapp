"""Targeted backfill of the 2026-06-22 -> 2026-07-13 feed-outage gap.

The Tiingo plan lapse froze the feed; the plan was reactivated 2026-07-22 but the
missing bars were never filled. Result: 15 trading days where 30-47% of the
universe has no bar. Backtests over that window silently pick from whichever
subset happened to refresh — a survivorship bias inside our own cache.

Fetches a 60d window (covers 2026-06-01 onward) for the affected tickers only.
20 concurrent, matching data_cache.refresh() — well inside the 10K/hr cap.
"""
import asyncio, os, sys, time
import aiohttp, pandas as pd

for line in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')):
    if line.startswith('TIINGO_API_KEY='):
        os.environ['TIINGO_API_KEY'] = line.split('=', 1)[1].strip()

import data_cache
from data_cache import DataCache

cache = DataCache()
tickers = [t.strip() for t in open('/tmp/backfill_tickers.txt') if t.strip()]
print(f"backfilling {len(tickers)} tickers, 60d window, 20 concurrent")

ok = 0; fail = []
t0 = time.time()


async def main():
    global ok
    sem = asyncio.Semaphore(20)
    async with aiohttp.ClientSession() as session:
        async def one(tk):
            global ok
            async with sem:
                df = await cache._fetch_tiingo(session, tk, days=60, min_rows=1)
                if isinstance(df, pd.DataFrame) and len(df):
                    try:
                        cache._rebase_if_adjusted(tk, df)
                    except Exception:
                        pass
                    cache.store(tk, df)
                    ok += 1
                else:
                    fail.append(tk)
                n = ok + len(fail)
                if n % 200 == 0:
                    print(f"  {n}/{len(tickers)}  ok={ok} fail={len(fail)}  {time.time()-t0:.0f}s", flush=True)
        await asyncio.gather(*[one(t) for t in tickers])

asyncio.run(main())
print(f"\ndone in {time.time()-t0:.0f}s   ok={ok}  failed={len(fail)}")
if fail:
    print(f"failed sample: {fail[:30]}")
    open('/tmp/backfill_failed.txt', 'w').write('\n'.join(fail))
