"""MIX9 ENGINE — live entry/exit engine. Deployed variant: XLK core.

Imports mix9_core (proven byte-identical to the backtest by _mix9_equiv_test.py),
adds the pieces a live book needs that a backtest does not:

  * component equity curves for all 7 strategies, recomputed from inception on
    every run so the DD-stop can never drift from what the backtest produces
  * the target book in dollars, given current equity
  * the diff between the current book and the target (what to actually trade)
  * a decision journal, so every fill has a recorded reason

No api_v2 import — same isolation rule as sim_engine.py, no circular dependency.

WHAT IT DOES EACH RUN
  1. read today's regime (prod-exact chain)
  2. look up the frozen regime -> strategy map
  3. recompute all 7 component equity curves; check whether the ACTIVE one is
     >15% below its own running peak
  4. if it is -> the 70% sleeve parks in the core (XLK), else it holds the
     active strategy's top-10
  5. build the dollar target: 30% core + 70% sleeve
  6. emit the trade list to reach it (only on month-end, or on a DD-stop flip)

EXITS ARE NOT TIMERS. A name leaves the book when it drops out of the active
strategy's monthly top-10, when the strategy switches, or when the DD-stop
fires. There is no Fixed42/Fixed60 here — that was the MR engine this replaces.
"""
from __future__ import annotations
import os, sqlite3, json, uuid
from typing import Dict, List, Optional, Tuple
import numpy as np

from mix9_core import (Mix9Data, REGMAP, STRATEGIES, DD_STOP, CORE_WEIGHT,
                       SLEEVE_WEIGHT, TOP_N, INCEPTION, FEE, SLIP, EFEE)

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, 'data', 'mix9.db')

# DEPLOY VARIANT: XLK core (user decision 2026-07-31, after a head-to-head test).
# XLK core beat SPY core in 7/10 calendar years and compounds $19,511 -> $982K vs
# $737K over the decade. The cost is real and was accepted knowingly: 2022 was
# -27.4% vs -17.7%, OOS MDD -25.7% vs -18.8%, and DSR@40 0.826 vs 0.869.
# NOTE the ETF gap does NOT transmit proportionally — XLK-the-ETF beats SPY by
# 13-15pp over recent windows, but MIX9-XLK beats MIX9-SPY by only ~2pp (and
# LOSES by 4.6pp over the last 12 months), because the core is just 30% of the
# book and is bypassed entirely whenever the sleeve is active.
# This matches the registered roster-9 rule, which also specifies an XLK core.
CORE_TICKER = 'XLK'
MIN_POSITION_USD = 300.0     # below this a slot is not worth a fill
REBALANCE_DRIFT_PCT = 25.0   # off-cycle correction only if a leg drifts this far


