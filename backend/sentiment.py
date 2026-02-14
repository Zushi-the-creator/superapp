"""
News Sentiment Analysis Engine
Scrapes news from multiple sources and performs VADER sentiment analysis
"""

import asyncio
import aiohttp
from typing import List, Dict
from datetime import datetime, timedelta
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from bs4 import BeautifulSoup
import feedparser


class SentimentEngine:
    """Analyze sentiment from news articles using VADER"""

    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()
        self.cache = {}  # Simple in-memory cache
        self.cache_duration = 300  # 5 minutes

    async def get_news_for_ticker(self, ticker: str) -> List[Dict]:
        """Get news articles for a specific ticker"""
        # Check cache
        cache_key = f"news_{ticker}"
        if cache_key in self.cache:
            cached_time, cached_data = self.cache[cache_key]
            if (datetime.now() - cached_time).seconds < self.cache_duration:
                return cached_data

        news_items = []

        # Method 1: yfinance news - DISABLED (rate limited)
        # yfinance news is disabled due to persistent 429 rate limiting from Yahoo Finance

        # Method 2: Google News RSS (free, no API key needed, PRIMARY source)
        try:
            rss_url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
            feed = await asyncio.to_thread(feedparser.parse, rss_url)

            if hasattr(feed, 'entries') and feed.entries:
                for entry in feed.entries[:5]:  # Top 5 from Google News
                    title = entry.get("title", "")
                    if title:  # Only add if we have a title
                        news_items.append({
                            "title": title,
                            "link": entry.get("link", ""),
                            "publisher": entry.get("source", {}).get("title", "Google News") if isinstance(entry.get("source"), dict) else "Google News",
                            "published": int(datetime.now().timestamp()),
                            "source": "google_news"
                        })
        except Exception:
            pass  # Skip Google News if it fails

        # If we have no news, create a generic placeholder
        if not news_items:
            news_items = [{
                "title": f"{ticker} stock continues trading",
                "link": "",
                "publisher": "General",
                "published": int(datetime.now().timestamp()),
                "source": "placeholder"
            }]

        # Cache the results
        self.cache[cache_key] = (datetime.now(), news_items)

        return news_items

    def analyze_sentiment(self, text: str) -> Dict:
        """
        Analyze sentiment of text using VADER

        Returns:
            Dict with sentiment scores (compound, positive, negative, neutral)
        """
        scores = self.analyzer.polarity_scores(text)
        return {
            "compound": scores["compound"],  # -1 (most negative) to +1 (most positive)
            "positive": scores["pos"],
            "negative": scores["neg"],
            "neutral": scores["neu"]
        }

    async def get_ticker_sentiment(self, ticker: str) -> Dict:
        """
        Get aggregated sentiment for a ticker based on recent news

        Returns:
            Dict with sentiment analysis and news articles
        """
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
                "timestamp": datetime.now().isoformat()
            }

        # Analyze each article
        sentiments = []
        analyzed_articles = []

        for item in news_items:
            text = item["title"]  # Use title for sentiment (lightweight)
            sentiment = self.analyze_sentiment(text)

            sentiments.append(sentiment["compound"])
            analyzed_articles.append({
                **item,
                "sentiment": sentiment,
                "sentiment_label": self._get_sentiment_label(sentiment["compound"])
            })

        # Aggregate scores
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.0

        # Count sentiment types
        positive_count = sum(1 for s in sentiments if s > 0.05)
        negative_count = sum(1 for s in sentiments if s < -0.05)
        neutral_count = len(sentiments) - positive_count - negative_count

        return {
            "ticker": ticker,
            "sentiment_score": round(avg_sentiment, 3),
            "sentiment_label": self._get_sentiment_label(avg_sentiment),
            "article_count": len(news_items),
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "articles": analyzed_articles[:5],  # Return top 5 for UI
            "timestamp": datetime.now().isoformat()
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
        """
        Compare sentiment between two tickers

        Returns:
            Dict with comparative analysis
        """
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
            "analysis": self._generate_comparison_text(ticker1, ticker2, sentiment1, sentiment2, difference)
        }

    def _generate_comparison_text(self, t1: str, t2: str, s1: Dict, s2: Dict, diff: float) -> str:
        """Generate human-readable comparison"""
        if abs(diff) < 0.05:
            return f"{t1} and {t2} have similar sentiment profiles with no clear winner."

        winner = t1 if diff > 0 else t2
        loser = t2 if diff > 0 else t1
        winner_sentiment = s1 if diff > 0 else s2
        loser_sentiment = s2 if diff > 0 else s1

        return (
            f"{winner} shows {winner_sentiment['sentiment_label']} sentiment "
            f"({winner_sentiment['sentiment_score']:+.2f}) based on {winner_sentiment['article_count']} articles, "
            f"while {loser} shows {loser_sentiment['sentiment_label']} sentiment "
            f"({loser_sentiment['sentiment_score']:+.2f}) from {loser_sentiment['article_count']} articles. "
            f"{winner} has a sentiment advantage of {abs(diff):.2f} points."
        )


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
