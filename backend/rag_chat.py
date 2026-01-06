"""
RAG-based Analyst Chat System
Uses ChromaDB for vector storage and LangGraph for research agent
Integrates with Ollama for local LLM inference
"""

import asyncio
import httpx
from typing import List, Dict, Optional
from datetime import datetime
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


class RAGChatSystem:
    """
    Retrieval-Augmented Generation chat system for stock analysis
    Stores scan results and news in vector DB for contextual retrieval
    """

    def __init__(self, ollama_host: str = "http://ollama:11434", chroma_host: str = "chromadb", chroma_port: int = 8000):
        self.ollama_host = ollama_host

        # Initialize ChromaDB client
        try:
            self.chroma_client = chromadb.HttpClient(
                host=chroma_host,
                port=chroma_port,
                settings=Settings(allow_reset=True, anonymized_telemetry=False)
            )
        except Exception as e:
            print(f"Warning: Could not connect to ChromaDB: {e}")
            print("Using in-memory ChromaDB instead")
            self.chroma_client = chromadb.Client()

        # Create collections
        self.stock_collection = self.chroma_client.get_or_create_collection(
            name="stock_data",
            metadata={"description": "Stock scan results and signals"}
        )

        self.news_collection = self.chroma_client.get_or_create_collection(
            name="news_articles",
            metadata={"description": "Stock news and sentiment"}
        )

        # Embedding model (lightweight, runs locally)
        self.embedder = SentenceTransformer('all-MiniLM-L6-v2')

        # Chat history
        self.chat_history = []

    async def index_stock_data(self, stock_data: Dict):
        """Index stock scan results into vector DB"""
        try:
            # Create a rich text representation
            doc_text = self._create_stock_document(stock_data)

            # Generate embedding
            embedding = self.embedder.encode(doc_text).tolist()

            # Add to collection
            self.stock_collection.upsert(
                ids=[stock_data["ticker"]],
                embeddings=[embedding],
                documents=[doc_text],
                metadatas=[{
                    "ticker": stock_data["ticker"],
                    "signal": stock_data["signal"],
                    "price": stock_data["price"],
                    "timestamp": stock_data["last_updated"]
                }]
            )
        except Exception as e:
            print(f"Error indexing stock data: {e}")

    async def index_news_article(self, article: Dict, ticker: str):
        """Index news article into vector DB"""
        try:
            doc_text = f"{article['title']} - {article.get('publisher', 'Unknown')}"

            embedding = self.embedder.encode(doc_text).tolist()

            article_id = f"{ticker}_{article.get('published', int(datetime.now().timestamp()))}"

            self.news_collection.upsert(
                ids=[article_id],
                embeddings=[embedding],
                documents=[doc_text],
                metadatas=[{
                    "ticker": ticker,
                    "title": article["title"],
                    "sentiment": article.get("sentiment_label", "NEUTRAL"),
                    "link": article.get("link", "")
                }]
            )
        except Exception as e:
            print(f"Error indexing news: {e}")

    def _create_stock_document(self, stock: Dict) -> str:
        """Create a rich text document from stock data"""
        reasons = ", ".join(stock.get("reasons", []))

        doc = f"""
        Stock: {stock['ticker']} ({stock['name']})
        Sector: {stock['sector']}
        Price: ${stock['price']} ({stock['change_pct']:+.2f}%)
        Signal: {stock['signal']} (Strength: {stock['signal_strength']}%)
        RSI: {stock['rsi']}
        Volume: {stock['volume']:,} ({stock['volume_ratio']:.1f}x average)
        Sentiment: {stock['sentiment_label']} ({stock['sentiment_score']:+.2f})
        Combined Score: {stock['combined_score']}/100
        Reasons: {reasons}
        """
        return doc.strip()

    async def retrieve_context(self, query: str, n_results: int = 5) -> Dict:
        """
        Retrieve relevant context from vector DB

        Returns:
            Dict with stock data and news context
        """
        try:
            # Generate query embedding
            query_embedding = self.embedder.encode(query).tolist()

            # Search stock data
            stock_results = self.stock_collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results
            )

            # Search news
            news_results = self.news_collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results
            )

            return {
                "stocks": {
                    "documents": stock_results.get("documents", [[]])[0],
                    "metadatas": stock_results.get("metadatas", [[]])[0]
                },
                "news": {
                    "documents": news_results.get("documents", [[]])[0],
                    "metadatas": news_results.get("metadatas", [[]])[0]
                }
            }
        except Exception as e:
            print(f"Error retrieving context: {e}")
            return {"stocks": {"documents": [], "metadatas": []}, "news": {"documents": [], "metadatas": []}}

    async def chat(self, user_message: str, scanner_data: Optional[Dict] = None) -> str:
        """
        Process user chat message with RAG

        Args:
            user_message: User's question
            scanner_data: Optional current scanner state

        Returns:
            AI response
        """
        # Retrieve relevant context
        context = await self.retrieve_context(user_message, n_results=5)

        # Build context string
        context_str = self._build_context_string(context, scanner_data)

        # Build system prompt
        system_prompt = f"""You are an expert financial analyst and trading advisor. You have access to real-time stock market data, technical indicators, and news sentiment analysis.

Your role is to:
1. Provide clear, actionable insights based on technical and sentiment data
2. Explain your reasoning with specific data points
3. Be concise but thorough
4. Acknowledge uncertainty when data is limited

Current Context:
{context_str}

Respond professionally and focus on data-driven insights."""

        # Add to chat history
        self.chat_history.append({"role": "user", "content": user_message})

        # Generate response using Ollama
        response = await self._generate_ollama_response(system_prompt, user_message)

        # Add to chat history
        self.chat_history.append({"role": "assistant", "content": response})

        # Keep history manageable (last 20 messages)
        if len(self.chat_history) > 20:
            self.chat_history = self.chat_history[-20:]

        return response

    def _build_context_string(self, context: Dict, scanner_data: Optional[Dict]) -> str:
        """Build context string from retrieved data"""
        context_parts = []

        # Add stock data
        if context["stocks"]["documents"]:
            context_parts.append("=== Relevant Stock Data ===")
            for doc in context["stocks"]["documents"][:3]:
                context_parts.append(doc)
                context_parts.append("")

        # Add news
        if context["news"]["documents"]:
            context_parts.append("=== Recent News ===")
            for doc in context["news"]["documents"][:3]:
                context_parts.append(doc)
                context_parts.append("")

        # Add current scanner stats
        if scanner_data:
            context_parts.append("=== Current Market Snapshot ===")
            context_parts.append(f"Total stocks scanned: {scanner_data.get('scanned_tickers', 0)}")
            context_parts.append(f"High-volume stocks: {scanner_data.get('hot_tickers', 0)}")

        return "\n".join(context_parts)

    async def _generate_ollama_response(self, system_prompt: str, user_message: str) -> str:
        """
        Generate response using Ollama API

        Falls back to rule-based response if Ollama is unavailable
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Check if Ollama is available
                try:
                    await client.get(f"{self.ollama_host}/api/tags")
                except Exception:
                    return self._fallback_response(user_message)

                # Generate response
                payload = {
                    "model": "llama3.2",  # or "llama3.1", "mistral", etc.
                    "prompt": f"{system_prompt}\n\nUser: {user_message}\n\nAssistant:",
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "max_tokens": 500
                    }
                }

                response = await client.post(
                    f"{self.ollama_host}/api/generate",
                    json=payload,
                    timeout=30.0
                )

                if response.status_code == 200:
                    result = response.json()
                    return result.get("response", "").strip()
                else:
                    return self._fallback_response(user_message)

        except Exception as e:
            print(f"Error calling Ollama: {e}")
            return self._fallback_response(user_message)

    def _fallback_response(self, user_message: str) -> str:
        """Fallback response when Ollama is unavailable"""
        message_lower = user_message.lower()

        if "why" in message_lower and "buy" in message_lower:
            return "Based on the technical indicators and sentiment analysis, I can provide insights on buy signals. However, the AI model is currently unavailable. Please ensure Ollama is running with: `docker-compose up ollama` and pull a model with: `docker exec -it <container> ollama pull llama3.2`"

        elif "compare" in message_lower:
            return "I can compare stocks based on technical signals and sentiment scores. However, the AI model is currently unavailable. Please ensure Ollama is running."

        else:
            return "I'm your AI analyst assistant. I can help analyze stocks, explain signals, and compare sentiment. However, the AI model is currently unavailable. Please ensure Ollama is running and has a model pulled (llama3.2 recommended)."

    async def explain_signal(self, ticker: str, stock_data: Dict) -> str:
        """Generate detailed explanation for a stock's signal"""
        query = f"Explain why {ticker} has a {stock_data['signal']} signal"

        # Add stock data to context
        await self.index_stock_data(stock_data)

        response = await self.chat(query, scanner_data=None)
        return response

    def clear_history(self):
        """Clear chat history"""
        self.chat_history = []

    def get_chat_history(self) -> List[Dict]:
        """Get chat history"""
        return self.chat_history.copy()


class AnalystAgent:
    """
    Advanced research agent using LangGraph patterns
    This is a simplified version - can be expanded with LangGraph
    """

    def __init__(self, rag_system: RAGChatSystem):
        self.rag = rag_system

    async def research_ticker(self, ticker: str) -> Dict:
        """
        Perform comprehensive research on a ticker

        Returns:
            Dict with research findings
        """
        # Multi-step research process
        steps = [
            f"Analyze technical signals for {ticker}",
            f"Review news sentiment for {ticker}",
            f"Identify key risks and opportunities for {ticker}"
        ]

        findings = []

        for step in steps:
            response = await self.rag.chat(step)
            findings.append({
                "step": step,
                "finding": response
            })

        return {
            "ticker": ticker,
            "research_steps": findings,
            "timestamp": datetime.now().isoformat()
        }

    async def compare_stocks(self, ticker1: str, ticker2: str) -> str:
        """Compare two stocks comprehensively"""
        query = f"Compare {ticker1} and {ticker2}. Which has better technical signals and sentiment? Provide a detailed comparison."

        response = await self.rag.chat(query)
        return response
