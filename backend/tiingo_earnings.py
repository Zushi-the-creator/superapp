"""
Tiingo earnings detection — Tiingo News with `tags=earnings` filter.

Why this module exists:
  Finnhub free-tier earnings calendar has gaps (e.g., it missed IREN's Q3 FY26
  earnings on 2026-05-08 — we held through the print without warning). Our paid
  Tiingo Power plan does not include the Fundamentals add-on (DOW 30 only there),
  but it DOES include the News API for all tickers. Tiingo tags news articles
  with topic labels including "earnings" — articles with that tag fire on:
    - Earnings preview / expectations
    - Earnings results / call highlights
    - Estimate revisions
  So the same data feed we already use for sentiment doubles as a forward-looking
  earnings detector.

Public API:
  await earnings_window(session, ticker, days=14) -> dict | None
    Returns {date: ISO, title: str, source: "tiingo", direction: "past|future",
             age_hours: float} for the most recent / nearest earnings article
    within the window, or None if nothing matched.

  await earnings_window_batch(session, tickers, days=14) -> dict[str, dict]
    Concurrent batch fetch for portfolio checks.
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

_TIINGO_KEY = os.environ.get("TIINGO_API_KEY", "")
_NEWS_URL = "https://api.tiingo.com/tiingo/news"
_SEARCH_URL = "https://api.tiingo.com/tiingo/utilities/search"

# Company-name cache so we don't hit the search endpoint on every earnings check.
# Tiingo News tags every ticker mentioned in an article (e.g., a story about
# Palantir's earnings will tag NVDA if NVDA is mentioned in passing). To filter
# that out we require the ticker's symbol OR its full company name to appear in
# the article title — a stronger signal that the article is about us, not just
# mentioning us.
_COMPANY_NAME_CACHE: dict[str, str] = {}

# Title patterns that indicate AN EARNINGS EVENT (not generic commentary).
# Tightened after smoke test — single word "earnings" is too broad and lets
# valuation commentary leak through. Now requires explicit event language.
_EARNINGS_TITLE_RE = re.compile(
    r"\b("
    r"q[1-4]\s+results|"
    r"q[1-4]\s+\d{4}|"
    r"q[1-4]\s+earnings|"
    r"(reports|posts|announces|delivers)\s+(?:fiscal\s+)?"
    r"(first|second|third|fourth|q[1-4])(\s+quarter)?|"
    r"earnings\s+(call|preview|date|release|report|results|beat|miss|"
    r"transcript|highlights|expectations|beats|misses|tops)|"
    r"beats\s+q[1-4]|"
    r"surpasses\s+q[1-4]|"
    r"to\s+report\s+(?:fiscal\s+)?(first|second|third|fourth|q[1-4])|"
    r"earnings\s+(jump|surge|drop|fall|rise)"
    r")\b",
    re.IGNORECASE,
)

# Stock-exchange ticker tag inside a title (e.g., "Graham (NYSE:GHC)") — strong
# signal that the article is about THAT specific symbol. If we see the tag and
# it's a different ticker, reject (catches the GHM-vs-GHC sibling-ticker case).
_EXCHANGE_TAG_RE = re.compile(
    r"\((?:nasdaq|nyse|amex|otc|tsx|lse)\s*:\s*([A-Z]+)\)",
    re.IGNORECASE,
)


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse Tiingo's ISO-8601 timestamps (with or without Z)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


# Generic suffixes that aren't useful for matching (drop "Inc", "Corp", "Ltd"…).
_NAME_SUFFIX_RE = re.compile(
    r"\b(inc|corp|corporation|company|co|ltd|limited|plc|nv|sa|ag|holdings?|"
    r"group|technologies|tech|industries|systems|solutions|international)\b\.?",
    re.IGNORECASE,
)


def _normalize_company_name(raw: str) -> str:
    """Strip suffixes so "Iris Energy Ltd" → "iris energy" (matches more titles)."""
    name = _NAME_SUFFIX_RE.sub("", raw)
    return re.sub(r"[^\w\s]", " ", name).strip().lower()


async def _company_name(session: aiohttp.ClientSession, ticker: str) -> str:
    """Look up the canonical company name from Tiingo. Cached forever — names
    don't change in our session lifetime."""
    if ticker in _COMPANY_NAME_CACHE:
        return _COMPANY_NAME_CACHE[ticker]
    if not _TIINGO_KEY:
        return ""
    try:
        async with session.get(
            _SEARCH_URL,
            params={"query": ticker, "token": _TIINGO_KEY},
            timeout=aiohttp.ClientTimeout(total=4.0),
        ) as resp:
            if resp.status != 200:
                return ""
            data = await resp.json()
    except Exception:
        return ""
    if not isinstance(data, list):
        return ""
    exact = next(
        (e for e in data if (e.get("ticker") or "").upper() == ticker.upper()),
        None,
    )
    name = (exact or {}).get("name", "") if exact else ""
    normalized = _normalize_company_name(name) if name else ""
    _COMPANY_NAME_CACHE[ticker] = normalized
    return normalized


