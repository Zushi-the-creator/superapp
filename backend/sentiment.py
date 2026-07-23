"""
News Sentiment Analysis Engine
Primary: Tiingo News API (rich descriptions, multi-ticker, tagged)
Fallback: Google News RSS
Sentiment: VADER (title + description combined)
Daily logging: Stores all articles in news_log table for future backtesting
"""

import asyncio
import aiohttp
import os
import sqlite3
from typing import List, Dict
from datetime import datetime, timedelta, date
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import feedparser

_DB_PATH = os.path.join(os.path.dirname(__file__), "data", "stock_cache.db")
_TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "")


def _ensure_news_log():
    """Create news_log table for historical news storage."""
    conn = sqlite3.connect(_DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS news_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            published_date TEXT,
            title TEXT,
            description TEXT,
            source TEXT,
            tags TEXT,
            sentiment_score REAL,
            sentiment_label TEXT,
            fetch_date TEXT,
            UNIQUE(ticker, published_date, title)
        )
    ''')
    conn.execute('''
        CREATE INDEX IF NOT EXISTS idx_news_log_ticker_date
        ON news_log (ticker, published_date)
    ''')
    conn.commit()
    conn.close()


# Ensure table exists on import
try:
    _ensure_news_log()
except Exception:
    pass


class SentimentEngine:
    """Analyze sentiment from news articles using VADER + Tiingo News"""

    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()
        self.cache = {}  # Simple in-memory cache
        self.cache_duration = 300  # 5 minutes

    async def get_news_for_ticker(self, ticker: str) -> List[Dict]:
        """Get news articles for a specific ticker.
        Primary: Tiingo News API (richer data, descriptions, tags)
        Fallback: Google News RSS
        """
        # Check cache
        cache_key = f"news_{ticker}"
        if cache_key in self.cache:
            cached_time, cached_data = self.cache[cache_key]
            if (datetime.now() - cached_time).seconds < self.cache_duration:
                return cached_data

        news_items = []

        # Method 1: Tiingo News API (PRIMARY — rich descriptions + tags)
        try:
            url = f"https://api.tiingo.com/tiingo/news?tickers={ticker}&limit=10&token={_TIINGO_KEY}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers={"Content-Type": "application/json"}, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if isinstance(data, list) and data:
                            for article in data[:10]:
                                title = article.get("title", "")
                                desc = article.get("description", "")
                                if title:
                                    news_items.append({
                                        "title": title,
                                        "description": desc[:500] if desc else "",
                                        "link": article.get("url", ""),
                                        "publisher": article.get("source", "Tiingo"),
                                        "published": article.get("publishedDate", ""),
                                        "tags": article.get("tags", []),
                                        "source": "tiingo",
                                    })
        except Exception:
            pass

        # Method 2: Google News RSS (FALLBACK)
        if not news_items:
            try:
                rss_url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
                feed = await asyncio.to_thread(feedparser.parse, rss_url)
                if hasattr(feed, 'entries') and feed.entries:
                    for entry in feed.entries[:5]:
                        title = entry.get("title", "")
                        if title:
                            news_items.append({
                                "title": title,
                                "description": "",
                                "link": entry.get("link", ""),
                                "publisher": entry.get("source", {}).get("title", "Google News") if isinstance(entry.get("source"), dict) else "Google News",
                                "published": "",
                                "tags": [],
                                "source": "google_news",
                            })
            except Exception:
                pass

        # If we have no news, create a generic placeholder
        if not news_items:
            news_items = [{
                "title": f"{ticker} stock continues trading",
                "description": "",
                "link": "",
                "publisher": "General",
                "published": "",
                "tags": [],
                "source": "placeholder",
            }]

        # Cache the results
        self.cache[cache_key] = (datetime.now(), news_items)

        # Log to DB for future backtesting (non-blocking)
        try:
            self._log_news(ticker, news_items)
        except Exception:
            pass

        return news_items

    def _log_news(self, ticker: str, articles: List[Dict]):
        """Store articles in news_log table for historical analysis."""
        today = date.today().isoformat()
        conn = sqlite3.connect(_DB_PATH)
        for a in articles:
            if a.get("source") == "placeholder":
                continue
            title = a.get("title", "")
            desc = a.get("description", "")
            # Analyze sentiment on title + description combined
            text = f"{title}. {desc}" if desc else title
            sent = self.analyze_sentiment(text)
            try:
                conn.execute('''
                    INSERT OR IGNORE INTO news_log
                    (ticker, published_date, title, description, source, tags,
                     sentiment_score, sentiment_label, fetch_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    ticker,
                    a.get("published", "")[:19],
                    title[:500],
                    desc[:1000],
                    a.get("publisher", ""),
                    ",".join(a.get("tags", [])) if a.get("tags") else "",
                    sent["compound"],
                    self._get_sentiment_label(sent["compound"]),
                    today,
                ))
            except Exception:
                pass
        conn.commit()
        conn.close()

    def analyze_sentiment(self, text: str) -> Dict:
        """Analyze sentiment using VADER.
        For Tiingo articles, analyzes title + description combined for richer signal.
        """
        scores = self.analyzer.polarity_scores(text)
        return {
            "compound": scores["compound"],
            "positive": scores["pos"],
            "negative": scores["neg"],
            "neutral": scores["neu"],
        }

    async def get_ticker_sentiment(self, ticker: str) -> Dict:
        """Get aggregated sentiment for a ticker based on recent news."""
        news_items = await self.get_news_for_ticker(ticker)

        if not news_items:
            return {
                "ticker": ticker,
                "sentiment_score": 0.0,
                "sentiment_label": "NEUTRAL",
                "article_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "articles": [],
                "headlines": [],
                "timestamp": datetime.now().isoformat(),
            }

        # Analyze each article — use title + description for Tiingo articles
        sentiments = []
        analyzed_articles = []

        for item in news_items:
            title = item.get("title", "")
            desc = item.get("description", "")
            # Combine title + description for richer sentiment (Tiingo gives us both)
            text = f"{title}. {desc}" if desc else title
            sentiment = self.analyze_sentiment(text)

            sentiments.append(sentiment["compound"])
            analyzed_articles.append({
                **item,
                "sentiment": sentiment,
                "sentiment_label": self._get_sentiment_label(sentiment["compound"]),
            })

        # Aggregate scores
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

        # Count sentiment types
        positive_count = sum(1 for s in sentiments if s > 0.05)
        negative_count = sum(1 for s in sentiments if s < -0.05)
        neutral_count = len(sentiments) - positive_count - negative_count

        # Extract headlines for the UI
        headlines = [a.get("title", "") for a in analyzed_articles[:5] if a.get("title")]

        return {
            "ticker": ticker,
            "sentiment_score": round(avg_sentiment, 3),
            "sentiment_label": self._get_sentiment_label(avg_sentiment),
            "article_count": len(news_items),
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "articles": analyzed_articles[:5],
            "headlines": headlines,
            "timestamp": datetime.now().isoformat(),
        }

    def _get_sentiment_label(self, compound_score: float) -> str:
        """Convert compound score to label"""
        if compound_score >= 0.05:
            return "POSITIVE"
        elif compound_score <= -0.05:
            return "NEGATIVE"
        else:
            return "NEUTRAL"

    async def compare_tickers(self, ticker1: str, ticker2: str) -> Dict:
        """Compare sentiment between two tickers"""
        sentiment1 = await self.get_ticker_sentiment(ticker1)
        sentiment2 = await self.get_ticker_sentiment(ticker2)

        difference = sentiment1["sentiment_score"] - sentiment2["sentiment_score"]
        winner = ticker1 if difference > 0 else ticker2 if difference < 0 else "TIE"

        return {
            "ticker1": ticker1,
            "ticker2": ticker2,
            "sentiment1": sentiment1,
            "sentiment2": sentiment2,
            "difference": round(difference, 3),
            "winner": winner,
        }


