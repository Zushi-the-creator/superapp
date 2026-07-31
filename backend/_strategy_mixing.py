"""STRATEGY MIXING: how to combine strategies through the year to cut losses
and keep winners.

Builds each strategy's daily equity curve once, then tests combination rules on
the return series:
  A  equal-weight blend of all active strategies (monthly rebalance)
  B  equal-weight blend + XLK core
  C  regime-conditional switching  -- map derived from IS ONLY (2016-2022),
     applied OOS (2023+). Avoids the lookahead trap logged in memory.
  D  strategy-momentum: hold top-2 strategies by trailing 126d, monthly
  E  inverse-volatility weighting (risk parity across strategies)
  F  drawdown-guard: drop any strategy >15% below its own peak, redistribute
Reports IS / OOS / 2026-YTD / worst-window for every rule vs XLK.
Tier B where stock strategies are involved (survivor universe = ceiling).
"""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
import numpy as np
from collections import defaultdict

IS0 = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
OOS0 = next(i for i, d in enumerate(dates) if d >= '2023-01-03')
Y0 = next(i for i, d in enumerate(dates) if d >= '2026-01-02')
XLi = C.columns.get_loc('XLK'); SPi = C.columns.get_loc('SPY')
NP_ = lambda d: R[d] not in {'DANGER', 'WEAK', 'CRISIS'}
DIPS = {'DIP_BUY', 'SHARP_DROP', 'BEAR_BOUNCE', 'CORRECTION'}
UP = {'HEALTHY', 'PULLBACK', 'DIP_BUY'}

print("building strategy curves ...", flush=True)
CUR = {}
CUR['TREND10']    = monthly_rot_g(_trend_sel, 10, IS0)[1:]
CUR['RELSTR10']   = monthly_rot_g(mk_relstr(99, 'XLK'), 10, IS0)[1:]
CUR['cap2+guard'] = monthly_rot_g(mk_relstr(2, 'SPY'), 10, IS0, pos_stop=0.15, dd_guard=0.12)[1:]
CUR['LeadSector'] = monthly_rot_g(_leadsec_sel, 10, IS0)[1:]
CUR['LC 12-1']    = monthly_rot(None, lc121, 10, IS0)
CUR['MR-dips90']  = stock_sim_cash(lambda d: (('mr', MRS, 90) if R[d] in DIPS else None), IS0)
CUR['MOM-brk90']  = stock_sim_cash(lambda d: (('mom', MOMS, 90) if R[d] in UP else None), IS0)
n = min(len(v) for v in CUR.values())
for k in CUR: CUR[k] = np.asarray(CUR[k], float)[:n]
XLK = np.array([Cf[IS0 + i, XLi] for i in range(n)]); XLK /= XLK[0]
SPY = np.array([Cf[IS0 + i, SPi] for i in range(n)]); SPY /= SPY[0]
regs = [R[IS0 + i] for i in range(n)]
names = list(CUR)
Rmat = np.vstack([np.diff(CUR[k]) / CUR[k][:-1] for k in names])   # strat x day returns
rx = np.diff(XLK) / XLK[:-1]
T = Rmat.shape[1]
mends = sorted({i for i in range(n - 1) if dates[IS0+i][:7] != dates[IS0+i+1][:7]})
mset = set(mends)
IS_T = OOS0 - IS0; Y_T = Y0 - IS0

# --- derive regime -> best strategy map from IS ONLY (no lookahead) ---
isr = defaultdict(lambda: defaultdict(list))
for t in range(min(IS_T, T)):
    rg = regs[t]
    for si, k in enumerate(names):
        isr[rg][k].append(Rmat[si, t])
REGMAP = {}
for rg, dd in isr.items():
    best = max(dd, key=lambda k: np.mean(dd[k]) if len(dd[k]) > 20 else -9)
    REGMAP[rg] = best
print("regime -> strategy map (derived from IS 2016-2022 only):")
for rg in sorted(REGMAP): print(f"   {rg:<14} -> {REGMAP[rg]}")

