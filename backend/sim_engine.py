"""
SIM ENGINE — $100,000 autonomous multi-strategy paper book
===========================================================

A fully separate, self-contained simulation portfolio. It NEVER touches
positions.db or any live money path — its own SQLite file (data/sim.db),
its own cash ledger, its own decision journal.

The book runs a REGISTRY of named strategies (see STRATEGIES below), each
carrying an explicit evidence tier so the UI can never present an unvalidated
sleeve as if it were a validated one:

    Tier A — survived a walk-forward on our own data. Safe to size.
    Tier B — supported by a study but not yet walk-forward validated here.
    Tier C — documented as weak/unvalidated. Available, off by default.

Every fill — model-driven or manual — is journalled with its full rationale,
and manual trades are tagged separately so discretionary decisions can be
measured against the model's instead of quietly blending into the track record.

This module is intentionally free of any api_v2 import (no circular deps).
The caller supplies live inputs (regime, signals, prices, technicals, earnings,
sentiment) and this module owns the policy, the ledger and the journal.
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "sim.db")

STARTING_CAPITAL = 100_000.0
BENCH_TICKER = "QQQ"


# ──────────────────────────────────────────────────────────────────────────
# Strategy registry
# ──────────────────────────────────────────────────────────────────────────
# `source` tells the engine where candidates come from:
#   MR        — mean-reversion signals (MEAN_REVERSION / BOTH) from /scan/combined
#   BREAKOUT  — momentum signals within `max_high52_dist`% of the 252d high
#   MOM       — raw momentum-scanner signals
#   ROTATION  — monthly top-N of the 12-1 large-cap momentum ranking
#   CORE      — passive index sleeve, rebalanced in a band
#
# `exit` is the ONLY way a position leaves the book (plus the two universal
# exits: earnings <=7d and stock-specific negative sentiment).

STRATEGIES: Dict[str, Dict] = {
    "CORE_QQQ": {
        "label": "Core · QQQ passive",
        "short": "CORE",
        "tier": "A",
        "kind": "CORE",
        "source": "CORE",
        "exit": {"type": "rebalance"},
        "default_enabled": 1,
        "default_slots": 0,          # sized by core_target_pct, not slots
        "thesis": "Hold beta. Every always-on active config in the master-harness "
                  "study lost to QQQ out-of-sample by 13-29pp, and time-in-market "
                  "explained ~90% of return variance.",
        "evidence": "_master_harness3.py (2026-07-24); needle-movers study (2026-07-24)",
    },
    "MR_FIXED42": {
        "label": "Mean Reversion · Fixed42d",
        "short": "MR42",
        "tier": "A",
        "kind": "ALPHA",
        "source": "MR",
        "exit": {"type": "timer", "days": 42},
        "default_enabled": 1,
        "default_slots": 5,
        "thesis": "RSI2<10 above SMA50 with ATR>=3% and a >=5% SMA50 buffer, held "
                  "to a fixed 42-trading-day timer. The production entry.",
        "evidence": "17-window rolling walk-forward on clean Tiingo data — Fixed42 "
                    "won 8/17 windows, +30.8% compounded vs Fixed60 -26.1%",
    },
    "SWING_RSI75": {
        "label": "Swing MR · RSI75 fast exit",
        "short": "SWING",
        "tier": "C",
        "kind": "ALPHA",
        "source": "MR",
        "exit": {"type": "rsi", "rsi_above": 75, "max_days": 21},
        "default_enabled": 1,
        "default_slots": 2,
        "entry_max_rsi2": 10,        # must be a live dip, not a bounced signal
        "thesis": "Connors-style short hold: same oversold entry, exit the moment "
                  "RSI(2) clears 75 or at 21 days. ~6-day holds, 64-70% win rate — "
                  "the closest thing here to day-trading the bounce.",
        "evidence": "_exit_family_bt.py (7,322 signals): 64-70% WR, best per-day cell "
                    "in DIP regimes (0.23%/day) — BUT lost to fixed timers in every "
                    "portfolio simulation: it cuts winners at +2% while losers ride "
                    "to the cap, and the fee churn compounds against you.",
    },
    "BREAKOUT_52W": {
        "label": "52-week breakout · Fixed90d",
        "short": "BRK52",
        "tier": "B",
        "kind": "ALPHA",
        "source": "BREAKOUT",
        "exit": {"type": "timer", "days": 90},
        "default_enabled": 1,
        "default_slots": 2,
        "max_high52_dist": 5.0,      # within 5% of the 252-day high
        "thesis": "Minervini-style: buy strength within 5% of the 52-week high and "
                  "hold 90 trading days. The momentum GATE works at the right "
                  "horizon — it's the tab's ranking inside it that rotted.",
        "evidence": "_alt_strategy_bt.py: 56.4% WR / +4.62% per trade out-of-sample, "
                    "59.5% WR on 2025+ data. Not yet walk-forward validated here.",
    },
    "MOM_ROT_12_1": {
        "label": "Large-cap 12-1 rotation",
        "short": "ROT121",
        "tier": "B",
        "kind": "ALPHA",
        "source": "ROTATION",
        "exit": {"type": "monthly_rank"},
        "default_enabled": 1,
        "default_slots": 3,
        "thesis": "Monthly rebalance into the top large-caps by 12-month-minus-1 "
                  "momentum. Equal weight, no SMA gate (gates hurt in our tests).",
        "evidence": "_mom_rotation_bt.py: 32.5% CAGR / -40.9% MDD / 63.5% monthly WR "
                    "on 2017+ — but SURVIVORSHIP-INFLATED (live SPMO analog 18.6%/yr) "
                    "and param-sensitive. Treat the number as an upper bound.",
    },
    "MOM_FIXED90": {
        "label": "Momentum scanner · Fixed90d",
        "short": "MOM90",
        "tier": "C",
        "kind": "ALPHA",
        "source": "MOM",
        "exit": {"type": "timer", "days": 90},
        "default_enabled": 0,
        "default_slots": 2,
        "thesis": "The production momentum scanner's own ranking, held 90 days.",
        "evidence": "Ranks by ret20 x volume ratio — documented spike-chasing that has "
                    "never passed walk-forward. Off by default; BREAKOUT_52W is the "
                    "validated way to take the same momentum gate.",
    },
}

ALPHA_STRATEGIES = [k for k, v in STRATEGIES.items() if v["kind"] == "ALPHA"]

# Legacy signal labels → strategy ids (rows written before the registry existed)
_LEGACY_STRATEGY_MAP = {
    "MEAN_REVERSION": "MR_FIXED42",
    "BOTH": "MR_FIXED42",
    "MOMENTUM": "MOM_FIXED90",
    "CORE": "CORE_QQQ",
}

DEFAULT_CONFIG = {
    "enabled": 1,                  # master switch for the autonomous loop
    "starting_capital": STARTING_CAPITAL,
    "cycle_minutes": 60,           # how often the loop runs during market hours
    # ── Sleeve allocation ──
    "core_ticker": BENCH_TICKER,
    "core_target_pct": 40.0,       # % of equity held passively in the core sleeve
    "core_band_pct": 5.0,          # rebalance only when drift exceeds this
    # ── Per-strategy switches (strategy_id -> 0/1 and slot count) ──
    "strategy_enabled": {k: v["default_enabled"] for k, v in STRATEGIES.items()},
    "strategy_slots": {k: v["default_slots"] for k, v in STRATEGIES.items()},
    # ── Shared alpha risk limits ──
    "max_position_pct": 15.0,      # hard cap of equity in one alpha name
    "min_position_usd": 750.0,     # don't open dust
    "min_composite": 45.0,         # composite_score floor for a signal entry
    "max_per_sector": 3,           # concentration guard
    # ── Rotation / switching ──
    "rotation_enabled": 0,         # OFF: tested at -13 to -24 CAGR pts vs holding
    "rotation_min_gap": 15.0,      # candidate composite must beat the held one by this
    "rotation_min_days": 5,        # don't churn a position opened days ago
    # ── Costs ──
    "commission_usd": 1.50,        # per fill, matches the real broker
    "slippage_bps": 5.0,           # 0.05% each way
    "cash_floor_usd": 0.0,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sim_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    sleeve TEXT NOT NULL,              -- CORE | ALPHA
    strategy TEXT NOT NULL,            -- strategy id from STRATEGIES
    entry_date TEXT NOT NULL,          -- YYYY-MM-DD (ET)
    entry_ts TEXT NOT NULL,
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    cost_basis REAL NOT NULL,          -- incl. fees/slippage actually paid
    hold_days INTEGER NOT NULL,        -- trading days until the timer fires
    status TEXT NOT NULL DEFAULT 'OPEN',
    exit_date TEXT, exit_ts TEXT, exit_price REAL,
    exit_reason TEXT, realized_pnl REAL, fees REAL DEFAULT 0,
    entry_composite REAL DEFAULT 0,
    origin TEXT DEFAULT 'MODEL',       -- MODEL | MANUAL
    rationale TEXT
);
CREATE INDEX IF NOT EXISTS idx_sim_pos_status ON sim_positions(status);

CREATE TABLE IF NOT EXISTS sim_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, date TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,              -- DEPOSIT | BUY | SELL
    price REAL DEFAULT 0, shares REAL DEFAULT 0,
    gross REAL DEFAULT 0,              -- price * shares (pre-cost)
    fee REAL DEFAULT 0, slippage REAL DEFAULT 0,
    cash_delta REAL NOT NULL,          -- signed effect on cash
    realized_pnl REAL,
    sleeve TEXT, strategy TEXT, origin TEXT DEFAULT 'MODEL',
    reason TEXT, position_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sim_tx_date ON sim_transactions(date);

CREATE TABLE IF NOT EXISTS sim_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, cycle_id TEXT NOT NULL,
    kind TEXT NOT NULL,                -- CYCLE|ENTRY|EXIT|HOLD|SKIP|REBALANCE|PAUSE|SWITCH|MANUAL
    ticker TEXT DEFAULT '',
    action TEXT DEFAULT '',            -- BUY|SELL|NONE
    strategy TEXT DEFAULT '',
    origin TEXT DEFAULT 'MODEL',
    reason TEXT DEFAULT '',
    regime TEXT DEFAULT '',
    composite REAL DEFAULT 0,
    detail TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sim_dec_ts ON sim_decisions(ts);

CREATE TABLE IF NOT EXISTS sim_equity (
    date TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    cash REAL NOT NULL, positions_value REAL NOT NULL, equity REAL NOT NULL,
    core_value REAL DEFAULT 0, alpha_value REAL DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    bench_price REAL DEFAULT 0, bench_equity REAL DEFAULT 0,
    regime TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sim_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ──────────────────────────────────────────────────────────────────────────
# Storage
# ──────────────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_initialized = False


def init_db(starting_capital: float = STARTING_CAPITAL) -> None:
    """Create tables and, on a first-ever run, fund the book."""
    global _initialized
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        # Additive migrations for books created before a column existed
        for table, col, decl in (
            ("sim_positions", "origin", "TEXT DEFAULT 'MODEL'"),
            ("sim_transactions", "strategy", "TEXT"),
            ("sim_transactions", "origin", "TEXT DEFAULT 'MODEL'"),
            ("sim_decisions", "strategy", "TEXT DEFAULT ''"),
            ("sim_decisions", "origin", "TEXT DEFAULT 'MODEL'"),
        ):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass
        # Legacy signal labels -> registry ids
        for old, new in _LEGACY_STRATEGY_MAP.items():
            conn.execute("UPDATE sim_positions SET strategy=? WHERE strategy=?", (new, old))

        row = conn.execute(
            "SELECT COUNT(*) c FROM sim_transactions WHERE action='DEPOSIT'"
        ).fetchone()
        if row["c"] == 0:
            now = datetime.now()
            conn.execute(
                """INSERT INTO sim_transactions
                   (ts, date, ticker, action, cash_delta, reason)
                   VALUES (?,?,?,?,?,?)""",
                (now.isoformat(), now.strftime("%Y-%m-%d"), "CASH", "DEPOSIT",
                 float(starting_capital), "Initial simulation funding"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO sim_meta (key, value) VALUES ('inception', ?)",
                (now.isoformat(),),
            )
        conn.commit()
    finally:
        conn.close()
    _initialized = True


def _ensure() -> None:
    if not _initialized:
        init_db()


def get_config() -> Dict:
    _ensure()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    conn = _connect()
    try:
        for r in conn.execute("SELECT key, value FROM sim_config"):
            if r["key"] not in cfg:
                continue
            try:
                cfg[r["key"]] = json.loads(r["value"])
            except Exception:
                cfg[r["key"]] = r["value"]
    finally:
        conn.close()
    # A strategy added to the registry after the config was saved must still
    # get its default rather than vanishing from the dicts.
    for k, v in STRATEGIES.items():
        cfg["strategy_enabled"].setdefault(k, v["default_enabled"])
        cfg["strategy_slots"].setdefault(k, v["default_slots"])
    return cfg


def set_config(patch: Dict) -> Dict:
    """Update config keys. Unknown keys are ignored (no silent typo damage).
    The two per-strategy dicts are merged, not replaced, so a partial patch
    like {"strategy_enabled": {"SWING_RSI75": 1}} leaves the rest intact."""
    _ensure()
    cur = get_config()
    conn = _connect()
    try:
        for k, v in (patch or {}).items():
            if k not in DEFAULT_CONFIG:
                continue
            if k in ("strategy_enabled", "strategy_slots") and isinstance(v, dict):
                merged = dict(cur[k])
                merged.update({sk: sv for sk, sv in v.items() if sk in STRATEGIES})
                v = merged
            conn.execute(
                "INSERT OR REPLACE INTO sim_config (key, value) VALUES (?,?)",
                (k, json.dumps(v)),
            )
        conn.commit()
    finally:
        conn.close()
    return get_config()


def reset(starting_capital: float = STARTING_CAPITAL, keep_config: bool = True) -> Dict:
    """Wipe the book back to day zero. Destructive — routes gate this."""
    global _initialized
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        for t in ("sim_positions", "sim_transactions", "sim_decisions",
                  "sim_equity", "sim_meta"):
            conn.execute(f"DELETE FROM {t}")
        if not keep_config:
            conn.execute("DELETE FROM sim_config")
        conn.commit()
    finally:
        conn.close()
    _initialized = False
    init_db(starting_capital)
    return get_state()


# ──────────────────────────────────────────────────────────────────────────
# Ledger primitives
# ──────────────────────────────────────────────────────────────────────────

def get_cash(conn: Optional[sqlite3.Connection] = None) -> float:
    _ensure()
    own = conn is None
    conn = conn or _connect()
    try:
        r = conn.execute("SELECT COALESCE(SUM(cash_delta),0) c FROM sim_transactions").fetchone()
        return round(float(r["c"] or 0), 2)
    finally:
        if own:
            conn.close()


def get_open_positions(conn: Optional[sqlite3.Connection] = None) -> List[Dict]:
    _ensure()
    own = conn is None
    conn = conn or _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sim_positions WHERE status='OPEN' ORDER BY entry_ts"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        if own:
            conn.close()


def get_closed_positions(limit: int = 200) -> List[Dict]:
    _ensure()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sim_positions WHERE status='CLOSED' ORDER BY exit_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_transactions(limit: int = 200) -> List[Dict]:
    _ensure()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sim_transactions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_decisions(limit: int = 150, kinds: Optional[List[str]] = None) -> List[Dict]:
    _ensure()
    conn = _connect()
    try:
        if kinds:
            q = ",".join("?" * len(kinds))
            rows = conn.execute(
                f"SELECT * FROM sim_decisions WHERE kind IN ({q}) ORDER BY id DESC LIMIT ?",
                (*kinds, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sim_decisions ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["detail"] = json.loads(d.get("detail") or "{}")
            except Exception:
                d["detail"] = {}
            d["strategy_label"] = STRATEGIES.get(d.get("strategy") or "", {}).get("label", "")
            out.append(d)
        return out
    finally:
        conn.close()


def get_equity_curve(limit: int = 400) -> List[Dict]:
    _ensure()
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sim_equity ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


def _log(conn: sqlite3.Connection, cycle_id: str, kind: str, *, ticker: str = "",
         action: str = "NONE", reason: str = "", regime: str = "", strategy: str = "",
         origin: str = "MODEL", composite: float = 0,
         detail: Optional[Dict] = None) -> None:
    conn.execute(
        """INSERT INTO sim_decisions
           (ts, cycle_id, kind, ticker, action, strategy, origin, reason, regime,
            composite, detail)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), cycle_id, kind, ticker, action, strategy, origin,
         reason, regime, float(composite or 0), json.dumps(detail or {}, default=str)),
    )


