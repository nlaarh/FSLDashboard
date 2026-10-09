"""Garage Live "Needs attention": plain-English, explainable rules over one garage's tickets and drivers. No Salesforce, no LLM.

Input is what garage_live.build() assembled (tickets, drivers, the Watchlist alerts for the garage); output is a ranked list of
items. Every threshold lives in THRESHOLDS so the data analyst can tune them in one place. The member-wait colours (yellow up to
30 min late, orange 30-90, red 90+) are the call map's own (watchlist_call_map.lateness), so a pin and its drawer line always agree.

Item: {id, rule, severity (red|orange|yellow|info), text, actions [call_garage|replay|salesforce], sa_id, sa_number, driver_id,
       minutes, target {type: ticket|driver, id}}.  Ranking: severity, then rule order below, then minutes (largest first).
"""

import re

import watchlist_call_map as wcm
from report_card_snapshot import miles

THRESHOLDS = {
    # Member waiting past the promise: colours come from watchlist_call_map.lateness (30 / 90 min)
    'late_min': 1,                    # minutes past the promise before the member counts as late
    # Call not accepted
    'garage_received_min': 10,        # garage still "Received" (has not accepted)
    'rejected_min': 0,                # garage "Rejected" it: shown at once
    'not_accepted_min': 10,           # driver assigned, status still Dispatched / Assigned
    'not_accepted_red_min': 30,       # ... red from here
    # Driver on scene
    'on_scene_light_min': 60,         # light service (battery, lockout, tire, fuel ...): orange from here
    'on_scene_any_min': 120,          # any call: red from here
    # Driver en route
    'en_route_min': 45,               # orange from here
    'en_route_red_min': 90,           # red from here
    'stationary_min': 15,             # en route and the position has not changed this long
    'stationary_radius_mi': 0.1,      # "has not moved" = every position of those minutes within this radius
    # GPS
    'gps_stale_min': 30,              # driver with a job, last position older than this: yellow
    'gps_stale_orange_min': 60,       # ... orange from here
    'gps_map_max_age_min': 240,       # older positions are not drawn on the map
    # Free qualified driver closer than the assigned one
    'suggest_after_min': 5,           # only for calls waiting at least this long
    'max_items': 40,
}

SEVERITY_RANK = {'red': 3, 'orange': 2, 'yellow': 1, 'info': 0}
RULE_ORDER = {'late': 0, 'not_accepted': 1, 'on_scene': 2, 'en_route': 3, 'not_moving': 3, 'gps': 4, 'watchlist': 5, 'closer_driver': 6, 'capacity': 7}

# Watchlist flags: severity of the line, and which of our own rules already says the same thing (then the flag adds nothing).
WATCHLIST_SEVERITY = {
    'Call At Risk of Missing PTA': 'yellow', 'High Priority Call Late': 'orange', 'Call Not Assigned': 'orange',
    'Call Not Assigned - Rejected': 'orange', 'Call Not Assigned - Received': 'orange', 'No Service Appointments on Work Order': 'orange',
    'Call Not Closed': 'red', 'Potential Duplicate': 'yellow',
}
COVERED_BY = {   # flag -> own rules that make it redundant for the same call
    'Call At Risk of Missing PTA': {'late'},
    'Call Not Assigned - Rejected': {'not_accepted'},
    'Call Not Assigned - Received': {'not_accepted'},
    'Call Not Closed': {'on_scene', 'en_route'},
}


def fmt_min(m) -> str:
    """52 -> '52 min', 125 -> '2 h 05 min'."""
    m = int(round(m))
    return f'{m} min' if m < 60 else f'{m // 60} h {m % 60:02d} min'


def _label(t: dict) -> str:
    return f"{t['number']} ({t['work_type']})" if t.get('work_type') else t['number']


def _short(name: str | None) -> str:
    return re.sub(r'\s+\d{2,5}[A-Z]{0,2}$', '', name or '').strip() or 'The driver'


def _item(rule, severity, text, *, actions, sa=None, driver=None, minutes=0, key=''):
    target = {'type': 'driver', 'id': driver['id']} if driver else {'type': 'ticket', 'id': sa['sa_id']} if sa else None
    return {'id': f"{rule}:{(sa or {}).get('sa_id') or (driver or {}).get('id') or ''}{key}", 'rule': rule, 'severity': severity, 'text': text,
            'actions': actions, 'sa_id': (sa or {}).get('sa_id'), 'sa_number': (sa or {}).get('number'),
            'driver_id': (driver or {}).get('id') or (sa or {}).get('driver_id'), 'minutes': int(minutes or 0), 'target': target}


def _call_actions(sa) -> list:
    return ['call_garage', 'replay', 'salesforce'] if sa else ['call_garage']


# ── ticket rules ────────────────────────────────────────────────────────────

