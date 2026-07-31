"""MASTER HARNESS v2 — every past + proposed strategy, one set of rules.
Slot-limited N=5, next-open entry, fee 0.3%+slip 0.05%/side stocks (0.05%+slip ETFs),
IS 2016-06->2022-12 / OOS 2023-01->2026-07, delisting haircut -30% when a ticker's
series ends >10d before cache end (mitigates ffill flat-line bias)."""
import sqlite3, numpy as np, pandas as pd
TRADES=[0]
TRADELOG=[]
LOG_ON=[False]
FEE=0.003; SLIP=0.0005; EFEE=0.0005; NSLOT=5; DELIST_HC=0.70
con=sqlite3.connect('data/stock_cache.db')
quar={r[0] for r in con.execute("SELECT ticker FROM ticker_quarantine")}
df=pd.read_sql_query("SELECT ticker,date,open,high,low,close,volume FROM daily_prices",con)
df=df[~df.ticker.isin(quar)&~df.ticker.str.endswith('USD')&(df.ticker!='VIX')]
C=df.pivot(index='date',columns='ticker',values='close').astype('float32')
O=df.pivot(index='date',columns='ticker',values='open').astype('float32')
H=df.pivot(index='date',columns='ticker',values='high').astype('float32')
L=df.pivot(index='date',columns='ticker',values='low').astype('float32')
V=df.pivot(index='date',columns='ticker',values='volume').astype('float32')
del df
dates=C.index.tolist(); ND=len(dates)
last_valid=C.apply(lambda s: s.last_valid_index()).map(lambda d: dates.index(d) if d is not None else -1).values
sma50=C.rolling(50).mean();sma150=C.rolling(150).mean();sma200=C.rolling(200).mean()
d1=C.diff();g=d1.clip(lower=0);l=(-d1).clip(lower=0)
def rsi(p):
    a=g.ewm(alpha=1/p,adjust=False,min_periods=p*3).mean();b=l.ewm(alpha=1/p,adjust=False,min_periods=p*3).mean()
    return 100-100/(1+a/b.replace(0,np.nan))
rsi2=rsi(2);rsi14=rsi(14);pc=C.shift(1)
TR=pd.concat([H-L,(H-pc).abs(),(L-pc).abs()]).groupby(level=0).max().reindex(C.index)
atrp=TR.rolling(14).mean()/C*100;vr=V/V.rolling(20).mean()
r20=C.pct_change(20,fill_method=None)*100;r5=C.pct_change(5,fill_method=None)*100
r126=C.pct_change(126,fill_method=None)*100;d1p=C.pct_change(1,fill_method=None)*100
hi=C.rolling(252).max();lo=C.rolling(252).min();buf=(C/sma50-1)*100
mrg=((C>sma50)&(atrp>=3)&(atrp<15)&(buf>=5)&(vr>=1.0)&(rsi2<10)&(rsi14<60)&(C>=10)).values
a_=atrp.values;r2v=rsi2.values;r20v=r20.values;vrv=vr.values;bfv=buf.values;pv=C.values
ap=np.select([a_>=15,a_>=10,a_>=8,a_>=6,a_>=5,a_>=4,a_>=3],[-5,35,40,35,30,20,15],default=0)
bp=np.where(a_>=15,0,np.select([(r20v>10)&(a_>=5),(r20v>5)&(a_>=4)],[12,8],default=0))
vp=np.select([vrv<0.5,vrv<1.0,vrv<1.5],[8,0,10],default=5)
fp=np.select([bfv>=5,bfv>=0],[2,1],default=0)
pp=np.select([(pv>=10)&(pv<=25),pv<=50,pv<=100,pv<=200,pv<=500],[10,8,5,2,-3],default=-5)
rp=np.select([r2v<5,r2v<10],[3,2],default=0)
MRS=np.where(mrg,np.clip(ap+rp+fp+bp+4+vp+pp,0,100),-1)
momg=((C>=10)&(C<=200)&(C>sma50)&(C>sma150)&(C>sma200)&(sma50>sma150)&(sma150>sma200)
      &(C/hi-1>-0.05)&(C/lo-1>0.30)&(r20>5)&(d1p<10)&(r5<=15)).values
