"""Satisfaction garage-level and day-level detail endpoints."""

from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import parse_dt as _parse_dt
from sf_client import sf_query_all, sf_parallel, sanitize_soql  # sf_parallel used in garage detail
from sf_batch import batch_soql_parallel
import cache

from routers.dispatch_shared import _fmt_et, _is_real_garage
from routers.satisfaction_utils import _satisfaction_insights, _build_day_result
from routers.satisfaction_shared import (
    _build_towbook_on_location_map, _process_sa_ata_pta,
    _pct,
)

router = APIRouter()


@router.get("/api/insights/satisfaction/garage/{name}")
def api_satisfaction_garage(name: str, month: str = Query(..., description="YYYY-MM")):
    """Garage-level satisfaction detail: daily satisfaction + ATA correlation + insights."""
    import re, calendar, logging, threading
    from datetime import date as _date, timedelta as _td

    name = sanitize_soql(name)
    if not re.match(r'^\d{4}-\d{2}$', month):
        raise HTTPException(400, "month must be YYYY-MM format")
    year, mon = int(month[:4]), int(month[5:7])
    today = _date.today()
    if _date(year, mon, 1) > today:
        raise HTTPException(400, "Cannot fetch future months")

    is_current = (year == today.year and mon == today.month)
    cache_key = f'satisfaction_garage_{name}_{month}'
    ttl = 14400 if is_current else 31536000  # 4h current, 1yr past

    def _strip(d):
        return {k: v for k, v in d.items() if not k.startswith('_')} if isinstance(d, dict) else d

    cached = cache.get(cache_key)
    if cached:
        return _strip(cached)
    disk = cache.disk_get(cache_key, ttl=ttl)
    if disk:
        cache.put(cache_key, disk, ttl)
        return _strip(disk)

    _log = logging.getLogger('satisfaction')
    gen_lock = f'gen_sat_garage_{name}_{month}'
    if cache.fs_lock_acquire(gen_lock, max_age=600):
        def _bg():
            try:
                result = _generate_satisfaction_garage(name, month)
                cache.put(cache_key, result, ttl)
                cache.disk_put(cache_key, result, ttl)
                _log.info(f"Satisfaction garage detail for {name} {month} generated.")
            except Exception as e:
                _log.warning(f"Satisfaction garage generation failed for {name} {month}: {e}")
            finally:
                cache.fs_lock_release(gen_lock)
        threading.Thread(target=_bg, daemon=True).start()

    return {'garage': name, 'month': month, 'summary': {}, 'daily': [], 'insights': [], 'loading': True}


