"""RESEARCH CYCLE — round 6: BLEND + LEVER TO EQUAL RISK.

Round 5 result (2,352-cell grid): multi-asset rotation does NOT beat XLK.
Honest IS->OOS selection gave OOS MAR 1.35 vs XLK 1.37, and only 34/2352 cells
(1.4%) beat XLK's OOS Sharpe — indistinguishable from noise. The whole family
loses badly IN-SAMPLE (median IS CAGR 6.0% vs XLK 18.4%).

BUT the sleeve has a property XLK does not: MDD around -10% to -17% vs -25.7%.

That is the textbook setup for the institutional approach the literature actually
endorses (Man Group / Research Affiliates / AQR risk-parity work):
    1. build the highest-SHARPE base you can, ignoring its raw return
    2. then LEVER it to the risk level you actually want
Return is a leverage decision; Sharpe is the thing you cannot buy.

So: does a levered XLK+diversifier blend beat plain XLK at EQUAL RISK?

ANTI-CONTAMINATION: the sleeve used here is the cell selected on IS ONLY in round 5.
Using round 5's OOS-best cell would be circular.
"""
exec(open('_hunt_r5.py').read().split('# ── benchmarks ──')[0])
import numpy as np, math, bisect

print("\n" + "=" * 100)
print("ROUND 6 — BLEND AND LEVER TO EQUAL RISK")
print("=" * 100)

# sleeves chosen on IS ONLY in round 5 (no OOS peeking)
SLEEVES = {
    'MA-isMAR  (factors/blend/252/k2/ivol/cash/M)': dict(uset='factors', sig='blend', lb=252, k=2, wt='ivol', dfns='cash', rb='M'),
    'MA-isCAGR (US-eq/mom/252/k5/eq/GLD/M)':        dict(uset='US-equity', sig='mom', lb=252, k=5, wt='eq', dfns='GLD', rb='M'),
}


def curve(spec, a, b=None):
    return build(spec['uset'], spec['sig'], spec['lb'], spec['k'], spec['wt'],
                 spec['dfns'], spec['rb'], s0=a, s1=b)


def bh(t, a, b=None):
    b = b if b is not None else ND - 1
    return np.array([P[i, IX[t]] / P[a, IX[t]] for i in range(a, b + 1)])


def rets(c):
    c = np.asarray(c, float); return np.diff(c) / c[:-1]


def stat_r(r, lev=1.0, rate=None):
    rr = lev * r + (max(1 - lev, 0) * (rate if rate is not None else 0.0))
    if lev > 1 and rate is not None: rr = rr - (lev - 1) * rate
    eq = np.cumprod(1 + rr); pk = np.maximum.accumulate(eq)
    cg = (eq[-1] ** (252 / len(rr)) - 1) * 100
    md = (eq / pk - 1).min() * 100
    sh = (rr.mean() / (rr.std() + 1e-12)) * math.sqrt(252)
    return cg, md, sh, cg / abs(md) if md else 0


print("\n--- STEP 1: sleeve vs XLK, and their CORRELATION (OOS) ---")
xo = rets(bh('XLK', OOS0))
print(f"{'series':<46}{'CAGR':>8}{'MDD':>8}{'Shrp':>7}{'MAR':>7}{'corr w/XLK':>12}")
print(f"{'XLK':<46}{stat_r(xo)[0]:>7.1f}%{stat_r(xo)[1]:>7.1f}%{stat_r(xo)[2]:>7.2f}{stat_r(xo)[3]:>7.2f}{1.0:>12.2f}")
SR = {}
for nm, sp in SLEEVES.items():
    r = rets(curve(sp, OOS0)); n = min(len(r), len(xo)); SR[nm] = r[:n]
    s = stat_r(r)
    print(f"{nm:<46}{s[0]:>7.1f}%{s[1]:>7.1f}%{s[2]:>7.2f}{s[3]:>7.2f}{np.corrcoef(r[:n], xo[:n])[0,1]:>12.2f}")

print("\n--- STEP 2: BLEND SWEEP (unlevered). w = weight on the diversifier sleeve ---")
best = {}
for nm in SLEEVES:
    print(f"\n  {nm}")
    print(f"    {'w_sleeve':<10}{'CAGR':>8}{'MDD':>8}{'Shrp':>7}{'MAR':>7}")
    sr = SR[nm]; n = len(sr); x = xo[:n]
    for w in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0):
        r = (1 - w) * x + w * sr
        s = stat_r(r)
        print(f"    {w:<10.1f}{s[0]:>7.1f}%{s[1]:>7.1f}%{s[2]:>7.2f}{s[3]:>7.2f}")
        if nm not in best or s[2] > best[nm][1]: best[nm] = (w, s[2])
    print(f"    -> max-Sharpe blend at w={best[nm][0]:.1f} (Sharpe {best[nm][1]:.2f} vs XLK {stat_r(x)[2]:.2f})")

