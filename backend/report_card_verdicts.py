"""Scheduler Report Card: per-SA decision verdicts (auditor mode). Pure, no I/O.

Codes, precedence, flags and thresholds: metrics-spec.md section 7 (rules r1, engine e1).
Thresholds live in RULES_R1 (spec 7.6 verbatim plus the blocks architecture.md 7.2 adds); the code
only reads them. One function per code and per flag, fed by sa_features().
"""

import copy
from datetime import timedelta

from utils import parse_dt

ENGINE_VERSION = 'e1'
# "Closer" must beat the pick by more than GPS jitter. Henry's validated script uses 0.01 mi.
TIE_MI = 0.01

RULES_R1 = {
    'rules_version': 'r1', 'engine_version': ENGINE_VERSION,
    'precedence': ['NOT_GRADED_TOWBOOK', 'NOT_GRADED_CANCELED_PRE_ASSIGN', 'INBOUND_CASCADE', 'BOUNCED',
                   'NOT_GRADED_INSUFFICIENT_DATA', 'STACKED', 'FAR_PICK', 'LATE_DESPITE_CAPACITY',
                   'LATE_EXECUTION', 'CAPACITY_SHORT', 'GOOD_NO_ARRIVAL', 'GOOD'],
    'failure_codes': ['BOUNCED', 'STACKED', 'FAR_PICK', 'LATE_DESPITE_CAPACITY'],
    'context_codes': ['INBOUND_CASCADE', 'CAPACITY_SHORT', 'LATE_EXECUTION'],
    'actors': {
        'fsl_engine': ['Platform Integration User', 'FSL System User'],
        'integration': ['Mulesoft Integration', 'Replicant Integration User', 'IT System User'],
        'towbook_sync_profiles': ['Towbook Integrations'],
        'driver_profiles': ['Fleet Driver'],
        'garage_dispatcher_profiles': ['Partner Community User'],
        'human_profiles': ['Membership User'],
    },
    'candidate': {'gps_max_age_min': 30, 'gps_forward_slack_min': 5,
                  'qualified_rule': 'woli_skills_subset_of_sr_skills_plus_truck_caps',
                  'qualified_login_forward_min': 30},
    'params': {
        'STACKED': {'min_open_on_pick': 1, 'min_idle_alternatives': 1, 'closer_by_mi': 0.0},
        'FAR_PICK': {'extra_mi': 5.0},
        'LATE_DESPITE_CAPACITY': {'pta_grace_min': 0, 'sample_step_min': 2},
        'MISSED_REBALANCE': {'min_idle_run_min': 10},
        'LATE_EXECUTION': {'quick_assign_min': 10},
        'OPTIMIZER_CHURN': {'min_pre_dispatch_picks': 3},
        'SLOW_RELEASE': {'release_min': 10},
        'M05': {'wait_min': 10, 'reach_mi': 15},
        'M20': {'closer_by_mi': 0.5},
    },
    'bands': {'distance_mi': [0, 3, 7, 15, 30], 'demand_open_per_driver': [0, 0.5, 1.0, 2.0], 'hour_blocks': 'hourly'},
    'metric_bands': {
        'M02': {'good': [0, 1.5], 'watch': [1.5, 2.0]}, 'M05': {'good': [0, 0.05], 'watch': [0.05, 0.10]},
        'M06': {'good': [0, 2], 'watch': [2, 3]}, 'M08': {'good': [0, 30], 'watch': [30, 60]},
        'M10': {'good': [0, 0.05], 'watch': [0.05, 0.15]}, 'M13': {'good': [0.85, 1], 'watch': [0.75, 0.85]},
        'M16': {'good': [0, 0.05], 'watch': [0.05, 0.10]}, 'M17': {'good': [0.80, 1], 'watch': [0.65, 0.80]},
        'M19': {'good': [0.80, 1], 'watch': [0.65, 0.80]}, 'M20': {'good': [0, 0.05], 'watch': [0.05, 0.15]},
        'M21': {'good': [0.90, 1], 'watch': [0.75, 0.90]},
    },
    'min_support': 20,
    'channel_map': {'Fleet Driver': 'fleet', 'On-Platform Contractor Driver': 'on_platform_contractor',
                    'Off-Platform Contractor Driver': 'towbook'},
    'user_pending': {'pta_target': 0.85, 'human_class_source': 'profile', 'pullback_is_bounce': True},
    # Driver-day health h1 (spec 5A): two lenses, the badge is the worse one, labelled with its owner.
    'driver_health': {
        'version': 'h1',
        'min_on_shift_min': 120,
        'reach_mi': 15, 'gps_max_age_min': 30,
        'workload': {
            'H1_avoidable_stacked_share': {'good': [0, 0.05], 'watch': [0.05, 0.20]},
            'H2_idle_while_waited_share': {'good': [0, 0.10], 'watch': [0.10, 0.25]},
            'H3_max_open': {'bad_at': 4},
        },
        'execution': {
            'H4_late_execution_count': {'watch_at': 1, 'bad_at': 2},
            'H5_nonresponse_pullbacks': {'watch_at': 1, 'bad_at': 2, 'min_wait': 'free_accept_p75',
                                         'min_wait_fallback_min': 15},
            'H6_accept_when_free_median': {'good': 'free_accept_p75', 'watch': 'free_accept_p90', 'min_n': 3,
                                           'fallback_min': {'p75': 15.1, 'p90': 40.1}},
        },
        'context_only': ['pta_split_by_owner', 'queue_wait_median', 'long_on_scene'],
    },
}

