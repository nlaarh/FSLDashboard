import json, sys
from datetime import datetime, timezone, timedelta
def et(s):
    if not s: return None
    d=datetime.fromisoformat(s.replace('+0000','+00:00')); return (d-timedelta(hours=4)).strftime('%H:%M:%S')
d=json.load(open(sys.argv[1]))
sa=d['sa']; [x.pop('attributes',None) for x in [sa]]
print('SA', {k:v for k,v in sa.items() if v not in (None,False) and k!='attributes'})
print('WOLI', d['woli']); print('WO', {k:v for k,v in d['wo'].items() if v not in (None,False)})
print('SIBS', [(s['AppointmentNumber'],s['Status'],s['WorkType']['Name'],(s.get('ServiceTerritory') or {}).get('Name')) for s in d['sibling_sas']])
print('AR', [(a['ServiceResource']['Name'],a['ServiceResource'].get('ERS_Driver_Type__c'),a['CreatedBy']['Name'],et(a['CreatedDate'])) for a in d['ar']])
skip={'SchedEndTime','FSL__InternalSLRGeolocation__Latitude__s','FSL__InternalSLRGeolocation__Longitude__s','StateCode','CountryCode','ActualDuration','Latitude','Longitude'}
for h in d['hist']:
    if h['Field'] in skip: continue
    print(' ', et(h['CreatedDate']), h['Field'], '|', h['OldValue'], '->', h['NewValue'], '|', h['CreatedBy']['Name'], '/', (h['CreatedBy'].get('Profile') or {}).get('Name'))
for s in d['sms']: print(' SMS', et(s['CreatedDate']), s['Message_Definition__c'], s['Source_Flow__c'], s['Outcome__c'], s.get('Checkpoint_Minutes__c'), s.get('MEU_Resolution__c'), 'SA' if s.get('Service_Appointment__c') else '')
print('SURVEY', d['survey'])