print("\n" + "=" * 100)
print("STEP 3 — THE REAL TEST: lever the best blend to XLK's VOLATILITY, then compare returns.")
print("         Equal risk, so any return difference is genuine, not leverage.")
print("=" * 100)
RT = np.array([0.05 / 252] * len(xo))
xvol = xo.std()
xs = stat_r(xo)
print(f"XLK: CAGR {xs[0]:.1f}%  MDD {xs[1]:.1f}%  Sharpe {xs[2]:.2f}  ann.vol {xvol*math.sqrt(252)*100:.1f}%")
print(f"\n{'blend':<46}{'lev':>6}{'CAGR':>8}{'MDD':>8}{'Shrp':>7}{'vs XLK':>9}")
for nm in SLEEVES:
    w = best[nm][0]; sr = SR[nm]; n = len(sr); x = xo[:n]
    r = (1 - w) * x + w * sr
    lev = xvol / r.std()
    s = stat_r(r, lev=lev, rate=RT[:n])
    print(f"{(nm.split('(')[0].strip() + f' w={w:.1f}'):<46}{lev:>6.2f}{s[0]:>7.1f}%{s[1]:>7.1f}%{s[2]:>7.2f}{s[0]-xs[0]:>+8.1f}")

print("\n--- STEP 4: same test but lever to XLK's MAX DRAWDOWN instead of vol ---")
print(f"{'blend':<46}{'lev':>6}{'CAGR':>8}{'MDD':>8}{'Shrp':>7}{'vs XLK':>9}")
for nm in SLEEVES:
    w = best[nm][0]; sr = SR[nm]; n = len(sr); x = xo[:n]
    r = (1 - w) * x + w * sr
    lo, hi = 0.5, 4.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if abs(stat_r(r, lev=mid, rate=RT[:n])[1]) > abs(xs[1]): hi = mid
        else: lo = mid
    s = stat_r(r, lev=lo, rate=RT[:n])
    print(f"{(nm.split('(')[0].strip() + f' w={w:.1f}'):<46}{lo:>6.2f}{s[0]:>7.1f}%{s[1]:>7.1f}%{s[2]:>7.2f}{s[0]-xs[0]:>+8.1f}")

print("\n" + "=" * 100)
print("STEP 5 — WALK-FORWARD the equal-vol levered blend (rolling 6-month windows, FULL history)")
print("=" * 100)
starts = []; y, mn = 2017, 1
while (y, mn) <= (2026, 1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn += 6
    if mn > 12: y, mn = y + 1, mn - 12
dp = lambda s: min(bisect.bisect_left(dates, s), ND - 1)
nm0 = list(SLEEVES)[0]
w0 = best[nm0][0]
print(f"using {nm0}  w={w0:.1f}, leverage re-solved per window on TRAILING data only (no lookahead)")
print(f"{'window':<12}{'blend(lev)':>12}{'XLK':>10}{'diff':>9}{'lev':>7}")
wn = 0; tot = 0; sb = []; sx = []
for s in starts:
    a = dp(s); nx = f"{int(s[:4]) + (1 if s[5:7] == '07' else 0)}-{'01' if s[5:7] == '07' else '07'}-01"
    b = min(dp(nx), ND - 1)
    if b - a < 60 or a < IS0 + 260: continue
    tr0 = max(a - 252, IS0)
    rs_t = rets(curve(SLEEVES[nm0], tr0, a)); rx_t = rets(bh('XLK', tr0, a))
    n_t = min(len(rs_t), len(rx_t))
    lev = rx_t[:n_t].std() / max(((1 - w0) * rx_t[:n_t] + w0 * rs_t[:n_t]).std(), 1e-9)
    lev = float(np.clip(lev, 0.5, 3.0))
    rs = rets(curve(SLEEVES[nm0], a, b)); rx = rets(bh('XLK', a, b))
    n = min(len(rs), len(rx))
    r = (1 - w0) * rx[:n] + w0 * rs[:n]
    rr = lev * r - (lev - 1) * 0.05 / 252 if lev > 1 else lev * r + (1 - lev) * 0.05 / 252
    rb_ = np.prod(1 + rr) - 1; rxx = np.prod(1 + rx[:n]) - 1
    sb.append(rb_); sx.append(rxx); tot += 1; wn += rb_ > rxx
    print(f"{s:<12}{rb_*100:>+11.1f}%{rxx*100:>+9.1f}%{(rb_-rxx)*100:>+8.1f}%{lev:>7.2f}")
print('-' * 52)
print(f"{'compounded':<12}{(np.prod(1+np.array(sb))-1)*100:>+11.1f}%{(np.prod(1+np.array(sx))-1)*100:>+9.1f}%")
print(f"{'median':<12}{np.median(sb)*100:>+11.1f}%{np.median(sx)*100:>+9.1f}%")
print(f"{'worst':<12}{min(sb)*100:>+11.1f}%{min(sx)*100:>+9.1f}%")
print(f"{'beat XLK':<12}{wn:>11}/{tot}")
