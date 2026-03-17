"""One-time backfill: fetch 5yr history for all stocks missing it."""
import sqlite3, requests, time, os

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stock_cache.db")
conn = sqlite3.connect(DB)
c = conn.cursor()

c.execute("SELECT ticker, COUNT(*) as cnt FROM daily_prices GROUP BY ticker HAVING cnt BETWEEN 100 AND 1199 ORDER BY cnt ASC")
need = c.fetchall()
print(f"Stocks needing backfill: {len(need)}")

fetched = 0; failed = 0; t0 = time.time()
for i, (ticker, cnt) in enumerate(need):
    if i % 100 == 0 and i > 0:
        elapsed = time.time() - t0
        print(f"  {i}/{len(need)} | fetched: {fetched} | failed: {failed} | {elapsed:.0f}s", flush=True)
    try:
        r = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5y&interval=1d",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200: failed += 1; continue
        chart = r.json().get("chart", {}).get("result", [{}])[0]
        ts = chart.get("timestamp", [])
        quotes = chart.get("indicators", {}).get("quote", [{}])[0]
        if not ts or not quotes.get("close"): failed += 1; continue
        from datetime import datetime
        dates = [datetime.utcfromtimestamp(t).strftime('%Y-%m-%d') for t in ts]
        existing = set(r[0] for r in c.execute("SELECT date FROM daily_prices WHERE ticker=?", (ticker,)).fetchall())
        new_rows = 0
        for j, d in enumerate(dates):
            if d in existing: continue
            cl = quotes["close"][j]
            if cl is None: continue
            op = quotes["open"][j] if quotes.get("open") else cl
            hi = quotes["high"][j] if quotes.get("high") else cl
            lo = quotes["low"][j] if quotes.get("low") else cl
            vo = quotes["volume"][j] if quotes.get("volume") else 0
            c.execute("INSERT OR IGNORE INTO daily_prices VALUES (?,?,?,?,?,?,?)", (ticker, d, op, hi, lo, cl, vo))
            new_rows += 1
        if new_rows > 0: conn.commit(); fetched += 1
        time.sleep(0.3)
    except Exception: failed += 1

print(f"\nDone in {time.time()-t0:.0f}s | Fetched: {fetched}/{len(need)} | Failed: {failed}")
c.execute("SELECT COUNT(*) FROM (SELECT ticker, COUNT(*) as cnt FROM daily_prices GROUP BY ticker HAVING cnt >= 1200)")
print(f"Stocks with 5yr+: {c.fetchone()[0]}")
conn.close()
