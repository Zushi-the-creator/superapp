"""Is MIX9 a one-sector bet? Measure it, don't assume.

Two things could make it tech-concentrated:
  1. the 30% core IS XLK (100% tech by construction)
  2. RELSTR10's filter is literally "beats XLK on 252d AND 63d" — a tech hurdle,
     which in a tech-led decade selects tech

Measured here with the point-in-time sector map (_sectors_at: trailing 504d
max-correlation to the 10 SPDRs, cached per quarter — no lookahead).

Then re-runs MIX9 with the core swapped to SPY and to an equal-weight 10-sector
basket, on the CORRECTED data, to separate "the core is tech" from
"the strategy only works on tech".
"""
exec(open('_strategy_mixing.py').read().split("RULES = [")[0])
import numpy as np, math
from collections import Counter, defaultdict

Y0 = next(i for i, d in enumerate(dates) if d >= '2026-01-02'); Y_T = Y0 - IS0
SEL = {'TREND10': _trend_sel, 'RELSTR10': mk_relstr(99, 'XLK'),
       'cap2+guard': mk_relstr(2, 'SPY'), 'LeadSector': _leadsec_sel, 'LC 12-1': lc121}

print("=" * 100)
print("PART 1 — SECTOR MIX OF THE 70% STOCK SLEEVE (point-in-time sector map)")
print("=" * 100)
mlist = sorted(mset)
per_year = defaultdict(Counter)
for t in mlist:
    j = IS0 + t
    if j < 504: continue
    k = REGMAP.get(regs[t], 'TREND10')          # which strategy is active that month
    if k not in SEL: continue                    # MR/MOM sleeves handled separately
    sec = _sectors_at(j)
    for c in SEL[k](j, 10):
        per_year[dates[j][:4]][sec.get(c, '?')] += 1
print(f"{'year':<7}{'top sectors held by the active sleeve (share of slot-months)':<80}{'tech%':>7}")
for y in sorted(per_year):
    cnt = per_year[y]; tot = sum(cnt.values()) or 1
    top = ", ".join(f"{s} {v/tot*100:.0f}%" for s, v in cnt.most_common(5))
    print(f"{y:<7}{top:<80}{cnt.get('XLK',0)/tot*100:>6.0f}%")
allc = Counter()
for y in per_year: allc.update(per_year[y])
tot = sum(allc.values()) or 1
print(f"\nWHOLE PERIOD sleeve mix: " + ", ".join(f"{s} {v/tot*100:.0f}%" for s, v in allc.most_common()))
sleeve_tech = allc.get('XLK', 0) / tot
hhi = sum((v/tot)**2 for v in allc.values())
print(f"sleeve tech share {sleeve_tech*100:.0f}%   HHI {hhi:.3f} "
      f"(0.10 = perfectly spread over 10 sectors, 1.00 = single sector)")

print("\n" + "=" * 100)
print("PART 2 — EFFECTIVE TOTAL TECH EXPOSURE (70% sleeve + 30% XLK core)")
print("=" * 100)
eff = 0.30 * 1.0 + 0.70 * sleeve_tech
print(f"  30% core  = XLK           -> 30.0pp tech")
print(f"  70% sleeve at {sleeve_tech*100:.0f}% tech   -> {0.70*sleeve_tech*100:.1f}pp tech")
print(f"  EFFECTIVE TECH WEIGHT      = {eff*100:.1f}%")
print(f"  ...vs XLK buy-hold         = 100.0%")
print(f"  ...vs SPY (tech weight)    ~  32-34%")
print(f"\n  non-tech weight in MIX9    = {(1-eff)*100:.1f}%  (spread over "
      f"{len([s for s in allc if s!='XLK'])} other sectors)")