# ──────────────────────────────────────────────────────────────────────────
# Trading-day math
# ──────────────────────────────────────────────────────────────────────────

def weekdays_between(start: str, end: str) -> int:
    """Trading days elapsed, weekday-counted (matches the live positions logic).

    Holidays are not excluded — the same approximation production uses, so a
    sim position and a live position of the same age agree on their countdown.
    """
    try:
        d0 = datetime.strptime(start[:10], "%Y-%m-%d").date()
        d1 = datetime.strptime(end[:10], "%Y-%m-%d").date()
    except Exception:
        return 0
    if d1 <= d0:
        return 0
    days = 0
    cur = d0
    while cur < d1:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def days_held(pos: Dict, today: Optional[str] = None) -> int:
    return weekdays_between(pos["entry_date"], today or datetime.now().strftime("%Y-%m-%d"))


def strategy_of(pos: Dict) -> Dict:
    sid = pos.get("strategy") or ""
    return STRATEGIES.get(sid) or STRATEGIES.get(_LEGACY_STRATEGY_MAP.get(sid, ""), {})


# ──────────────────────────────────────────────────────────────────────────
# Fills
# ──────────────────────────────────────────────────────────────────────────

def _fill_price(price: float, side: str, slippage_bps: float) -> float:
    """Adverse-fill model: you always cross the spread against yourself."""
    adj = price * (slippage_bps / 10_000.0)
    return round(price + adj if side == "BUY" else price - adj, 4)


