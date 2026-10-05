"""Markdown tables for roi-baseline.md from rows.json + summary.json (+ snapshots for drive-time check)."""
import json, os, sys
from collections import Counter, defaultdict
sys.path.insert(0, 'backend')
from utils import parse_dt

S = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(f'{S}/summary.json'))
R = json.load(open(f'{S}/rows.json'))['rows']
CAL = {'0HhPb00000007qGKAQ': (21, 9, 'Sep 2026'), '0HhPb00000007s3KAA': (21, 10, 'Aug 2026'), '0HhPb00000007rKKAQ': (21, 9, 'Sep 2026'), '0HhPb00000007qUKAQ': (21, 9, 'Sep 2026')}
NAME = {'0HhPb00000007qGKAQ': '100 WNY Fleet', '0HhPb00000007s3KAA': '076DO (On-Platform)', '0HhPb00000007rKKAQ': '800 Central Fleet', '0HhPb00000007qUKAQ': '421 Action Towing (On-Platform)'}

# implausible-distance picks: pick > 15 mi but implied speed > 70 mph from the GPS point
sn, implaus = {}, set()
for r in R:
    if r['code'] in ('STACKED', 'FAR_PICK') and (r['extra_free_mi'] or 0) > 0 and r['pick_mi'] > 15:
        k = (r['tid'], r['date'])
        if k not in sn:
            sn[k] = {x['id']: x for x in json.load(open(os.path.expanduser(f"~/.fslapp/report_card/{k[0]}_{k[1]}.snapshot.json")))['sas']}
        m = sn[k][r['id']]['milestones']
        if m['t_ol'] and m['t_er']:
            h = (parse_dt(m['t_ol']) - parse_dt(m['t_er'])).total_seconds() / 3600
            if h <= 0 or r['pick_mi'] / h > 70:
                implaus.add(r['id'])
cons = defaultdict(float)
for r in R:
    if r['code'] in ('STACKED', 'FAR_PICK') and (r['extra_free_mi'] or 0) > 0 and r['id'] not in implaus:
        cons[(r['tid'], r['date'])] += r['extra_free_mi']

lines = []
P = lines.append
for tid, (nwd, nwe, mon) in CAL.items():
    days = [o for o in D['per_day'] if o['tid'] == tid]
    days.sort(key=lambda o: (o['weekend'], o['date']))
    P(f'\n#### {NAME[tid]}: per day ({mon})\n')
    P('| Date | Day | Calls | Extra mi strict (cons.) | Extra mi broad | PTA met | Misses: sched / capacity / bounced / inbound / driver | Late min: sched / capacity / bounced | Member cancels (sched-delay) | Picks/call | Pull-backs | Idle q. driver-h | Call-h waited w/ idle q. driver |')
    P('|---|---|---|---|---|---|---|---|---|---|---|---|---|')
    for o in days:
        m = o['m']
        dow = parse_dt(o['date'] + 'T12:00:00Z').strftime('%a')
        P(f"| {o['date']} | {dow}{' (wkd)' if o['weekend'] else ''} | {m['calls']} | {m['avoid_mi_strict']:.0f} ({cons[(tid, o['date'])]:.0f}) | {m['avoid_mi_broad']:.0f} | "
          f"{m['pta_met']}/{m['pta_n']} ({100*m['pta_met']/m['pta_n']:.0f}%) | {m['miss_scheduler']} / {m['miss_capacity']} / {m['miss_bounced']} / {m['miss_inbound']} / {m['miss_driver']} | "
          f"{m['late_min_scheduler']:.0f} / {m['late_min_capacity']:.0f} / {m['late_min_bounced']:.0f} | {m['mcancel']} ({m['mcancel_sched_any']}) | "
          f"{m['picks']/m['calls']:.2f} | {m['pullbacks']} | {m['idle_driver_h']:.1f} | {m['waited_call_h_idle_q']:.1f} |")
    s = D['summary'][tid]
    wd = [o for o in days if not o['weekend']]
    we = [o for o in days if o['weekend']]
    cw = sum(cons[(tid, o['date'])] for o in wd) / len(wd)
    ce = sum(cons[(tid, o['date'])] for o in we) / len(we)
    P(f'\n#### {NAME[tid]}: daily averages and month extrapolation ({mon}: {nwd} weekdays + {nwe} weekend/holiday days)\n')
    P('| Measure | Weekday avg | Weekend avg | Month total (extrapolated) | Sample total (10 days) |')
    P('|---|---|---|---|---|')
    def row(label, k, fmt='{:.0f}'):
        x = s[k]
        P(f"| {label} | {fmt.format(x['wd_avg'])} | {fmt.format(x['we_avg'])} | {fmt.format(x['month'])} | {fmt.format(x['sample_total'])} |")
    row('Scored calls', 'calls')
    row('Avoidable extra miles, strict (STACKED + FAR_PICK)', 'avoid_mi_strict')
    P(f"| Avoidable extra miles, conservative (strict minus {sum(1 for r in R if r['id'] in implaus and r['tid']==tid)} implausible-speed picks) | {cw:.0f} | {ce:.0f} | {cw*nwd+ce*nwe:.0f} | {sum(cons[(tid,o['date'])] for o in days):.0f} |")
    row('Extra miles, broad upper bound (any closer free qualified driver > 0.5 mi)', 'avoid_mi_broad')
    row('PTA misses, all', 'misses')
    row('PTA misses, scheduler-owned (LATE_DESPITE_CAPACITY / STACKED / FAR_PICK)', 'miss_scheduler')
    row('PTA misses, capacity-owned (CAPACITY_SHORT)', 'miss_capacity')
    row('PTA misses, BOUNCED (pull-back / re-dispatch)', 'miss_bounced')
    row('PTA misses, INBOUND_CASCADE (clock started in another garage)', 'miss_inbound')
    row('PTA misses, driver-owned (LATE_EXECUTION)', 'miss_driver')
    row('Late minutes past PTA, all', 'late_min_all')
    row('Late minutes, scheduler-owned', 'late_min_scheduler')
    row('Late minutes, capacity-owned', 'late_min_capacity')
    row('Late minutes, BOUNCED', 'late_min_bounced')
    row('Late minutes, INBOUND_CASCADE', 'late_min_inbound')
    row('Late minutes, driver-owned', 'late_min_driver')
    row('Member cancels before arrival', 'mcancel')
    row('  of which past the PTA when cancelled', 'mcancel_past_pta')
    row('  of which in scheduler-owned delay (failure code, or idle qualified driver <= 15 mi for >= 10 min)', 'mcancel_sched_any')
    row('  of which BOUNCED', 'mcancel_bounced')
    row('  of which parked unassigned (Spotted >= 10 min, or cancelled while Spotted, or came from a SPOT territory)', 'mcancel_spot')
    row('Assignment picks (all)', 'picks')
    row('Calls with OPTIMIZER_CHURN (>= 3 picks before dispatch)', 'churn_calls')
    row('Pull-backs (Dispatched/Accepted/En Route -> Spotted)', 'pullbacks')
    row('Calls with >= 1 pull-back', 'pullback_calls')
    row('Idle qualified driver-hours while a call within 15 mi waited (H2 numerator)', 'idle_driver_h', '{:.1f}')
    row('Call-hours waited while an idle qualified driver was within 15 mi', 'waited_call_h_idle_q', '{:.1f}')
    row('Driver on-shift hours (roster, truck login)', 'on_shift_h', '{:.0f}')
    row('PTA met (final PTA, r1)', 'pta_met')
    row('PTA graded calls', 'pta_n')
    row('PTA met against the ORIGINAL promise', 'met_orig')
    row('Met only because PTA was re-based', 'rebased_met')
    row('Calls with a later ERS_PTA__c edit', 'pta_edit_calls')

