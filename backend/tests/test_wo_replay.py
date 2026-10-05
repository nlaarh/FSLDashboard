"""wo_replay.py: call story -> animation steps. Synthetic story, no Salesforce."""

from wo_replay import build_replay


def ev(i, ts, kind, cls, actor, **kw):
    return {'id': f'E{i}', 'ts': ts, 'kind': kind, 'actor_class': cls, 'actor': actor, 'hidden': False, 'leg': 'member',
            'fields': kw.pop('fields', []), **kw}


def story(**over):
    s = {
        'resolution': {'wo': {'number': '0001'}, 'legs': [{'number': 'SA-1', 'selected': True}]},
        'header': {'work_type': 'Tow', 'source': 'IVR', 'final_garage': '076DO - Test Garage',
                   'channel_path': [{'garage': '076DO - Test Garage'}]},
        'pta': {'initial_min': 60, 'due_initial': '2026-09-28T16:44:11.000Z', 'met_initial': False, 'margin_initial_min': -34.5},
        'events': [
            ev(1, '2026-09-28T15:44:12.000Z', 'E01_sa_created', 'INTEGRATION', 'Replicant Integration User'),
            ev(2, '2026-09-28T15:44:23.000Z', 'E04_assigned', 'FSL_AUTO_SCHEDULE', 'Mulesoft Integration', driver='Ann Lee 100'),
            ev(3, '2026-09-28T15:52:55.000Z', 'E06_dispatched', 'HUMAN', 'Pat Dispatcher'),
            ev(4, '2026-09-28T17:01:39.000Z', 'E07_accepted', 'DRIVER', 'Ann Lee', fields=[{'field': 'Status', 'new': 'Accepted'}]),
            ev(5, '2026-09-28T15:44:15.000Z', 'E99_other', 'INTEGRATION', 'Mulesoft Integration', hidden=True),
        ],
        'sms': {'rows': [{'ts': '2026-09-28T15:44:13.000+0000', 'label': 'Call received', 'outcome': 'sent', 'checkpoint_min': 0},
                         {'ts': '2026-09-28T16:14:51.000+0000', 'label': 'Still working on it', 'outcome': 'no_consent',
                          'reason': 'member did not opt in', 'checkpoint_min': 30}], 'why_not': []},
        'bullets': [{'text': 'Assigned once.', 'headline': True, 'event_ids': ['E2', 'E99']}],
        'verdict': {'primary': 'CAPACITY_SHORT', 'evidence': {'pick_miles': 3.6, 'closest_q_miles': 2.3, 'picked_closest': False,
                                                              'final_actor_class': 'FSL_ENGINE'}},
    }
    s.update(over)
    return s


def by_id(r):
    return {s['id']: s for s in r['steps']}


def test_steps_in_time_order_with_eastern_clock_and_seconds_since_start():
    r = build_replay(story())
    assert [s['id'] for s in r['steps']] == ['C0', 'E1', 'S1', 'E2', 'E3', 'S2', 'P1', 'E4']
    assert r['steps'][0]['clock'] == '11:44:12' and r['steps'][0]['dt'] == 0
    assert by_id(r)['E2']['dt'] == 11


def test_intake_channel_and_route():
    r = by_id(build_replay(story()))
    assert r['C0']['title'] == 'Call captured: Voice AI (Replicant)'
    assert (r['C0']['from'], r['C0']['to']) == ('member', 'src_ivr')
    assert (r['E1']['from'], r['E1']['via'], r['E1']['to']) == ('src_ivr', 'intake', 'sf')
    assert r['E1']['detail'] == 'Promise to the member: 60 min'


def test_who_acted_decides_the_route_and_driver_suffix_is_dropped():
    r = by_id(build_replay(story()))
    assert (r['E2']['via'], r['E2']['kind'], r['E2']['names']['driver']) == ('fsl', 'system', 'Ann Lee')
    assert r['E2']['role'] == 'FSL auto-schedule'
    assert (r['E3']['via'], r['E3']['kind'], r['E3']['names']['dispatcher']) == ('dispatcher', 'human', 'Pat Dispatcher')
    assert (r['E4']['from'], r['E4']['to'], r['E4']['kind']) == ('driver', 'sf', 'driver')