MOMS=np.where(momg,r126.values,-1e9)          # candidate: rank by 12-1 momentum
MSPK=np.where(momg,r20.values*vr.values,-1e9) # PROD tab momentum sleeve: ret20 x volume spike
Cv=C.values;Ov=O.values;Cf=C.ffill().values
import csv
VIXM={}
for row in csv.reader(open('/tmp/vix.csv')):
    try: VIXM[row[0]]=float(row[1])
    except Exception: pass
VIXA=np.array([VIXM.get(d,0.0) for d in dates])
# VIX gaps: prod reads the last cached close, so carry the previous value forward
# rather than letting a missing row read as 0 (which silently disables CRISIS/FEAR).
for _i in range(1,len(VIXA)):
    if VIXA[_i]<=0: VIXA[_i]=VIXA[_i-1]
# REGIME INPUTS — must mirror prod `_check_market_regime`, which calls
# spy_df["Close"].dropna() and then min(252, len(closes)). A STRICT rolling
# window here does not: one NaN SPY bar (e.g. the 2026-02-16 holiday row)
# poisons the next 252/200/50 bars, every comparison against NaN returns False,
# and the regime chain falls through to HEALTHY/SHARP_DROP on the 5d return
# alone. That mislabelled 26% of 2026 — the March -9.1% drawdown read HEALTHY
# instead of DANGER. Fix: ffill the close (= prod's dropna) + min_periods.
spy=C['SPY'].ffill()
dd=((spy/spy.rolling(252,min_periods=20).max())-1)*100
g2=((spy/spy.rolling(200,min_periods=20).mean())-1)*100
g5=((spy/spy.rolling(50,min_periods=10).mean())-1)*100
sr5=spy.pct_change(5,fill_method=None)*100
ddv=dd.values;g2v=g2.values;g5v=g5.values;sr5v=sr5.values
def REGf(i):
    d,gg,g5x,rr=ddv[i],g2v[i],g5v[i],sr5v[i]
    v=VIXA[i]
    if -15<=d<=-7:return 'DANGER'
    if v>40:return 'CRISIS'
    if -2<gg<0:return 'WEAK'
    if -20<=d<-15:return 'CORRECTION'
    if d<-20:return 'BEAR_BOUNCE'
    if gg<-2:return 'BELOW200'
    if g5x<0:return 'PULLBACK'
    if d<=-3:return 'DIP_BUY'
    if rr<-2:return 'SHARP_DROP'
    if v>30:return 'FEAR'
    return 'HEALTHY'
R=[REGf(i) for i in range(ND)]
qc_=C.columns.get_loc('QQQ');QQ=Cf[:,qc_];SP=Cf[:,C.columns.get_loc('SPY')];XL=Cf[:,C.columns.get_loc('XLK')]
q200=pd.Series(QQ).rolling(200).mean().values
sig={}
gr,gc=np.where(mrg)
for i,c in zip(gr,gc): sig.setdefault(('mr',i),[]).append(c)
gr,gc=np.where(momg)
for i,c in zip(gr,gc): sig.setdefault(('mom',i),[]).append(c)
# --- path-dependent exit offsets per MR signal (entry at i+1 open) ---
EX={'rsi75c21':{},'stop8w42':{},'hyb21':{}}
for (k,i),cols in [((k,i),v) for (k,i),v in sig.items() if k=='mr']:
    for col in cols:
        e=i+1
        if e+1>=ND: continue
        ep=Ov[e,col]
        if not np.isfinite(ep) or ep<=0: continue
        w=Cf[e:min(e+43,ND),col]
        # rsi75 cap21
        off=21
        rr=r2v[e:min(e+22,ND),col]
        for j in range(1,min(22,len(w))):
            if np.isfinite(rr[j]) and rr[j]>75: off=j;break
        EX['rsi75c21'][(i,col)]=off
        # stop -8% else 42
        off=42
        for j in range(1,min(43,len(w))):
            if w[j]<=ep*0.92: off=j;break
        EX['stop8w42'][(i,col)]=off
        # Hybrid21d: >=7d, then if pnl>5% trail -3% from peak; cap 21
        off=21;peak=ep
        for j in range(1,min(22,len(w))):
            peak=max(peak,w[j])
            if j>=7 and (w[j]/ep-1)>0.05 and w[j]<peak*0.97: off=j;break
        EX['hyb21'][(i,col)]=off