# split shares
P('\n#### Who owns the late minutes (sample totals)\n')
P('| Garage | Scheduler | Capacity (staffing) | Bounced | Inbound cascade | Driver | Total late min | Scheduler share of (scheduler + capacity) |')
P('|---|---|---|---|---|---|---|---|')
for tid in CAL:
    s = D['summary'][tid]
    t = {k: s[f'late_min_{k}']['sample_total'] for k in ('scheduler', 'capacity', 'bounced', 'inbound', 'driver', 'other')}
    tot = sum(t.values())
    f = lambda k: f"{t[k]:.0f} ({100*t[k]/tot:.0f}%)"
    P(f"| {NAME[tid]} | {f('scheduler')} | {f('capacity')} | {f('bounced')} | {f('inbound')} | {f('driver')} | {tot:.0f} | {100*t['scheduler']/(t['scheduler']+t['capacity']):.0f}% |")
P('\n#### Who owns the misses (count, sample totals)\n')
P('| Garage | Scheduler | Capacity | Bounced | Inbound | Driver | Other | All misses | Scheduler share of (scheduler + capacity) |')
P('|---|---|---|---|---|---|---|---|---|')
for tid in CAL:
    s = D['summary'][tid]
    t = {k: s[f'miss_{k}']['sample_total'] for k in ('scheduler', 'capacity', 'bounced', 'inbound', 'driver', 'other')}
    tot = sum(t.values())
    P(f"| {NAME[tid]} | {t['scheduler']:.0f} | {t['capacity']:.0f} | {t['bounced']:.0f} | {t['inbound']:.0f} | {t['driver']:.0f} | {t['other']:.0f} | {tot:.0f} | {100*t['scheduler']/(t['scheduler']+t['capacity']):.0f}% |")

# pull-back actors
P('\n#### Pull-backs by actor (sample totals)\n')
for tid in CAL:
    pa = Counter()
    for o in D['per_day']:
        if o['tid'] == tid:
            pa.update(o['m']['pullback_actors'])
    P(f"- {NAME[tid]}: {dict(pa)}")
open(f'{S}/tables.md', 'w').write('\n'.join(lines))
print('\n'.join(lines))
print('implausible', len(implaus))