GRADED_CHANNELS = ('fleet', 'on_platform_contractor')


# r2 = r1 + metrics-spec 7.7 (graded on the ORIGINAL promise) + B4a (integration picks 0-60 s after
# Auto_Schedule_Requested__c are FSL auto-schedule, a policy run, not a bypass). r1 stays unchanged for audit.
RULES_R2_DELTA = {'rules_version': 'r2', 'pta_basis': 'initial', 'pta_initial_window_sec': 5,
                  'auto_schedule': {'window_sec': [0, 60]}}
DEFAULT_RULES = 'r2'
RULES_VERSIONS = ('r1', 'r2')


class RulesNotAvailable(Exception):
    """The snapshot lacks what this rules version needs (r2 on a pre-rc-build-1.1 snapshot): rebuild, never fall back."""


def rules_for(version: str = DEFAULT_RULES) -> dict:
    if version not in RULES_VERSIONS:
        raise ValueError(f'Unknown rules version {version}')
    rules = copy.deepcopy(RULES_R1)
    if version == 'r2':
        rules.update(copy.deepcopy(RULES_R2_DELTA))
    target = rules['user_pending']['pta_target']
    rules['metric_bands']['M13']['good'][0] = target
    rules['metric_bands']['M13']['watch'][1] = target
    return rules


def actor_class(actor: dict | None, rules: dict, decision: bool = False) -> str | None:
    """Spec B4, evaluated in order. decision=True (an assignment pick): a garage-portal user who is also on
    the roster is acting as a garage dispatcher, not a driver (spec 6.2: Todd Kryszak, 46 finals on 8/31)."""
    if not actor:
        return None
    a, name, prof = rules['actors'], actor.get('actor'), actor.get('actor_profile')
    if decision and prof in a['garage_dispatcher_profiles'] and name not in a['fsl_engine'] + a['integration']:
        return 'GARAGE_DISPATCHER'
    if name in a['fsl_engine']:
        return 'FSL_ENGINE'
    if name in a['integration']:
        return 'INTEGRATION'
    if prof in a['towbook_sync_profiles']:
        return 'TOWBOOK_SYNC'
    if actor.get('actor_is_driver') or prof in a['driver_profiles']:
        return 'DRIVER'
    if prof in a['garage_dispatcher_profiles']:
        return 'GARAGE_DISPATCHER'
    if prof in a['human_profiles']:
        return 'HUMAN'
    return 'OTHER'


