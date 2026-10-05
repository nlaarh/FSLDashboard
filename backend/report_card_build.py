"""Scheduler Report Card: Salesforce pull for one garage and one past Eastern day.

architecture.md section 5.2, metrics-spec.md section 2. Every query is a read-only SELECT,
run strictly one after another (never sf_parallel) and bounded by territory + window.
Output is the raw bundle that report_card_snapshot.build_snapshot() turns into a snapshot.

Not in this slice: Q12 region outbound moves, Optimization_Log__c, Q5 Shift (off by default).
"""

import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone

from sf_client import sf_query, sf_query_all, sanitize_soql
from utils import _ET, ERS_SA_FILTER

log = logging.getLogger('report_card_build')

CARRYOVER_HOURS = 6        # SAs created this long before day start may still be open at it
LOGIN_LOOKBACK_HOURS = 14  # truck logins made the evening before still count (spec S8)
AFTER_HOURS = 2            # history read past day end, so late logouts close their shift
GRADED_DRIVER_TYPES = ('Fleet Driver', 'On-Platform Contractor Driver')
SPLIT_COOLDOWN_S = 20      # pause before re-reading a timed-out batch in halves
MIN_SPLIT = 5              # below this many ids a failure is final


def day_window(service_date: str) -> dict:
    """Eastern calendar day as UTC datetimes. DST-safe: 23 h, 24 h or 25 h (spec S1)."""
    d = date.fromisoformat(service_date)
    start = datetime.combine(d, dtime(0), tzinfo=_ET).astimezone(timezone.utc)
    end = datetime.combine(d + timedelta(days=1), dtime(0), tzinfo=_ET).astimezone(timezone.utc)
    return {
        'day_start': start,
        'day_end': end,
        'carryover_from': start - timedelta(hours=CARRYOVER_HOURS),
        'hist_start': start - timedelta(hours=LOGIN_LOOKBACK_HOURS),
        'hist_end': end + timedelta(hours=AFTER_HOURS),
    }


