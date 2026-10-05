exec(open(__file__.rsplit('/',1)[0]+'/h.py').read())
import re, math, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
TAG=sys.argv[1]; DS=sys.argv[2]; DE=sys.argv[3]
D0=datetime.fromisoformat(DS.replace('Z','+00:00')); D1=datetime.fromisoformat(DE.replace('Z','+00:00'))
ID=re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
def P(s): 
    if not s: return None
    return datetime.fromisoformat(s.replace('+0000','+00:00').replace('Z','+00:00'))
def et(t): return (t-timedelta(hours=4)).strftime('%H:%M') if t else '-'
def hav(a,b,c,d):
    R=3958.8; p1,p2=math.radians(a),math.radians(c); dp=p2-p1; dl=math.radians(d-b)
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2; return 2*R*math.asin(math.sqrt(x))
sas=load(f'sa_{TAG}'); ar=load(f'ar_{TAG}'); hist=load(f'hist_{TAG}'); mem=load(f'mem_{TAG}')
ah=load(f'ah_{TAG}'); gps=load(f'gps_{TAG}'); ra=load(f'ra_{TAG}'); sk=load(f'sk_{TAG}')
try: wsk=load(f'woliskill_{TAG}')
except Exception: wsk=[]
P_STALE=int(os.environ.get('STALE',30)); FAR=float(os.environ.get('FAR',5)); WAITMIN=10
SYS_INT={'Mulesoft Integration','Replicant Integration User','IT System User'}
FSL_ENG={'Platform Integration User','FSL System User'}
def src(name,prof):
    if name in FSL_ENG: return 'FSL_ENGINE'
    if name in SYS_INT: return 'INTEGRATION'
    if prof=='Membership User': return 'HUMAN'
    return 'OTHER:'+str(name)
# names
srname={m['ServiceResourceId']:m['ServiceResource']['Name'] for m in mem}
for a in ar: srname[a['ServiceResourceId']]=a['ServiceResource']['Name']
name2id={v:k for k,v in srname.items()}
drivers=[m['ServiceResourceId'] for m in mem if m['ServiceResource']['ERS_Driver_Type__c'] in ('Fleet Driver','On-Platform Contractor Driver')]
dskills=defaultdict(set)
for x in sk: dskills[x['ServiceResourceId']].add(x['Skill']['MasterLabel'])
woreq=defaultdict(set)
for x in wsk: woreq[x['RelatedRecordId']].add(x['Skill']['MasterLabel'])
# shifts from AssetHistory
ev=defaultdict(list)
for a in ah:
    t=P(a['CreatedDate'])
    if a['NewValue'] and not a['OldValue']: ev[a['NewValue']].append((t,'in'))
    elif a['OldValue'] and not a['NewValue']: ev[a['OldValue']].append((t,'out'))
    elif a['OldValue'] and a['NewValue']: ev[a['OldValue']].append((t,'out')); ev[a['NewValue']].append((t,'in'))
shifts=defaultdict(list)
for d,es in ev.items():
    es.sort(); cur=None
    for t,k in es:
        if k=='in' and cur is None: cur=t
        elif k=='out' and cur is not None: shifts[d].append((cur,t)); cur=None
        elif k=='out' and cur is None: shifts[d].append((D0-timedelta(hours=10),t))  # logged in before lookback
    if cur is not None: shifts[d].append((cur,D1+timedelta(hours=2)))
truck_iv=defaultdict(list)
try: caps={a['Id']:{c.strip() for c in (a['ERS_Truck_Capabilities__c'] or '').split(';') if c.strip()} for a in load(f'assets_{TAG}')}
except FileNotFoundError: caps={}
_open={}
for a in sorted(ah,key=lambda a:a['CreatedDate']):
    t=P(a['CreatedDate'])
    if a['OldValue'] and (a['OldValue'],a['AssetId']) in _open: truck_iv[a['OldValue']].append((_open.pop((a['OldValue'],a['AssetId'])),t,a['AssetId']))
    if a['NewValue']: _open[(a['NewValue'],a['AssetId'])]=t
