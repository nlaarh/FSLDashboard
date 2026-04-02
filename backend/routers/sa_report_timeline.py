"""SA Report timeline utilities — split from sa_report.py.

Contains: timeline building, narrative generation, phase computation,
reassignment impact calculation, and SA summary helpers.
These are utility functions imported by sa_report.py (not a router).
"""

import logging
from utils import parse_dt as _parse_dt, to_eastern as _to_eastern
from dispatch_utils import _SF_ID_RE, _STATUS_LABEL, _SYSTEM_USERS


# ── Garage type classification ────────────────────────────────────────────────

def _garage_type(territory: str, dispatch_method: str) -> str:
    """Classify garage as Fleet / On-Platform Contractor / Towbook.

    Rules:
      Towbook           — dispatch_method == 'Towbook'
      Fleet             — territory name contains 'FLEET' (WNY Fleet territories)
      On-Platform Contractor — everything else with Field Services dispatch
    """
    if dispatch_method == 'Towbook':
        return 'Towbook'
    if 'FLEET' in (territory or '').upper():
        return 'Fleet'
    return 'On-Platform Contractor'


# ── SA summary (frontend-ready shape) ────────────────────────────────────────

def _sf_record_url(record_id: str) -> str | None:
    """Build Lightning URL for a Salesforce record."""
    try:
        from sf_client import get_auth
        _, instance = get_auth()
        base = instance.rstrip('/')
        return f"{base}/lightning/r/ServiceAppointment/{record_id}/view"
    except Exception as e:
        logging.getLogger('sa_report').warning('_sf_record_url failed: %s', e)
        return None


def _build_sa_summary(sa: dict) -> dict:
    et       = _to_eastern(sa.get('CreatedDate'))
    start_et = _to_eastern(sa.get('ActualStartTime'))
    end_et   = _to_eastern(sa.get('ActualEndTime'))
    cd, ast  = _parse_dt(sa.get('CreatedDate')), _parse_dt(sa.get('ActualStartTime'))
    response_min = None
    if cd and ast:
        diff = (ast - cd).total_seconds() / 60
        if 0 < diff < 1440:
            response_min = round(diff)
    return {
        'id':             sa['Id'],
        'number':         sa.get('AppointmentNumber'),
        'status':         sa.get('Status'),
        'work_type':      (sa.get('WorkType') or {}).get('Name', '?'),
        'address':        f"{sa.get('Street') or ''} {sa.get('City') or ''} {sa.get('State') or ''}".strip(),
        'zip':            sa.get('PostalCode') or '',
        'lat':            sa.get('Latitude'),
        'lon':            sa.get('Longitude'),
        'territory':      (sa.get('ServiceTerritory') or {}).get('Name', '?'),
        'territory_id':   sa.get('ServiceTerritoryId'),
        'truck_id':       sa.get('Off_Platform_Truck_Id__c') or '',
        'pta':            sa.get('ERS_PTA__c'),
        'created':        et.strftime('%b %d, %I:%M %p') if et else '?',
        '_created_iso':   sa.get('CreatedDate'),  # raw ISO for calculations
        'started':        start_et.strftime('%b %d, %I:%M %p') if start_et else None,
        'completed':      end_et.strftime('%b %d, %I:%M %p') if end_et else None,
        'response_min':   response_min,
        'dispatch_method': sa.get('ERS_Dispatch_Method__c') or '',
        'dispatched_lat': sa.get('ERS_Dispatched_Geolocation__Latitude__s'),
        'dispatched_lon': sa.get('ERS_Dispatched_Geolocation__Longitude__s'),
        'garage_type':    _garage_type(
                              (sa.get('ServiceTerritory') or {}).get('Name', ''),
                              sa.get('ERS_Dispatch_Method__c') or '',
                          ),
        'sf_url':         _sf_record_url(sa['Id']),
    }


# ── Timeline builder (uses pre-fetched rows — avoids a dedicated SF call) ────

