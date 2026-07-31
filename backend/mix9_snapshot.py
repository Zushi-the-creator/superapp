#!/usr/bin/env python3
"""Compute the MIX9 target book and write it to mix9.db as a snapshot.

Run as a SUBPROCESS, never in the API process. Mix9Data needs several hundred MB
and the 2GB Fly machine already runs the scanner, cache, sim engine and sector
intel — computing in-process OOM-killed the whole app. A subprocess releases
every byte back to the OS on exit, and the API then serves the cheap snapshot.

MIX9 only rebalances monthly, so a snapshot refreshed once per day is not stale
in any way that matters.

usage:  python3 mix9_snapshot.py <equity_usd> '<holdings_json>'
"""
import json, sys, sqlite3, os
import mix9_engine as M

HERE = os.path.dirname(os.path.abspath(__file__))


def save(payload: dict) -> None:
    M.init_db()
    with M._connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS mix9_snapshot ("
                  "id INTEGER PRIMARY KEY CHECK (id=1), computed_at TEXT, payload TEXT)")
        c.execute("INSERT OR REPLACE INTO mix9_snapshot (id, computed_at, payload) "
                  "VALUES (1, datetime('now'), ?)", (json.dumps(payload),))


def load() -> dict:
    M.init_db()
    with M._connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS mix9_snapshot ("
                  "id INTEGER PRIMARY KEY CHECK (id=1), computed_at TEXT, payload TEXT)")
        r = c.execute("SELECT computed_at, payload FROM mix9_snapshot WHERE id=1").fetchone()
    if not r:
        return {}
    out = json.loads(r["payload"])
    out["computed_at"] = r["computed_at"]
    return out


if __name__ == '__main__':
    equity = float(sys.argv[1]) if len(sys.argv) > 1 else 19511.0
    holdings = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    res = M.run_cycle(equity, holdings, dry_run=False, force=True)
    res["holdings"] = holdings
    save(res)
    t = res["target"]
    print(f"MIX9 snapshot saved: {t['asof']} {t['regime']} -> {t['active_strategy']} "
          f"parked={t['parked']} trades={len(res['trades'])}")
