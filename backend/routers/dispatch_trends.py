"""Dispatch trends endpoints — 30-day rolling and monthly trends."""

from datetime import datetime
from zoneinfo import ZoneInfo
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Query

from utils import parse_dt as _parse_dt
from sf_client import sf_query_all, sf_parallel, sanitize_soql
import cache

from routers.dispatch_shared import _ET, _today_start_utc, _fmt_et, _sa_row

router = APIRouter()


# ── 30-Day Rolling Trends ──────────────────────────────────────────────────

@router.get("/api/insights/trends")
def api_trends():
    """30-day rolling trend data for the Dispatch Insights Trends tab.

    Returns daily KPI series (volume, completion, auto%, SLA%, ATA by channel,
    reassignments, satisfaction) plus top/bottom garages by performance.
    Shows last 30 COMPLETE days (up to yesterday, excludes today's partial data).
    Pre-computed nightly at 12:05 AM ET, persisted to disk.
    """
    import re
    from sf_client import sf_parallel

    _sf_id_pat = re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')

    def _fetch():
        # ── Parallel SOQL queries ────────────────────────────────────
        # Use LAST_N_DAYS:31 + CreatedDate < TODAY to get 30 complete days
        # (excludes today's incomplete data)

        def _get_sas():
            return sf_query_all("""
                SELECT Id, CreatedDate, Status, ActualStartTime, ERS_PTA__c,
                       ERS_Dispatch_Method__c, ServiceTerritoryId,
                       ServiceTerritory.Name, WorkType.Name,
                       CreatedBy.Profile.Name
                FROM ServiceAppointment
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND ServiceTerritoryId != null
                  AND RecordType.Name = 'ERS Service Appointment'
            """)

        def _get_status_history():
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'Status'
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            """)

        def _get_reassignment_history():
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedDate, NewValue
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'ERS_Assigned_Resource__c'
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            """)

        def _get_satisfaction():
            return sf_query_all("""
                SELECT DAY_ONLY(CreatedDate) d,
                       ERS_Overall_Satisfaction__c sat,
                       COUNT(Id) cnt
                FROM Survey_Result__c
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND ERS_Overall_Satisfaction__c != null
                GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c
            """)

        def _get_reassign_with_creator():
            """SAHistory rows for manual dispatch detection.
            Manual = count > 2 (reassigned at least once) AND a human (Membership User) was involved.
            Each assignment creates 2 rows (display name + SF ID), so count > 2 = reassigned.
            """
            return sf_query_all("""
                SELECT ServiceAppointmentId, CreatedBy.Name, CreatedBy.Profile.Name
                FROM ServiceAppointmentHistory
                WHERE CreatedDate = LAST_N_DAYS:31
                  AND CreatedDate < TODAY
                  AND Field = 'ERS_Assigned_Resource__c'
                  AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
            """)

        # All queries in parallel for speed
        data = sf_parallel(sas=_get_sas, status_hist=_get_status_history,
                           reassign_hist=_get_reassignment_history,
                           satisfaction=_get_satisfaction, assign_hist=_get_reassign_with_creator)

        all_sas = data['sas']
        status_hist = data['status_hist']
        reassign_hist = data['reassign_hist']
        satisfaction_rows = data['satisfaction']
        assign_hist_rows = data['assign_hist']

        import logging
        _log = logging.getLogger('trends')
        _log.info(f"Trends fetch: sas={len(all_sas)}, status_hist={len(status_hist)}, reassign={len(reassign_hist)}, satisfaction={len(satisfaction_rows)}, assign_hist={len(assign_hist_rows)}")

        # ── Pre-process history data ─────────────────────────────────

        # 1. Manual dispatch: SA was reassigned (SAHistory count > 2) AND a human was involved.
        #    Each assignment creates 2 SAHistory rows (display name + SF ID).
        #    count > 2 means at least one reassignment happened.
        #    Single assignment (by anyone) = auto.
        _hist_count: dict = {}
        _hist_human: set = set()
        for r in assign_hist_rows:
            sa_id = r.get('ServiceAppointmentId')
            if not sa_id:
                continue
            _hist_count[sa_id] = _hist_count.get(sa_id, 0) + 1
            profile = ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name', '')
            if profile == 'Membership User':
                _hist_human.add(sa_id)
        human_touched_ids = {sa_id for sa_id, cnt in _hist_count.items()
                             if cnt > 2 and sa_id in _hist_human}

        # 2. Towbook on-location times: {sa_id: earliest 'On Location' datetime}
        towbook_on_location = {}
        for r in status_hist:
            sa_id = r.get('ServiceAppointmentId')
            if not sa_id:
                continue
            if r.get('NewValue') == 'On Location':
                ts = _parse_dt(r.get('CreatedDate'))
                if ts:
                    if sa_id not in towbook_on_location or ts < towbook_on_location[sa_id]:
                        towbook_on_location[sa_id] = ts

        # 3. Reassignments per day — only count 2nd+ assignments (actual reassignments)
        #    First assignment is normal dispatch; only subsequent ones are reassignments.
        reassign_by_day = defaultdict(int)
        _sa_assign_seq = defaultdict(int)  # count name-only rows per SA
        for r in reassign_hist:
            new_val = (r.get('NewValue') or '').strip()
            if not new_val or _sf_id_pat.match(new_val):
                continue  # Skip SF ID duplicate rows
            sa_id = r.get('ServiceAppointmentId')
            _sa_assign_seq[sa_id] += 1
            if _sa_assign_seq[sa_id] > 1:  # 2nd+ = actual reassignment
                date_str = (r.get('CreatedDate') or '')[:10]
                if date_str:
                    reassign_by_day[date_str] += 1

        # 4. Satisfaction by day: {date_str: {'total_satisfied': int, 'total_surveys': int}}
        sat_by_day = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0})
        for r in satisfaction_rows:
            date_str = r.get('d', '')
            sat_val = (r.get('sat') or '').strip()
            cnt = r.get('cnt', 0) or 0
            if date_str and sat_val:
                sat_by_day[date_str]['total'] += cnt
                if sat_val.lower() == 'totally satisfied':
                    sat_by_day[date_str]['totally_satisfied'] += cnt

        # ── Build daily buckets from SAs ─────────────────────────────

        daily = defaultdict(lambda: {
            'volume': 0, 'completed': 0,
            'fleet_ata_sum': 0.0, 'fleet_ata_count': 0,
            'towbook_ata_sum': 0.0, 'towbook_ata_count': 0,
            'sla_hits': 0, 'sla_eligible': 0,
            'auto_count': 0, 'total_for_auto': 0,
            'sa_ids': [],
        })

        # SA lookup for Towbook ATA calculation
        sa_lookup = {}
        for sa in all_sas:
            sa_lookup[sa.get('Id')] = sa

        for sa in all_sas:
            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue  # Exclude Tow Drop-Off

            date_str = (sa.get('CreatedDate') or '')[:10]
            if not date_str:
                continue

            d = daily[date_str]
            d['volume'] += 1
            d['sa_ids'].append(sa.get('Id'))

            if sa.get('Status') == 'Completed':
                d['completed'] += 1

            dispatch_method = sa.get('ERS_Dispatch_Method__c') or ''

            # Auto dispatch: all SAs count. Manual = human reassigned after initial assignment.
            # Who created the SA doesn't matter.
            d['total_for_auto'] += 1
            if sa.get('Id') not in human_touched_ids:
                d['auto_count'] += 1

            # Fleet ATA + SLA (only completed Fleet SAs with ActualStartTime)
            if sa.get('Status') == 'Completed' and dispatch_method == 'Field Services':
                created = _parse_dt(sa.get('CreatedDate'))
                actual = _parse_dt(sa.get('ActualStartTime'))
                if created and actual:
                    diff_min = (actual - created).total_seconds() / 60
                    if 0 < diff_min < 480:
                        d['fleet_ata_sum'] += diff_min
                        d['fleet_ata_count'] += 1
                        d['sla_eligible'] += 1
                        if diff_min <= 45:
                            d['sla_hits'] += 1

            # Towbook ATA (use SAHistory 'On Location', NOT ActualStartTime)
            if sa.get('Status') == 'Completed' and dispatch_method == 'Towbook':
                sa_id = sa.get('Id')
                on_loc = towbook_on_location.get(sa_id)
                if on_loc:
                    created = _parse_dt(sa.get('CreatedDate'))
                    if created:
                        diff_min = (on_loc - created).total_seconds() / 60
                        if 0 < diff_min < 480:
                            d['towbook_ata_sum'] += diff_min
                            d['towbook_ata_count'] += 1

        # ── Assemble daily output ────────────────────────────────────

        days_output = []
        for date_str in sorted(daily.keys()):
            d = daily[date_str]
            vol = d['volume']
            comp = d['completed']

            fleet_ata = round(d['fleet_ata_sum'] / d['fleet_ata_count']) if d['fleet_ata_count'] else None
            towbook_ata = round(d['towbook_ata_sum'] / d['towbook_ata_count']) if d['towbook_ata_count'] else None
            sla_pct = round(100 * d['sla_hits'] / d['sla_eligible']) if d['sla_eligible'] else None
            auto_pct = round(100 * d['auto_count'] / d['total_for_auto']) if d['total_for_auto'] else None

            sat_info = sat_by_day.get(date_str, {})
            sat_pct = (
                round(100 * sat_info['totally_satisfied'] / sat_info['total'])
                if sat_info.get('total') else None
            )

            days_output.append({
                'date': date_str,
                'volume': vol,
                'completed': comp,
                'completion_pct': round(100 * comp / vol) if vol else 0,
                'auto_pct': auto_pct,
                'sla_pct': sla_pct,
                'fleet_ata': fleet_ata,
                'towbook_ata': towbook_ata,
                'reassignments': reassign_by_day.get(date_str, 0),
                'closest_pct': None,  # TODO: too expensive for 30-day span; shown on today-only card
                'satisfaction_pct': sat_pct,
            })

        # ── Top / Bottom garages (30-day aggregate) ──────────────────

        garage = defaultdict(lambda: {
            'volume': 0, 'completed': 0,
            'ata_sum': 0.0, 'ata_count': 0,
        })

        for sa in all_sas:
            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue
            tname = (sa.get('ServiceTerritory') or {}).get('Name', '')
            if not tname:
                continue
            # Skip non-garage territories: offices, grid zones, fleet aggregates, spot
            tl = tname.lower()
            if any(x in tl for x in ('office', 'spot', 'fleet', 'region')):
                continue
            # Grid zones = 2-letter + 3-digit pattern (e.g., WR006, CM001)
            if len(tname) <= 6 and tname[:2].isalpha() and tname[2:].isdigit():
                continue
            g = garage[tname]
            g['volume'] += 1
            if sa.get('Status') == 'Completed':
                g['completed'] += 1

            dispatch_method = sa.get('ERS_Dispatch_Method__c') or ''
            if sa.get('Status') == 'Completed':
                # Fleet: use ActualStartTime
                if dispatch_method == 'Field Services':
                    created = _parse_dt(sa.get('CreatedDate'))
                    actual = _parse_dt(sa.get('ActualStartTime'))
                    if created and actual:
                        diff = (actual - created).total_seconds() / 60
                        if 0 < diff < 480:
                            g['ata_sum'] += diff
                            g['ata_count'] += 1
                # Towbook: use SAHistory 'On Location'
                elif dispatch_method == 'Towbook':
                    sa_id = sa.get('Id')
                    on_loc = towbook_on_location.get(sa_id)
                    if on_loc:
                        created = _parse_dt(sa.get('CreatedDate'))
                        if created:
                            diff = (on_loc - created).total_seconds() / 60
                            if 0 < diff < 480:
                                g['ata_sum'] += diff
                                g['ata_count'] += 1

        # Minimum 20 calls to qualify (avoid noise from low-volume garages)
        qualified = []
        for name, g in garage.items():
            if g['volume'] < 20:
                continue
            avg_ata = round(g['ata_sum'] / g['ata_count']) if g['ata_count'] else 999
            comp_pct = round(100 * g['completed'] / g['volume']) if g['volume'] else 0
            qualified.append({
                'name': name,
                'ata': avg_ata,
                'completion_pct': comp_pct,
                'volume': g['volume'],
            })

        # Top 3 = lowest ATA among garages with >85% completion
        top_pool = [g for g in qualified if g['completion_pct'] > 85 and g['ata'] < 999]
        top_pool.sort(key=lambda x: x['ata'])
        top_garages = top_pool[:3]

        # Bottom 3 = highest ATA with actual ATA data (exclude 999 = no data)
        bottom_pool = [g for g in qualified if g['ata'] < 999]
        bottom_pool.sort(key=lambda x: (-x['ata'], x['completion_pct']))
        bottom_garages = bottom_pool[:3]

        return {
            'days': days_output,
            'top_garages': top_garages,
            'bottom_garages': bottom_garages,
        }

    # Serve from cache ONLY — never block a request with heavy SF queries.
    # The nightly thread (12:05 AM ET) or manual trigger populates the cache.
    cached = cache.get('insights_trends_30d')
    if cached:
        return cached
    # Try disk cache (survives restarts)
    disk = cache.disk_get('insights_trends_30d', ttl=86400)
    if disk:
        cache.put('insights_trends_30d', disk, 86400)
        return disk
    # No cache at all — trigger background generation, return empty immediately
    import threading, logging as _lg
    def _bg():
        _log = _lg.getLogger('trends')
        for attempt in range(3):
            try:
                result = _fetch()
                cache.put('insights_trends_30d', result, 86400)
                cache.disk_put('insights_trends_30d', result, 86400)
                _log.info("Trends 30d background generation complete.")
                return
            except Exception as e:
                _log.warning(f"Trends 30d fetch failed (attempt {attempt+1}/3): {e}")
                if attempt < 2:
                    import time as _t; _t.sleep(300)  # retry in 5 min
        _log.error("Trends 30d fetch failed after 3 attempts — cache not updated.")
    threading.Thread(target=_bg, daemon=True).start()
    return {'days': [], 'top_garages': [], 'bottom_garages': [], 'loading': True}