def _iso(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def _in(ids) -> str:
    return ",".join(f"'{sanitize_soql(i)}'" for i in ids)


class CallCapReached(RuntimeError):
    """A capped pull (call story, max_sf_calls) would exceed its Salesforce call budget."""


class Puller:
    """Runs queries one at a time and counts them (recorded as sf_calls)."""

    def __init__(self, max_calls: int | None = None):
        self.calls = 0
        self.max_calls = max_calls

    def _spend(self):
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise CallCapReached(f'Salesforce call cap {self.max_calls} reached')
        self.calls += 1

    def all(self, soql: str) -> list:
        self._spend()
        return sf_query_all(soql)

    def count(self, soql: str) -> int:
        self._spend()
        return sf_query(soql).get('totalSize', 0)

    def batched(self, template: str, ids, size: int = 150, split_on_timeout: bool = False) -> list:
        ids = sorted(set(i for i in ids if i))
        out = []
        for i in range(0, len(ids), size):
            chunk = ids[i:i + size]
            out += self._split_retry(template, chunk) if split_on_timeout else self.all(template.format(ids=_in(chunk)))
        return out

    def _split_retry(self, template: str, ids: list) -> list:
        """GPS history can time out on a large driver set (076DO 2026-08-03 hit the 45 s limit). On a failure,
        cool down, then retry the same rows as two halves, down to MIN_SPLIT ids. Still sequential."""
        try:
            return self.all(template.format(ids=_in(ids)))
        except RuntimeError as e:
            if len(ids) <= MIN_SPLIT:
                raise
            log.warning('report card SF read failed on %d ids (%s); cooling down %ss, retrying in halves',
                        len(ids), e, SPLIT_COOLDOWN_S)
            time.sleep(SPLIT_COOLDOWN_S)
            half = len(ids) // 2
            return self._split_retry(template, ids[:half]) + self._split_retry(template, ids[half:])


_Puller = Puller   # old name, kept for callers

_SA_FIELDS = """Id, AppointmentNumber, Status, CreatedDate, SchedStartTime, SchedEndTime,
 ActualStartTime, ActualEndTime, EarliestStartTime, DueDate, WorkType.Name, ParentRecordId,
 ERS_PTA__c, ERS_PTA_Due__c, ERS_Spotting_Datetime__c, ERS_Dispatch_Method__c,
 ERS_Dynamic_Priority__c, FSL__Duration_In_Minutes__c, FSL__Scheduling_Policy_Used__c,
 Off_Platform_Driver__c, Off_Platform_Driver__r.Name, Off_Platform_Truck_Id__c,
 Latitude, Longitude, City, PostalCode, ERS_Cancellation_Reason__c,
 ERS_Dispatched_Geolocation__Latitude__s, ERS_Dispatched_Geolocation__Longitude__s, Auto_Schedule_Requested__c"""


def pull_garage_day(territory_id: str, service_date: str) -> dict:
    """Read everything one garage-day needs. Raises on an SA count mismatch (section 5.6)."""
    t0 = time.time()
    tid = sanitize_soql(territory_id)
    w = day_window(service_date)
    p = Puller()
    raw = {'territory_id': territory_id, 'service_date': service_date,
           'window': {k: _iso(v) for k, v in w.items()}}

    terr = p.all(f"""SELECT Id, Name, Latitude, Longitude, ParentTerritoryId,
        RSO_Automation_Active__c, ERS_Auto_Schedule__c FROM ServiceTerritory WHERE Id = '{tid}'""")
    if not terr:
        raise ValueError(f'Territory {territory_id} not found')
    raw['territory'] = terr[0]

    # Q0 + Q1: scored SAs (created in the day) plus carryover context, with a completeness check.
    where = (f"ServiceTerritoryId = '{tid}' AND CreatedDate >= {_iso(w['carryover_from'])} "
             f"AND CreatedDate < {_iso(w['day_end'])} AND {ERS_SA_FILTER}")
    expected = p.count(f"SELECT COUNT() FROM ServiceAppointment WHERE {where}")
    sas = p.all(f"SELECT {_SA_FIELDS} FROM ServiceAppointment WHERE {where}")
    if len(sas) != expected:
        sas = p.all(f"SELECT {_SA_FIELDS} FROM ServiceAppointment WHERE {where}")
        if len(sas) != expected:
            raise RuntimeError(f'SA count mismatch {expected} vs {len(sas)}')
    raw['sa_count_expected'] = expected
    raw['sas'] = sas
    sa_ids = [s['Id'] for s in sas]

    # Q2, Q3, Q3b: history, assigned resources, WOLI skill requirements.
    raw['history'] = p.batched("""SELECT ServiceAppointmentId, Field, OldValue, NewValue, CreatedDate,
        CreatedById, CreatedBy.Name, CreatedBy.Profile.Name FROM ServiceAppointmentHistory
        WHERE ServiceAppointmentId IN ({ids})
        AND Field IN ('Status','ERS_Assigned_Resource__c','ServiceTerritory','ERS_PTA__c')""", sa_ids)
    raw['assigned'] = p.batched("""SELECT ServiceAppointmentId, ServiceResourceId, ServiceResource.Name,
        ServiceResource.ERS_Driver_Type__c, CreatedDate, CreatedBy.Name
        FROM AssignedResource WHERE ServiceAppointmentId IN ({ids})""", sa_ids)
    raw['woli_skills'] = p.batched("""SELECT RelatedRecordId, Skill.MasterLabel FROM SkillRequirement
        WHERE RelatedRecordId IN ({ids})""", [s.get('ParentRecordId') for s in sas])

    # Q4: roster effective that day. No IsActive filter (spec S10).
    raw['members'] = p.all(f"""SELECT ServiceResourceId, ServiceResource.Name,
        ServiceResource.ERS_Driver_Type__c, ServiceResource.RelatedRecordId, TerritoryType,
        EffectiveStartDate, EffectiveEndDate, Latitude, Longitude FROM ServiceTerritoryMember
        WHERE ServiceTerritoryId = '{tid}' AND EffectiveStartDate < {_iso(w['day_end'])}
        AND (EffectiveEndDate = null OR EffectiveEndDate > {_iso(w['day_start'])})""")
    drivers = {m['ServiceResourceId'] for m in raw['members']
               if (m.get('ServiceResource') or {}).get('ERS_Driver_Type__c') in GRADED_DRIVER_TYPES}
    drivers |= {a['ServiceResourceId'] for a in raw['assigned']
                if (a.get('ServiceResource') or {}).get('ERS_Driver_Type__c') in GRADED_DRIVER_TYPES}

    if drivers:
        _pull_driver_day(p, raw, drivers, w)
    else:  # Towbook-only day: no FSL drivers, so no logins, GPS or optimizer trail to read
        for k in ('asset_history', 'assets', 'absences', 'skills', 'gps', 'opt_requests'):
            raw[k] = []
    raw['policies'] = _pull_policies(p, raw['opt_requests'])
    raw['sf_calls'] = p.calls
    raw['build_ms'] = int((time.time() - t0) * 1000)
    log.info('report card pull %s %s: %d SAs, %d calls, %d ms',
             territory_id, service_date, len(sas), p.calls, raw['build_ms'])
    return raw


def _pull_driver_day(p: Puller, raw: dict, drivers: set, w: dict):
    hs, he = _iso(w['hist_start']), _iso(w['hist_end'])
    # Q6: truck logins. Org-wide by date, then kept only for this garage's drivers.
    ah = p.all(f"""SELECT AssetId, OldValue, NewValue, CreatedDate FROM AssetHistory
        WHERE Field = 'ERS_Driver__c' AND Asset.RecordType.Name = 'ERS Truck'
        AND CreatedDate >= {hs} AND CreatedDate < {he}""")
    raw['asset_history'] = [a for a in ah if a.get('NewValue') in drivers or a.get('OldValue') in drivers]
    logged = {a['NewValue'] for a in raw['asset_history'] if a.get('NewValue') in drivers}
    logged |= {a['OldValue'] for a in raw['asset_history'] if a.get('OldValue') in drivers}
    assigned = {a['ServiceResourceId'] for a in raw['assigned'] if a['ServiceResourceId'] in drivers}
    people = sorted(logged | assigned)

    # Q6b: current truck capabilities (no history in SF; caveated on screen).
    raw['assets'] = p.batched("""SELECT Id, Name, ERS_Truck_Capabilities__c FROM Asset
        WHERE Id IN ({ids})""", [a['AssetId'] for a in raw['asset_history']])
    # Q7, Q4c
    raw['absences'] = p.batched(f"""SELECT ResourceId, Type, Start, End FROM ResourceAbsence
        WHERE ResourceId IN ({{ids}}) AND Start < {_iso(w['day_end'])}
        AND End > {_iso(w['day_start'])}""", people)
    raw['skills'] = p.batched("""SELECT ServiceResourceId, Skill.MasterLabel, SkillLevel
        FROM ServiceResourceSkill WHERE ServiceResourceId IN ({ids})""", people)
    # Q8: GPS, the slowest step. No COUNT() on this object (spec section 14).
    raw['gps'] = p.batched(f"""SELECT ServiceResourceId, Field, NewValue, CreatedDate
        FROM ServiceResourceHistory WHERE Field IN ('LastKnownLatitude','LastKnownLongitude')
        AND ServiceResourceId IN ({{ids}}) AND CreatedDate >= {hs} AND CreatedDate < {he}""",
        people, size=100, split_on_timeout=True)
    # Q13: SF optimizer trail: territory runs (In-Day) and runs on this garage's drivers (RSO).
    ds, de = _iso(w['day_start']), _iso(w['day_end'])
    terr_runs = p.all(f"""SELECT FSL__Optimization_Request__r.Id,
        FSL__Optimization_Request__r.CreatedDate, FSL__Optimization_Request__r.FSL__Type__c,
        FSL__Optimization_Request__r.FSL__Status__c,
        FSL__Optimization_Request__r.FSL__Scheduling_Policy__c
        FROM FSL__Territory_Optimization_Request__c
        WHERE FSL__ServiceTerritory__c = '{sanitize_soql(raw['territory_id'])}'
        AND CreatedDate >= {ds} AND CreatedDate < {de}""")
    runs = {r['FSL__Optimization_Request__r']['Id']: r['FSL__Optimization_Request__r']
            for r in terr_runs if r.get('FSL__Optimization_Request__r')}
    rso = p.batched(f"""SELECT Id, CreatedDate, FSL__Type__c, FSL__Status__c, FSL__Scheduling_Policy__c
        FROM FSL__Optimization_Request__c WHERE FSL__Service_Resource__c IN ({{ids}})
        AND CreatedDate >= {ds} AND CreatedDate < {de}""", sorted(drivers))
    for r in rso:
        runs.setdefault(r['Id'], r)
    raw['opt_requests'] = [{'id': k, 'ts': r.get('CreatedDate'), 'type': r.get('FSL__Type__c'),
                            'status': r.get('FSL__Status__c'),
                            'policy_id': r.get('FSL__Scheduling_Policy__c')} for k, r in runs.items()]


def _pull_policies(p: Puller, requests: list) -> list:
    """Q11: objectives and work rules of the policies the optimizer actually ran that day."""
    seen = {}
    for r in requests:
        if r.get('policy_id'):
            seen[r['policy_id']] = seen.get(r['policy_id'], 0) + 1
    if not seen:
        return []
    ids = _in(seen)
    goals = p.all(f"""SELECT FSL__Scheduling_Policy__c, FSL__Scheduling_Policy__r.Name,
        FSL__Service_Goal__r.Name, FSL__Weight__c FROM FSL__Scheduling_Policy_Goal__c
        WHERE FSL__Scheduling_Policy__c IN ({ids})""")
    rules = p.all(f"""SELECT FSL__Scheduling_Policy__c, FSL__Work_Rule__r.Name,
        FSL__Work_Rule__r.RecordType.Name FROM FSL__Scheduling_Policy_Work_Rule__c
        WHERE FSL__Scheduling_Policy__c IN ({ids})""")
    out = []
    for pid, n in sorted(seen.items(), key=lambda kv: -kv[1]):
        g = [x for x in goals if x['FSL__Scheduling_Policy__c'] == pid]
        name = next(((x.get('FSL__Scheduling_Policy__r') or {}).get('Name') for x in g), None)
        out.append({
            'id': pid, 'name': name, 'seen_in_runs': n,
            'objectives': sorted(({'goal': (x.get('FSL__Service_Goal__r') or {}).get('Name'),
                                   'weight': x.get('FSL__Weight__c')} for x in g),
                                 key=lambda o: -(o['weight'] or 0)),
            'work_rules': sorted(({'name': (x.get('FSL__Work_Rule__r') or {}).get('Name'),
                                   'type': ((x.get('FSL__Work_Rule__r') or {}).get('RecordType') or {}).get('Name')}
                                  for x in rules if x['FSL__Scheduling_Policy__c'] == pid),
                                 key=lambda r: r['name'] or ''),
        })
    return out