def _title_is_about_ticker(title: str, ticker: str, company_words: str) -> bool:
    """Article title must mention the ticker symbol OR the company's primary words.
    Filters out collateral mentions (Tiingo tags every ticker an article mentions).
    Also rejects when the title carries an explicit exchange tag for a *different*
    symbol — handles same-name siblings like Graham Corp (GHM) vs Graham Holdings (GHC).
    """
    if not title:
        return False
    title_l = title.lower()
    # Reject if title's exchange tag points to a different ticker
    tag_match = _EXCHANGE_TAG_RE.search(title)
    if tag_match and tag_match.group(1).upper() != ticker.upper():
        return False
    # Ticker as a standalone word (avoids substring matches like AMSC in NAMSCO)
    if re.search(rf"\b{re.escape(ticker.lower())}\b", title_l):
        return True
    # Company name fragment — require at least 2 consecutive words to match,
    # so "Sprouts Farmers" works but a single common word like "Energy" doesn't
    # over-match (which would let an "Iris Energy" filter accidentally fire on
    # any title containing "Energy").
    if company_words:
        words = company_words.split()
        if len(words) >= 2:
            phrase = " ".join(words[:2])  # first two non-suffix words
            if phrase in title_l:
                return True
        elif len(words) == 1 and len(words[0]) >= 5:
            # Fall back to single-word name when it's long enough to be specific
            if re.search(rf"\b{re.escape(words[0])}\b", title_l):
                return True
    return False


async def earnings_window(
    session: aiohttp.ClientSession,
    ticker: str,
    days: int = 7,
    timeout_s: float = 6.0,
) -> Optional[dict]:
    """Look for an earnings-tagged article for `ticker` within ±`days` window.

    Returns the most relevant match (preferring future-dated, then most-recent
    past), or None. Result fields:
      ticker, date (ISO), title, url, source="tiingo", direction ("past"|"future"),
      age_hours (float, signed: positive=past, negative=future)
    """
    if not _TIINGO_KEY:
        return None
    ticker = ticker.upper()
    params = {
        "tickers": ticker.lower(),
        "tags": "earnings",
        "limit": "10",
        "token": _TIINGO_KEY,
    }
    try:
        async with session.get(
            _NEWS_URL,
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout_s),
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status != 200:
                return None
            articles = await resp.json()
    except Exception:
        return None
    if not isinstance(articles, list) or not articles:
        return None

    company_words = await _company_name(session, ticker)

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    window_end = now + timedelta(days=days)
    candidates = []
    for a in articles:
        title = a.get("title", "") or ""
        if not _EARNINGS_TITLE_RE.search(title):
            continue
        # Title must be ABOUT this ticker, not just mention it (Tiingo tags
        # every ticker mentioned). Without this filter NVDA fires on
        # Palantir-earnings articles, GHM fires on Graham Holdings (GHC), etc.
        if not _title_is_about_ticker(title, ticker, company_words):
            continue
        article_tickers = [t.lower() for t in (a.get("tickers") or [])]
        if ticker.lower() not in article_tickers:
            continue
        pub = _parse_iso(a.get("publishedDate", ""))
        if pub is None:
            continue
        if pub < window_start or pub > window_end:
            continue
        age_hours = (now - pub).total_seconds() / 3600.0
        candidates.append({
            "ticker": ticker,
            "date": pub.isoformat(),
            "title": title,
            "url": a.get("url", "") or "",
            "source": "tiingo",
            "direction": "past" if age_hours >= 0 else "future",
            "age_hours": round(age_hours, 1),
        })
    if not candidates:
        return None
    # Prefer future-dated articles (preview / expectations) — those are the
    # actionable warnings. If only past articles exist, take the most recent.
    candidates.sort(key=lambda c: (c["direction"] != "future", abs(c["age_hours"])))
    return candidates[0]


async def earnings_window_batch(
    session: aiohttp.ClientSession,
    tickers: list[str],
    days: int = 7,
    concurrency: int = 8,
) -> dict[str, dict]:
    """Concurrent batch lookup. Returns {ticker: result_dict} for matches only."""
    if not tickers:
        return {}
    sem = asyncio.Semaphore(concurrency)

    async def _one(t: str):
        async with sem:
            return t, await earnings_window(session, t, days=days)

    results = await asyncio.gather(*[_one(t) for t in tickers], return_exceptions=True)
    out: dict[str, dict] = {}
    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        ticker, hit = r
        if hit:
            out[ticker] = hit
    return out
