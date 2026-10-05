import json, os, sys, time
sys.path.insert(0, 'backend'); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sf_client as s
from flowkeys import from_json, from_xml
S = os.path.dirname(os.path.abspath(__file__))
LOCAL = '/Users/alaaroubi/Library/CloudStorage/OneDrive-AAAWesternandCentralNewYork/AAA/Dev/FSL/FSL/force-app/main/default/flows/'
names = ['AAA_ERS_Sent_SMS_when_call_is_not_accepted_by_a_driver', 'AAA_ERS_Sent_SMS_Not_Accepted_50mins', 'AAA_ERS_Sent_SMS_Not_Accepted_80mins']
q = "SELECT Id, DeveloperName, ActiveVersionId, LatestVersionId, LastModifiedDate, LastModifiedBy.Name FROM FlowDefinition WHERE DeveloperName IN (%s)" % ",".join(f"'{n}'" for n in names)
defs = s.sf_rest_get('/services/data/v65.0/tooling/query', params={'q': q})['records']
out = {}
for d in defs:
    print(d['DeveloperName'], 'active', d['ActiveVersionId'], 'latest', d['LatestVersionId'], d['LastModifiedDate'], (d.get('LastModifiedBy') or {}).get('Name'))
    time.sleep(0.5)
    r = s.sf_rest_get('/services/data/v65.0/tooling/query', params={'q': f"SELECT Id, VersionNumber, Status, LastModifiedDate, Metadata FROM Flow WHERE Id = '{d['ActiveVersionId']}'"})['records'][0]
    prod, loc = from_json(r['Metadata']), from_xml(LOCAL + d['DeveloperName'] + '.flow-meta.xml')
    prod.pop('status', None); loc.pop('status', None)
    diffs = {k: (loc.get(k), prod.get(k)) for k in set(prod) | set(loc) if json.dumps(prod.get(k), default=str, sort_keys=True) != json.dumps(loc.get(k), default=str, sort_keys=True)}
    print('  prod version', r['VersionNumber'], r['Status'], r['LastModifiedDate'], 'DIFFS vs 8/13 local:', json.dumps(diffs, default=str)[:1500] if diffs else 'none')
    out[d['DeveloperName']] = {'def': d, 'version': r['VersionNumber'], 'status': r['Status'], 'modified': r['LastModifiedDate'], 'diffs': diffs, 'prod': prod}
json.dump(out, open(S + '/flows_prod.json', 'w'), default=str, indent=1)
time.sleep(0.5)
desc = s.sf_rest_get('/services/data/v65.0/sobjects/SMS_Send_Log__c/describe')
print([f['name'] for f in desc['fields'] if f['custom']])
