"""Scheduler Report Card: AI day findings from the fact sheet (architecture.md section 11).

The model never computes: it writes from the fact sheet, cites fact ids, and every number it writes must
appear in a fact it cites (headline_refs / fact_refs). Failure -> one retry listing the problems -> template.
Results are cached by (fact-sheet hash, prompt version, model) in the interim file store.
Drivers are D1, D2... in the prompt; the alias map is returned for the UI and never sent to the model.
"""

import json
import logging
import re
from datetime import datetime, timezone

import report_card_store as store
from report_card_facts import fact_hash, template_narrative

log = logging.getLogger('report_card_ai')
PROMPT_VERSION = 'day-v10'
from report_card_verdicts import FLAG_FNS, RULES_R1

_NAMES = sorted(set(RULES_R1['precedence']) | set(FLAG_FNS) | {'FSL_ENGINE', 'INTEGRATION', 'HUMAN', 'GARAGE_DISPATCHER',
                                                                'TOWBOOK_SYNC', 'DRIVER'}, key=len, reverse=True)
_CODES = re.compile(r'\b(?:' + '|'.join(_NAMES) + r')\b|\b[A-Z]{2,}(?:_[A-Z]+)+\b|\b[LFG]\d{1,2}\b|__c\b'
                    r'|\bRSO\b|\bIn-Day\b')
DEFAULT_MODELS = {'openai': 'gpt-4o', 'anthropic': 'claude-sonnet-4-6'}

SYSTEM = """You write the daily scheduling review of one roadside garage for AAA operations directors.
You receive a JSON fact sheet built by code. Write for a busy executive: plain English, member impact first.
Rules:
- Use ONLY the facts provided. Do not compute, add, average, subtract or estimate. Every number you write must
  appear in a fact you cite (headline_refs for the headline; a finding may use numbers from its diagnosis entry,
  that entry's finding_fact and config_refs, and any extra fact_refs you list). Write numbers as they appear.
- No codes or jargon in any text you write: no verdict or flag names (e.g. STACKED, BYPASSED_OPTIMIZER), no lever
  ids (L01...), no fact ids, no Salesforce field names. Say what happened to members and drivers.
- Headline: exactly two sentences. Sentence 1: what went wrong today (the share of GRADED calls that were scheduled
  poorly, and how many calls missed their promised arrival time). Sentence 2 starts "The biggest lever:" and gives the `action` of the diagnosis entry
  with the largest impact_minutes: copy its `headline_action` word for word. Cite that entry's id and the facts you used in headline_refs.
- Findings: choose 3 to 5 diagnosis entries (fewer only if fewer exist), largest impact_minutes first. For each,
  write a title that leads with member impact, e.g. "55 calls went to a busy or farther driver while a qualified
  driver was free nearby" (you may reuse plain_title), and 1-2 sentences of text saying in plain words what members
  or drivers experienced. Do not restate the cause, action, severity or impact minutes: the page shows those from the
  diagnosis entry. No internal system names in the text (RSO, In-Day, goal types, work rules).
- Be exact about who was hurt: only the entry's `late_calls` missed the promised time; never say all of a finding's
  calls were delayed. State what happened, not why: no "because", no speculation (confusion, inefficiency, morale).
- A diagnosis `count` means exactly its `count_of`. Causes are hypotheses: "consistent with", never "caused by".
- Refer to drivers only by alias (D1, D2...). Never invent names.
- Only scheduler failures are "scheduled poorly"; calls short of capacity, rescued from another garage, or late on
  the driver's side are not the scheduler's fault. Never say the optimizer performs worse because its calls have
  lower PTA met.
Return JSON only:
{"headline": "two sentences", "headline_refs": ["F..", "G.."],
 "findings": [{"diagnosis_id": "G..", "title": "...", "text": "...", "fact_refs": []}]}"""

_STRIP = re.compile(r'\bSA-\d+\b|\b[DFGLHM]\d+\b|\b\d{4}-\d{2}-\d{2}\b|\br1\b|\bh1\b')
_NUM = re.compile(r'\d+(?:\.\d+)?')


def _numbers(text: str, strip=()) -> list:
    for s in strip:
        if s:
            text = text.replace(s, ' ')
    text = re.sub(r'(?<=\d),(?=\d{3}\b)', '', _STRIP.sub(' ', text or ''))
    return [float(x) for x in _NUM.findall(text)]


def _allowed(items: list) -> set:
    out = set()
    for it in items:
        out.update(_numbers(json.dumps(it)))
        for v in (it.get('value'),):
            if isinstance(v, float) and 0 <= v <= 1:
                out.update({round(v * 100), round(v * 100, 1)})
    return out