def open_position(conn, *, ticker: str, strategy_id: str, price: float,
                  dollars: float, cfg: Dict, rationale: Dict,
                  composite: float = 0, origin: str = "MODEL") -> Optional[Dict]:
    """Buy `dollars` worth at an adverse fill. Returns the new position or None."""
    if price <= 0 or dollars <= 0:
        return None
    strat = STRATEGIES.get(strategy_id)
    if not strat:
        return None
    fill = _fill_price(price, "BUY", cfg["slippage_bps"])
    fee = float(cfg["commission_usd"])
    investable = dollars - fee
    if investable <= 0:
        return None
    shares = investable / fill
    gross = shares * fill
    total_cost = gross + fee
    cash = get_cash(conn)
    if total_cost > cash - float(cfg.get("cash_floor_usd", 0)):
        return None

    now = datetime.now()
    exit_rule = strat["exit"]
    hold = exit_rule.get("days") or exit_rule.get("max_days") or 99_999
    sleeve = strat["kind"]
    cur = conn.execute(
        """INSERT INTO sim_positions
           (ticker, sleeve, strategy, entry_date, entry_ts, entry_price, shares,
            cost_basis, hold_days, status, fees, entry_composite, origin, rationale)
           VALUES (?,?,?,?,?,?,?,?,?,'OPEN',?,?,?,?)""",
        (ticker, sleeve, strategy_id, now.strftime("%Y-%m-%d"), now.isoformat(),
         fill, shares, total_cost, int(hold), fee, float(composite or 0), origin,
         json.dumps(rationale, default=str)),
    )
    pid = cur.lastrowid
    conn.execute(
        """INSERT INTO sim_transactions
           (ts, date, ticker, action, price, shares, gross, fee, slippage,
            cash_delta, sleeve, strategy, origin, reason, position_id)
           VALUES (?,?,?,'BUY',?,?,?,?,?,?,?,?,?,?,?)""",
        (now.isoformat(), now.strftime("%Y-%m-%d"), ticker, fill, shares, gross,
         fee, round(abs(fill - price) * shares, 2), -round(total_cost, 2),
         sleeve, strategy_id, origin, rationale.get("summary", ""), pid),
    )
    return {"id": pid, "ticker": ticker, "shares": shares, "price": fill,
            "cost": round(total_cost, 2), "sleeve": sleeve, "strategy": strategy_id,
            "strategy_label": strat["label"], "origin": origin}


def close_position(conn, pos: Dict, price: float, reason: str, cfg: Dict,
                   shares: Optional[float] = None,
                   origin: str = "MODEL") -> Optional[Dict]:
    """Sell (all, or a partial slice for core rebalancing) at an adverse fill."""
    if price <= 0:
        return None
    sell_shares = pos["shares"] if shares is None else min(shares, pos["shares"])
    if sell_shares <= 0:
        return None
    fill = _fill_price(price, "SELL", cfg["slippage_bps"])
    fee = float(cfg["commission_usd"])
    gross = sell_shares * fill
    proceeds = gross - fee
    frac = sell_shares / pos["shares"]
    cost_slice = pos["cost_basis"] * frac
    pnl = round(proceeds - cost_slice, 2)
    now = datetime.now()
    partial = sell_shares < pos["shares"] - 1e-9

    if partial:
        conn.execute(
            "UPDATE sim_positions SET shares=?, cost_basis=?, fees=fees+? WHERE id=?",
            (pos["shares"] - sell_shares, pos["cost_basis"] - cost_slice, fee, pos["id"]),
        )
    else:
        conn.execute(
            """UPDATE sim_positions
               SET status='CLOSED', exit_date=?, exit_ts=?, exit_price=?,
                   exit_reason=?, realized_pnl=?, fees=fees+?
               WHERE id=?""",
            (now.strftime("%Y-%m-%d"), now.isoformat(), fill, reason, pnl, fee, pos["id"]),
        )
    conn.execute(
        """INSERT INTO sim_transactions
           (ts, date, ticker, action, price, shares, gross, fee, slippage,
            cash_delta, realized_pnl, sleeve, strategy, origin, reason, position_id)
           VALUES (?,?,?,'SELL',?,?,?,?,?,?,?,?,?,?,?,?)""",
        (now.isoformat(), now.strftime("%Y-%m-%d"), pos["ticker"], fill, sell_shares,
         gross, fee, round(abs(price - fill) * sell_shares, 2), round(proceeds, 2),
         pnl, pos["sleeve"], pos.get("strategy"), origin, reason, pos["id"]),
    )
    return {"id": pos["id"], "ticker": pos["ticker"], "shares": sell_shares,
            "price": fill, "proceeds": round(proceeds, 2), "pnl": pnl,
            "pnl_pct": round(pnl / cost_slice * 100, 2) if cost_slice else 0,
            "strategy": pos.get("strategy"), "reason": reason, "origin": origin}


# ──────────────────────────────────────────────────────────────────────────
# Valuation
# ──────────────────────────────────────────────────────────────────────────

