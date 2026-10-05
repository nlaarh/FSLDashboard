"""Scheduler Report Card AI findings: fact sheet, number validator, retry/fallback, cache (no network)."""

import json

import pytest

from report_card_ai import day_findings, enrich, validate
from report_card_facts import LEVERS, build_fact_sheet, fact_hash, template_narrative
from report_card_metrics import garage_summary
from report_card_verdicts import rules_for, score_snapshot
from tests.report_card_factories import load_wny_0928

RULES = rules_for('r1')


@pytest.fixture(scope='module')
def sheet():
    fx = load_wny_0928()
    v = score_snapshot(fx, RULES)
    return build_fact_sheet(fx, v, [], garage_summary(fx, v, [], RULES), RULES)


def _fact(sheet, prefix):
    return next(f for f in sheet['facts'] if f['label'].startswith(prefix))


def test_fact_sheet_headline_facts_match_the_golden_day(sheet):
    s, _ = sheet
    assert _fact(s, 'Scheduler failures')['display'] == '9 of 81 (11%)'
    assert _fact(s, 'PTA met')['display'] == '65 of 82 (79%)'
    assert _fact(s, 'Calls with verdict GOOD')['value'] == 54
    assert _fact(s, 'Calls flagged SKILL_MISMATCH')['examples'] == ['SA-1075493']
    assert _fact(s, 'Closest qualified driver picked, FSL')['display'] == '7 of 20 (35%)'     # spec 10
    assert _fact(s, "Main optimizer policy")['weights'] == {'ASAP High Priority': 120000, 'ASAP': 60000,
                                                            'Minimize Travel': 10}


def test_diagnosis_pairs_use_the_lever_whitelist_and_name_their_counts(sheet):
    s, _ = sheet
    levers = [g['lever_id'] for g in s['diagnosis']]
    assert {'L02', 'L03', 'L04', 'L05', 'L06', 'L07', 'L13'} <= set(levers) <= set(LEVERS)
    known = {f['id'] for f in s['facts']}
    for g in s['diagnosis']:
        assert g['finding_fact'] in known and set(g['config_refs']) <= known
        assert g['count_of'] and all(x.startswith('SA-') for x in g['example_sas'])
        assert 'caused by' not in g['cause'].lower()
        assert ': ' in g['action'] and g['headline_action'].endswith(')')
    rebalance = next(g for g in s['diagnosis'] if g['lever_id'] == 'L03')
    assert (rebalance['count'], sorted(rebalance['example_sas'])) == (2, ['SA-1074458', 'SA-1075605'])
    assert rebalance['plain_title'] == '2 calls went to a busy or farther driver while a qualified driver was free nearby'


def test_findings_are_ordered_by_member_impact(sheet):
    """Product owner: order by minutes members waited past PTA on each finding's calls, not by count."""
    s, _ = sheet
    impact = [g['impact_minutes'] for g in s['diagnosis']]
    assert impact == sorted(impact, reverse=True) and impact[0] > 0
    late = _fact(s, 'Minutes members waited past')
    assert late['calls'] == _fact(s, 'PTA met')['missed'] == 17
    assert all(g['impact_minutes'] <= late['value'] and g['late_calls'] <= 17 for g in s['diagnosis'])
    assert next(g for g in s['diagnosis'] if g['lever_id'] == 'L10')['plain_title'].startswith('1 call went')


def test_drivers_are_anonymised(sheet):
    s, driver_map = sheet
    text = json.dumps(s)
    assert all(name not in text for name in driver_map.values() if name)
    assert '0HnFAKE' not in text and set(driver_map) == {f'D{i}' for i in range(1, len(driver_map) + 1)}


def test_hash_ignores_key_order(sheet):
    s, _ = sheet
    shuffled = json.loads(json.dumps(s), object_pairs_hook=lambda kv: dict(reversed(kv)))
    assert fact_hash(shuffled) == fact_hash(s)


def test_template_always_validates(sheet):
    s, dm = sheet
    t = template_narrative(s)
    assert validate(t, s, dm) == [] and 3 <= len(t['findings']) <= 5


def _good(sheet):
    s, _ = sheet
    fail, pta = _fact(s, 'Scheduler failures'), _fact(s, 'PTA met')
    top = s['diagnosis'][0]
    findings = [{'diagnosis_id': g['id'], 'title': g['plain_title'], 'text': 'Members on these calls waited longer.'}
                for g in s['diagnosis'][:3]]
    return {'headline': f"11% of graded calls were scheduled poorly and {pta['missed']} calls missed their promise. "
                        f"The biggest lever: {top['headline_action']}.",
            'headline_refs': [fail['id'], pta['id'], top['id']], 'findings': findings}


def test_validator_accepts_numbers_from_cited_facts(sheet):
    assert validate(_good(sheet), *sheet) == []


@pytest.mark.parametrize('mutate, expect', [
    (lambda o: o.update(headline=o['headline'].replace('11%', '12%')), 'headline numbers'),
    (lambda o: o.update(headline='Things went fine.'), 'The biggest lever'),
    (lambda o: o['findings'][0].update(text='54 calls were good.'), 'numbers'),           # true, but not this entry's
    (lambda o: o['findings'][0].update(text='Too many STACKED calls.'), 'uses codes'),
    (lambda o: o['findings'][0].update(title='Fix it with L03'), 'uses codes'),
    (lambda o: o['findings'][0].update(text='The RSO kept moving them.'), 'uses codes'),
    (lambda o: o['findings'][0].update(text='D99 was stacked.'), 'unknown driver aliases'),
    (lambda o: o['findings'][1].update(diagnosis_id=o['findings'][0]['diagnosis_id']), 'unknown or repeated'),
    (lambda o: o['findings'][0].update(diagnosis_id='G99'), 'unknown or repeated'),
    (lambda o: o.update(findings=o['findings'][:2]), '3 to 5'),
])
def test_validator_rejects(sheet, mutate, expect):
    out = _good(sheet)
    mutate(out)
    assert any(expect in e for e in validate(out, *sheet))


