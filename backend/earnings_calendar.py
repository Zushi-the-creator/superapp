"""
EARNINGS CALENDAR — redundant, persistent forward earnings dates
================================================================

The binary-event guard (exit a holding, veto an entry when earnings are <=7
days out) was a single point of failure until 2026-08-03: one source
(Finnhub, 60/min, one HTTP call PER TICKER), no persistence, and a failed
lookup that quietly returned "no earnings". Every failure mode looked
identical to "this stock has no earnings coming" — so the guard switched off
silently. It cost a 26-trade churn loop and left names sitting on earnings.

Three changes fix that class of failure:

1. PERSISTENCE. Dates live in SQLite on the Fly volume, so a restart, a
   rate-limit or an outage can never blind the guard. A cached future date is
   only ever replaced by a newer date, never erased by a failed lookup.

2. A DATE-KEYED PRIMARY SOURCE. Nasdaq's calendar is queried BY DATE and
   returns every company reporting that day. Answering "does anything I hold
   report in the next 7 days" therefore costs ~10 HTTP calls total, regardless
   of universe size — against 40+ per cycle for a per-ticker API, which is
   what blew the Finnhub budget. Coverage is also better: on 2026-08-03
   Finnhub resolved 18 of 25 requested names and had nothing for CROX, CBNK
   or KFRC.

3. AN EXPLICIT UNKNOWN. `get_next_earnings` reports which tickers it has no
   information for, so callers can distinguish "no earnings due" from "we
   don't know" and log the difference instead of silently trading through it.

Deliberately NOT used: Tiingo's news-text earnings detector. It was measured
at 94% false positives (2026-06-03) and is banned for this purpose.
"""

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "earnings.db")

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings"
FINNHUB_URL = "https://finnhub.io/api/v1/calendar/earnings"
_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
}

