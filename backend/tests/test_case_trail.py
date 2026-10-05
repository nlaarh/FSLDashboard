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


def test_what_people_wrote_and_said_is_shown_in_full_with_who_and_when():
    feed = [{'ParentId': '500A', 'Type': 'TextPost', 'Body': "<p>I left voicemail to advise call was NC.  </p><p>Per mem&#39;s email: no tow</p>",
             'CreatedDate': '2026-10-04T04:30:00.000+0000', 'CreatedBy': {'Name': 'Adam Sukert', 'Profile': {'Name': 'Membership User'}}},
            {'ParentId': '500A', 'Type': 'CaseCommentPost', 'Body': 'dupe of the comment', 'CreatedDate': '2026-10-04T04:30:01.000+0000'}]
    comments = [{'ParentId': '500A', 'CommentBody': 'Called the member back', 'IsPublished': False, 'CreatedDate': '2026-10-04T04:31:00.000+0000',
                 'CreatedBy': {'Name': 'Tyler LaFave', 'Profile': {'Name': 'Membership User'}}}]
    emails = [{'ParentId': '500A', 'Subject': 'AAA Case ID #1', 'FromName': 'Member Relations', 'ToAddress': 'm@x.com', 'Incoming': False,
               'MessageDate': '2026-10-04T04:32:00.000+0000', 'TextBody': 'Dear member,\nthis will not count against your four free calls.\n' + 'x' * 5000}]
    tasks = [{'WhatId': '500A', 'Subject': 'Email: AAA Case ID #1', 'TaskSubtype': 'Email', 'Description': 'same email again', 'CreatedDate': '2026-10-04T04:32:01.000+0000',
              'CreatedBy': {'Name': 'Debbie Gordon', 'Profile': {'Name': 'Membership User'}}},
             {'WhatId': '500A', 'Subject': 'Call driver', 'TaskSubtype': 'Call', 'Description': 'Driver says he is 10 min out', 'Status': 'Completed',
              'Owner': {'Name': 'Tyler LaFave'}, 'CreatedDate': '2026-10-04T04:33:00.000+0000', 'CreatedBy': {'Name': 'Tyler LaFave', 'Profile': {'Name': 'Membership User'}}}]
    case = ct.compose([CASE], HIST, comments, emails, tasks, feed)[0]
    ev = case['events']
    note = next(e for e in ev if e['type'] == 'note')
    assert note['name'] == 'Adam Sukert' and note['kind'] == 'person' and note['ts'].startswith('2026-10-04T04:30')
    assert note['body'] == "I left voicemail to advise call was NC.\nPer mem's email: no tow"                 # tags and entities gone
    assert next(e for e in ev if e['type'] == 'comment')['body'] == 'Called the member back' and 'internal' in next(e for e in ev if e['type'] == 'comment')['text']
    mail = next(e for e in ev if e['type'] == 'email')
    assert mail['name'] == 'Debbie Gordon' and mail['kind'] == 'person'                  # the person, not the shared mailbox
    assert mail['text'].startswith('Emailed m@x.com (from the Member Relations mailbox): AAA Case ID #1') and 'will not count against your four free calls' in mail['body'] and len(mail['body']) <= 2001
    tasks_out = [e for e in ev if e['type'] == 'task']
    assert len(tasks_out) == 1 and tasks_out[0]['body'] == 'Driver says he is 10 min out' and tasks_out[0]['text'].startswith('Call: Call driver')
    assert not any('dupe of the comment' in (e.get('body') or '') for e in ev)                                  # only chatter TEXT posts
    assert case['written_count'] == 4 and [e['ts'] for e in ev] == sorted(e['ts'] for e in ev)


def test_case_carries_its_description_and_resolution_for_the_header():
    c = {**CASE, 'Description': '<p>Member waited 2 h</p>', 'Resolution__c': 'Courtesy', 'Resolution_Notes__c': 'Waived the call.', 'Feedback_Resolution__c': None}
    out = ct.compose([c], [], [], [], [], [])[0]
    assert out['description'] == 'Member waited 2 h' and out['resolution'] == 'Courtesy' and out['resolution_notes'] == 'Waived the call.' and out['written_count'] == 0


def test_pull_makes_one_query_when_there_are_no_cases_and_six_when_there_are():
    class P:
        def __init__(self, cases): self.sql, self.cases = [], cases
        def all(self, q): self.sql.append(q); return self.cases
        def batched(self, t, ids, size=150): self.sql.append(t); return []
    none, some = P([]), P([CASE])
    assert ct.pull('0WOPb00000KZeOrOAL', none) == [] and len(none.sql) == 1
    out = ct.pull('0WOPb00000KZeOrOAL', some)
    assert len(some.sql) == 6 and out[0]['number'] == '01032674' and out[0]['events'] == []


def test_a_case_is_automatic_or_human_by_who_opened_it_and_lists_who_touched_it():
    auto = {**CASE, 'CreatedBy': {'Name': 'Mulesoft Integration', 'Profile': {'Name': 'AAACRM Mulesoft Integration User'}}}
    human = {**CASE, 'CreatedBy': {'Name': 'Elizabeth Proper', 'Profile': {'Name': 'Membership User'}}}
    only_system = [_h('2026-10-04T04:17:02.000+0000', 'Status', 'New', 'Closed', 'DynamicEnum', 'IT System User', 'AAACRM Mulesoft Integration User')]
    a = ct.compose([auto], only_system, [], [], [], [])[0]
    assert a['origin'] == 'automatic' and a['human_touched'] is False and a['people'] == []
    h = ct.compose([human], HIST, [], [], [], [])[0]
    assert h['origin'] == 'human' and h['human_touched'] is True and h['people'] == ['Elizabeth Proper', 'Tyler LaFave']


def test_a_system_administrator_is_a_person_not_an_automation():
    assert ct.actor('Pat Admin', 'System Administrator')['kind'] == 'person'
