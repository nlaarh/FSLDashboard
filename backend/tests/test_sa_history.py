"""The shared appointment-history copy: one big load, then tiny updates; old appointments and failures read directly."""

import time

import pytest

import sa_history as sh


class FakeSF:
    """Pretends to be Salesforce: remembers every query and answers from a list of history rows."""
    def __init__(self, rows=()):
        self.rows, self.queries, self.fail = list(rows), [], False

    def sf_query_all(self, soql):
        self.queries.append(soql)
        if self.fail:
            raise RuntimeError('salesforce down')
        if 'WHERE ServiceAppointmentId IN' in soql:                          # the old direct lookup
            ids = soql.split("IN ('")[1].split("')")[0].split("','")
            field = soql.split("Field = '")[1].split("'")[0]
            return [r for r in self.rows if r['ServiceAppointmentId'] in ids and r['Field'] == field]
        if 'AND CreatedDate >=' in soql:                                     # a delta: only rows since the given time
            since = soql.split('AND CreatedDate >= ')[1].split(' ')[0]
            return [r for r in self.rows if r['CreatedDate'][:19] >= since[:19].replace('Z', '')]
        return list(self.rows)                                               # the full window load


def H(i, sa, field, new, ts, who='Pat'):
    return {'Id': f'H{i}', 'ServiceAppointmentId': sa, 'Field': field, 'NewValue': new, 'OldValue': None,
            'CreatedDate': ts, 'CreatedBy': {'Name': who, 'Profile': {'Name': 'Membership User'}}}


@pytest.fixture
def sf(monkeypatch):
    fake = FakeSF()
    monkeypatch.setattr(sh.sf_client, 'sf_query_all', fake.sf_query_all)
    sh._st.update(rows={}, seen=set(), window_start=None, loaded_at=0.0, synced_at=0.0)
    for k in sh.stats: sh.stats[k] = 0
    return fake


def _now_iso(offset_s=0):
    return time.strftime('%Y-%m-%dT%H:%M:%S.000+0000', time.gmtime(time.time() + offset_s))


def test_first_use_loads_the_window_once_and_later_uses_cost_one_small_query(sf):
    sf.rows = [H(1, 'A', 'Status', 'Dispatched', _now_iso(-600)), H(2, 'A', 'Status', 'On Location', _now_iso(-300))]
    created = {'A': _now_iso(-3600)}
    assert [r['NewValue'] for r in sh.rows_for('Status', ['A'], created)] == ['Dispatched', 'On Location']
    assert sh.stats['full_loads'] == 1 and len(sf.queries) == 1
    sh._st['synced_at'] -= 60                                               # a minute later
    sf.rows.append(H(3, 'A', 'Status', 'Completed', _now_iso()))
    assert [r['NewValue'] for r in sh.rows_for('Status', ['A'], created)] == ['Dispatched', 'On Location', 'Completed']
    assert sh.stats['deltas'] == 1 and len(sf.queries) == 2 and 'AND CreatedDate >=' in sf.queries[1]


def test_screens_refreshing_together_share_one_update(sf):
    sf.rows = [H(1, 'A', 'Status', 'Dispatched', _now_iso(-60))]
    created = {'A': _now_iso(-3600)}
    for field in ('Status', 'ERS_Assigned_Resource__c', 'ServiceTerritory', 'Status'):
        sh.rows_for(field, ['A'], created)
    assert len(sf.queries) == 1                                              # one load serves every screen and every field


def test_a_row_seen_twice_in_the_overlap_is_stored_once(sf):
    sf.rows = [H(1, 'A', 'Status', 'Dispatched', _now_iso(-30))]
    created = {'A': _now_iso(-3600)}
    sh.rows_for('Status', ['A'], created)
    sh._st['synced_at'] -= 60
    assert len(sh.rows_for('Status', ['A'], created)) == 1                   # the delta re-read it; not duplicated