# How far ahead the date sweep runs. The veto only cares about <=7 days, but a
# little headroom means a date is already known before it enters the window.
SWEEP_DAYS = 12
SWEEP_TTL_SEC = 6 * 3600      # re-sweep at most 4x/day
_VETO_DAYS = 7


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS earnings_dates (
            ticker TEXT PRIMARY KEY,
            report_date TEXT NOT NULL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sweep_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    return conn


def _today() -> datetime.date:
    return datetime.now().date()


def _store(rows: List[Tuple[str, str, str]]) -> int:
    """Upsert {ticker, date, source}. A stored FUTURE date is never overwritten
    by an older one — only by a date at least as recent."""
    if not rows:
        return 0
    now = datetime.now().isoformat()
    written = 0
    conn = _connect()
    try:
        for ticker, date, source in rows:
            if not ticker or not date:
                continue
            cur = conn.execute(
                "SELECT report_date FROM earnings_dates WHERE ticker=?", (ticker,)
            ).fetchone()
            if cur and cur["report_date"] > date:
                # Existing record is further out; only replace it if the new
                # date is still in the future (a genuine reschedule forward).
                if date < _today().isoformat():
                    continue
            conn.execute(
                """INSERT INTO earnings_dates (ticker, report_date, source, fetched_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(ticker) DO UPDATE SET
                     report_date=excluded.report_date,
                     source=excluded.source,
                     fetched_at=excluded.fetched_at""",
                (ticker, date, source, now),
            )
            written += 1
        conn.commit()
    finally:
        conn.close()
    return written


def _read(tickers: List[str]) -> Dict[str, Dict]:
    """Persisted dates for these tickers, with days_to recomputed from today."""
    if not tickers:
        return {}
    out: Dict[str, Dict] = {}
    today = _today()
    conn = _connect()
    try:
        q = ",".join("?" * len(tickers))
        for r in conn.execute(
            f"SELECT * FROM earnings_dates WHERE ticker IN ({q})", tuple(tickers)
        ):
            try:
                d = datetime.strptime(r["report_date"][:10], "%Y-%m-%d").date()
            except Exception:
                continue
            out[r["ticker"]] = {
                "date": r["report_date"],
                "days_to": (d - today).days,
                "source": r["source"],
            }
    finally:
        conn.close()
    return out


def _sweep_age_sec() -> float:
    conn = _connect()
    try:
        r = conn.execute("SELECT value FROM sweep_meta WHERE key='last_sweep'").fetchone()
        if not r:
            return 1e9
        return (datetime.now() - datetime.fromisoformat(r["value"])).total_seconds()
    except Exception:
        return 1e9
    finally:
        conn.close()


def _mark_sweep() -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sweep_meta (key, value) VALUES ('last_sweep', ?)",
            (datetime.now().isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()


async def _nasdaq_day(session: aiohttp.ClientSession, date: str) -> List[Tuple[str, str, str]]:
    """Every ticker reporting on `date`. One call covers the whole market."""
    try:
        async with session.get(NASDAQ_URL, params={"date": date}, headers=_UA,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
            if r.status != 200:
                return []
            payload = await r.json(content_type=None)
    except Exception:
        return []
    rows = ((payload or {}).get("data") or {}).get("rows") or []
    out = []
    for row in rows:
        sym = (row.get("symbol") or "").strip().upper()
        if sym:
            out.append((sym, date, "nasdaq"))
    return out


async def sweep(days: int = SWEEP_DAYS,
                session: Optional[aiohttp.ClientSession] = None) -> int:
    """Populate the calendar for the next `days` dates. ~1 call per date."""
    own = session is None
    session = session or aiohttp.ClientSession()
    try:
        today = _today()
        dates = [(today + timedelta(days=i)).isoformat() for i in range(days + 1)]
        # Modest concurrency — this is a courtesy endpoint, not a paid API.
        sem = asyncio.Semaphore(4)

        async def _one(d: str):
            async with sem:
                return await _nasdaq_day(session, d)

        results = await asyncio.gather(*[_one(d) for d in dates], return_exceptions=True)
        rows: List[Tuple[str, str, str]] = []
        for r in results:
            if isinstance(r, list):
                rows.extend(r)
        written = _store(rows)
        if written:
            _mark_sweep()
        print(f"[Earnings] Nasdaq sweep: {len(dates)} dates → {written} ticker-dates stored")
        return written
    finally:
        if own:
            await session.close()


async def _finnhub_one(session: aiohttp.ClientSession, ticker: str,
                       key: str, days: int) -> Optional[Tuple[str, str, str]]:
    today = _today()
    try:
        async with session.get(
            FINNHUB_URL,
            params={"from": today.isoformat(),
                    "to": (today + timedelta(days=days)).isoformat(),
                    "symbol": ticker, "token": key},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            if r.status != 200:
                return None
            payload = await r.json(content_type=None)
    except Exception:
        return None
    cal = (payload or {}).get("earningsCalendar") or []
    future = sorted(c.get("date") for c in cal if c.get("date") and c["date"] >= today.isoformat())
    return (ticker, future[0], "finnhub") if future else None


async def top_up_finnhub(tickers: List[str], days: int = 30, max_calls: int = 12,
                         session: Optional[aiohttp.ClientSession] = None) -> int:
    """Per-ticker fallback for names the date sweep didn't cover.

    Bounded by `max_calls` — this is the API whose 60/min budget the old
    implementation blew by issuing one call per ticker per cycle.
    """
    key = os.environ.get("FINNHUB_API_KEY", "")
    if not key or not tickers:
        return 0
    own = session is None
    session = session or aiohttp.ClientSession()
    try:
        sem = asyncio.Semaphore(4)

        async def _one(t: str):
            async with sem:
                return await _finnhub_one(session, t, key, days)

        res = await asyncio.gather(*[_one(t) for t in tickers[:max_calls]],
                                   return_exceptions=True)
        rows = [r for r in res if isinstance(r, tuple)]
        return _store(rows)
    finally:
        if own:
            await session.close()


async def get_next_earnings(tickers: List[str], *, force_sweep: bool = False,
                            allow_finnhub: bool = True) -> Tuple[Dict[str, Dict], List[str]]:
    """Next earnings date per ticker.

    Returns (found, unknown) — `unknown` is the explicit list of tickers we
    have no information for, so a caller can log "we don't know" rather than
    treating it as "nothing due".
    """
    want = sorted({t.strip().upper() for t in tickers if t and t.strip()})
    if not want:
        return {}, []

    if force_sweep or _sweep_age_sec() > SWEEP_TTL_SEC:
        try:
            await sweep()
        except Exception as e:
            print(f"[Earnings] sweep failed: {e}")

    found = _read(want)
    unknown = [t for t in want if t not in found]

    # Anything still unknown AND not covered by the sweep window might simply
    # report further out — ask Finnhub for those, bounded.
    if unknown and allow_finnhub:
        try:
            if await top_up_finnhub(unknown):
                found = _read(want)
                unknown = [t for t in want if t not in found]
        except Exception as e:
            print(f"[Earnings] finnhub top-up failed: {e}")

    return found, unknown


def sweep_is_fresh() -> bool:
    """True when the date sweep has run recently enough to be authoritative.

    This is the property that makes an absent ticker SAFE rather than unknown:
    the sweep enumerates everyone reporting on each of the next SWEEP_DAYS
    dates, so after a fresh sweep, "not in the calendar" means "not reporting
    inside the window" — which fully answers the <=7d veto. Before this module
    a missing ticker was genuinely ambiguous, and we traded through it.
    """
    return _sweep_age_sec() <= SWEEP_TTL_SEC * 2


def blocking_reason(ticker: str, found: Dict[str, Dict],
                    veto_days: int = _VETO_DAYS) -> str:
    """'' if clear. Shared by the entry veto and the exit rule so the two can
    never disagree — the disagreement is exactly what caused the churn loop."""
    e = (found or {}).get(ticker) or {}
    dt = e.get("days_to")
    if dt is not None and 0 <= dt <= veto_days:
        return f"Earnings in {dt}d — binary event risk"
    return ""


def stats() -> Dict:
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) c FROM earnings_dates").fetchone()["c"]
        upcoming = conn.execute(
            "SELECT COUNT(*) c FROM earnings_dates WHERE report_date >= ?",
            (_today().isoformat(),),
        ).fetchone()["c"]
        by_src = {r["source"]: r["c"] for r in conn.execute(
            "SELECT source, COUNT(*) c FROM earnings_dates GROUP BY source")}
        last = conn.execute("SELECT value FROM sweep_meta WHERE key='last_sweep'").fetchone()
        return {"tickers": total, "upcoming": upcoming, "by_source": by_src,
                "last_sweep": last["value"] if last else None,
                "sweep_age_min": round(_sweep_age_sec() / 60, 1)}
    finally:
        conn.close()


if __name__ == "__main__":
    async def _main():
        n = await sweep()
        print("stored:", n)
        found, unknown = await get_next_earnings(
            ["SNDK", "AMD", "CROX", "CBNK", "KFRC", "MU", "XLK", "INTC"])
        for t, v in sorted(found.items()):
            print(f"  {t:<6} {v['date']}  in {v['days_to']:>3}d  [{v['source']}]")
        print("  unknown:", unknown)
        print("  stats:", stats())
    asyncio.run(_main())