def combo(rule, core_w=0.0):
    """returns daily equity curve of the mixing rule."""
    eq = 1.0; out = [1.0]; w = np.ones(len(names)) / len(names); held = None
    peaks = np.ones(len(names)); cur = np.ones(len(names))
    for t in range(T):
        cur = cur * (1 + Rmat[:, t]); peaks = np.maximum(peaks, cur)
        if rule == 'A':    r = w @ Rmat[:, t]
        elif rule == 'B':  r = (1-core_w) * (w @ Rmat[:, t]) + core_w * rx[t]
        elif rule == 'C':
            k = REGMAP.get(regs[t], 'TREND10'); r = Rmat[names.index(k), t]
        elif rule == 'D':
            r = (w @ Rmat[:, t]) if held is None else np.mean([Rmat[i, t] for i in held])
        elif rule in ('E', 'F'):  r = w @ Rmat[:, t]
        else: r = rx[t]
        eq *= (1 + r); out.append(eq)
        if t in mset:
            if rule == 'D':
                lb = max(0, t - 126)
                perf = [(cur[i] / (cur[i] / np.prod(1 + Rmat[i, lb:t+1])) - 1) if t > lb else 0
                        for i in range(len(names))]
                perf = [np.prod(1 + Rmat[i, lb:t+1]) - 1 for i in range(len(names))]
                held = list(np.argsort(perf)[-2:])
            elif rule == 'E':
                lb = max(0, t - 63)
                vol = np.array([Rmat[i, lb:t+1].std() + 1e-9 for i in range(len(names))])
                w = (1 / vol); w /= w.sum()
            elif rule == 'F':
                ok = (cur > peaks * 0.85).astype(float)
                w = ok / ok.sum() if ok.sum() > 0 else np.ones(len(names)) / len(names)
    return np.array(out)

def stats(c, a, b):
    seg = np.asarray(c[a:b]); seg = seg / seg[0]
    yrs = len(seg) / 252
    pk = np.maximum.accumulate(seg)
    return (seg[-1] ** (1 / yrs) - 1) * 100, (seg / pk - 1).min() * 100, (seg[-1] - 1) * 100

RULES = [('A: equal-weight all 7', 'A', 0.0), ('B: 50% blend + 50% XLK', 'B', 0.5),
         ('B: 30% blend + 70% XLK', 'B', 0.7), ('C: regime-switch (IS map)', 'C', 0.0),
         ('D: top-2 by 126d momentum', 'D', 0.0), ('E: inverse-vol weights', 'E', 0.0),
         ('F: drop DD>15% strategies', 'F', 0.0)]
print(f"\n{'mixing rule':<28}{'IS CAGR':>9}{'OOS CAGR':>10}{'OOS MDD':>9}{'2026 YTD':>10}{'YTD MDD':>9}")
print('-' * 76)
for lbl, rule, cw in RULES:
    c = combo(rule, cw)
    i_c, _, _ = stats(c, 0, IS_T)
    o_c, o_m, _ = stats(c, IS_T, len(c))
    _, y_m, y_r = stats(c, Y_T, len(c))
    print(f"{lbl:<28}{i_c:>8.1f}%{o_c:>9.1f}%{o_m:>8.1f}%{y_r:>+9.1f}%{y_m:>8.1f}%")
for nm, arr in (('XLK buy-hold', XLK), ('SPY buy-hold', SPY)):
    i_c, _, _ = stats(arr, 0, IS_T); o_c, o_m, _ = stats(arr, IS_T, len(arr)); _, y_m, y_r = stats(arr, Y_T, len(arr))
    print(f"{nm:<28}{i_c:>8.1f}%{o_c:>9.1f}%{o_m:>8.1f}%{y_r:>+9.1f}%{y_m:>8.1f}%")
print(f"\n{'individual strategies':<28}{'IS CAGR':>9}{'OOS CAGR':>10}{'OOS MDD':>9}{'2026 YTD':>10}{'YTD MDD':>9}")
for k in names:
    c = CUR[k]; i_c, _, _ = stats(c, 0, IS_T); o_c, o_m, _ = stats(c, IS_T, len(c)); _, y_m, y_r = stats(c, Y_T, len(c))
    print(f"{k:<28}{i_c:>8.1f}%{o_c:>9.1f}%{o_m:>8.1f}%{y_r:>+9.1f}%{y_m:>8.1f}%")
# correlation matrix (diversification potential)
print("\nstrategy correlation (OOS daily returns) — low corr = mixing helps")
sub = Rmat[:, IS_T:]
cm = np.corrcoef(sub)
print("      " + "".join(f"{k[:7]:>9}" for k in names))
for i, k in enumerate(names):
    print(f"{k[:6]:<6}" + "".join(f"{cm[i,j]:>9.2f}" for j in range(len(names))))