def test_each_source_lights_its_own_circle():
    for source, node in [('DRR', 'src_drr'), ('Intake', 'src_mcc'), ('RAP', 'src_partner')]:
        s = story(); s['header']['source'] = source
        assert by_id(build_replay(s))['C0']['to'] == node


def test_steps_carry_what_was_inside_the_change_and_never_ids_or_noise():
    s = story()
    s['events'][1]['fields'] = [{'field': 'ERS_Assigned_Resource__c', 'old': None, 'new': 'Ann Lee 100'},
                                {'field': 'SchedStartTime', 'new': '2026-09-28T16:21:00.000+0000'},
                                {'field': 'ServiceTerritory', 'old': None, 'new': '0HhPb00000005R7KAI'}]
    r = by_id(build_replay(s))
    assert r['E2']['content'] == ['Driver: Ann Lee']
    assert r['S2']['content'][0] == 'Message: Still working on it (30 min)'


def test_content_reads_cleanly_for_new_values_and_whole_numbers():
    s = story()
    s['events'][1]['fields'] = [{'field': 'Status', 'old': 'None', 'new': 'Spotted'}, {'field': 'ERS_PTA__c', 'old': '90.0', 'new': '60.0'}]
    assert by_id(build_replay(s))['E2']['content'] == ['Status: Spotted', 'Promise (min): 90 → 60']
    s['events'][1]['fields'] += [{'field': 'ERS_PTA__c', 'old': None, 'new': '90.0'}, {'field': 'ERS_PTA__c', 'old': '90.0', 'new': '60.0'}]
    s['events'][1]['fields'] = s['events'][1]['fields'][2:]
    assert by_id(build_replay(s))['E2']['content'] == ['Promise (min): 90 → 60']


def test_a_text_that_was_not_sent_is_a_flagged_problem_step():
    s2 = by_id(build_replay(story()))['S2']
    assert s2['title'].startswith('Text NOT sent') and s2['flag']['level'] == 'bad'
    assert s2['detail'] == 'member did not opt in'


def test_promise_step_flagged_when_driver_was_late():
    p1 = by_id(build_replay(story()))['P1']
    assert p1['flag']['text'] == 'Arrived 34 min after the promise'  # round(34.5) is 34 (banker's rounding)


def test_hidden_noise_events_are_not_drawn_and_problems_link_only_to_real_steps():
    r = build_replay(story())
    assert 'E5' not in by_id(r)
    assert r['problems'][0]['step_ids'] == ['E2']


def test_decision_summary_comes_from_the_verdict_evidence():
    d = build_replay(story())['decision']
    assert (d['pick_miles'], d['closest_qualified_miles'], d['picked_closest'], d['who_decided']) == (3.6, 2.3, False, 'FSL optimizer')


def test_towbook_offer_decline_and_no_phone_or_address_in_output():
    s = story()
    s['events'] += [ev(6, '2026-09-28T15:45:00.000Z', 'E04_assigned', 'INTEGRATION', 'IT System User', driver='Towbook-4652 4652'),
                    ev(7, '2026-09-28T15:45:33.000Z', 'E07_declined', 'TOWBOOK_SYNC', 'Integrations Towbook', reason=None, seconds_from_offer=33)]
    r = by_id(build_replay(s))
    assert r['E6']['to'] == 'towbook'
    assert r['E7']['title'] == 'Garage declined in 33 s' and r['E7']['flag']['level'] == 'warn'
    blob = str(build_replay(s)).lower()
    assert 'phone' not in blob and 'street' not in blob


def test_empty_story_does_not_crash():
    s = story(events=[], sms={'rows': [], 'why_not': []}, pta={})
    assert build_replay(s)['steps'] == []


def test_placeholder_drivers_read_as_what_they_are():
    from wo_replay import _driver
    assert _driver('Towbook-630 630') == 'Towbook 630'
    assert _driver('000-ST Spot 000- ST') == 'SPOT queue (no driver)'
    assert _driver('Marquan Gates 100') == 'Marquan Gates' and _driver(None) == ''