def pick_class(pick: dict | None, sa: dict, rules: dict) -> str | None:
    """Actor class of an assignment pick. Under r2 (B4a) an integration pick 0-60 s after the SA's
    Auto_Schedule_Requested__c stamp is FSL_AUTO_SCHEDULE: FSL's own batch scheduler running as that account."""
    cls = actor_class(pick, rules, decision=True)
    auto = rules.get('auto_schedule')
    if cls == 'INTEGRATION' and auto and pick and pick.get('ts') and sa.get('auto_schedule_requested'):
        lag = (parse_dt(pick['ts']) - parse_dt(sa['auto_schedule_requested'])).total_seconds()
        if auto['window_sec'][0] <= lag <= auto['window_sec'][1]:
            return 'FSL_AUTO_SCHEDULE'
    return cls


def _mins(a, b):
    return (b - a).total_seconds() / 60 if a and b else None


def _cand(c):
    keys = ('driver_id', 'lat', 'lon', 'miles', 'qualified', 'on_shift', 'open_jobs', 'gps_age_min', 'member')
    return dict(zip(keys, c))


def pick_qualified_s9t(sa: dict, driver: dict | None, t_asg, rules: dict):
    """S9-T: no truck at the decision -> judge against the first truck logged into within
    qualified_login_forward_min after it and before this SA's En Route. None = unknown (no flag)."""
    if not driver:
        return None
    t_er = parse_dt(sa['milestones']['t_er'])
    limit = t_asg + timedelta(minutes=rules['candidate']['qualified_login_forward_min'])
    later = sorted((parse_dt(x['start']), x) for x in driver.get('trucks') or []
                   if t_asg < parse_dt(x['start']) <= limit and (t_er is None or parse_dt(x['start']) < t_er))
    if not later:
        return None
    return set(sa.get('required_skills') or []) <= set(driver.get('skills') or []) | set(later[0][1]['truck_caps'])


def _in_truck(driver: dict | None, t) -> bool:
    return any(parse_dt(x['start']) <= t < parse_dt(x['end']) for x in (driver or {}).get('trucks') or [])


