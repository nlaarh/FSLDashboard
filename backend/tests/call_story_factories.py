"""Synthetic Call Story raw bundles (fake ids and names) reproducing call-story-spec 10.4 step by step:
Towbook cascade (076DO declined 33 s, 630 declined 36 s), On-Platform driver rejected "Out of Area", 48.1 min with no
owner, 26 min parked in another region's SPOT, back to 076DO, Towbook accepted and re-based PTA 90 -> 120, arrival
from history (ActualStartTime empty), drop-off leg. Times are ET 2026-09-24 converted to UTC (+4 h)."""

SA, DROP, WO = '08pFAKE00000010AAA', '08pFAKE00000011AAA', '0WOFAKE00000001AAA'
DOMINGO, TABB = '005FAKE00000020AAA', '005FAKE00000021AAA'
_n = [0]


def _z(et_hms: str) -> str:
    h, m, s = (int(x) for x in et_hms.split(':'))
    return f'2026-09-24T{h + 4:02d}:{m:02d}:{s:02d}.000+0000'


def _h(et, field, new, old=None, actor='IT System User', profile='AAACRM Mulesoft Integration User', user='005FAKE00000099AAA',
       sa=SA):
    _n[0] += 1
    return {'Id': f'0shFAKE{_n[0]:08d}AAA', 'ServiceAppointmentId': sa, 'Field': field, 'OldValue': old, 'NewValue': new,
            'CreatedDate': _z(et), 'CreatedById': user, 'CreatedBy': {'Name': actor, 'Profile': {'Name': profile}}}


TB = dict(actor='Integrations Towbook', profile='Towbook Integrations')
DOM = dict(actor='Domingo Santiago', profile='Membership User', user=DOMINGO)


