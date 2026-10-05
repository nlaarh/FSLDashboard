"""ROI baseline: build sampled garage-day snapshots sequentially with Ruby's builder (read-only SOQL).
Also pulls ERS_PTA__c history per garage-day (for original-promise PTA). Skips work already done."""
import json, os, sys, time, logging
sys.path.insert(0, 'backend')
from report_card_build import pull_garage_day
from report_card_snapshot import build_snapshot
from report_card_store import load_snapshot, save_snapshot
from sf_client import sf_query_all

import report_card_build as rcb
_orig_all = rcb._Puller.all
def _all_retry(self, soql):
    for attempt in range(3):
        try:
            return _orig_all(self, soql)
        except Exception as e:  # slow ServiceResourceHistory reads time out at 45 s; cool down, retry
            print(f'RETRY after error ({type(e).__name__}) attempt {attempt+1}', flush=True)
            if attempt == 2:
                raise
            time.sleep(60)
rcb._Puller.all = _all_retry
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
S = os.path.dirname(os.path.abspath(__file__))
PLAN = {
    '0HhPb00000007rKKAQ': ['2026-09-01', '2026-09-09', '2026-09-11', '2026-09-14', '2026-09-17',
                           '2026-09-22', '2026-09-25', '2026-09-28', '2026-09-12', '2026-09-20'],
    '0HhPb00000007qUKAQ': ['2026-09-01', '2026-09-09', '2026-09-11', '2026-09-14', '2026-09-17',
                           '2026-09-22', '2026-09-25', '2026-09-28', '2026-09-12', '2026-09-20'],
}

for tid, days in PLAN.items():
    for d in days:
        snap = load_snapshot(tid, d)
        if snap is None:
            t0 = time.time()
            raw = pull_garage_day(tid, d)
            snap = build_snapshot(raw)
            save_snapshot(tid, d, snap)
            print(f'BUILT {tid} {d} sas={len(snap["sas"])} calls={raw["sf_calls"]} {time.time()-t0:.0f}s', flush=True)
            time.sleep(5)
        else:
            print(f'CACHED {tid} {d}', flush=True)
        hp = f'{S}/pta_{tid}_{d}.json'
        if not os.path.exists(hp):
            ids = [x['id'] for x in snap['sas'] if x['in_day']]
            rows = []
            for i in range(0, len(ids), 150):
                rows += sf_query_all("SELECT ServiceAppointmentId, OldValue, NewValue, CreatedDate, CreatedBy.Name "
                                     "FROM ServiceAppointmentHistory WHERE Field = 'ERS_PTA__c' AND ServiceAppointmentId IN ("
                                     + ",".join(f"'{x}'" for x in ids[i:i + 150]) + ")")
            json.dump(rows, open(hp, 'w'))
            print(f'PTAHIST {tid} {d} rows={len(rows)}', flush=True)
            time.sleep(2)
print('DONE', flush=True)
