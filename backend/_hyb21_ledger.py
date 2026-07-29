"""HYB21 (V3.1) full YTD trade ledger with entry technicals + exit reasons."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
vrv2=vr.values; r14v=rsi14.values
trades=[]  # dicts
NSLOT=5
cash=1.0; op=[]  # (exit_day, inv, col, ep, entry_day, sig_day)
pol=lambda d: R[d] not in {'DANGER','WEAK','CRISIS'}
for d in range(Y0,ND):
    keep=[]
    for (x,inv,col,ep,ed,sd) in op:
        if d>=x:
            xi=min(x,ND-1,last_valid[col]) if last_valid[col]>=0 else min(x,ND-1)
            cash+=inv*(Cf[xi,col]/ep)*(1-FEE-SLIP)
            trades.append(dict(col=col,sig=sd,ed=ed,xd=xi,ep=ep,xp=float(Cf[xi,col]),open=False))
        else: keep.append((x,inv,col,ep,ed,sd))
    op=keep
    eq=cash+sum(inv*(Cf[d,col]/ep) for (_,inv,col,ep,_,_) in op)
    if pol(d) and d+1<ND:
        free=NSLOT-len(op)
        if free>0 and ('mr',d) in sig:
            hd={x[2] for x in op}
            cand=sorted(sig[('mr',d)],key=lambda x:-MRS[d,x])
            for col in cand:
                if free==0: break
                if col in hd: continue
                ep=Ov[d+1,col]
                if not np.isfinite(ep) or ep<=0: continue
                h=EX['hyb21'].get((d,col),21)
                al=min(eq/NSLOT,cash)
                if al<=eq*0.02: break
                cash-=al; al*=(1-FEE-SLIP)
                op.append((d+1+h,al,col,ep,d+1,d)); hd.add(col); free-=1
for (x,inv,col,ep,ed,sd) in op:
    trades.append(dict(col=col,sig=sd,ed=ed,xd=None,ep=ep,xp=float(Cf[ND-1,col]),open=True))
def exit_reason(t):
    if t['open']:
        return f"OPEN day {ND-1-t['ed']}/21"
    e=t['ed']; ep=t['ep']; off=t['xd']-e
    w=Cf[e:t['xd']+1,t['col']]; peak=ep
    for j in range(1,len(w)):
        peak=max(peak,w[j])
        if j>=7 and (w[j]/ep-1)>0.05 and w[j]<peak*0.97:
            return f"TRAIL -3% off peak (locked, day {j})"
    if off>=21: return "21d CAP"
    return f"exit day {off}"
print(f"{'ticker':<7}{'entry':<12}{'entry$':>8}{'RSI2':>6}{'ATR%':>6}{'buf%':>6}{'vol':>5}{'RSI14':>6} {'reg':<11}{'exit':<12}{'exit$':>8}{'hold':>5}{'P&L':>8}  reason")
print('-'*118)
wr=0;n=0;rets=[]
for t in sorted(trades,key=lambda t:t['ed']):
    c=t['col']; s=t['sig']
    r=(t['xp']/t['ep']-1)*100
    if not t['open']: rets.append(r); n+=1; wr+=r>0
    print(f"{C.columns[c]:<7}{dates[t['ed']]:<12}{t['ep']:>8.2f}{r2v[s,c]:>6.1f}{a_[s,c]:>6.1f}{bfv[s,c]:>6.1f}{vrv2[s,c]:>5.1f}{r14v[s,c]:>6.0f} {R[s]:<11}{dates[t['xd']] if t['xd'] else '—':<12}{t['xp']:>8.2f}{(t['xd'] or ND-1)-t['ed']:>5}{r:>+7.1f}%  {exit_reason(t)}")
print(f"\nclosed: {n} | WR {wr/n*100:.0f}% | avg {np.mean(rets):+.2f}% | med {np.median(rets):+.2f}%")