def value_book(prices: Dict[str, float], conn=None) -> Dict:
    _ensure()
    own = conn is None
    conn = conn or _connect()
    try:
        cash = get_cash(conn)
        positions = get_open_positions(conn)
        core_val = alpha_val = 0.0
        enriched = []
        today = datetime.now().strftime("%Y-%m-%d")
        for p in positions:
            px = float(prices.get(p["ticker"]) or p["entry_price"])
            val = px * p["shares"]
            pnl = val - p["cost_basis"]
            held = days_held(p, today)
            strat = strategy_of(p)
            e = dict(p)
            e.update({
                "strategy_label": strat.get("label", p.get("strategy", "")),
                "strategy_short": strat.get("short", ""),
                "strategy_tier": strat.get("tier", ""),
                "exit_rule": _exit_rule_label(strat),
                "current_price": round(px, 2),
                "value": round(val, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_pct": round(pnl / p["cost_basis"] * 100, 2) if p["cost_basis"] else 0,
                "days_held": held,
                "days_remaining": (max(0, p["hold_days"] - held)
                                   if p["sleeve"] == "ALPHA" and p["hold_days"] < 99_999 else None),
                "price_stale": p["ticker"] not in prices,
            })
            enriched.append(e)
            if p["sleeve"] == "CORE":
                core_val += val
            else:
                alpha_val += val
        equity = cash + core_val + alpha_val
        for e in enriched:
            e["weight_pct"] = round(e["value"] / equity * 100, 2) if equity else 0
        return {"cash": round(cash, 2), "core_value": round(core_val, 2),
                "alpha_value": round(alpha_val, 2),
                "positions_value": round(core_val + alpha_val, 2),
                "equity": round(equity, 2), "positions": enriched}
    finally:
        if own:
            conn.close()


def _exit_rule_label(strat: Dict) -> str:
    ex = strat.get("exit") or {}
    t = ex.get("type")
    if t == "timer":
        return f"Fixed{ex['days']}d timer"
    if t == "rsi":
        return f"RSI(2)>{ex['rsi_above']} or {ex['max_days']}d cap"
    if t == "monthly_rank":
        return "Monthly rank rebalance"
    if t == "rebalance":
        return "Passive · band rebalance"
    return "—"


def _inception() -> Optional[str]:
    conn = _connect()
    try:
        r = conn.execute("SELECT value FROM sim_meta WHERE key='inception'").fetchone()
        return r["value"] if r else None
    finally:
        conn.close()


def snapshot_equity(prices: Dict[str, float], regime_name: str = "") -> Dict:
    """Write/refresh today's equity row, including the QQQ buy-and-hold benchmark."""
    _ensure()
    book = value_book(prices)
    cfg = get_config()
    bench_px = float(prices.get(BENCH_TICKER) or 0)
    bench_equity = 0.0
    if bench_px > 0:
        conn = _connect()
        try:
            r = conn.execute("SELECT value FROM sim_meta WHERE key='bench_shares'").fetchone()
            if r:
                bench_shares = float(r["value"])
            else:
                bench_shares = float(cfg["starting_capital"]) / bench_px
                conn.execute(
                    "INSERT OR REPLACE INTO sim_meta (key,value) VALUES ('bench_shares',?)",
                    (str(bench_shares),),
                )
                conn.commit()
            bench_equity = bench_shares * bench_px
        finally:
            conn.close()

    now = datetime.now()
    conn = _connect()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO sim_equity
               (date, ts, cash, positions_value, equity, core_value, alpha_value,
                open_positions, bench_price, bench_equity, regime)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (now.strftime("%Y-%m-%d"), now.isoformat(), book["cash"],
             book["positions_value"], book["equity"], book["core_value"],
             book["alpha_value"], len(book["positions"]), round(bench_px, 2),
             round(bench_equity, 2), regime_name),
        )
        conn.commit()
    finally:
        conn.close()
    return book


# ──────────────────────────────────────────────────────────────────────────
# Candidate gating
# ──────────────────────────────────────────────────────────────────────────

def _is_validated(sig: Dict) -> bool:
    """Same gate the Entries tab applies: Phase-3 enrichment must have landed.

    Raw /scan/combined rows include technically-oversold names with no analyst
    or sentiment data attached. Those are not tradable candidates.
    """
    return bool((sig.get("analyst_consensus") or "").strip()
                or (sig.get("sentiment_label") or "").strip())


def _entry_veto(sig: Dict, cfg: Dict) -> str:
    """Production VETO chain. Returns a reason string, or '' to allow."""
    px = float(sig.get("price") or 0)
    if px < 10:
        return "Price < $10 (penny filter)"
    atr = float(sig.get("atr_pct") or 0)
    if atr >= 15:
        return f"ATR {atr:.1f}% >= 15% (29% WR / -12.6% cohort)"
    consensus = (sig.get("analyst_consensus") or "").strip()
    if consensus in ("Hold", "Sell", "Strong Sell", "Underperform"):
        return f"Analyst consensus {consensus}"
    if int(sig.get("trades") or 0) < 10:
        return f"Only {sig.get('trades', 0)} backtest trades (< 10)"
    if float(sig.get("composite_score") or 0) < float(cfg["min_composite"]):
        return f"Composite {sig.get('composite_score', 0):.0f} < {cfg['min_composite']:.0f}"
    if sig.get("vetoed"):
        return sig.get("veto_reason") or "Vetoed upstream"
    return ""


def _matches_source(sig: Dict, strategy_id: str) -> Tuple[bool, str]:
    """Does this signal belong to this strategy's candidate pool?"""
    strat = STRATEGIES[strategy_id]
    src = strat["source"]
    sig_strat = sig.get("strategy", "")
    if src == "MR":
        if sig_strat not in ("MEAN_REVERSION", "BOTH"):
            return False, "not a mean-reversion signal"
        cap = strat.get("entry_max_rsi2")
        if cap is not None:
            rsi2 = sig.get("rsi2")
            if rsi2 is None or float(rsi2) > cap:
                return False, (f"RSI(2) {float(rsi2 or 0):.0f} > {cap} — the dip already "
                               f"bounced, no swing left to catch")
        return True, ""
    if src == "MOM":
        if sig_strat not in ("MOMENTUM", "BOTH"):
            return False, "not a momentum signal"
        return True, ""
    if src == "BREAKOUT":
        if sig_strat not in ("MOMENTUM", "BOTH"):
            return False, "not a momentum signal"
        dist = sig.get("high52_dist")
        cap = strat.get("max_high52_dist", 5.0)
        if dist is None:
            return False, "no 52-week high data"
        if float(dist) > cap:
            return False, f"{float(dist):.1f}% below the 52w high (needs <= {cap:.0f}%)"
        return True, ""
    return False, "no signal source"


# ──────────────────────────────────────────────────────────────────────────
# Exits
# ──────────────────────────────────────────────────────────────────────────

def _exit_check(pos: Dict, *, today: str, earnings: Dict, sentiment: Dict,
                technicals: Dict, rotation_target: Optional[List[str]]) -> Tuple[bool, str]:
    """Per-strategy exit rule plus the two universal exits.

    No stops, no profit targets — every stop variant tested lost to holding the
    strategy's own exit rule (project_zone_calibration_2026-07).
    """
    ticker = pos["ticker"]
    held = days_held(pos, today)

    # Universal exit 1: binary event risk
    e = (earnings or {}).get(ticker) or {}
    dt = e.get("days_to")
    if dt is not None and 0 <= dt <= 7:
        return True, f"Earnings in {dt}d — binary event risk"

    # Universal exit 2: stock-specific bad news (NOT market-wide noise)
    s = (sentiment or {}).get(ticker) or {}
    label = (s.get("sentiment_label") or "").upper()
    if label in ("NEGATIVE", "VERY_NEGATIVE") and float(s.get("sentiment_score") or 0) < -0.3:
        return True, f"Stock-specific negative sentiment ({label})"

    strat = strategy_of(pos)
    rule = strat.get("exit") or {"type": "timer", "days": pos["hold_days"]}
    kind = rule.get("type")

    if kind == "timer":
        days = rule.get("days", pos["hold_days"])
        if held >= days:
            return True, f"Timer: day {held}/{days} (Fixed{days}d)"
        return False, f"Hold — day {held}/{days}"

    if kind == "rsi":
        rsi2 = (technicals or {}).get(ticker, {}).get("rsi2")
        cap = rule.get("max_days", 21)
        if rsi2 is not None and float(rsi2) >= rule.get("rsi_above", 75):
            return True, f"RSI(2) {float(rsi2):.0f} >= {rule['rsi_above']} — bounce captured"
        if held >= cap:
            return True, f"Swing cap: day {held}/{cap} without an RSI exit"
        rsi_txt = f"RSI(2) {float(rsi2):.0f}" if rsi2 is not None else "RSI unavailable"
        return False, f"Hold — {rsi_txt}, day {held}/{cap}"

    if kind == "monthly_rank":
        if rotation_target is None:
            return False, f"Hold — day {held}, awaiting monthly ranking"
        if ticker not in rotation_target:
            return True, "Dropped out of the monthly 12-1 momentum top ranks"
        return False, f"Hold — still ranked, day {held}"

    return False, f"Hold — day {held}"


