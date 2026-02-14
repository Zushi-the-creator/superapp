"""
NASDAQ Super App - FastAPI Backend
Provides REST API and WebSocket endpoints for real-time stock scanning
"""

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
from rag_chat import RAGChatSystem, AnalystAgent
from backtest import BacktestEngine
from macro_policy import (
    calculate_policy_risk_score,
    get_upcoming_events,
    adjust_signal_for_macro,
    full_macro_analysis
)
from api_v2 import router as v2_router, background_monitor


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
rag_system = RAGChatSystem()
analyst_agent = AnalystAgent(rag_system)
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


# Startup event
@app.on_event("startup")
async def startup_event():
    """Start background scanner on startup"""
    print("Starting NASDAQ Super App backend...")

    # Start scanner in background
    asyncio.create_task(run_scanner_loop(scanner))

    # Start WebSocket broadcast task
    asyncio.create_task(broadcast_updates())

    # Start RAG indexing task
    asyncio.create_task(rag_indexing_loop())

    # Start V2 background monitor (health check every 15 min)
    asyncio.create_task(background_monitor())

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
    """
    Chat with AI analyst

    Request body:
        {
            "message": "Why is NVDA a buy?"
        }
    """
    scanner_stats = scanner.get_scanner_stats()
    response = await rag_system.chat(message.message, scanner_stats)

    return ChatResponse(
        response=response,
        timestamp=datetime.now().isoformat()
    )


@app.get("/api/chat/history")
async def get_chat_history():
    """Get chat history"""
    return {"history": rag_system.get_chat_history()}


@app.post("/api/chat/clear")
async def clear_chat_history():
    """Clear chat history"""
    rag_system.clear_history()
    return {"status": "cleared"}


@app.get("/api/research/{ticker}")
async def research_ticker(ticker: str):
    """
    Perform comprehensive research on a ticker using AI agent

    This uses multi-step reasoning to analyze technical, sentiment, and news
    """
    result = await analyst_agent.research_ticker(ticker.upper())
    return result


@app.post("/api/research/compare")
async def compare_stocks(request: CompareRequest):
    """
    Compare two stocks using AI agent

    Request body:
        {
            "ticker1": "AAPL",
            "ticker2": "MSFT"
        }
    """
    result = await analyst_agent.compare_stocks(
        request.ticker1.upper(),
        request.ticker2.upper()
    )

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
    shares: int
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


# ========================================
# PORTFOLIO DASHBOARD API (NEW - Lean UI)
# ========================================