for (d,aid),t in _open.items(): truck_iv[d].append((t,D1+timedelta(hours=2),aid))
def truck_caps(d,t):
    for a,b,aid in truck_iv.get(d,[]):
        if a<=t<b: return caps.get(aid,set())
    return set()
def clip(iv): 
    a,b=max(iv[0],D0),min(iv[1],D1); return (a,b) if b>a else None
absn=defaultdict(list)
for r in ra:
    absn[r['ResourceId']].append((P(r['Start']),P(r['End']),r['Type']))
def on_shift(d,t):
    if not any(a<=t<b for a,b in shifts.get(d,[])): return False
    if any(a<=t<b for a,b,_ in absn.get(d,[])): return False
    return True
# GPS
glat=defaultdict(list); glon=defaultdict(list)
for g in gps:
    try: v=float(g['NewValue'])
    except: continue
    (glat if g['Field']=='LastKnownLatitude' else glon)[g['ServiceResourceId']].append((P(g['CreatedDate']),v))
for x in (glat,glon):
    for k in x: x[k].sort()
def pos(d,t,stale=P_STALE,slack=5):
    cut=t+timedelta(minutes=slack); la=lo=None; lt=None
    for ts,v in reversed(glat.get(d,[])):
        if ts<=cut: la=v; lt=ts; break
    for ts,v in reversed(glon.get(d,[])):
        if ts<=cut: lo=v; break
    if la is None or lo is None: return None
    if stale is not None and (t-lt).total_seconds()/60>stale: return None
    return (la,lo,lt)
# per SA
H=defaultdict(list)
for h in sorted(hist,key=lambda h:h['CreatedDate']): H[h['ServiceAppointmentId']].append(h)
ARm={a['ServiceAppointmentId']:a for a in ar}
TERM={'Completed','Unable to Complete','Cancel Call - Service Not En Route','Cancel Call - Service En Route','Canceled','No-Show'}
recs=[]
for s in sas:
    wt=(s['WorkType'] or {}).get('Name') or ''
    if 'drop' in wt.lower(): continue
    r=dict(id=s['Id'],num=s['AppointmentNumber'],wt=wt,status=s['Status'],created=P(s['CreatedDate']),pta=s['ERS_PTA__c'],due=P(s['ERS_PTA_Due__c']),
           lat=s['Latitude'],lon=s['Longitude'],ast=P(s['ActualStartTime']),aet=P(s['ActualEndTime']))
    a=ARm.get(s['Id'])
    r['chan']=a['ServiceResource']['ERS_Driver_Type__c'] if a else 'NO_AR'
    r['drv']=a['ServiceResourceId'] if a else None
    r['src']=src(a['CreatedBy']['Name'],(a['CreatedBy'].get('Profile') or {}).get('Name')) if a else None
    r['ar_by']=a['CreatedBy']['Name'] if a else None
    st_=[(P(h['CreatedDate']),h['NewValue'],h['CreatedBy']['Name']) for h in H[s['Id']] if h['Field']=='Status']
    def first(v): return next((t for t,n,_ in st_ if n==v),None)
    r['t_disp']=first('Dispatched'); r['t_acc']=first('Accepted'); r['t_er']=first('En Route'); r['t_ol']=first('On Location')
    r['t_end']=next((t for t,n,_ in st_ if n in TERM),None)
    asg=[(P(h['CreatedDate']),h['NewValue'],h['OldValue'],h['CreatedBy']['Name'],(h['CreatedBy'].get('Profile') or {}).get('Name')) for h in H[s['Id']]
         if h['Field']=='ERS_Assigned_Resource__c' and not ID.match(h['NewValue'] or '') and not (h['NewValue'] is None and ID.match(h['OldValue'] or ''))]
    picks=[x for x in asg if x[1]]
    r['picks']=picks
    if not r['drv'] and picks:
        lastd=[x[1] for x in picks if x[1]][-1]
        if name2id.get(lastd) in drivers:
            r['drv']=name2id[lastd]; r['chan']=next(m['ServiceResource']['ERS_Driver_Type__c'] for m in mem if m['ServiceResourceId']==r['drv']); r['no_ar_fallback']=True
    r['first_src']=src(picks[0][3],picks[0][4]) if picks else None
    r['src_ar']=r['src']
    r['src']=src(picks[-1][3],picks[-1][4]) if (picks and r['drv']) else None
    r['pullbacks']=sum(1 for t,n,_ in st_ if n=='Spotted' and any(t2<t and n2 in ('Dispatched','Accepted','En Route') for t2,n2,_ in st_))
    r['last_pick_by']=picks[-1][3] if picks else None
    fin=[x for x in picks if r['drv'] and name2id.get(x[1])==r['drv']]
    r['t_asg']=fin[-1][0] if fin else (picks[-1][0] if picks else None)
    r['t_first']=picks[0][0] if picks else None
    r['n_pre']=sum(1 for x in picks if r['t_disp'] is None or x[0]<r['t_disp'])
    drvs_after=[x[1] for x in picks if r['t_disp'] and x[0]>r['t_disp']]
    r['post_reassign']=len(drvs_after)
    r['opt_touch']=any(x[3] in FSL_ENG for x in picks)
    tch=[h for h in H[s['Id']] if h['Field']=='ServiceTerritory' and h['OldValue'] and h['NewValue'] and not ID.match(h['NewValue'])]
    r['terr_moves']=[(h['OldValue'],h['NewValue']) for h in tch]
    r['req']=woreq.get(s['ParentRecordId'],set())
    # arrival
    hol=r['t_ol']
    r['arr']=r['ast'] if r['chan'] in ('Fleet Driver','On-Platform Contractor Driver') else hol
    r['arr_hist']=hol
    r['resp']=(r['arr']-r['created']).total_seconds()/60 if r['arr'] else None
    r['pta_ok']=(r['arr']<=r['due']) if (r['arr'] and r['due'] and r['pta'] and 0<r['pta']<999) else None
    r['pta_ok_created']=(r['arr']<=r['created']+timedelta(minutes=r['pta'])) if (r['arr'] and r['pta'] and 0<r['pta']<999) else None
    recs.append(r)
