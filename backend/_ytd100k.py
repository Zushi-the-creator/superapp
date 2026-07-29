"""$100K per strategy, 2026-01-02 -> latest bar, true next-open entries/exits.
Runs every harness strategy + captures trade ledgers for registered rosters."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])  # load data+sims (no report)
def m(c):
    pk=np.maximum.accumulate(c);return c[-1]-1,(c/pk-1).min()
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
CAP=100_000.0
xlk_r=(Cf[ND-1,C.columns.get_loc('XLK')]/Cf[Y0,C.columns.get_loc('XLK')]-1)*100
qqq_r=(QQ[ND-1]/QQ[Y0]-1)*100
# --- add missing strategies (rejected family) ---
vol60=(C.pct_change(fill_method=None).rolling(60).std()*np.sqrt(252)).values
hi252v=hi.values
def prox_f(j,n):
    ok=np.isfinite(Cv[j])&(Cv[j]>=10)&np.isfinite(dvol[j])&np.isfinite(hi252v[j])&(hi252v[j]>0)
    e=np.where(ok)[0]
    if not len(e): return []
    td=e[np.argsort(-dvol[j,e])][:500]
    pr=Cv[j,td]/hi252v[j,td]
    return list(td[np.argsort(-pr)][:n])
def lowvol_f(j,n):
    ok=np.isfinite(Cv[j])&(Cv[j]>=10)&np.isfinite(dvol[j])&np.isfinite(vol60[j])
    e=np.where(ok)[0]
    if not len(e): return []
    td=e[np.argsort(-dvol[j,e])][:500]
    return list(td[np.argsort(vol60[j,td])][:n])
def sell_in_may(s0):
    eq=1.;c=[1.0]
    for i in range(s0,ND):
        mth=int(dates[i][5:7])
        if mth in (11,12,1,2,3,4): eq*=QQ[i]/QQ[i-1]
        c.append(eq)
    return np.array(c)
def tom_spy(s0):
    mo2=[d[:7] for d in dates]; me2={i for i in range(ND-1) if mo2[i]!=mo2[i+1]}
    inwin=np.zeros(ND,bool)
    for e in me2:
        for k in range(-3,4):
            if 0<=e+k<ND: inwin[e+k]=True
    eq=1.;c=[1.0]
    for i in range(s0,ND):
        if inwin[i-1]: eq*=SP[i]/SP[i-1]
        c.append(eq)
    return np.array(c)
STRATS=STRATS+[
 ('B','52wk-high proximity top10 monthly (rejected)',lambda s:monthly_rot(None,prox_f,10,s)),
 ('B','Low-volatility top10 monthly (rejected)',lambda s:monthly_rot(None,lowvol_f,10,s)),
 ('A','Sell-in-May QQQ (rejected)',sell_in_may),
 ('A','Turn-of-month SPY (rejected)',tom_spy)]
res=[]
LEDGERS={}
for tier,k,f in STRATS:
    TRADES[0]=0; TRADELOG.clear()
    LOG_ON[0]=k in ('MR dips-only Fixed42','MOM breakout r126 F90 uptrend-only')
    try:
        c=f(Y0); r,mdd=m(c/c[0] if c[0]!=1.0 else c)
        res.append((tier,k,CAP*(1+r),r*100,mdd*100,TRADES[0]))
        if LOG_ON[0]: LEDGERS[k]=list(TRADELOG)
    except Exception as ex:
        print('ERR',k,ex)
print(f"latest bar: {dates[ND-1]} | XLK YTD {xlk_r:+.1f}% | QQQ YTD {qqq_r:+.1f}%\n")
print(f"{'T':<2}{'strategy':<46}{'final $':>11}{'ret':>8}{'MDD':>8}{'trades':>7}{'vs XLK':>8}")
print('-'*90)
for tier,k,fv,r,mdd,ntr in sorted(res,key=lambda x:-x[3]):
    print(f"{tier:<2}{k:<46}{fv:>11,.0f}{r:>+7.1f}%{mdd:>7.1f}%{ntr:>7}{r-xlk_r:>+7.1f}%")

print("-"*90)
acct_now=18528.0; deposited=20907.44
print(f"{'*':<2}{'YOUR ACTUAL BROKER ACCOUNT (ground truth)':<46}{100000*acct_now/deposited:>11,.0f}{(acct_now/deposited-1)*100:>+7.1f}%{'':>7}{'':>7}{(acct_now/deposited-1)*100-xlk_r:>+7.1f}%")
print("   (scaled to $100K basis from real $20,907 deposited -> $18,528 now; deposits completed Feb; incl. all fees/tax)")
for k,led in LEDGERS.items():
    print(f"\n=== TRADE LEDGER: {k} (YTD) ===")
    for row in led[:40]:
        typ,dt,tk,px,pnl=row
        print(f"  {dt} {typ:<6}{tk:<7}{'' if px is None else f'@{px}'}{'' if pnl is None else f'  P&L {pnl:+.1f}%'}")