# ──────────────────────────────────────────────────────────────────────────
# The decision cycle
# ──────────────────────────────────────────────────────────────────────────

def run_cycle(*, regime: Dict, signals: List[Dict], prices: Dict[str, float],
              earnings: Optional[Dict] = None, sentiment: Optional[Dict] = None,
              technicals: Optional[Dict] = None, sectors: Optional[Dict] = None,
              rotation_ranks: Optional[List[str]] = None,
              session: str = "REGULAR", force_entries: bool = False,
              dry_run: bool = False) -> Dict:
    """One decision cycle: exits → core rebalance → entries → optional rotation."""
    _ensure()
    cfg = get_config()
    cycle_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    today = datetime.now().strftime("%Y-%m-%d")
    regime_name = regime.get("regime", "UNKNOWN")
    actions = {"exits": [], "entries": [], "rebalance": [], "switches": []}

    enabled = {k for k, v in (cfg.get("strategy_enabled") or {}).items() if v}
    rot_target = None
    if "MOM_ROT_12_1" in enabled and rotation_ranks:
        rot_target = rotation_ranks[: int(cfg["strategy_slots"].get("MOM_ROT_12_1", 4))]

    tradable = session == "REGULAR" or force_entries
    conn = _connect()
    try:
        _log(conn, cycle_id, "CYCLE", reason=f"session={session} regime={regime_name}",
             regime=regime_name,
             detail={"session": session, "signals_in": len(signals),
                     "strategies_on": sorted(enabled),
                     "pause_entries": regime.get("pause_entries"),
                     "size_pct": regime.get("position_size_pct"),
                     "rotation_enabled": bool(cfg.get("rotation_enabled")),
                     "dry_run": dry_run, "tradable": tradable})

        # ── 1. EXITS ──────────────────────────────────────────────────────
        for pos in get_open_positions(conn):
            if pos["sleeve"] == "CORE":
                continue                       # core is rebalanced, never timed out
            should, reason = _exit_check(
                pos, today=today, earnings=earnings or {}, sentiment=sentiment or {},
                technicals=technicals or {}, rotation_target=rot_target)
            px = float(prices.get(pos["ticker"]) or 0)
            if not should:
                _log(conn, cycle_id, "HOLD", ticker=pos["ticker"], reason=reason,
                     regime=regime_name, strategy=pos.get("strategy", ""),
                     detail={"days_held": days_held(pos, today)})
                continue
            if px <= 0:
                _log(conn, cycle_id, "SKIP", ticker=pos["ticker"], action="SELL",
                     strategy=pos.get("strategy", ""),
                     reason=f"{reason} — but no live price; will retry next cycle",
                     regime=regime_name)
                continue
            if not tradable:
                _log(conn, cycle_id, "SKIP", ticker=pos["ticker"], action="SELL",
                     strategy=pos.get("strategy", ""),
                     reason=f"{reason} — market {session}, execute at next open",
                     regime=regime_name)
                continue
            if dry_run:
                actions["exits"].append({"ticker": pos["ticker"], "reason": reason,
                                         "dry_run": True})
                continue
            res = close_position(conn, pos, px, reason, cfg)
            if res:
                actions["exits"].append(res)
                _log(conn, cycle_id, "EXIT", ticker=pos["ticker"], action="SELL",
                     reason=reason, regime=regime_name,
                     strategy=pos.get("strategy", ""), detail=res)

        # ── 2. CORE SLEEVE ────────────────────────────────────────────────
        # Rebalanced at most once a day, and only outside the drift band.
        if (tradable and not dry_run and "CORE_QQQ" in enabled
                and float(cfg["core_target_pct"]) > 0):
            already = conn.execute(
                """SELECT COUNT(*) c FROM sim_decisions
                   WHERE kind='REBALANCE' AND action IN ('BUY','SELL') AND ts >= ?""",
                (today,),
            ).fetchone()["c"]
            if already == 0:
                _rebalance_core(conn, cycle_id, cfg, prices, regime_name, actions)

        # ── 3. ENTRIES ────────────────────────────────────────────────────
        if regime.get("pause_entries"):
            _log(conn, cycle_id, "PAUSE", reason=f"Regime {regime_name}: "
                 f"{regime.get('reason', 'entries paused')}", regime=regime_name)
        elif not tradable:
            _log(conn, cycle_id, "PAUSE", reason=f"Market {session} — no entry fills",
                 regime=regime_name)
        else:
            _run_entries(conn, cycle_id, cfg, regime, signals, prices, sectors or {},
                         enabled, rot_target, actions, dry_run)
            if cfg.get("rotation_enabled") and not dry_run:
                _run_rotation(conn, cycle_id, cfg, regime, signals, prices,
                              enabled, actions)

        if not dry_run:
            conn.commit()
    finally:
        conn.close()

    book = snapshot_equity(prices, regime_name) if not dry_run else value_book(prices)
    return {"cycle_id": cycle_id, "ts": datetime.now().isoformat(),
            "session": session, "regime": regime_name, "dry_run": dry_run,
            "actions": actions, "equity": book["equity"], "cash": book["cash"],
            "open_positions": len(book["positions"])}


def _rebalance_core(conn, cycle_id: str, cfg: Dict, prices: Dict[str, float],
                    regime_name: str, actions: Dict) -> None:
    ticker = cfg["core_ticker"]
    px = float(prices.get(ticker) or 0)
    if px <= 0:
        _log(conn, cycle_id, "SKIP", ticker=ticker, strategy="CORE_QQQ",
             reason="No live price for core sleeve", regime=regime_name)
        return
    book = value_book(prices, conn)
    equity = book["equity"]
    if equity <= 0:
        return
    target_val = equity * float(cfg["core_target_pct"]) / 100.0
    core_positions = [p for p in book["positions"] if p["sleeve"] == "CORE"]
    current_val = sum(p["value"] for p in core_positions)
    drift_pct = (current_val - target_val) / equity * 100.0
    band = float(cfg["core_band_pct"])

    if abs(drift_pct) <= band:
        _log(conn, cycle_id, "REBALANCE", ticker=ticker, action="NONE", strategy="CORE_QQQ",
             reason=f"Core {current_val / equity * 100:.1f}% vs target "
                    f"{cfg['core_target_pct']:.0f}% — inside ±{band:.0f}pp band",
             regime=regime_name,
             detail={"current_pct": round(current_val / equity * 100, 2),
                     "target_pct": cfg["core_target_pct"], "drift_pp": round(drift_pct, 2)})
        return

    if drift_pct < 0:
        need = target_val - current_val
        cash_avail = book["cash"] - float(cfg.get("cash_floor_usd", 0))
        buy_usd = min(need, cash_avail)
        if buy_usd < float(cfg["min_position_usd"]):
            _log(conn, cycle_id, "REBALANCE", ticker=ticker, action="NONE",
                 strategy="CORE_QQQ",
                 reason=f"Core underweight {drift_pct:+.1f}pp but only "
                        f"${max(0, buy_usd):,.0f} deployable", regime=regime_name)
            return
        res = open_position(conn, ticker=ticker, strategy_id="CORE_QQQ", price=px,
                            dollars=buy_usd, cfg=cfg,
                            rationale={"summary": f"Core sleeve top-up to "
                                                  f"{cfg['core_target_pct']:.0f}% target",
                                       "drift_pp": round(drift_pct, 2)})
        if res:
            actions["rebalance"].append(res)
            _log(conn, cycle_id, "REBALANCE", ticker=ticker, action="BUY",
                 strategy="CORE_QQQ",
                 reason=f"Core {drift_pct:+.1f}pp underweight → buy ${buy_usd:,.0f}",
                 regime=regime_name, detail=res)
    else:
        excess = current_val - target_val
        for p in sorted(core_positions, key=lambda x: x["entry_ts"], reverse=True):
            if excess <= 0:
                break
            sell_usd = min(excess, p["value"])
            res = close_position(conn, p, px, "Core sleeve trim to target", cfg,
                                 shares=sell_usd / px)
            if res:
                actions["rebalance"].append(res)
                excess -= sell_usd
                _log(conn, cycle_id, "REBALANCE", ticker=ticker, action="SELL",
                     strategy="CORE_QQQ",
                     reason=f"Core {drift_pct:+.1f}pp overweight → trim ${sell_usd:,.0f}",
                     regime=regime_name, detail=res)


