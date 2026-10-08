"""Replay extras rules (Henry's H2-H4). Fixture: real 10/07 work orders, trimmed to status/holder history (no phones, no names
beyond the FSL driver). The four test work orders and their expected values are Henry's (replay_v2_design.md, H5)."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import replay_extras as rx
from utils import parse_dt

FIX = json.loads((Path(__file__).parent / 'fixtures' / 'replay_extras_1007.json').read_text())
NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
VC = {'CallType': 'Inbound', 'CallDurationInSeconds': 1073, 'User': {'Name': 'Agent One'}}


def _jobs(won):
    """What the live query would return: the driver's SAs created within [given - 12 h, end + 1 h]."""
    f = FIX[won]
    ctx = rx.member_context(f['raw'], NOW)
    lo, hi = ctx['given'] - timedelta(hours=12), ctx['end'] + timedelta(hours=1)
    jobs = [j for j in f['jobs'] if lo <= parse_dt(j['CreatedDate']) <= hi]
    ids = {j['Id'] for j in jobs}
    return ctx, jobs, [r for r in f['trail'] if r['ServiceAppointmentId'] in ids]


def _load(won):
    ctx, jobs, trail = _jobs(won)
    return ctx, rx.driver_load(ctx, jobs, trail)


def _z(et: str) -> str:
    h, m, s = (int(x) for x in et.split(':'))
    return f'2026-10-07T{h + 4:02d}:{m:02d}:{s:02d}.000+0000'


def test_towbook_call_05195827_jobs_ahead_and_after():
    ctx, load = _load('05195827')
    assert ctx['channel'] == 'towbook' and ctx['given'] == parse_dt(_z('14:53:02'))
    assert load['driver'] == 'Towbook Driver' and load['channel'] == 'towbook'          # Towbook drivers are never named
    assert [(a['wo'], a['label']) for a in load['ahead']] == [('05195923', 'not started')]
    assert load['current'] is None
    assert [a['wo'] for a in load['after']] == ['05196239']                              # served before this member
    wos = {a['wo'] for a in load['ahead'] + load['after']}
    assert not wos & {'05196220', '05195364'}                                            # reached after / finished before
    assert load['after'][0]['reached_at'] == '2026-10-07T21:09:29Z'                      # 5:09:29 PM ET
    assert all(a['lat'] is None or a['work_type'].lower().find('drop') < 0 for a in load['ahead'])


def test_fleet_call_05194934_waited_for_previous_job():
    ctx, load = _load('05194934')
    assert ctx['channel'] == 'fleet' and load['driver'] == ctx['driver_name'] and load['channel'] == 'fleet'
    assert [(a['wo'], a['label'], a['is_current']) for a in load['ahead']] == [('05194878', 'driving to it', True)]
    assert load['current']['wo'] == '05194878' and load['after'] == []
    assert load['given_at'] == '2026-10-07T13:40:52Z'                                    # given to him 9:40:52 AM, not the 9:40:37 swap


def test_on_platform_call_05195668_driver_still_driving_to_previous_job():
    ctx, load = _load('05195668')
    assert ctx['channel'] == 'on_platform' and load['channel'] == 'on_platform'
    assert [(a['wo'], a['label']) for a in load['ahead']] == [('05195136', 'driving to it')]
    assert load['after'] == []                                                           # WO 05196132 was given after this member was reached


def test_towing_leg_counts_as_on_the_plate_05194797():
    """Pick-up Completed and drop-off En Route in the same second: grouped by work order, the driver is 'towing'."""
    ctx, load = _load('05194797')
    assert [(a['wo'], a['label'], a['state']) for a in load['ahead']] == [('05194738', 'towing', 'towing')]
    assert load['current']['label'] == 'towing'
    assert all(a['lat'] is None or a['wo'] for a in load['ahead'])


def test_drop_off_never_gets_a_pin():
    ctx, jobs, trail = _jobs('05194797')
    for j in jobs:
        if rx._is_drop(rx._wt(j)):
            assert rx._job_view(j, rx._Trail(trail))['lat'] is None


