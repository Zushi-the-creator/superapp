"""RESEARCH CYCLE — round 4: STRESS-TEST the Tier A winner.

Candidate: XLK core + 40% satellite in a 2x-levered XLK sleeve, sleeve invested
only while XLK > SMA200, daily-rebalanced leverage (= how a 2x ETF actually works,
vol decay included), financing charged on the levered dollar, 0.95% expense ratio.

Why it got this far (round 3):
    OOS CAGR 38.9% vs XLK 34.3%   |  OOS MDD -24.8% vs XLK -25.8% (BETTER)
    IS  CAGR 23.0% vs XLK 19.0%   |  beats XLK in 13/19 rolling windows
    Tier A: universe fixed in advance, survivorship inflation impossible.

Round 4 tries to break it:
  X1  financing-rate sensitivity   (what if rates go to 8%?)
  X2  expense-ratio sensitivity
  X3  execution lag / whipsaw      (signal->trade delay, switch frequency)
  X4  per-year full history
  X5  real-instrument reality      (does a tradeable 2x XLK ETF exist and trade?)
  X6  sub-period stability         (does it beat XLK in BOTH halves?)
  X7  crash behaviour              (2018Q4, 2020 covid, 2022 bear)
"""
exec(open('_master_harness3.py').read().split("STRATS=[")[0])
import numpy as np, math, bisect

IS0 = next(i for i, d in enumerate(dates) if d >= '2016-06-01')
OOS0 = next(i for i, d in enumerate(dates) if d >= '2023-01-03')
XLi = C.columns.get_loc('XLK')
A = Cf[:, XLi]
S200 = pd.Series(A).rolling(200, min_periods=180).mean().values


def sat(s0, s1=None, sat_frac=0.40, mult=2, er=0.0095, rate_add=0.0, lag=1, sma=S200):
    """lag=1 -> signal from bar i-1, traded on bar i (no lookahead)."""
    end = s1 if s1 is not None else ND - 1
    eq = 1.0; c = [1.0]; inp = True; sw = 0
    for i in range(s0, end + 1):
        dg = (er + (mult - 1) * (RATEA[i] + rate_add)) / 252
        a, b = A[i - 1], A[i]
        r = (b / a - 1) if (np.isfinite(a) and np.isfinite(b) and a > 0) else 0.0
        k = max(i - lag, 0)
        w = bool(np.isfinite(sma[k]) and A[k] > sma[k])
        if w != inp:
            eq *= 1 - sat_frac * (EFEE + SLIP); inp = w; sw += 1
        eq *= (1 + (1 - sat_frac) * r + sat_frac * ((mult * r - dg) if inp else 0.0))
        c.append(eq)
    return np.array(c), sw


def xlk(s0, s1=None):
    end = s1 if s1 is not None else ND - 1
    return np.array([A[i] / A[s0] for i in range(s0, end + 1)])


def st(c):
    c = np.asarray(c, float); c = c / c[0]
    r = np.diff(c) / c[:-1]; pk = np.maximum.accumulate(c)
    cg = (c[-1] ** (252 / len(r)) - 1) * 100
    md = (c / pk - 1).min() * 100
    return cg, md, (r.mean() / (r.std() + 1e-12)) * math.sqrt(252), cg / abs(md)


def line(lbl, c, ref=None):
    cg, md, sh, mar = st(c)
    d = f"{cg - st(ref)[0]:>+8.1f}" if ref is not None else "        "
    print(f"  {lbl:<40}{cg:>8.1f}%{md:>8.1f}%{sh:>7.2f}{mar:>7.2f}{d}")


H = f"  {'variant':<40}{'CAGR':>8}{'MDD':>8}{'Shrp':>7}{'MAR':>7}{'vsXLK':>9}"
XO = xlk(OOS0)
print("=" * 88); print("BASELINE (OOS 2023-01 -> now)"); print("=" * 88); print(H)
line('XLK buy-hold', XO)
line('CANDIDATE: XLK +40% 2x-trend', sat(OOS0)[0], XO)

print("\n" + "=" * 88)
print("X1 — FINANCING-RATE SENSITIVITY (extra bps ON TOP of the modelled path)")
print("=" * 88); print(H)
for add in (0.0, 0.01, 0.02, 0.03, 0.05):
    line(f'+{int(add*100)}pp financing', sat(OOS0, rate_add=add)[0], XO)

print("\n" + "=" * 88); print("X2 — EXPENSE-RATIO SENSITIVITY"); print("=" * 88); print(H)
for er in (0.0095, 0.015, 0.020, 0.030):
    line(f'expense {er*100:.2f}%/yr', sat(OOS0, er=er)[0], XO)