def sa_features(sa: dict, rules: dict, driver: dict | None = None) -> dict:
    """Spec 7.3 features for one SA, from the snapshot only. `driver` = the final driver's snapshot
    record (trucks, skills), needed for S9-T when the pick came before the truck login."""
    m, dec = sa['milestones'], sa['decision']
    created, t_asg = parse_dt(sa['created']), parse_dt(m['t_asg'])
    t_disp, t_er = parse_dt(m['t_disp']), parse_dt(m['t_er'])
    if rules.get('pta_basis') == 'initial':
        arrival, due, pta = parse_dt(m['arrival']), parse_dt(sa.get('pta_initial_due')), sa.get('pta_initial_min')
    else:
        arrival, due, pta = parse_dt(m['arrival']), parse_dt(sa['pta_due']), sa.get('pta_min')
    pta_ok = arrival <= due + timedelta(minutes=rules['params']['LATE_DESPITE_CAPACITY']['pta_grace_min']) \
        if (arrival and due and pta and 0 < pta < 999) else None
    f = {
        'channel': sa['channel'], 'driver_id': sa['final_driver_id'], 'in_day': sa['in_day'],
        'final_actor': (dec['final'] or {}).get('actor'), 'final_actor_class': pick_class(dec['final'], sa, rules),
        'first_actor_class': pick_class(dec['first'], sa, rules),
        'ar_creator': (dec['ar_creator'] or {}).get('name'),
        'n_picks': dec['n_picks'], 'n_pre_dispatch_picks': dec['n_pre_dispatch_picks'],
        'pullbacks': dec['pullbacks'], 'reassign_after_dispatch': dec['reassign_after_dispatch'],
        'terr_moves_in': sa['territory_moves']['in'],
        'decide_min': _mins(created, parse_dt(m['t_first'])), 'release_min': _mins(t_asg, t_disp),
        'queue_wait_min': _mins(t_asg, t_er), 'assign_after_created_min': _mins(created, t_asg),
        'arrived': arrival is not None, 'response_min': _mins(created, arrival), 'pta_met': pta_ok,
        'graded': False, 'pick_qualified': None, 'assigned_off_shift': None,
    }
    idx = sa.get('decision_set_idx')
    if idx is None or not sa['final_driver_id'] or not t_asg:
        return f
    cs = [_cand(c) for c in sa['candidate_sets'][idx]['c']]
    act = next((c for c in cs if c['driver_id'] == sa['final_driver_id']), None)
    if act is None:
        return f
    if act['qualified'] or _in_truck(driver, t_asg):
        f['pick_qualified'] = bool(act['qualified'])
    else:
        f['pick_qualified'] = pick_qualified_s9t(sa, driver, t_asg, rules)
    f['assigned_off_shift'] = not act['on_shift']
    f['pick_open_jobs'] = act['open_jobs']
    f['pick_miles'] = act['miles']
    others = [c for c in cs if c is not act and c['member'] and c['on_shift'] and c['qualified']
              and c['miles'] is not None]
    # M20: graded whenever the pick has a fresh fix and the call did not arrive from another garage.
    if act['miles'] is not None and sa['lat'] is not None and not f['terr_moves_in']:
        da, oa, by = act['miles'], act['open_jobs'], rules['params']['M20']['closer_by_mi']
        closer = [c for c in others if c['miles'] < da - by]
        f['m20_graded'] = True
        f['idle_q_closer_count'] = sum(1 for c in closer if c['open_jobs'] == 0)
        f['less_loaded_q_closer_count'] = sum(1 for c in closer if c['open_jobs'] < oa)
    # Closest-driver grading (B6 at t_asg): the pick must be a roster member with a fresh fix.
    if not act['member'] or act['miles'] is None:
        return f
    pool = [act] + others
    best = min(pool, key=lambda c: c['miles'])
    free = [c for c in pool if c['open_jobs'] == 0]
    best_free = min(free, key=lambda c: c['miles']) if free else None
    f.update({
        'graded': True, 'n_candidates': len(pool),
        'closest_driver_id': best['driver_id'], 'closest_q_miles': best['miles'], 'picked_closest': best is act,
        'extra_miles': act['miles'] - best['miles'],
        'closest_free_driver_id': best_free['driver_id'] if best_free else None,
        'closest_free_q_miles': best_free['miles'] if best_free else None,
        'picked_closest_free': (best_free is act) if best_free else None,
        'extra_free_miles': (act['miles'] - best_free['miles']) if best_free else None,
        'idle_closer': [[c['driver_id'], round(c['miles'], 2)] for c in free if c is not act
                        and c['miles'] < act['miles'] - rules['params']['STACKED']['closer_by_mi'] - TIE_MI],
    })
    samples = sa.get('free_samples') or {}
    step = samples.get('step_min', 2)
    run_needed = max(1, round(rules['params']['MISSED_REBALANCE']['min_idle_run_min'] / step))
    f['missed_rebalance'] = act['open_jobs'] > 0 and bool(t_er) and \
        _has_run(samples.get('queue') or [], act['miles'], run_needed)
    reach = act['miles'] + rules['params']['FAR_PICK']['extra_mi']
    f['free_before_assign'] = _has_run(samples.get('pre') or [], reach, 1)
    return f


def _has_run(series: list, max_mi: float, need: int) -> bool:
    run = 0
    for sample in series:
        if any(mi <= max_mi for _, mi in sample):
            run += 1
            if run >= need:
                return True
        else:
            run = 0
    return False


# ── Primary codes (spec 7.2): fn(features, params) -> bool ──

def _towbook(f, p): return f['channel'] == 'towbook'
def _pre_assign(f, p): return not f['driver_id']
def _inbound(f, p): return f['terr_moves_in'] >= 1
def _bounced(f, p): return f['pullbacks'] >= 1 or f['reassign_after_dispatch'] >= 1
def _insufficient(f, p): return f['channel'] not in GRADED_CHANNELS or not f['graded']


def _stacked(f, p):
    q = p['STACKED']
    return f['pick_open_jobs'] >= q['min_open_on_pick'] and len(f['idle_closer']) >= q['min_idle_alternatives']


