"""Daily facts, the builder: one UTC day of appointments in, one row per garage out.

The numbers are the ones Reporting (routers/reporting.py `_compute_bulk_report`) and the 30-day trends
(routers/dispatch_trends.py `_fetch`) already compute, computed by the same rules on the same Salesforce fields:
  - Tow Drop-Off is excluded everywhere ('drop' in the work type name).
  - Towbook ATA never uses ActualStartTime (a midnight bulk update): it is the first 'On Location' row of the
    appointment's Status history. Fleet ('Field Services') trends ATA uses ActualStartTime.
  - A day is the UTC date of the appointment's CreatedDate, the same bucket Reporting (UTC date range) and the trends
    (CreatedDate[:10]) already use.
Reporting needs medians and share-under-45-min over a whole range, so each garage-day keeps its list of ATA, PTA and
PTA-delta values (about 20 numbers a garage a day) and not only averages: that is what makes ranges add up exactly.
Appointment surveys are not stored: both screens keep reading them live (one small query).

`compute_garage_facts` and `count_reassignments` are pure (rows in, numbers out) and tested against the live code paths.
"""

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sf_client import get_stats, sf_query_all
from utils import parse_dt

log = logging.getLogger('facts_build')

FACTS_VERSION = 1           # bump when a definition below changes: older rows then stop counting as covered

# Reporting's appointment status list (routers/reporting.py), kept here so the facts match it
R_STATUSES = ('Dispatched', 'Completed', 'Canceled', 'Assigned', 'Cancel Call - Service Not En Route',
              'Cancel Call - Service En Route', 'Unable to Complete', 'No-Show')
_SF_ID = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')


def _blank(name: str) -> dict:
    return {'territory_name': name, 'r_total': 0, 'r_completed': 0, 'r_declined': 0, 'r_cancelled': 0,
            'r_first_total': 0, 'r_first_accepted': 0, 'r_second_total': 0, 'r_second_accepted': 0,
            'r_accepted': 0, 'r_accepted_completed': 0, 'ata': [], 'pta': [], 'pts': [],
            't_volume': 0, 't_completed': 0, 't_auto': 0, 't_fsl_volume': 0, 't_towbook_volume': 0,
            't_fleet_sum': 0.0, 't_fleet_n': 0, 't_sla_hits': 0, 't_tb_sum': 0.0, 't_tb_n': 0}


def history_lookups(history: list) -> tuple[dict, dict]:
    """({sa id: earliest 'On Location' datetime}, {sa id: first territory id}) from Status/ServiceTerritory history,
    the way Reporting builds them (oldest row first per appointment)."""
    on_loc, first_terr = {}, {}
    for h in sorted(history, key=lambda h: (h.get('ServiceAppointmentId') or '', h.get('CreatedDate') or '')):
        sa_id = h.get('ServiceAppointmentId')
        if not sa_id:
            continue
        field = h.get('Field', '')
        if field == 'Status' and h.get('NewValue') == 'On Location':
            ts = parse_dt(h.get('CreatedDate'))
            if ts and (sa_id not in on_loc or ts < on_loc[sa_id]):
                on_loc[sa_id] = ts
        elif field == 'ServiceTerritory' and sa_id not in first_terr:
            if h.get('OldValue') is None:
                nv = h.get('NewValue') or ''
                if len(nv) >= 15 and nv.startswith('0H'):
                    first_terr[sa_id] = nv
    return on_loc, first_terr


def human_touched(assign_rows: list) -> set:
    """SA ids reassigned at least once (more than 2 rows: each assignment writes a name row and an id row) with a human
    (profile 'Membership User') involved: the trends' 'manual dispatch' rule."""
    count, human = defaultdict(int), set()
    for r in assign_rows:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id:
            continue
        count[sa_id] += 1
        if ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name', '') == 'Membership User':
            human.add(sa_id)
    return {sa_id for sa_id, n in count.items() if n > 2 and sa_id in human}


def compute_garage_facts(sas: list, history: list, assign_rows: list) -> dict:
    """{territory id: facts dict} for the appointments of one day."""
    on_loc, first_terr = history_lookups(history)
    touched = human_touched(assign_rows)
    out = {}
    for sa in sas:
        tid = sa.get('ServiceTerritoryId')
        if not tid:
            continue
        if 'drop' in ((sa.get('WorkType') or {}).get('Name') or '').lower():
            continue                                                        # Tow Drop-Off never counts
        g = out.setdefault(tid, _blank((sa.get('ServiceTerritory') or {}).get('Name', '')))
        g['territory_name'] = (sa.get('ServiceTerritory') or {}).get('Name', '')
        status, dm = sa.get('Status'), sa.get('ERS_Dispatch_Method__c') or ''
        created = parse_dt(sa.get('CreatedDate'))
        if status in R_STATUSES:
            _reporting_part(g, sa, tid, status, dm, created, on_loc, first_terr)
        _trends_part(g, sa, status, dm, created, on_loc, touched)
    return out