print("\n" + "=" * 100)
print("PART 3 — SWAP THE CORE. Does MIX9 need tech, or just a core?")
print("=" * 100)
SPD = [s for s in ['XLK','XLV','XLF','XLE','XLI','XLP','XLY','XLU','XLB','XLRE'] if s in C.columns]
spi = [C.columns.get_loc(s) for s in SPD]
ew = np.zeros(T)
for t in range(T):
    rs = [Cf[IS0+t+1, k]/Cf[IS0+t, k]-1 for k in spi
          if np.isfinite(Cf[IS0+t, k]) and np.isfinite(Cf[IS0+t+1, k]) and Cf[IS0+t, k] > 0]
    ew[t] = np.mean(rs) if rs else 0.0
r_spy = np.diff(SPY)/SPY[:-1]

def mix9(core_r, core_w=0.30, dd_stop=0.15):
    eq = 1.0; out = [1.0]; peaks = {k: 1.0 for k in names}; cur = {k: 1.0 for k in names}
    for t in range(T):
        for i, k in enumerate(names):
            cur[k] *= (1+Rmat[i, t]); peaks[k] = max(peaks[k], cur[k])
        k = REGMAP.get(regs[t], 'TREND10'); si = names.index(k); ra = Rmat[si, t]
        if dd_stop and cur[k] < peaks[k]*(1-dd_stop): ra = core_r[t]
        eq *= (1 + (1-core_w)*ra + core_w*core_r[t]); out.append(eq)
    return np.array(out)

def sl(c, a):
    x = np.asarray(c, float)[a:]; x = x/x[0]
    r = np.diff(x)/x[:-1]; pk = np.maximum.accumulate(x)
    return (x[-1]-1)*100, (x[-1]**(252/len(r))-1)*100, (x/pk-1).min()*100, (r.mean()/(r.std()+1e-12))*math.sqrt(252)

CORES = {'XLK  (tech only)': rx, 'SPY  (broad market)': r_spy, 'EW10 (all 10 sectors)': ew}
print(f"{'MIX9 core':<24}{'IS CAGR':>9}{'OOS CAGR':>10}{'OOS MDD':>9}{'OOS Shrp':>10}{'YTD 2026':>10}{'10y CAGR':>10}{'10y MDD':>9}")
for nm, cr in CORES.items():
    c = mix9(cr)
    _, ic, _, _ = sl(c[:IS_T+1], 0)
    _, oc, om, osh = sl(c, IS_T)
    yt, _, _, _ = sl(c, Y_T)
    _, fc, fm, _ = sl(c, 0)
    print(f"{nm:<24}{ic:>8.1f}%{oc:>9.1f}%{om:>8.1f}%{osh:>10.2f}{yt:>+9.1f}%{fc:>9.1f}%{fm:>8.1f}%")
for nm, arr in (('XLK buy-hold', XLK), ('SPY buy-hold', SPY)):
    _, ic, _, _ = sl(arr[:IS_T+1], 0); _, oc, om, osh = sl(arr, IS_T)
    yt, _, _, _ = sl(arr, Y_T); _, fc, fm, _ = sl(arr, 0)
    print(f"{nm:<24}{ic:>8.1f}%{oc:>9.1f}%{om:>8.1f}%{osh:>10.2f}{yt:>+9.1f}%{fc:>9.1f}%{fm:>8.1f}%")

print("\n" + "=" * 100)
print("PART 4 — CORRELATION OF THE SLEEVE TO XLK (is the 70% just tech in disguise?)")
print("=" * 100)
sleeve = np.array([Rmat[names.index(REGMAP.get(regs[t], 'TREND10')), t] for t in range(T)])
for lbl, a, b in [('IS 2016-22', 0, IS_T), ('OOS 2023+', IS_T, T), ('2026 YTD', Y_T, T)]:
    cxl = np.corrcoef(sleeve[a:b], rx[a:b])[0, 1]
    csp = np.corrcoef(sleeve[a:b], r_spy[a:b])[0, 1]
    print(f"  {lbl:<12} corr(sleeve, XLK) = {cxl:.2f}    corr(sleeve, SPY) = {csp:.2f}")
