"""Top strategies: last 5 years + YTD actual trades, annotated with REGIME and SECTOR.

Uses canonical harness machinery (point-in-time sector map, prod-exact regimes).
Tier B for stock strategies (survivor universe = ceiling).
"""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
import numpy as np
from collections import Counter, defaultdict

XLi = C.columns.get_loc('XLK'); QQi = C.columns.get_loc('QQQ')
NP_ = lambda d: R[d] not in {'DANGER', 'WEAK', 'CRISIS'}
DIPS = {'DIP_BUY', 'SHARP_DROP', 'BEAR_BOUNCE', 'CORRECTION'}

def rot_trades(sel, top_n, s0, s1, pos_stop=None, dd_guard=None):
    """monthly rotation returning (equity_curve, trade_log). Trades at next open."""
    fee = FEE + SLIP; eq = 1.0; hold = {}; peak = 1.0; parked = False
    curve = [1.0]; log = []
    for i in range(s0, s1 + 1):
        if parked:
            eq *= Cf[i, C.columns.get_loc('SPY')] / Cf[i-1, C.columns.get_loc('SPY')]
        elif hold:
            rs = []
            for col, (ep, pk) in list(hold.items()):
                if not (np.isfinite(Cv[i, col]) and np.isfinite(Cv[i-1, col])
                        and Cv[i-1, col] > 0 and i <= last_valid[col]):
                    continue
                rs.append(Cv[i, col] / Cv[i-1, col] - 1)
                hold[col] = (ep, max(pk, Cv[i, col]))
            eq *= (1 + np.mean(rs)) if rs else 1
        peak = max(peak, eq)
        if pos_stop and hold and not parked:
            drop = [c for c, (ep, pk) in hold.items()
                    if np.isfinite(Cv[i, c]) and Cv[i, c] < pk * (1 - pos_stop)]
            if drop:
                eq *= 1 - fee * (len(drop) / max(len(hold), 1))
                for c in drop:
                    log.append(('STOP', dates[i], C.columns[c], float(Cv[i, c]),
                                (Cv[i, c] / hold[c][0] - 1) * 100, R[i]))
                    hold.pop(c, None)
        if dd_guard:
            if not parked and eq < peak * (1 - dd_guard):
                eq *= 1 - fee
                for c in hold: log.append(('GUARD-EXIT', dates[i], C.columns[c], float(Cv[i, c]),
                                           (Cv[i, c] / hold[c][0] - 1) * 100, R[i]))
                hold = {}; parked = True
            elif parked and eq > peak * (1 - dd_guard / 2):
                parked = False; log.append(('UNPARK', dates[i], '-', 0.0, 0.0, R[i]))
        if (i - 1 in me) and not parked and i <= s1:
            new = sel(i - 1, top_n)
            if new:
                sec = _sectors_at(i - 1)
                for c in list(hold):
                    if c not in new:
                        log.append(('SELL', dates[i], C.columns[c], float(Cv[i-1, c]),
                                    (Cv[i-1, c] / hold[c][0] - 1) * 100, R[i-1]))
                ch = len(set(new) ^ set(hold))
                eq *= 1 - fee * 2 * (ch / max(len(new) + len(hold), 1))
                nh = {}
                for c in new:
                    p = Ov[i, c] if (np.isfinite(Ov[i, c]) and Ov[i, c] > 0) else Cv[i-1, c]
                    if c not in hold:
                        log.append(('BUY', dates[i], C.columns[c], float(p), None,
                                    R[i-1], sec.get(c, '?')))
                    nh[c] = hold.get(c, (p, p))
                hold = nh
        curve.append(eq)
    return np.array(curve), log, hold

def yr_bounds(y):
    a = next(i for i, d in enumerate(dates) if d >= f'{y}-01-01')
    b = max(i for i, d in enumerate(dates) if d <= f'{y}-12-31')
    return a, b

SELS = {'TREND10': _trend_sel, 'RELSTR10': mk_relstr(99, 'XLK'),
        'RELSTR10-cap2': mk_relstr(2, 'XLK'), 'Leading-sector': _leadsec_sel}

print("=== LAST 5 YEARS: annual return + dominant regime + sector concentration ===")
print(f"{'year':<6}" + "".join(f"{k:>16}" for k in SELS) + f"{'XLK':>9}{'QQQ':>9}   regime mix (days)")
for y in range(2022, 2027):
    a, b = yr_bounds(y)
    line = f"{y}{'*' if y == 2026 else ' '}   "
    for k, sel in SELS.items():
        cv, _, _ = rot_trades(sel, 10, a, b)
        line += f"{(cv[-1]-1)*100:>+15.1f}%"
    rx = (Cf[b, XLi] / Cf[a, XLi] - 1) * 100
    rq = (Cf[b, QQi] / Cf[a, QQi] - 1) * 100
    rc = Counter(R[i] for i in range(a, b + 1))
    mix = " ".join(f"{k[:4]}:{v}" for k, v in rc.most_common(3))
    print(line + f"{rx:>+8.1f}%{rq:>+8.1f}%   {mix}")

Y0 = next(i for i, d in enumerate(dates) if d >= '2026-01-02')
for name in ('TREND10', 'RELSTR10'):
    sel = SELS[name]
    cv, log, hold = rot_trades(sel, 10, Y0, ND - 1)
    print(f"\n{'='*100}\n=== {name} — 2026 YTD actual trades  (final {(cv[-1]-1)*100:+.1f}%, XLK {(Cf[ND-1,XLi]/Cf[Y0,XLi]-1)*100:+.1f}%) ===")
    print(f"{'date':<12}{'action':<7}{'ticker':<7}{'price':>9}{'P&L':>9}  {'regime':<12}sector")
    for row in log:
        typ, dt, tk, px, pnl, reg = row[:6]
        sec = row[6] if len(row) > 6 else ''
        pl = f"{pnl:>+8.1f}%" if pnl is not None else "        "
        print(f"{dt:<12}{typ:<7}{tk:<7}{px:>9.2f}{pl}  {reg:<12}{sec}")
    sec_now = _sectors_at(ND - 1)
    cnt = Counter(sec_now.get(c, '?') for c in hold)
    print(f"  OPEN BOOK ({len(hold)}): " + ", ".join(C.columns[c] for c in hold))
    print(f"  sector mix: " + ", ".join(f"{k} {v}" for k, v in cnt.most_common()))

print(f"\n{'='*100}\n=== SECTOR EXPOSURE BY YEAR (share of monthly picks) ===")
for name in ('TREND10', 'RELSTR10'):
    sel = SELS[name]
    print(f"\n-- {name} --")
    for y in range(2022, 2027):
        a, b = yr_bounds(y)
        cnt = Counter()
        for i in range(a, b + 1):
            if i - 1 in me:
                sec = _sectors_at(i - 1)
                for c in sel(i - 1, 10):
                    cnt[sec.get(c, '?')] += 1
        tot = sum(cnt.values()) or 1
        top = ", ".join(f"{k} {v/tot*100:.0f}%" for k, v in cnt.most_common(4))
        print(f"  {y}: {top}")