def test_each_field_returns_only_its_own_rows_in_time_order_with_the_old_shape(sf):
    sf.rows = [H(2, 'A', 'ERS_Assigned_Resource__c', 'Tyler', _now_iso(-200), who='Tyler LaFave'),
               H(1, 'A', 'Status', 'Dispatched', _now_iso(-300)), H(3, 'A', 'ServiceTerritory', 'G2', _now_iso(-100))]
    created = {'A': _now_iso(-3600)}
    status = sh.rows_for('Status', ['A'], created)
    assert [r['NewValue'] for r in status] == ['Dispatched'] and {'ServiceAppointmentId', 'NewValue', 'CreatedDate'} <= set(status[0])
    who = sh.rows_for('ERS_Assigned_Resource__c', ['A'], created)[0]
    assert who['NewValue'] == 'Tyler' and who['CreatedBy']['Name'] == 'Tyler LaFave' and who['CreatedBy']['Profile']['Name'] == 'Membership User'
    assert [r['NewValue'] for r in sh.rows_for('ServiceTerritory', ['A'], created)] == ['G2']


def test_callers_get_private_copies(sf):
    sf.rows = [H(1, 'A', 'Status', 'Dispatched', _now_iso(-60))]
    created = {'A': _now_iso(-3600)}
    sh.rows_for('Status', ['A'], created)[0]['NewValue'] = 'TAMPERED'
    assert sh.rows_for('Status', ['A'], created)[0]['NewValue'] == 'Dispatched'


def test_an_appointment_older_than_the_window_is_read_directly(sf):
    sf.rows = [H(1, 'NEW', 'Status', 'Dispatched', _now_iso(-60)), H(2, 'OLD', 'Status', 'Completed', _now_iso(-30 * 3600))]
    created = {'NEW': _now_iso(-3600), 'OLD': _now_iso(-31 * 3600)}
    out = sh.rows_for('Status', ['NEW', 'OLD'], created)
    assert {r['ServiceAppointmentId'] for r in out} == {'NEW', 'OLD'}        # OLD was fetched, not silently dropped
    assert any("WHERE ServiceAppointmentId IN ('OLD')" in q for q in sf.queries) and sh.stats['fallback_ids'] == 1


def test_everything_is_reloaded_after_an_hour(sf):
    sf.rows = [H(1, 'A', 'Status', 'Dispatched', _now_iso(-60))]
    created = {'A': _now_iso(-3600)}
    sh.rows_for('Status', ['A'], created)
    sh._st['loaded_at'] -= sh.FULL_RELOAD_S + 5
    sh.rows_for('Status', ['A'], created)
    assert sh.stats['full_loads'] == 2


def test_if_salesforce_fails_the_old_direct_lookup_still_answers_or_raises_like_before(sf):
    sf.rows = [H(1, 'A', 'Status', 'Dispatched', _now_iso(-60))]
    created = {'A': _now_iso(-3600)}
    sh.rows_for('Status', ['A'], created)                                    # loaded fine
    sh._st['synced_at'] -= 60
    sf.fail = True
    with pytest.raises(RuntimeError):                                         # delta fails -> direct lookup also fails -> same error as before
        sh.rows_for('Status', ['A'], created)
    sf.fail = False
    assert [r['NewValue'] for r in sh.rows_for('Status', ['A'], created)] == ['Dispatched']


def test_towbook_arrival_uses_the_shared_copy_and_the_first_on_location_wins(sf):
    import sf_client
    sf.rows = [H(1, 'A', 'Status', 'En Route', _now_iso(-500)), H(2, 'A', 'Status', 'On Location', _now_iso(-400)),
               H(3, 'A', 'Status', 'On Location', _now_iso(-300)), H(4, 'B', 'Status', 'Completed', _now_iso(-200))]
    created = {'A': _now_iso(-3600), 'B': _now_iso(-3600)}
    out = sf_client.get_towbook_on_location(['A', 'B'], created)
    assert out == {'A': sf.rows[1]['CreatedDate']}                       # the FIRST On Location, and only for A
    assert len(sf.queries) == 1                                          # one load, no per-batch lookups


def test_without_the_created_map_the_original_direct_lookup_is_still_used(sf, monkeypatch):
    import sf_client
    seen = []
    monkeypatch.setattr(sf_client, 'sf_query_all', lambda q: seen.append(q) or [])
    sf_client.get_towbook_on_location(['A'])                             # other callers (scorecards, etc.) are untouched
    assert len(seen) == 1 and "WHERE ServiceAppointmentId IN ('A')" in seen[0] and sh.stats['full_loads'] == 0