def late_items(tickets: list, th: dict) -> list:
    out = []
    for t in tickets:
        late = t.get('late_min')
        if not t.get('waiting') or late is None or late < th['late_min']:
            continue
        sev = t['late']['level']
        who = f" Driver: {_short(t['driver_name'])}." if t.get('driver_name') and not t.get('towbook') else ' Towbook driver.' if t.get('towbook') else ' No driver yet.'
        out.append(_item('late', sev, f"The member has waited {fmt_min(late)} past the promise on {_label(t)}.{who}",
                         actions=_call_actions(t), sa=t, minutes=late))
    return out


def not_accepted_items(tickets: list, th: dict) -> list:
    out = []
    for t in tickets:
        st = (t.get('status') or '').lower()
        if st == 'rejected':
            mins = t.get('status_min') or 0
            if mins >= th['rejected_min']:
                out.append(_item('not_accepted', 'red', f"The garage rejected {_label(t)}{f' {fmt_min(mins)} ago' if mins else ''}. It needs a new home.",
                                 actions=_call_actions(t), sa=t, minutes=mins))
        elif st == 'received':
            mins = t.get('status_min') if t.get('status_min') is not None else t.get('age_min') or 0
            if mins >= th['garage_received_min']:
                out.append(_item('not_accepted', 'orange', f"The garage has not accepted {_label(t)}. It has been Received for {fmt_min(mins)}.",
                                 actions=_call_actions(t), sa=t, minutes=mins))
        elif st in ('dispatched', 'assigned') and t.get('driver_name') and not t.get('towbook'):
            mins = t.get('not_accepted_min') or 0
            if mins >= th['not_accepted_min']:
                sev = 'red' if mins >= th['not_accepted_red_min'] else 'orange'
                out.append(_item('not_accepted', sev, f"{_short(t['driver_name'])} was given {_label(t)} {fmt_min(mins)} ago and has not accepted it.",
                                 actions=_call_actions(t), sa=t, minutes=mins))
    return out


# ── driver rules ────────────────────────────────────────────────────────────

def on_scene_items(drivers: list, th: dict) -> list:
    out = []
    for d in drivers:
        job = d.get('job')
        if d['status'] != 'on_scene' or not job or d.get('status_min') is None:
            continue
        m, light = d['status_min'], job.get('is_light')
        if m >= th['on_scene_any_min']:
            sev = 'red'
        elif light and m >= th['on_scene_light_min']:
            sev = 'orange'
        else:
            continue
        out.append(_item('on_scene', sev, f"{_short(d['name'])} has been on scene {fmt_min(m)} at {job['number']}"
                         f"{' (' + job['work_type'] + ')' if job.get('work_type') else ''}.", actions=['call_garage', 'replay', 'salesforce'],
                         sa={'sa_id': job['sa_id'], 'number': job['number'], 'driver_id': d['id']}, driver=d, minutes=m))
    return out


def en_route_items(drivers: list, th: dict) -> list:
    out = []
    for d in drivers:
        job = d.get('job')
        if d['status'] != 'driving' or not job:
            continue
        sa = {'sa_id': job['sa_id'], 'number': job['number'], 'driver_id': d['id']}
        gps_age = d.get('gps_age_min')
        m = d.get('status_min')
        if m is not None and m >= th['en_route_min']:
            sev = 'red' if m >= th['en_route_red_min'] else 'orange'
            out.append(_item('en_route', sev, f"{_short(d['name'])} has been driving to {job['number']} for {fmt_min(m)}.",
                             actions=_call_actions(sa), sa=sa, driver=d, minutes=m))
        stuck = d.get('stationary_min')
        if gps_age is not None and th['stationary_min'] <= gps_age <= th['gps_stale_min']:
            stuck = max(stuck or 0, gps_age)          # the last position is this old: it has not changed since
        if stuck is not None and stuck >= th['stationary_min'] and not (gps_age is not None and gps_age > th['gps_stale_min']):
            out.append(_item('not_moving', 'orange', f"{_short(d['name'])} has not moved in {fmt_min(stuck)} while driving to {job['number']}.",
                             actions=_call_actions(sa), sa=sa, driver=d, minutes=stuck))
    return out


def gps_items(drivers: list, th: dict) -> list:
    out = []
    for d in drivers:
        if not d.get('job') and d['status'] == 'free':
            continue
        age = d.get('gps_age_min')
        if age is None:
            text, m = f"{_short(d['name'])} has a job but no GPS position at all.", th['gps_stale_orange_min']
        elif age >= th['gps_stale_min']:
            text, m = f"{_short(d['name'])} has a job but the GPS has not updated for {fmt_min(age)}.", age
        else:
            continue
        sev = 'orange' if m >= th['gps_stale_orange_min'] else 'yellow'
        job = d.get('job')
        out.append(_item('gps', sev, text, actions=_call_actions(job), driver=d, minutes=m,
                         sa={'sa_id': job['sa_id'], 'number': job['number'], 'driver_id': d['id']} if job else None))
    return out


# ── Watchlist, closer driver, capacity ──────────────────────────────────────

