"""Call Story: optional AI paragraph from the composed story's facts (architecture 7.3).

Only on an explicit "Write summary" click. People are anonymised ("Driver A", "Dispatcher B") in the prompt; the
UI maps them back. Validator: every number, person label, cause code and event id must exist in the facts; never
"caused by". One retry, then the deterministic bullets. Cached by (fact hash, prompt version, model).
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

import report_card_store as store
from report_card_ai import _allowed, _call, _numbers, _parse
from report_card_verdicts import RULES_R1
from utils import to_eastern

log = logging.getLogger('call_story_narrative')
PROMPT_VERSION = 'cs-narr-1'
SYSTEM = """You write a short plain-English account of one roadside call for AAA supervisors, from a JSON fact list.
Rules: use only the facts. Do not compute or estimate. Every number you write must appear in the facts. Refer to people
only by the labels given (e.g. "Driver A", "Dispatcher B"). Mention only causes listed in `causes`, by what happened, and
cite their codes in cause_codes. Hypotheses about configuration are "consistent with", never "caused by". Each sentence
lists the event ids (E..) it is based on. 3 to 6 sentences, time order.
Return JSON only: {"sentences": [{"text": "...", "event_ids": ["E3"], "cause_codes": ["C09"]}]}"""
SYSTEM_ACCOUNTS = set(RULES_R1['actors']['fsl_engine'] + RULES_R1['actors']['integration']) | {'Integrations Towbook'}
ROLE = {'DRIVER': 'Driver', 'HUMAN': 'Dispatcher', 'CALL_TAKER': 'Call taker', 'GARAGE_DISPATCHER': 'Garage dispatcher'}


def people_map(story: dict) -> dict:
    """Real name -> label, in order of first appearance."""
    labels, counts = {}, {}

    def add(name, role):
        if not name or name in SYSTEM_ACCOUNTS or name in labels:
            return
        counts[role] = counts.get(role, 0) + 1
        labels[name] = f"{role} {chr(64 + counts[role])}"
    for e in story['events']:
        add(e['actor'], ROLE.get(e['actor_class'], 'Person'))
        if e.get('driver') and not e['driver'].lower().startswith(('towbook', '000-')):
            add(e['driver'], 'Driver')
    for g in story['segments']:
        add(g.get('driver'), 'Driver')
    return labels


def _anon(value, labels: dict):
    text = json.dumps(value)
    for name, label in sorted(labels.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(name, label)
    return json.loads(text)


def fact_sheet(story: dict) -> tuple:
    labels = people_map(story)
    facts = {
        'events': [{'id': e['id'], 'time_et': to_eastern(e['ts']).strftime('%H:%M'), 'kind': e['kind'], 'actor': e['actor'], 'actor_class': e['actor_class'],
                    **({'driver': e['driver']} if e.get('driver') else {})} for e in story['events'] if not e['hidden']],
        'segments': [{'id': g['id'], 'kind': g['kind'], 'minutes': g['minutes'], 'severity': g['severity'],
                      'driver_state': g.get('driver_state'),
                      'baseline': {k: (g['baseline'] or {}).get(k) for k in ('p75', 'p90', 'p95', 'n')}}
                     for g in story['segments']],
        'causes': [{'code': c['code'], 'name': c['name'], 'evidence': c['evidence'], 'event_ids': c['event_ids'],
                    'diagnosis': c.get('diagnosis')} for c in story['causes']],
        'verdict': {k: story['verdict'].get(k) for k in ('primary', 'flags', 'note')},
        'pta': {k: story['pta'].get(k) for k in ('initial_min', 'final_min', 'met_initial', 'met_final',
                                                  'margin_initial_min', 'response_min')},
        'texts': [{'label': r['label'], 'outcome': r['outcome']} for r in story['sms']['rows']],
    }
    return _anon(facts, labels), labels


def validate(out, facts: dict, labels: dict) -> list:
    if not isinstance(out, dict) or not isinstance(out.get('sentences'), list) or not out['sentences']:
        return ['no sentences']
    errs = []
    allowed = _allowed([facts])
    events = {e['id'] for e in facts['events']}
    codes = {c['code'] for c in facts['causes']}
    names = set(labels.values())
    for i, s in enumerate(out['sentences'], 1):
        text = s.get('text') or ''
        bad = [n for n in _numbers(text) if n not in allowed]
        if bad:
            errs.append(f'sentence {i}: numbers {bad} not in the facts')
        people = set(re.findall(r'\b(?:Driver|Dispatcher|Call taker|Garage dispatcher|Person) [A-Z]\b', text))
        if people - names:
            errs.append(f'sentence {i}: unknown people {sorted(people - names)}')
        if set(s.get('event_ids') or []) - events:
            errs.append(f'sentence {i}: unknown event ids')
        if set(s.get('cause_codes') or []) - codes or set(re.findall(r'\bC\d{2}\b', text)) - codes:
            errs.append(f'sentence {i}: cause codes not fired')
        if 'caused by' in text.lower():
            errs.append(f'sentence {i}: says "caused by"')
    return errs


def narrate(story: dict, ai_settings, call=_call) -> dict:
    """Cached narrative for a composed story; deterministic bullets when no AI, no causes, or validation fails."""
    facts, labels = fact_sheet(story)
    template = {'sentences': [{'text': b['text'], 'event_ids': b['event_ids'], 'cause_codes': b['cause_codes']}
                              for b in story['bullets']], 'source': 'template', 'model': None}
    provider, key, model = ai_settings
    model = model or 'gpt-4o'
    if not story['causes'] or not key:
        return {**template, 'people': {}, 'validation': {'passed': False, 'retries': 0, 'errors': [],
                                                          'ai_configured': bool(key), 'reason': 'no causes' if key else 'no AI key'}}
    h = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
    cache_key = f"{h}_{PROMPT_VERSION}_{re.sub(r'[^A-Za-z0-9.-]', '', model)}"
    cached = store.load_ai(cache_key)
    if cached:
        return cached
    errors, result, retries, answered = [], None, 0, True
    prompt = json.dumps(facts, sort_keys=True)
    for attempt in range(2):
        ask = prompt if not errors else prompt + '\n\nRejected:\n- ' + '\n- '.join(errors) + '\nFix and return the JSON again.'
        raw = call(provider, key, model, ask, SYSTEM)
        answered = answered and raw is not None
        out = _parse(raw)
        errors = validate(out, facts, labels) if out else ['no JSON in the response']
        retries = attempt
        if not errors:
            result = {**out, 'source': 'ai', 'model': model}
            break
    result = result or template
    result.update({'people': {v: k for k, v in labels.items()} if result['source'] == 'ai' else {},
                   'prompt_version': PROMPT_VERSION, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                   'validation': {'passed': result['source'] == 'ai', 'retries': retries, 'errors': errors[:10],
                                  'ai_configured': True}})
    if answered:
        store.save_ai(cache_key, result)
    return result