def stock_sim(pol,s0):
    u=1.0/QQ[s0];op=[];c=[];n_delist=0
    for d in range(s0,ND):
        p=QQ[d];k=[]
        for (x,inv,col,ep) in op:
            if d>=x:
                xi=min(x,ND-1,last_valid[col]) if last_valid[col]>=0 else min(x,ND-1)
                px=Cf[xi,col]
                f=1.0
                if x>last_valid[col] and last_valid[col]<ND-10: f=DELIST_HC;n_delist+=1
                u+=inv*(px*f/ep)*(1-FEE-SLIP)*(1-EFEE-SLIP)/p
                TRADES[0]+=1
                if LOG_ON[0]: TRADELOG.append(('EXIT',dates[min(xi,ND-1)],C.columns[col],round(float(px),2),round(float(px*f/ep-1)*100,1)))
            else: k.append((x,inv,col,ep))
        op=k
        eq=u*p+sum(inv*(Cf[d,col]/ep) for (_,inv,col,ep) in op); c.append(eq)
        z=pol(d)
        if z and d+1<ND:
            key,score,hold=z;free=NSLOT-len(op)
            if free>0 and (key,d) in sig:
                hd={x[2] for x in op};cand=sorted(sig[(key,d)],key=lambda x:-score[d,x])
                for col in cand:
                    if free==0:break
                    if col in hd:continue
                    ep=Ov[d+1,col]
                    if not np.isfinite(ep) or ep<=0:continue
                    h=EX[hold].get((d,col),21 if hold!='stop8w42' else 42) if isinstance(hold,str) else hold
                    al=min(eq/NSLOT,u*p)
                    if al<=eq*0.02:break
                    u-=al/p;al*=(1-FEE-SLIP)*(1-EFEE-SLIP);op.append((d+1+h,al,col,ep));hd.add(col);free-=1
                    TRADES[0]+=1
                    if LOG_ON[0]: TRADELOG.append(('ENTRY',dates[d+1],C.columns[col],round(float(ep),2),None))
    return np.array(c)
def stock_sim_cash(pol,s0):
    cash=1.0;op=[];c=[]
    for d in range(s0,ND):
        k=[]
        for (x,inv,col,ep) in op:
            if d>=x:
                xi=min(x,ND-1,last_valid[col]) if last_valid[col]>=0 else min(x,ND-1)
                f=DELIST_HC if (x>last_valid[col] and last_valid[col]<ND-10) else 1.0
                cash+=inv*(Cf[xi,col]*f/ep)*(1-FEE-SLIP)
                TRADES[0]+=1
                if LOG_ON[0]: TRADELOG.append(('EXIT',dates[min(xi,ND-1)],C.columns[col],round(float(Cf[xi,col]),2),round(float(Cf[xi,col]*f/ep-1)*100,1)))
            else: k.append((x,inv,col,ep))
        op=k
        eq=cash+sum(inv*(Cf[d,col]/ep) for (_,inv,col,ep) in op); c.append(eq)
        z=pol(d)
        if z and d+1<ND:
            key,score,hold=z;free=NSLOT-len(op)
            if free>0 and (key,d) in sig:
                hd={x[2] for x in op};cand=sorted(sig[(key,d)],key=lambda x:-score[d,x])
                for col in cand:
                    if free==0:break
                    if col in hd:continue
                    ep=Ov[d+1,col]
                    if not np.isfinite(ep) or ep<=0:continue
                    h=EX[hold].get((d,col),21 if hold!='stop8w42' else 42) if isinstance(hold,str) else hold
                    al=min(eq/NSLOT,cash)
                    if al<=eq*0.02:break
                    cash-=al;al*=(1-FEE-SLIP);op.append((d+1+h,al,col,ep));hd.add(col);free-=1
                    TRADES[0]+=1
                    if LOG_ON[0]: TRADELOG.append(('ENTRY',dates[d+1],C.columns[col],round(float(ep),2),None))
    return np.array(c)
