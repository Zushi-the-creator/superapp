"""
NASDAQ Super App - FastAPI Backend
All trading logic served via V2 API router (api_v2.py).
"""

# Load .env BEFORE any module that reads os.environ
from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from datetime import datetime

# Bump on every deploy that changes runtime behaviour so a deploy can be
# verified from the PUBLIC health endpoint (GET /) without needing fly logs.
# 2026-07-22: Yahoo-primary refresh (breaks the Tiingo daily-cap freeze).
BUILD_TAG = "2026-07-22-yahoo-refresh"

from api_v2 import (
    router as v2_router,
    background_monitor, price_level_monitor, warmup_signal_cache,
    quote_refresh_loop, cache_refresh_loop, extended_hours_refresh_loop,
    technicals_refresh_loop, signal_tracker_loop, sector_intel_loop,
)


# FastAPI app
app = FastAPI(
    title="NASDAQ Super App API",
    description="Real-time stock scanning with AI analyst",
    version="2.6.0"
)

# CORS middleware
_cors_env = os.environ.get("CORS_ORIGINS", "*")
_cors_origins = ["*"] if _cors_env == "*" else _cors_env.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount V2 router (all /api/v2/* endpoints)
app.include_router(v2_router)


# Background task wrapper — logs exceptions instead of silently dying
async def _safe_task(name: str, coro):
    """Run a background coroutine with crash logging and auto-restart."""
    while True:
        try:
            await coro()
            break  # If coro returns normally, stop
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"[ERROR] Background task '{name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(10)
            print(f"[INFO] Restarting background task '{name}'...")


@app.on_event("startup")
async def startup_event():
    """Start all background loops on startup."""
    print("Starting NASDAQ Super App backend "
          f"[build {BUILD_TAG}, refresh source: Yahoo-primary/Tiingo-fallback]...")

    # V2 background monitor (health check every 15 min)
    asyncio.create_task(_safe_task("background_monitor", background_monitor))

    # Price level monitor (stop loss / target alerts every 60s)
    asyncio.create_task(_safe_task("price_level_monitor", price_level_monitor))

    # Warmup signal cache so first portfolio request is fast
    asyncio.create_task(warmup_signal_cache())  # One-shot, no restart needed

    # Centralized quote refresh (replaces per-endpoint Finnhub calls)
    asyncio.create_task(_safe_task("quote_refresh_loop", quote_refresh_loop))

    # Background technicals computation (runs _get_technicals in worker thread)
    asyncio.create_task(_safe_task("technicals_refresh_loop", technicals_refresh_loop))

    # Daily historical cache refresh (keeps stock_cache.db fresh for scanner/backtest)
    asyncio.create_task(_safe_task("cache_refresh_loop", cache_refresh_loop))

    # Extended hours (pre-market / after-hours) quote refresh
    asyncio.create_task(_safe_task("extended_hours_refresh", extended_hours_refresh_loop))

    # Signal tracker — daily snapshot of top-20 entries + backfill returns
    # (NEW 2026-06-02: builds the feedback loop for score-vs-realized analysis)
    asyncio.create_task(_safe_task("signal_tracker_loop", signal_tracker_loop))

    # Sector intelligence — news narratives (45 min) + ticker->sector Finnhub backfill
    asyncio.create_task(_safe_task("sector_intel_loop", sector_intel_loop))

    print("Backend started successfully!")


@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "online",
        "app": "NASDAQ Super App",
        "version": "2.6.0",
        "build": BUILD_TAG,
        "refresh_source": "yahoo-primary",
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