@app.get("/api/portfolio/dashboard")
async def get_portfolio_dashboard():
    """
    Get all data needed for the lean portfolio dashboard.
    Returns positions, models, signals, forecasts, and market insights.
    ALWAYS fetches fresh data on every call.
    """
    import requests

    # Helper to fetch fresh price from Yahoo with RSI
    def fetch_fresh_price(ticker: str) -> dict:
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}'
            params = {'interval': '1d', 'range': '20d'}  # Need more data for RSI
            headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
            resp = requests.get(url, params=params, headers=headers, timeout=5)
            data = resp.json()

            if 'chart' in data and data['chart']['result']:
                result = data['chart']['result'][0]
                meta = result.get('meta', {})
                quotes = result['indicators']['quote'][0]
                closes = [c for c in quotes['close'] if c is not None]

                current = meta.get('regularMarketPrice', closes[-1] if closes else 0)
                prev_close = meta.get('previousClose', closes[-2] if len(closes) > 1 else current)
                change_pct = ((current - prev_close) / prev_close * 100) if prev_close else 0

                # Calculate RSI(14)
                rsi = 50.0  # default
                if len(closes) >= 15:
                    gains = []
                    losses = []
                    for i in range(1, 15):
                        diff = closes[-(i)] - closes[-(i+1)]
                        if diff > 0:
                            gains.append(diff)
                            losses.append(0)
                        else:
                            gains.append(0)
                            losses.append(abs(diff))
                    avg_gain = sum(gains) / 14 if gains else 0.0001
                    avg_loss = sum(losses) / 14 if losses else 0.0001
                    rs = avg_gain / avg_loss if avg_loss > 0 else 100
                    rsi = 100 - (100 / (1 + rs))

                return {
                    'price': current,
                    'change_pct': change_pct,
                    'rsi': rsi,
                    'source': 'Yahoo Finance (Live)'
                }
        except Exception as e:
            print(f"Fresh fetch error for {ticker}: {e}")
        return None

    # Portfolio positions - UPDATED 2026-01-20 after portfolio cleanup
    positions = [
        {"ticker": "QQQ", "shares": 2.379, "entry_price": 614.50, "cost_basis": 1461.72, "model": "V15.0", "entry_date": "2026-01-20", "allocation": 45},
        {"ticker": "NVDA", "shares": 5.6698, "entry_price": 179.90, "cost_basis": 1020.00, "model": "V22.0", "entry_date": "2026-01-20", "allocation": 30},
        {"ticker": "MU", "shares": 2.5, "entry_price": 376.50, "cost_basis": 941.25, "model": "V21.0", "entry_date": "2026-01-20", "allocation": 25}
    ]

    # Profit targets for exit strategy
    profit_targets = {
        "NVDA": {"target": 187.00, "stop": 172.00, "target_profit": 40.23, "note": "The Spring - 4% move = monthly goal"},
        "MU": {"target": 390.00, "stop": 360.00, "target_profit": 33.75, "note": "Relative strength leader"},
        "QQQ": {"target": 625.00, "stop": 590.00, "target_profit": 24.97, "note": "Market anchor"}
    }

    # Buy recommendations when TIME STOP triggers (Rule: When saying SELL, say what to BUY)
    buy_recommendations = {
        "QQQ": {"replace_with": "HOLD", "reason": "Core position - rebuy on RSI(2) < 5 dips", "limit_price": None},
        "NVDA": {"replace_with": "CEG", "reason": "Constellation Energy at $290 support", "limit_price": 290.00},
        "MU": {"replace_with": "HOLD", "reason": "Relative strength leader - rebuy on pullback", "limit_price": None}
    }

    data_source = "Pending"

    # Get FRESH prices for each position
    for pos in positions:
        # Try fresh fetch first
        fresh = fetch_fresh_price(pos["ticker"])
        if fresh:
            pos["current_price"] = float(fresh['price'])
            pos["change_pct"] = float(fresh['change_pct'])
            pos["rsi"] = float(fresh.get('rsi', 50.0))
            data_source = fresh['source']
        else:
            # Fallback to scanner cache
            stock_data = scanner.get_by_ticker(pos["ticker"])
            if stock_data:
                pos["current_price"] = float(stock_data.get("price", pos["entry_price"]))
                pos["change_pct"] = float(stock_data.get("change_pct", 0))
                pos["rsi"] = float(stock_data.get("rsi", 50.0))
                data_source = "Scanner Cache"
            else:
                pos["current_price"] = pos["entry_price"]
                pos["change_pct"] = 0
                pos["rsi"] = 50.0  # Default RSI when no data available

        # Calculate days held for TIME STOP
        entry_date = datetime.strptime(pos["entry_date"], "%Y-%m-%d")
        pos["days_held"] = (datetime.now() - entry_date).days
        pos["time_stop_triggered"] = pos["days_held"] >= 7

        # Calculate P&L
        pos["current_value"] = pos["shares"] * pos["current_price"]
        pos["pnl"] = pos["current_value"] - pos["cost_basis"]
        pos["pnl_pct"] = (pos["pnl"] / pos["cost_basis"]) * 100

        # Calculate macro/policy risk (V23.0)
        macro_risk = calculate_policy_risk_score(pos["ticker"])
        pos["macro_risk"] = {
            "score": macro_risk["risk_score"],
            "level": macro_risk["risk_level"],
            "position_multiplier": macro_risk["position_multiplier"],
            "tariff_exposure": macro_risk["components"]["tariff_exposure"],
            "event_risk": macro_risk["components"]["event_risk"]
        }

        # Determine signal based on model rules
        if pos["time_stop_triggered"]:
            pos["signal"] = "SELL"
            pos["signal_reason"] = f"TIME STOP: {pos['days_held']} days (max 7)"
            if pos["ticker"] in buy_recommendations:
                pos["buy_recommendation"] = buy_recommendations[pos["ticker"]]
        else:
            base_signal = "HOLD"
            base_reason = f"Day {pos['days_held']}/7"

            # Adjust signal for macro risk
            if macro_risk["risk_level"] == "CRITICAL":
                pos["signal"] = "TRIM"
                pos["signal_reason"] = f"{base_reason} | ⚠️ CRITICAL policy risk - reduce exposure"
            elif macro_risk["risk_level"] == "HIGH" and macro_risk.get("imminent_events"):
                pos["signal"] = "WATCH"
                pos["signal_reason"] = f"{base_reason} | ⚠️ HIGH policy risk - event imminent"
            else:
                pos["signal"] = base_signal
                pos["signal_reason"] = base_reason

    # Models with accuracy - UPDATED for new portfolio
    models = [
        {
            "version": "V15.0",
            "name": "Connors RSI(2)",
            "ticker": "QQQ",
            "win_rate": 83.3,
            "avg_return": 3.59,
            "description": "Larry Connors mean reversion - market anchor",
            "entry_rule": "RSI(2) < 5 AND Price > SMA(200)",
            "exit_rule": "Price > SMA(5) or 7-day hold"
        },
        {
            "version": "V22.0",
            "name": "Support Sniper",
            "ticker": "NVDA",
            "win_rate": 87.5,
            "avg_return": 4.2,
            "description": "Buy at major support floors during panic",
            "entry_rule": "Price at institutional support + RSI(2) < 10",
            "exit_rule": "RSI(2) > 80 OR Price > target OR 7-day hold"
        },
        {
            "version": "V21.0",
            "name": "Relative Strength",
            "ticker": "MU",
            "win_rate": 82.0,
            "avg_return": 3.8,
            "description": "Buy stocks showing strength during weakness",
            "entry_rule": "Green during market red day + Volume confirmation",
            "exit_rule": "Loses relative strength OR RSI(5) > 75 OR 7-day hold"
        }
    ]

    # Calculate portfolio totals
    total_cost = sum(p["cost_basis"] for p in positions)
    total_value = sum(p["current_value"] for p in positions)
    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost) * 100

    # Profit-Taking Plan - targets for monthly goal
    execution_plan = {
        "title": "Profit-Taking Plan",
        "goal": "$37 monthly profit (1%)",
        "status": "ACTIVE - Waiting for targets",
        "targets": [
            {"ticker": "NVDA", "entry": 179.90, "target": 187.00, "move": "+3.9%", "profit": 40.23, "note": "THE SPRING - this alone hits monthly goal"},
            {"ticker": "MU", "entry": 376.50, "target": 390.00, "move": "+3.6%", "profit": 33.75, "note": "Relative strength leader"},
            {"ticker": "QQQ", "entry": 614.50, "target": 625.00, "move": "+1.7%", "profit": 24.97, "note": "Market anchor"}
        ],
        "stops": [
            {"ticker": "NVDA", "stop": 172.00, "loss": -44.77},
            {"ticker": "MU", "stop": 360.00, "loss": -41.25},
            {"ticker": "QQQ", "stop": 590.00, "loss": -58.34}
        ],
        "strategy": "Any ONE target hit = Monthly goal achieved. Hold until target or 7-day time stop."
    }

    # Market Insights - Fresh research data
    market_insights = [
        {
            "date": "2026-01-20",
            "type": "EXECUTION",
            "title": "Portfolio Cleanup Complete",
            "impact": "BULLISH",
            "affected": ["NVDA", "MU", "QQQ"],
            "summary": "Sold laggards (COIN, VST, LLY). Bought kings at discount during Greenland Tariff panic.",
            "analysis": "NVDA bought at $180 support floor. MU was green during crash (relative strength). Position for recovery."
        },
        {
            "date": "2026-01-20",
            "type": "TECHNICAL",
            "title": "NVDA $180 Support Hold",
            "impact": "BULLISH",
            "affected": ["NVDA"],
            "summary": "NVDA touched $180 institutional support and bounced. We bought the literal bottom.",
            "analysis": "Major support floor confirmed. Target $187-195 for profit taking. Stop at $172."
        },
        {
            "date": "2026-01-20",
            "type": "SMART_MONEY",
            "title": "MU Relative Strength",
            "impact": "BULLISH",
            "affected": ["MU"],
            "summary": "MU was the ONLY stock green during morning crash. Strong institutional buying.",
            "analysis": "When a stock stays green during panic, institutions are accumulating. Follow the smart money."
        },
        {
            "date": "2026-01-20",
            "type": "AVOIDED",
            "title": "CEG Dead Cat Bounce",
            "impact": "SAVED",
            "affected": ["CEG"],
            "summary": "Did NOT buy CEG at $305. It fell to $297. Saved $25 potential loss.",
            "analysis": "Model correctly identified bounce as unsustainable. Watch for $290 entry."
        }
    ]

    # Daily suggestions - profit taking focused
    suggestions = []

    for pos in positions:
        ticker = pos["ticker"]
        if ticker in profit_targets:
            target_info = profit_targets[ticker]
            pct_to_target = ((target_info["target"] - pos["current_price"]) / pos["current_price"]) * 100
            pct_to_stop = ((pos["current_price"] - target_info["stop"]) / pos["current_price"]) * 100

            if pos["current_price"] >= target_info["target"]:
                suggestions.append({
                    "ticker": ticker,
                    "action": "TAKE PROFIT",
                    "reason": f"Target ${target_info['target']} reached! +${target_info['target_profit']:.2f} profit",
                    "urgency": "HIGH",
                    "type": "SELL"
                })
            elif pos["current_price"] <= target_info["stop"]:
                suggestions.append({
                    "ticker": ticker,
                    "action": "STOP LOSS",
                    "reason": f"Stop ${target_info['stop']} triggered. Exit to preserve capital.",
                    "urgency": "HIGH",
                    "type": "SELL"
                })
            else:
                suggestions.append({
                    "ticker": ticker,
                    "action": "HOLD",
                    "reason": f"{pct_to_target:+.1f}% to target ${target_info['target']} | {target_info['note']}",
                    "urgency": "LOW",
                    "type": "HOLD",
                    "target": target_info["target"],
                    "stop": target_info["stop"],
                    "potential_profit": target_info["target_profit"]
                })

    # Add watchlist item
    suggestions.append({
        "ticker": "CEG",
        "action": "WATCH",
        "reason": "Avoided at $305, now ~$297. Watch for $290 entry point.",
        "urgency": "LOW",
        "type": "WATCH"
    })

    # Load historical data for charts with REAL DATES + PROJECTIONS
    charts_data = {}
    for pos in positions:
        ticker = pos["ticker"]
        chart_points = []

        try:
            df = await scanner.historical_manager.get_stock_history(ticker, 60)
            if not df.empty:
                # Get last 30 days of actual data with dates
                df = df.tail(30).reset_index()
                for _, row in df.iterrows():
                    date_val = row.get('Date', row.get('index', ''))
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime('%Y-%m-%d')
                    else:
                        date_str = str(date_val)[:10]

                    chart_points.append({
                        "date": date_str,
                        "price": float(row['Close']),
                        "type": "actual"
                    })
        except Exception as e:
            print(f"Error fetching chart data for {ticker}: {e}")

        # If no data, generate from current price going back
        if not chart_points:
            current_price = pos["current_price"]
            today = datetime.now()
            for i in range(30, 0, -1):
                past_date = today - timedelta(days=i)
                # Simulate slight price variation
                variation = 1 + ((30 - i) / 30) * (pos["pnl_pct"] / 100)
                price = current_price / variation
                chart_points.append({
                    "date": past_date.strftime('%Y-%m-%d'),
                    "price": round(price, 2),
                    "type": "estimated"
                })
            # Add today
            chart_points.append({
                "date": today.strftime('%Y-%m-%d'),
                "price": current_price,
                "type": "actual"
            })

        # Add PROJECTIONS for next 30 days based on model
        model_for_ticker = next((m for m in models if ticker in m["ticker"]), None)
        if model_for_ticker:
            avg_return = model_for_ticker["avg_return"]  # e.g., 2.49%
            win_rate = model_for_ticker["win_rate"]  # e.g., 85.7%

            # Expected monthly return = avg_return * (win_rate/100) * ~4 trades/month
            # Conservative: assume 2 trades per month
            expected_monthly_return = avg_return * (win_rate / 100) * 2
            daily_return = expected_monthly_return / 30

            last_price = chart_points[-1]["price"] if chart_points else pos["current_price"]
            last_date = datetime.strptime(chart_points[-1]["date"], '%Y-%m-%d') if chart_points else datetime.now()

            for i in range(1, 31):
                future_date = last_date + timedelta(days=i)
                # Projected price with model's expected return
                projected_price = last_price * (1 + (daily_return / 100) * i)
                chart_points.append({
                    "date": future_date.strftime('%Y-%m-%d'),
                    "price": round(projected_price, 2),
                    "type": "projected"
                })

        charts_data[ticker] = chart_points

    # ML Learning Progression - Track model improvements over time
    ml_progression = [
        {
            "date": "2026-01-10",
            "version": "V1.0",
            "name": "Basic RSI/EMA",
            "avg_win_rate": 52.4,
            "note": "Initial baseline model"
        },
        {
            "date": "2026-01-12",
            "version": "V11.0-V14.0",
            "name": "Hybrid Models",
            "avg_win_rate": 61.2,
            "note": "Tested Buy Dip, Support/Resist, Divergence"
        },
        {
            "date": "2026-01-14",
            "version": "V15.0-V19.0",
            "name": "High Accuracy",
            "avg_win_rate": 78.5,
            "note": "Connors RSI(2), Extreme Oversold, Triple Confirm"
        },
        {
            "date": "2026-01-15",
            "version": "V20.0",
            "name": "COIN Optimized",
            "avg_win_rate": 80.0,
            "note": "RSI(5)+BB combo for volatile stocks"
        },
        {
            "date": "2026-01-16",
            "version": "V21.0",
            "name": "ML Framework",
            "avg_win_rate": 83.0,
            "note": "Walk-forward validation, ensemble voting"
        }
    ]

    # Data freshness timestamps
    # Determine actual data source used
    data_source = "Pending"
    for pos in positions:
        stock_data = scanner.get_by_ticker(pos["ticker"])
        if stock_data and stock_data.get("price"):
            data_source = "Live API (Finnhub/TwelveData)"
            break

    data_timestamps = {
        "positions_updated": datetime.now().isoformat(),
        "prices_source": data_source,
        "models_validated": "2026-01-15T11:56:16",
        "last_backtest": "2026-01-15T11:41:04",
        "charts_period": "30 days history + 30 days projection"
    }

    # Get upcoming macro events (V23.0)
    macro_events = get_upcoming_events(days_ahead=14)

    return {
        "timestamp": datetime.now().isoformat(),
        "data_timestamps": data_timestamps,
        "portfolio": {
            "total_deposited": 3700,
            "total_cost": total_cost,
            "total_value": total_value,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
            "monthly_target": 3700 * 1.01,  # 1% target
            "target_gap": (3700 * 1.01) - total_value
        },
        "positions": positions,
        "models": models,
        "suggestions": suggestions,
        "charts": charts_data,
        "ml_progression": ml_progression,
        "execution_plan": execution_plan,
        "market_insights": market_insights,
        "profit_targets": profit_targets,
        "macro_events": macro_events
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