def validate(out, sheet: dict, driver_map: dict) -> list:
    """Problems with a model (or template) output; empty list = valid."""
    if not isinstance(out, dict):
        return ['output is not a JSON object']
    errs = []
    diag = {g['id']: g for g in sheet['diagnosis']}
    by_id = {f['id']: f for f in sheet['facts']} | diag
    strip = [sheet['scope']['garage']] + [g[k] for g in sheet['diagnosis'] for k in ('action', 'headline_action')]
    head = out.get('headline')
    if not isinstance(head, str) or not head.strip():
        errs.append('headline missing')
    else:
        hrefs = [r for r in out.get('headline_refs') or [] if r in by_id]
        if not hrefs:
            errs.append('headline_refs missing or unknown')
        bad = [n for n in _numbers(head, strip) if n not in _allowed([by_id[r] for r in hrefs])]
        if bad:
            errs.append(f'headline numbers {bad} are not in its cited facts {hrefs}')
        if diag and 'The biggest lever:' not in head:
            errs.append('headline must end with "The biggest lever: <action>"')
        errs += [f'headline uses codes {c}' for c in sorted(set(_CODES.findall(head)))]
    findings = out.get('findings')
    need = min(3, len(diag))
    if not isinstance(findings, list) or not need <= len(findings) <= 5:
        return errs + [f'findings must be a list of {need} to 5']
    seen = set()
    for i, f in enumerate(findings, 1):
        g = diag.get(f.get('diagnosis_id'))
        if g is None or g['id'] in seen:
            errs.append(f"finding {i}: diagnosis_id {f.get('diagnosis_id')} unknown or repeated")
            continue
        seen.add(g['id'])
        extra = [r for r in f.get('fact_refs') or [] if r not in by_id]
        if extra:
            errs.append(f'finding {i}: unknown fact_refs {extra}')
        cited = [g, by_id[g['finding_fact']]] + [by_id[r] for r in g['config_refs'] + (f.get('fact_refs') or []) if r in by_id]
        text = f"{f.get('title') or ''} {f.get('text') or ''}"
        if not (f.get('title') or '').strip():
            errs.append(f'finding {i}: title missing')
        bad = [n for n in _numbers(text, strip) if n not in _allowed(cited)]
        if bad:
            errs.append(f"finding {i}: numbers {bad} are not in diagnosis {g['id']} or its cited facts")
        errs += [f'finding {i}: uses codes {c}' for c in sorted(set(_CODES.findall(text)))]
        aliases = set(re.findall(r'\bD\d+\b', text)) - set(driver_map)
        if aliases:
            errs.append(f'finding {i}: unknown driver aliases {sorted(aliases)}')
    return errs


def enrich(out: dict, sheet: dict) -> dict:
    """Attach the deterministic parts of each finding from its diagnosis entry; order by member impact."""
    diag = {g['id']: g for g in sheet['diagnosis']}
    findings = []
    for f in out['findings']:
        g = diag[f['diagnosis_id']]
        findings.append({**f, 'severity': g['severity'], 'owner': g['owner'], 'lever_id': g['lever_id'],
                         'action': g['action'], 'config_cause': g['cause'], 'tags': g['tags'],
                         'impact_minutes': g['impact_minutes'], 'late_calls': g['late_calls'],
                         'mostly_one_call': g.get('mostly_one_call'),
                         'evidence_sas': g['example_sas']})
    findings.sort(key=lambda x: -x['impact_minutes'])
    return {**out, 'findings': findings}


def _parse(text):
    if not text:
        return None
    a, b = text.find('{'), text.rfind('}')
    try:
        return json.loads(text[a:b + 1]) if a >= 0 and b > a else None
    except json.JSONDecodeError:
        return None


def _call(provider, key, model, user_prompt, system=None):
    """One provider call through the chatbot's provider functions. Shared with the call-story narrative."""
    from routers.chatbot_providers import _call_anthropic, _call_openai
    messages = [{'role': 'system', 'content': system or SYSTEM}, {'role': 'user', 'content': user_prompt}]
    try:
        return (_call_anthropic if provider == 'anthropic' else _call_openai)(key, model, messages)
    except Exception as e:  # network / quota: fall back to the template, never break the page
        log.warning('report card AI call failed (%s %s): %s', provider, model, e)
        return None


def day_findings(sheet: dict, driver_map: dict, ai_settings=None, call=_call) -> dict:
    """Cached findings for a fact sheet. ai_settings = (provider, api_key, model) from utils.load_ai_settings."""
    if ai_settings is None:
        from utils import load_ai_settings
        ai_settings = load_ai_settings()
    provider, key, model = ai_settings
    if provider == 'anthropic' and not (model or '').startswith('claude'):
        model = DEFAULT_MODELS['anthropic']
    model = model or DEFAULT_MODELS.get(provider, 'gpt-4o')
    h = fact_hash(sheet)
    cache_key = f'{h}_{PROMPT_VERSION}_{re.sub(r"[^A-Za-z0-9.-]", "", model if key else "template")}'
    cached = store.load_ai(cache_key)
    if cached:
        return cached
    result, errors, retries, answered = None, [], 0, True
    if key:
        prompt = json.dumps(sheet, sort_keys=True)
        for attempt in range(2):
            ask = prompt if not errors else (prompt + '\n\nYour previous answer was rejected:\n- ' + '\n- '.join(errors)
                                             + '\nFix every problem and return the JSON again.')
            raw = call(provider, key, model, ask)
            answered = answered and raw is not None
            out = _parse(raw)
            errors = validate(out, sheet, driver_map) if out is not None else ['no JSON in the response']
            retries = attempt
            if not errors:
                result = {**enrich(out, sheet), 'source': 'ai', 'model': model}
                break
        if errors:
            log.warning('report card AI output rejected after retry: %s', errors[:5])
    if result is None:
        result = {**enrich(template_narrative(sheet), sheet), 'source': 'template', 'model': None}
    result.update({
        'prompt_version': PROMPT_VERSION, 'fact_hash': h,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'validation': {'passed': result['source'] == 'ai', 'retries': retries, 'errors': errors[:10],
                       'ai_configured': bool(key)},
        'driver_map': driver_map,
        'levers': {x['lever_id']: x for x in sheet['levers']},
    })
    if answered:   # a network/quota failure is not cached, so the next view tries the model again
        store.save_ai(cache_key, result)
    return result
