"""
NASDAQ Super App - FastAPI Backend
Provides REST API and WebSocket endpoints for real-time stock scanning
"""

# Load .env BEFORE any module that reads os.environ (e.g. data_cache.py)
from dotenv import load_dotenv
load_dotenv()

import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import asyncio
import json
from datetime import datetime, timedelta

from scanner import NASDAQScanner, run_scanner_loop
from sentiment import SentimentEngine
from backtest import BacktestEngine
from macro_policy import (
    calculate_policy_risk_score,
    get_upcoming_events,
    adjust_signal_for_macro,
    full_macro_analysis
)
from api_v2 import router as v2_router, background_monitor, price_level_monitor, warmup_signal_cache, quote_refresh_loop, cache_refresh_loop, extended_hours_refresh_loop, technicals_refresh_loop

# Optional: RAG/LLM (not installed in production slim build)
try:
    from rag_chat import RAGChatSystem, AnalystAgent
    _rag_available = True
except ImportError:
    _rag_available = False


# FastAPI app
app = FastAPI(
    title="NASDAQ Super App API",
    description="Real-time stock scanning with AI analyst",
    version="1.0.0"
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

# Mount V2 router
app.include_router(v2_router)

# Global instances
scanner = NASDAQScanner()
sentiment_engine = SentimentEngine()
if _rag_available:
    rag_system = RAGChatSystem()
    analyst_agent = AnalystAgent(rag_system)
else:
    rag_system = None
    analyst_agent = None
backtest_engine = BacktestEngine(scanner.historical_manager)

# WebSocket connections
active_connections: List[WebSocket] = []


# Pydantic models
class ChatMessage(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    timestamp: str


class CompareRequest(BaseModel):
    ticker1: str
    ticker2: str


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
            await asyncio.sleep(10)  # Wait before restart
            print(f"[INFO] Restarting background task '{name}'...")


# Startup event
@app.on_event("startup")
async def startup_event():
    """Start background scanner on startup"""
    print("Starting NASDAQ Super App backend...")

    # Start scanner in background
    asyncio.create_task(_safe_task("scanner_loop", lambda: run_scanner_loop(scanner)))

    # Start WebSocket broadcast task
    asyncio.create_task(_safe_task("broadcast_updates", broadcast_updates))

    # Start RAG indexing task (only if langchain/chromadb installed)
    if _rag_available:
        asyncio.create_task(_safe_task("rag_indexing", rag_indexing_loop))

    # Start V2 background monitor (health check every 15 min)
    asyncio.create_task(_safe_task("background_monitor", background_monitor))

    # Start price level monitor (stop loss / target alerts every 60s)
    asyncio.create_task(_safe_task("price_level_monitor", price_level_monitor))

    # Warmup signal cache so first portfolio request is fast
    asyncio.create_task(warmup_signal_cache())  # One-shot, no restart needed

    # Centralized quote refresh (replaces per-endpoint Finnhub calls)
    asyncio.create_task(_safe_task("quote_refresh_loop", quote_refresh_loop))

    # Background technicals computation (runs _get_technicals in worker thread)
    asyncio.create_task(_safe_task("technicals_refresh_loop", technicals_refresh_loop))

    # Daily historical cache refresh (keeps stock_cache.db fresh for scanner/backtest)
    asyncio.create_task(_safe_task("cache_refresh_loop", cache_refresh_loop))

    # Extended hours (pre-market / after-hours) quote refresh via yfinance
    asyncio.create_task(_safe_task("extended_hours_refresh", extended_hours_refresh_loop))

    print("Backend started successfully!")


# API Endpoints

@app.get("/")
async def root():
    """Health check"""
    return {
        "status": "online",
        "app": "NASDAQ Super App",
        "version": "1.0.0",
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/scanner/stats")
async def get_scanner_stats():
    """Get scanner statistics"""
    return scanner.get_scanner_stats()


@app.get("/api/stocks/top-signals")
async def get_top_signals(signal_type: Optional[str] = None, limit: int = 20):
    """
    Get top stocks by signal strength

    Query params:
        - signal_type: BUY, SELL, or omit for all
        - limit: Number of results (default 20)
    """
    results = scanner.get_top_signals(signal_type, limit)
    return {"count": len(results), "stocks": results}


@app.get("/api/stocks/most-volatile")
async def get_most_volatile(limit: int = 20):
    """Get stocks with highest price volatility"""
    results = scanner.get_most_volatile(limit)
    return {"count": len(results), "stocks": results}


@app.get("/api/stocks/volume-leaders")
async def get_volume_leaders(limit: int = 20):
    """Get stocks with highest volume"""
    results = scanner.get_volume_leaders(limit)
    return {"count": len(results), "stocks": results}


@app.get("/api/stocks/top-sentiment")
async def get_top_sentiment(limit: int = 20):
    """Get stocks with highest sentiment scores"""
    results = scanner.get_top_sentiment(limit)
    return {"count": len(results), "stocks": results}


@app.get("/api/stocks/search/{ticker}")
async def search_stock(ticker: str):
    """
    Search for a stock - scans it if not already scanned

    This endpoint will:
    1. Check if stock is already scanned
    2. If not, scan it immediately
    3. Return the stock data with score
    """
    ticker = ticker.upper()

    # Check if already scanned
    result = scanner.get_by_ticker(ticker)

    if result:
        return {"status": "found", "stock": result}

    # Not found, scan it now
    print(f"Scanning {ticker} on demand...")
    result = await scanner.scan_ticker(ticker)

    if not result:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found - unable to fetch data")

    # Add to scanner results
    scanner.scan_results[ticker] = result

    return {"status": "scanned", "stock": result}


@app.get("/api/stocks/{ticker}")
async def get_stock_detail(ticker: str):
    """Get detailed data for a specific ticker"""
    result = scanner.get_by_ticker(ticker.upper())

    if not result:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not found or not yet scanned")

    return result


@app.get("/api/sentiment/{ticker}")
async def get_sentiment(ticker: str):
    """Get sentiment analysis for a ticker"""
    sentiment = await sentiment_engine.get_ticker_sentiment(ticker.upper())
    return sentiment


@app.post("/api/sentiment/compare")
async def compare_sentiment(request: CompareRequest):
    """Compare sentiment between two tickers"""
    result = await sentiment_engine.compare_tickers(
        request.ticker1.upper(),
        request.ticker2.upper()
    )
    return result


@app.post("/api/chat")
async def chat(message: ChatMessage):
    """Chat with AI analyst"""
    if not _rag_available:
        raise HTTPException(status_code=503, detail="RAG system not available in production")
    scanner_stats = scanner.get_scanner_stats()
    response = await rag_system.chat(message.message, scanner_stats)
    return ChatResponse(response=response, timestamp=datetime.now().isoformat())


@app.get("/api/chat/history")
async def get_chat_history():
    if not _rag_available:
        return {"history": []}
    return {"history": rag_system.get_chat_history()}


@app.post("/api/chat/clear")
async def clear_chat_history():
    if _rag_available:
        rag_system.clear_history()
    return {"status": "cleared"}


@app.get("/api/research/{ticker}")
async def research_ticker(ticker: str):
    if not _rag_available:
        raise HTTPException(status_code=503, detail="Research agent not available in production")
    result = await analyst_agent.research_ticker(ticker.upper())
    return result


@app.post("/api/research/compare")
async def compare_stocks(request: CompareRequest):
    if not _rag_available:
        raise HTTPException(status_code=503, detail="Research agent not available in production")
    result = await analyst_agent.compare_stocks(request.ticker1.upper(), request.ticker2.upper())
    return {
        "ticker1": request.ticker1.upper(),
        "ticker2": request.ticker2.upper(),
        "analysis": result,
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/scanner/scan-now")
async def trigger_scan(background_tasks: BackgroundTasks):
    """
    Trigger an immediate hot scan

    This is useful for manual refresh
    """
    background_tasks.add_task(scanner.hot_scan)
    return {"status": "scan_triggered", "message": "Hot scan initiated"}


# ========================================
# POSITION TRACKING ENDPOINTS
# ========================================

class PositionCreate(BaseModel):
    ticker: str
    entry_date: str
    entry_price: float
    shares: float
    notes: str = ""


class PositionClose(BaseModel):
    exit_date: str
    exit_price: float


@app.post("/api/positions/add")
async def add_position(position: PositionCreate):
    """Add a new stock position"""
    result = await scanner.position_manager.add_position(
        position.ticker,
        position.entry_date,
        position.entry_price,
        position.shares,
        position.notes
    )
    return result


@app.get("/api/positions")
async def get_positions(include_closed: bool = False):
    """Get all positions"""
    positions = await scanner.position_manager.get_all_positions(include_closed)
    return {"count": len(positions), "positions": positions}


@app.get("/api/positions/{position_id}")
async def get_position_performance(position_id: int):
    """Get detailed performance of a specific position"""
    # Get position
    positions = await scanner.position_manager.get_all_positions(include_closed=True)
    position = next((p for p in positions if p['id'] == position_id), None)

    if not position:
        raise HTTPException(status_code=404, detail="Position not found")

    # Get current stock data
    stock_data = scanner.get_by_ticker(position['ticker'])
    if not stock_data:
        raise HTTPException(status_code=404, detail=f"Stock {position['ticker']} not found")

    # Convert numpy types to Python types for JSON serialization
    clean_stock_data = {
        'signal': stock_data['signal'],
        'rsi': float(stock_data['rsi']),
        'signal_strength': int(stock_data['signal_strength'])
    }

    # Get performance
    performance = await scanner.position_manager.get_position_performance(
        position_id,
        float(stock_data['price']),
        clean_stock_data
    )

    return performance


@app.post("/api/positions/{position_id}/close")
async def close_position(position_id: int, close_data: PositionClose):
    """Close a position"""
    result = await scanner.position_manager.close_position(
        position_id,
        close_data.exit_date,
        close_data.exit_price
    )
    return result


@app.delete("/api/positions/{position_id}")
async def delete_position(position_id: int):
    """Delete a position"""
    result = await scanner.position_manager.delete_position(position_id)
    return result


# ========================================
# ALERT ENDPOINTS
# ========================================

class AlertCreate(BaseModel):
    ticker: str
    alert_type: str  # PRICE or RSI
    condition: str  # ABOVE or BELOW
    target_value: float


@app.post("/api/alerts/create")
async def create_alert(alert: AlertCreate):
    """Create a new price or RSI alert"""
    result = await scanner.alert_manager.create_alert(
        alert.ticker,
        alert.alert_type,
        alert.condition,
        alert.target_value
    )
    return result


@app.get("/api/alerts")
async def get_alerts(ticker: Optional[str] = None, status: str = "active"):
    """Get alerts, optionally filtered by ticker"""
    if status == "triggered":
        alerts = await scanner.alert_manager.get_triggered_alerts(50)
    else:
        alerts = await scanner.alert_manager.get_active_alerts(ticker)

    return {"count": len(alerts), "alerts": alerts}


@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: int):
    """Delete an alert"""
    result = await scanner.alert_manager.delete_alert(alert_id)
    return result


@app.post("/api/alerts/clear-triggered")
async def clear_triggered_alerts():
    """Clear all triggered alerts"""
    result = await scanner.alert_manager.clear_triggered_alerts()
    return result


# ========================================
# HISTORICAL DATA ENDPOINTS
# ========================================

@app.get("/api/historical/{ticker}")
async def get_stock_history(ticker: str, days: int = 365):
    """Get historical data for a ticker"""
    df = await scanner.historical_manager.get_stock_history(ticker.upper(), days)

    if df.empty:
        raise HTTPException(status_code=404, detail=f"No historical data for {ticker}")

    # Convert to JSON
    history = df.to_dict(orient='records')

    return {
        "ticker": ticker.upper(),
        "data_points": len(history),
        "history": history
    }


@app.get("/api/historical/{ticker}/seasonality")
async def get_seasonality(ticker: str):
    """Get seasonality analysis for a ticker"""
    result = await scanner.historical_manager.detect_seasonality(ticker.upper())
    return result


@app.get("/api/historical/{ticker}/spike-prediction")
async def predict_spike(ticker: str):
    """Predict probability of price spike"""
    # Get current stock data
    stock_data = scanner.get_by_ticker(ticker.upper())

    if not stock_data:
        raise HTTPException(status_code=404, detail=f"Stock {ticker} not scanned yet")

    result = await scanner.historical_manager.predict_spike(ticker.upper(), stock_data)
    return result


# ========================================
# BACKTEST ENDPOINTS
# ========================================

@app.get("/api/backtest/{ticker}/{date}")
async def backtest_date(ticker: str, date: str):
    """
    Get signal that was generated on a specific date

    Args:
        ticker: Stock ticker
        date: Date in YYYY-MM-DD format

    Returns:
        Signal data and forward returns
    """
    result = await backtest_engine.backtest_signal(ticker.upper(), date)
    return result


@app.get("/api/backtest/{ticker}/range")
async def backtest_range(ticker: str, start_date: str, end_date: str):
    """
    Backtest all signals for a ticker over a date range

    Query params:
        - start_date: YYYY-MM-DD
        - end_date: YYYY-MM-DD
    """
    result = await backtest_engine.backtest_ticker_range(
        ticker.upper(),
        start_date,
        end_date
    )
    return result


@app.get("/api/backtest/performance")
async def get_performance(days: int = 30):
    """Get overall signal performance statistics"""
    result = await backtest_engine.get_signal_accuracy_summary(days)
    return result


@app.post("/api/backtest/compare-position")
async def compare_position(request: Dict):
    """
    Compare what our signal said vs actual position outcome

    Request body:
        {
            "ticker": "MU",
            "entry_date": "2025-12-20",
            "entry_price": 288.0
        }
    """
    ticker = request.get("ticker")
    entry_date = request.get("entry_date")
    entry_price = request.get("entry_price")

    if not all([ticker, entry_date, entry_price]):
        raise HTTPException(status_code=400, detail="Missing required fields")

    result = await backtest_engine.compare_signal_vs_actual(
        ticker.upper(),
        entry_date,
        float(entry_price)
    )

    return result


# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time stock updates

    Clients receive:
    - Scanner stats
    - Top signals
    - Volume leaders
    """
    await websocket.accept()
    active_connections.append(websocket)

    try:
        while True:
            # Keep connection alive and listen for messages
            data = await websocket.receive_text()

            # Echo or handle client messages if needed
            if data == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)
        print("WebSocket client disconnected")


async def broadcast_updates():
    """
    Background task to broadcast updates to all WebSocket clients
    Runs every 15 seconds (aligned with scanner)
    """
    while True:
        await asyncio.sleep(15)  # Broadcast every 15 seconds

        if not active_connections:
            continue

        try:
            # Prepare update payload
            update = {
                "type": "scanner_update",
                "timestamp": datetime.now().isoformat(),
                "stats": scanner.get_scanner_stats(),
                "top_buys": scanner.get_top_signals("BUY", 10),
                "top_sells": scanner.get_top_signals("SELL", 10),
                "most_volatile": scanner.get_most_volatile(10),
                "volume_leaders": scanner.get_volume_leaders(10)
            }

            # Broadcast to all connected clients
            disconnected = []
            for connection in active_connections:
                try:
                    await connection.send_json(update)
                except Exception as e:
                    print(f"Error sending to client: {e}")
                    disconnected.append(connection)

            # Remove disconnected clients
            for conn in disconnected:
                if conn in active_connections:
                    active_connections.remove(conn)

        except Exception as e:
            print(f"Error in broadcast_updates: {e}")


# Background task to index scan results into RAG system
async def rag_indexing_loop():
    """Background task to continuously index scan results"""
    while True:
        await asyncio.sleep(30)  # Index every 30 seconds

        try:
            # Get all scan results
            for ticker, stock_data in scanner.scan_results.items():
                # Index stock data
                await rag_system.index_stock_data(stock_data)

                # Index news if available
                if stock_data.get("article_count", 0) > 0:
                    sentiment = await sentiment_engine.get_ticker_sentiment(ticker)
                    for article in sentiment.get("articles", []):
                        await rag_system.index_news_article(article, ticker)

            print("RAG indexing complete")

        except Exception as e:
            print(f"Error in RAG indexing: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