print("\n" + "=" * 88)
print("X3 — EXECUTION LAG & WHIPSAW (lag = bars between signal and fill)")
print("=" * 88); print(H)
for lg in (1, 2, 3, 5):
    c, sw = sat(OOS0, lag=lg)
    line(f'lag {lg} bar(s)  [{sw} switches OOS]', c, XO)
cF, swF = sat(IS0)
print(f"\n  full-period switches: {swF} over {(ND-IS0)/252:.1f} yrs = {swF/((ND-IS0)/252):.1f}/yr")

print("\n" + "=" * 88); print("X4 — PER-YEAR (full history)"); print("=" * 88)
dpos = lambda s: min(bisect.bisect_left(dates, s), ND - 1)
print(f"{'year':<7}{'candidate':>12}{'XLK':>10}{'diff':>9}{'cand MDD':>10}{'XLK MDD':>9}")
wins = 0; tot = 0
for y in range(2017, 2027):
    a = dpos(f'{y}-01-01'); b = min(dpos(f'{y+1}-01-01'), ND - 1)
    if b - a < 60: continue
    cc = sat(a, b)[0]; xx = xlk(a, b)
    rc = (cc[-1] - 1) * 100; rx = (xx[-1] / xx[0] - 1) * 100
    tot += 1; wins += rc > rx
    mc = st(cc)[1]; mx = st(xx)[1]
    print(f"{y}{'*' if y == 2026 else ' '}   {rc:>+11.1f}%{rx:>+9.1f}%{rc-rx:>+8.1f}%{mc:>9.1f}%{mx:>8.1f}%")
print(f"\n  beats XLK in {wins}/{tot} calendar years")

print("\n" + "=" * 88); print("X6 — SUB-PERIOD STABILITY (must win in BOTH halves)"); print("=" * 88); print(H)
MID = next(i for i, d in enumerate(dates) if d >= '2021-01-04')
for nm, a, b in [('first half 2016-06..2020-12', IS0, MID),
                 ('second half 2021-01..now', MID, ND - 1),
                 ('IS 2016-06..2022-12', IS0, OOS0),
                 ('OOS 2023-01..now', OOS0, ND - 1)]:
    print(f"  -- {nm}")
    line('    XLK', xlk(a, b))
    line('    candidate', sat(a, b)[0], xlk(a, b))

print("\n" + "=" * 88); print("X7 — CRASH BEHAVIOUR"); print("=" * 88)
print(f"{'episode':<26}{'candidate':>12}{'XLK':>10}{'diff':>9}")
for nm, s, e in [('2018 Q4 selloff', '2018-10-01', '2018-12-26'),
                 ('2020 COVID crash', '2020-02-19', '2020-03-23'),
                 ('2020 recovery', '2020-03-24', '2020-09-01'),
                 ('2022 bear (full year)', '2022-01-03', '2022-12-30'),
                 ('2025 drawdown', '2025-02-19', '2025-04-30')]:
    a, b = dpos(s), min(dpos(e), ND - 1)
    if b <= a: continue
    rc = (sat(a, b)[0][-1] - 1) * 100
    xx = xlk(a, b); rx = (xx[-1] / xx[0] - 1) * 100
    print(f"{nm:<26}{rc:>+11.1f}%{rx:>+9.1f}%{rc-rx:>+8.1f}%")

print("\n" + "=" * 88); print("X5 — REAL-INSTRUMENT CHECK (is the sleeve actually tradeable?)"); print("=" * 88)
import sqlite3
con = sqlite3.connect('data/stock_cache.db')
for tk, desc in [('ROM', '2x XLK (ProShares Ultra Technology)'),
                 ('QLD', '2x QQQ (ProShares Ultra QQQ)'),
                 ('TQQQ', '3x QQQ (ProShares UltraPro QQQ)'),
                 ('USD', '2x semis'), ('XLK', 'underlying')]:
    q = con.execute("SELECT COUNT(*), MIN(date), MAX(date), AVG(close*volume) "
                    "FROM daily_prices WHERE ticker=? AND date>='2025-01-01'", (tk,)).fetchone()
    if q and q[0]:
        print(f"  {tk:<6}{desc:<40}{q[0]:>5} bars {q[1]}..{q[2]}  avg $vol ${q[3]/1e6:,.1f}M")
    else:
        print(f"  {tk:<6}{desc:<40}NOT IN CACHE — cannot verify tradeability")