def _fetch_trends_range(start_utc: str, end_utc: str) -> list[dict]:
    """Fetch trend daily rows for a specific UTC datetime range [start_utc, end_utc).
    Skips garage ranking (too expensive for small ranges — caller keeps existing rankings).
    start_utc / end_utc format: '2026-03-17T00:00:00Z'
    """
    import re as _re

    def _get_sas():
        return sf_query_all(f"""
            SELECT Id, CreatedDate, Status, ActualStartTime, ERS_PTA__c,
                   ERS_Dispatch_Method__c, WorkType.Name,
                   CreatedBy.Profile.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ServiceTerritoryId != null
        """)

    def _get_hist():
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'Status'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
        """)

    def _get_reassign():
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedDate, NewValue
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'ERS_Assigned_Resource__c'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
        """)

    def _get_sat():
        return sf_query_all(f"""
            SELECT DAY_ONLY(CreatedDate) d, ERS_Overall_Satisfaction__c sat, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND ERS_Overall_Satisfaction__c != null
            GROUP BY DAY_ONLY(CreatedDate), ERS_Overall_Satisfaction__c
        """)

    def _get_assign_hist():
        """SAHistory rows for manual dispatch detection.
        Manual = count > 2 (reassigned at least once) AND a human (Membership User) was involved.
        Each assignment creates 2 rows (display name + SF ID), so count > 2 = reassigned.
        """
        return sf_query_all(f"""
            SELECT ServiceAppointmentId, CreatedBy.Name, CreatedBy.Profile.Name
            FROM ServiceAppointmentHistory
            WHERE CreatedDate >= {start_utc} AND CreatedDate < {end_utc}
              AND Field = 'ERS_Assigned_Resource__c'
              AND ServiceAppointment.RecordType.Name = 'ERS Service Appointment'
              AND ServiceAppointment.ServiceTerritoryId != null
        """)

    # Run in parallel with small batches to avoid SF rate limiting
    from sf_client import sf_parallel
    data = sf_parallel(sas=_get_sas, hist=_get_hist, reassign=_get_reassign,
                       sat=_get_sat, assign_hist=_get_assign_hist)

    # Manual dispatch: SA was reassigned (SAHistory count > 2) AND a human was involved.
    # Each assignment creates 2 SAHistory rows (display name + SF ID).
    # count > 2 means at least one reassignment happened.
    _hist_count: dict = {}
    _hist_human: set = set()
    for r in data['assign_hist']:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id:
            continue
        _hist_count[sa_id] = _hist_count.get(sa_id, 0) + 1
        profile = ((r.get('CreatedBy') or {}).get('Profile') or {}).get('Name', '')
        if profile == 'Membership User':
            _hist_human.add(sa_id)
    human_touched = {sa_id for sa_id, cnt in _hist_count.items()
                     if cnt > 2 and sa_id in _hist_human}

    # Towbook on-location times
    on_location: dict = {}
    for r in data['hist']:
        sa_id = r.get('ServiceAppointmentId')
        if not sa_id:
            continue
        if r.get('NewValue') == 'On Location':
            ts = _parse_dt(r.get('CreatedDate'))
            if ts and (sa_id not in on_location or ts < on_location[sa_id]):
                on_location[sa_id] = ts

    # Reassignments per day — only 2nd+ assignments (actual reassignments, not first dispatch)
    _sf_id_pat = _re.compile(r'^[a-zA-Z0-9]{15}$|^[a-zA-Z0-9]{18}$')
    reassign_by_day: dict = defaultdict(int)
    _sa_assign_seq: dict = defaultdict(int)
    for r in data['reassign']:
        new_val = (r.get('NewValue') or '').strip()
        if not new_val or _sf_id_pat.match(new_val):
            continue
        sa_id = r.get('ServiceAppointmentId')
        _sa_assign_seq[sa_id] += 1
        if _sa_assign_seq[sa_id] > 1:
            date_str = (r.get('CreatedDate') or '')[:10]
            if date_str:
                reassign_by_day[date_str] += 1

    # Satisfaction by day
    sat_by_day: dict = defaultdict(lambda: {'totally_satisfied': 0, 'total': 0})
    for r in data['sat']:
        date_str = r.get('d', '')
        sat_val = (r.get('sat') or '').strip()
        cnt = r.get('cnt', 0) or 0
        if date_str and sat_val:
            sat_by_day[date_str]['total'] += cnt
            if sat_val.lower() == 'totally satisfied':
                sat_by_day[date_str]['totally_satisfied'] += cnt

    # Build daily buckets
    daily: dict = defaultdict(lambda: {
        'volume': 0, 'completed': 0,
        'fleet_ata_sum': 0.0, 'fleet_ata_count': 0,
        'towbook_ata_sum': 0.0, 'towbook_ata_count': 0,
        'sla_hits': 0, 'sla_eligible': 0,
        'auto_count': 0, 'total_for_auto': 0,
    })

    for sa in data['sas']:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        date_str = (sa.get('CreatedDate') or '')[:10]
        if not date_str:
            continue
        d = daily[date_str]
        d['volume'] += 1
        if sa.get('Status') == 'Completed':
            d['completed'] += 1
        # Auto dispatch: all SAs count. Manual = human reassigned after initial assignment.
        d['total_for_auto'] += 1
        if sa.get('Id') not in human_touched:
            d['auto_count'] += 1
        dm = sa.get('ERS_Dispatch_Method__c') or ''
        if sa.get('Status') == 'Completed':
            if dm == 'Field Services':
                created = _parse_dt(sa.get('CreatedDate'))
                actual = _parse_dt(sa.get('ActualStartTime'))
                if created and actual:
                    diff = (actual - created).total_seconds() / 60
                    if 0 < diff < 480:
                        d['fleet_ata_sum'] += diff
                        d['fleet_ata_count'] += 1
                        d['sla_eligible'] += 1
                        if diff <= 45:
                            d['sla_hits'] += 1
            elif dm == 'Towbook':
                on_loc = on_location.get(sa.get('Id'))
                if on_loc:
                    created = _parse_dt(sa.get('CreatedDate'))
                    if created:
                        diff = (on_loc - created).total_seconds() / 60
                        if 0 < diff < 480:
                            d['towbook_ata_sum'] += diff
                            d['towbook_ata_count'] += 1

    # Assemble output rows
    rows = []
    for date_str in sorted(daily.keys()):
        d = daily[date_str]
        vol = d['volume']
        comp = d['completed']
        sat_info = sat_by_day.get(date_str, {})
        rows.append({
            'date': date_str,
            'volume': vol,
            'completed': comp,
            'completion_pct': round(100 * comp / vol) if vol else 0,
            'auto_pct': round(100 * d['auto_count'] / d['total_for_auto']) if d['total_for_auto'] else None,
            'sla_pct': round(100 * d['sla_hits'] / d['sla_eligible']) if d['sla_eligible'] else None,
            'fleet_ata': round(d['fleet_ata_sum'] / d['fleet_ata_count']) if d['fleet_ata_count'] else None,
            'towbook_ata': round(d['towbook_ata_sum'] / d['towbook_ata_count']) if d['towbook_ata_count'] else None,
            'reassignments': reassign_by_day.get(date_str, 0),
            'closest_pct': None,
            'satisfaction_pct': round(100 * sat_info['totally_satisfied'] / sat_info['total']) if sat_info.get('total') else None,
        })
    return rows


# NOTE: /api/insights/trends/refresh moved to routers/dispatch_trends_monthly.py
# NOTE: Monthly trend endpoints moved to routers/dispatch_trends_monthly.py
# NOTE: /api/territory/{territory_id}/forecast moved to routers/dispatch_trends_monthly.py