def _build_timeline(hist_rows: list, sa_id: str) -> list:
    """Build ordered timeline from SAHistory rows (Field=Status or ERS_Assigned_Resource__c)."""
    tl: list = []
    for r in hist_rows:
        if r.get('ServiceAppointmentId') != sa_id:
            continue
        field   = r.get('Field', '')
        new_val = str(r.get('NewValue') or '').strip()
        if not new_val:
            continue
        ts     = _parse_dt(r.get('CreatedDate'))
        et_ts  = _to_eastern(r.get('CreatedDate'))
        cb     = r.get('CreatedBy') or {}
        by_name    = cb.get('Name', '')
        by_profile = (cb.get('Profile') or {}).get('Name', '')
        is_human   = by_name not in _SYSTEM_USERS and by_profile == 'Membership User'
        time_str   = et_ts.strftime('%b %d, %I:%M %p') if et_ts else '?'

        if field == 'Status':
            tl.append({
                'event': _STATUS_LABEL.get(new_val, new_val),
                'ts': ts, 'time': time_str,
                'by_name': by_name, 'is_human': is_human,
            })
        elif field == 'ERS_Assigned_Resource__c':
            if _SF_ID_RE.match(new_val):
                continue
            prior_drivers = [e for e in tl if 'driver' in e]
            tl.append({
                'event':  'Reassigned' if prior_drivers else 'Assigned',
                'driver': new_val,
                'ts': ts, 'time': time_str,
                'by_name': by_name, 'is_human': is_human,
            })

    sorted_tl = sorted(tl, key=lambda e: e['ts'] or 0)

    # Remove bare Status='Assigned'/'Reassigned' entries that duplicate an
    # ERS_Assigned_Resource__c event at the same timestamp (within 60 sec).
    driver_ts_list = [e['ts'] for e in sorted_tl if 'driver' in e and e['ts'] is not None]
    def _is_dupe_status(e):
        if 'driver' in e or e['event'] not in ('Assigned', 'Reassigned'):
            return False
        if e['ts'] is None:
            return False
        return any(abs((e['ts'] - dt).total_seconds()) <= 60 for dt in driver_ts_list)

    filtered = [e for e in sorted_tl if not _is_dupe_status(e)]

    # Remove duplicate status events within 5 min window (same event + same actor)
    seen = {}  # (event, driver_or_dispatcher) -> last ts
    deduped = []
    for e in filtered:
        actor = e.get('driver') or e.get('by_name') or ''
        key = (e['event'], actor)
        ts = e.get('ts')
        if key in seen and ts and seen[key]:
            if abs((ts - seen[key]).total_seconds()) < 300:
                continue  # skip duplicate
        seen[key] = ts
        deduped.append(e)
    return deduped


# ── Narrative ─────────────────────────────────────────────────────────────────

def _who_phrase(by_name: str) -> str:
    low = (by_name or '').lower()
    if not by_name or low in ('mulesoft integration', 'automated process',
                               'it system user', 'system', 'replicant integration user',
                               'platform integration user'):
        return 'by auto-dispatch'
    return f'by dispatcher {by_name}'


