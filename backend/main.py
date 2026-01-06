"""
NASDAQ Super App - FastAPI Backend
Provides REST API and WebSocket endpoints for real-time stock scanning
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict
import asyncio
import json
from datetime import datetime

from scanner import NASDAQScanner, run_scanner_loop
from sentiment import SentimentEngine
from rag_chat import RAGChatSystem, AnalystAgent


# FastAPI app
app = FastAPI(
    title="NASDAQ Super App API",
    description="Real-time stock scanning with AI analyst",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
scanner = NASDAQScanner()
sentiment_engine = SentimentEngine()
rag_system = RAGChatSystem()
analyst_agent = AnalystAgent(rag_system)

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
                await websocket.send_text("pong")

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
@app.on_event("startup")
async def start_rag_indexing():
    """Background task to continuously index scan results"""
    async def index_loop():
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

    asyncio.create_task(index_loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
