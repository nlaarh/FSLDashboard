import json, sys, time
sys.path.insert(0, 'backend')
import sf_client as s
def Q(q):
    time.sleep(0.4)
    try: return s.sf_query_all(q)
    except Exception as e: print('  ERR', str(e)[:200]); return []
def T(q):
    time.sleep(0.4)
    try: return s.sf_rest_get('/services/data/v65.0/tooling/query', params={'q': q})['records']
    except Exception as e: print('  ERR', str(e)[:200]); return []
names = ['IT System User', 'Mulesoft Integration', 'Replicant Integration User', 'Platform Integration User', 'FSL System User']
users = Q("SELECT Id, Name, Username, UserType, IsActive, Profile.Name, CreatedDate, LastLoginDate FROM User WHERE Name IN (%s)" % ",".join(f"'{n}'" for n in names))
ids = {u['Id']: u['Name'] for u in users}
for u in users: print(u['Name'], '|', u['Username'], '|', u['UserType'], '|', (u.get('Profile') or {}).get('Name'), '| active', u['IsActive'], '| last login', u['LastLoginDate'])
inn = ",".join(f"'{i}'" for i in ids)
print('\nPermission sets:')
for r in Q(f"SELECT AssigneeId, PermissionSet.Name, PermissionSet.IsOwnedByProfile, PermissionSetGroup.DeveloperName FROM PermissionSetAssignment WHERE AssigneeId IN ({inn}) AND PermissionSet.IsOwnedByProfile = false"):
    print(' ', ids[r['AssigneeId']], '->', (r.get('PermissionSet') or {}).get('Name'), (r.get('PermissionSetGroup') or {}) and r['PermissionSetGroup'].get('DeveloperName'))
print('\nLogins last 7 days (Application, LoginType):')
for r in Q(f"SELECT UserId, Application, LoginType, COUNT(Id) n FROM LoginHistory WHERE UserId IN ({inn}) AND LoginTime = LAST_N_DAYS:7 GROUP BY UserId, Application, LoginType"):
    print(' ', ids[r['UserId']], '|', r['Application'], '|', r['LoginType'], '|', r['n'])
print('\nAsync Apex submitted by these users, last 2 days:')
for r in Q(f"SELECT CreatedById, ApexClass.Name, JobType, COUNT(Id) n FROM AsyncApexJob WHERE CreatedById IN ({inn}) AND CreatedDate = LAST_N_DAYS:2 GROUP BY CreatedById, ApexClass.Name, JobType"):
    print(' ', ids[r['CreatedById']], '|', r.get('Name'), r.get('JobType'), r['n'])
print('\nPlatform event subscriber run-as configs:')
for r in T("SELECT DeveloperName, UserId, BatchSize FROM PlatformEventSubscriberConfig"):
    print(' ', r['DeveloperName'], '| run as', ids.get(r['UserId'], r['UserId']))
print('\nOrg-wide policy stamp, ERS SAs created Aug 2026:')
for w in ["FSL__Scheduling_Policy_Used__c != null", "FSL__Scheduling_Policy_Used__c = null"]:
    print(' ', w, s.sf_query(f"SELECT COUNT() FROM ServiceAppointment WHERE RecordType.Name = 'ERS Service Appointment' AND CreatedDate >= 2026-08-01T04:00:00Z AND CreatedDate < 2026-09-01T04:00:00Z AND {w}")['totalSize'])
    time.sleep(0.4)
json.dump({'users': users}, open(sys.argv[1] + '/integ_users.json', 'w'), default=str)