# ══════════════════════════════════════════════════════════════════════════
# state DB
# ══════════════════════════════════════════════════════════════════════════
def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    with _connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mix9_state (
            id INTEGER PRIMARY KEY CHECK (id=1),
            core_ticker TEXT, enabled INTEGER DEFAULT 0,
            last_rebalance_date TEXT, last_active_strategy TEXT,
            dd_parked INTEGER DEFAULT 0, updated_at TEXT);
        CREATE TABLE IF NOT EXISTS mix9_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, cycle_id TEXT, ts TEXT,
            asof TEXT, kind TEXT, ticker TEXT, regime TEXT, strategy TEXT,
            dd_pct REAL, target_usd REAL, reason TEXT);
        CREATE TABLE IF NOT EXISTS mix9_strategy_equity (
            asof TEXT, strategy TEXT, equity REAL, peak REAL, dd_pct REAL,
            PRIMARY KEY (asof, strategy));
        """)
        c.execute("INSERT OR IGNORE INTO mix9_state (id, core_ticker, enabled) VALUES (1,?,0)",
                  (CORE_TICKER,))


def get_state() -> Dict:
    init_db()
    with _connect() as c:
        r = c.execute("SELECT * FROM mix9_state WHERE id=1").fetchone()
    return dict(r) if r else {}


def set_state(**kw) -> None:
    if not kw: return
    init_db()
    cols = ", ".join(f"{k}=?" for k in kw)
    with _connect() as c:
        c.execute(f"UPDATE mix9_state SET {cols}, updated_at=datetime('now') WHERE id=1",
                  tuple(kw.values()))


def _log(conn, cycle_id: str, kind: str, *, asof: str = "", ticker: str = "",
         regime: str = "", strategy: str = "", dd_pct: float = 0.0,
         target_usd: float = 0.0, reason: str = "") -> None:
    conn.execute(
        "INSERT INTO mix9_decisions (cycle_id, ts, asof, kind, ticker, regime, strategy,"
        " dd_pct, target_usd, reason) VALUES (?,datetime('now'),?,?,?,?,?,?,?,?)",
        (cycle_id, asof, kind, ticker, regime, strategy, dd_pct, target_usd, reason))


def get_decisions(limit: int = 200) -> List[Dict]:
    init_db()
    with _connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM mix9_decisions ORDER BY id DESC LIMIT ?", (limit,))]


# ══════════════════════════════════════════════════════════════════════════
# component equity curves — the DD-stop input
# ══════════════════════════════════════════════════════════════════════════
def _rotation_equity(D: Mix9Data, sel, s0: int, end: int,
                     pos_stop: Optional[float] = None,
                     dd_guard: Optional[float] = None) -> np.ndarray:
    """Monthly rotation equity. Mirrors _master_harness3.monthly_rot_g exactly."""
    fee = FEE + SLIP
    spy_i = D.colix['SPY']
    eq = 1.0; hold: Dict[int, Tuple[float, float]] = {}
    peak = 1.0; parked = False; out = [1.0]
    for i in range(s0, end + 1):
        if parked:
            a, b = D.Cf[i - 1, spy_i], D.Cf[i, spy_i]
            eq *= (b / a) if (np.isfinite(a) and np.isfinite(b) and a > 0) else 1.0
        elif hold:
            rs = []
            for col, (ep, pk) in list(hold.items()):
                if not (np.isfinite(D.Cv[i, col]) and np.isfinite(D.Cv[i - 1, col])
                        and D.Cv[i - 1, col] > 0 and i <= D.last_valid[col]):
                    continue
                rs.append(D.Cv[i, col] / D.Cv[i - 1, col] - 1)
                hold[col] = (ep, max(pk, D.Cv[i, col]))
            eq *= (1 + float(np.mean(rs))) if rs else 1.0
        peak = max(peak, eq)
        if pos_stop and hold and not parked:
            drop = [c for c, (ep, pk) in hold.items()
                    if np.isfinite(D.Cv[i, c]) and D.Cv[i, c] < pk * (1 - pos_stop)]
            if drop:
                eq *= 1 - fee * (len(drop) / max(len(hold), 1))
                for c in drop: hold.pop(c, None)
        if dd_guard:
            if not parked and eq < peak * (1 - dd_guard):
                eq *= 1 - fee; hold = {}; parked = True
            elif parked and eq > peak * (1 - dd_guard / 2):
                parked = False
        if (i - 1) in D.month_end and not parked:
            new = sel(i - 1, TOP_N)
            if new:
                ch = len(set(new) ^ set(hold))
                eq *= 1 - fee * 2 * (ch / max(len(new) + len(hold), 1))
                hold = {}
                for col in new:
                    p = D.Ov[i, col] if (np.isfinite(D.Ov[i, col]) and D.Ov[i, col] > 0) else D.Cv[i - 1, col]
                    hold[col] = (p, p)
        out.append(eq)
    return np.array(out)


def _signal_sleeve_equity(D: Mix9Data, kind: str, hold_days: int,
                          regimes: List[str], allowed: set, s0: int, end: int,
                          nslot: int = 5) -> np.ndarray:
    """MR-dips90 / MOM-brk90 equity. Mirrors stock_sim_cash (cash idle)."""
    sig = D.mr_sig if kind == 'mr' else D.mom_sig
    score = D.MRS if kind == 'mr' else D.MOMS
    cash = 1.0; op: List[Tuple[int, float, int, float]] = []; out = [1.0]
    for d in range(s0, end + 1):
        keep = []
        for (x, inv, col, ep) in op:
            if d >= x:
                xi = min(x, D.ND - 1, D.last_valid[col]) if D.last_valid[col] >= 0 else min(x, D.ND - 1)
                cash += inv * (D.Cf[xi, col] / ep) * (1 - FEE - SLIP)
            else:
                keep.append((x, inv, col, ep))
        op = keep
        eq = cash + sum(inv * (D.Cf[d, col] / ep) for (_, inv, col, ep) in op)
        if regimes[d] in allowed and d + 1 <= end and d in sig:
            free = nslot - len(op); held = {x[2] for x in op}
            for col in sorted(sig[d], key=lambda x: -score[d, x]):
                if free == 0: break
                if col in held: continue
                ep = D.Ov[d + 1, col]
                if not np.isfinite(ep) or ep <= 0: continue
                al = min(eq / nslot, cash)
                if al <= eq * 0.02: break
                cash -= al; al *= (1 - FEE - SLIP)
                op.append((d + 1 + hold_days, al, col, ep)); held.add(col); free -= 1
        out.append(eq)
    return np.array(out)


DIP_REGIMES = {'DIP_BUY', 'SHARP_DROP', 'BEAR_BOUNCE', 'CORRECTION'}
UP_REGIMES = {'HEALTHY', 'PULLBACK', 'DIP_BUY'}


def component_equities(D: Mix9Data, asof_i: int) -> Dict[str, Dict]:
    """All 7 component equity curves from inception to asof_i.

    Recomputed every run rather than persisted: persisted state would slowly
    drift away from what the backtest produces, and the DD-stop is the one
    thing that MUST match or the strategy behaves differently live.
    """
    s0 = D.index_of_date(INCEPTION)
    regimes = [D.regime_at(i) for i in range(D.ND)]
    curves = {
        'TREND10':    _rotation_equity(D, D.sel_trend, s0, asof_i),
        'RELSTR10':   _rotation_equity(D, lambda j, k: D.sel_relstr(j, k, 99, 'XLK'), s0, asof_i),
        'cap2+guard': _rotation_equity(D, lambda j, k: D.sel_relstr(j, k, 2, 'SPY'), s0, asof_i,
                                       pos_stop=0.15, dd_guard=0.12),
        'LeadSector': _rotation_equity(D, D.sel_leadsector, s0, asof_i),
        'LC 12-1':    _rotation_equity(D, D.sel_lc121, s0, asof_i),
        'MR-dips90':  _signal_sleeve_equity(D, 'mr', 90, regimes, DIP_REGIMES, s0, asof_i),
        'MOM-brk90':  _signal_sleeve_equity(D, 'mom', 90, regimes, UP_REGIMES, s0, asof_i),
    }
    out = {}
    for k, c in curves.items():
        eq = float(c[-1]); peak = float(np.maximum.accumulate(c)[-1])
        out[k] = {'equity': eq, 'peak': peak,
                  'dd_pct': (eq / peak - 1) * 100 if peak > 0 else 0.0,
                  'parked': eq < peak * (1 - DD_STOP)}
    return out


# ══════════════════════════════════════════════════════════════════════════
# the target book
# ══════════════════════════════════════════════════════════════════════════
def compute_target(equity_usd: float, asof: Optional[str] = None,
                   D: Optional[Mix9Data] = None) -> Dict:
    """The full MIX9 decision for a given date and account size."""
    D = D or Mix9Data()
    i = D.ND - 1 if asof is None else D.index_of_date(asof)
    asof_d = D.dates[i]
    regime = D.regime_at(i)
    active = REGMAP.get(regime, 'TREND10')
    comps = component_equities(D, i)
    ddinfo = comps[active]
    parked = bool(ddinfo['parked'])

    core_i = D.colix[CORE_TICKER]
    core_px = float(D.Cf[i, core_i])
    core_usd = equity_usd * CORE_WEIGHT
    sleeve_usd = equity_usd * SLEEVE_WEIGHT

    picks: List[Dict] = []
    if parked:
        core_usd += sleeve_usd
        sleeve_usd = 0.0
    else:
        sel = D.selector(active)
        cols = sel(i, TOP_N) if sel else []
        if not cols:                       # selector empty -> park rather than guess
            core_usd += sleeve_usd; sleeve_usd = 0.0; parked = True
        else:
            per = sleeve_usd / len(cols)
            for c in cols:
                px = float(D.Cf[i, c])
                if not np.isfinite(px) or px <= 0: continue
                picks.append({'ticker': D.cols[c], 'target_usd': round(per, 2),
                              'price': round(px, 2), 'shares': round(per / px, 4)})

    return {
        'asof': asof_d, 'regime': regime, 'active_strategy': active,
        'dd_pct': round(ddinfo['dd_pct'], 2), 'dd_stop_pct': DD_STOP * 100,
        'parked': parked,
        'core': {'ticker': CORE_TICKER, 'target_usd': round(core_usd, 2),
                 'price': round(core_px, 2), 'shares': round(core_usd / core_px, 4)},
        'sleeve': picks,
        'sleeve_usd': round(sleeve_usd, 2),
        'equity_usd': round(equity_usd, 2),
        'is_rebalance_day': (i - 1) in D.month_end or i in D.month_end,
        'components': {k: {'dd_pct': round(v['dd_pct'], 2), 'parked': v['parked']}
                       for k, v in comps.items()},
    }


def diff_to_target(current: Dict[str, float], target: Dict) -> List[Dict]:
    """current: {ticker: current_usd}. Returns the trade list to reach target."""
    want: Dict[str, float] = {target['core']['ticker']: target['core']['target_usd']}
    for p in target['sleeve']:
        want[p['ticker']] = want.get(p['ticker'], 0.0) + p['target_usd']
    trades = []
    for tk in sorted(set(want) | set(current)):
        cu = float(current.get(tk, 0.0)); tg = float(want.get(tk, 0.0))
        d = tg - cu
        if abs(d) < MIN_POSITION_USD: continue
        trades.append({'ticker': tk, 'side': 'BUY' if d > 0 else 'SELL',
                       'usd': round(abs(d), 2), 'current_usd': round(cu, 2),
                       'target_usd': round(tg, 2)})
    trades.sort(key=lambda t: (t['side'] == 'BUY', -t['usd']))   # sells first, frees cash
    return trades


def run_cycle(equity_usd: float, current: Dict[str, float],
              *, dry_run: bool = True, force: bool = False) -> Dict:
    """Compute the decision and journal it. Returns target + trade list."""
    init_db()
    cycle_id = uuid.uuid4().hex[:12]
    D = Mix9Data()
    tgt = compute_target(equity_usd, D=D)
    st = get_state()
    switched = st.get('last_active_strategy') not in (None, tgt['active_strategy'])
    dd_flip = bool(st.get('dd_parked', 0)) != tgt['parked']
    should_trade = force or tgt['is_rebalance_day'] or switched or dd_flip
    trades = diff_to_target(current, tgt) if should_trade else []

    with _connect() as c:
        _log(c, cycle_id, 'CYCLE', asof=tgt['asof'], regime=tgt['regime'],
             strategy=tgt['active_strategy'], dd_pct=tgt['dd_pct'],
             reason=(f"regime={tgt['regime']} -> {tgt['active_strategy']}; "
                     f"dd={tgt['dd_pct']:.1f}% (stop -{DD_STOP*100:.0f}%); "
                     f"{'PARKED in core' if tgt['parked'] else 'sleeve active'}; "
                     f"trade={'yes' if should_trade else 'no'}"
                     f"{' [rebalance day]' if tgt['is_rebalance_day'] else ''}"
                     f"{' [strategy switch]' if switched else ''}"
                     f"{' [dd flip]' if dd_flip else ''}"))
        for t in trades:
            _log(c, cycle_id, t['side'], asof=tgt['asof'], ticker=t['ticker'],
                 regime=tgt['regime'], strategy=tgt['active_strategy'],
                 target_usd=t['target_usd'],
                 reason=f"{t['side']} ${t['usd']:,.0f} to move {t['ticker']} "
                        f"${t['current_usd']:,.0f} -> ${t['target_usd']:,.0f}")
        for k, v in tgt['components'].items():
            c.execute("INSERT OR REPLACE INTO mix9_strategy_equity "
                      "(asof, strategy, equity, peak, dd_pct) VALUES (?,?,?,?,?)",
                      (tgt['asof'], k, 0.0, 0.0, v['dd_pct']))
    if not dry_run:
        set_state(last_active_strategy=tgt['active_strategy'],
                  dd_parked=int(tgt['parked']),
                  last_rebalance_date=tgt['asof'] if should_trade else st.get('last_rebalance_date'))
    return {'cycle_id': cycle_id, 'target': tgt, 'trades': trades,
            'should_trade': should_trade, 'dry_run': dry_run}


if __name__ == '__main__':
    import sys
    eq = float(sys.argv[1]) if len(sys.argv) > 1 else 19511.0
    r = run_cycle(eq, {}, dry_run=True, force=True)
    t = r['target']
    print(f"asof {t['asof']}  regime {t['regime']}  ->  {t['active_strategy']}")
    print(f"strategy dd {t['dd_pct']:+.1f}% (stop -{t['dd_stop_pct']:.0f}%)  parked={t['parked']}")
    print(f"\ncore  {t['core']['ticker']:<6} ${t['core']['target_usd']:>10,.2f}  "
          f"{t['core']['shares']:>10.4f} sh @ ${t['core']['price']:.2f}")
    print(f"sleeve (${t['sleeve_usd']:,.2f} across {len(t['sleeve'])}):")
    for p in t['sleeve']:
        print(f"      {p['ticker']:<6} ${p['target_usd']:>10,.2f}  {p['shares']:>10.4f} sh @ ${p['price']:.2f}")
    print(f"\ncomponent drawdowns:")
    for k, v in t['components'].items():
        print(f"      {k:<12} {v['dd_pct']:>+7.2f}%  {'PARKED' if v['parked'] else ''}")
