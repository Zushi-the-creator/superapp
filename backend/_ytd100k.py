"""$100K per strategy, 2026-01-02 -> latest bar, true next-open entries/exits.
Runs every harness strategy + captures trade ledgers for registered rosters."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])  # load data+sims (no report)
def m(c):
    pk=np.maximum.accumulate(c);return c[-1]-1,(c/pk-1).min()
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
CAP=100_000.0
xlk_r=(Cf[ND-1,C.columns.get_loc('XLK')]/Cf[Y0,C.columns.get_loc('XLK')]-1)*100
qqq_r=(QQ[ND-1]/QQ[Y0]-1)*100
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
for k,led in LEDGERS.items():
    print(f"\n=== TRADE LEDGER: {k} (YTD) ===")
    for row in led[:40]:
        typ,dt,tk,px,pnl=row
        print(f"  {dt} {typ:<6}{tk:<7}{'' if px is None else f'@{px}'}{'' if pnl is None else f'  P&L {pnl:+.1f}%'}")
