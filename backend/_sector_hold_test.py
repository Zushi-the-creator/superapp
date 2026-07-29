"""Two tests under the canonical harness:
 A) HOLD LENGTH — does the Fixed42/60 finding survive when the exit is HYBRID?
    (fixed timer vs hybrid trail at caps 21/30/42/60/90)
 B) SECTORS — classify universe by max correlation to SPDR sector ETFs, then
    test sector filters (exclude/only) and per-sector MR performance."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
IS=next(i for i,d in enumerate(dates) if d>='2016-06-01')
OOS=next(i for i,d in enumerate(dates) if d>='2023-01-03')
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
def m2(c):
    pk=np.maximum.accumulate(c);return c[-1]**(252/max(len(c)-1,1))-1,(c/pk-1).min()
NP_=lambda d: R[d] not in {'DANGER','WEAK','CRISIS'}
def build_hyb(minh,trail,arm,cap):
    key=f'h{minh}_{int(trail*100)}_{int(arm*100)}_{cap}'
    if key in EX: return key
    EX[key]={}
    for (k,i),cols in [((k,i),v) for (k,i),v in sig.items() if k=='mr']:
        for col in cols:
            e=i+1
            if e+1>=ND: continue
            ep=Ov[e,col]
            if not np.isfinite(ep) or ep<=0: continue
            w=Cf[e:min(e+cap+1,ND),col]; off=cap; peak=ep
            for j in range(1,len(w)):
                peak=max(peak,w[j])
                if j>=minh and (w[j]/ep-1)>arm and w[j]<peak*(1-trail):
                    off=j;break
            EX[key][(i,col)]=off
    return key
def run(exitspec,slots=8,mask=None):
    global NSLOT; old=NSLOT; NSLOT=slots
    if mask is not None:
        saved=MRS.copy(); MRS[:, ~mask]= -1
    pol=lambda d:(('mr',MRS,exitspec) if NP_(d) else None)
    ci=stock_sim_cash(pol,IS)[:OOS-IS]; co=stock_sim_cash(pol,OOS); cy=stock_sim_cash(pol,Y0)
    if mask is not None: MRS[:]=saved
    NSLOT=old
    ai,_=m2(ci); ao,mo=m2(co)
    return ai*100,ao*100,mo*100,(cy[-1]/cy[0]-1)*100
print("=== A) HOLD LENGTH: fixed timer vs hybrid-trail, at 8 slots ===")
print(f"{'exit':<34}{'IS':>8}{'OOS':>8}{'OOSmdd':>8}{'YTD':>9}")
for cap in (21,30,42,60,90):
    r=run(cap)   # pure fixed timer
    print(f"{f'Fixed{cap}d (no trail)':<34}{r[0]:>7.1f}%{r[1]:>7.1f}%{r[2]:>7.1f}%{r[3]:>+8.1f}%")
for cap in (21,30,42,60,90):
    k=build_hyb(7,0.03,0.05,cap)
    r=run(k)
    print(f"{f'Hybrid trail, cap {cap}d':<34}{r[0]:>7.1f}%{r[1]:>7.1f}%{r[2]:>7.1f}%{r[3]:>+8.1f}%")
# ---------- sectors ----------
SPDR={'XLK':'Tech','XLV':'Health','XLF':'Financials','XLE':'Energy','XLI':'Industrials',
      'XLP':'Staples','XLY':'Discretionary','XLU':'Utilities','XLB':'Materials','XLRE':'RealEstate'}
avail=[t for t in SPDR if t in C.columns]
rets=C.pct_change(fill_method=None)
win=rets.iloc[-756:]  # ~3yr correlation window
etf=win[avail]
sec_of={}
for col_i,tk in enumerate(C.columns):
    if tk in SPDR: sec_of[col_i]=SPDR[tk]; continue
    s=win[tk]
    if s.notna().sum()<200: continue
    cors={e:s.corr(etf[e]) for e in avail}
    best=max(cors,key=lambda e: (cors[e] if cors[e]==cors[e] else -9))
    if cors[best]==cors[best] and cors[best]>0.25: sec_of[col_i]=SPDR[best]
from collections import Counter
print(f"\n=== B) SECTORS: classified {len(sec_of)} tickers by 3y max-corr to SPDRs ===")
print(dict(Counter(sec_of.values()).most_common()))
# per-sector MR trade stats (fwd 21d from signal, next-open)
e1=np.full_like(Ov,np.nan); x1=np.full_like(Cv,np.nan)
e1[:-1]=Ov[1:]; x1[:ND-1-21]=Cv[1+21:]
F21=(x1/e1-1)-2*(FEE+SLIP)
rows={}
gr,gc=np.where(mrg)
for i,c in zip(gr,gc):
    if i<IS or c not in sec_of: continue
    v=F21[i,c]
    if np.isfinite(v): rows.setdefault(sec_of[c],[]).append(v*100)
print(f"\n{'sector':<14}{'n':>6}{'avg21d':>9}{'WR':>7}")
for s,v in sorted(rows.items(),key=lambda kv:-np.mean(kv[1])):
    print(f"{s:<14}{len(v):>6}{np.mean(v):>+8.2f}%{(np.array(v)>0).mean()*100:>6.0f}%")
# sector filter tests on the winning config
k8=build_hyb(7,0.03,0.05,21)
base=run(k8)
print(f"\n=== sector filters on HYB21-s8 ===")
print(f"{'filter':<34}{'IS':>8}{'OOS':>8}{'OOSmdd':>8}{'YTD':>9}")
print(f"{'no filter (baseline)':<34}{base[0]:>7.1f}%{base[1]:>7.1f}%{base[2]:>7.1f}%{base[3]:>+8.1f}%")
ncols=len(C.columns)
top3=[s for s,_ in sorted(rows.items(),key=lambda kv:-np.mean(kv[1]))[:3]]
bot3=[s for s,_ in sorted(rows.items(),key=lambda kv:np.mean(kv[1]))[:3]]
for label,keep in [(f'ONLY top-3 sectors {top3}',set(top3)),(f'EXCLUDE bottom-3 {bot3}',None)]:
    mask=np.zeros(ncols,bool)
    for ci_,s in sec_of.items():
        mask[ci_]= (s in keep) if keep else (s not in set(bot3))
    r=run(k8,mask=mask)
    print(f"{label[:34]:<34}{r[0]:>7.1f}%{r[1]:>7.1f}%{r[2]:>7.1f}%{r[3]:>+8.1f}%")
