"""SAME CALENDAR WINDOW across years: Jan 2 -> Jul 30, every year 2017-2026.
Like-for-like comparison with the 2026 YTD window we are currently living through.
Annotated with the regime mix of each window. Tier B for stock strategies."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
import numpy as np
from collections import Counter

XLi = C.columns.get_loc('XLK'); QQi = C.columns.get_loc('QQQ'); SPi = C.columns.get_loc('SPY')
NP_ = lambda d: R[d] not in {'DANGER', 'WEAK', 'CRISIS'}
DIPS = {'DIP_BUY', 'SHARP_DROP', 'BEAR_BOUNCE', 'CORRECTION'}
UP = {'HEALTHY', 'PULLBACK', 'DIP_BUY'}

def window(y):
    a = next((i for i, d in enumerate(dates) if d >= f'{y}-01-01'), None)
    b = max((i for i, d in enumerate(dates) if d <= f'{y}-07-30'), default=None)
    return a, b

def rot(sel, n, a, b, pos_stop=None, dd_guard=None):
    fee = FEE + SLIP; eq = 1.0; hold = {}; peak = 1.0; parked = False; c = [1.0]
    for i in range(a, b + 1):
        if parked:
            eq *= Cf[i, SPi] / Cf[i-1, SPi]
        elif hold:
            rs = []
            for col, (ep, pk) in list(hold.items()):
                if not (np.isfinite(Cv[i, col]) and np.isfinite(Cv[i-1, col])
                        and Cv[i-1, col] > 0 and i <= last_valid[col]):
                    continue
                rs.append(Cv[i, col] / Cv[i-1, col] - 1); hold[col] = (ep, max(pk, Cv[i, col]))
            eq *= (1 + np.mean(rs)) if rs else 1
        peak = max(peak, eq)
        if pos_stop and hold and not parked:
            drop = [c2 for c2, (ep, pk) in hold.items()
                    if np.isfinite(Cv[i, c2]) and Cv[i, c2] < pk * (1 - pos_stop)]
            if drop:
                eq *= 1 - fee * (len(drop) / max(len(hold), 1))
                for c2 in drop: hold.pop(c2, None)
        if dd_guard:
            if not parked and eq < peak * (1 - dd_guard): eq *= 1 - fee; hold = {}; parked = True
            elif parked and eq > peak * (1 - dd_guard / 2): parked = False
        if (i - 1 in me) and not parked:
            new = sel(i - 1, n)
            if new:
                ch = len(set(new) ^ set(hold)); eq *= 1 - fee * 2 * (ch / max(len(new) + len(hold), 1))
                nh = {}
                for col in new:
                    p = Ov[i, col] if (np.isfinite(Ov[i, col]) and Ov[i, col] > 0) else Cv[i-1, col]
                    nh[col] = hold.get(col, (p, p))
                hold = nh
        c.append(eq)
    return c[-1] - 1

def mr_sim(a, b, spec_fn):
    cash = 1.0; op = []
    for d in range(a, b + 1):
        k = []
        for (x, inv, col, ep) in op:
            if d >= x:
                xi = min(x, ND-1, last_valid[col]) if last_valid[col] >= 0 else min(x, ND-1)
                f = DELIST_HC if (x > last_valid[col] and last_valid[col] < ND-10) else 1.0
                cash += inv * (Cf[xi, col] * f / ep) * (1 - FEE - SLIP)
            else: k.append((x, inv, col, ep))
        op = k
        eq = cash + sum(inv * (Cf[d, col] / ep) for (_, inv, col, ep) in op)
        sp = spec_fn(d)
        if sp and d + 1 <= b:
            skey, score, hold_d, slots = sp
            if (skey, d) in sig:
                free = slots - len(op); hd = {x[2] for x in op}
                for col in sorted(sig[(skey, d)], key=lambda x: -score[d, x]):
                    if free == 0: break
                    if col in hd: continue
                    ep = Ov[d+1, col]
                    if not np.isfinite(ep) or ep <= 0: continue
                    al = min(eq / slots, cash)
                    if al <= eq * 0.02: break
                    cash -= al; al *= (1 - FEE - SLIP)
                    op.append((d + 1 + hold_d, al, col, ep)); hd.add(col); free -= 1
    return (cash + sum(inv * (Cf[b, col] / ep) * (1 - FEE - SLIP) for (_, inv, col, ep) in op)) - 1

STR = [
    ('TREND10',        lambda a, b: rot(_trend_sel, 10, a, b)),
    ('RELSTR10',       lambda a, b: rot(mk_relstr(99, 'XLK'), 10, a, b)),
    ('RELSTR10-cap2',  lambda a, b: rot(mk_relstr(2, 'XLK'), 10, a, b)),
    ('cap2+guard',     lambda a, b: rot(mk_relstr(2, 'SPY'), 10, a, b, 0.15, 0.12)),
    ('LeadSector',     lambda a, b: rot(_leadsec_sel, 10, a, b)),
    ('LC 12-1',        lambda a, b: monthly_rot(None, lc121, 10, a)[b - a] / monthly_rot(None, lc121, 10, a)[0] - 1),
    ('MR-dips F90',    lambda a, b: mr_sim(a, b, lambda d: ('mr', MRS, 90, 5) if R[d] in DIPS else None)),
    ('PROD MR-F42',    lambda a, b: mr_sim(a, b, lambda d: ('mr', MRS, 42, 5) if NP_(d) else None)),
]
print("SAME WINDOW EVERY YEAR:  Jan 2  ->  Jul 30")
print(f"{'year':<6}" + "".join(f"{n:>14}" for n, _ in STR) + f"{'XLK':>9}{'QQQ':>9}   regime mix")
print('-' * 152)
res = {n: [] for n, _ in STR}
for y in range(2017, 2027):
    a, b = window(y)
    if a is None or b is None or b <= a: continue
    line = f"{y}{'*' if y == 2026 else ' '}   "
    for n, fn in STR:
        try: v = fn(a, b) * 100
        except Exception: v = float('nan')
        res[n].append(v); line += f"{v:>+13.1f}%"
    rx = (Cf[b, XLi] / Cf[a, XLi] - 1) * 100
    rq = (Cf[b, QQi] / Cf[a, QQi] - 1) * 100
    rc = Counter(R[i] for i in range(a, b + 1))
    print(line + f"{rx:>+8.1f}%{rq:>+8.1f}%   " + " ".join(f"{k[:4]}:{v}" for k, v in rc.most_common(3)))
print('-' * 152)
avg = "avg   " + "".join(f"{np.nanmean(res[n]):>+13.1f}%" for n, _ in STR)
med = "med   " + "".join(f"{np.nanmedian(res[n]):>+13.1f}%" for n, _ in STR)
print(avg); print(med)
xl = [(Cf[window(y)[1], XLi] / Cf[window(y)[0], XLi] - 1) * 100 for y in range(2017, 2027)]
print(f"\nXLK same-window: avg {np.mean(xl):+.1f}%  median {np.median(xl):+.1f}%")
print("\nrank of 2026 within each strategy's own 10-year history of this window:")
for n, _ in STR:
    v = res[n]
    if len(v) < 2 or not np.isfinite(v[-1]): continue
    rank = sum(1 for x in v[:-1] if np.isfinite(x) and x > v[-1]) + 1
    print(f"  {n:<16}2026 = {v[-1]:+7.1f}%   rank {rank}/{len([x for x in v if np.isfinite(x)])}")
r26 = xl[-1]
print(f"  {'XLK':<16}2026 = {r26:+7.1f}%   rank {sum(1 for x in xl[:-1] if x > r26)+1}/{len(xl)}")