RATEA=np.array([0.01 if d<'2022-06-01' else (0.03 if d<'2023-01-01' else 0.05) for d in dates])
def etf_curve(sat,mult,s0,er=0.0095):
    eq=1.;c=[1.0];inp=True
    for i in range(s0,ND):
        dg=(er+(mult-1)*RATEA[i])/252
        r=QQ[i]/QQ[i-1]-1;w=QQ[i-1]>q200[i-1]
        if w!=inp: eq*=1-sat*(EFEE+SLIP);inp=w;TRADES[0]+=1
        eq*=(1+(1-sat)*r+sat*((mult*r-dg) if inp else 0));c.append(eq)
    return np.array(c)
def bh(arr,s0): return np.array([arr[i]/arr[s0] for i in range(s0,ND)])
def faber(s0):
    eq=1.;c=[1.0];inp=True
    for i in range(s0,ND):
        if (i-1 in me) or i==s0:
            w=QQ[i-1]>q200[i-1]
            if w!=inp: eq*=1-EFEE-SLIP;inp=w
        if inp: eq*=QQ[i]/QQ[i-1]
        c.append(eq)
    return np.array(c)
mo=[d[:7] for d in dates];me={i for i in range(ND-1) if mo[i]!=mo[i+1]}
dvol=(C*V).rolling(63).mean().values
def monthly_rot(score_at,univ_filter,top_n,s0,stock=True):
    fee=(FEE if stock else EFEE)+SLIP
    eq=1.;hold=[];c=[];n_delist=0
    for i in range(s0,ND):
        if hold:
            rs=[]
            for col in hold:
                if i>last_valid[col] and last_valid[col]<ND-10: rs.append(-0.0)  # flat after delist haircut applied at rebalance
                elif np.isfinite(Cv[i,col]) and np.isfinite(Cv[i-1,col]) and Cv[i-1,col]>0: rs.append(Cv[i,col]/Cv[i-1,col]-1)
            eq*=(1+np.mean(rs)) if rs else 1
        if (i-1 in me) or not c:
            j=i-1;new=univ_filter(j,top_n)
            ch=len(set(new)^set(hold));eq*=1-fee*2*(ch/max(len(new)+len(hold),1));hold=new
            TRADES[0]+=ch
            if LOG_ON[0] and ch: TRADELOG.append(('REBAL',dates[i],'+'.join(C.columns[c] for c in new[:10]),None,None))
        c.append(eq)
    return np.array(c)
def lc121(j,n):
    m=(Cv[j-21]/Cv[j-252]-1) if j>=252 else None
    if m is None: return []
    ok=np.isfinite(m)&np.isfinite(Cv[j])&(Cv[j]>=20)&np.isfinite(dvol[j])&(m<=2.0)
    e=np.where(ok)[0]
    if not len(e): return []
    td=e[np.argsort(-dvol[j,e])][:200]
    return list(td[np.argsort(-m[td])][:n])
SPDRS=[C.columns.get_loc(t) for t in ['XLK','XLE','XLF','XLV','XLI','XLP','XLY','XLU','XLB'] if t in C.columns]
def sect(j,n):
    if j<63: return []
    m=Cv[j]/Cv[j-63]-1
    cand=[(m[c],c) for c in SPDRS if np.isfinite(m[c])]
    return [c for _,c in sorted(cand,reverse=True)[:n]]
def _blend(a,b,w):
    n=min(len(a),len(b)); a,b=a[:n],b[:n]
    ra=np.diff(a)/a[:-1]; rb=np.diff(b)/b[:-1]
    return np.concatenate([[1.0],np.cumprod(1+(1-w)*ra+w*rb)])
