"""Signal Tracker — daily update job.

Snapshots the Entries-tab top-20 from the entries_YYYY-MM-DD.json cache and
back-fills forward returns for older signals as new prices land. Run daily.

V2 (2026-07-19 forward-testing overhaul):
  - Horizons extended to the ACTUAL exit horizons: 7 / 14 / 21 / 42 / 60 td
    (Fixed60d is the live MR exit — a tracker that stops at 21d cannot
    forward-test the system it monitors).
  - QQQ forward return captured per signal at 21/60d -> every WR readout is
    benchmarked, not naked.
  - Market regime recorded at snapshot time (regime-conditional edge is the
    validated story; unconditioned WR is noise).
  - Empty snapshots are recorded in snapshot_log so "tab showed nothing" is
    distinguishable from "tracker didn't run".
  - Report: per-sleeve x per-horizon WR/avg vs QQQ, rank bands at 21d/60d.

Writes to backend/data/signal_tracker.db.

Usage:
    python3 signal_tracker_update.py                  # daily snapshot + backfill
    python3 signal_tracker_update.py --backfill-only  # only update forward returns
    python3 signal_tracker_update.py --report         # print performance report
"""
import argparse, json, os, sqlite3, sys, statistics
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'data', 'signal_tracker.db')
ENTRIES_DIR = os.path.join(HERE, 'data')  # entries_YYYY-MM-DD.json live here
STOCK_DB = os.path.join(HERE, 'data', 'stock_cache.db')
TOP_N = 20
FEE_PCT = 0.30
HORIZONS = (7, 14, 21, 42, 60)

