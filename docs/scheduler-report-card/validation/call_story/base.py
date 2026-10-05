import sys, json, os
sys.path.insert(0,'backend'); import sf_client
SP=os.path.dirname(os.path.abspath(__file__))
tid, tag, a, b = sys.argv[1:5]
w=f"ServiceTerritoryId='{tid}' AND CreatedDate >= {a} AND CreatedDate < {b} AND RecordType.Name='ERS Service Appointment'"
n=sf_client.sf_rest_get('/services/data/v65.0/query',params={'q':f"SELECT COUNT() FROM ServiceAppointment WHERE {w}"})['totalSize']
sas=sf_client.sf_query_all(f"SELECT Id, AppointmentNumber, CreatedDate, Status, WorkType.Name, ERS_PTA__c, ActualStartTime FROM ServiceAppointment WHERE {w}")
assert len(sas)==n, (len(sas), n)
sas=[s for s in sas if 'drop' not in (s.get('WorkType') or {}).get('Name','').lower()]
hist=[]
ids=[s['Id'] for s in sas]
for i in range(0,len(ids),200):
    il=",".join(f"'{x}'" for x in ids[i:i+200])
    hist+=sf_client.sf_query_all(f"SELECT ServiceAppointmentId, Field, OldValue, NewValue, CreatedDate, CreatedBy.Name FROM ServiceAppointmentHistory WHERE ServiceAppointmentId IN ({il}) AND Field IN ('Status','ServiceTerritory','ERS_Assigned_Resource__c') ORDER BY CreatedDate ASC")
json.dump({'sas':sas,'hist':hist}, open(f"{SP}/base_{tag}.json",'w'), default=str)
print(tag, 'count', n, 'non-drop', len(sas), 'hist', len(hist))