def _sector_normalizer(sectors: Dict):
    """'' = unclassified. SectorStore returns the literal 'Unknown' for names it
    hasn't backfilled yet; bucketing those together would let one unknown name
    block every other unclassified candidate via the sector cap."""
    def _of(t: str) -> str:
        s = (sectors.get(t) or "").strip()
        return "" if s.upper() in ("", "UNKNOWN", "N/A", "NONE") else s
    return _of


def slot_size_usd(cfg: Dict, equity: float, enabled: set, size_mult: float) -> float:
    """Alpha capital spread across every enabled slot, regime-scaled and capped."""
    total_slots = sum(int(cfg["strategy_slots"].get(s, 0))
                      for s in enabled if STRATEGIES[s]["kind"] == "ALPHA")
    if total_slots <= 0:
        return 0.0
    core_pct = float(cfg["core_target_pct"]) if "CORE_QQQ" in enabled else 0.0
    alpha_target = equity * (100.0 - core_pct) / 100.0
    size = (alpha_target / total_slots) * size_mult
    return min(size, equity * float(cfg["max_position_pct"]) / 100.0)


def _run_entries(conn, cycle_id: str, cfg: Dict, regime: Dict, signals: List[Dict],
                 prices: Dict[str, float], sectors: Dict, enabled: set,
                 rot_target: Optional[List[str]], actions: Dict, dry_run: bool) -> None:
    regime_name = regime.get("regime", "UNKNOWN")
    size_mult = float(regime.get("position_size_pct", 100)) / 100.0
    sector_of = _sector_normalizer(sectors)

    book = value_book(prices, conn)
    equity = book["equity"]
    held = {p["ticker"] for p in book["positions"]}
    open_by_strat: Dict[str, int] = {}
    sector_counts: Dict[str, int] = {}
    for p in book["positions"]:
        if p["sleeve"] != "ALPHA":
            continue
        open_by_strat[p["strategy"]] = open_by_strat.get(p["strategy"], 0) + 1
        s = sector_of(p["ticker"])
        if s:
            sector_counts[s] = sector_counts.get(s, 0) + 1

    slot_usd = slot_size_usd(cfg, equity, enabled, size_mult)
    if slot_usd < float(cfg["min_position_usd"]):
        _log(conn, cycle_id, "SKIP", regime=regime_name,
             reason=f"Slot size ${slot_usd:,.0f} below the ${cfg['min_position_usd']:,.0f} "
                    f"minimum — reduce slot counts or the core target to size up")
        return

    # Ranked once; each strategy takes from the same list in registry order so
    # the validated sleeves get first pick of a shared candidate.
    ranked = sorted(signals, key=lambda s: float(s.get("composite_score") or 0), reverse=True)

    for sid in ALPHA_STRATEGIES:
        if sid not in enabled:
            continue
        strat = STRATEGIES[sid]
        slots = int(cfg["strategy_slots"].get(sid, 0)) - open_by_strat.get(sid, 0)
        if slots <= 0:
            continue

        if strat["source"] == "ROTATION":
            _run_rotation_sleeve(conn, cycle_id, cfg, regime_name, sid, rot_target,
                                 prices, held, slot_usd, actions, dry_run)
            continue

        opened = 0
        for sig in ranked:
            if opened >= slots:
                break
            ticker = sig.get("ticker", "")
            if not ticker or ticker in held:
                continue
            composite = float(sig.get("composite_score") or 0)

            ok, why = _matches_source(sig, sid)
            if not ok:
                # Only journal near-misses — a mean-reversion signal isn't a
                # "skip" for the breakout sleeve, it's just a different pool.
                if why not in ("not a momentum signal", "not a mean-reversion signal"):
                    _log(conn, cycle_id, "SKIP", ticker=ticker, composite=composite,
                         strategy=sid, reason=f"Not eligible: {why}", regime=regime_name)
                continue
            if not _is_validated(sig):
                _log(conn, cycle_id, "SKIP", ticker=ticker, composite=composite,
                     strategy=sid, reason="Not Phase-3 validated (no analyst/sentiment data)",
                     regime=regime_name)
                continue
            veto = _entry_veto(sig, cfg)
            if veto:
                _log(conn, cycle_id, "SKIP", ticker=ticker, composite=composite,
                     strategy=sid, reason=f"VETO: {veto}", regime=regime_name,
                     detail={"price": sig.get("price")})
                continue
            sector = sector_of(ticker)
            if sector and sector_counts.get(sector, 0) >= int(cfg["max_per_sector"]):
                _log(conn, cycle_id, "SKIP", ticker=ticker, composite=composite,
                     strategy=sid, reason=f"Sector cap: already {sector_counts[sector]} "
                     f"in {sector}", regime=regime_name)
                continue

            px = float(prices.get(ticker) or sig.get("price") or 0)
            if px <= 0:
                continue
            cash_avail = get_cash(conn) - float(cfg.get("cash_floor_usd", 0))
            size = min(slot_usd, cash_avail)
            if size < float(cfg["min_position_usd"]):
                _log(conn, cycle_id, "SKIP", ticker=ticker, composite=composite,
                     strategy=sid,
                     reason=f"Insufficient cash (${max(0, cash_avail):,.0f} free)",
                     regime=regime_name)
                break

            rationale = _build_rationale(sig, sid, composite, regime, sector)
            if dry_run:
                actions["entries"].append({"ticker": ticker, "strategy": sid,
                                           "size": round(size, 2), "composite": composite,
                                           "dry_run": True})
                opened += 1
                continue
            res = open_position(conn, ticker=ticker, strategy_id=sid, price=px,
                                dollars=size, cfg=cfg, rationale=rationale,
                                composite=composite)
            if not res:
                continue
            opened += 1
            held.add(ticker)
            open_by_strat[sid] = open_by_strat.get(sid, 0) + 1
            if sector:
                sector_counts[sector] = sector_counts.get(sector, 0) + 1
            actions["entries"].append(res)
            _log(conn, cycle_id, "ENTRY", ticker=ticker, action="BUY", composite=composite,
                 strategy=sid, reason=rationale["summary"], regime=regime_name,
                 detail={**res, **rationale})

        if opened == 0 and slots > 0:
            _log(conn, cycle_id, "SKIP", strategy=sid, regime=regime_name,
                 reason=f"{strat['label']}: {slots} slot(s) open, no candidate cleared "
                        f"the gate ({len(ranked)} signals reviewed)")


def _build_rationale(sig: Dict, sid: str, composite: float, regime: Dict,
                     sector: str) -> Dict:
    strat = STRATEGIES[sid]
    return {
        "summary": f"{strat['label']} — composite {composite:.0f} "
                   f"({sig.get('quality_tier', '')})",
        "strategy": sid,
        "strategy_label": strat["label"],
        "evidence_tier": strat["tier"],
        "signal_strategy": sig.get("strategy"),
        "regime": regime.get("regime"),
        "regime_size_pct": regime.get("position_size_pct"),
        "composite_score": composite,
        "quality_tier": sig.get("quality_tier"),
        "ranking_factors": sig.get("ranking_factors"),
        "rsi2": sig.get("rsi2"), "atr_pct": sig.get("atr_pct"),
        "sma50_buffer": sig.get("sma50_buffer"), "ret_20d": sig.get("ret_20d"),
        "high52_dist": sig.get("high52_dist"),
        "volume_ratio": sig.get("volume_ratio"),
        "backtest_wr": sig.get("confidence"), "backtest_trades": sig.get("trades"),
        "expected_return": sig.get("expected_return"),
        "analyst_consensus": sig.get("analyst_consensus"),
        "sentiment_label": sig.get("sentiment_label"),
        "exit_plan": _exit_rule_label(strat),
        "sector": sector or "unclassified",
    }


