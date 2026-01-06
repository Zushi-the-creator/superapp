# NASDAQ Super App

> **Real-time stock scanning with AI-powered analysis** | 15-second rotational scanner • Technical indicators • Sentiment analysis • RAG-based chat

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11-blue.svg)
![Node](https://img.shields.io/badge/node-20-green.svg)
![Docker](https://img.shields.io/badge/docker-required-blue.svg)

---

## 🚀 Features

### Core Capabilities

- **15-Second Rotational Scanner**: Intelligently scans top NASDAQ stocks in batches, prioritizing high-volume "hot" stocks
- **Multi-Signal Analysis**: Combines RSI, EMA crossovers, volume spikes, and sentiment for comprehensive signals
- **AI Analyst Chat**: RAG-powered chatbot using ChromaDB and Ollama (local LLM) for contextual stock analysis
- **Real-time Updates**: WebSocket-based live feed with sub-second latency
- **Calm Design UI**: Modern, dark-mode interface with high-contrast signal highlighting (2026 trend)

### Technical Indicators

- **RSI (14)**: Relative Strength Index for overbought/oversold conditions
- **EMA Crossovers**: Fast (9) and Slow (21) exponential moving averages
- **Volume Analysis**: Real-time volume ratio compared to 20-day average
- **Combined Score**: Weighted algorithm (60% technical + 40% sentiment)

### Sentiment Analysis

- **Multi-Source News**: Yahoo Finance + Google News RSS feeds
- **VADER Sentiment**: Advanced NLP sentiment scoring (-1 to +1)
- **Article-Level Analysis**: Individual article sentiment with aggregation
- **Comparative Analysis**: Side-by-side ticker sentiment comparison

### AI Features

- **Local LLM**: Runs Llama 3.2 (or similar) via Ollama - 100% free, unlimited queries
- **RAG Pipeline**: Retrieval-Augmented Generation with ChromaDB vector storage
- **Contextual Answers**: Chat queries pull from live scanner data + news
- **Multi-Step Research**: Agent can perform comprehensive ticker research

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     NASDAQ Super App                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Frontend (Next.js 15 + Tailwind)                          │
│  ├── 3-Column Layout (Ticker Feed | Chart | Chat)         │
│  ├── Real-time WebSocket Updates (15s refresh)            │
│  └── Calm Design System (Dark Mode)                       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Backend (FastAPI + Python 3.11)                           │
│  ├── Scanner Engine (yfinance + Background Tasks)         │
│  ├── Signal Engine (RSI, EMA, Volume)                     │
│  ├── Sentiment Engine (VADER + BeautifulSoup)             │
│  ├── RAG Chat (ChromaDB + LangGraph)                      │
│  └── REST API + WebSocket Server                          │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Infrastructure (Docker Compose)                           │
│  ├── Ollama (Local LLM - Llama 3.2)                       │
│  ├── ChromaDB (Vector Database)                           │
│  └── Persistent Volumes                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📋 Prerequisites

### Required Software

- **Docker** & **Docker Compose**: [Install Docker](https://docs.docker.com/get-docker/)
- **Git**: For cloning the repository

### System Requirements

- **RAM**: 8GB minimum (16GB recommended for Ollama)
- **Storage**: 5GB free space (LLM models can be large)
- **CPU**: Multi-core recommended for parallel scanning
- **OS**: Linux, macOS, or Windows with WSL2

---

## 🚀 Quick Start (5 Minutes)

### 1. Clone the Repository

```bash
git clone <repository-url>
cd superapp
```

### 2. Start All Services

```bash
docker-compose up -d
```

This command will:
- Build the FastAPI backend
- Build the Next.js frontend
- Start Ollama (LLM server)
- Start ChromaDB (vector database)
- Create persistent volumes for data

### 3. Pull the LLM Model

```bash
# Wait ~30 seconds for Ollama to initialize, then:
docker exec -it $(docker ps -q -f name=ollama) ollama pull llama3.2
```

**Note**: This downloads ~2GB. Alternative models:
- `llama3.1` (larger, more accurate)
- `mistral` (fast, efficient)
- `phi3` (smaller, faster)

### 4. Access the Application

- **Frontend**: [http://localhost:3000](http://localhost:3000)
- **Backend API**: [http://localhost:8000](http://localhost:8000)
- **API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

### 5. Wait for First Scan

The scanner performs an initial full scan of ~100 NASDAQ stocks. This takes **30-60 seconds**.

You'll see data populate in real-time as the scan completes.

---

## 📖 Detailed Setup

### Development Mode

For active development with hot-reload:

```bash
# Backend (FastAPI with auto-reload)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend (Next.js dev server)
cd frontend
npm install
npm run dev
```

### Environment Variables

Create `.env` files if you want to customize:

**Backend** (`.env` in `backend/` directory):
```bash
OLLAMA_HOST=http://ollama:11434
CHROMA_HOST=chromadb
CHROMA_PORT=8000
```

**Frontend** (`.env.local` in `frontend/` directory):
```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

### Production Build

```bash
# Build for production
docker-compose -f docker-compose.yml build

# Run in production mode
docker-compose -f docker-compose.yml up -d
```

---

## 🎯 Usage Guide

### Understanding the Interface

#### Left Column: Ticker Feed
- **Buy Signals**: Stocks with bullish indicators
- **Sell Signals**: Stocks with bearish indicators
- **Volatile**: Highest price movement stocks
- **Volume Leaders**: Highest volume ratio stocks

Click any stock to view detailed analysis.

#### Center Column: Chart & Reasoning
- **Price Chart**: Current price with change percentage
- **Signal Overview**: Primary signal (BUY/SELL/HOLD) with strength
- **Technical Indicators**: RSI, EMA, Volume ratio
- **Sentiment**: News sentiment analysis
- **Reasoning Card**: 3-point analysis framework

#### Right Column: AI Analyst Chat
- Ask questions about any stock
- Compare multiple tickers
- Get explanations of technical indicators
- Receive real-time contextual answers

### Example Chat Queries

```
"Why is NVDA a buy right now?"
"Compare AAPL vs MSFT sentiment in the last hour"
"What does RSI mean and why is it important?"
"Show me the top 5 buy signals"
"Explain the EMA crossover for TSLA"
```

### API Endpoints

Full API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

**Key Endpoints**:

```bash
# Get scanner statistics
GET /api/scanner/stats

# Get top buy signals
GET /api/stocks/top-signals?signal_type=BUY&limit=20

# Get stock detail
GET /api/stocks/{ticker}

# Get sentiment for ticker
GET /api/sentiment/{ticker}

# Chat with AI analyst
POST /api/chat
{
  "message": "Why is AAPL a buy?"
}

# Compare two stocks
POST /api/sentiment/compare
{
  "ticker1": "AAPL",
  "ticker2": "MSFT"
}
```

---

## 🔧 Configuration

### Scanner Configuration

Edit `backend/scanner.py`:

```python
# Modify scanner parameters
self.scan_batch_size = 50        # Stocks per batch
self.hot_batch_size = 20         # Hot stocks to prioritize
```

### Signal Parameters

Edit `backend/signals.py`:

```python
# Adjust technical indicators
self.rsi_period = 14             # RSI lookback period
self.ema_fast = 9                # Fast EMA period
self.ema_slow = 21               # Slow EMA period
self.volume_threshold = 2.0      # Volume spike threshold (2x avg)
```

### Ticker Universe

Edit `backend/scanner.py` → `_load_nasdaq_tickers()`:

```python
# Add more tickers to the list
top_nasdaq = [
    "AAPL", "MSFT", "GOOGL", ...
    # Add your tickers here
]
```

---

## 🐳 Docker Commands

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f frontend
docker-compose logs -f ollama
```

### Restart Services

```bash
# Restart all
docker-compose restart

# Restart specific service
docker-compose restart backend
```

### Stop Services

```bash
docker-compose down
```

### Rebuild After Code Changes

```bash
# Rebuild backend
docker-compose up -d --build backend

# Rebuild frontend
docker-compose up -d --build frontend
```

---

## 🧪 Testing

### Backend Tests

```bash
cd backend
python -m pytest tests/
```

### API Testing

Use the Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs) to test endpoints interactively.

### Scanner Testing

```bash
# Trigger manual scan
curl -X POST http://localhost:8000/api/scanner/scan-now
```

---

## 📊 Performance

### Scanner Performance

- **Initial Full Scan**: 30-60 seconds (100 stocks)
- **Hot Scan**: 5-10 seconds (20 stocks)
- **Refresh Rate**: 15 seconds
- **Data Latency**: <1 second (yfinance)

### LLM Performance

- **Llama 3.2**: 2-5 seconds per query (CPU)
- **Llama 3.2 (GPU)**: <1 second per query
- **Context Window**: 8K tokens
- **Concurrent Queries**: 1 (sequential processing)

### Optimization Tips

1. **Use GPU for Ollama**: Significantly faster inference
2. **Reduce Ticker Universe**: Focus on specific stocks
3. **Adjust Scan Intervals**: Increase for less frequent updates
4. **Use Smaller LLM**: `phi3` or `mistral` for faster responses

---

## 🛠️ Troubleshooting

### Ollama Not Responding

```bash
# Check Ollama status
docker logs $(docker ps -q -f name=ollama)

# Restart Ollama
docker-compose restart ollama

# Ensure model is pulled
docker exec -it $(docker ps -q -f name=ollama) ollama list
```

### ChromaDB Connection Error

```bash
# Check ChromaDB logs
docker logs $(docker ps -q -f name=chromadb)

# Restart ChromaDB
docker-compose restart chromadb
```

### Scanner Not Updating

```bash
# Check backend logs
docker-compose logs -f backend

# Trigger manual scan
curl -X POST http://localhost:8000/api/scanner/scan-now
```

### Frontend Not Loading

```bash
# Check frontend logs
docker-compose logs -f frontend

# Rebuild frontend
docker-compose up -d --build frontend
```

### WebSocket Disconnections

- Check network stability
- Ensure backend is running: `docker ps`
- Check CORS settings in `backend/main.py`

---

## 🌟 Key Innovations (2026)

### 1. Local LLM Integration
- **No API Costs**: Run unlimited queries on your hardware
- **Privacy**: All data stays local
- **Customization**: Fine-tune your own models

### 2. Rotation Strategy
- **Smart Prioritization**: Focus on high-volume stocks
- **Rate Limit Friendly**: Batch requests to avoid bans
- **Adaptive Scanning**: Automatically adjusts to market conditions

### 3. Narrative RAG
- **Context-Aware**: Searches last 100 news articles
- **Multi-Modal**: Combines technical + sentiment + news
- **Real-Time**: Updates vector DB every 30 seconds

### 4. Calm UI Design
- **Stability-First Palette**: Slate grays, deep blues
- **Reduced Fatigue**: Minimizes eye strain during long sessions
- **High-Contrast Signals**: Green/red glows for action zones
- **Monospaced Consistency**: Terminal-inspired aesthetics

---

## 📝 Tech Stack Summary

### Backend
- **FastAPI**: Modern async Python web framework
- **yfinance**: Free stock data (Yahoo Finance)
- **VADER**: Sentiment analysis
- **ChromaDB**: Vector database for RAG
- **LangChain/LangGraph**: LLM orchestration

### Frontend
- **Next.js 15**: React framework with App Router
- **Tailwind CSS**: Utility-first CSS framework
- **Lucide Icons**: Modern icon library
- **Recharts**: Charting library (ready to use)

### Infrastructure
- **Docker Compose**: Container orchestration
- **Ollama**: Local LLM server
- **WebSocket**: Real-time bidirectional communication

### Free Services Used
- **Yahoo Finance**: Stock prices (via yfinance)
- **Google News RSS**: News articles
- **Ollama**: Local LLM inference

**Total Cost**: $0/month 🎉

---

## 🚀 Future Enhancements

### Planned Features

- [ ] **Historical Charts**: Interactive price charts with Recharts
- [ ] **Portfolio Tracking**: Save and track your positions
- [ ] **Alerts System**: Email/push notifications for signals
- [ ] **Backtesting Engine**: Test strategies on historical data
- [ ] **Options Analysis**: Greeks, IV, and option chains
- [ ] **Sector Heatmaps**: Visual sector performance
- [ ] **Multi-Timeframe Analysis**: 1m, 5m, 1h, 1d charts
- [ ] **Dark Pool Data**: Institutional flow indicators
- [ ] **Social Sentiment**: Reddit, Twitter integration

### Community Contributions Welcome!

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **yfinance**: For free, reliable stock data
- **Ollama**: For making local LLMs accessible
- **ChromaDB**: For the excellent vector database
- **FastAPI**: For the outstanding async framework
- **Next.js**: For the incredible React framework

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/nasdaq-super-app/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/nasdaq-super-app/discussions)
- **Email**: support@example.com

---

## ⚠️ Disclaimer

This application is for **educational and informational purposes only**. It is **not financial advice**.

- Always conduct your own research
- Never invest more than you can afford to lose
- Past performance does not guarantee future results
- Markets are inherently risky
- Consult a licensed financial advisor before making investment decisions

**The creators of this software are not responsible for any financial losses incurred through its use.**

---

## 🎯 Getting Started Checklist

- [ ] Docker and Docker Compose installed
- [ ] Repository cloned
- [ ] `docker-compose up -d` executed
- [ ] Ollama model pulled (`llama3.2`)
- [ ] Frontend accessible at `localhost:3000`
- [ ] Backend API accessible at `localhost:8000`
- [ ] First scan completed (30-60 seconds)
- [ ] Chat interface tested
- [ ] WebSocket connection established (green dot in header)

**Ready to trade? Let's go! 🚀📈**