def test_enrich_attaches_diagnosis_fields_and_sorts_by_impact(sheet):
    s, _ = sheet
    out = _good(sheet)
    out['findings'].reverse()
    res = enrich(out, s)
    assert [f['impact_minutes'] for f in res['findings']] == sorted((g['impact_minutes'] for g in s['diagnosis'][:3]), reverse=True)
    f0, g0 = res['findings'][0], s['diagnosis'][0]
    assert (f0['action'], f0['lever_id'], f0['tags'], f0['evidence_sas']) == (g0['action'], g0['lever_id'], g0['tags'], g0['example_sas'])


def test_validator_handles_thousands_separators(sheet):
    s, dm = sheet
    out = _good(sheet)
    pol = _fact(s, 'Main optimizer policy')
    out['findings'][0].update(text='Travel weighs 10 against 60,000 for speed.', fact_refs=[pol['id']])
    assert validate(out, s, dm) == []


@pytest.fixture
def tmp_store(monkeypatch, tmp_path):
    monkeypatch.setenv('REPORT_CARD_STORE_DIR', str(tmp_path))
    return tmp_path


def test_no_key_renders_the_template_and_caches_it(sheet, tmp_store):
    calls = []
    res = day_findings(*sheet, ai_settings=('openai', '', ''), call=lambda *a: calls.append(a))
    assert res['source'] == 'template' and calls == [] and res['validation']['ai_configured'] is False
    assert res['driver_map'] == sheet[1] and len(list((tmp_store / 'ai').iterdir())) == 1


def test_invalid_answer_is_retried_once_then_accepted(sheet, tmp_store):
    answers = iter(['{"headline": "Everything was 100% perfect."}', json.dumps(_good(sheet))])
    prompts = []
    res = day_findings(*sheet, ai_settings=('openai', 'k', 'gpt-4o'),
                       call=lambda p, k, m, prompt: prompts.append(prompt) or next(answers))
    assert res['source'] == 'ai' and res['validation'] == {'passed': True, 'retries': 1, 'errors': [], 'ai_configured': True}
    assert 'action' in res['findings'][0] and res['findings'][0]['impact_minutes'] >= res['findings'][-1]['impact_minutes']
    assert 'previous answer was rejected' in prompts[1]
    cached = day_findings(*sheet, ai_settings=('openai', 'k', 'gpt-4o'), call=lambda *a: pytest.fail('cache miss'))
    assert cached['source'] == 'ai'


def test_two_bad_answers_fall_back_to_the_template(sheet, tmp_store):
    res = day_findings(*sheet, ai_settings=('openai', 'k', 'gpt-4o'), call=lambda *a: 'not json')
    assert res['source'] == 'template' and res['validation']['passed'] is False and res['validation']['retries'] == 1


def test_network_failure_is_not_cached(sheet, tmp_store):
    res = day_findings(*sheet, ai_settings=('anthropic', 'k', ''), call=lambda *a: None)
    assert res['source'] == 'template' and not (tmp_store / 'ai').exists() or not list((tmp_store / 'ai').iterdir())


# ── Member impact (metrics-spec 5B) ──

def _call_sa(arrival=None, t_end=None, cancel_reason=None, pta0=60, due0='2026-09-28T17:00:00.000Z'):
    return {'pta_initial_min': pta0, 'pta_initial_due': due0, 'pta_min': 120, 'pta_due': '2026-09-28T18:00:00.000Z',
            'cancel_reason': cancel_reason, 'milestones': {'arrival': arrival, 't_end': t_end}}


def test_member_wait_uses_the_original_promise_and_the_member_cancel_rule():
    from report_card_facts import member_wait
    sas = {
        'late': _call_sa(arrival='2026-09-28T17:30:00.000Z'),                                  # 30 min past the original
        'gave_up': _call_sa(t_end='2026-09-28T17:20:00.000Z', cancel_reason='Member Could Not Wait'),
        'facility': _call_sa(t_end='2026-09-28T17:20:00.000Z', cancel_reason='Facility initiated'),
        'early_cancel': _call_sa(t_end='2026-09-28T16:20:00.000Z', cancel_reason='member found own service'),
        'no_pta': _call_sa(arrival='2026-09-28T19:00:00.000Z', pta0=999),
        'on_time': _call_sa(arrival='2026-09-28T16:50:00.000Z'),
    }
    assert member_wait(sas, rules_for('r2')) == {'late': 30, 'gave_up': 20}
    assert member_wait(sas, rules_for('r1')) == {'no_pta': 60}   # r1 grades the re-based 120-min promise


def test_one_call_dominating_a_finding_is_named(sheet):
    s, _ = sheet
    for g in s['diagnosis']:
        if g.get('mostly_one_call'):
            assert g['mostly_one_call'].startswith('SA-') and g['late_calls'] > 1
    from report_card_facts import _impact_sentence
    g = {'impact_minutes': 700, 'late_calls': 3, 'mostly_one_call': 'SA-974049'}
    assert _impact_sentence(g).endswith('Mostly one call (SA-974049).')
