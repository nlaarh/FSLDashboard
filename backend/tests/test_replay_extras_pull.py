"""Replay extras Salesforce plan: at most 2 composite requests, the right filters, nothing private in the answer."""

import json
from datetime import datetime, timezone

import pytest

import replay_extras_pull as pull
from report_card_build import CompositeError, Puller
from tests.test_replay_extras import FIX, NOW, VC, _session, _voice

PROMISE = '2026-10-07T19:06:00Z'


class FakePuller(Puller):
    """Puller whose composite() answers from a dict; records every request."""

    def __init__(self, phones=None, voice=None, sessions=None, jobs=None, trail=None, fail_round2=False):
        super().__init__(max_calls=4)
        self.requests, self.fail_round2 = [], fail_round2
        self.data = {'phones': [phones or {}], 'calls': voice or [], 'sessions': sessions or [], 'jobs': jobs or [], 'trail': trail or []}

    def composite(self, named):
        self._spend()
        self.requests.append(named)
        if self.fail_round2 and 'calls' in named or self.fail_round2 and 'sessions' in named:
            raise CompositeError('calls', 'boom')
        return {k: self.data[k] for k in named}


def _raw(won='05195827', end_user='0PAFAKE'):
    raw = json.loads(json.dumps(FIX[won]['raw']))
    raw['sms'] = [{'Name': 'x', 'Messaging_End_User__c': end_user}] if end_user else []
    return raw


def _p(won='05195827', **kw):
    return FakePuller(jobs=FIX[won]['jobs'], trail=FIX[won]['trail'], **kw)


def test_two_composites_and_the_answer_has_no_phone():
    p = _p(phones={'Mobile_Phone__c': '5858319725', 'Callback_Phone__c': None}, voice=_voice(), sessions=[_session('16:55:56')])
    out, private = pull.pull_extras(_raw(), PROMISE, NOW, p)
    assert out['sf_calls'] == p.calls == 2 and len(p.requests) == 2
    assert set(p.requests[0]) == {'phones', 'jobs', 'trail'} and set(p.requests[1]) == {'calls', 'sessions'}
    assert '5858319725' not in json.dumps(out) and '585' not in json.dumps(out['window'])
    assert private['conversations'] == ['conv-1'] and 'conv-1' not in json.dumps(out)
    assert [i['code'] for i in out['insights']][0] == 'CALLED_BACK' and out['driver_load'][0]['ahead'][0]['wo'] == '05195923'


def test_phone_is_matched_in_both_formats_and_sessions_use_the_end_user():
    p = _p(phones={'Mobile_Phone__c': '5858319725', 'Callback_Phone__c': '5858319725'})
    pull.pull_extras(_raw(), PROMISE, NOW, p)
    calls_q, sess_q = p.requests[1]['calls'], p.requests[1]['sessions']
    assert "'+1 585 831 9725','+15858319725'" in calls_q and calls_q.count('585 831') == 1
    assert "MessagingEndUserId IN ('0PAFAKE')" in sess_q and 'MessagingPlatformKey' not in sess_q
    assert "Origin = 'InboundInitiated'" in sess_q and 'LIMIT 50' in sess_q


def test_old_call_without_end_user_uses_the_platform_key():
    p = _p(phones={'Mobile_Phone__c': '5858319725'})
    pull.pull_extras(_raw(end_user=None), PROMISE, NOW, p)
    assert "MessagingPlatformKey IN ('+15858319725')" in p.requests[1]['sessions']


def test_no_phone_and_no_end_user_skips_round_two_with_a_note():
    p = _p()
    out, _ = pull.pull_extras(_raw(end_user=None), PROMISE, NOW, p)
    assert p.calls == 1 and len(p.requests) == 1 and out['sf_calls'] == 1
    assert out['calls'] == [] and out['inbound_texts'] == [] and 'No phone number on this work order, so member calls cannot be matched.' in out['notes']


def test_towbook_jobs_filter_uses_only_the_off_platform_driver():
    p = _p()
    pull.pull_extras(_raw(), PROMISE, NOW, p)
    jobs_q, trail_q = p.requests[0]['jobs'], p.requests[0]['trail']
    assert 'Off_Platform_Driver__c = ' in jobs_q and 'ERS_Assigned_Resource__c =' not in jobs_q
    assert "RecordType.Name = 'ERS Service Appointment'" in jobs_q and 'LIMIT 200' in jobs_q
    assert "Field IN ('Status','ERS_Assigned_Resource__c')" in trail_q and trail_q.count('FROM ServiceAppointment WHERE') == 1


def test_fleet_jobs_filter_uses_the_final_holder():
    p = _p('05194934')
    pull.pull_extras(_raw('05194934'), PROMISE, NOW, p)
    jobs_q = p.requests[0]['jobs']
    assert "ERS_Assigned_Resource__c = '0Hn" in jobs_q and 'Off_Platform_Driver__c' not in jobs_q


def test_no_driver_means_phones_only_in_round_one():
    raw = _raw('05194934')
    raw['history'] = [h for h in raw['history'] if h['Field'] == 'Status' and h['NewValue'] == 'Spotted']
    p = _p('05194934')
    out, _ = pull.pull_extras(raw, PROMISE, NOW, p)
    assert set(p.requests[0]) == {'phones'} and out['driver_load'] == []


def test_failed_calls_and_texts_keeps_the_rest():
    p = _p(phones={'Mobile_Phone__c': '5858319725'}, fail_round2=True)
    out, private = pull.pull_extras(_raw(), PROMISE, NOW, p)
    assert 'Member calls and texts could not be loaded.' in out['notes'] and out['driver_load'] and private['conversations'] == []


def test_failed_round_one_raises():
    class Boom(FakePuller):
        def composite(self, named):
            raise CompositeError('jobs', 'bad')
    with pytest.raises(CompositeError):
        pull.pull_extras(_raw(), PROMISE, NOW, Boom())


def test_window_is_capped_at_a_day_and_open_call_ends_now():
    raw = _raw()
    raw['history'] = [h for h in raw['history'] if not (h['Field'] == 'Status' and h['NewValue'] in ('Completed',))]
    now = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc)
    p = _p()
    out, _ = pull.pull_extras(raw, PROMISE, now, p)
    assert out['window']['to'] == '2026-10-07T21:00:00Z'