R={r['id']:r for r in recs}
print('N SA (non drop-off)', len(recs), Counter(r['chan'] for r in recs))
print('AR.CreatedBy == last pick creator:', sum(1 for r in recs if r['ar_by'] and r['ar_by']==r['last_pick_by']), 'of', sum(1 for r in recs if r['ar_by']))
print('AR.CreatedBy source:', Counter(r['src_ar'] for r in recs))
print('FINAL decision source (last ERS_Assigned_Resource__c actor):', Counter(r['src'] for r in recs))
print('pullbacks (Dispatched/Accepted/EnRoute -> Spotted) SAs:', sum(1 for r in recs if r['pullbacks']))
print('cross: AR src vs final src', Counter((r['src_ar'],r['src']) for r in recs if r['src_ar']!=r['src']))
print('first-pick source:', Counter(r['first_src'] for r in recs))
print('optimizer touched any pick:', sum(r['opt_touch'] for r in recs))
print('AR creators:', Counter(r['ar_by'] for r in recs))
# arrival agreement
ag=[(r['ast']-r['arr_hist']).total_seconds()/60 for r in recs if r['ast'] and r['arr_hist']]
print('ActualStartTime vs SAHist OnLoc minutes diff: n',len(ag),'median',st.median(ag) if ag else None,'max abs',max(map(abs,ag)) if ag else None)
print('ActualStart present w/o OnLoc hist', sum(1 for r in recs if r['ast'] and not r['arr_hist']), 'OnLoc w/o ActualStart', sum(1 for r in recs if r['arr_hist'] and not r['ast']))
# outcomes
def summ(rs,lab):
    rr=[r['resp'] for r in rs if r['resp'] is not None and 0<r['resp']<1440]
    pk=[r['pta_ok'] for r in rs if r['pta_ok'] is not None]
    return f"{lab}: n={len(rs)} arrived={len(rr)} median_resp={round(st.median(rr)) if rr else '-'} mean={round(st.mean(rr)) if rr else '-'} PTA_met={sum(pk)}/{len(pk)}={round(100*sum(pk)/len(pk)) if pk else '-'}%"
