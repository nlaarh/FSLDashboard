exec(open(__file__.rsplit('/',1)[0]+'/h.py').read())
from collections import Counter, defaultdict
sas=load('sa_GKAQ_0928'); hist=load('hist_GKAQ_0928')
p=defaultdict(list)
for h in sorted(hist,key=lambda h:h['CreatedDate']):
    if h['Field']=='ERS_PTA__c': p[h['ServiceAppointmentId']].append((h['CreatedDate'][11:19],h['OldValue'],h['NewValue'],h['CreatedBy']['Name']))
print('SAs with PTA hist', len(p), Counter(len(v) for v in p.values()))
for k in list(p)[:4]:
    s=[x for x in sas if x['Id']==k][0]; print(s['AppointmentNumber'], 'final',s['ERS_PTA__c'], 'created',s['CreatedDate'][11:19],'spot',(s['ERS_Spotting_Datetime__c'] or '')[11:19],'due',(s['ERS_PTA_Due__c'] or '')[11:19], p[k])
print('spot-created sec', Counter(round(((__import__('datetime').datetime.fromisoformat(s['ERS_Spotting_Datetime__c'][:19])-__import__('datetime').datetime.fromisoformat(s['CreatedDate'][:19])).total_seconds())/60) for s in sas if s['ERS_Spotting_Datetime__c']).most_common(8))
print('PTA vals', Counter(s['ERS_PTA__c'] for s in sas).most_common(10))
wts=sf_query_all("SELECT Id, Name FROM WorkType WHERE Name IN ('Battery','Tire','Lockout','Fuel / Miscellaneous','Locksmith','Tow Pick-Up','Tow Drop-Off','Winch Out')")
il=",".join(f"'{w['Id']}'" for w in wts)
sr=sf_query_all(f"SELECT RelatedRecordId, Skill.MasterLabel FROM SkillRequirement WHERE RelatedRecordId IN ({il})")
nm={w['Id']:w['Name'] for w in wts}
req=defaultdict(list)
for x in sr: req[nm[x['RelatedRecordId']]].append(x['Skill']['MasterLabel'])
print(dict(req)); save('wtskills', dict(req))
sk=load('sk_GKAQ_0928'); print(Counter(x['Skill']['MasterLabel'] for x in sk))
