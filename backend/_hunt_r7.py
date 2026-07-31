"""RESEARCH CYCLE — round 7: FULLY-HONEST WALK-FORWARD. The definitive test.

Round 6 looked strong: XLK + a zero-correlation multi-asset sleeve at w=0.6 gave
OOS Sharpe 1.91 vs XLK 1.37, and 12/18 rolling windows.

But TWO parameters were chosen with OOS knowledge:
    - the blend weight w=0.6 was picked by maximising OOS Sharpe
    - the sleeve config was picked on IS, but the *family* was chosen after
      seeing round 5's OOS table
Both must go. This round rebuilds the whole thing so that at every point in time,
EVERY decision uses only data strictly before that point:

    at each window start t:
        1. score a FIXED candidate family of sleeve configs on trailing 504d ONLY
        2. pick the best sleeve by trailing Sharpe
        3. pick the blend weight w by maximising trailing Sharpe of (1-w)*XLK + w*sleeve
        4. set leverage = trailing XLK vol / trailing blend vol
        5. apply blind for the next 6 months
        6. repeat

Nothing about the future is used at any step. If this still beats XLK, the edge is
real. If it does not, round 6 was selection bias and the honest answer is "no".

Also run: a RANDOM-SLEEVE control (same machinery, random config each window) —
it must lose, otherwise the machinery itself is manufacturing the result.
"""
exec(open('_hunt_r5.py').read().split('# ── benchmarks ──')[0])
import numpy as np, math, bisect, itertools

print("\n" + "=" * 104)
print("ROUND 7 — FULLY-HONEST WALK-FORWARD (every parameter from trailing data only)")
print("=" * 104)

# Candidate family, fixed in advance. Deliberately small and spread across the
# structural choices round 5 showed matter (universe, signal, k, defensive).
FAMILY = [dict(uset=u, sig=s, lb=252, k=k, wt=w, dfns=d, rb='M')
          for u, s, k, w, d in itertools.product(
              ['factors', 'multi-asset', 'equity+bond', 'global-equity'],
              ['mom', 'sharpe', 'blend'], [3, 5], ['eq', 'ivol'], ['GLD', 'IEF'])]
print(f"candidate sleeve family: {len(FAMILY)} configs (fixed in advance, no OOS input)")

WS = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
CACHE = {}


def sleeve_r(spec, a, b):
    key = (tuple(sorted(spec.items())), a, b)
    if key not in CACHE:
        c = build(spec['uset'], spec['sig'], spec['lb'], spec['k'], spec['wt'],
                  spec['dfns'], spec['rb'], s0=a, s1=b)
        CACHE[key] = np.diff(c) / c[:-1]
    return CACHE[key]


def xlk_r(a, b):
    x = np.array([P[i, IX['XLK']] for i in range(a, b + 1)])
    return np.diff(x) / x[:-1]


def sharpe(r):
    return (r.mean() / (r.std() + 1e-12)) * math.sqrt(252) if len(r) > 20 else -9