DIP={'DIP_BUY','SHARP_DROP','BEAR_BOUNCE','CORRECTION'}
NONPAUSE=lambda d: R[d] not in {'DANGER','WEAK','CRISIS'}

# ===== 2026-07-30: ported from exploration scripts into the canonical harness =====
# Sector map: trailing 504d max-correlation to SPDRs, cached per ~quarter (point-in-time).
_SPDR=[s for s in ['XLK','XLV','XLF','XLE','XLI','XLP','XLY','XLU','XLB','XLRE'] if s in C.columns]
_SPI={s:list(C.columns).index(s) for s in _SPDR}
_rets=C.pct_change(fill_method=None)
_seccache={}
def _sectors_at(j):
    key=j//63
    if key in _seccache: return _seccache[key]
    a=max(0,j-504); w=_rets.iloc[a:j+1]; etf=w[_SPDR]
    sub=w.dropna(axis=1,thresh=int((j-a)*0.6)); out={}
    _cl=list(C.columns)
    for tk in sub.columns:
        if tk in _SPDR: out[_cl.index(tk)]=tk; continue
        s=sub[tk]; best=None; bv=-9.0
        for e in _SPDR:
            cc=s.corr(etf[e])
            if cc==cc and cc>bv: bv=cc; best=e
        if best and bv>0.25: out[_cl.index(tk)]=best
    _seccache[key]=out; return out
_r252=(C/C.shift(252)-1).values; _r63=(C/C.shift(63)-1).values; _r126m=(C/C.shift(126)-1).values
_s200=C.rolling(200,min_periods=180).mean().values
_s50h=C.rolling(50,min_periods=45).mean().values
_hi252=C.rolling(252,min_periods=200).max().values
def _liquid(j,n=300):
    ok=np.isfinite(Cv[j])&(Cv[j]>=15)&np.isfinite(dvol[j])&(dvol[j]>3e6)
    e=np.where(ok)[0]
    return e[np.argsort(-dvol[j,e])][:n] if len(e) else np.array([],int)
def mk_relstr(cap=99,bench='XLK'):
    bi=C.columns.get_loc(bench)
    def f(j,n):
        if j<252: return []
        u=_liquid(j)
        if not len(u): return []
        b252=Cf[j,bi]/Cf[j-252,bi]-1; b63=Cf[j,bi]/Cf[j-63,bi]-1
        cand=[c for c in u if np.isfinite(_r252[j,c]) and _r252[j,c]>b252 and np.isfinite(_r63[j,c]) and _r63[j,c]>b63]
        cand.sort(key=lambda c:-_r252[j,c])
        if cap>=99: return cand[:n]
        sec=_sectors_at(j); out=[]; cnt={}
        for c in cand:
            s=sec.get(c,'?')
            if cnt.get(s,0)>=cap: continue
            out.append(c); cnt[s]=cnt.get(s,0)+1
            if len(out)==n: break
        return out
    return f
def _trend_sel(j,n):
    u=_liquid(j)
    ok=[c for c in u if np.isfinite(_s200[j,c]) and Cv[j,c]>_s200[j,c] and np.isfinite(_s50h[j,c])
        and Cv[j,c]>_s50h[j,c] and np.isfinite(_hi252[j,c]) and Cv[j,c]/_hi252[j,c]>0.90 and np.isfinite(_r126m[j,c])]
    return sorted(ok,key=lambda c:-_r126m[j,c])[:n]
