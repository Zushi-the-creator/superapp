"""V3.1 Hybrid21d always-on: last-30-trading-day behavior of the running YTD book."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
LOG_ON[0]=True; TRADES[0]=0; TRADELOG.clear()
pol=lambda d:(('mr',MRS,'hyb21') if R[d] not in {'DANGER','WEAK','CRISIS'} else None)
c=stock_sim_cash(pol,Y0)
W=30
seg=c[-W-1:]
xl=Cf[:,C.columns.get_loc('XLK')]; qq=QQ
d0=ND-1-W
print(f"window: {dates[d0]} -> {dates[ND-1]}  (last {W} trading days — the momentum crash)")
print(f"HYB21 running book: {(seg[-1]/seg[0]-1)*100:+.2f}%   (peak-to-trough in window: {((seg/np.maximum.accumulate(seg))-1).min()*100:.1f}%)")
print(f"XLK same window:    {(xl[ND-1]/xl[d0]-1)*100:+.2f}%")
print(f"QQQ same window:    {(qq[ND-1]/qq[d0]-1)*100:+.2f}%")
cut=dates[d0]
led=[t for t in TRADELOG if t[1]>=cut]
ent=[t for t in led if t[0]=='ENTRY']; ex=[t for t in led if t[0]=='EXIT']
print(f"\ntrades in window: {len(ent)} entries, {len(ex)} exits")
print(f"{'date':<12}{'type':<7}{'ticker':<7}{'px':>9}{'P&L':>8}")
for typ,dt,tk,px,pnl in led:
    print(f"{dt:<12}{typ:<7}{tk:<7}{px:>9}{'' if pnl is None else f'{pnl:>+7.1f}%'}")
wins=[p for *_,p in ex if p is not None and p>0]; losses=[p for *_,p in ex if p is not None and p<=0]
if ex:
    pn=[p for *_,p in ex if p is not None]
    print(f"\nexits: {len(ex)} | WR {len(wins)/len(pn)*100:.0f}% | avg {np.mean(pn):+.1f}% | avg hold <=21td by rule")
# open positions at end
opens={}
for typ,dt,tk,px,pnl in TRADELOG:
    if typ=='ENTRY': opens[tk]=opens.get(tk,[])+[(dt,px)]
    elif typ=='EXIT' and tk in opens and opens[tk]: opens[tk].pop(0)
live=[(tk,v[0]) for tk,v in opens.items() if v]
print(f"\nopen positions now: {[(tk,d,px) for tk,(d,px) in live]}")
