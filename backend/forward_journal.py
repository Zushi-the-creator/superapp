#!/usr/bin/env python3
"""Forward-test journal — records each REGISTERED roster's picks at the latest
completed bar, at signal time. Appended JSONL per roster; this journal (not
retro-reconstruction) is the ONLY admissible evidence for /forward-test verdicts.
Run nightly after the cache refresh. Idempotent per (roster, asof) — reruns skip.
"""
import json, os, sqlite3, csv, hashlib
import numpy as np, pandas as pd

HERE=os.path.dirname(os.path.abspath(__file__))
JDIR=os.path.join(HERE,'data','forward_journal')
os.makedirs(JDIR,exist_ok=True)
con=sqlite3.connect(os.path.join(HERE,'data','stock_cache.db'))
quar={r[0] for r in con.execute("SELECT ticker FROM ticker_quarantine")}
df=pd.read_sql_query("SELECT ticker,date,open,high,low,close,volume FROM daily_prices WHERE date>='2024-06-01'",con)
df=df[~df.ticker.isin(quar)&~df.ticker.str.endswith('USD')&(df.ticker!='VIX')]
C=df.pivot(index='date',columns='ticker',values='close').astype('float64')
H=df.pivot(index='date',columns='ticker',values='high').astype('float64')
L=df.pivot(index='date',columns='ticker',values='low').astype('float64')
V=df.pivot(index='date',columns='ticker',values='volume').astype('float64')
dates=C.index.tolist(); T=len(dates)-1; ASOF=dates[T]
# indicators at ASOF (point-in-time by construction: only bars <= ASOF loaded)
sma50=C.rolling(50,min_periods=45).mean(); sma150=C.rolling(150).mean(); sma200=C.rolling(200,min_periods=180).mean()
d1=C.diff();g=d1.clip(lower=0);l=(-d1).clip(lower=0)
rsi2=100-100/(1+g.ewm(alpha=.5,adjust=False,min_periods=6).mean()/l.ewm(alpha=.5,adjust=False,min_periods=6).mean().replace(0,np.nan))
rsi14=100-100/(1+g.ewm(alpha=1/14,adjust=False,min_periods=42).mean()/l.ewm(alpha=1/14,adjust=False,min_periods=42).mean().replace(0,np.nan))
pc=C.shift(1)
TR=pd.concat([H-L,(H-pc).abs(),(L-pc).abs()]).groupby(level=0).max().reindex(C.index)
atrp=TR.rolling(14,min_periods=12).mean()/C*100; vr=V/V.rolling(20,min_periods=18).mean()
r20=C.pct_change(20,fill_method=None)*100; r5=C.pct_change(5,fill_method=None)*100
hi=C.rolling(252,min_periods=200).max(); lo=C.rolling(252).min(); buf=(C/sma50-1)*100
dv=(C*V).rolling(63,min_periods=55).mean()
# long history for 12-1 momentum
CL=pd.read_sql_query("SELECT ticker,date,close FROM daily_prices WHERE date>='2024-01-01'",con)
CL=CL[~CL.ticker.isin(quar)&~CL.ticker.str.endswith('USD')&(CL.ticker!='VIX')]
CL=CL.pivot(index='date',columns='ticker',values='close').astype('float64')
dl=CL.index.tolist()
# regime (prod-exact) at ASOF
try:
    vixmap={r[0]:float(r[1]) for r in csv.reader(open('/tmp/vix.csv')) if r and r[1].replace('.','',1).isdigit()}
except FileNotFoundError:
    vixmap={}
spy=C['SPY']
ddn=(spy.iloc[T]/spy.rolling(252).max().iloc[T]-1)*100
g200=(spy.iloc[T]/spy.rolling(200).mean().iloc[T]-1)*100
g50=(spy.iloc[T]/spy.rolling(50).mean().iloc[T]-1)*100
r5s=(spy.iloc[T]/spy.iloc[T-5]-1)*100
vix=vixmap.get(ASOF,0)
if -15<=ddn<=-7: REGIME='DANGER'
elif vix>40: REGIME='CRISIS'
elif -2<g200<0: REGIME='WEAK'
elif -20<=ddn<-15: REGIME='CORRECTION'
elif ddn<-20: REGIME='BEAR_BOUNCE'
elif g200<-2: REGIME='BELOW200'
elif g50<0: REGIME='PULLBACK'
elif ddn<=-3: REGIME='DIP_BUY'
elif r5s<-2: REGIME='SHARP_DROP'
elif vix>30: REGIME='FEAR'
else: REGIME='HEALTHY'

def month_end_leq(t):
    """last month-end trading day index <= t (signal day for monthly rosters)"""
    for i in range(t,0,-1):
        if dates[i][:7]!=dates[min(i+1,T)][:7] or i==T and False: return i
        if i<T and dates[i][:7]!=dates[i+1][:7]: return i
    return t
def rot10_picks():
    sig=month_end_leq(T-1) if dates[T][:7]==dates[T-1][:7] else T  # if today IS month-end, today
    sd=dates[sig]
    j=dl.index(sd)
    if j<252: return sd,[]
    m=(CL.iloc[j-21]/CL.iloc[j-252]-1)
    jj=dates.index(sd)
    ok=m.notna()&C.iloc[jj].notna()&(C.iloc[jj]>=20)&dv.iloc[jj].notna()&(m<=2.0)
    td=dv.iloc[jj][m[ok].index].nlargest(200).index
    picks=m[td].nlargest(10)
    return sd,[{'ticker':t,'rank':i+1,'mom_12_1':round(float(v),4),'px_at_signal':round(float(C.iloc[jj][t]),2)} for i,(t,v) in enumerate(picks.items())]
