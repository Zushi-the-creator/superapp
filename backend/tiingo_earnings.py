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

# UPCOMING earnings — the warning class. These titles signal a binary event
# RISK ahead of us (per CLAUDE.md "earnings within 7 days = VETO"). Forward-
# looking language only — past-tense and result-disclosure phrasings stay in
# _REPORTED_TITLE_RE below.
_UPCOMING_TITLE_RE = re.compile(
    r"\b("
    r"ahead\s+of\s+(?:its\s+)?(?:q[1-4]\s+)?earnings|"
    r"before\s+(?:its\s+|the\s+)?[a-z]+\s+\d{1,2}\s+earnings|"
    r"earnings\s+preview|"
    r"earnings\s+are\s+coming|"
    r"to\s+(?:report|release|announce|publish)\s+(?:fiscal\s+)?(?:q[1-4]|first|second|third|fourth)\s+(?:quarter\s+)?(?:results|earnings)|"
    r"will\s+(?:report|release|announce|publish)\s+(?:fiscal\s+)?(?:q[1-4]|first|second|third|fourth)|"
    r"set\s+to\s+report|"
    r"upcoming\s+earnings|"
    r"expected\s+to\s+report\s+(?:q[1-4]|first|second|third|fourth|earnings)|"
    r"earnings\s+date\s+(?:announced|set|confirmed)|"
    r"earnings\s+(?:on|due)\s+(?:january|february|march|april|may|june|july|august|september|october|november|december|\d{1,2})|"
    r"(?:reports|releases|announces)\s+earnings\s+(?:on|next)\s+|"
    r"q[1-4]\s+earnings\s+(?:on|due)\s+\d|"
    r"earnings\s+release\s+(?:on|scheduled)|"
    r"q[1-4]\s+\d{4}\s+(?:earnings|results)\s+(?:on|date|preview)"
    r")\b",
    re.IGNORECASE,
)

# JUST-REPORTED earnings — informational, not a warning. The event already
# happened; market reaction is in price; no binary risk left. Allows an
# optional adjective (record/strong/preliminary/etc.) between the verb and
# the quarter — catches PR phrasings like "Reports Record First Quarter".
_REPORTED_TITLE_RE = re.compile(
    r"\b("
    r"q[1-4]\s+results|"
    r"q[1-4]\s+\d{4}|"
    r"q[1-4]\s+earnings\s+(call|highlights|transcript|results|beat|miss|tops|snapshot|overview|recap|summary)|"
    r"q[1-4]\s+(?:adj\.?\s+)?eps\s+(?:of\s+)?\$?[\d\.\(\)\-]+\s+(?:beats?|misses?|tops|in[\s-]line)|"
    r"q[1-4]\s+(?:revenue|sales|net\s+income)\s+(?:of\s+)?\$?[\d\.\(\)\-]+|"
    r"earnings\s+(call\s+highlights|highlights|transcript|results|beat|miss|"
    r"beats|misses|tops|snapshot|recap|overview|summary)|"
    r"(reports|posts|announces|delivers|releases)\s+"
    r"(?:(?:record|strong|robust|solid|preliminary|mixed|disappointing|weak|all[\s-]?time|blowout)\s+)?"
    r"(?:fiscal\s+)?"
    r"(first|second|third|fourth|q[1-4])(\s+quarter)?|"
    r"beats\s+q[1-4]|"
    r"surpasses\s+q[1-4]|"
    r"after\s+earnings\s+(beat|miss)|"
    r"earnings\s+(jump|surge|drop|fell|rose|beat|miss)"
    r")\b",
    re.IGNORECASE,
)


def _classify_title(title: str) -> Optional[str]:
    """Classify earnings article: 'upcoming' (warning) | 'reported' (info) | None.

    Returns None when neither regex matches — caller should fall back to
    publishedDate-based inference (Tiingo already tagged the article as
    earnings-related, so a None classification just means we couldn't pin
    the direction from the title alone).
    """
    if _UPCOMING_TITLE_RE.search(title):
        return "upcoming"
    if _REPORTED_TITLE_RE.search(title):
        return "reported"
    return None

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
        # Tiingo's `tags=earnings` filter already classified this article as
        # earnings-related. Title regex is now used only for direction labeling.
        # If regex is silent, default to "reported" — earnings news flows
        # AFTER events, so the prior is the article is past-tense. CAMT
        # 2026-05-12 missed because of regex over-strictness; this restores
        # the catch.
        kind = _classify_title(title) or "reported"
        age_hours = (now - pub).total_seconds() / 3600.0
        candidates.append({
            "ticker": ticker,
            "date": pub.isoformat(),
            "title": title,
            "url": a.get("url", "") or "",
            "source": "tiingo",
            # Forward semantics:
            #   "upcoming" = binary event RISK ahead (warn the user)
            #   "reported" = event already happened, market has digested it
            "kind": kind,
            "direction": "future" if kind == "upcoming" else "past",
            "age_hours": round(age_hours, 1),
        })
    if not candidates:
        return None
    # Prefer upcoming (the actionable warning) over reported (informational).
    # Within each class, prefer the most recent article.
    candidates.sort(key=lambda c: (c["kind"] != "upcoming", abs(c["age_hours"])))
    return candidates[0]


