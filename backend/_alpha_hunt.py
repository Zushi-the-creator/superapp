"""Hunt for genuine STOCK-SELECTION alpha vs XLK. Structures not yet tested:
 1. Relative-strength vs XLK (own the leaders, drop laggards) - monthly
 2. Dual-momentum stock rotation (12-1 AND 3-1 both positive)
 3. Concentrated tech-universe momentum (XLK-correlated names only)
 4. Trend-following stocks (buy >SMA200 + new highs, hold while trend intact)
 5. Momentum + low-vol filter (quality momentum)
 6. Buy-and-hold top-N momentum with NO rebalance (let winners run)
All monthly, next-open, honest costs, 17 WF windows + decade compound."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
import bisect
XLc=C.columns.get_loc('XLK')
dv=(C*V).rolling(63,min_periods=55).mean().values
r252=(C/C.shift(252)-1).values; r126_=(C/C.shift(126)-1).values
r63=(C/C.shift(63)-1).values; r21=(C/C.shift(21)-1).values
m121=(C.shift(21)/C.shift(252)-1).values
vol60=(C.pct_change(fill_method=None).rolling(60,min_periods=50).std()*np.sqrt(252)).values
sma200v=C.rolling(200,min_periods=180).mean().values; sma50v=C.rolling(50,min_periods=45).mean().values
hi252=C.rolling(252,min_periods=200).max().values
xlr252=np.array([ (Cf[i,XLc]/Cf[i-252,XLc]-1) if i>=252 else np.nan for i in range(ND)])
xlr63=np.array([ (Cf[i,XLc]/Cf[i-63,XLc]-1) if i>=63 else np.nan for i in range(ND)])
mo=[d[:7] for d in dates]; ME={i for i in range(ND-1) if mo[i]!=mo[i+1]}
def liquid(j,n=300,px=15):
    ok=np.isfinite(Cv[j])&(Cv[j]>=px)&np.isfinite(dv[j])&(dv[j]>3e6)
    e=np.where(ok)[0]
    return e[np.argsort(-dv[j,e])][:n] if len(e) else np.array([],int)
def sel_relstrength(j,n):   # beat XLK over 252d AND 63d, rank by 252d
    u=liquid(j)
    if not len(u) or not np.isfinite(xlr252[j]): return []
    ok=[c for c in u if np.isfinite(r252[j,c]) and r252[j,c]>xlr252[j] and np.isfinite(r63[j,c]) and r63[j,c]>xlr63[j]]
    return sorted(ok,key=lambda c:-r252[j,c])[:n]
def sel_dualmom(j,n):       # 12-1 AND 3-1 both positive
    u=liquid(j)
    ok=[c for c in u if np.isfinite(m121[j,c]) and m121[j,c]>0 and np.isfinite(r63[j,c]) and r63[j,c]>0 and m121[j,c]<=2.0]
    return sorted(ok,key=lambda c:-m121[j,c])[:n]
def sel_trend(j,n):         # >SMA200, >SMA50, within 10% of 252d high
    u=liquid(j)
    ok=[c for c in u if np.isfinite(sma200v[j,c]) and Cv[j,c]>sma200v[j,c] and Cv[j,c]>sma50v[j,c]
        and np.isfinite(hi252[j,c]) and Cv[j,c]/hi252[j,c]>0.90]
    return sorted(ok,key=lambda c:-r126_[j,c])[:n]
def sel_qualmom(j,n):       # momentum / vol  (risk-adjusted momentum)
    u=liquid(j)
    ok=[c for c in u if np.isfinite(m121[j,c]) and m121[j,c]>0 and np.isfinite(vol60[j,c]) and vol60[j,c]>0.05]
    return sorted(ok,key=lambda c:-(m121[j,c]/vol60[j,c]))[:n]
def sel_lowvolmom(j,n):     # top momentum, then lowest vol half
    u=liquid(j)
    ok=[c for c in u if np.isfinite(m121[j,c]) and m121[j,c]>0]
    top=sorted(ok,key=lambda c:-m121[j,c])[:n*3]
    return sorted(top,key=lambda c: vol60[j,c])[:n]
SELECTORS={'RelStrength vs XLK':sel_relstrength,'Dual-momentum':sel_dualmom,
           'Trend (>200SMA,near hi)':sel_trend,'Quality-mom (mom/vol)':sel_qualmom,
           'Low-vol momentum':sel_lowvolmom}
def rot(a,b,sel,n=10,rebal_every=1,cap=1.0):
    """rebal_every: 1=monthly, 3=quarterly, 0=buy&hold-once"""
    eq=cap; hold=[]; cnt=0
    for i in range(a,b+1):
        if hold:
            rs=[Cv[i,c]/Cv[i-1,c]-1 for c in hold if np.isfinite(Cv[i,c]) and np.isfinite(Cv[i-1,c]) and Cv[i-1,c]>0 and i<=last_valid[c]]
            eq*= (1+np.mean(rs)) if rs else 1
        do = (i-1 in ME and (rebal_every==1 or cnt%rebal_every==0)) if rebal_every else (not hold)
        if do or not hold:
            if i-1 in ME or not hold:
                new=sel(i-1,n)
                if new:
                    ch=len(set(new)^set(hold)); eq*=1-(FEE+SLIP)*2*(ch/max(len(new)+len(hold),1)); hold=new
                if i-1 in ME: cnt+=1
    return eq
starts=[];y,mn=2018,1
while (y,mn)<=(2026,1):
    starts.append(f"{y:04d}-{mn:02d}-01");mn+=6
    if mn>12:y,mn=y+1,mn-12
def dp(s): return min(bisect.bisect_left(dates,s),ND-1)
wins=[(s,dp(s),dp(f"{int(s[:4])+(1 if s[5:7]=='07' else 0)}-{'01' if s[5:7]=='07' else '07'}-01")) for s in starts]
wins=[w for w in wins if w[2]-w[1]>=60]
A0=next(i for i,d in enumerate(dates) if d>='2017-01-03')
print(f"{'strategy':<30}{'N':>4}{'WFcomp':>9}{'WFmed':>8}{'worst':>8}{'pos%':>6}{'decade $100K':>14}")
print('-'*79)
out=[]
for nm,sel in SELECTORS.items():
    for n in (10,20):
        v=np.array([rot(a,b,sel,n)-1 for _,a,b in wins])
        dec=rot(A0,ND-1,sel,n)*100_000
        out.append((f"{nm} top{n}",n,np.prod(1+v)-1,np.median(v),v.min(),(v>0).mean(),dec))
xl=np.array([(Cf[b,XLc]/Cf[a,XLc]-1) for _,a,b in wins])
for nm,n,comp,med,worst,pos,dec in sorted(out,key=lambda r:-r[6]):
    print(f"{nm:<30}{n:>4}{comp*100:>8.1f}%{med*100:>7.1f}%{worst*100:>7.1f}%{pos*100:>5.0f}%{dec:>14,.0f}")
print(f"{'XLK buy-hold':<30}{'':>4}{(np.prod(1+xl)-1)*100:>8.1f}%{np.median(xl)*100:>7.1f}%{xl.min()*100:>7.1f}%{(xl>0).mean()*100:>5.0f}%{100_000*Cf[ND-1,XLc]/Cf[A0,XLc]:>14,.0f}")

print("\n=== ROBUSTNESS of the two winners ===")
def curve(a,b,sel,n):
    eq=1.0;hold=[];c=[]
    for i in range(a,b+1):
        if hold:
            rs=[Cv[i,x]/Cv[i-1,x]-1 for x in hold if np.isfinite(Cv[i,x]) and np.isfinite(Cv[i-1,x]) and Cv[i-1,x]>0 and i<=last_valid[x]]
            eq*=(1+np.mean(rs)) if rs else 1
        if (i-1 in ME) or not c:
            new=sel(i-1,n)
            if new:
                ch=len(set(new)^set(hold));eq*=1-(FEE+SLIP)*2*(ch/max(len(new)+len(hold),1));hold=new
        c.append(eq)
    return np.array(c)
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
for nm,sel in [('Trend(>200SMA,near hi)',sel_trend),('RelStrength vs XLK',sel_relstrength)]:
    print(f"\n-- {nm} --")
    print("  top-N sensitivity (decade $100K):", {n:f"{rot(A0,ND-1,sel,n)*100_000:,.0f}" for n in (5,8,10,15,20,25)})
    for y in range(2017,2027):
        a=next(i for i,d in enumerate(dates) if d>=f'{y}-01-01'); b=max(i for i,d in enumerate(dates) if d<=f'{y}-12-31')
        r=(rot(a,b,sel,10)-1)*100; rx=(Cf[b,XLc]/Cf[a,XLc]-1)*100
        print(f"   {y}: {r:>+7.1f}%  vs XLK {rx:>+6.1f}%  {'WIN' if r>rx else ''}")
    cc=curve(A0,ND-1,sel,10)
    open(f'/tmp/curves/ALPHA_{nm[:12].replace(" ","_")}.csv','w').write('\n'.join(str(x) for x in cc))
    ytd=(rot(Y0,ND-1,sel,10)-1)*100
    print(f"   2026 YTD: {ytd:+.1f}% vs XLK {(Cf[ND-1,XLc]/Cf[Y0,XLc]-1)*100:+.1f}%")
