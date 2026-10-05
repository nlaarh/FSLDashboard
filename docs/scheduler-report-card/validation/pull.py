exec(open(__file__.rsplit('/',1)[0]+'/h.py').read())
import sys
TER, DAY, S, E = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
tag=f"{TER[-4:]}_{DAY}"
W=f"ServiceTerritoryId='{TER}' AND CreatedDate>={S} AND CreatedDate<{E} AND RecordType.Name='ERS Service Appointment'"
n=sf_query(f"SELECT COUNT() FROM ServiceAppointment WHERE {W}")['totalSize']
sas=sf_query_all(f"""SELECT Id, AppointmentNumber, Status, CreatedDate, SchedStartTime, SchedEndTime, ActualStartTime, ActualEndTime, WorkType.Name,
 ERS_PTA__c, ERS_PTA_Due__c, ERS_Spotting_Datetime__c, ERS_Dispatch_Method__c, ERS_Assigned_Resource__c, ERS_Assigned_Resource__r.Name, Off_Platform_Driver__c, Off_Platform_Driver__r.Name,
 ParentRecordId, FSL__Scheduling_Policy_Used__c, FSL__Auto_Schedule__c, Latitude, Longitude, ERS_Tow_Pick_Up_Drop_off__c,
 ERS_Dispatched_Geolocation__Latitude__s, ERS_Dispatched_Geolocation__Longitude__s, ERS_Cancellation_Reason__c
 FROM ServiceAppointment WHERE {W}""")
print('SA count', n, 'pulled', len(sas)); assert n==len(sas)
ids=[r['Id'] for r in sas]
ar=[];hist=[]
for i in range(0,len(ids),150):
    il=",".join(f"'{x}'" for x in ids[i:i+150])
    ar+=sf_query_all(f"""SELECT Id, ServiceAppointmentId, ServiceResourceId, ServiceResource.Name, ServiceResource.ERS_Driver_Type__c, ServiceResource.IsActive,
      CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name, CreatedBy.UserType, FSL__UpdatedByOptimization__c, EstimatedTravelTime, FSL__EstimatedTravelDistanceTo__c
      FROM AssignedResource WHERE ServiceAppointmentId IN ({il})""")
    hist+=sf_query_all(f"""SELECT ServiceAppointmentId, Field, OldValue, NewValue, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name
      FROM ServiceAppointmentHistory WHERE ServiceAppointmentId IN ({il})
      AND Field IN ('Status','ERS_Assigned_Resource__c','ServiceTerritory','ERS_PTA__c','SchedStartTime')""")
print('AR', len(ar), 'hist', len(hist))
save(f'sa_{tag}',sas); save(f'ar_{tag}',ar); save(f'hist_{tag}',hist)
