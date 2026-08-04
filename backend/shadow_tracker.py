"""Skipped-ticket shadow tracker — quantify the cost of CEO discretion.

The 2026-07-11 honest audit proved the model's top-5 picks did +9.4%/21td while
the account bled from *deviations* — off-model buys and early exits. This module
closes the measurement gap: it logs every trade ticket the operator delivers
(sent / executed / skipped) with the entry-day price, then back-fills forward
returns exactly like signal_tracker_update.py. The report compares EXECUTED vs
SKIPPED forward returns per horizon — i.e. what discretion cost (or saved).

Design mirrors signal_tracker_update.py on purpose:
  - Same forward-return primitive (next-day open -> close after N trading days,
    0.30% fee) reused via import, so the shadow book is directly comparable to
    the signal tracker and the live exit horizons (7/14/21/42/60 td).
  - Additive schema migration so an existing prod DB upgrades in place.
  - Idempotent: a ticket can be logged once (auto id) and its action updated
    later (sent -> executed / skipped) without losing back-filled returns.

Writes to backend/data/shadow_tracker.db (separate file — the shadow book is
audit bookkeeping, never touched by the scan/exit hot path).

Usage:
    python3 shadow_tracker.py --log NVDA skipped --price 172.50 --strategy MR \
        --score 71.2 --note "CEO passed, wanted more cash"
    python3 shadow_tracker.py --backfill-only   # only update forward returns
    python3 shadow_tracker.py --report          # executed-vs-skipped report
"""
import argparse
import os
import sqlite3
import statistics
import sys
from datetime import datetime

# Reuse the exact forward-return primitive + regime probe the signal tracker
# uses, so the two books are apples-to-apples and there is one source of truth.
from signal_tracker_update import _forward_return, _current_regime, HORIZONS, FEE_PCT

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'data', 'shadow_tracker.db')

VALID_ACTIONS = ('sent', 'executed', 'skipped')