def towbook_cascade_raw() -> dict:
    _n[0] = 0
    hist = [
        _h('10:35:49', 'created', None, actor='Mulesoft Integration'),
        _h('10:35:49', 'ServiceTerritory', '076DO - TRANSIT AUTO DETAIL', actor='Mulesoft Integration'),
        _h('10:35:49', 'ServiceTerritory', '0HhFAKE00000076AAA', actor='Mulesoft Integration'),
        _h('10:35:49', 'ERS_PTA__c', '90', actor='Mulesoft Integration'),
        _h('10:35:49', 'Status', 'Spotted', 'None', actor='Mulesoft Integration'),
        _h('10:35:49', 'ERS_Assigned_Resource__c', 'Towbook-076DO'),
        _h('10:35:49', 'Status', 'Dispatched', 'Spotted'),
        _h('10:36:22', 'Status', 'Declined', 'Dispatched', **TB),
        _h('10:36:30', 'ServiceTerritory', '630 - BACHS TOWING', '076DO - TRANSIT AUTO DETAIL'),
        _h('10:36:30', 'ERS_Assigned_Resource__c', 'Towbook-630', 'Towbook-076DO'),
        _h('10:36:30', 'Status', 'Dispatched', 'Declined'),
        _h('10:37:06', 'Status', 'Declined', 'Dispatched', **TB),
        _h('10:37:21', 'ServiceTerritory', '642 - AUTO WRENCH CONNECTION', '630 - BACHS TOWING'),
        _h('10:37:21', 'ERS_Assigned_Resource__c', 'Anthony Tabb Jr', 'Towbook-630'),
        _h('10:37:21', 'Status', 'Assigned', 'Declined'),
        _h('10:41:01', 'Status', 'Dispatched', 'Assigned'),
        _h('10:43:20', 'Status', 'Rejected', 'Dispatched', actor='Anthony Tabb Jr', profile='Partner Community User', user=TABB),
        _h('11:04:00', 'ServiceNote', None, **TB),
        _h('11:05:00', 'SchedStartTime', '2026-09-24T15:10:00.000+0000', **TB),
        _h('11:20:00', 'Street', '12 Member Lane', '10 Member Lane', **DOM),
        _h('11:31:24', 'Status', 'Spotted', 'Rejected', **DOM),
        _h('11:31:45', 'ServiceTerritory', '000- ST SPOT', '642 - AUTO WRENCH CONNECTION', **DOM),
        _h('11:32:10', 'ERS_Assigned_Resource__c', '000-ST Spot', 'Anthony Tabb Jr', **DOM),
        _h('11:32:10', 'Status', 'Dispatched', 'Spotted', **DOM),
        _h('11:57:51', 'ServiceTerritory', '076DO - TRANSIT AUTO DETAIL', '000- ST SPOT', **DOM),
        _h('11:57:51', 'ERS_Assigned_Resource__c', None, '000-ST Spot', **DOM),
        _h('11:57:51', 'Status', 'Spotted', 'Dispatched', **DOM),
        _h('11:58:07', 'Status', 'Accepted', 'Spotted', **TB),
        _h('11:58:07', 'ERS_PTA__c', '120', '90', **TB),
        _h('12:13:36', 'Status', 'En Route', 'Accepted', **TB),
        _h('12:20:44', 'Status', 'On Location', 'En Route', **TB),
        _h('12:32:36', 'Status', 'Completed', 'On Location', **TB),
        _h('12:40:00', 'Status', 'Dispatched', 'Spotted', sa=DROP, **TB),
    ]
    sa = {'Id': SA, 'AppointmentNumber': 'SA-1000010', 'Status': 'Completed', 'CreatedDate': _z('10:35:49'),
          'ActualStartTime': None, 'ActualEndTime': _z('12:32:36'), 'WorkType': {'Name': 'Tow Pick-Up'},
          'RecordType': {'Name': 'ERS Service Appointment'}, 'ServiceTerritoryId': '0HhFAKE00000076AAA',
          'ServiceTerritory': {'Name': '076DO - TRANSIT AUTO DETAIL'}, 'ERS_Parent_Territory__c': '0HhFAKE0000GRIDAAA',
          'ERS_Parent_Territory__r': {'Name': 'WM003'}, 'ParentRecordId': '1WLFAKE00000010AAA',
          'ERS_PTA__c': 120, 'ERS_PTA_Due__c': _z('12:35:49'), 'ERS_Spotting_Datetime__c': _z('10:35:49'),
          'ERS_Spotting_Number__c': 2, 'ERS_Rejection_Reason__c': 'Out of Area', 'ERS_Rejected_Datetime__c': _z('10:43:18'),
          'ERS_Facility_Decline_Reason__c': 'Too busy', 'Off_Platform_Driver__r': {'Name': 'Adam Lucas'},
          'ERS_Tow_Pick_Up_Drop_off__c': DROP, 'Latitude': 43.0, 'Longitude': -78.8, 'City': 'Buffalo', 'PostalCode': '14201'}
    drop = {**sa, 'Id': DROP, 'AppointmentNumber': 'SA-1000011', 'WorkType': {'Name': 'Tow Drop-Off'},
            'CreatedDate': _z('10:35:50'), 'ERS_Tow_Pick_Up_Drop_off__c': None}
    sms = [{'CreatedDate': _z('10:35:53'), 'Sent_At__c': _z('10:35:53'),
            'Message_Definition__c': 'Message_1_Sent_upon_initial_call_placement', 'Outcome__c': 'Sent'},
           {'CreatedDate': _z('10:36:00'), 'Message_Definition__c': 'ERS_Send_SMS_Notification_to_Dispatchers_Contacts',
            'Outcome__c': 'Sent'},
           {'CreatedDate': _z('11:58:08'), 'Sent_At__c': _z('11:58:08'),
            'Message_Definition__c': 'Facility_Assigned_WO_Id_PTA_SMS', 'Outcome__c': 'Sent'}]
    matrix = {'rows': [{'rank': 2, 'garage': '076DO - TRANSIT AUTO DETAIL', 'worktype': 'Tow', 'hours': '24/7', 'slots': None},
                       {'rank': 3, 'garage': '630 - BACHS TOWING', 'worktype': 'Tow', 'hours': '24/7', 'slots': None},
                       {'rank': 4, 'garage': '642 - AUTO WRENCH CONNECTION', 'worktype': 'Tow', 'hours': '24/7', 'slots': None},
                       {'rank': 10, 'garage': '000- WNY M SPOT', 'worktype': 'Tow', 'hours': '24/7', 'slots': None},
                       {'rank': 11, 'garage': "202 - ELLMAN'S GARAGE INC.", 'worktype': 'Tow', 'hours': '24/7', 'slots': None}]}
    return {'resolution': {'input': '05164342', 'input_type': 'wo',
                           'wo': {'id': WO, 'number': '05164342', 'call_key': '084-20260924-05164342', 'source_call_id': None}},
            'wo': {'Id': WO, 'WorkOrderNumber': '05164342', 'CreatedDate': _z('10:33:58'), 'Tow_Call__c': True,
                   'Source__c': 'DRR', 'SMS_Opt_In__c': True, 'Resolution_Code__c': 'T100', 'ERS_Call_Key__c': '084-20260924-05164342'},
            'sas': [sa, drop], 'history': hist, 'assigned': [], 'sms': sms, 'sms_source': 'send_log', 'matrix': matrix,
            'survey': [], 'data_notes': [], 'sf_calls': 8, 'fetched_at': '2026-10-04T12:00:00+00:00', 'closed': True}


class FakeNorms:
    """Spec 5.2 first data: S7 pooled over all channels n 76, p75 2.0, p90 7.3, p95 14.7. Nothing else (floors only)."""

    def baseline(self, seg):
        if seg['kind'] == 'S7':
            return {'p50': 0.0, 'p75': 2.0, 'p90': 7.3, 'p95': 14.7, 'n': 76, 'key_level': 'segment_all_channels',
                    'days_covered': 20, 'window': ['2026-07-30', '2026-09-23']}
        return None