print(summ(recs,'ALL'))
print('PTA due vs created+PTA disagreements', sum(1 for r in recs if r['pta_ok'] is not None and r['pta_ok']!=r['pta_ok_created']))
for k in ['FSL_ENGINE','INTEGRATION','HUMAN']: print(summ([r for r in recs if r['src']==k],'final='+k))
for k in ['FSL_ENGINE','INTEGRATION','HUMAN']: print(summ([r for r in recs if r['first_src']==k],'first='+k))
print(summ([r for r in recs if r['opt_touch']],'opt-touched'), '|', summ([r for r in recs if not r['opt_touch'] and r['picks']],'never-opt'))
# bounces
print('garage bounces SAs', sum(1 for r in recs if r['terr_moves']), Counter(m for r in recs for m in r['terr_moves']))
print('post-dispatch driver reassign SAs', sum(1 for r in recs if r['post_reassign']), 'pre-dispatch picks/SA', Counter(r['n_pre'] for r in recs))
print('distinct drivers per SA', Counter(len(set(x[1] for x in r['picks'])) for r in recs))
# skills check
skm=[(r['num'],srname.get(r['drv']),r['req']-dskills[r['drv']]) for r in recs if r['drv'] and r['req'] and not r['req']<=dskills[r['drv']]]
print('final driver lacks strict WOLI skills:', len(skm), 'of', sum(1 for r in recs if r['drv'] and r['req']), Counter(frozenset(x[2]) for x in skm))
skany=[1 for r in recs if r['drv'] and r['req'] and not (r['req']&dskills[r['drv']])]
print('final driver has NONE of required skills:', len(skany))
save(f'recs_{TAG}', recs)
import glob
try:
    ors=[P(x['FSL__Optimization_Request__r']['CreatedDate']) for x in load(f'orj_{TAG}')]+[P(x['CreatedDate']) for x in load(f'orr_{TAG}')]
    fe=[x for r in recs for x in r['picks'] if x[3]=='Platform Integration User']
    near=sum(1 for x in fe if any(-60<=(x[0]-o).total_seconds()<=180 for o in ors))
    print('Platform Integration User assignment events within -1..+3 min of an In-Day/RSO request for this territory/its drivers:', near, 'of', len(fe))
except FileNotFoundError: pass
# ---------- driver-day ----------
def busy_iv(r):
    a=r['t_asg']; b=r['t_end'] or r['aet']
    return (a,b) if a and b and b>a else None
jobs=defaultdict(list)
for r in recs:
    if r['drv'] and busy_iv(r): jobs[r['drv']].append((busy_iv(r),r))
def open_jobs(d,t,exclude=None):
    return [r for (a,b),r in jobs.get(d,[]) if a<=t<b and r['id']!=exclude]
