import sys, json, os
sys.path.insert(0,'backend'); import sf_client
SP=os.path.dirname(os.path.abspath(__file__))
q=sf_client.sf_query_all
def one(s):
    r=q(s); return r[0] if r else None
sa_id=sys.argv[1]
out={}
sa=one(f"""SELECT Id, AppointmentNumber, Status, CreatedDate, ActualStartTime, ActualEndTime, SchedStartTime,
 WorkType.Name, ServiceTerritoryId, ServiceTerritory.Name, ERS_Parent_Territory__r.Name, AAA_ERS_Account_Facility__r.Name,
 ERS_PTA__c, ERS_PTA_Due__c, ERS_Spotting_Datetime__c, ERS_Spotting_Number__c, ERS_For_Spotting__c, ERS_Auto_Assign__c,
 ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c, ERS_Rejection_Reason__c, ERS_Reason_for_changing_Facility__c,
 ERS_Truck_not_Capable_Reason__c, ERS_Rejected_Datetime__c, ERS_Assigned_Datetime__c, AAA_ERS_Reason_for_Delay__c, Reason_For_Delay__c,
 FSL__InJeopardy__c, FSL__InJeopardyReason__c, FSL__Schedule_Mode__c, FSL__Pinned__c, Auto_Schedule_Requested__c, Auto_Schedule_Elapsed_Seconds__c,
 Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c, ERS_Tow_Pick_Up_Drop_off__c, ParentRecordId, ERS_Work_Order__c, FSSK__FSK_Work_Order__c,
 ERS_Dispatch_Method__c, WO_Priority_Code__c, ERS_Priority_Group__c, ERS_Gone_on_Arrival__c, RecordType.Name
 FROM ServiceAppointment WHERE Id='{sa_id}'""")
out['sa']=sa
woli=one(f"SELECT Id, LineItemNumber, Status, WorkType.Name, WorkOrderId FROM WorkOrderLineItem WHERE Id='{sa['ParentRecordId']}'")
out['woli']=woli
wo_id=woli['WorkOrderId']
out['wo']=one(f"""SELECT Id, WorkOrderNumber, Status, CreatedDate, Tow_Call__c, ERS_Call_Key__c, ERS_Source_Call_ID__c, ERS_Source_Call_Key__c,
 Source_System_ID__c, Source__c, Priority_Code__c, PTA__c, SMS_Opt_In__c, Trouble_Code__c, Resolution_Code__c, Clear_Code__c, Status_Reason__c,
 Facility_Name__c, Last_Spotted_Date__c, ERS_Dispatch_Date_Time__c, ERS_En_Route_Date_Time__c, ERS_On_Location_Date_Time__c, Completed_TimeStamp__c,
 ERS_Submitted_Date_Time__c, ERS_Assigned_Date_Time__c, ERS_Channel_Type__c FROM WorkOrder WHERE Id='{wo_id}'""")
wolis=q(f"SELECT Id, Status, WorkType.Name FROM WorkOrderLineItem WHERE WorkOrderId='{wo_id}'")
ids=",".join(f"'{w['Id']}'" for w in wolis)
out['wolis']=wolis
out['sibling_sas']=q(f"SELECT Id, AppointmentNumber, Status, WorkType.Name, ServiceTerritory.Name, CreatedDate, ERS_Work_Order__c FROM ServiceAppointment WHERE ParentRecordId IN ({ids}) ORDER BY CreatedDate")
out['hist']=q(f"""SELECT Field, OldValue, NewValue, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name, DataType
 FROM ServiceAppointmentHistory WHERE ServiceAppointmentId='{sa_id}' ORDER BY CreatedDate ASC, Id ASC""")
out['ar']=q(f"SELECT ServiceResource.Name, ServiceResource.ERS_Driver_Type__c, CreatedBy.Name, CreatedDate, LastModifiedDate FROM AssignedResource WHERE ServiceAppointmentId='{sa_id}'")
out['sms']=q(f"""SELECT Name, CreatedDate, Sent_At__c, Message_Definition__c, Source_Flow__c, Outcome__c, Error_Message__c, Checkpoint_Minutes__c,
 MEU_Resolution__c, Messaging_End_User__c, Service_Appointment__c FROM SMS_Send_Log__c WHERE Work_Order__c='{wo_id}' ORDER BY CreatedDate""")
out['survey']=q(f"SELECT Name, ERS_Overall_Satisfaction__c, ERS_Survey_Completed_Date__c FROM Survey_Result__c WHERE ERS_Work_Order__c='{wo_id}'")
for r in out['sms']: r.pop('attributes',None)
json.dump(out, open(f"{SP}/story_{sa['AppointmentNumber']}.json",'w'), indent=1, default=str)
print('saved', sa['AppointmentNumber'], 'hist', len(out['hist']), 'sms', len(out['sms']), 'sibs', len(out['sibling_sas']))
