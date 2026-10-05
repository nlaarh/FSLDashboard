"""wo_takeaways.py: plain-rule takeaways. Synthetic story and steps, no I/O."""

from wo_takeaways import takeaways


def st(i, title, dt, driver=None, kind='system', detail='', flag=None):
    return {'id': i, 'title': title, 'dt': dt, 'kind': kind, 'detail': detail, 'flag': flag, 'names': {'driver': driver} if driver else {}}


def story(**o):
    s = {'pta': {'initial_min': 60, 'margin_initial_min': 8.0, 'response_min': 52, 'arrival': 'x', 'rebased': None}, 'segments': [],
         'verdict': {'evidence': {}}, 'sms': {'rows': [{'outcome': 'sent'}, {'outcome': 'sent'}], 'source': 'send_log', 'why_not': []}}
    s.update(o)
    return s


GOOD = [st('E1', 'Call received', 0, kind='member'), st('E3', 'Assigned to Ann', 40, 'Ann'), st('E8', 'Released to Ann (Dispatched)', 70),
        st('S1', 'Text: Garage and PTA', 90, kind='sms')]


def test_a_clean_on_time_call_has_only_good_news():
    t = takeaways(story(), GOOD)
    assert t['verdict'] == 'good' and not t['went_wrong'] and not t['improve']
    texts = ' | '.join(w['text'] for w in t['went_well'])
    assert 'arrived 8 min before the original promise' in texts and 'never re-assigned' in texts and 'All 2 texts' in texts
    assert 'got the garage and arrival time within 2 min' in texts


def test_churn_late_arrival_and_a_closer_driver_are_called_out_with_numbers_and_levers():
    steps = [st('E1', 'Call received', 0), st('E3', 'Assigned to Ann', 10, 'Ann'), st('E5', 'Assigned to Bo', 60, 'Bo'), st('E7', 'Assigned to Cy', 400, 'Cy'),
             st('E8', 'Released to Cy (Dispatched)', 520)]
    s = story(pta={'initial_min': 60, 'margin_initial_min': -34.5, 'response_min': 94.4, 'arrival': 'x', 'rebased': None},
              verdict={'evidence': {'pick_miles': 3.6, 'closest_q_miles': 2.3, 'picked_closest': False, 'extra_miles': 1.3, 'pick_open_jobs': 1, 'closest_free_q_miles': None}})
    t = takeaways(s, steps)
    wrong = [w['text'] for w in t['went_wrong']]
    assert t['verdict'] == 'poor' and wrong[0].startswith('The driver arrived 34 min after the original promise of 60 min')
    assert any('assigned 3 times before it was first released' in w for w in wrong)
    assert any('A closer qualified driver existed: 2.3 mi away against the 3.6 mi driver' in w for w in wrong)
    owners = {i['owner'] for i in t['improve']}
    assert 'FSL admin' in owners                                     # L05 (lock after first pick) and L04 (travel weight)


def test_long_wait_busy_driver_declines_rejection_and_missing_texts():
    steps = [st('E1', 'Call received', 0), st('D1', 'Garage declined in 33 s', 40, detail='x'), st('D2', 'Garage declined in 36 s', 80, detail='x'),
             st('R1', 'Driver rejected', 200, detail='Out of Area'), st('S1', 'Text: Garage and PTA', 4900, kind='sms')]
    s = story(segments=[{'kind': 'S3', 'minutes': 68.7, 'severity': 'CRITICAL', 'driver': 'Isaiah', 'driver_state': 'BUSY', 'event_ids': ['E8']}],
              sms={'rows': [{'outcome': 'sent'}, {'outcome': 'no_consent'}], 'source': 'send_log', 'why_not': [{'text': "No 'still working' text fired."}]})
    wrong = [w['text'] for w in takeaways(s, steps)['went_wrong']]
    assert any('waited 69 min for Isaiah to accept' in w and 'still on another job' in w for w in wrong)
    assert any('2 Towbook garages declined' in w for w in wrong) and any('rejected the call (Out of Area)' in w for w in wrong)
    assert any('1 text to the member did not go out (no_consent)' in w for w in wrong)
    assert any('first text with the garage and the arrival time came 82 min' in w for w in wrong)
    assert any("No 'still working' text fired." in w for w in wrong)


def test_worst_problems_come_first_and_every_problem_points_at_replay_steps():
    steps = [st('E1', 'Call received', 0), st('E3', 'Assigned to Ann', 10, 'Ann'), st('R1', 'Driver rejected', 90, detail='Busy')]
    s = story(pta={'initial_min': 60, 'margin_initial_min': -5, 'response_min': 65, 'arrival': 'x', 'rebased': None})
    t = takeaways(s, steps)
    sev = [w['severity'] for w in t['went_wrong']]
    assert sev == sorted(sev, key=lambda x: {'bad': 0, 'warn': 1, 'info': 2}[x])
    assert next(w for w in t['went_wrong'] if 'rejected' in w['text'])['step_ids'] == ['R1']


def test_no_arrival_is_a_failure_and_an_empty_story_does_not_crash():
    t = takeaways(story(pta={'arrival': None}), GOOD)
    assert any('No driver arrived' in w['text'] for w in t['went_wrong'])
    assert takeaways({}, [])['verdict'] in ('good', 'mixed', 'poor')
