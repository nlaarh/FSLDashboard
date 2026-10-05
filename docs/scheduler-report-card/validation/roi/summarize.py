"""Per-day ROI measures + monthly extrapolation + survey link. Reads rows.json (+ surveys.json if present)."""
import json, math, os, sys
from collections import Counter, defaultdict
from datetime import date

S = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(f'{S}/rows.json'))
rows, days = D['rows'], D['days']
CAL = {'0HhPb00000007qGKAQ': (21, 9), '0HhPb00000007s3KAA': (21, 10), '0HhPb00000007rKKAQ': (21, 9), '0HhPb00000007qUKAQ': (21, 9)}  # (weekdays, weekend+holiday)
SCHED = ('STACKED', 'FAR_PICK', 'LATE_DESPITE_CAPACITY')
BUCKET = {'STACKED': 'scheduler', 'FAR_PICK': 'scheduler', 'LATE_DESPITE_CAPACITY': 'scheduler',
          'CAPACITY_SHORT': 'capacity', 'LATE_EXECUTION': 'driver', 'BOUNCED': 'bounced',
          'INBOUND_CASCADE': 'inbound'}


def measures(rs, day):
    m = {}
    m['calls'] = len(rs)
    strict = [r for r in rs if r['code'] in ('STACKED', 'FAR_PICK') and (r['extra_free_mi'] or 0) > 0]
    m['far_stack_calls'] = len(strict)
    m['avoid_mi_strict'] = sum(r['extra_free_mi'] for r in strict)
    broad = [r for r in rs if r['code'] != 'INBOUND_CASCADE' and r['extra_free_mi'] is not None and r['extra_free_mi'] > 0.5]
    m['avoid_mi_broad'] = sum(r['extra_free_mi'] for r in broad)
    m['broad_calls'] = len(broad)
    miss = [r for r in rs if r['pta_met'] is False]
    m['pta_n'] = sum(1 for r in rs if r['pta_met'] is not None)
    m['pta_met'] = sum(1 for r in rs if r['pta_met'] is True)
    m['misses'] = len(miss)
    for b in ('scheduler', 'capacity', 'driver', 'bounced', 'inbound', 'other'):
        mb = [r for r in miss if BUCKET.get(r['code'], 'other') == b]
        m[f'miss_{b}'] = len(mb)
        m[f'late_min_{b}'] = sum(r['late_min'] for r in mb)
    m['late_min_all'] = sum(r['late_min'] for r in miss)
    c = [r for r in rs if r['cancel'] and r['cancel']['member']]
    m['mcancel'] = len(c)
    m['mcancel_past_pta'] = sum(1 for r in c if r['cancel']['past_pta'])
    m['mcancel_sched_code'] = sum(1 for r in c if r['code'] in SCHED)
    m['mcancel_idle_q10'] = sum(1 for r in c if r['cancel']['idle_q_run_min'] >= 10)
    m['mcancel_bounced'] = sum(1 for r in c if r['code'] == 'BOUNCED')
    m['mcancel_sched_any'] = sum(1 for r in c if r['code'] in SCHED or r['cancel']['idle_q_run_min'] >= 10)
    m['mcancel_spot'] = sum(1 for r in c if r['cancel']['status_before'] == 'Spotted' or r['cancel']['spotted_min'] >= 10
                            or r['cancel']['from_spot_terr'])
    m['cancel_other'] = sum(1 for r in rs if r['cancel'] and not r['cancel']['member'])
    m['picks'] = sum(r['n_picks'] for r in rs)
    m['pre_picks'] = sum(r['n_pre'] for r in rs)
    m['churn_calls'] = sum(1 for r in rs if 'OPTIMIZER_CHURN' in r['flags'])
    m['pullbacks'] = sum(r['pullbacks'] for r in rs)
    m['pullback_calls'] = sum(1 for r in rs if r['pullbacks'])
    m['reassign_after_disp'] = sum(1 for r in rs if r['reassign_after_dispatch'])
    pa = Counter()
    for r in rs:
        pa.update(r['pullback_actors'])
    m['pullback_actors'] = dict(pa)
    m['idle_driver_h'] = day['idle_driver_min'] / 60
    m['waited_call_h_idle_q'] = day['waited_call_min_with_idle_q'] / 60
    m['waited_call_h'] = day['waited_call_min'] / 60
    m['on_shift_h'] = day['on_shift_min'] / 60
    m['met_orig_n'] = sum(1 for r in rs if r['met_orig'] is not None and r['pta_met'] is not None)
    m['met_orig'] = sum(1 for r in rs if r['met_orig'] is True and r['pta_met'] is not None)
    m['rebased_met'] = sum(1 for r in rs if r['pta_met'] is True and r['met_orig'] is False)
    m['pta_edit_calls'] = sum(1 for r in rs if r['pta_later_edits'])
    m['spot_shift_calls'] = sum(1 for r in rs if r['spot_shift_min'] is not None and r['spot_shift_min'] > 1)
    m['codes'] = dict(Counter(r['code'] for r in rs))
    return m