mins=[D0+timedelta(minutes=i) for i in range(int((D1-D0).total_seconds()//60))]
rows=[]
for d in drivers:
    osm=sum(1 for t in mins if on_shift(d,t))
    if osm==0 and not jobs.get(d): continue
    done=[r for _,r in jobs.get(d,[]) if r['status']=='Completed']
    assigned=len(jobs.get(d,[]))
    busy=sum(1 for t in mins if open_jobs(d,t))
    idle=sum(1 for t in mins if on_shift(d,t) and not open_jobs(d,t))
    mx=max([len(open_jobs(d,t)) for t in mins] or [0])
    stk=sum(1 for t in mins if len(open_jobs(d,t))>=2)
    rows.append(dict(d=srname.get(d),onshift_h=round(osm/60,1),assigned=assigned,completed=len(done),busy_h=round(busy/60,1),idle_h=round(idle/60,1),max_conc=mx,stack_min=stk,
                    jph=round(assigned/(osm/60),2) if osm>=60 else None, shifts=[(et(a),et(b)) for a,b in shifts.get(d,[]) if clip((a,b))]))
    rows[-1]['util']=round(sum(1 for t in mins if on_shift(d,t) and open_jobs(d,t))/osm,2) if osm else None
    rows[-1]['asg_offshift']=sum(1 for (a,b),r in jobs.get(d,[]) if not on_shift(d,a))
rows.sort(key=lambda x:-x['assigned'])
print('\nDRIVER-DAY'); 
for x in rows: print(x)
act=[x for x in rows if x['onshift_h']>=1]
asg=[x['assigned'] for x in act]
print('drivers on shift>=1h', len(act), 'calls/driver median', st.median(asg), 'max', max(asg), 'top/median', round(max(asg)/st.median(asg),2) if st.median(asg) else None)
jp=[x['jph'] for x in act if x['jph'] is not None]
print('jobs/onshift-hour median', st.median(jp), 'min', min(jp), 'max', max(jp))
print('drivers with max_conc>=2', sum(1 for x in rows if x['max_conc']>=2), 'max overall', max(x['max_conc'] for x in rows), 'total stacked driver-min', sum(x['stack_min'] for x in rows))
# idle while waiting
def waiting(t):
    out=[]
    for r in recs:
        if r['created']<=t and (r['t_er'] or r['t_end'] or D1)>t and (t-r['created']).total_seconds()/60>=WAITMIN:
            if r['t_end'] and r['t_end']<=t: continue
            out.append(r)
    return out
iw=0; iw_min=0; iwq=0; peak=[]
for t in mins:
    idle=[d for d in drivers if on_shift(d,t) and not open_jobs(d,t)]
    w=waiting(t)
    if w and idle: iw+=len(idle); iw_min+=1; iwq+=min(len(idle),len(w))
iwr=0
for t in mins[::2]:
    w=waiting(t)
    if not w: continue
    for d in drivers:
        if not on_shift(d,t) or open_jobs(d,t): continue
        p=pos(d,t)
        if p and any(r['lat'] and hav(p[0],p[1],r['lat'],r['lon'])<=15 for r in w): iwr+=2
print(f'idle driver-hours while a call waited >={WAITMIN}m AND idle driver within 15 mi of it (GPS): {round(iwr/60,1)} h')
print(f'idle driver-hours while >=1 call waited >={WAITMIN}m: {round(iw/60,1)} h over {iw_min} clock-minutes; matched (min(idle,waiting)) {round(iwq/60,1)} h')
# queue wait = assigned->en route
qw=[(r['t_er']-r['t_asg']).total_seconds()/60 for r in recs if r['t_er'] and r['t_asg'] and r['t_er']>r['t_asg']]
print('queue wait final-assign -> En Route: n',len(qw),'median',round(st.median(qw)),'p90',round(sorted(qw)[int(.9*len(qw))]))
dw=[(r['t_disp']-r['t_asg']).total_seconds()/60 for r in recs if r['t_disp'] and r['t_asg'] and r['t_disp']>=r['t_asg']]
print('final-assign -> Dispatched median', round(st.median(dw),1) if dw else None)
cw=[(r['t_first']-r['created']).total_seconds()/60 for r in recs if r['t_first']]
print('created -> first pick median min', round(st.median(cw),1))
# ---------- closest driver ----------
def eligible(d,r,mode):
    if mode=='strict': return r['req']<=dskills[d] if r['req'] else True
    if mode=='any': return bool(r['req']&dskills[d]) if r['req'] else True
    if mode=='combo': return r['req']<=(dskills[d]|truck_caps(d,r.get('_t') or r['t_asg'] or r['created'])) if r['req'] else True
    return True
SKMODE=os.environ.get('SKMODE','any')
cl=[]
for r in recs:
    if not r['drv'] or not r['t_asg'] or not r['lat']: continue
    t=r['t_asg']
    cands=[]
    for d in drivers:
        is_act=(d==r['drv'])
        if not is_act and not on_shift(d,t): continue
        if not is_act and not eligible(d,r,SKMODE): continue
        p=pos(d,t)
        if not p: 
            if is_act: cands.append(dict(d=d,dist=None,act=True,open=len(open_jobs(d,t,r['id']))))
            continue
        cands.append(dict(d=d,dist=hav(p[0],p[1],r['lat'],r['lon']),act=is_act,open=len(open_jobs(d,t,r['id']))))
    act=next((c for c in cands if c['act']),None)
    g=[c for c in cands if c['dist'] is not None]
    if not act or act['dist'] is None or not g:
        cl.append(dict(r=r,graded=False,why='no GPS for assigned driver' if act else 'assigned driver missing')); continue
    best=min(g,key=lambda c:c['dist']); free=[c for c in g if c['open']==0]
    bestfree=min(free,key=lambda c:c['dist']) if free else None
    cl.append(dict(r=r,graded=True,act=act,best=best,bestfree=bestfree,n=len(g),
        picked=best['act'],extra=act['dist']-best['dist'],extra_free=(act['dist']-bestfree['dist']) if bestfree else None,
        idle_closer=[c for c in free if c['dist']<act['dist']-0.01 and not c['act']]))
gr=[c for c in cl if c['graded']]
print(f'\nCLOSEST (skill mode={SKMODE}, stale<={P_STALE}m, at final-assign time): graded {len(gr)}/{len(cl)}; ungraded reasons', Counter(c['why'] for c in cl if not c['graded']))
fr=[c for c in gr if c['bestfree']]
print(' closest FREE picked', sum(1 for c in fr if c['bestfree']['act']), 'of', len(fr), ' extra_free>FAR', sum(1 for c in fr if c['extra_free']>FAR), 'extra_free>2', sum(1 for c in fr if c['extra_free']>2))
print(' closest picked', sum(c['picked'] for c in gr), f"{round(100*sum(c['picked'] for c in gr)/len(gr))}%", ' extra miles total', round(sum(c['extra'] for c in gr),1), 'median extra when not closest', round(st.median([c['extra'] for c in gr if not c['picked']]),1) if any(not c['picked'] for c in gr) else 0)
print(' within 2mi of closest', sum(1 for c in gr if c['extra']<=2))
print(' assigned driver had other open job at assign', sum(1 for c in gr if c['act']['open']>0), ' ...and an idle qualified driver was closer', sum(1 for c in gr if c['act']['open']>0 and c['idle_closer']))
for k in ['FSL_ENGINE','INTEGRATION','HUMAN']:
    g2=[c for c in gr if c['r']['src']==k]
    if g2: print(f'  final={k}: n={len(g2)} closest={sum(c["picked"] for c in g2)} ({round(100*sum(c["picked"] for c in g2)/len(g2))}%) extra_mi_sum={round(sum(c["extra"] for c in g2),1)}')
save(f'cl_{TAG}', [dict(id=c['r']['id'],graded=c['graded'],**({k:c[k] for k in ('picked','extra','extra_free','n')} if c['graded'] else {})) for c in cl])
# simulate_day replica
rep=[]
for r in recs:
    if not r['drv'] or not r['t_first'] or not r['lat']: continue
    t=r['t_first']; g=[]
    for d in drivers:
        p=pos(d,t,stale=None)
        if p: g.append((hav(p[0],p[1],r['lat'],r['lon']),d,(t-p[2]).total_seconds()/60))
    if not g or r['drv'] not in [x[1] for x in g]: continue
    b=min(g); rep.append((b[1]==r['drv'], b[2]))
print(f' simulate_day-replica (no truck gate, no staleness, first-pick time, WorkType skills=none): closest {sum(x[0] for x in rep)}/{len(rep)} = {round(100*sum(x[0] for x in rep)/len(rep)) if rep else "-"}%; closest-candidate GPS age >60m in {sum(1 for x in rep if x[1]>60)} SAs')
# ---------- verdicts ----------
CL={c['r']['id']:c for c in cl}
def idle_qualified_at(r,t,maxd=None):
    out=[]
    for d in drivers:
        if d==r['drv'] or not on_shift(d,t) or open_jobs(d,t) or not eligible(d,r,SKMODE): continue
        p=pos(d,t)
        if not p: continue
        dist=hav(p[0],p[1],r['lat'],r['lon'])
        if maxd is None or dist<=maxd: out.append((d,dist))
    return out
V=[]
def cap_window(r, d_act, start=None, end=None, need=5):
    t=start or r['created']; end=end or r['t_asg']; run=0
    while t<=end:
        if idle_qualified_at(r,t,maxd=d_act): 
            run+=1
            if run>=need: return True
        else: run=0
        t+=timedelta(minutes=2)
    return False
for r in recs:
    tags=[]
    if r['src'] in ('INTEGRATION','HUMAN'): tags.append('BYPASSED_OPTIMIZER')
    if r['src']=='HUMAN': tags.append('HUMAN_FINAL')
    if r['n_pre']>=3: tags.append('OPTIMIZER_CHURN')
    if r['t_disp'] and r['t_asg'] and (r['t_disp']-r['t_asg']).total_seconds()/60>10: tags.append('SLOW_RELEASE')
    if r['drv'] and r['req'] and r['t_asg'] and not (r['req']<=(dskills[r['drv']]|truck_caps(r['drv'],r['t_asg']))): tags.append('SKILL_MISMATCH')
    c=CL.get(r['id'])
    missed=False
    if c and c.get('graded') and c['act']['open']>0 and r['t_er']:
        missed=cap_window(r, c['act']['dist'], start=r['t_asg'], end=r['t_er'])
        if missed: tags.append('MISSED_REBALANCE')
    if not r['drv'] or r['chan'] not in ('Fleet Driver','On-Platform Contractor Driver'):
        v='NOT_GRADED'
    elif r['terr_moves']:
        v='INBOUND_CASCADE'
    elif r['pullbacks'] or r['post_reassign']:
        v='BOUNCED'
    elif not c or not c['graded']:
        v='UNVERIFIABLE'
    elif c['act']['open']>0 and c['idle_closer']:
        v='STACKED'
    elif c['extra_free'] is not None and c['extra_free']>FAR and c['bestfree'] and not c['bestfree']['act']:
        v='FAR_PICK'
    elif r['pta_ok'] is False:
        if missed or cap_window(r, c['act']['dist']+FAR, end=r['t_asg'], need=1): v='LATE_DESPITE_CAPACITY'
        elif c['act']['open']==0 and (r['t_asg']-r['created']).total_seconds()/60<=10: v='LATE_EXECUTION'
        else: v='CAPACITY_SHORT'
    elif r['arr'] is None:
        v='GOOD_NO_ARRIVAL'
    else:
        v='GOOD'
    r['verdict']=v; r['tags']=tags; V.append(r)
print('\nVERDICTS', Counter(r['verdict'] for r in V))
print('TAGS', Counter(t for r in V for t in r['tags']))
for v in sorted(set(r['verdict'] for r in V)):
    ex=[r for r in V if r['verdict']==v][:3]
    for r in ex:
        c=CL.get(r['id']) or {}
        print(f"  {v:24} {r['num']} {r['id']} {r['wt']:8} created {et(r['created'])} assign {et(r['t_asg'])} by {r['last_pick_by']} (AR:{r['ar_by']}) -> {srname.get(r['drv'])} open={c.get('act',{}).get('open') if c.get('graded') else '-'} dist={round(c['act']['dist'],1) if c.get('graded') else '-'} closest={srname.get(c['best']['d']) if c.get('graded') else '-'}@{round(c['best']['dist'],1) if c.get('graded') else '-'} resp={round(r['resp']) if r['resp'] else '-'} PTA={r['pta']} ok={r['pta_ok']} status={r['status']} picks={len(r['picks'])} tags={r['tags']}")
save(f'verdicts_{TAG}', [dict(id=r['id'],num=r['num'],verdict=r['verdict'],tags=r['tags'],src=r['src'],hour=(r['created']-timedelta(hours=4)).hour,wt=r['wt'],pta_ok=r['pta_ok'],resp=r['resp']) for r in V])
# by hour demand
print('\nBY HOUR (ET): calls created, on-shift drivers avg, PTA met, verdict mix')
for hh in range(24):
    rs=[r for r in V if (r['created']-timedelta(hours=4)).hour==hh]
    if not rs: continue
    t0=D0+timedelta(hours=hh); osd=st.mean([sum(1 for d in drivers if on_shift(d,t0+timedelta(minutes=m))) for m in range(0,60,10)])
    pk=[r['pta_ok'] for r in rs if r['pta_ok'] is not None]
    print(f"  {hh:02d} calls={len(rs)} drivers_on={round(osd,1)} PTA={sum(pk)}/{len(pk)} {dict(Counter(r['verdict'] for r in rs))}")

# ---------- qualified & available but not picked ----------
print('\nQUALIFIED-AVAILABLE-NOT-PICKED (final decision time; on truck, not absent, GPS<=%dm)'%P_STALE)
def alt_counts(when):
    out={}
    for mode in ('strict','any','combo','none'):
        a=b=c=n=0; exs=[]
        for r in recs:
            if not r['drv'] or not r['lat'] or r['terr_moves']: continue
            t=r['t_asg'] if when=='final' else r['t_first']
            if not t: continue
            r['_t']=t
            pa=pos(r['drv'],t)
            if not pa: continue
            da=hav(pa[0],pa[1],r['lat'],r['lon']); oa=len(open_jobs(r['drv'],t,r['id']))
            n+=1; fa=fb=fc=False
            for d in drivers:
                if d==r['drv'] or not on_shift(d,t) or not eligible(d,r,mode): continue
                p=pos(d,t)
                if not p: continue
                dd=hav(p[0],p[1],r['lat'],r['lon']); od=len(open_jobs(d,t,r['id']))
                if dd<da-0.5:
                    fa=True
                    if od<oa: fb=True
                    if od==0: fc=True; 
                    if od<oa and len(exs)<3 and fb: exs.append((r['num'],srname[r['drv']],round(da,1),oa,srname[d],round(dd,1),od))
            a+=fa; b+=fb; c+=fc
        out[mode]=(n,a,b,c,exs)
        print(f"  [{when}] skills={mode:6} graded={n}  >=1 qualified closer(by>0.5mi)={a}  closer AND less loaded={b}  closer AND idle={c}")
    return out
o=alt_counts('final'); 
for e in o['combo'][4]: print('     example(combo) SA, picked, pick_mi, pick_open, alt, alt_mi, alt_open:', e)
alt_counts('first')
fe=[r for r in recs if r['src']=='FSL_ENGINE' and r['drv'] and r['req']]
for k in ('FSL_ENGINE','INTEGRATION','HUMAN'):
    fk=[r for r in recs if r['src']==k and r['drv'] and r['req'] and r['t_asg']]
    print(f'{k} final picks meeting WOLI skills vs (SR skills + logged-in truck caps):', sum(1 for r in fk if r['req']<=(dskills[r['drv']]|truck_caps(r['drv'],r['t_asg']))), 'of', len(fk))
print('FSL_ENGINE final picks meeting strict WOLI skills:', sum(1 for r in fe if r['req']<=dskills[r['drv']]), 'of', len(fe))

cov=[0,0]
for d in drivers:
    for t in mins[::5]:
        if on_shift(d,t):
            cov[1]+=1; cov[0]+= 1 if pos(d,t) else 0
print('GPS coverage: on-shift driver-minutes with fix <=%dm: %d/%d = %d%%'%(P_STALE,cov[0],cov[1],round(100*cov[0]/max(cov[1],1))))
rat=[]
for r in recs:
    a=ARm.get(r['id'])
    if not a or not a.get('FSL__EstimatedTravelDistanceTo__c') or not r['t_asg'] or not r['lat']: continue
    p=pos(r['drv'],r['t_asg'])
    if not p: continue
    h=hav(p[0],p[1],r['lat'],r['lon'])
    if h>0.3: rat.append((a['FSL__EstimatedTravelDistanceTo__c']/h, a['EstimatedTravelTime'], h))
if rat:
    rs=sorted(x[0] for x in rat)
    print('AR est travel distance / GPS haversine at final assign: n',len(rat),'median',round(st.median(rs),2),'p25',round(rs[len(rs)//4],2),'p75',round(rs[3*len(rs)//4],2))