# -----------------------------------------------------------------------------
# Finnhub backstop — `/calendar/earnings` returns scheduled/reported events
# directly. Different blind spots than Tiingo News (Finnhub missed IREN
# 2026-05-08; Tiingo missed CAMT 2026-05-12). Union of both = best coverage.
# -----------------------------------------------------------------------------

_FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
_FINNHUB_CAL_URL = "https://finnhub.io/api/v1/calendar/earnings"


async def _finnhub_earnings_window(
    session: aiohttp.ClientSession,
    ticker: str,
    days: int = 7,
    timeout_s: float = 4.0,
) -> Optional[dict]:
    """Look up ticker in Finnhub's earnings calendar within ±`days`.

    Returns the same dict shape as `earnings_window()` so callers can treat
    both sources uniformly.
    """
    if not _FINNHUB_KEY:
        return None
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=days)).date().isoformat()
    end = (now + timedelta(days=days)).date().isoformat()
    try:
        async with session.get(
            _FINNHUB_CAL_URL,
            params={
                "symbol": ticker.upper(),
                "from": start,
                "to": end,
                "token": _FINNHUB_KEY,
            },
            timeout=aiohttp.ClientTimeout(total=timeout_s),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except Exception:
        return None
    rows = (data or {}).get("earningsCalendar") or []
    if not rows:
        return None
    # Pick the row closest to today (the actionable event).
    today = now.date()

    def _key(r):
        try:
            d = datetime.fromisoformat(r["date"]).date()
            return abs((d - today).days)
        except Exception:
            return 9999

    row = sorted(rows, key=_key)[0]
    try:
        event_date = datetime.fromisoformat(row["date"]).replace(tzinfo=timezone.utc)
    except Exception:
        return None
    # epsActual present + non-null = already reported; null/missing = upcoming.
    eps_actual = row.get("epsActual")
    reported = eps_actual is not None
    kind = "reported" if reported else "upcoming"
    age_hours = (now - event_date).total_seconds() / 3600.0
    quarter = row.get("quarter")
    year = row.get("year")
    title = f"{ticker.upper()} Q{quarter} {year} Earnings (Finnhub calendar)"
    if reported:
        title += f" — EPS ${eps_actual} vs ${row.get('epsEstimate', '?')} est"
    return {
        "ticker": ticker.upper(),
        "date": event_date.isoformat(),
        "title": title,
        "url": "",
        "source": "finnhub",
        "kind": kind,
        "direction": "future" if kind == "upcoming" else "past",
        "age_hours": round(age_hours, 1),
    }


def _pick_best(hits: list[Optional[dict]]) -> Optional[dict]:
    """Pick the most actionable hit from multiple sources.

    Priority:
      1. Any "upcoming" beats any "reported" — upcoming is the WARNING class.
      2. Within same kind, prefer source with the smaller |age_hours|
         (closest to the actual event).
      3. Annotate the chosen hit with `sources=[...]` listing every backend
         that confirmed the event — useful for debugging/telemetry.
    """
    real = [h for h in hits if h]
    if not real:
        return None
    real.sort(key=lambda h: (h.get("kind") != "upcoming", abs(h.get("age_hours", 1e9))))
    best = dict(real[0])
    best["sources"] = sorted({h.get("source", "?") for h in real})
    return best


async def earnings_window_combined(
    session: aiohttp.ClientSession,
    ticker: str,
    days: int = 7,
) -> Optional[dict]:
    """Union Tiingo News + Finnhub calendar. Either source firing = a hit.

    Resilient to partial failures: if one source 5xx's or rate-limits, the
    other still gets to answer. This is the function you want to call from
    production code — `earnings_window()` and `_finnhub_earnings_window()`
    are exposed for direct testing only.
    """
    tg, fh = await asyncio.gather(
        earnings_window(session, ticker, days=days),
        _finnhub_earnings_window(session, ticker, days=days),
        return_exceptions=True,
    )
    tg = tg if isinstance(tg, dict) else None
    fh = fh if isinstance(fh, dict) else None
    return _pick_best([tg, fh])


async def earnings_window_batch(
    session: aiohttp.ClientSession,
    tickers: list[str],
    days: int = 7,
    concurrency: int = 8,
) -> dict[str, dict]:
    """Concurrent batch lookup. Returns {ticker: result_dict} for matches only.

    Uses the combined Tiingo+Finnhub source for resilience — see
    `earnings_window_combined` for the union semantics.
    """
    if not tickers:
        return {}
    sem = asyncio.Semaphore(concurrency)

    async def _one(t: str):
        async with sem:
            return t, await earnings_window_combined(session, t, days=days)

    results = await asyncio.gather(*[_one(t) for t in tickers], return_exceptions=True)
    out: dict[str, dict] = {}
    for r in results:
        if isinstance(r, Exception) or r is None:
            continue
        ticker, hit = r
        if hit:
            out[ticker] = hit
    return out
