"""MIX9 — trade statistics + the strongest available backtest proof.

PART 1: turnover — trades/month, average holding days, switches/year.
PART 2: ROLLING walk-forward. Instead of one regime->strategy map fitted on
        2016-2022 and applied forever, the map is RE-DERIVED at every window
        using ONLY data before that window, then applied blind to the next 6
        months. This is the honest "prove it now" test: no map ever sees the
        period it is judged on.
"""
exec(open('_strategy_mixing.py').read().split("RULES = [")[0])
import numpy as np, bisect
from collections import defaultdict, Counter

# ---------------- PART 1: turnover / holding period ----------------
print("\n" + "=" * 78)
print("PART 1 — MIX9 TRADE STATISTICS")
print("=" * 78)

# strategy-level switches
switches = sum(1 for t in range(1, T) if REGMAP.get(regs[t]) != REGMAP.get(regs[t-1]))
yrs = T / 252
print(f"strategy switches: {switches} over {yrs:.1f} yrs = {switches/yrs:.0f}/yr ({switches/yrs/12:.1f}/month)")

# underlying stock turnover per strategy (monthly rotations rebalance 10 names)
def rot_turnover(sel, top_n=10):
    prev = []; changes = []; holds = defaultdict(int); entry_month = {}
    mlist = sorted(mset)
    for mi, t in enumerate(mlist):
        j = IS0 + t
        new = sel(j, top_n)
        ch = len(set(new) ^ set(prev)) / 2  # pairs swapped
        changes.append(ch)
        for c in new:
            if c not in prev: entry_month[c] = mi
        for c in prev:
            if c not in new and c in entry_month:
                holds[c] = holds.get(c, 0) + (mi - entry_month[c])
        prev = new
    hold_months = [v for v in holds.values() if v > 0]
    return np.mean(changes), (np.mean(hold_months) if hold_months else 0)

for nm, sel in [('TREND10', _trend_sel), ('RELSTR10', mk_relstr(99, 'XLK')),
                ('LeadSector', _leadsec_sel)]:
    ch, hm = rot_turnover(sel)
    print(f"  {nm:<12} {ch:.1f} name-swaps/month of 10  ->  ~{ch*2:.0f} trades/month, "
          f"avg hold {hm:.1f} months ({hm*21:.0f} trading days)")
print("  MR-dips-F90  fixed 90-day hold, <=5 slots -> ~1.7 trades/month when active")
print("  MOM-brk-F90  fixed 90-day hold, <=5 slots -> ~1.7 trades/month when active")
print(f"\n  MIX9 TOTAL (70% sleeve): roughly 6-14 stock trades/month + ~{switches/yrs/12:.1f} strategy switches")
print( "  average holding period: 1-3 months for rotations, 90 trading days for the fixed-timer sleeves")

# ---------------- PART 2: rolling walk-forward re-derivation ----------------
print("\n" + "=" * 78)
print("PART 2 — ROLLING WALK-FORWARD (map re-derived each window, never sees its test period)")
print("=" * 78)

starts = []; y, mn = 2019, 1          # need >=2.5y of history to derive the first map
while (y, mn) <= (2026, 1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn += 6
    if mn > 12: y, mn = y + 1, mn - 12
def dpos(s): return min(bisect.bisect_left(dates, s), ND - 1) - IS0

def derive_map(upto_t, min_days=20):
    acc = defaultdict(lambda: defaultdict(list))
    for t in range(upto_t):
        rg = regs[t]
        for si, k in enumerate(names):
            acc[rg][k].append(Rmat[si, t])
    m = {}
    for rg, dd in acc.items():
        cand = {k: np.mean(v) for k, v in dd.items() if len(v) >= min_days}
        if cand: m[rg] = max(cand, key=cand.get)
    return m

def run_window(a, b, m, core_w=0.30, dd_stop=0.15, fallback='TREND10'):
    eq = 1.0; peaks = {k: 1.0 for k in names}; cur = {k: 1.0 for k in names}
    for t in range(a, b):
        for i, k in enumerate(names):
            cur[k] *= (1 + Rmat[i, t]); peaks[k] = max(peaks[k], cur[k])
        k = m.get(regs[t], fallback); si = names.index(k); ra = Rmat[si, t]
        if dd_stop and cur[k] < peaks[k] * (1 - dd_stop): ra = rx[t]
        eq *= (1 + (1 - core_w) * ra + core_w * rx[t])
    return eq - 1

print(f"{'window':<12}{'MIX9(WF map)':>14}{'MIX9(fixed map)':>17}{'XLK':>9}{'map source':>26}")
wf, fx, bx = [], [], []
for s in starts:
    a = dpos(s)
    nxt = f"{int(s[:4]) + (1 if s[5:7]=='07' else 0)}-{'01' if s[5:7]=='07' else '07'}-01"
    b = dpos(nxt)
    if b - a < 60 or a <= 0: continue
    m = derive_map(a)                      # ONLY data before this window
    r_wf = run_window(a, b, m)
    r_fx = run_window(a, b, REGMAP)        # the original fixed IS map
    r_x = XLK[b] / XLK[a] - 1
    wf.append(r_wf); fx.append(r_fx); bx.append(r_x)
    heal = m.get('HEALTHY', '-')[:12]
    print(f"{s:<12}{r_wf*100:>+13.1f}%{r_fx*100:>+16.1f}%{r_x*100:>+8.1f}%   HEALTHY->{heal}")
wf, fx, bx = map(np.array, (wf, fx, bx))
print('-' * 78)
print(f"{'compounded':<12}{(np.prod(1+wf)-1)*100:>+13.1f}%{(np.prod(1+fx)-1)*100:>+16.1f}%{(np.prod(1+bx)-1)*100:>+8.1f}%")
print(f"{'median':<12}{np.median(wf)*100:>+13.1f}%{np.median(fx)*100:>+16.1f}%{np.median(bx)*100:>+8.1f}%")
print(f"{'worst':<12}{wf.min()*100:>+13.1f}%{fx.min()*100:>+16.1f}%{bx.min()*100:>+8.1f}%")
print(f"{'beat XLK':<12}{(wf>bx).sum():>13}/{len(wf)}{(fx>bx).sum():>16}/{len(fx)}")
