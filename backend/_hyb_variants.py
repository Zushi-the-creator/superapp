"""HYB21 variant + mix search under the SAME harness (IS/OOS/YTD, honest costs).
Axes: min-hold (5/7/10), trail (-2/-3/-5%), profit-arm (3/5/8%), cap (14/21/30),
slots (5/8), plus blends with XLK core."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
def m2(c):
    pk=np.maximum.accumulate(c);return c[-1]**(252/max(len(c)-1,1))-1,(c/pk-1).min()
# build custom hybrid exit offsets
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
            w=Cf[e:min(e+cap+1,ND),col]
            off=cap; peak=ep
            for j in range(1,len(w)):
                peak=max(peak,w[j])
                if j>=minh and (w[j]/ep-1)>arm and w[j]<peak*(1-trail):
                    off=j; break
            EX[key][(i,col)]=off
    return key
IS=next(i for i,d in enumerate(dates) if d>='2016-06-01')
OOS=next(i for i,d in enumerate(dates) if d>='2023-01-03')
NP_=lambda d: R[d] not in {'DANGER','WEAK','CRISIS'}
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
def run(minh,trail,arm,cap,slots=5,label=''):
    key=build_hyb(minh,trail,arm,cap)
    global NSLOT
    old=NSLOT; NSLOT=slots
    pol=lambda d:(('mr',MRS,key) if NP_(d) else None)
    ci=stock_sim_cash(pol,IS)[:OOS-IS]; co=stock_sim_cash(pol,OOS); cy=stock_sim_cash(pol,Y0)
    NSLOT=old
    ai,_=m2(ci); ao,mo=m2(co)
    return ai*100, ao*100, mo*100, (cy[-1]/cy[0]-1)*100
rows=[]
rows.append(('HYB21 baseline (7d,-3%,+5%,cap21)',)+run(7,0.03,0.05,21))
for minh in (5,10):
    rows.append((f'min-hold {minh}d',)+run(minh,0.03,0.05,21))
for tr in (0.02,0.05):
    rows.append((f'trail -{int(tr*100)}%',)+run(7,tr,0.05,21))
for arm in (0.03,0.08):
    rows.append((f'arm +{int(arm*100)}%',)+run(7,0.03,arm,21))
for cap in (14,30):
    rows.append((f'cap {cap}d',)+run(7,0.03,0.05,cap))
rows.append(('slots 8 (more diversified)',)+run(7,0.03,0.05,21,slots=8))
rows.append(('best-guess combo 5d/-2%/+3%/cap14',)+run(5,0.02,0.03,14))
print(f"{'variant':<38}{'IS':>8}{'OOS':>8}{'OOSmdd':>8}{'YTD':>9}")
for r in rows:
    print(f"{r[0]:<38}{r[1]:>7.1f}%{r[2]:>7.1f}%{r[3]:>7.1f}%{r[4]:>+8.1f}%")
# blends with XLK core
XLc=C.columns.get_loc('XLK')
def blend_run(w,minh=7,trail=0.03,arm=0.05,cap=21):
    key=build_hyb(minh,trail,arm,cap)
    pol=lambda d:(('mr',MRS,key) if NP_(d) else None)
    out=[]
    for s in (IS,OOS,Y0):
        h=stock_sim_cash(pol,s); x=np.array([Cf[i,XLc]/Cf[s,XLc] for i in range(s,ND)])
        n=min(len(h),len(x)); rh=np.diff(h[:n])/h[:n-1]; rx=np.diff(x[:n])/x[:n-1]
        out.append(np.concatenate([[1.0],np.cumprod(1+(1-w)*rx+w*rh)]))
    ci,co,cy=out
    ai,_=m2(ci[:OOS-IS]); ao,mo=m2(co)
    return ai*100, ao*100, mo*100, (cy[-1]/cy[0]-1)*100
print(f"\n{'XLK-core + HYB21 blend':<38}{'IS':>8}{'OOS':>8}{'OOSmdd':>8}{'YTD':>9}")
for w in (0.3,0.5,0.7):
    r=blend_run(w)
    print(f"{f'{int((1-w)*100)}% XLK + {int(w*100)}% HYB21':<38}{r[0]:>7.1f}%{r[1]:>7.1f}%{r[2]:>7.1f}%{r[3]:>+8.1f}%")
xl_is=(Cf[OOS-1,XLc]/Cf[IS,XLc])**(252/(OOS-IS))-1
xl_oos=(Cf[ND-1,XLc]/Cf[OOS,XLc])**(252/(ND-OOS))-1
xl_ytd=(Cf[ND-1,XLc]/Cf[Y0,XLc]-1)
print(f"{'XLK buy-hold (benchmark)':<38}{xl_is*100:>7.1f}%{xl_oos*100:>7.1f}%{'':>8}{xl_ytd*100:>+8.1f}%")

print("\n=== ROBUSTNESS of 'slots 8' (the OOS standout) ===")
for sl in (6,7,8,9,10,12):
    r=run(7,0.03,0.05,21,slots=sl)
    print(f"  slots {sl:>2}: IS {r[0]:>6.1f}%  OOS {r[1]:>6.1f}%  MDD {r[2]:>6.1f}%  YTD {r[3]:>+7.1f}%")
print("\n=== slots-8 x trail sensitivity ===")
for tr in (0.02,0.03,0.05):
    r=run(7,tr,0.05,21,slots=8)
    print(f"  slots8 trail -{int(tr*100)}%: IS {r[0]:>6.1f}%  OOS {r[1]:>6.1f}%  MDD {r[2]:>6.1f}%  YTD {r[3]:>+7.1f}%")
print("\n=== XLK blends with slots-8 variant ===")
def blend8(w):
    key=build_hyb(7,0.03,0.05,21)
    global NSLOT; old=NSLOT; NSLOT=8
    pol=lambda d:(('mr',MRS,key) if NP_(d) else None)
    out=[]
    for s in (IS,OOS,Y0):
        h=stock_sim_cash(pol,s); x=np.array([Cf[i,C.columns.get_loc('XLK')]/Cf[s,C.columns.get_loc('XLK')] for i in range(s,ND)])
        n=min(len(h),len(x)); rh=np.diff(h[:n])/h[:n-1]; rx=np.diff(x[:n])/x[:n-1]
        out.append(np.concatenate([[1.0],np.cumprod(1+(1-w)*rx+w*rh)]))
    NSLOT=old
    ci,co,cy=out
    ai,_=m2(ci[:OOS-IS]); ao,mo=m2(co)
    return ai*100,ao*100,mo*100,(cy[-1]/cy[0]-1)*100
for w in (0.3,0.5,0.7,1.0):
    r=blend8(w)
    print(f"  {int((1-w)*100)}% XLK + {int(w*100)}% HYB21-s8: IS {r[0]:>6.1f}%  OOS {r[1]:>6.1f}%  MDD {r[2]:>6.1f}%  YTD {r[3]:>+7.1f}%")