def mombrk5_picks():
    if REGIME not in {'HEALTHY','PULLBACK','DIP_BUY'}: return []
    i=T
    gate=(C.iloc[i]>=10)&(C.iloc[i]<=200)&(C.iloc[i]>sma50.iloc[i])&(C.iloc[i]>sma150.iloc[i])&(C.iloc[i]>sma200.iloc[i])&(sma50.iloc[i]>sma150.iloc[i])&(sma150.iloc[i]>sma200.iloc[i])&(C.iloc[i]/hi.iloc[i]-1>-0.05)&(C.iloc[i]/lo.iloc[i]-1>0.30)&(r20.iloc[i]>5)&(r5.iloc[i]<=15)
    r126=(C.iloc[i]/C.iloc[i-126]-1)
    picks=r126[gate.fillna(False)].nlargest(5)
    return [{'ticker':t,'rank':k+1,'r126':round(float(v),4),'px_at_signal':round(float(C.iloc[i][t]),2)} for k,(t,v) in enumerate(picks.items())]
def mrdip_picks():
    if REGIME not in {'DIP_BUY','SHARP_DROP','BEAR_BOUNCE'}: return []
    i=T
    gate=(C.iloc[i]>sma50.iloc[i])&(atrp.iloc[i]>=3)&(atrp.iloc[i]<15)&(buf.iloc[i]>=5)&(vr.iloc[i]>=1.0)&(rsi2.iloc[i]<10)&(rsi14.iloc[i]<60)&(C.iloc[i]>=10)
    picks=atrp.iloc[i][gate.fillna(False)].nlargest(5)
    return [{'ticker':t,'rank':k+1,'atr_pct':round(float(v),2),'px_at_signal':round(float(C.iloc[i][t]),2)} for k,(t,v) in enumerate(picks.items())]
def hyb21_picks():
    if REGIME in {'DANGER','CRISIS','WEAK'}: return []
    i=T
    gate=(C.iloc[i]>sma50.iloc[i])&(atrp.iloc[i]>=3)&(atrp.iloc[i]<15)&(buf.iloc[i]>=5)&(vr.iloc[i]>=1.0)&(rsi2.iloc[i]<10)&(rsi14.iloc[i]<60)&(C.iloc[i]>=10)
    picks=atrp.iloc[i][gate.fillna(False)].nlargest(5)
    return [{'ticker':t,'rank':k+1,'atr_pct':round(float(v),2),'px_at_signal':round(float(C.iloc[i][t]),2)} for k,(t,v) in enumerate(picks.items())]
def trend10_picks():
    i=T; j=i
    dvv=dv.iloc[j]; px=C.iloc[j]
    sma200=C.rolling(200,min_periods=180).mean().iloc[j]; sma50v=C.rolling(50,min_periods=45).mean().iloc[j]
    hi252=C.rolling(252,min_periods=200).max().iloc[j]; r126v=(C.iloc[j]/C.iloc[j-126]-1) if j>=126 else None
    if r126v is None: return []
    ok=(px>=15)&dvv.notna()&(dvv>3e6)&px.notna()&sma200.notna()&(px>sma200)&(px>sma50v)&hi252.notna()&((px/hi252)>0.90)&r126v.notna()
    cand=dvv[ok.fillna(False)].nlargest(300).index
    picks=r126v[cand].nlargest(10)
    return [{'ticker':t,'rank':k+1,'r126':round(float(v),4),'px_at_signal':round(float(px[t]),2),
             'pct_of_52wk_high':round(float(px[t]/hi252[t]),3)} for k,(t,v) in enumerate(picks.items())]
def baseline():
    out={}
    for t in ('XLK','QQQ','SPY'):
        out[t]=round(float(C.iloc[T][t]),2)
    return out

def append(name,payload):
    path=os.path.join(JDIR,f'{name}.jsonl')
    if os.path.exists(path):
        for line in open(path):
            try:
                if json.loads(line).get('asof')==ASOF:
                    print(f'{name}: already journaled for {ASOF}, skip'); return
            except Exception: pass
    row={'asof':ASOF,'regime':REGIME,**payload}
    row['row_sha256']=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()[:16]
    with open(path,'a') as f: f.write(json.dumps(row)+'\n')
    print(f'{name}: journaled {ASOF} ({len(payload.get("picks",payload))} items)')

sd,rp=rot10_picks()
append('ROT10',{'signal_date':sd,'picks':rp})
append('MOMBRK5',{'picks':mombrk5_picks()})
append('MRDIP',{'picks':mrdip_picks()})
append('V4BLEND',{'core':'XLK','core_w':0.5,'sleeve':'ROT10','sleeve_w':0.5,'overlay':'MRDIP(max 2x10% from core)'})
append('HYB21',{'picks':hyb21_picks()})
append('TREND10',{'picks':trend10_picks()})
append('BASELINE',{'closes':baseline()})
print(f'\nregime at {ASOF}: {REGIME}')