def _build_narrative(sa_summary: dict, timeline: list, assign_steps: list) -> list[str]:
    lines: list[str] = []
    wt        = sa_summary.get('work_type', '?')
    terr      = sa_summary.get('territory', '?')
    num       = sa_summary.get('number', '?')
    gtype     = sa_summary.get('garage_type', '')
    is_towbook = sa_summary.get('dispatch_method') == 'Towbook'

    garage_label = f"{terr} [{gtype}]" if gtype else terr

    created_time = sa_summary.get('created', '?')
    received = next((e for e in timeline if e['event'] in ('Received', 'Spotted')), None)
    lines.append(
        f"{num} — {wt} call created at {created_time}, dispatched to {garage_label}."
    )

    first_assign = next((e for e in timeline if e['event'] == 'Assigned' and 'driver' in e), None)
    if first_assign:
        lines.append(
            f"First assigned to {first_assign['driver']} ({garage_label}) "
            f"at {first_assign['time']} {_who_phrase(first_assign.get('by_name', ''))}."
        )

    for i, step in enumerate(assign_steps):
        drivers  = step.get('step_drivers', [])
        assigned = next((d for d in drivers if d['is_assigned']), None)
        closest  = next((d for d in drivers if d['is_closest']), None)
        driver_name = assigned['name'] if assigned else step.get('driver', '?')
        reason = step.get('reason')

        if i == 0:
            if assigned and not assigned.get('no_gps'):
                dist_str = f"{assigned['distance']} mi" if assigned.get('distance') is not None else '?'
                if assigned.get('is_closest'):
                    lines.append(f"{driver_name} was {dist_str} away — closest eligible driver. \u2713")
                elif closest:
                    lines.append(f"{driver_name} was {dist_str} away. Closer option: {closest['name']} at {closest['distance']} mi.")
                else:
                    lines.append(f"{driver_name} was {dist_str} away.")
            elif assigned and assigned.get('no_gps'):
                lines.append(f"{driver_name} had no GPS at dispatch time.")
        else:
            dist_part = ''
            if assigned and not assigned.get('no_gps') and assigned.get('distance') is not None:
                dist_part = f" ({assigned['distance']} mi away)"
            by_name = step.get('by_name', '')
            if step.get('is_human'):
                by_part = f" by dispatcher {by_name}"
            elif by_name:
                by_part = f" by {by_name}"
            else:
                by_part = ''
            if reason and reason.lower() not in ('reassigned', 'none'):
                reason_part = f" — {reason}"
            elif step.get('is_human'):
                reason_part = f" — manual dispatch override"
            elif 'Platform Integration' in by_name or 'FSL' in by_name:
                reason_part = " — auto-scheduler reassignment"
            elif 'Mulesoft' in by_name:
                reason_part = " — Mulesoft cascade"
            else:
                reason_part = ''
            lines.append(f"Reassigned to {driver_name}{dist_part} at {step['time']}{by_part}.{reason_part}")

    on_loc = next((e for e in timeline if e['event'] == 'On Location'), None)
    if on_loc:
        lines.append(f"Driver arrived on location at {on_loc['time']}.")

    resp = sa_summary.get('response_min')
    if resp:
        pta = sa_summary.get('pta')
        if pta and 0 < pta < 999:
            diff = resp - pta
            verdict = 'on time \u2713' if diff <= 0 else f'{diff} min late \u2717'
            lines.append(f"Response time: {resp} min. PTA {pta} min — {verdict}.")
        else:
            lines.append(f"Response time: {resp} min.")

    if is_towbook and not assign_steps:
        lines.append(f"Dispatched via Towbook ({terr}) — off-platform contractor. Driver location not tracked in FSL.")

    end = next((e for e in timeline if e['event'] in ('Completed', 'Canceled')), None)
    if end:
        lines.append(f"Call {end['event'].lower()} at {end['time']}.")

    return lines