def _conn():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS shadow_ticket (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sent_date   TEXT NOT NULL,
        ticker      TEXT NOT NULL,
        action      TEXT NOT NULL,          -- sent | executed | skipped
        strategy    TEXT,
        composite   REAL,
        price       REAL,                    -- price when the ticket was delivered
        size_usd    REAL,
        regime      TEXT,
        note        TEXT,
        created_at  TEXT,
        updated_at  TEXT,
        ret_7d REAL, ret_14d REAL, ret_21d REAL, ret_42d REAL, ret_60d REAL,
        qqq_21d REAL, qqq_60d REAL)""")
    # additive migration for an already-deployed prod DB
    cols = {r[1] for r in con.execute("PRAGMA table_info(shadow_ticket)")}
    _num_cols = ('composite', 'price', 'size_usd',
                 'ret_7d', 'ret_14d', 'ret_21d', 'ret_42d', 'ret_60d',
                 'qqq_21d', 'qqq_60d')
    _txt_cols = ('strategy', 'regime', 'note', 'created_at', 'updated_at')
    for col in _num_cols:
        if col not in cols:
            con.execute(f"ALTER TABLE shadow_ticket ADD COLUMN {col} REAL")
    for col in _txt_cols:
        if col not in cols:
            con.execute(f"ALTER TABLE shadow_ticket ADD COLUMN {col} TEXT")
    return con


def log_ticket(ticker, action, price=None, strategy=None, composite=None,
               size_usd=None, note=None, sent_date=None, ticket_id=None,
               regime=None):
    """Record a delivered ticket, or update an existing one's action/note.

    If ticket_id is given and exists, the row's action/note/size are updated
    (the sent -> executed/skipped lifecycle) and back-filled returns are kept.
    Otherwise a new row is inserted. Returns the ticket id.
    """
    action = (action or '').lower().strip()
    if action not in VALID_ACTIONS:
        raise ValueError(f"action must be one of {VALID_ACTIONS}, got {action!r}")
    ticker = (ticker or '').upper().strip()
    if not ticker:
        raise ValueError("ticker is required")
    now = datetime.now().isoformat(timespec='seconds')
    sent_date = sent_date or datetime.now().strftime('%Y-%m-%d')
    if regime is None:
        regime = _current_regime()

    con = _conn()
    try:
        if ticket_id is not None:
            row = con.execute("SELECT id FROM shadow_ticket WHERE id=?",
                              (ticket_id,)).fetchone()
            if row is None:
                raise ValueError(f"ticket_id {ticket_id} not found")
            con.execute(
                "UPDATE shadow_ticket SET action=?, "
                "note=COALESCE(?, note), size_usd=COALESCE(?, size_usd), "
                "updated_at=? WHERE id=?",
                (action, note, size_usd, now, ticket_id))
            con.commit()
            return ticket_id
        cur = con.execute(
            "INSERT INTO shadow_ticket "
            "(sent_date, ticker, action, strategy, composite, price, size_usd, "
            " regime, note, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sent_date, ticker, action, strategy, composite, price, size_usd,
             regime, note, now, now))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def backfill_returns():
    """Fill any NULL forward-return column that has become computable."""
    con = _conn()
    rows = con.execute(
        "SELECT id, ticker, sent_date FROM shadow_ticket "
        "WHERE ret_7d IS NULL OR ret_14d IS NULL OR ret_21d IS NULL "
        "   OR ret_42d IS NULL OR ret_60d IS NULL OR qqq_60d IS NULL"
    ).fetchall()
    updated = 0
    for _id, ticker, sent_date in rows:
        vals = {f'ret_{h}d': _forward_return(ticker, sent_date, h) for h in HORIZONS}
        vals['qqq_21d'] = _forward_return('QQQ', sent_date, 21)
        vals['qqq_60d'] = _forward_return('QQQ', sent_date, 60)
        sets = ", ".join(f"{k}=COALESCE({k},?)" for k in vals)
        con.execute(f"UPDATE shadow_ticket SET {sets} WHERE id=?",
                    (*vals.values(), _id))
        if any(v is not None for v in vals.values()):
            updated += 1
    con.commit()
    con.close()
    return updated


def _wr(xs):
    return sum(1 for x in xs if x > 0) / len(xs) * 100 if xs else float('nan')


def book_summary():
    """Structured executed-vs-skipped comparison, for the API and the CLI report.

    Returns a dict: {tickets, by_action, discretion_cost, benchmark}.
      - by_action[action][horizon] = {n, avg, wr}
      - discretion_cost[horizon] = executed_avg - skipped_avg (the alpha the
        operator's discretion added; negative means discretion HELPED by
        skipping losers).
    """
    con = _conn()
    cur = con.cursor()
    cur.execute("SELECT * FROM shadow_ticket ORDER BY sent_date, id")
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    con.close()

    by_action = {}
    for action in VALID_ACTIONS:
        sub = [r for r in rows if r['action'] == action]
        per_h = {}
        for h in HORIZONS:
            xs = [r[f'ret_{h}d'] for r in sub if r.get(f'ret_{h}d') is not None]
            per_h[h] = {
                'n': len(xs),
                'avg': round(statistics.mean(xs), 3) if xs else None,
                'wr': round(_wr(xs), 1) if xs else None,
            }
        by_action[action] = {'count': len(sub), 'horizons': per_h}

    discretion_cost = {}
    for h in HORIZONS:
        ex = by_action['executed']['horizons'][h]['avg']
        sk = by_action['skipped']['horizons'][h]['avg']
        discretion_cost[h] = (round(ex - sk, 3)
                              if ex is not None and sk is not None else None)

    qqq = [r['qqq_21d'] for r in rows if r.get('qqq_21d') is not None]
    benchmark = {'qqq_21d_avg': round(statistics.mean(qqq), 3) if qqq else None}

    return {
        'tickets': len(rows),
        'by_action': by_action,
        'discretion_cost': discretion_cost,  # executed_avg - skipped_avg per horizon
        'benchmark': benchmark,
        'rows': rows,
    }


def report():
    s = book_summary()
    if not s['tickets']:
        print("Shadow book is empty — no tickets logged yet.")
        return
    print(f"\n=== Shadow Ticket Book — {s['tickets']} tickets "
          f"(fee {FEE_PCT}% baked in) ===")
    hdr = f"{'action':<10}{'N':>4} " + "".join(f"{f'{h}d avg/WR':>15}" for h in HORIZONS)
    print("\n" + hdr)
    for action in VALID_ACTIONS:
        a = s['by_action'][action]
        row = f"{action:<10}{a['count']:>4} "
        for h in HORIZONS:
            c = a['horizons'][h]
            row += (f"{c['avg']:>+8.2f}/{c['wr']:>4.1f}%"
                    if c['avg'] is not None else f"{'—':>15}")
        print(row)

    print("\nDiscretion cost (executed_avg − skipped_avg; + = executing beat "
          "skipping, − = skipping was right):")
    for h in HORIZONS:
        d = s['discretion_cost'][h]
        print(f"  {h:>2}d: {d:+.2f}%" if d is not None else f"  {h:>2}d: —")
    b = s['benchmark']['qqq_21d_avg']
    if b is not None:
        print(f"\nBenchmark: QQQ 21d avg {b:+.2f}% over the same signal dates")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description="Skipped-ticket shadow tracker")
    p.add_argument('--log', nargs=2, metavar=('TICKER', 'ACTION'),
                   help="log a ticket, e.g. --log NVDA skipped")
    p.add_argument('--price', type=float)
    p.add_argument('--strategy')
    p.add_argument('--score', type=float, help="composite score")
    p.add_argument('--size', type=float, help="size in USD")
    p.add_argument('--note')
    p.add_argument('--backfill-only', action='store_true')
    p.add_argument('--report', action='store_true')
    args = p.parse_args()

    if args.log:
        ticker, action = args.log
        tid = log_ticket(ticker, action, price=args.price, strategy=args.strategy,
                         composite=args.score, size_usd=args.size, note=args.note)
        print(f"Logged ticket #{tid}: {ticker.upper()} {action.lower()}")
        u = backfill_returns()
        print(f"Back-filled forward returns: {u} rows updated")
        sys.exit(0)

    if args.report:
        report()
        sys.exit(0)

    u = backfill_returns()
    print(f"Back-filled forward returns: {u} rows updated")
    report()