def _run_rotation_sleeve(conn, cycle_id: str, cfg: Dict, regime_name: str, sid: str,
                         rot_target: Optional[List[str]], prices: Dict[str, float],
                         held: set, slot_usd: float, actions: Dict,
                         dry_run: bool) -> None:
    """Monthly 12-1 momentum sleeve: buy into whatever the ranking says is missing.
    Exits are handled by the `monthly_rank` exit rule in the exit pass."""
    if not rot_target:
        _log(conn, cycle_id, "SKIP", strategy=sid, regime=regime_name,
             reason="No 12-1 momentum ranking available this cycle")
        return
    for ticker in rot_target:
        if ticker in held:
            continue
        px = float(prices.get(ticker) or 0)
        if px <= 0:
            continue
        cash_avail = get_cash(conn) - float(cfg.get("cash_floor_usd", 0))
        size = min(slot_usd, cash_avail)
        if size < float(cfg["min_position_usd"]):
            _log(conn, cycle_id, "SKIP", ticker=ticker, strategy=sid, regime=regime_name,
                 reason=f"Insufficient cash (${max(0, cash_avail):,.0f} free)")
            return
        rationale = {
            "summary": f"{STRATEGIES[sid]['label']} — in the monthly top ranks",
            "strategy": sid, "strategy_label": STRATEGIES[sid]["label"],
            "evidence_tier": STRATEGIES[sid]["tier"],
            "rank": rot_target.index(ticker) + 1,
            "exit_plan": "Held until it drops out of the monthly ranking",
        }
        if dry_run:
            actions["entries"].append({"ticker": ticker, "strategy": sid,
                                       "size": round(size, 2), "dry_run": True})
            continue
        res = open_position(conn, ticker=ticker, strategy_id=sid, price=px,
                            dollars=size, cfg=cfg, rationale=rationale)
        if res:
            held.add(ticker)
            actions["entries"].append(res)
            _log(conn, cycle_id, "ENTRY", ticker=ticker, action="BUY", strategy=sid,
                 reason=rationale["summary"], regime=regime_name,
                 detail={**res, **rationale})


def _run_rotation(conn, cycle_id: str, cfg: Dict, regime: Dict, signals: List[Dict],
                  prices: Dict[str, float], enabled: set, actions: Dict) -> None:
    """Switch a held position for a materially better candidate.

    OFF by default. Our own point-in-time test of exactly this logic (gap>15)
    came in 13-24 CAGR points BELOW simply holding to the timer, because the
    positions it rotates out of are mid-dip — which is the trade working, not
    failing. Kept available and fully journalled so the cost is measurable
    rather than assumed.
    """
    regime_name = regime.get("regime", "UNKNOWN")
    gap = float(cfg["rotation_min_gap"])
    min_days = int(cfg["rotation_min_days"])
    today = datetime.now().strftime("%Y-%m-%d")

    book = value_book(prices, conn)
    alpha = [p for p in book["positions"] if p["sleeve"] == "ALPHA"
             and STRATEGIES.get(p["strategy"], {}).get("source") in ("MR", "MOM", "BREAKOUT")]
    if not alpha:
        return
    held = {p["ticker"] for p in book["positions"]}
    ranked = [s for s in sorted(signals, key=lambda s: float(s.get("composite_score") or 0),
                                reverse=True)
              if s.get("ticker") not in held and _is_validated(s)
              and not _entry_veto(s, cfg)]
    if not ranked:
        return

    weakest = min(alpha, key=lambda p: p["entry_composite"])
    if days_held(weakest, today) < min_days:
        return
    best = ranked[0]
    cand_score = float(best.get("composite_score") or 0)
    edge = cand_score - float(weakest["entry_composite"] or 0)
    if edge < gap:
        _log(conn, cycle_id, "SWITCH", action="NONE", regime=regime_name,
             strategy=weakest["strategy"],
             reason=f"No switch: best candidate {best['ticker']} ({cand_score:.0f}) beats "
                    f"weakest holding {weakest['ticker']} ({weakest['entry_composite']:.0f}) "
                    f"by {edge:.0f} < {gap:.0f} required")
        return

    sell_px = float(prices.get(weakest["ticker"]) or 0)
    buy_px = float(prices.get(best["ticker"]) or best.get("price") or 0)
    if sell_px <= 0 or buy_px <= 0:
        return
    reason = (f"Rotate into {best['ticker']} (composite {cand_score:.0f} vs "
              f"{weakest['entry_composite']:.0f}, +{edge:.0f})")
    sold = close_position(conn, weakest, sell_px, reason, cfg)
    if not sold:
        return
    actions["switches"].append(sold)
    _log(conn, cycle_id, "SWITCH", ticker=weakest["ticker"], action="SELL",
         strategy=weakest["strategy"], reason=reason, regime=regime_name,
         composite=weakest["entry_composite"], detail=sold)

    sid = weakest["strategy"] if weakest["strategy"] in enabled else "MR_FIXED42"
    ok, _ = _matches_source(best, sid)
    if not ok:
        sid = "MR_FIXED42"
    rationale = _build_rationale(best, sid, cand_score, regime, "")
    rationale["summary"] = f"Rotation buy — replaced {weakest['ticker']}"
    bought = open_position(conn, ticker=best["ticker"], strategy_id=sid, price=buy_px,
                           dollars=sold["proceeds"], cfg=cfg, rationale=rationale,
                           composite=cand_score)
    if bought:
        actions["switches"].append(bought)
        _log(conn, cycle_id, "SWITCH", ticker=best["ticker"], action="BUY", strategy=sid,
             reason=rationale["summary"], regime=regime_name, composite=cand_score,
             detail={**bought, **rationale})


# ──────────────────────────────────────────────────────────────────────────
# Manual (discretionary) actions — tagged MANUAL so they never blend into the
# model's track record.
# ──────────────────────────────────────────────────────────────────────────

def manual_buy(*, ticker: str, strategy_id: str, dollars: float, price: float,
               note: str = "", signal: Optional[Dict] = None) -> Dict:
    _ensure()
    if strategy_id not in STRATEGIES:
        return {"ok": False, "error": f"Unknown strategy '{strategy_id}'"}
    cfg = get_config()
    ticker = ticker.upper().strip()
    conn = _connect()
    try:
        if any(p["ticker"] == ticker for p in get_open_positions(conn)):
            return {"ok": False, "error": f"{ticker} is already held"}
        composite = float((signal or {}).get("composite_score") or 0)
        rationale = (_build_rationale(signal, strategy_id, composite,
                                      {"regime": "MANUAL"}, "")
                     if signal else
                     {"summary": f"Manual buy — {STRATEGIES[strategy_id]['label']}",
                      "strategy": strategy_id,
                      "exit_plan": _exit_rule_label(STRATEGIES[strategy_id])})
        rationale["summary"] = f"MANUAL buy · {STRATEGIES[strategy_id]['label']}"
        rationale["note"] = note
        res = open_position(conn, ticker=ticker, strategy_id=strategy_id, price=price,
                            dollars=dollars, cfg=cfg, rationale=rationale,
                            composite=composite, origin="MANUAL")
        if not res:
            return {"ok": False, "error": "Insufficient cash or invalid size"}
        _log(conn, datetime.now().strftime("%Y%m%d-%H%M%S"), "MANUAL", ticker=ticker,
             action="BUY", strategy=strategy_id, origin="MANUAL", composite=composite,
             reason=note or rationale["summary"], detail={**res, **rationale})
        conn.commit()
        return {"ok": True, "position": res}
    finally:
        conn.close()


def manual_close(*, position_id: int, price: float, note: str = "") -> Dict:
    _ensure()
    cfg = get_config()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sim_positions WHERE id=? AND status='OPEN'", (position_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "No open position with that id"}
        pos = dict(row)
        reason = note or "Manual close"
        res = close_position(conn, pos, price, f"MANUAL: {reason}", cfg, origin="MANUAL")
        if not res:
            return {"ok": False, "error": "Close failed"}
        _log(conn, datetime.now().strftime("%Y%m%d-%H%M%S"), "MANUAL",
             ticker=pos["ticker"], action="SELL", strategy=pos.get("strategy", ""),
             origin="MANUAL", reason=reason,
             detail={**res, "days_held": days_held(pos), "hold_days": pos["hold_days"],
                     "cut_short_by": max(0, pos["hold_days"] - days_held(pos))})
        conn.commit()
        return {"ok": True, "closed": res}
    finally:
        conn.close()


