"""RELSTR10 month-by-month 2026: returns, book, and what it held each month."""
import sqlite3, numpy as np, pandas as pd
FEE=0.003; SLIP=0.0005
con=sqlite3.connect('data/stock_cache.db')
quar={r[0] for r in con.execute("SELECT ticker FROM ticker_quarantine")}
df=pd.read_sql_query("SELECT ticker,date,close,volume FROM daily_prices",con)
df=df[~df.ticker.isin(quar)&~df.ticker.str.endswith('USD')&(df.ticker!='VIX')]
C=df.pivot(index='date',columns='ticker',values='close').astype('float64')
V=df.pivot(index='date',columns='ticker',values='volume').astype('float64')
dates=C.index.tolist(); ND=len(dates); Cv=C.values; Cf=C.ffill().values
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
Y0=next(i for i,d in enumerate(dates) if d>='2026-01-02')
eq=1.0; hold=[]; eqs={}; books={}
for i in range(Y0,ND):
    if hold:
        rs=[Cv[i,c]/Cv[i-1,c]-1 for c in hold if np.isfinite(Cv[i,c]) and np.isfinite(Cv[i-1,c]) and Cv[i-1,c]>0 and i<=last_valid[c]]
        eq*=(1+np.mean(rs)) if rs else 1
    if (i-1 in ME) or not eqs:
        new=picks(i-1)
        if new:
            ch=len(set(new)^set(hold)); eq*=1-(FEE+SLIP)*2*(ch/max(len(new)+len(hold),1)); hold=new
            books[mo[i]]=[C.columns[c] for c in new]
    eqs[dates[i]]=eq
ser=pd.Series(eqs); ser.index=pd.to_datetime(ser.index)
m_end=ser.resample('ME').last(); m_start=ser.resample('ME').first()
xls=pd.Series({dates[i]:Cf[i,XL] for i in range(Y0,ND)}); xls.index=pd.to_datetime(xls.index)
qqs=pd.Series({dates[i]:Cf[i,QQ] for i in range(Y0,ND)}); qqs.index=pd.to_datetime(qqs.index)
xe=xls.resample('ME').last(); xs=xls.resample('ME').first()
qe=qqs.resample('ME').last(); qs=qqs.resample('ME').first()
print(f"{'month':<9}{'RELSTR10':>10}{'XLK':>9}{'QQQ':>9}{'$100K→':>11}  book (top holdings that month)")
print('-'*112)
cum=100_000
for d in m_end.index:
    k=d.strftime('%Y-%m')
    r=(m_end[d]/m_start[d]-1)*100
    rx=(xe[d]/xs[d]-1)*100; rq=(qe[d]/qs[d]-1)*100
    cum=100_000*m_end[d]
    bk=books.get(k,[])
    print(f"{k:<9}{r:>+9.1f}%{rx:>+8.1f}%{rq:>+8.1f}%{cum:>11,.0f}  {', '.join(bk[:8])}")
print(f"\nYTD: RELSTR10 {(ser.iloc[-1]-1)*100:+.1f}%  |  XLK {(xls.iloc[-1]/xls.iloc[0]-1)*100:+.1f}%  |  QQQ {(qqs.iloc[-1]/qqs.iloc[0]-1)*100:+.1f}%")
pk=ser.cummax(); print(f"peak equity {(pk.max()-1)*100:+.1f}% (on {pk.idxmax().date()}), current {(ser.iloc[-1]-1)*100:+.1f}%, drawdown from peak {((ser.iloc[-1]/pk.max())-1)*100:.1f}%")
