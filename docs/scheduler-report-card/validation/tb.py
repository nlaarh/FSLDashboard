exec(open(__file__.rsplit('/',1)[0]+'/h.py').read())
import re, statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta
ID=re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
def P(s): return datetime.fromisoformat(s.replace('+0000','+00:00')) if s else None
sas=load('sa_0924'); hist=load('hist_0924')
H=defaultdict(list)
for h in sorted(hist,key=lambda h:h['CreatedDate']): H[h['ServiceAppointmentId']].append(h)
rs=[s for s in sas if 'drop' not in ((s['WorkType'] or {}).get('Name') or '').lower()]
print('member calls', len(rs), Counter(s['Status'] for s in rs))
out=[]
for s in rs:
    st_=[(P(h['CreatedDate']),h['NewValue'],h['CreatedBy']['Name']) for h in H[s['Id']] if h['Field']=='Status']
    ol=next((t for t,n,_ in st_ if n=='On Location'),None)
    cr=P(s['CreatedDate']); due=P(s['ERS_PTA_Due__c']); ast=P(s['ActualStartTime'])
    picks=[h for h in H[s['Id']] if h['Field']=='ERS_Assigned_Resource__c' and h['NewValue'] and not ID.match(h['NewValue'])]
    tm=[h for h in H[s['Id']] if h['Field']=='ServiceTerritory' and h['OldValue'] and h['NewValue'] and not ID.match(h['NewValue'])]
    human=any((h['CreatedBy'].get('Profile') or {}).get('Name')=='Membership User' and h['CreatedBy']['Name'] not in ('Mulesoft Integration','Replicant Integration User','IT System User') for h in H[s['Id']] if h['Field'] in ('Status','ERS_Assigned_Resource__c'))
    out.append(dict(num=s['AppointmentNumber'],id=s['Id'],drv=(s['Off_Platform_Driver__r'] or {}).get('Name'),ol=ol,ast=ast,cr=cr,
        resp=(ol-cr).total_seconds()/60 if ol else None, ok=(ol<=due) if ol and due and s['ERS_PTA__c'] and 0<s['ERS_PTA__c']<999 else None,
        ast_resp=(ast-cr).total_seconds()/60 if ast else None, picks=len(picks), tin=[(h['OldValue'],h['NewValue']) for h in tm], human=human, st=s['Status']))
r=[o['resp'] for o in out if o['resp'] and 0<o['resp']<1440]
pk=[o['ok'] for o in out if o['ok'] is not None]
print('On Location (SAHistory): n',len(r),'median',round(st.median(r)),'PTA met',sum(pk),'/',len(pk), round(100*sum(pk)/len(pk)))
a=[o['ast_resp'] for o in out if o['ast_resp'] is not None]
print('ActualStartTime-based (WRONG for Towbook): n',len(a),'median',round(st.median(a)), 'ast hour-of-day UTC', Counter(o['ast'].hour for o in out if o['ast']).most_common(4))
dd=[abs((o['ast']-o['ol']).total_seconds()/60) for o in out if o['ast'] and o['ol']]
print('ActualStart vs OnLoc |diff| median min', round(st.median(dd)), 'share >30min', round(100*sum(1 for x in dd if x>30)/len(dd)))
print('Off_Platform_Driver populated', sum(1 for o in out if o['drv']), 'distinct drivers', len(set(o['drv'] for o in out if o['drv'])))
per=Counter(o['drv'] for o in out if o['drv'])
print('calls/driver top', per.most_common(5), 'median', st.median(per.values()))
print('territory moves in', sum(1 for o in out if o['tin']), Counter(x for o in out for x in o['tin']).most_common(4))
print('human-touched (Membership User on Status/Assigned)', sum(o['human'] for o in out))
for o in out[:3]: print('  ex', o['num'], o['id'], 'created', o['cr'].strftime('%H:%M'), 'onloc', o['ol'].strftime('%H:%M') if o['ol'] else '-', 'AST', o['ast'].strftime('%m-%d %H:%M') if o['ast'] else '-', 'driver', o['drv'], 'PTA ok', o['ok'])
