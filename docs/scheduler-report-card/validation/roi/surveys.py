"""Surveys for sampled SAs: SA.ParentRecordId (WOLI) -> WorkOrderId -> Survey_Result__c.ERS_Work_Order__c. Read-only, sequential."""
import json, os, sys, time
sys.path.insert(0, 'backend')
from sf_client import sf_query_all, sf_query

S = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(f'{S}/rows.json'))['rows']
wolis = sorted({r['woli'] for r in rows if r['woli']})
q = lambda ids: ",".join(f"'{i}'" for i in ids)
prev = json.load(open(f'{S}/surveys.json')) if os.path.exists(f'{S}/surveys.json') else {'woli_wo': {}, 'surveys': []}
woli_wo = dict(prev['woli_wo'])
wolis = [w for w in wolis if w not in woli_wo]
new_wo = set()
for i in range(0, len(wolis), 200):
    for x in sf_query_all(f"SELECT Id, WorkOrderId FROM WorkOrderLineItem WHERE Id IN ({q(wolis[i:i+200])})"):
        woli_wo[x['Id']] = x['WorkOrderId']; new_wo.add(x['WorkOrderId'])
    time.sleep(0.5)
wos = sorted(new_wo)
surveys = list(prev['surveys'])
for i in range(0, len(wos), 200):
    w = f"ERS_Work_Order__c IN ({q(wos[i:i+200])})"
    n = sf_query(f"SELECT COUNT() FROM Survey_Result__c WHERE {w}")['totalSize']
    got = sf_query_all(f"SELECT Id, ERS_Work_Order__c, ERS_Overall_Satisfaction__c, ERS_Response_Time_Satisfaction__c, "
                       f"ERS_Survey_Completed_Date__c FROM Survey_Result__c WHERE {w}")
    assert len(got) == n, (n, len(got))
    surveys += got
    time.sleep(0.5)
json.dump({'woli_wo': woli_wo, 'surveys': surveys}, open(f'{S}/surveys.json', 'w'))
print('wolis', len(wolis), 'mapped', len(woli_wo), 'wos', len(wos), 'surveys', len(surveys))
