"""Cases on a work order and the full trail of who touched each one.

Read-only. Salesforce keeps, per case: field history (owner, status, reassignments... with who and when), comments,
emails and tasks. This module turns those rows into one time-ordered list of events per case.
Five SELECTs (history, comments, emails, tasks, chatter notes) cover ALL the work order's cases at once.
"""

import html
import re

_SF_ID = re.compile(r'^[a-zA-Z0-9]{15}([a-zA-Z0-9]{3})?$')
_ID_KIND = {'005': 'a person', '00G': 'a queue'}
_SYSTEM_PROFILE = re.compile(r'integration|mulesoft|towbook|automat|api only', re.I)   # NOT a bare 'system': System Administrator is a person
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


def clean_text(v, limit: int = 2000) -> str:
    """Chatter posts come as HTML ('<p>I left voicemail</p>'): show what the person actually wrote."""
    if not v:
        return ''
    t = re.sub(r'(?i)<\s*br\s*/?>|</\s*p\s*>|</\s*li\s*>', '\n', str(v))
    t = html.unescape(re.sub(r'<[^>]+>', '', t))
    t = re.sub(r'[ \t]+\n', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t).strip()
    return t if len(t) <= limit else t[:limit].rstrip() + '…'


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


def _secs(iso: str) -> float:
    from datetime import datetime
    return datetime.fromisoformat((iso or '1970-01-01T00:00:00+00:00').replace('+0000', '+00:00').replace('Z', '+00:00')).timestamp()


def _who(row: dict) -> dict:
    cb = row.get('CreatedBy') or {}
    return actor(cb.get('Name'), (cb.get('Profile') or {}).get('Name'))


def compose(cases: list, history: list, comments: list, emails: list, tasks: list, feed: list | None = None) -> list:
    """[{case..., events: [oldest first]}] for every case on the work order.
    Written content (notes, comments, emails, call notes) carries `body`: what the person wrote or told the member/driver."""
    feed = feed or []
    by = lambda rows, key: {c['Id']: [r for r in rows if r.get(key) == c['Id']] for c in cases}
    h, cm, em, tk, fd = by(history, 'CaseId'), by(comments, 'ParentId'), by(emails, 'ParentId'), by(tasks, 'WhatId'), by(feed, 'ParentId')
    out = []
    for c in cases:
        ev = _history_events(h[c['Id']])
        for r in fd[c['Id']]:
            if r.get('Type') == 'TextPost':
                ev.append({'ts': r['CreatedDate'], 'type': 'note', 'text': 'Wrote a note', 'body': clean_text(r.get('Body')), **_who(r)})
        for r in cm[c['Id']]:
            ev.append({'ts': r['CreatedDate'], 'type': 'comment', 'text': 'Added a comment' + ('' if r.get('IsPublished') else ' (internal)'),
                       'body': clean_text(r.get('CommentBody')), 'public': r.get('IsPublished'), **_who(r)})
        # The email's From is a shared mailbox ('Member Relations'). The email's activity task knows which person sent it.
        mail_tasks = [t for t in tk[c['Id']] if t.get('TaskSubtype') == 'Email']
        for r in em[c['Id']]:
            sent = not r.get('Incoming')
            ts = r.get('MessageDate') or r.get('CreatedDate')
            sender = next((t for t in mail_tasks if (t.get('Subject') or '').endswith(r.get('Subject') or '\0')
                           and abs(_secs(t['CreatedDate']) - _secs(ts)) <= 5), None)
            who = _who(sender) if sent and sender else actor(r.get('FromName') or r.get('FromAddress'), None)
            via = f" (from the {r['FromName']} mailbox)" if sent and sender and r.get('FromName') else ''
            ev.append({'ts': ts, 'type': 'email',
                       'text': f"{'Emailed ' + (r.get('ToAddress') or 'the member') if sent else 'Received an email'}{via}: {r.get('Subject') or '(no subject)'}",
                       'body': clean_text(r.get('TextBody')), 'incoming': bool(r.get('Incoming')), **who})
        for r in tk[c['Id']]:
            if r.get('TaskSubtype') == 'Email':
                continue                       # an email task repeats the email above
            ev.append({'ts': r['CreatedDate'], 'type': 'task', 'text': f"{r.get('TaskSubtype') or 'Task'}: {r.get('Subject') or '(no subject)'} [{r.get('Status') or ''}]"
                       + (f" → {(r.get('Owner') or {}).get('Name')}" if (r.get('Owner') or {}).get('Name') else ''),
                       'body': clean_text(r.get('Description')), **_who(r)})
        ev.sort(key=lambda e: e['ts'] or '')
        written = [e for e in ev if e.get('body')]
        opener = actor((c.get('CreatedBy') or {}).get('Name'), ((c.get('CreatedBy') or {}).get('Profile') or {}).get('Name'))
        people = sorted({e['name'] for e in ev if e['kind'] == 'person'})
        out.append({'id': c['Id'], 'number': c.get('CaseNumber'), 'subject': c.get('Subject'), 'status': c.get('Status'),
                    'closed': bool(c.get('IsClosed')), 'priority': c.get('Priority'), 'origin': c.get('Origin'),
                    'type': (c.get('RecordType') or {}).get('DeveloperName'), 'alert': c.get('ERS_Alert_Name__c'),
                    'description': clean_text(c.get('Description')), 'resolution': c.get('Resolution__c'),
                    'resolution_notes': clean_text(c.get('Resolution_Notes__c')), 'feedback_resolution': c.get('Feedback_Resolution__c'),
                    'owner': (c.get('Owner') or {}).get('Name'), 'created': c.get('CreatedDate'),
                    'created_by': (c.get('CreatedBy') or {}).get('Name'), 'last_modified': c.get('LastModifiedDate'),
                    'last_modified_by': (c.get('LastModifiedBy') or {}).get('Name'), 'closed_date': c.get('ClosedDate'),
                    'origin': 'human' if opener['kind'] == 'person' else 'automatic',     # who OPENED it: a person, or an integration/system
                    'people': people, 'human_touched': bool(people),                       # whether any person touched it afterwards
                    'written_count': len(written), 'events': ev})
    return out


