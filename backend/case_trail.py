"""Cases on a work order and the full trail of who touched each one.

Read-only. Salesforce keeps, per case: field history (owner, status, reassignments... with who and when), comments,
emails and tasks. This module turns those rows into one time-ordered list of events per case.
Three SELECTs for the cases' history, comments and tasks (+ emails) cover ALL the work order's cases at once.
"""

import re

_SF_ID = re.compile(r'^[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?$')
_ID_KIND = {'005': 'a person', '00G': 'a queue'}
_SYSTEM_PROFILE = re.compile(r'integration|mulesoft|api|system|towbook', re.I)
_SYSTEM_NAME = re.compile(r'integration|mulesoft|system user|automated|process', re.I)

FIELD_LABELS = {'ownerAssignment': 'Reassigned', 'Owner': 'Owner', 'Status': 'Status', 'Contact': 'Contact',
                'Subject': 'Subject', 'Description': 'Description', 'Priority': 'Priority', 'Origin': 'Origin',
                'QueuedToBundleOmni__c': 'Queued for Omni bundle', 'Omni_Case_Bundle__c': 'Omni case bundle',
                'Resolution__c': 'Resolution', 'Feedback_Resolution__c': 'Feedback resolution',
                'Resolution_Notes__c': 'Resolution notes', 'RecordType': 'Record type', 'Type': 'Type'}


def actor(name: str | None, profile: str | None) -> dict:
    """A person or a system. Integrations and automations are not dispatchers, so the page can tell them apart."""
    name, profile = name or 'Unknown', profile or ''
    system = bool(_SYSTEM_PROFILE.search(profile) or _SYSTEM_NAME.search(name))
    return {'name': name, 'profile': profile, 'kind': 'system' if system else 'person'}


def _label(field: str) -> str:
    return FIELD_LABELS.get(field) or re.sub(r'\s+', ' ', field.replace('__c', '').replace('_', ' ')).strip()


def _val(v, limit: int = 200):
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return 'yes' if v else 'no'
    v = str(v)
    if _SF_ID.match(v) and v[:3] in _ID_KIND:
        return _ID_KIND[v[:3]]
    return v if len(v) <= limit else v[:limit] + '…'


def _history_events(rows: list) -> list:
    """Salesforce writes an owner change twice (once with ids, once with names). Keep the readable one."""
    named = {(r['CreatedDate'], r['Field']) for r in rows if r.get('DataType') != 'EntityId'}
    out = []
    for r in rows:
        if r.get('DataType') == 'EntityId' and (r['CreatedDate'], r['Field']) in named:
            continue
        who = actor((r.get('CreatedBy') or {}).get('Name'), ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name'))
        f, old, new = r['Field'], _val(r.get('OldValue')), _val(r.get('NewValue'))
        if f == 'created':
            text, kind = 'Created the case', 'created'
        elif f == 'ownerAssignment':
            text, kind = f'Reassigned: {old or "nobody"} → {new or "nobody"}', 'change'
        else:
            text, kind = (f'{_label(f)}: {old or "empty"} → {new or "empty"}' if old or new else f'{_label(f)} changed'), 'change'
        out.append({'ts': r['CreatedDate'], 'type': kind, 'field': f, 'old': old, 'new': new, 'text': text, **who})
    return out


def compose(cases: list, history: list, comments: list, emails: list, tasks: list) -> list:
    """[{case..., events: [oldest first]}] for every case on the work order."""
    by = lambda rows, key: {c['Id']: [r for r in rows if r.get(key) == c['Id']] for c in cases}
    h, cm, em, tk = by(history, 'CaseId'), by(comments, 'ParentId'), by(emails, 'ParentId'), by(tasks, 'WhatId')
    out = []
    for c in cases:
        ev = _history_events(h[c['Id']])
        for r in cm[c['Id']]:
            ev.append({'ts': r['CreatedDate'], 'type': 'comment', 'text': (r.get('CommentBody') or '')[:600],
                       'public': r.get('IsPublished'), **actor((r.get('CreatedBy') or {}).get('Name'), ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name'))})
        for r in em[c['Id']]:
            ev.append({'ts': r.get('MessageDate') or r.get('CreatedDate'), 'type': 'email',
                       'text': f"{'Received' if r.get('Incoming') else 'Sent'} email: {r.get('Subject') or '(no subject)'}",
                       'snippet': (r.get('TextBody') or '')[:300], **actor(r.get('FromName') or r.get('FromAddress'), None)})
        for r in tk[c['Id']]:
            ev.append({'ts': r['CreatedDate'], 'type': 'task', 'text': f"Task: {r.get('Subject') or '(no subject)'} [{r.get('Status') or ''}]"
                       + (f" → {(r.get('Owner') or {}).get('Name')}" if (r.get('Owner') or {}).get('Name') else ''),
                       **actor((r.get('CreatedBy') or {}).get('Name'), ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name'))})
        ev.sort(key=lambda e: e['ts'] or '')
        out.append({'id': c['Id'], 'number': c.get('CaseNumber'), 'subject': c.get('Subject'), 'status': c.get('Status'),
                    'closed': bool(c.get('IsClosed')), 'priority': c.get('Priority'), 'origin': c.get('Origin'),
                    'type': (c.get('RecordType') or {}).get('DeveloperName'), 'alert': c.get('ERS_Alert_Name__c'),
                    'owner': (c.get('Owner') or {}).get('Name'), 'created': c.get('CreatedDate'),
                    'created_by': (c.get('CreatedBy') or {}).get('Name'), 'last_modified': c.get('LastModifiedDate'),
                    'last_modified_by': (c.get('LastModifiedBy') or {}).get('Name'), 'closed_date': c.get('ClosedDate'),
                    'events': ev})
    return out


def pull(wo_id: str, puller) -> list:
    """One work order: 1 query for its cases, then 4 queries covering all of them. No cases = 1 query."""
    cases = puller.all(
        "SELECT Id, CaseNumber, Subject, Status, IsClosed, Priority, Origin, RecordType.DeveloperName, ERS_Alert_Name__c, "
        "Owner.Name, CreatedDate, CreatedBy.Name, LastModifiedDate, LastModifiedBy.Name, ClosedDate "
        f"FROM Case WHERE ERS_Work_Order__c = '{wo_id}' ORDER BY CreatedDate")
    if not cases:
        return []
    ids = [c['Id'] for c in cases]
    history = puller.batched("SELECT CaseId, Field, OldValue, NewValue, DataType, CreatedBy.Name, CreatedBy.Profile.Name, CreatedDate "
                             "FROM CaseHistory WHERE CaseId IN ({ids}) ORDER BY CreatedDate", ids, size=200)
    comments = puller.batched("SELECT ParentId, CommentBody, IsPublished, CreatedBy.Name, CreatedBy.Profile.Name, CreatedDate "
                              "FROM CaseComment WHERE ParentId IN ({ids})", ids, size=200)
    emails = puller.batched("SELECT ParentId, Subject, FromName, FromAddress, Incoming, MessageDate, CreatedDate, TextBody "
                            "FROM EmailMessage WHERE ParentId IN ({ids})", ids, size=200)
    tasks = puller.batched("SELECT WhatId, Subject, Status, Owner.Name, CreatedBy.Name, CreatedBy.Profile.Name, CreatedDate "
                           "FROM Task WHERE WhatId IN ({ids})", ids, size=200)
    return compose(cases, history, comments, emails, tasks)
