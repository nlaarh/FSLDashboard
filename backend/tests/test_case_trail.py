"""Cases on a work order and who touched each one: shaped from real Salesforce rows."""

import case_trail as ct

CASE = {'Id': '500A', 'CaseNumber': '01032674', 'Subject': 'Late', 'Status': 'Closed', 'IsClosed': True,
        'RecordType': {'DeveloperName': 'ERS_KMI_Alerts'}, 'Owner': {'Name': 'Tyler LaFave'}, 'CreatedDate': '2026-10-04T04:15:03.000+0000',
        'CreatedBy': {'Name': 'Elizabeth Proper'}, 'LastModifiedBy': {'Name': 'Integrations Towbook'}}


def _h(ts, field, old, new, dtype, who, profile):
    return {'CaseId': '500A', 'Field': field, 'OldValue': old, 'NewValue': new, 'DataType': dtype, 'CreatedDate': ts,
            'CreatedBy': {'Name': who, 'Profile': {'Name': profile}}}


HIST = [
    _h('2026-10-04T04:15:03.000+0000', 'created', None, None, 'Text', 'Elizabeth Proper', 'Membership User'),
    _h('2026-10-04T04:17:02.000+0000', 'Owner', '005Pb000016cyaHIAQ', '00GPb000005EHe4MAG', 'EntityId', 'IT System User', 'AAACRM Mulesoft Integration User'),
    _h('2026-10-04T04:17:02.000+0000', 'Owner', 'Case Omni Queue User', 'ERS KMI Alerts Queue', 'Text', 'IT System User', 'AAACRM Mulesoft Integration User'),
    _h('2026-10-04T04:44:43.000+0000', 'Status', 'New', 'Working', 'DynamicEnum', 'Tyler LaFave', 'Membership User'),
    _h('2026-10-04T04:54:52.000+0000', 'Status', 'Working', 'Closed', 'DynamicEnum', 'Integrations Towbook', 'Towbook Integrations'),
    _h('2026-10-04T04:15:03.000+0000', 'QueuedToBundleOmni__c', False, True, 'Boolean', 'Elizabeth Proper', 'Membership User'),
]


def test_a_person_and_a_system_are_told_apart():
    assert ct.actor('Tyler LaFave', 'Membership User')['kind'] == 'person'
    for n, p in [('IT System User', 'AAACRM Mulesoft Integration User'), ('Integrations Towbook', 'Towbook Integrations'), ('Mulesoft Integration', None)]:
        assert ct.actor(n, p)['kind'] == 'system', n


def test_trail_is_oldest_first_with_who_and_what():
    ev = ct.compose([CASE], HIST, [], [], [])[0]['events']
    assert [e['ts'] for e in ev] == sorted(e['ts'] for e in ev)
    assert ev[0]['text'] == 'Created the case' and ev[0]['name'] == 'Elizabeth Proper' and ev[0]['kind'] == 'person'
    status = [e for e in ev if e['field'] == 'Status']
    assert [(e['name'], e['text']) for e in status] == [('Tyler LaFave', 'Status: New → Working'), ('Integrations Towbook', 'Status: Working → Closed')]
    assert status[1]['kind'] == 'system'


def test_owner_change_written_twice_by_salesforce_is_shown_once_with_names():
    owner = [e for e in ct.compose([CASE], HIST, [], [], [])[0]['events'] if e['field'] == 'Owner']
    assert len(owner) == 1 and owner[0]['text'] == 'Owner: Case Omni Queue User → ERS KMI Alerts Queue'


def test_raw_ids_never_leak_and_booleans_read_naturally():
    ids_only = [_h('2026-10-04T05:00:00.000+0000', 'Owner', '005Pb000016cyaHIAQ', '00GPb000005EHe4MAG', 'EntityId', 'X', 'Membership User')]
    assert ct.compose([CASE], ids_only, [], [], [])[0]['events'][0]['text'] == 'Owner: a person → a queue'
    flag = [e for e in ct.compose([CASE], HIST, [], [], [])[0]['events'] if e['field'] == 'QueuedToBundleOmni__c'][0]
    assert flag['text'] == 'Queued for Omni bundle: no → yes'


def test_comments_emails_and_tasks_join_the_same_timeline():
    comments = [{'ParentId': '500A', 'CommentBody': 'Called the member', 'IsPublished': False, 'CreatedDate': '2026-10-04T04:30:00.000+0000',
                 'CreatedBy': {'Name': 'Tyler LaFave', 'Profile': {'Name': 'Membership User'}}}]
    emails = [{'ParentId': '500A', 'Subject': 'Your service', 'FromName': 'Member', 'Incoming': True, 'MessageDate': '2026-10-04T04:31:00.000+0000', 'TextBody': 'x' * 500}]
    tasks = [{'WhatId': '500A', 'Subject': 'Call back', 'Status': 'Open', 'Owner': {'Name': 'Tyler LaFave'}, 'CreatedDate': '2026-10-04T04:32:00.000+0000',
              'CreatedBy': {'Name': 'Tyler LaFave', 'Profile': {'Name': 'Membership User'}}}]
    ev = ct.compose([CASE], HIST, comments, emails, tasks)[0]['events']
    assert {e['type'] for e in ev} >= {'comment', 'email', 'task', 'created', 'change'}
    assert [e for e in ev if e['type'] == 'email'][0]['text'] == 'Received email: Your service' and len([e for e in ev if e['type'] == 'email'][0]['snippet']) == 300
    assert [e['ts'] for e in ev] == sorted(e['ts'] for e in ev)


def test_pull_makes_one_query_when_there_are_no_cases_and_five_when_there_are():
    class P:
        def __init__(self, cases): self.sql, self.cases = [], cases
        def all(self, q): self.sql.append(q); return self.cases
        def batched(self, t, ids, size=150): self.sql.append(t); return []
    none, some = P([]), P([CASE])
    assert ct.pull('0WOPb00000KZeOrOAL', none) == [] and len(none.sql) == 1
    out = ct.pull('0WOPb00000KZeOrOAL', some)
    assert len(some.sql) == 5 and out[0]['number'] == '01032674' and out[0]['events'] == []