def test_no_driver_when_never_given_to_one():
    f = FIX['05194934']
    raw = {**f['raw'], 'history': [h for h in f['raw']['history'] if h['Field'] == 'Status' and h['NewValue'] in ('Spotted', 'Canceled')]}
    ctx = rx.member_context(raw, NOW)
    assert ctx['driver'] is None and rx.driver_load(ctx, [], []) is None


def test_towbook_without_driver_gets_note():
    f = FIX['05195827']
    sas = [{**s, 'Off_Platform_Driver__c': None} for s in f['raw']['sas']]
    ctx = rx.member_context({**f['raw'], 'sas': sas}, NOW)
    out = rx.build_extras(ctx, [], [], [], [], None, [])
    assert ctx['channel'] == 'towbook' and out['driver_load'] == [] and rx.TOWBOOK_NOTE in out['notes']


# ---- calls and texts ----------------------------------------------------------------------------------------------

CREATED = parse_dt('2026-10-07T18:17:26.000+0000')          # WO 05195827, 2:17:26 PM ET


def _voice():
    return [
        {**VC, 'Id': 'v1', 'CallStartDateTime': _z('17:20:06'), 'CallEndDateTime': _z('17:37:59'), 'CallAcceptDateTime': _z('17:20:20'),
         'ToPhoneNumber': 'MCC ERS Replicant Return'},
        {**VC, 'Id': 'v2', 'CallType': 'Transfer', 'PreviousCallId': 'v1', 'CallStartDateTime': _z('17:22:00'), 'ToPhoneNumber': 'Dispatch ERS Status'},
        {**VC, 'Id': 'v3', 'CallType': 'Transfer', 'PreviousCallId': 'v2', 'CallStartDateTime': _z('17:30:00'), 'ToPhoneNumber': 'Dispatch ERS Status'},
        {**VC, 'Id': 'v4', 'CallType': 'Transfer', 'PreviousCallId': 'v3', 'CallStartDateTime': _z('17:34:00'), 'ToPhoneNumber': 'Dispatch ERS Status'},
        {**VC, 'Id': 'v0', 'CallStartDateTime': '2026-10-07T18:15:00.000+0000', 'ToPhoneNumber': 'MCC ERS New'},        # 2 min before: the original call
        {**VC, 'Id': 'v5', 'CallStartDateTime': _z('16:00:00'), 'ToPhoneNumber': 'MCC Membership'},
    ]


def test_transfers_fold_into_one_callback_and_other_lines_are_not_callbacks():
    calls = rx.build_calls(_voice(), CREATED)
    assert [c['kind'] for c in calls] == ['original', 'membership_line', 'callback']
    cb = calls[2]
    assert cb['min_after_create'] == 182.7 and cb['duration_s'] == 1073 and cb['agent'] == 'Agent One'
    assert [t['to'] for t in cb['transfers']] == ['Dispatch ERS Status'] * 3
    assert calls[0]['min_after_create'] == -2.4
    assert rx.build_calls([{**VC, 'Id': 'x', 'CallType': 'Outbound', 'CallStartDateTime': _z('17:00:00'), 'ToPhoneNumber': 'MCC ERS New'}], CREATED) == []


def _session(et, label='ERS SMS Messaging Channel', origin='InboundInitiated', conv='conv-1'):
    return {'Id': f's{et}', 'CreatedDate': _z(et), 'StartTime': _z(et), 'EndTime': _z('17:11:52'), 'Origin': origin, 'EndUserMessageCount': 1,
            'Owner': {'Name': 'Deonna M'}, 'Conversation': {'ConversationIdentifier': conv}, 'MessagingChannel': {'MasterLabel': label, 'DeveloperName': 'TEXT_US_1'}}


def test_only_member_started_ers_sms_sessions_count():
    rows = [_session('16:55:56'), _session('16:56:00', label='Other Channel'), _session('16:57:00', origin='OutboundInitiated')]
    texts = rx.build_texts(rows, CREATED)
    assert [t['ts'] for t in texts] == ['2026-10-07T20:55:56Z'] and texts[0]['messages'] == 1


