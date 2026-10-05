"""Work Order Replay: WHY the driver changed. Pure, no I/O.

Two sources, never mixed up on screen:
  events      what Salesforce recorded between two picks (a rejection with its reason, a Towbook decline, a pull-back, a
              dispatcher release). This is fact.
  candidates  the day snapshot's candidate list at each pick (distance, open jobs, qualified, on shift, GPS age for every driver
              with a fresh fix). The comparison between the new and the previous pick is computed from it. Salesforce itself does
              NOT record why the optimizer chose a driver, so these are computed comparisons, labelled "computed".
Without a built day there is no candidate list: the reason falls back to the events and says so.
"""

import re

from utils import parse_dt

_SUFFIX = re.compile(r'\s+\d{2,3}[A-Z]{0,2}$')
CLOSER_MI = 0.3          # a pick must be this much nearer than the previous one to be called "closer"


def _short(n):
    return _SUFFIX.sub('', n or '').strip()


def pick_trail(snap: dict | None, snap_sa: dict | None) -> list | None:
    """[{ts, picked_id, picked, cands:[{id, name, miles, qualified, on_shift, open_jobs, gps_age_min}]}] per assignment."""
    if not snap or not snap_sa or not snap_sa.get('candidate_sets'):
        return None
    names = {d['id']: _short(d['name']) for d in snap['drivers']}
    picks = [e for e in snap_sa['events'] if e['field'] == 'assigned']
    out = []
    for cs in snap_sa['candidate_sets']:
        pick = picks[cs['event_idx']] if cs['event_idx'] < len(picks) else {}
        pid = pick.get('driver_id')
        cands = [{'id': d, 'name': names.get(d), 'miles': mi, 'qualified': bool(q), 'on_shift': bool(sh), 'open_jobs': oj, 'gps_age_min': age}
                 for d, _la, _lo, mi, q, sh, oj, age, _m in cs['c'] if mi is not None or d == pid]
        out.append({'ts': cs['ts'], 'picked_id': pid, 'picked': names.get(pid) or _short(pick.get('driver')), 'cands': cands})
    return out


def _find(entry, name):
    return next((c for c in (entry or {}).get('cands', []) if c['name'] == name), None)


def _jobs(n):
    return f"{n} open job{'s' if n != 1 else ''}"


def _compare(new, prev, new_before, prev_before):
    """Why the new pick beat the previous one, as (kind, text) pairs from the candidate lists. Order = what to tell first."""
    out = []
    if prev is None or prev['miles'] is None:
        out.append(('gps', 'the previous driver had no fresh GPS position'))
    if prev is not None and not prev['qualified']:
        out.append(('qualified', 'the previous driver was not qualified for this call (skills or truck)'))
    if prev is not None and not prev['on_shift']:
        out.append(('shift', 'the previous driver was off shift'))
    if prev and prev_before and prev['open_jobs'] > prev_before['open_jobs']:
        out.append(('busy', f"the previous driver became busy since the last pick ({_jobs(prev_before['open_jobs'])} to {_jobs(prev['open_jobs'])})"))
    if new and new_before and new['open_jobs'] < new_before['open_jobs']:
        out.append(('free', f"{new['name']} became available since the last pick ({_jobs(new_before['open_jobs'])} to {_jobs(new['open_jobs'])})"))
    if new and prev and prev['open_jobs'] > new['open_jobs']:
        out.append(('jobs', f"{new['name']} has fewer open jobs ({new['open_jobs']} against {prev['open_jobs']})"))
    if new and prev and new['miles'] is not None and prev['miles'] is not None and new['miles'] + CLOSER_MI < prev['miles']:
        out.append(('closer', f"{new['name']} is closer ({new['miles']:.1f} mi against {prev['miles']:.1f} mi)"))
    return out


def why_for_pick(step: dict, prev_pick: dict | None, between: list, trail_now: dict | None, trail_prev: dict | None) -> dict:
    """{headline, lines, source, computed}. between = the steps recorded after the previous pick and before this one."""
    new_name = step['names'].get('driver')
    prev_name = prev_pick['names'].get('driver') if prev_pick else None
    titles = [b['title'] for b in between]
    lines, headline, facts = [], '', 'events'
    if prev_pick is None:
        headline = ('First pick: FSL auto-schedule ran as the call arrived' if step.get('role') == 'FSL auto-schedule'
                    else f"First pick by {step.get('actor') or 'the scheduler'}")
    else:
        rej = next((b for b in between if b['title'].startswith('Driver rejected')), None)
        dec = next((b for b in between if b['title'].startswith('Garage declined')), None)
        if rej:
            headline = f"{prev_name or 'The previous driver'} rejected the call ({rej.get('detail') or 'reason not recorded'}), so it was assigned again"
        elif dec:
            headline = 'The garage declined, so the call moved on to the next garage'
        elif any(t.startswith('Pulled back') for t in titles):
            headline = 'A dispatcher pulled the call back, so it was assigned again'
        elif any('Released' in t or 'Auto-released' in t for t in titles):
            headline = 'Re-assigned after it had been released'
        else:
            headline = f"{step.get('role') or 'The scheduler'} re-ran and chose a different driver"
    if trail_now:
        facts = 'candidates'
        new = _find(trail_now, new_name)
        prev = _find(trail_now, prev_name) if prev_name else None
        if (new_name or '').startswith('SPOT'):
            lines.append('Parked in the SPOT queue for a dispatcher to place: no driver was chosen')
        elif not new:
            lines.append('This driver is not on this garage-day\'s roster, so there is no distance comparison for the pick')
        if new:
            lines.append(f"{new_name}: {new['miles']:.1f} mi away, {_jobs(new['open_jobs'])}" if new['miles'] is not None else f"{new_name}: no fresh GPS, {_jobs(new['open_jobs'])}")
        if prev_name and prev:
            lines.append(f"{prev_name} at that moment: " + (f"{prev['miles']:.1f} mi away, {_jobs(prev['open_jobs'])}" if prev['miles'] is not None else f"no fresh GPS, {_jobs(prev['open_jobs'])}"))
        if prev_pick and not any(b['title'].startswith(('Driver rejected', 'Garage declined')) for b in between):
            because = _compare(new, prev, _find(trail_prev, new_name), _find(trail_prev, prev_name))
            lines.append('Computed from the candidate list: ' + ('; '.join(t for _, t in because[:2]) if because else
                         'no clear difference in distance, open jobs or qualification between the two'))
        qual = [c for c in trail_now['cands'] if c['qualified'] and c['on_shift'] and c['miles'] is not None]
        best = min(qual, key=lambda c: c['miles'], default=None)
        if best and new and best['id'] != new['id']:
            lines.append(f"Closest qualified driver then: {best['name']}, {best['miles']:.1f} mi ({_jobs(best['open_jobs'])})")
        elif best and new and best['id'] == new['id']:
            lines.append('This was the closest qualified driver')
    else:
        lines.append('The reason for the choice is not recorded in Salesforce. Build this garage-day to compare the candidates.')
    return {'headline': headline, 'lines': lines, 'source': facts}


def attach_why(steps: list, trail: list | None):
    """Adds step['why'] to every assignment step, in place."""
    prev, between = None, []
    last_entry = None
    for st in steps:
        if st['title'].startswith('Assigned to') and st['names'].get('driver'):
            ts = parse_dt(st['ts'])
            now = next((t for t in trail or [] if abs((parse_dt(t['ts']) - ts).total_seconds()) <= 2), None)
            st['why'] = why_for_pick(st, prev, between, now, last_entry)
            prev, between, last_entry = st, [], now or last_entry
        elif prev is not None:
            between.append(st)
