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
    if not os.path.exists(SEED_PATH):
        print("[Seed] No seed DB found, skipping")
        return

    need_seed = not os.path.exists(DEST_PATH)

    if not need_seed:
        try:
            conn = sqlite3.connect(DEST_PATH)
            count = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM cache_meta"
            ).fetchone()[0]
            conn.close()
            if count < MIN_TICKERS:
                print(f"[Seed] Volume DB has only {count} tickers (< {MIN_TICKERS}), re-seeding...")
                need_seed = True
            else:
                print(f"[Seed] Volume DB OK ({count} tickers)")
        except Exception as e:
            print(f"[Seed] Volume DB corrupted ({e}), re-seeding...")
            need_seed = True

    if need_seed:
        # Remove corrupted/small DB first
        if os.path.exists(DEST_PATH):
            os.remove(DEST_PATH)
        shutil.copy2(SEED_PATH, DEST_PATH)
        size_mb = os.path.getsize(DEST_PATH) // 1024 // 1024
        print(f"[Seed] Copied stock_cache.db ({size_mb}MB) to volume")


if __name__ == "__main__":
    seed_if_needed()