def _reporting_part(g, sa, tid, status, dm, created, on_loc, first_terr):
    declined = bool(sa.get('ERS_Facility_Decline_Reason__c'))
    g['r_total'] += 1
    g['r_declined'] += declined
    g['r_cancelled'] += 'cancel' in (status or '').lower()
    first = first_terr.get(sa['Id'], tid) == tid
    second = sa['Id'] in first_terr and first_terr[sa['Id']] != tid
    g['r_first_total'] += first
    g['r_first_accepted'] += first and not declined
    g['r_second_total'] += second
    g['r_second_accepted'] += second and not declined
    g['r_accepted'] += not declined
    if status != 'Completed':
        return
    g['r_completed'] += 1
    g['r_accepted_completed'] += not declined
    actual = on_loc.get(sa['Id']) if dm == 'Towbook' else parse_dt(sa.get('ActualStartTime'))
    pta_raw = sa.get('ERS_PTA__c')
    pv = float(pta_raw) if pta_raw is not None else None
    if pv is not None and 0 < pv < 999:
        g['pta'].append(pv)
    if created and actual:
        ata = (actual - created).total_seconds() / 60
        if 0 < ata < 480:
            g['ata'].append(ata)
            if pv is not None and 0 < pv < 999:
                g['pts'].append((actual - (created + timedelta(minutes=pv))).total_seconds() / 60)


def _trends_part(g, sa, status, dm, created, on_loc, touched):
    g['t_volume'] += 1
    g['t_auto'] += sa.get('Id') not in touched
    g['t_fsl_volume'] += dm == 'Field Services'
    g['t_towbook_volume'] += dm == 'Towbook'
    if status != 'Completed':
        return
    g['t_completed'] += 1
    if dm == 'Field Services':
        actual = parse_dt(sa.get('ActualStartTime'))
        if created and actual:
            diff = (actual - created).total_seconds() / 60
            if 0 < diff < 480:
                g['t_fleet_sum'] += diff
                g['t_fleet_n'] += 1
                g['t_sla_hits'] += diff <= 45
    elif dm == 'Towbook':
        ol = on_loc.get(sa.get('Id'))
        if ol and created:
            diff = (ol - created).total_seconds() / 60
            if 0 < diff < 480:
                g['t_tb_sum'] += diff
                g['t_tb_n'] += 1


def count_reassignments(rows: list, day: str) -> int:
    """Assignments after the first for an appointment, by the UTC date of the history row (the trends' rule: name rows
    only, 2nd and later). `rows` should reach one day back so an appointment that started the evening before counts."""
    seq, n = defaultdict(int), 0
    for r in sorted(rows, key=lambda r: (r.get('ServiceAppointmentId') or '', r.get('CreatedDate') or '')):
        new_val = (r.get('NewValue') or '').strip()
        if not new_val or _SF_ID.match(new_val):
            continue
        sa_id = r.get('ServiceAppointmentId')
        seq[sa_id] += 1
        if seq[sa_id] > 1 and (r.get('CreatedDate') or '')[:10] == day:
            n += 1
    return n


# ── Salesforce pulls for one day (sequential, each paginated; 4 queries) ─────────────────────────────────────────────

def _window(day: str) -> tuple[str, str]:
    d = date.fromisoformat(day)
    return f'{d.isoformat()}T00:00:00Z', f'{(d + timedelta(days=1)).isoformat()}T00:00:00Z'


def _sa_filter(since: str, until: str) -> str:
    return (f"CreatedDate >= {since} AND CreatedDate < {until} AND RecordType.Name = 'ERS Service Appointment' "
            "AND ServiceTerritoryId != null")


def pull_day(day: str) -> dict:
    """The four Salesforce reads for one UTC day, one after another. Returns the raw rows and the request count."""
    since, until = _window(day)
    prev = f'{(date.fromisoformat(day) - timedelta(days=1)).isoformat()}T00:00:00Z'
    calls0 = _requests()
    sas = sf_query_all(f"""SELECT Id, ServiceTerritoryId, ServiceTerritory.Name, Status, CreatedDate, ActualStartTime,
        ERS_PTA__c, ERS_Dispatch_Method__c, ERS_Facility_Decline_Reason__c, WorkType.Name
        FROM ServiceAppointment WHERE {_sa_filter(since, until)}""")
    history = sf_query_all(f"""SELECT ServiceAppointmentId, Field, OldValue, NewValue, CreatedDate
        FROM ServiceAppointmentHistory WHERE Field IN ('Status', 'ServiceTerritory')
        AND ServiceAppointmentId IN (SELECT Id FROM ServiceAppointment WHERE {_sa_filter(since, until)})""")
    assign = sf_query_all(f"""SELECT ServiceAppointmentId, CreatedBy.Profile.Name
        FROM ServiceAppointmentHistory WHERE Field = 'ERS_Assigned_Resource__c'
        AND ServiceAppointmentId IN (SELECT Id FROM ServiceAppointment WHERE {_sa_filter(since, until)})""")
    reassign = sf_query_all(f"""SELECT ServiceAppointmentId, CreatedDate, NewValue
        FROM ServiceAppointmentHistory WHERE CreatedDate >= {prev} AND CreatedDate < {until}
        AND Field = 'ERS_Assigned_Resource__c' AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'""")
    return {'sas': sas, 'history': history, 'assign': assign, 'reassign': reassign, 'requests': _requests() - calls0}


def _requests() -> int:
    s = get_stats()
    return s.get('total_calls', 0) + s.get('pages', 0)


def build_day(day: str, now: datetime | None = None) -> dict:
    """{'day', 'computed_at', 'version', 'sa_count', 'reassignments', 'garages': {tid: facts}, 'requests'} for a UTC day."""
    raw = pull_day(day)
    garages = compute_garage_facts(raw['sas'], raw['history'], raw['assign'])
    return {'day': day, 'computed_at': now or datetime.now(timezone.utc), 'version': FACTS_VERSION,
            'sa_count': sum(g['t_volume'] for g in garages.values()),
            'reassignments': count_reassignments(raw['reassign'], day), 'garages': garages, 'requests': raw['requests']}