def _build_reassignment_impact(sa_summary: dict, timeline: list, assign_steps: list, hist_rows: list) -> dict | None:
    """Calculate the impact of reassignment on member wait time.

    Returns None if no reassignment happened.
    """
    if len(assign_steps) < 2:
        return None

    created_dt = _parse_dt(sa_summary.get('_created_iso'))
    if not created_dt:
        return None

    # PTA = the promise made to the member at creation.
    pta_at_creation = []
    pta_cutoff_ts = created_dt.timestamp() + 5 if created_dt else 0
    for h in hist_rows:
        if h.get('Field') != 'ERS_PTA__c' or h.get('NewValue') is None:
            continue
        h_ts = _parse_dt(h.get('CreatedDate'))
        if h_ts and h_ts.timestamp() <= pta_cutoff_ts:
            try:
                v = float(h['NewValue'])
                if 0 < v < 999:
                    pta_at_creation.append(v)
            except (TypeError, ValueError):
                pass
    pta = min(pta_at_creation) if pta_at_creation else None
    if pta is None:
        pta = sa_summary.get('pta')
        if pta and (pta <= 0 or pta >= 999):
            pta = None

    first_step = assign_steps[0]
    first_driver = first_step.get('driver', '?')
    first_time = first_step.get('time', '?')

    first_driver_distance = None
    first_step_drivers = first_step.get('step_drivers', [])
    assigned_in_first = next((d for d in first_step_drivers if d.get('is_assigned')), None)
    if assigned_in_first and assigned_in_first.get('distance') is not None:
        first_driver_distance = assigned_in_first['distance']

    first_sched_start = None  # not used directly

    on_loc_event = next((e for e in timeline if e['event'] == 'On Location'), None)
    on_loc_dt = on_loc_event.get('ts') if on_loc_event else None

    last_step = assign_steps[-1]
    final_driver = last_step.get('driver', '?')

    # Calculate time lost: gap between driver REMOVAL and next ASSIGNMENT
    time_lost = 0.0
    saw_assignment = False
    removal_ts = None
    for ev in timeline:
        if ev['event'] in ('Reassigned',) and not saw_assignment:
            saw_assignment = True
            continue
        if saw_assignment and ev['event'] == 'Spotted' and ev.get('ts'):
            removal_ts = ev['ts']
        if removal_ts and ev['event'] == 'Reassigned' and ev.get('ts'):
            gap = (ev['ts'] - removal_ts).total_seconds() / 60
            if gap > 1:
                time_lost += gap
            removal_ts = None

    actual_ata = None
    if on_loc_dt and created_dt:
        actual_ata = round((on_loc_dt - created_dt).total_seconds() / 60)

    first_driver_eta = None
    if first_driver_distance is not None:
        first_driver_eta = round((first_driver_distance / 25) * 60 + 5)
    elif pta:
        first_driver_eta = round(pta)

    pta_delta = round(actual_ata - pta) if actual_ata and pta else None

    return {
        'first_driver': first_driver,
        'first_driver_time': first_time,
        'final_driver': final_driver,
        'on_location_time': on_loc_event.get('time') if on_loc_event else None,
        'pta_minutes': round(pta) if pta else None,
        'actual_ata_minutes': actual_ata,
        'pta_delta_minutes': pta_delta,
        'reassignment_count': len(assign_steps) - 1,
        'time_lost_minutes': round(time_lost) if time_lost > 0 else 0,
    }


def _build_phases(timeline: list, sa_summary: dict) -> list:
    """Build phase durations from the timeline for a visual bar.

    Each phase = {label, minutes, color, start_time, end_time}
    """
    _PHASE_COLORS = {
        'Spotted':      '#f59e0b',  # amber
        'Received':     '#f59e0b',
        'Assigned':     '#3b82f6',  # blue
        'Reassigned':   '#f97316',  # orange
        'Dispatched':   '#6366f1',  # indigo
        'En Route':     '#8b5cf6',  # violet
        'On Location':  '#22c55e',  # green
    }
    _PHASE_LABELS = {
        'Spotted':      'In Queue',
        'Received':     'In Queue',
        'Assigned':     'Assigned',
        'Reassigned':   'Reassigned',
        'Dispatched':   'Dispatched',
        'En Route':     'En Route',
        'On Location':  'On Location',
    }

    phases = []
    sorted_tl = [e for e in timeline if e.get('ts')]
    if not sorted_tl:
        return []

    for i in range(len(sorted_tl) - 1):
        curr = sorted_tl[i]
        nxt = sorted_tl[i + 1]
        event = curr['event']
        seconds = (nxt['ts'] - curr['ts']).total_seconds()
        if seconds < 0:
            continue
        minutes = round(seconds / 60, 1)

        label = _PHASE_LABELS.get(event, event)
        color = _PHASE_COLORS.get(event, '#475569')

        if phases and phases[-1]['label'] == label:
            phases[-1]['minutes'] += minutes
            phases[-1]['end_time'] = nxt.get('time', '?')
        else:
            phases.append({
                'label': label,
                'event': event,
                'minutes': minutes,
                'color': color,
                'start_time': curr.get('time', '?'),
                'end_time': nxt.get('time', '?'),
                'driver': curr.get('driver'),
                'reason': curr.get('reason'),
            })

    return phases
