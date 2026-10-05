"""Replay list flags: RAP, out of territory, coverage and why a member got no text."""

from report_card_flags import compose, text_state

NEW = '2026-10-01T15:00:00.000+0000'
OLD = '2026-08-20T15:00:00.000+0000'
SENT = {'Message_Definition__c': 'Message_1_Sent_upon_initial_call_placement', 'Outcome__c': 'Sent'}


def test_a_text_to_the_member_is_ok():
    assert text_state({'CreatedDate': NEW, 'SMS_Opt_In__c': True}, [SENT])['state'] == 'ok'


def test_only_opt_in_survey_or_dispatcher_texts_still_counts_as_no_text():
    logs = [{'Message_Definition__c': 'Opt_in_Confirmation', 'Outcome__c': 'Sent'},
            {'Message_Definition__c': 'Survey_IC_SMS', 'Outcome__c': 'Sent'}]
    assert text_state({'CreatedDate': NEW, 'SMS_Opt_In__c': True}, logs)['state'] == 'missing'


def test_opted_out_is_explained_and_is_not_the_problem():
    r = text_state({'CreatedDate': NEW, 'SMS_Opt_In__c': False}, [])
    assert r['state'] == 'opted_out' and 'not opted in' in r['tip']


def test_opted_in_with_nothing_sent_is_the_problem_and_says_why():
    r = text_state({'CreatedDate': NEW, 'SMS_Opt_In__c': True},
                   [{'Message_Definition__c': 'Message_1_Sent_upon_initial_call_placement', 'Outcome__c': 'Skipped-No-MEU'}])
    assert r['state'] == 'missing' and 'Skipped-No-MEU' in r['tip']
    assert 'even attempted' in text_state({'CreatedDate': NEW, 'SMS_Opt_In__c': True}, [])['tip']


def test_before_the_log_existed_is_no_data_not_a_failure():
    assert text_state({'CreatedDate': OLD, 'SMS_Opt_In__c': True}, [])['state'] == 'no_data'


def test_compose_maps_each_sa_to_its_work_order_flags():
    wo = {'Id': 'W1', 'CreatedDate': NEW, 'Type__c': 'RAP', 'Out_of_Territory__c': True, 'Coverage__c': 'PLUS', 'SMS_Opt_In__c': True}
    out = compose([{'id': 'S1', 'woli_id': 'L1'}, {'id': 'S2', 'woli_id': 'L9'}], {'L1': 'W1'}, {'W1': wo}, {'W1': [SENT]})
    assert out == {'S1': {'rap': True, 'out_of_territory': True, 'opted_in': True, 'coverage': 'Plus', 'text': out['S1']['text'], 'survey': None, 'wo_id': 'W1', 'cases': {'total': 0, 'open': 0, 'human': 0, 'auto': 0}}}


def test_pull_flags_uses_two_queries_and_skips_the_log_for_old_calls():
    class Fake:
        def __init__(self): self.sql = []
        def batched(self, template, ids, size=150):
            self.sql.append((template, list(ids)))
            if 'WorkOrderLineItem' in template:
                return [{'Id': 'L1', 'WorkOrderId': 'W1', 'WorkOrder': {'attributes': {}, 'CreatedDate': OLD, 'Type__c': 'RAP', 'SMS_Opt_In__c': True}}]
            return []
    from report_card_flags import pull_flags
    f = Fake()
    out = pull_flags([{'id': 'S1', 'woli_id': 'L1'}], f)
    assert len(f.sql) == 4 and f.sql[1][1] == [] and f.sql[2][1] == []      # work orders, text log (none), surveys (none), case counts        # old call: no log ids requested
    assert out['S1']['rap'] and out['S1']['text']['state'] == 'no_data'


def test_survey_is_the_latest_one_and_totally_satisfied_is_flagged():
    from report_card_flags import survey_of
    assert survey_of([]) is None
    rows = [{'ERS_Overall_Satisfaction__c': 'Dissatisfied', 'ERS_Survey_Completed_Date__c': '2026-10-01'},
            {'ERS_Overall_Satisfaction__c': 'Totally satisfied', 'ERS_Response_Time_Satisfaction__c': 'Satisfied',
             'ERS_Survey_Completed_Date__c': '2026-10-02'}]
    assert survey_of(rows) == {'overall': 'Totally satisfied', 'response': 'Satisfied', 'tech': None, 'nps': None, 'score': None, 'totally': True}
    assert survey_of([{'ERS_NPS__c': 7.0, 'ERS_Survey_Completed_Date__c': 'x'}])['score'] == 70
    assert survey_of([{'ERS_NPS__c': 0.0}])['score'] == 0   # a real zero is a score, not 'missing'


def test_case_counts_split_by_who_opened_them_and_whether_still_open():
    from report_card_flags import pull_flags
    class P:
        def batched(self, template, ids, size=150, **k):
            if 'WorkOrderLineItem' in template:
                return [{'Id': 'L1', 'WorkOrderId': 'W1', 'WorkOrder': {'CreatedDate': NEW, 'Type__c': 'Standard', 'SMS_Opt_In__c': True}}]
            if 'FROM Case' in template:
                return [{'ERS_Work_Order__c': 'W1', 'IsClosed': True, 'prof': 'AAACRM Mulesoft Integration User', 'n': 2},
                        {'ERS_Work_Order__c': 'W1', 'IsClosed': False, 'prof': 'Membership User', 'n': 1},
                        {'ERS_Work_Order__c': 'W1', 'IsClosed': True, 'prof': 'Towbook Integrations', 'n': 1}]
            return []
    out = pull_flags([{'id': 'S1', 'woli_id': 'L1', 'status': 'Completed'}], P())
    assert out['S1']['cases'] == {'total': 4, 'open': 1, 'human': 1, 'auto': 3}