by_day = defaultdict(list)
for r in rows:
    by_day[(r['tid'], r['date'])].append(r)
out = []
for d in days:
    m = measures(by_day[(d['tid'], d['date'])], d)
    wk = date.fromisoformat(d['date']).weekday() >= 5
    out.append({**d, 'weekend': wk, 'm': m})

NUM = [k for k, v in out[0]['m'].items() if isinstance(v, (int, float))]
summary = {}
for tid, (nwd, nwe) in CAL.items():
    od = [o for o in out if o['tid'] == tid]
    wd = [o for o in od if not o['weekend']]
    we = [o for o in od if o['weekend']]
    s = {}
    for k in NUM:
        a = sum(o['m'][k] for o in wd) / len(wd)
        b = sum(o['m'][k] for o in we) / len(we)
        s[k] = {'wd_avg': a, 'we_avg': b, 'month': a * nwd + b * nwe, 'cal_daily': (a * nwd + b * nwe) / (nwd + nwe),
                'sample_total': sum(o['m'][k] for o in od)}
    summary[tid] = s

# survey link
sv = None
if os.path.exists(f'{S}/surveys.json'):
    SV = json.load(open(f'{S}/surveys.json'))
    by_wo = defaultdict(list)
    for x in SV['surveys']:
        by_wo[x['ERS_Work_Order__c']].append(x)
    def ts(r):
        xs = by_wo.get(SV['woli_wo'].get(r['woli']), [])
        xs = [x for x in xs if x.get('ERS_Overall_Satisfaction__c')]
        if not xs:
            return None
        return (xs[-1]['ERS_Overall_Satisfaction__c'] or '').strip().lower() == 'totally satisfied'
    groups = {'scheduler_failure (STACKED/FAR_PICK/LATE_DESPITE_CAPACITY)': lambda r: r['code'] in SCHED,
              'BOUNCED': lambda r: r['code'] == 'BOUNCED',
              'CAPACITY_SHORT': lambda r: r['code'] == 'CAPACITY_SHORT',
              'GOOD': lambda r: r['code'] == 'GOOD',
              'PTA met': lambda r: r['pta_met'] is True, 'PTA missed': lambda r: r['pta_met'] is False}
    sv = {'values': dict(Counter((x.get('ERS_Overall_Satisfaction__c') or 'null') for x in SV['surveys']))}
    for g, fn in groups.items():
        for scope in ('all', '0HhPb00000007qGKAQ', '0HhPb00000007s3KAA', '0HhPb00000007rKKAQ', '0HhPb00000007qUKAQ'):
            rs = [r for r in rows if fn(r) and (scope == 'all' or r['tid'] == scope)]
            t = [ts(r) for r in rs]
            t = [x for x in t if x is not None]
            sv[f'{g}|{scope}'] = {'calls': len(rs), 'surveyed': len(t), 'totally': sum(t)}

    def z(a, b):
        (x1, n1), (x2, n2) = a, b
        if not n1 or not n2:
            return None
        p = (x1 + x2) / (n1 + n2)
        se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else None
        return None if not se else round((x1 / n1 - x2 / n2) / se, 2)
    for scope in ('all',):
        g = lambda k: (sv[f'{k}|{scope}']['totally'], sv[f'{k}|{scope}']['surveyed'])
        sv['z_schedfail_vs_good'] = z(g('scheduler_failure (STACKED/FAR_PICK/LATE_DESPITE_CAPACITY)'), g('GOOD'))
        sv['z_missed_vs_met'] = z(g('PTA missed'), g('PTA met'))
        sv['z_bounced_vs_good'] = z(g('BOUNCED'), g('GOOD'))

json.dump({'per_day': out, 'summary': summary, 'survey': sv}, open(f'{S}/summary.json', 'w'), indent=1, default=str)
for o in out:
    m = o['m']
    print(o['date'], o['name'][:8], 'WE' if o['weekend'] else 'WD', m['calls'], 'mi', round(m['avoid_mi_strict']), round(m['avoid_mi_broad']),
          'miss', m['misses'], f"s{m['miss_scheduler']}/c{m['miss_capacity']}/d{m['miss_driver']}/b{m['miss_bounced']}/i{m['miss_inbound']}/o{m['miss_other']}",
          'late', round(m['late_min_scheduler']), round(m['late_min_capacity']), 'canc', m['mcancel'], m['mcancel_sched_any'],
          'pb', m['pullbacks'], 'idle', round(m['idle_driver_h'], 1), 'pta', m['pta_met'], m['pta_n'], m['met_orig'], m['rebased_met'])
print(json.dumps(sv, indent=1) if sv else 'no surveys yet')