def watchlist_items(alerts: list, entries: list, tickets: list, covered: dict) -> list:
    """The shared Watchlist's own flags and reasons for this garage, worded as the Watchlist words them.
    covered: sa_id -> rules already raised for it (so 'Call At Risk' is not said twice for a call that is already late)."""
    by_id = {t['sa_id']: t for t in tickets}
    out = []
    for a in alerts:
        flag, sa_id = a.get('flag'), a.get('sa_id')
        t = by_id.get(sa_id)
        if COVERED_BY.get(flag, set()) & covered.get(sa_id, set()):
            continue
        delta = a.get('pta_delta_min')
        extra = f" ({fmt_min(abs(delta))} {'past' if delta > 0 else 'before'} the promise)" if delta is not None and flag in ('Call At Risk of Missing PTA', 'High Priority Call Late') else ''
        dup = f" Same member: {', '.join(a['duplicate_of'])}." if a.get('duplicate_of') else ''
        label = a.get('sa_number') or (f"WO {a['wo_number']}" if a.get('wo_number') else '')
        out.append(_item('watchlist', WATCHLIST_SEVERITY.get(flag, 'yellow'), f"Watchlist: {flag}. {label} {a.get('work_type') or ''}{extra}.{dup}".replace('  ', ' ').replace(' .', '.'),
                         actions=_call_actions(t), sa=t or ({'sa_id': sa_id, 'number': label} if sa_id else None),
                         minutes=abs(delta or 0), key=f":{flag}:{label}"))
    for e in entries:
        t = by_id.get(e.get('sa_id'))
        if not t:
            continue
        out.append(_item('watchlist', 'yellow', f"Watchlist: {t['number']} is followed for {e.get('reason')}.", actions=_call_actions(t), sa=t, key=':entry'))
    return out


def closer_driver_items(tickets: list, drivers: list, skills_for, th: dict) -> list:
    """A free, qualified driver closer than the assigned one while a call is still waiting (the call map's own suggestion and qualified rule).
    skills_for(ticket, driver) -> bool is the qualified test (None = unknown, the rule stays silent)."""
    out = []
    free = [d for d in drivers if d['status'] == 'free' and d.get('lat') is not None and not d.get('stale_position')]
    if not free:
        return out
    by_id = {d['id']: d for d in drivers}
    for t in tickets:
        if not t.get('waiting') or t.get('towbook') or t.get('lat') is None or (t.get('age_min') or 0) < th['suggest_after_min']:
            continue
        peers = []
        for d in free:
            if d['id'] == t.get('driver_id'):
                continue
            q = skills_for(t, d)
            if not q:
                continue
            peers.append({'name': _short(d['name']), 'id': d['id'], 'miles': round(miles(d['lat'], d['lon'], t['lat'], t['lon']), 1), 'held': 0, 'status': 'free'})
        peers.sort(key=lambda p: p['miles'])
        mine = by_id.get(t.get('driver_id'))
        assigned = None
        if t.get('driver_id') and not t.get('towbook'):
            assigned = {'name': _short(t.get('driver_name')), 'held': max(0, (mine or {}).get('held', 1) - 1),
                        'miles': round(miles(mine['lat'], mine['lon'], t['lat'], t['lon']), 1) if mine and mine.get('lat') is not None else None}
        s = wcm.suggestion(t.get('status'), assigned, peers)
        if s:
            best = next(p for p in peers if p['name'] == s['driver'])
            out.append(_item('closer_driver', 'yellow', f"{_label(t)}: {s['text']}", actions=_call_actions(t), sa=t, minutes=0, key=f":{best['id']}"))
    return out


def capacity_item(summary: dict, towbook: bool):
    waiting = summary['waiting_calls']
    if not waiting:
        return None
    s = 's' if waiting != 1 else ''
    if towbook:
        return _item('capacity', 'info', f"{waiting} call{s} waiting. Towbook garage: no driver GPS, so drivers are not shown.", actions=['call_garage'], minutes=waiting)
    free = summary['drivers']['free']
    sev = 'orange' if free == 0 else 'info'
    return _item('capacity', sev, f"{waiting} call{s} waiting, {free} free driver{'s' if free != 1 else ''}.", actions=['call_garage'], minutes=waiting)


def rank(items: list, th: dict) -> list:
    items.sort(key=lambda i: (-SEVERITY_RANK[i['severity']], RULE_ORDER[i['rule']], -i['minutes']))
    return items[:th['max_items']]


def build_attention(tickets: list, drivers: list, alerts: list, entries: list, summary: dict, skills_for, *, towbook: bool = False, th: dict | None = None) -> list:
    th = th or THRESHOLDS
    items = late_items(tickets, th) + not_accepted_items(tickets, th)
    if not towbook:
        items += on_scene_items(drivers, th) + en_route_items(drivers, th) + gps_items(drivers, th)
    covered: dict = {}
    for i in items:
        if i['sa_id']:
            covered.setdefault(i['sa_id'], set()).add(i['rule'])
    items += watchlist_items(alerts, entries, tickets, covered)
    if not towbook:
        items += closer_driver_items(tickets, drivers, skills_for, th)
    cap = capacity_item(summary, towbook)
    if cap:
        items.append(cap)
    return rank(items, th)
