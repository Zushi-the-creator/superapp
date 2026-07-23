"""
Startup script — seeds the Fly.io volume with stock_cache.db if cold.
Called before uvicorn starts.
"""
import os
import shutil
import sqlite3

SEED_PATH = "/app/seed/stock_cache.db"
DEST_PATH = "/app/data/stock_cache.db"
MIN_TICKERS = 500  # If volume DB has fewer tickers, re-seed


def seed_if_needed():
    # Cheap sanity check — open the DB and confirm a table query works.
    # `PRAGMA integrity_check` was running for several minutes on the 700MB
    # volume DB on shared-1x Fly.io machines, blocking uvicorn startup. The
    # SQLite engine validates pages lazily during normal queries, so a quick
    # SELECT is enough to detect a corrupted/missing DB without paying the
    # full-scan cost.
    if os.path.exists(DEST_PATH):
        try:
            conn = sqlite3.connect(DEST_PATH, timeout=10)
            count = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM cache_meta"
            ).fetchone()[0]
            avg_bars = conn.execute(
                "SELECT AVG(cnt) FROM (SELECT COUNT(*) as cnt FROM daily_prices GROUP BY ticker LIMIT 100)"
            ).fetchone()[0] or 0
            conn.close()
            print(f"[Seed] Volume DB: {count} tickers, ~{avg_bars:.0f} avg bars")
            if count >= MIN_TICKERS and avg_bars >= 1000:
                return
            if count >= MIN_TICKERS and avg_bars < 1000:
                print(f"[Seed] Data too shallow ({avg_bars:.0f} bars < 1000). Re-seeding with 10yr data...")
        except Exception as e:
            print(f"[Seed] Volume DB unreadable ({e}), removing...")
            try:
                os.remove(DEST_PATH)
            except Exception:
                pass
            for suffix in ['-wal', '-shm']:
                try:
                    os.remove(DEST_PATH + suffix)
                except Exception:
                    pass

    # Try seed file first
    if os.path.exists(SEED_PATH):
        try:
            shutil.copy2(SEED_PATH, DEST_PATH)
            size_mb = os.path.getsize(DEST_PATH) // 1024 // 1024
            print(f"[Seed] Copied stock_cache.db ({size_mb}MB) to volume")
            return
        except Exception as e:
            print(f"[Seed] Copy failed: {e}")

    # No seed available — app will create empty DB and populate via Tiingo
    print("[Seed] No seed DB available — will populate via Tiingo on startup")


if __name__ == "__main__":
    seed_if_needed()