def pull(wo_id: str, puller) -> list:
    """One work order: 1 query for its cases, then 5 queries covering all of them. No cases = 1 query."""
    cases = puller.all(
        "SELECT Id, CaseNumber, Subject, Description, Status, IsClosed, Priority, Origin, RecordType.DeveloperName, ERS_Alert_Name__c, "
        "Resolution__c, Resolution_Notes__c, Feedback_Resolution__c, "
        "Owner.Name, CreatedDate, CreatedBy.Name, CreatedBy.Profile.Name, LastModifiedDate, LastModifiedBy.Name, ClosedDate "
        f"FROM Case WHERE ERS_Work_Order__c = '{wo_id}' ORDER BY CreatedDate")
    if not cases:
        return []
    ids = [c['Id'] for c in cases]
    history = puller.batched("SELECT CaseId, Field, OldValue, NewValue, DataType, CreatedBy.Name, CreatedBy.Profile.Name, CreatedDate "
                             "FROM CaseHistory WHERE CaseId IN ({ids}) ORDER BY CreatedDate", ids, size=200)
    comments = puller.batched("SELECT ParentId, CommentBody, IsPublished, CreatedBy.Name, CreatedBy.Profile.Name, CreatedDate "
                              "FROM CaseComment WHERE ParentId IN ({ids})", ids, size=200)
    emails = puller.batched("SELECT ParentId, Subject, FromName, FromAddress, ToAddress, Incoming, MessageDate, CreatedDate, TextBody "
                            "FROM EmailMessage WHERE ParentId IN ({ids})", ids, size=200)
    tasks = puller.batched("SELECT WhatId, Subject, Description, Status, TaskSubtype, Owner.Name, CreatedBy.Name, CreatedBy.Profile.Name, CreatedDate "
                           "FROM Task WHERE WhatId IN ({ids})", ids, size=200)
    feed = puller.batched("SELECT ParentId, Type, Body, CreatedBy.Name, CreatedBy.Profile.Name, CreatedDate "
                          "FROM CaseFeed WHERE Type = 'TextPost' AND ParentId IN ({ids})", ids, size=200)
    return compose(cases, history, comments, emails, tasks, feed)