starts = []; y, mn = 2018, 1
while (y, mn) <= (2026, 1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn += 6
    if mn > 12: y, mn = y + 1, mn - 12
dp = lambda s: min(bisect.bisect_left(dates, s), ND - 1)
RATE_D = 0.05 / 252
rng = np.random.default_rng(20260731)


def run_wf(mode):
    """mode: 'honest' = trailing-selected sleeve+w+lev; 'random' = random sleeve control."""
    rows = []
    for s in starts:
        a = dp(s)
        nx = f"{int(s[:4]) + (1 if s[5:7] == '07' else 0)}-{'01' if s[5:7] == '07' else '07'}-01"
        b = min(dp(nx), ND - 1)
        tr0 = a - 504
        if b - a < 60 or tr0 < 30: continue
        xt = xlk_r(tr0, a)
        # 1-2. pick sleeve on TRAILING data only
        if mode == 'random':
            spec = FAMILY[rng.integers(len(FAMILY))]
        else:
            best = None
            for sp in FAMILY:
                sh = sharpe(sleeve_r(sp, tr0, a))
                if best is None or sh > best[0]: best = (sh, sp)
            spec = best[1]
        st_ = sleeve_r(spec, tr0, a)
        n = min(len(st_), len(xt))
        # 3. pick w on TRAILING data only
        bw, bs = 0.0, -9
        for w in WS:
            sh = sharpe((1 - w) * xt[:n] + w * st_[:n])
            if sh > bs: bs, bw = sh, w
        # 4. leverage from TRAILING vols only
        bt = (1 - bw) * xt[:n] + bw * st_[:n]
        lev = float(np.clip(xt[:n].std() / max(bt.std(), 1e-9), 0.5, 2.5))
        # 5. apply BLIND
        sf = sleeve_r(spec, a, b); xf = xlk_r(a, b)
        m = min(len(sf), len(xf))
        rf = (1 - bw) * xf[:m] + bw * sf[:m]
        rl = lev * rf - (lev - 1) * RATE_D if lev > 1 else lev * rf + (1 - lev) * RATE_D
        rows.append(dict(win=s, blend=np.prod(1 + rl) - 1, xlk=np.prod(1 + xf[:m]) - 1,
                         w=bw, lev=lev, spec=f"{spec['uset'][:9]}/{spec['sig'][:4]}/k{spec['k']}/{spec['dfns']}",
                         rl=rl, xf=xf[:m]))
    return rows


for mode, title in [('honest', 'HONEST WALK-FORWARD'), ('random', 'RANDOM-SLEEVE CONTROL (must lose)')]:
    rows = run_wf(mode)
    print("\n" + "=" * 104); print(title); print("=" * 104)
    print(f"{'window':<11}{'blend':>10}{'XLK':>9}{'diff':>9}{'w':>6}{'lev':>6}  sleeve chosen from trailing data")
    for r in rows:
        print(f"{r['win']:<11}{r['blend']*100:>+9.1f}%{r['xlk']*100:>+8.1f}%{(r['blend']-r['xlk'])*100:>+8.1f}%"
              f"{r['w']:>6.1f}{r['lev']:>6.2f}  {r['spec']}")
    bl = np.array([r['blend'] for r in rows]); xk = np.array([r['xlk'] for r in rows])
    allr = np.concatenate([r['rl'] for r in rows]); allx = np.concatenate([r['xf'] for r in rows])
    eqb = np.cumprod(1 + allr); eqx = np.cumprod(1 + allx)
    mdb = ((eqb / np.maximum.accumulate(eqb)) - 1).min() * 100
    mdx = ((eqx / np.maximum.accumulate(eqx)) - 1).min() * 100
    print('-' * 104)
    print(f"{'compounded':<11}{(np.prod(1+bl)-1)*100:>+9.1f}%{(np.prod(1+xk)-1)*100:>+8.1f}%")
    print(f"{'median':<11}{np.median(bl)*100:>+9.1f}%{np.median(xk)*100:>+8.1f}%")
    print(f"{'worst':<11}{bl.min()*100:>+9.1f}%{xk.min()*100:>+8.1f}%")
    print(f"{'beat XLK':<11}{(bl>xk).sum():>9}/{len(bl)}")
    print(f"{'CAGR':<11}{((np.prod(1+bl))**(252/len(allr))-1)*100:>9.1f}%{((np.prod(1+xk))**(252/len(allx))-1)*100:>8.1f}%")
    print(f"{'MDD (stitched)':<11}{mdb:>6.1f}%{mdx:>8.1f}%")
    print(f"{'Sharpe':<11}{sharpe(allr):>10.2f}{sharpe(allx):>9.2f}")
    if mode == 'honest':
        HON = (allr, allx, bl, xk)
        from collections import Counter
        print(f"\n  sleeve stability: {Counter(r['spec'] for r in rows).most_common()}")
        print(f"  w chosen:  {Counter(r['w'] for r in rows).most_common()}")

# ── DSR on the honest walk-forward stream ──
print("\n" + "=" * 104); print("DSR on the fully-honest walk-forward return stream"); print("=" * 104)
DNS = {}; exec(open('_dsr.py').read().split("if __name__")[0], DNS); dsr = DNS['dsr']
allr, allx, bl, xk = HON
print(f"{'series':<26}{'Sharpe':>8}{'N=1':>8}{'N=40':>8}{'N=150':>8}  verdict")
for nm, r in [('honest WF blend', allr), ('XLK', allx)]:
    sh = sharpe(r)
    sk = float(((r - r.mean()) ** 3).mean() / (r.std() ** 3 + 1e-12))
    ku = float(((r - r.mean()) ** 4).mean() / (r.std() ** 4 + 1e-12))
    d1, _ = dsr(sh, len(r), 1, sk, ku); d40, _ = dsr(sh, len(r), 40, sk, ku); d150, _ = dsr(sh, len(r), 150, sk, ku)
    v = "PASS@150" if d150 >= .95 else ("PASS@40" if d40 >= .95 else ("PASS@1" if d1 >= .95 else "FAIL"))
    print(f"{nm:<26}{sh:>8.2f}{d1:>8.3f}{d40:>8.3f}{d150:>8.3f}  {v}")

# paired test on window differences
d = bl - xk
t = d.mean() / (d.std(ddof=1) / math.sqrt(len(d))) if len(d) > 2 else 0
print(f"\npaired t on {len(d)} window differences: mean {d.mean()*100:+.2f}pp, t = {t:+.2f}"
      f"  ({'significant' if abs(t) > 2 else 'NOT significant'} at |t|>2)")
