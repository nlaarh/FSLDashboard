import sys, json
from collections import Counter
sys.path.insert(0, 'backend')
from report_card_store import load_snapshot
from report_card_verdicts import rules_for, score_snapshot
R = rules_for('r1'); c = Counter(); who = Counter()
for d in ['2026-09-01','2026-09-09','2026-09-11','2026-09-14','2026-09-17','2026-09-22','2026-09-25','2026-09-28','2026-09-12','2026-09-20']:
    s = load_snapshot('0HhPb00000007qUKAQ', d); v = score_snapshot(s, R)
    drv = {x['id']: x for x in s['drivers']}
    for sa in s['sas']:
        if sa['id'] not in v or v[sa['id']]['code'] != 'NOT_GRADED_INSUFFICIENT_DATA': continue
        if sa['channel'] not in ('fleet', 'on_platform_contractor'): c['channel ' + sa['channel'] + ' / ' + str(sa['driver_type'])] += 1; continue
        idx = sa.get('decision_set_idx')
        if idx is None: c['no decision candidate set (final pick not found in history)'] += 1; continue
        me = next((x for x in sa['candidate_sets'][idx]['c'] if x[0] == sa['final_driver_id']), None)
        if not me[8]: c['final driver not on 421 roster that day'] += 1; who[drv.get(sa['final_driver_id'], {}).get('name')] += 1
        elif me[3] is None: c['final driver had no GPS fix <= 30 min'] += 1
        else: c['other'] += 1
print(c); print(who.most_common(8))
