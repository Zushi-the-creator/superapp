"""RELSTR10 last-30-trading-day behaviour: actual monthly books, per-name P&L."""
import sqlite3, numpy as np, pandas as pd
FEE=0.003; SLIP=0.0005
con=sqlite3.connect('data/stock_cache.db')
quar={r[0] for r in con.execute("SELECT ticker FROM ticker_quarantine")}
df=pd.read_sql_query("SELECT ticker,date,open,close,volume FROM daily_prices",con)
df=df[~df.ticker.isin(quar)&~df.ticker.str.endswith('USD')&(df.ticker!='VIX')]
C=df.pivot(index='date',columns='ticker',values='close').astype('float64')
O=df.pivot(index='date',columns='ticker',values='open').astype('float64')
V=df.pivot(index='date',columns='ticker',values='volume').astype('float64')
dates=C.index.tolist(); ND=len(dates); T=ND-1
Cv=C.values; Ov=O.values; Cf=C.ffill().values
last_valid=C.apply(lambda s:s.last_valid_index()).map(lambda d: dates.index(d) if d else -1).values
dv=(C*V).rolling(63,min_periods=55).mean().values
r252=(C/C.shift(252)-1).values; r63=(C/C.shift(63)-1).values
XL=C.columns.get_loc('XLK'); QQ=C.columns.get_loc('QQQ')
xl252=np.array([(Cf[i,XL]/Cf[i-252,XL]-1) if i>=252 else np.nan for i in range(ND)])
xl63=np.array([(Cf[i,XL]/Cf[i-63,XL]-1) if i>=63 else np.nan for i in range(ND)])
mo=[d[:7] for d in dates]; ME={i for i in range(ND-1) if mo[i]!=mo[i+1]}
def picks(j,n=10):
    ok=np.isfinite(Cv[j])&(Cv[j]>=15)&np.isfinite(dv[j])&(dv[j]>3e6)
    u=np.where(ok)[0]
    if not len(u) or not np.isfinite(xl252[j]): return []
    u=u[np.argsort(-dv[j,u])][:300]
    sel=[c for c in u if np.isfinite(r252[j,c]) and r252[j,c]>xl252[j] and np.isfinite(r63[j,c]) and r63[j,c]>xl63[j]]
    return sorted(sel,key=lambda c:-r252[j,c])[:n]
W=30; A=T-W
print(f"window {dates[A]} -> {dates[T]} ({W} trading days)")
# run the strategy from Jan so the book is 'live', capture last-30 behaviour
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
eq=1.0; hold=[]; series=[]; log=[]
for i in range(Y0,ND):
    if hold:
        rs=[Cv[i,c]/Cv[i-1,c]-1 for c in hold if np.isfinite(Cv[i,c]) and np.isfinite(Cv[i-1,c]) and Cv[i-1,c]>0 and i<=last_valid[c]]
        eq*=(1+np.mean(rs)) if rs else 1
    if (i-1 in ME) or not series:
        new=picks(i-1)
        if new:
            ch=len(set(new)^set(hold)); eq*=1-(FEE+SLIP)*2*(ch/max(len(new)+len(hold),1))
            if i>=A:
                out=[C.columns[c] for c in hold if c not in new]; inn=[C.columns[c] for c in new if c not in hold]
                log.append((dates[i],out,inn))
            hold=new
    series.append(eq)
series=np.array(series)
seg=series[-(W+1):]
print(f"RELSTR10 book:  {(seg[-1]/seg[0]-1)*100:+.2f}%   (intra-window drawdown {((seg/np.maximum.accumulate(seg))-1).min()*100:.1f}%)")
print(f"XLK:            {(Cf[T,XL]/Cf[A,XL]-1)*100:+.2f}%")
print(f"QQQ:            {(Cf[T,QQ]/Cf[A,QQ]-1)*100:+.2f}%")
print(f"YTD to date:    {(series[-1]-1)*100:+.2f}%  (vs XLK {(Cf[T,XL]/Cf[Y0,XL]-1)*100:+.1f}%)")
print("\n=== rebalances inside the window ===")
for d,out,inn in log:
    print(f"  {d}  SOLD: {', '.join(out) or '—'}")
    print(f"              BOUGHT: {', '.join(inn) or '—'}")
print("\n=== current book: per-name P&L over the window ===")
print(f"{'ticker':<7}{'start$':>9}{'now$':>9}{'30d P&L':>9}")
tot=[]
for c in hold:
    a=Cf[A,c]; b=Cf[T,c]
    if np.isfinite(a) and np.isfinite(b) and a>0:
        r=(b/a-1)*100; tot.append(r)
        print(f"{C.columns[c]:<7}{a:>9.2f}{b:>9.2f}{r:>+8.1f}%")
print(f"\nmean of current holdings over window: {np.mean(tot):+.1f}%  |  winners {sum(1 for r in tot if r>0)}/{len(tot)}")