def manual_switch(*, position_id: int, buy_ticker: str, sell_price: float,
                  buy_price: float, strategy_id: Optional[str] = None,
                  note: str = "", signal: Optional[Dict] = None) -> Dict:
    """Atomic sell-one/buy-one. Proceeds from the sale fund the purchase."""
    _ensure()
    cfg = get_config()
    buy_ticker = buy_ticker.upper().strip()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM sim_positions WHERE id=? AND status='OPEN'", (position_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "No open position with that id"}
        pos = dict(row)
        if any(p["ticker"] == buy_ticker for p in get_open_positions(conn)):
            return {"ok": False, "error": f"{buy_ticker} is already held"}
        sid = strategy_id or pos.get("strategy") or "MR_FIXED42"
        if sid not in STRATEGIES:
            return {"ok": False, "error": f"Unknown strategy '{sid}'"}

        reason = note or f"Manual switch {pos['ticker']} → {buy_ticker}"
        sold = close_position(conn, pos, sell_price, f"MANUAL: {reason}", cfg,
                              origin="MANUAL")
        if not sold:
            return {"ok": False, "error": "Sell leg failed"}
        composite = float((signal or {}).get("composite_score") or 0)
        rationale = (_build_rationale(signal, sid, composite, {"regime": "MANUAL"}, "")
                     if signal else
                     {"summary": reason, "strategy": sid,
                      "exit_plan": _exit_rule_label(STRATEGIES[sid])})
        rationale["summary"] = f"MANUAL switch from {pos['ticker']}"
        rationale["note"] = note
        bought = open_position(conn, ticker=buy_ticker, strategy_id=sid, price=buy_price,
                               dollars=sold["proceeds"], cfg=cfg, rationale=rationale,
                               composite=composite, origin="MANUAL")
        cid = datetime.now().strftime("%Y%m%d-%H%M%S")
        _log(conn, cid, "MANUAL", ticker=pos["ticker"], action="SELL",
             strategy=pos.get("strategy", ""), origin="MANUAL", reason=reason,
             detail={**sold, "days_held": days_held(pos), "hold_days": pos["hold_days"],
                     "cut_short_by": max(0, pos["hold_days"] - days_held(pos))})
        if bought:
            _log(conn, cid, "MANUAL", ticker=buy_ticker, action="BUY", strategy=sid,
                 origin="MANUAL", composite=composite, reason=rationale["summary"],
                 detail={**bought, **rationale})
        conn.commit()
        return {"ok": True, "sold": sold, "bought": bought,
                "warning": None if bought else "Sell executed but buy leg failed — "
                                               "proceeds are sitting in cash"}
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────────────────

def _trade_stats(rows: List[Dict]) -> Dict:
    wins = [c for c in rows if (c["realized_pnl"] or 0) > 0]
    losses = [c for c in rows if (c["realized_pnl"] or 0) <= 0]
    gross_win = sum(c["realized_pnl"] for c in wins) or 0.0
    gross_loss = abs(sum(c["realized_pnl"] for c in losses)) or 0.0
    rets = [(c["realized_pnl"] / c["cost_basis"] * 100) for c in rows if c["cost_basis"]]
    return {
        "closed_trades": len(rows),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(rows) * 100, 1) if rows else 0.0,
        "avg_return_pct": round(sum(rets) / len(rets), 2) if rets else 0.0,
        "best_trade_pct": round(max(rets), 2) if rets else 0.0,
        "worst_trade_pct": round(min(rets), 2) if rets else 0.0,
        "realized_pnl": round(sum(c["realized_pnl"] or 0 for c in rows), 2),
        # None = undefined (no losing trades yet), not "zero profit factor"
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
    }


def get_stats() -> Dict:
    """Realized track record: overall, per strategy, and model vs manual."""
    _ensure()
    conn = _connect()
    try:
        closed = [dict(r) for r in conn.execute(
            """SELECT ticker, strategy, origin, realized_pnl, cost_basis, exit_reason,
                      entry_date, exit_date
               FROM sim_positions WHERE status='CLOSED' AND sleeve='ALPHA'""")]
        curve = conn.execute("SELECT * FROM sim_equity ORDER BY date").fetchall()
    finally:
        conn.close()

    max_dd = 0.0
    peak = 0.0
    for r in curve:
        eq = r["equity"] or 0
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, (eq - peak) / peak * 100)

    out = _trade_stats(closed)
    out["max_drawdown_pct"] = round(max_dd, 2)
    out["snapshots"] = len(curve)
    out["by_strategy"] = {
        sid: _trade_stats([c for c in closed if c["strategy"] == sid])
        for sid in {c["strategy"] for c in closed}
    }
    out["by_origin"] = {
        o: _trade_stats([c for c in closed if (c.get("origin") or "MODEL") == o])
        for o in {(c.get("origin") or "MODEL") for c in closed}
    }
    return out


def get_strategy_book(prices: Optional[Dict[str, float]] = None) -> List[Dict]:
    """Per-strategy view: config, live exposure, and realized record."""
    _ensure()
    cfg = get_config()
    book = value_book(prices or {})
    stats = get_stats()
    equity = book["equity"] or 1
    out = []
    for sid, meta in STRATEGIES.items():
        pos = [p for p in book["positions"] if p["strategy"] == sid]
        val = sum(p["value"] for p in pos)
        out.append({
            "id": sid,
            "label": meta["label"],
            "short": meta["short"],
            "tier": meta["tier"],
            "kind": meta["kind"],
            "source": meta["source"],
            "exit_rule": _exit_rule_label(meta),
            "thesis": meta["thesis"],
            "evidence": meta["evidence"],
            "enabled": bool(cfg["strategy_enabled"].get(sid)),
            "slots": int(cfg["strategy_slots"].get(sid, 0)),
            "open_positions": len(pos),
            "value": round(val, 2),
            "weight_pct": round(val / equity * 100, 2),
            "unrealized_pnl": round(sum(p["unrealized_pnl"] for p in pos), 2),
            "target_pct": (float(cfg["core_target_pct"]) if meta["kind"] == "CORE" else None),
            "stats": stats["by_strategy"].get(sid, _trade_stats([])),
        })
    return out


def get_state(prices: Optional[Dict[str, float]] = None,
              regime: Optional[Dict] = None) -> Dict:
    """Everything the Sim tab needs in one payload."""
    _ensure()
    cfg = get_config()
    book = value_book(prices or {})
    start = float(cfg["starting_capital"])
    equity = book["equity"]
    curve = get_equity_curve()
    bench_equity = 0.0
    for row in reversed(curve):
        if row.get("bench_equity"):
            bench_equity = row["bench_equity"]
            break

    inception = _inception()
    days_live = 0
    if inception:
        try:
            days_live = (datetime.now() - datetime.fromisoformat(inception)).days
        except Exception:
            days_live = 0

    roi = (equity - start) / start * 100 if start else 0.0
    bench_roi = (bench_equity - start) / start * 100 if (start and bench_equity) else 0.0

    return {
        "timestamp": datetime.now().isoformat(),
        "inception": inception,
        "days_live": days_live,
        "starting_capital": start,
        "equity": round(equity, 2),
        "cash": book["cash"],
        "positions_value": book["positions_value"],
        "core_value": book["core_value"],
        "alpha_value": book["alpha_value"],
        "core_pct": round(book["core_value"] / equity * 100, 2) if equity else 0,
        "alpha_pct": round(book["alpha_value"] / equity * 100, 2) if equity else 0,
        "cash_pct": round(book["cash"] / equity * 100, 2) if equity else 0,
        "total_pnl": round(equity - start, 2),
        "roi_pct": round(roi, 2),
        "bench_ticker": BENCH_TICKER,
        "bench_equity": round(bench_equity, 2),
        "bench_roi_pct": round(bench_roi, 2),
        "alpha_vs_bench_pp": round(roi - bench_roi, 2) if bench_equity else 0.0,
        "positions": book["positions"],
        "config": cfg,
        "strategies": get_strategy_book(prices),
        "stats": get_stats(),
        "regime": regime or {},
        "equity_curve": curve,
    }