class NewsAggregator:
    """Aggregate news from multiple free sources"""

    @staticmethod
    async def fetch_market_news(limit: int = 20) -> List[Dict]:
        """Fetch general market news from free sources"""
        news_items = []

        # Yahoo Finance RSS
        try:
            rss_url = "https://finance.yahoo.com/rss/topstories"
            feed = await asyncio.to_thread(feedparser.parse, rss_url)

            for entry in feed.entries[:limit]:
                news_items.append({
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "publisher": "Yahoo Finance",
                    "published": int(datetime.now().timestamp()),
                    "summary": entry.get("summary", "")[:200]
                })
        except Exception as e:
            print(f"Error fetching Yahoo Finance RSS: {e}")

        return news_items


# ── Utility: News log stats ──

def news_log_stats():
    """Get stats about the news log."""
    conn = sqlite3.connect(_DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM news_log").fetchone()[0]
    tickers = conn.execute("SELECT COUNT(DISTINCT ticker) FROM news_log").fetchone()[0]
    oldest = conn.execute("SELECT MIN(fetch_date) FROM news_log").fetchone()[0]
    newest = conn.execute("SELECT MAX(fetch_date) FROM news_log").fetchone()[0]
    conn.close()
    return {
        "total_articles": total,
        "unique_tickers": tickers,
        "date_range": f"{oldest} to {newest}",
    }