def _far_pick(f, p):
    return f['closest_free_driver_id'] is not None and not f['picked_closest_free'] \
        and f['extra_free_miles'] > p['FAR_PICK']['extra_mi']


def _late_capacity(f, p): return f['pta_met'] is False and (f['missed_rebalance'] or f['free_before_assign'])


def _late_execution(f, p):
    return f['pta_met'] is False and f['pick_open_jobs'] == 0 \
        and f['assign_after_created_min'] <= p['LATE_EXECUTION']['quick_assign_min']


def _capacity_short(f, p): return f['pta_met'] is False
def _no_arrival(f, p): return not f['arrived']
def _good(f, p): return True


CODE_FNS = {
    'NOT_GRADED_TOWBOOK': _towbook, 'NOT_GRADED_CANCELED_PRE_ASSIGN': _pre_assign,
    'INBOUND_CASCADE': _inbound, 'BOUNCED': _bounced, 'NOT_GRADED_INSUFFICIENT_DATA': _insufficient,
    'STACKED': _stacked, 'FAR_PICK': _far_pick, 'LATE_DESPITE_CAPACITY': _late_capacity,
    'LATE_EXECUTION': _late_execution, 'CAPACITY_SHORT': _capacity_short,
    'GOOD_NO_ARRIVAL': _no_arrival, 'GOOD': _good,
}

# ── Flags (spec 7.1) ──
FLAG_FNS = {
    'BYPASSED_OPTIMIZER': lambda f, p: f['final_actor_class'] in ('INTEGRATION', 'HUMAN', 'GARAGE_DISPATCHER'),
    'HUMAN_FINAL': lambda f, p: f['final_actor_class'] == 'HUMAN',
    'OPTIMIZER_CHURN': lambda f, p: f['n_pre_dispatch_picks'] >= p['OPTIMIZER_CHURN']['min_pre_dispatch_picks'],
    'SLOW_RELEASE': lambda f, p: (f['release_min'] or 0) > p['SLOW_RELEASE']['release_min'],
    'MISSED_REBALANCE': lambda f, p: bool(f.get('missed_rebalance')),
    'SKILL_MISMATCH': lambda f, p: f['pick_qualified'] is False,
    'ASSIGNED_OFF_SHIFT': lambda f, p: bool(f['assigned_off_shift']),
}


def verdict(f: dict, rules: dict) -> dict:
    p = rules['params']
    code = next(c for c in rules['precedence'] if CODE_FNS[c](f, p))
    return {
        'code': code,
        'flags': [name for name, fn in FLAG_FNS.items() if fn(f, p)],
        'is_failure': code in rules['failure_codes'],
        'graded': not code.startswith('NOT_GRADED'),
        'rules_version': rules['rules_version'], 'engine_version': ENGINE_VERSION,
        'evidence': {k: (round(v, 2) if isinstance(v, float) else v) for k, v in f.items()},
    }


def supports(snapshot: dict, rules: dict) -> bool:
    """r2 needs pta_initial_* (builder rc-build-1.1+) and auto_schedule_requested (rc-build-1.2+) on every scored SA."""
    need = ([] if rules.get('pta_basis') != 'initial' else ['pta_initial_src']) + (['auto_schedule_requested']
                                                                                     if rules.get('auto_schedule') else [])
    return all(k in sa for k in need for sa in snapshot['sas'] if sa['in_day'] and not sa['is_drop_off'])


def score_snapshot(snapshot: dict, rules: dict) -> dict:
    """{sa_id: verdict} for every scored SA: created in the day, not a Tow Drop-Off (spec B1)."""
    if not supports(snapshot, rules):
        raise RulesNotAvailable(f"rules {rules['rules_version']} need fields this snapshot lacks: rebuild this day "
                                f"(snapshot {snapshot.get('builder_version')})")
    drivers = {d['id']: d for d in snapshot.get('drivers') or []}
    return {sa['id']: verdict(sa_features(sa, rules, drivers.get(sa['final_driver_id'])), rules)
            for sa in snapshot['sas'] if sa['in_day'] and not sa['is_drop_off']}