def _conn():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS signal_track (
        scan_date TEXT, ticker TEXT, rank INTEGER, price_at_signal REAL, score REAL,
        expected_return REAL, confidence REAL, strategy TEXT, strategy_label TEXT,
        trades INTEGER, rsi2 REAL, atr_pct REAL,
        ret_7d REAL, ret_14d REAL, ret_21d REAL,
        PRIMARY KEY(scan_date, ticker))""")
    con.execute("""CREATE TABLE IF NOT EXISTS snapshot_log (
        scan_date TEXT PRIMARY KEY, n_signals INTEGER, regime TEXT, note TEXT)""")
    # additive migration for existing prod DB
    cols = {r[1] for r in con.execute("PRAGMA table_info(signal_track)")}
    for col in ('ret_42d', 'ret_60d', 'qqq_21d', 'qqq_60d', 'regime', 'composite'):
        if col not in cols:
            con.execute(f"ALTER TABLE signal_track ADD COLUMN {col} REAL"
                        if col != 'regime' else
                        "ALTER TABLE signal_track ADD COLUMN regime TEXT")
    return con

def _forward_return(ticker, signal_date, hold_days, _cache={}):
    """Forward return from next-day open to close after `hold_days` trading days.
    Uses stock_cache.db daily_prices. Returns None if not enough forward bars."""
    key = (ticker, signal_date)
    if key not in _cache:
        sc = sqlite3.connect(STOCK_DB)
        _cache[key] = sc.execute(
            "SELECT date, open, close FROM daily_prices WHERE ticker=? AND date>=? ORDER BY date",
            (ticker, signal_date)).fetchall()
        sc.close()
        if len(_cache) > 4000:  # bound memory on huge backfills
            _cache.pop(next(iter(_cache)))
    rows = _cache[key]
    if len(rows) < hold_days + 1: return None
    entry_open = rows[1][1] if rows[1][1] and rows[1][1] > 0 else None
    if entry_open is None: return None
    exit_close = rows[hold_days][2]
    return ((exit_close - entry_open) / entry_open) * 100 - FEE_PCT

def _current_regime():
    try:
        import api_v2
        r = api_v2._check_market_regime()
        return r.get('regime') if isinstance(r, dict) else None
    except Exception:
        return None

def snapshot_today():
    """Read today's entries_YYYY-MM-DD.json and write top-20 picks into signal_track.
    Ranks by composite_score (the live tab sort, V3.5), tiebreak Buffered WR."""
    today = datetime.now().strftime('%Y-%m-%d')
    path = os.path.join(ENTRIES_DIR, f'entries_{today}.json')
    con = _conn()
    regime = _current_regime()
    if not os.path.exists(path):
        con.execute("INSERT OR REPLACE INTO snapshot_log VALUES (?,?,?,?)",
                    (today, -1, regime, 'no entries file'))
        con.commit(); con.close()
        print(f"  No snapshot file at {path} — logged")
        return 0
    entries = json.load(open(path))
    valid = sorted([e for e in entries if not e.get('vetoed')],
                   key=lambda x: (x.get('composite_score') or 0, x.get('score') or 0),
                   reverse=True)[:TOP_N]
    con.execute("INSERT OR REPLACE INTO snapshot_log VALUES (?,?,?,?)",
                (today, len(valid), regime,
                 'EMPTY TAB' if not valid else ''))
    inserted = 0
    for rank, e in enumerate(valid, 1):
        con.execute("""INSERT OR REPLACE INTO signal_track
            (scan_date, ticker, rank, price_at_signal, score, expected_return,
             confidence, strategy, strategy_label, trades, rsi2, atr_pct,
             composite, regime,
             ret_7d, ret_14d, ret_21d, ret_42d, ret_60d, qqq_21d, qqq_60d)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                    (SELECT ret_7d  FROM signal_track WHERE scan_date=? AND ticker=?),
                    (SELECT ret_14d FROM signal_track WHERE scan_date=? AND ticker=?),
                    (SELECT ret_21d FROM signal_track WHERE scan_date=? AND ticker=?),
                    (SELECT ret_42d FROM signal_track WHERE scan_date=? AND ticker=?),
                    (SELECT ret_60d FROM signal_track WHERE scan_date=? AND ticker=?),
                    (SELECT qqq_21d FROM signal_track WHERE scan_date=? AND ticker=?),
                    (SELECT qqq_60d FROM signal_track WHERE scan_date=? AND ticker=?))""",
            (today, e['ticker'], rank, e['price'], e.get('score', 0),
             e.get('expected_return', 0), e.get('confidence', 0),
             e.get('strategy', ''), e.get('strategy_label', ''),
             e.get('trades', 0), e.get('rsi2', 0), e.get('atr_pct', 0),
             e.get('composite_score'), regime,
             *[x for pair in [(today, e['ticker'])] * 7 for x in pair]))
        inserted += 1
    con.commit(); con.close()
    return inserted

def backfill_returns():
    """Fill any NULL forward-return column that has become computable."""
    con = _conn()
    rows = con.execute(
        "SELECT scan_date, ticker FROM signal_track "
        "WHERE ret_7d IS NULL OR ret_14d IS NULL OR ret_21d IS NULL "
        "   OR ret_42d IS NULL OR ret_60d IS NULL OR qqq_60d IS NULL"
    ).fetchall()
    updated = 0
    for scan_date, ticker in rows:
        vals = {f'ret_{h}d': _forward_return(ticker, scan_date, h) for h in HORIZONS}
        vals['qqq_21d'] = _forward_return('QQQ', scan_date, 21)
        vals['qqq_60d'] = _forward_return('QQQ', scan_date, 60)
        sets = ", ".join(f"{k}=COALESCE({k},?)" for k in vals)
        con.execute(f"UPDATE signal_track SET {sets} WHERE scan_date=? AND ticker=?",
                    (*vals.values(), scan_date, ticker))
        if any(v is not None for v in vals.values()):
            updated += 1
    con.commit(); con.close()
    return updated

def _wr(xs):
    return sum(1 for x in xs if x > 0) / len(xs) * 100 if xs else float('nan')

def report():
    """Per-sleeve x per-horizon WR/avg vs QQQ; rank bands; regime split."""
    con = _conn()
    cur = con.cursor()
    cur.execute("SELECT * FROM signal_track")
    cols = [d[0] for d in cur.description]
    rs = [dict(zip(cols, r)) for r in cur.fetchall()]
    ev = [r for r in rs if r.get('ret_7d') is not None]
    if not ev:
        print("No evaluated signals yet."); con.close(); return

    print(f"\n=== Signal Tracker Report — {len(ev)} evaluated signals "
          f"({min(r['scan_date'] for r in ev)} → {max(r['scan_date'] for r in ev)}) ===")

    print(f"\n{'sleeve':<16}{'N':>5} " + "".join(f"{f'{h}d avg/WR':>16}" for h in HORIZONS)
          + f"{'QQQ 60d':>10}")
    for s in ('MEAN_REVERSION', 'BOTH', 'MOMENTUM'):
        sub = [r for r in ev if r['strategy'] == s and r['rank'] <= 5]
        if not sub: continue
        row = f"{s:<16}{len(sub):>5} "
        for h in HORIZONS:
            xs = [r[f'ret_{h}d'] for r in sub if r.get(f'ret_{h}d') is not None]
            row += f"{(statistics.mean(xs) if xs else float('nan')):>+8.2f}/{_wr(xs):>5.1f}%" if xs else f"{'—':>16}"
        q = [r['qqq_60d'] for r in sub if r.get('qqq_60d') is not None]
        row += f"{(statistics.mean(q) if q else float('nan')):>+9.2f}%" if q else f"{'—':>10}"
        print(row)

    print("\nRank bands (21d | 60d):")
    for lo, hi in [(1, 3), (4, 5), (6, 10), (11, 20)]:
        sub = [r for r in ev if lo <= r['rank'] <= hi]
        if not sub: continue
        x21 = [r['ret_21d'] for r in sub if r.get('ret_21d') is not None]
        x60 = [r['ret_60d'] for r in sub if r.get('ret_60d') is not None]
        f21 = f"{statistics.mean(x21):+6.2f}%/{_wr(x21):4.1f}% (n={len(x21)})" if x21 else "—"
        f60 = f"{statistics.mean(x60):+6.2f}%/{_wr(x60):4.1f}% (n={len(x60)})" if x60 else "—"
        print(f"  rank {lo:>2}-{hi:<2}:  21d {f21}   60d {f60}")

    regs = sorted({r.get('regime') for r in ev if r.get('regime')})
    if regs:
        print("\nBy regime at signal (top-5, 21d):")
        for g in regs:
            sub = [r for r in ev if r.get('regime') == g and r['rank'] <= 5
                   and r.get('ret_21d') is not None]
            if not sub: continue
            xs = [r['ret_21d'] for r in sub]
            print(f"  {g:<14} N={len(xs):>3}  avg {statistics.mean(xs):+6.2f}%  WR {_wr(xs):4.1f}%")

    cur.execute("SELECT scan_date, n_signals, regime, note FROM snapshot_log "
                "ORDER BY scan_date DESC LIMIT 10")
    logs = cur.fetchall()
    if logs:
        print("\nRecent snapshots (date, n, regime):")
        for d, n, g, note in logs:
            print(f"  {d}  n={n:<3} {g or '?':<12} {note or ''}")
    con.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--backfill-only', action='store_true')
    p.add_argument('--report', action='store_true')
    args = p.parse_args()
    if args.report:
        report(); sys.exit(0)
    if not args.backfill_only:
        n = snapshot_today()
        print(f"Snapshotted top-{TOP_N} for today: {n} rows")
    u = backfill_returns()
    print(f"Back-filled forward returns: {u} rows updated")
    report()
