"""Settle hold-length with ROLLING WALK-FORWARD (17 windows) at 8 slots,
fixed-timer vs hybrid — the same method that decided Fixed42 originally."""
exec(open('_master_harness3.py').read().split("def m(c):")[0])
NP_=lambda d: R[d] not in {'DANGER','WEAK','CRISIS'}
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
            w=Cf[e:min(e+cap+1,ND),col]; off=cap; peak=ep
            for j in range(1,len(w)):
                peak=max(peak,w[j])
                if j>=minh and (w[j]/ep-1)>arm and w[j]<peak*(1-trail): off=j;break
            EX[key][(i,col)]=off
    return key
import bisect
def win_sim(a,b,exitspec,slots=8):
    global NSLOT; old=NSLOT; NSLOT=slots
    cash=1.0;op=[]
    for d in range(a,b):
        k=[]
        for (x,inv,col,ep) in op:
            if d>=x:
                xi=min(x,ND-1,last_valid[col]) if last_valid[col]>=0 else min(x,ND-1)
                f=DELIST_HC if (x>last_valid[col] and last_valid[col]<ND-10) else 1.0
                cash+=inv*(Cf[xi,col]*f/ep)*(1-FEE-SLIP)
            else: k.append((x,inv,col,ep))
        op=k
        eq=cash+sum(inv*(Cf[d,col]/ep) for (_,inv,col,ep) in op)
        if NP_(d) and d+1<ND and ('mr',d) in sig:
            free=slots-len(op)
            hd={x[2] for x in op}
            for col in sorted(sig[('mr',d)],key=lambda x:-MRS[d,x]):
                if free==0:break
                if col in hd:continue
                ep=Ov[d+1,col]
                if not np.isfinite(ep) or ep<=0:continue
                h=EX[exitspec].get((d,col),21) if isinstance(exitspec,str) else exitspec
                al=min(eq/slots,cash)
                if al<=eq*0.02:break
                cash-=al;al*=(1-FEE-SLIP);op.append((d+1+h,al,col,ep));hd.add(col);free-=1
    NSLOT=old
    final=cash+sum(inv*(Cf[b-1,col]/ep)*(1-FEE-SLIP) for (_,inv,col,ep) in op)
    return final-1
starts=[]
y,mn=2018,1
while (y,mn)<=(2026,1):
    starts.append(f"{y:04d}-{mn:02d}-01"); mn+=6
    if mn>12: y,mn=y+1,mn-12
def dpos(s): return min(bisect.bisect_left(dates,s),ND-1)
specs=[('Fixed21',21),('Fixed42',42),('Fixed60',60),('Fixed90',90),
       ('Hyb-cap21',build_hyb(7,0.03,0.05,21)),('Hyb-cap60',build_hyb(7,0.03,0.05,60))]
res={n:[] for n,_ in specs}
print(f"{'window':<12}"+"".join(f"{n:>11}" for n,_ in specs))
for s in starts:
    a=dpos(s); b=dpos(f"{int(s[:4])+(1 if s[5:7]=='07' else 0)}-{'01' if s[5:7]=='07' else '07'}-01")
    if b-a<60: continue
    line=f"{s:<12}"
    for n,sp in specs:
        r=win_sim(a,b,sp); res[n].append(r); line+=f"{r*100:>10.1f}%"
    print(line)
print(f"\n{'exit':<12}{'wins':>6}{'avg':>9}{'median':>9}{'worst':>9}{'compounded':>12}")
best={n:0 for n,_ in specs}
for k in range(len(res[specs[0][0]])):
    w=max(specs,key=lambda ns:res[ns[0]][k])[0]; best[w]+=1
for n,_ in specs:
    v=np.array(res[n]); comp=np.prod(1+v)-1
    print(f"{n:<12}{best[n]:>6}{v.mean()*100:>8.1f}%{np.median(v)*100:>8.1f}%{v.min()*100:>8.1f}%{comp*100:>11.1f}%")