def _leadsec_sel(j,n):
    u=_liquid(j)
    if not len(u): return []
    sm={s:(Cf[j,_SPI[s]]/Cf[j-126,_SPI[s]]-1) if j>=126 else -9 for s in _SPDR}
    lead=[s for s,_ in sorted(sm.items(),key=lambda kv:-kv[1])[:5]]
    sec=_sectors_at(j); per=max(1,n//len(lead)); out=[]
    for s in lead:
        mem=[c for c in u if sec.get(c)==s and np.isfinite(_r126m[j,c])]
        mem.sort(key=lambda c:-_r126m[j,c]); out+=mem[:per]
    return out[:n]
def monthly_rot_g(sel,top_n,s0,pos_stop=None,dd_guard=None):
    """monthly rotation with optional position trailing-stop and portfolio DD guard.
    NULL-CHECK: sel returning [] every month must reproduce cash (flat 1.0)."""
    fee=FEE+SLIP; eq=1.0; hold={}; peak=1.0; parked=False; c=[1.0]
    for i in range(s0,ND):
        if parked: eq*=Cf[i,SPYi]/Cf[i-1,SPYi]
        elif hold:
            rs=[]
            for col,(ep,pk) in list(hold.items()):
                if not (np.isfinite(Cv[i,col]) and np.isfinite(Cv[i-1,col]) and Cv[i-1,col]>0 and i<=last_valid[col]): continue
                rs.append(Cv[i,col]/Cv[i-1,col]-1); hold[col]=(ep,max(pk,Cv[i,col]))
            eq*=(1+np.mean(rs)) if rs else 1
        peak=max(peak,eq)
        if pos_stop and hold and not parked:
            drop=[col for col,(ep,pk) in hold.items() if np.isfinite(Cv[i,col]) and Cv[i,col]<pk*(1-pos_stop)]
            if drop:
                eq*=1-fee*(len(drop)/max(len(hold),1))
                for col in drop: hold.pop(col,None)
        if dd_guard:
            if not parked and eq<peak*(1-dd_guard): eq*=1-fee; hold={}; parked=True
            elif parked and eq>peak*(1-dd_guard/2): parked=False
        if (i-1 in me) and not parked:
            new=sel(i-1,top_n)
            if new:
                ch=len(set(new)^set(hold)); eq*=1-fee*2*(ch/max(len(new)+len(hold),1))
                hold={}
                for col in new:
                    p=Ov[i,col] if (np.isfinite(Ov[i,col]) and Ov[i,col]>0) else Cv[i-1,col]
                    hold[col]=(p,p)
        c.append(eq)
    return np.array(c)
SPYi=C.columns.get_loc('SPY')

STRATS=[
 ('B','RELSTR10 (beat XLK 252d+63d) [ported]',lambda s:monthly_rot_g(mk_relstr(99,'XLK'),10,s)),
 ('B','RELSTR10 sector-cap2 [ported]',lambda s:monthly_rot_g(mk_relstr(2,'XLK'),10,s)),
 ('B','RELSTR10 bench=SPY cap2 [ported]',lambda s:monthly_rot_g(mk_relstr(2,'SPY'),10,s)),
 ('B','RELSTR10 cap2 + stop15 + DD12 [ported]',lambda s:monthly_rot_g(mk_relstr(2,'SPY'),10,s,pos_stop=0.15,dd_guard=0.12)),
 ('B','TREND10 (>200SMA near 52wk-hi) [ported]',lambda s:monthly_rot_g(_trend_sel,10,s)),
 ('B','Leading-sector rotation [ported]',lambda s:monthly_rot_g(_leadsec_sel,10,s)),
 ('X','NULL CHECK (selector returns nothing)',lambda s:monthly_rot_g(lambda j,n:[],10,s)),
 ('A','QQQ buy-hold [BENCHMARK]',lambda s:bh(QQ,s)),
 ('A','SPY buy-hold',lambda s:bh(SP,s)),
 ('A','XLK buy-hold [ACCOUNT CORE]',lambda s:bh(XL,s)),
 ('B','V4BLEND (50% XLK + 50% ROT10) [registered]',lambda s:_blend(bh(XL,s),monthly_rot(None,lc121,10,s),0.5)),
 ('A','Faber SMA200 QQQ (insurance)',faber),
 ('A','80/20 QQQ+2x-trend',lambda s:etf_curve(0.20,2,s)),
 ('A','60/40 QQQ+2x-trend',lambda s:etf_curve(0.40,2,s)),
 ('A','80/20 QQQ+3x-trend',lambda s:etf_curve(0.20,3,s)),
 ('A','Sector top-2 SPDR monthly (rejected)',lambda s:monthly_rot(None,sect,2,s,stock=False)),
 ('B','TRUE PROD V3.6: MR alw-on F42 CASH idle',lambda s:stock_sim_cash(lambda d:(('mr',MRS,42) if NONPAUSE(d) else None),s)),
 ('B','V3.6 variant: MR alw-on F42 QQQ-core',lambda s:stock_sim(lambda d:(('mr',MRS,42) if NONPAUSE(d) else None),s)),
 ('B','PROD V3.4: MR always-on Fixed60',lambda s:stock_sim(lambda d:(('mr',MRS,60) if NONPAUSE(d) else None),s)),
 ('B','PROD V3.2: MR always-on Fixed30',lambda s:stock_sim(lambda d:(('mr',MRS,30) if NONPAUSE(d) else None),s)),
 ('B','PROD V3.1: MR always-on Hybrid21d',lambda s:stock_sim(lambda d:(('mr',MRS,'hyb21') if NONPAUSE(d) else None),s)),
 ('B','PROD tab MOM sleeve: ret20xvr F90',lambda s:stock_sim(lambda d:(('mom',MSPK,90) if R[d] not in {'DANGER','CRISIS'} else None),s)),
 ('B','MR dips-only Fixed42',lambda s:stock_sim(lambda d:(('mr',MRS,42) if R[d] in DIP else None),s)),
 ('B','MR short-exit RSI75cap21 always-on',lambda s:stock_sim(lambda d:(('mr',MRS,'rsi75c21') if NONPAUSE(d) else None),s)),
 ('B','MR stop-8% w42 always-on (rejected)',lambda s:stock_sim(lambda d:(('mr',MRS,'stop8w42') if NONPAUSE(d) else None),s)),
 ('B','MOM breakout r126 F90 uptrend-only',lambda s:stock_sim(lambda d:(('mom',MOMS,90) if R[d] in{'HEALTHY','PULLBACK','DIP_BUY'} else None),s)),
 ('B','MIX: MOM uptrend / MR bounce',lambda s:stock_sim(lambda d:(('mom',MOMS,90) if R[d] in{'HEALTHY','PULLBACK','DIP_BUY'} else (('mr',MRS,42) if R[d] in{'BEAR_BOUNCE','SHARP_DROP'} else None)),s)),
 ('B','Large-cap 12-1 rotation top10 monthly',lambda s:monthly_rot(None,lc121,10,s)),
]
def m(c):
    pk=np.maximum.accumulate(c);return c[-1]**(252/max(len(c)-1,1))-1,(c/pk-1).min()
IS=next(i for i,d in enumerate(dates) if d>='2016-06-01')
OOS=next(i for i,d in enumerate(dates) if d>='2023-01-03')
import os
os.makedirs('/tmp/curves',exist_ok=True)
out=[]
for tier,k,f in STRATS:
    try:
        ci=f(IS)[:OOS-IS]; co=f(OOS)
        ai,_=m(ci); ao,mo_=m(co)
        safe=''.join(c if c.isalnum() else '_' for c in k)[:40]
        with open(f'/tmp/curves/{safe}.csv','w') as fh:
            fh.write('\n'.join(str(float(x)) for x in co))
        out.append((tier,k,ai,ao,mo_))
    except Exception as ex:
        print(f"ERR {k}: {ex}")
qo=[r for r in out if 'BENCHMARK' in r[1]][0][3]
print(f"{'T':<2}{'strategy':<42}{'IS CAGR':>9}{'OOS CAGR':>10}{'OOS MDD':>9}{'OOSvQQQ':>9}")
print('-'*84)
for tier,k,ai,ao,mo_ in sorted(out,key=lambda x:-x[3]):
    print(f"{tier:<2}{k:<42}{ai*100:>8.1f}%{ao*100:>9.1f}%{mo_*100:>8.1f}%{(ao-qo)*100:>+8.1f}%")
print("\nT=A index/ETF only (no survivorship) | T=B stock-picking (survivor universe, -30% delist haircut applied)")