def _generate_satisfaction_garage(name: str, month: str):
    """Generate garage-level satisfaction detail with ATA correlation."""
    import calendar
    from datetime import date as _date, timedelta as _td

    year, mon = int(month[:4]), int(month[5:7])
    first_day = _date(year, mon, 1)
    last_day_num = calendar.monthrange(year, mon)[1]
    end_day = _date(year, mon, last_day_num) + _td(days=1)

    today = _date.today()
    is_current = (year == today.year and mon == today.month)
    if is_current:
        end_day = today

    start_utc = f"{first_day.isoformat()}T00:00:00Z"
    end_utc = f"{end_day.isoformat()}T00:00:00Z"

    safe_name = name  # already sanitized by sanitize_soql at router level

    # ALL queries in one parallel batch — single roundtrip to SF
    data = sf_parallel(
        sat_rows=lambda: sf_query_all(f"""
            SELECT DAY_ONLY(CreatedDate) d,
                   ERS_Overall_Satisfaction__c sat,
                   ERS_Response_Time_Satisfaction__c rt_sat,
                   ERS_Technician_Satisfaction__c tech_sat,
                   ERSSatisfaction_With_Being_Kept_Informed__c info_sat,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c,
                     ERS_Response_Time_Satisfaction__c, ERS_Technician_Satisfaction__c,
                     ERSSatisfaction_With_Being_Kept_Informed__c
        """),
        sas=lambda: sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime,
                   ERS_Dispatch_Method__c, ERS_PTA__c, WorkType.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritory.Name = '{safe_name}'
              AND ServiceTerritoryId != null
              AND Status = 'Completed'
            LIMIT 15000
        """),
        all_sas=lambda: sf_query_all(f"""
            SELECT Id, AppointmentNumber, CreatedDate, Status,
                   WorkType.Name, ERS_Facility_Decline_Reason__c
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritory.Name = '{safe_name}'
              AND ServiceTerritoryId != null
              AND RecordType.Name = 'ERS Service Appointment'
            LIMIT 15000
        """),
        drv_total=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did,
                   ERS_Driver__r.Name dname,
                   COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c, ERS_Driver__r.Name
        """),
        drv_overall_ts=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c = 'Totally Satisfied'
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c
        """),
        drv_rt_n=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Response_Time_Satisfaction__c != null
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c
        """),
        drv_rt_ts=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Response_Time_Satisfaction__c = 'Totally Satisfied'
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c
        """),
        drv_tech_n=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Technician_Satisfaction__c != null
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c
        """),
        drv_tech_ts=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Technician_Satisfaction__c = 'Totally Satisfied'
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c
        """),
        drv_info_n=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERSSatisfaction_With_Being_Kept_Informed__c != null
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c
        """),
        drv_info_ts=lambda: sf_query_all(f"""
            SELECT ERS_Driver__c did, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERSSatisfaction_With_Being_Kept_Informed__c = 'Totally Satisfied'
              AND ERS_Driver__c != null
              AND ERS_Work_Order__r.ServiceTerritory.Name = '{safe_name}'
            GROUP BY ERS_Driver__c
        """),
    )
    sat_rows = data['sat_rows']
    sas = data['sas']
    towbook_ids = [
        sa.get('Id') for sa in sas
        if sa.get('Id') and (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook'
    ]
    sa_ids = [sa.get('Id') for sa in sas if sa.get('Id')]
    ar_rows = batch_soql_parallel("""
        SELECT ServiceAppointmentId, ServiceResourceId, ServiceResource.Name, CreatedDate
        FROM AssignedResource
        WHERE ServiceAppointmentId IN ('{id_list}')
        ORDER BY ServiceAppointmentId, CreatedDate DESC
    """, sa_ids, chunk_size=200) if sa_ids else []
    assigned_by_sa = {}
    for r in ar_rows:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id or sa_id in assigned_by_sa:
            continue
        assigned_by_sa[sa_id] = {
            'driver_id': r.get('ServiceResourceId'),
            'name': (r.get('ServiceResource') or {}).get('Name'),
        }

    tb_rows = batch_soql_parallel("""
        SELECT ServiceAppointmentId, CreatedDate, NewValue
        FROM ServiceAppointmentHistory
        WHERE Field = 'Status'
          AND ServiceAppointmentId IN ('{id_list}')
    """, towbook_ids, chunk_size=200) if towbook_ids else []
    towbook_on_location = _build_towbook_on_location_map(tb_rows)

    # ── Map ALL SAs (incl. declined) to drivers for drill-down ──
    all_sas = data.get('all_sas', [])
    all_sa_ids = [sa.get('Id') for sa in all_sas if sa.get('Id')]
    all_ar_rows = batch_soql_parallel("""
        SELECT ServiceAppointmentId, ServiceResourceId, ServiceResource.Name, CreatedDate
        FROM AssignedResource
        WHERE ServiceAppointmentId IN ('{id_list}')
        ORDER BY ServiceAppointmentId, CreatedDate DESC
    """, all_sa_ids, chunk_size=200) if all_sa_ids else []
    all_assigned_by_sa = {}
    for r in all_ar_rows:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id or sa_id in all_assigned_by_sa:
            continue
        all_assigned_by_sa[sa_id] = {
            'driver_id': r.get('ServiceResourceId'),
            'name': (r.get('ServiceResource') or {}).get('Name'),
        }

    # Per-driver: completed list, declined list
    driver_sa_details = defaultdict(lambda: {'completed': [], 'declined': []})
    for sa in all_sas:
        wt = ((sa.get('WorkType') or {}).get('Name', '') or '')
        if 'drop' in wt.lower():
            continue
        sa_id = sa.get('Id')
        mapped = all_assigned_by_sa.get(sa_id) or {}
        did = mapped.get('driver_id')
        if not did:
            continue
        status = sa.get('Status') or ''
        decline_reason = sa.get('ERS_Facility_Decline_Reason__c')
        sa_row = {
            'sa_number': sa.get('AppointmentNumber') or '',
            'date': (sa.get('CreatedDate') or '')[:10],
            'work_type': wt,
            'status': status,
        }
        if status == 'Completed':
            driver_sa_details[did]['completed'].append(sa_row)
        if decline_reason:
            sa_row = {**sa_row, 'decline_reason': decline_reason}
            driver_sa_details[did]['declined'].append(sa_row)

    # ── Build daily satisfaction buckets (all 4 dimensions) ──
    _empty_day = lambda: {'total': 0,
                          'ts_overall': 0,
                          'n_rt': 0, 'ts_rt': 0,
                          'n_tech': 0, 'ts_tech': 0,
                          'n_info': 0, 'ts_info': 0}
    day_sat = defaultdict(_empty_day)
    for r in sat_rows:
        d = r.get('d', '')
        sat_val = (r.get('sat') or '').strip().lower()
        cnt = r.get('cnt', 0) or 0
        if not (d and sat_val):
            continue
        ds = day_sat[d]
        ds['total'] += cnt
        if sat_val == 'totally satisfied':
            ds['ts_overall'] += cnt
        rt = (r.get('rt_sat') or '').strip().lower()
        if rt:
            ds['n_rt'] += cnt
            if rt == 'totally satisfied':
                ds['ts_rt'] += cnt
        tech = (r.get('tech_sat') or '').strip().lower()
        if tech:
            ds['n_tech'] += cnt
            if tech == 'totally satisfied':
                ds['ts_tech'] += cnt
        info = (r.get('info_sat') or '').strip().lower()
        if info:
            ds['n_info'] += cnt
            if info == 'totally satisfied':
                ds['ts_info'] += cnt

    # ── ATA/PTA + per-driver stats (shared logic) ──
    day_ata, driver_stats = _process_sa_ata_pta(sas, towbook_on_location, assigned_by_sa=assigned_by_sa)

    # ── Merge and generate output ──
    all_dates = sorted(set(list(day_sat.keys()) + list(day_ata.keys())))
    daily = []
    for d in all_dates:
        s = day_sat.get(d, _empty_day())
        a = day_ata.get(d, {'ata_sum': 0, 'ata_count': 0, 'pta_miss': 0, 'pta_eligible': 0})

        sat_pct = _pct(s['ts_overall'], s['total'])
        rt_pct = _pct(s['ts_rt'], s['n_rt'])
        tech_pct = _pct(s['ts_tech'], s['n_tech'])
        info_pct = _pct(s['ts_info'], s['n_info'])
        avg_ata = round(a['ata_sum'] / a['ata_count']) if a['ata_count'] else None
        pta_miss_pct = _pct(a['pta_miss'], a['pta_eligible'])

        # SA count for that day
        sa_count = sum(1 for sa in sas
                       if (sa.get('CreatedDate') or '')[:10] == d
                       and 'drop' not in ((sa.get('WorkType') or {}).get('Name', '') or '').lower())

        insights = _satisfaction_insights(sat_pct, avg_ata, pta_miss_pct, rt_pct, s['total'])

        daily.append({
            'date': d,
            'totally_satisfied_pct': sat_pct,
            'response_time_pct': rt_pct,
            'technician_pct': tech_pct,
            'kept_informed_pct': info_pct,
            'surveys': s['total'],
            'sa_count': sa_count,
            'avg_ata': avg_ata,
            'pta_miss_pct': pta_miss_pct,
            'insights': insights,
        })

    # Summary
    total_surveys = sum(day_sat[d]['total'] for d in day_sat)
    total_ts = sum(day_sat[d]['ts_overall'] for d in day_sat)
    total_rt = sum(day_sat[d]['n_rt'] for d in day_sat)
    total_rt_ts = sum(day_sat[d]['ts_rt'] for d in day_sat)
    total_tech = sum(day_sat[d]['n_tech'] for d in day_sat)
    total_tech_ts = sum(day_sat[d]['ts_tech'] for d in day_sat)
    total_info = sum(day_sat[d]['n_info'] for d in day_sat)
    total_info_ts = sum(day_sat[d]['ts_info'] for d in day_sat)
    total_ata_sum = sum(day_ata[d]['ata_sum'] for d in day_ata)
    total_ata_count = sum(day_ata[d]['ata_count'] for d in day_ata)
    total_sa = sum(d.get('sa_count', 0) for d in daily)

    summary = {
        'totally_satisfied_pct': _pct(total_ts, total_surveys),
        'response_time_pct': _pct(total_rt_ts, total_rt),
        'technician_pct': _pct(total_tech_ts, total_tech),
        'kept_informed_pct': _pct(total_info_ts, total_info),
        'avg_ata': round(total_ata_sum / total_ata_count) if total_ata_count else None,
        'total_surveys': total_surveys,
        'total_sa': total_sa,
    }

    # Top-level insights for the garage
    garage_insights = _satisfaction_insights(
        summary['totally_satisfied_pct'],
        summary['avg_ata'],
        None,  # PTA miss aggregated would need full recalc
        summary['response_time_pct'],
        total_surveys,
    )

    # ── Per-driver satisfaction (faster split aggregates) ──
    _empty_drv = lambda: {'name': None, 'total': 0,
                          'ts_overall': 0, 'ts_rt': 0, 'n_rt': 0,
                          'ts_tech': 0, 'n_tech': 0, 'ts_info': 0, 'n_info': 0}
    driver_sat = defaultdict(_empty_drv)

    for r in data.get('drv_total', []):
        did = r.get('did')
        if not did:
            continue
        ds = driver_sat[did]
        ds['name'] = r.get('dname') or ds['name']
        ds['total'] = (r.get('cnt', 0) or 0)

    metric_map = [
        ('drv_overall_ts', 'ts_overall'),
        ('drv_rt_n', 'n_rt'),
        ('drv_rt_ts', 'ts_rt'),
        ('drv_tech_n', 'n_tech'),
        ('drv_tech_ts', 'ts_tech'),
        ('drv_info_n', 'n_info'),
        ('drv_info_ts', 'ts_info'),
    ]
    for key, field in metric_map:
        for r in data.get(key, []):
            did = r.get('did')
            if not did:
                continue
            driver_sat[did][field] = (r.get('cnt', 0) or 0)

    _empty_ops = lambda: {'name': None, 'sa_count': 0,
                          'ata_sum': 0.0, 'ata_count': 0,
                          'pta_miss': 0, 'pta_eligible': 0}
    drivers = []
    all_driver_ids = set(driver_sat.keys()) | set(driver_stats.keys()) | set(driver_sa_details.keys())
    for did in all_driver_ids:
        sat = driver_sat.get(did, _empty_drv())
        ops = driver_stats.get(did, _empty_ops())
        sa_det = driver_sa_details.get(did, {'completed': [], 'declined': []})
        dname = sat['name'] or ops['name']
        # Fallback: try to get name from AR mapping
        if not dname:
            for sa_info in all_assigned_by_sa.values():
                if sa_info.get('driver_id') == did and sa_info.get('name'):
                    dname = sa_info['name']
                    break
        if not dname:
            continue
        drivers.append({
            'driver_id': did,
            'name': dname,
            'surveys': sat['total'],
            'totally_satisfied_pct': _pct(sat['ts_overall'], sat['total']),
            'response_time_pct': _pct(sat['ts_rt'], sat['n_rt']),
            'technician_pct': _pct(sat['ts_tech'], sat['n_tech']),
            'kept_informed_pct': _pct(sat['ts_info'], sat['n_info']),
            'completed': len(sa_det['completed']),
            'declined': len(sa_det['declined']),
            'sa_count': ops['sa_count'],
            'avg_ata': round(ops['ata_sum'] / ops['ata_count']) if ops['ata_count'] else None,
            'pta_miss_pct': _pct(ops['pta_miss'], ops['pta_eligible']),
        })
    drivers.sort(key=lambda x: (x['surveys'], x['sa_count']), reverse=True)

    # Build driver ID→name map for the drill-down endpoint
    _driver_sa_map = {}
    for did, sa_det in driver_sa_details.items():
        dname = None
        for d in drivers:
            if d.get('driver_id') == did:
                dname = d['name']
                break
        if dname:
            _driver_sa_map[dname] = sa_det

    return {
        'garage': name,
        'month': month,
        'summary': summary,
        'daily': daily,
        'insights': garage_insights,
        'drivers': drivers,
        '_driver_sa_map': _driver_sa_map,
    }


@router.get("/api/insights/satisfaction/garage/{name}/driver-sas")
def api_garage_driver_sas(name: str, month: str = Query(...), driver: str = Query(...),
                          sa_type: str = Query('completed')):
    """Lazy-fetch SA list for a driver drill-down. Reads from cached data — no SF query."""
    name = sanitize_soql(name)
    cache_key = f'satisfaction_garage_{name}_{month}'
    data = cache.get(cache_key) or cache.disk_get(cache_key, ttl=31536000)
    if not data or not isinstance(data, dict):
        raise HTTPException(404, "Garage data not cached. Load the garage page first.")
    sa_map = data.get('_driver_sa_map', {})
    driver_data = sa_map.get(driver, {'completed': [], 'declined': []})
    return {'driver': driver, 'type': sa_type, 'items': driver_data.get(sa_type, [])}
