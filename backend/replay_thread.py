"""Replay text thread: the messages of one member's text conversation, read only when someone clicks (replay-v2 3.5).

One read-only Salesforce GET per conversation: /connect/conversation/{ConversationIdentifier}/entries. The entry shape
(seen live 2026-10-08): {'conversationEntries': [{'messageText', 'serverReceivedTimestamp' (ms), 'clientTimestamp' (ms),
'sender': {'role': 'EndUser'|'Agent'|'System', 'appType'}, 'relatedRecords': [MessagingSession id], 'identifier'}]},
in no particular order. The conversation also holds AAA's automatic texts (role System)."""

from datetime import datetime, timezone

from case_trail import clean_text
from sf_client import sf_rest_get

ROLES = {'enduser': 'member', 'agent': 'agent'}


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def map_entries(body) -> list:
    """Salesforce entries -> [{'ts', 'who': member|agent|system, 'text'}], oldest first. Empty texts are dropped."""
    out = []
    for e in (body or {}).get('conversationEntries') or []:
        text = clean_text(e.get('messageText'))
        ms = e.get('serverReceivedTimestamp') or e.get('clientTimestamp')
        if not text or not ms:
            continue
        who = ROLES.get(str((e.get('sender') or {}).get('role') or '').lower(), 'system')
        out.append({'ts': datetime.fromtimestamp(ms / 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'who': who, 'text': text})
    return sorted(out, key=lambda x: x['ts'])


def fetch_thread(conversation_ids: list, start: datetime, end: datetime) -> tuple:
    """(entries, sf_calls) for the conversations of one work order inside [start, end]."""
    entries, calls = [], 0
    for cid in conversation_ids:
        calls += 1
        entries += map_entries(sf_rest_get(f'/connect/conversation/{cid}/entries', {'startTimestamp': _ms(start), 'endTimestamp': _ms(end)}))
    return sorted(entries, key=lambda x: x['ts']), calls