def test_insights_for_05195827_use_henrys_wording_and_levels():
    ctx, jobs, trail = _jobs('05195827')
    out = rx.build_extras(ctx, jobs, trail, _voice(), [_session('16:55:56')], parse_dt(_z('15:06:00')), [])
    by = {i['code']: i for i in out['insights']}
    assert by['CALLED_BACK']['level'] == 'bad'
    assert by['CALLED_BACK']['text'] == ('The member called AAA back 1 time. The first call came 183 min after they asked for help. '
                                         '1 of these came after the promised arrival time.')
    assert by['TEXTED_IN']['level'] == 'warn' and by['TEXTED_IN']['text'] == 'The member texted AAA 1 time. 1 came after the promised arrival time.'
    assert by['DRIVER_AHEAD']['text'] == 'When this call went to the Towbook driver, they still had 1 other job to finish first.'
    assert by['DRIVER_MORE_AFTER']['text'] == 'The Towbook driver served 1 member who called later before reaching this member.'
    assert by['DRIVER_MORE_AFTER']['level'] == 'bad'                                   # arrived 6:36 PM, promise 3:06 PM
    assert [i['level'] for i in out['insights']] == sorted((i['level'] for i in out['insights']), key=rx.LEVELS.get)
    assert out['thread_available'] is True and len(out['calls']) == 3


def test_insights_for_05195668_three_texts_after_the_promise():
    texts = rx.build_texts([_session(e, conv='c') for e in ('10:54:25', '11:19:42', '11:29:45')], CREATED)
    ins = rx.build_insights([], texts, None, parse_dt(_z('10:43:00')), None)
    assert [(i['code'], i['level'], i['text']) for i in ins] == [
        ('TEXTED_IN', 'warn', 'The member texted AAA 3 times. 3 came after the promised arrival time.')]


def test_driver_ahead_wording_names_fleet_driver_and_mentions_current_job():
    ctx, load = _load('05194934')
    ins = rx.build_insights([], [], load, None, None)
    assert ins[0]['text'] == f"When this call went to {rx.short_driver_name(load['driver'])}, they still had 1 other job to finish first. One was already driving to it."
    assert ins[0]['level'] == 'info'


def test_one_callback_before_the_promise_is_info_and_at_most_four_insights():
    cb = [{'kind': 'callback', 'ts': '2026-10-07T19:00:00Z', 'min_after_create': 40.0}]
    assert rx.build_insights(cb, [], None, parse_dt('2026-10-07T20:00:00Z'), None)[0]['level'] == 'info'
    two = cb * 2
    assert rx.build_insights(two, [], None, parse_dt('2026-10-07T20:00:00Z'), None)[0]['level'] == 'warn'


def test_no_phone_digits_or_bodies_in_output():
    ctx, jobs, trail = _jobs('05195827')
    out = rx.build_extras(ctx, jobs, trail, _voice(), [_session('16:55:56')], None, [])
    text = json.dumps(out)
    assert 'conv-1' not in text and 'Conversation' not in text and 'FromPhone' not in text


def test_phone_digits_takes_last_ten():
    assert rx.phone_digits('5858319725', '(585) 831-9725', None, '+1 716 555 0100', '123') == ['5858319725', '7165550100']


def test_insight_names_drop_the_truck_number_like_the_garage_view():
    assert [rx.short_driver_name(n) for n in ('Marcus Gibson 100', 'Ann Lee 12A', 'Jo Kim 118AB', 'Zack Felix 4652D', 'Dee Roe')] == ['Marcus Gibson', 'Ann Lee', 'Jo Kim', 'Zack Felix', 'Dee Roe']
    load = {'driver': 'Marcus Gibson 100', 'channel': 'fleet', 'current': None, 'after': [],
            'ahead': [{'given_at': '2026-10-07T15:00:00Z'}], 'given_at': '2026-10-07T15:00:00Z'}
    out = rx.build_insights([], [], load, None, None)
    assert out[0]['text'].startswith('When this call went to Marcus Gibson, they')
