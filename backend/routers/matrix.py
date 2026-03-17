"""Matrix Health endpoint -- priority matrix cascade analysis."""

from fastapi import APIRouter, Query
from datetime import datetime, timedelta
from collections import defaultdict

from sf_client import sf_query_all, sf_parallel
from utils import _ET
import cache

router = APIRouter()


def _matrix_period_bounds(period: str):
    """Return (start_iso, end_iso, cache_ttl) for a period key."""
    now = datetime.now(_ET)
    if period == 'this_week':
        start = now - timedelta(days=now.weekday())
        return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 300
    if period == 'last_month':
        first = now.replace(day=1)
        end = first - timedelta(days=1)
        start = end.replace(day=1)
        return start.strftime('%Y-%m-%dT00:00:00Z'), first.strftime('%Y-%m-%dT00:00:00Z'), 86400
    if period in ('mtd', 'current'):
        start = now.replace(day=1)
        return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 900
    if period == 'ytd':
        start = now.replace(month=5, day=1) if now.month >= 5 else now.replace(year=now.year - 1, month=5, day=1)
        return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 900
    # Custom month: '2026-01', '2026-02', etc.
    if len(period) == 7 and '-' in period:
        y, m = int(period[:4]), int(period[5:])
        start = datetime(y, m, 1, tzinfo=_ET)
        if m == 12:
            end = datetime(y + 1, 1, 1, tzinfo=_ET)
        else:
            end = datetime(y, m + 1, 1, tzinfo=_ET)
        is_past = end <= now
        return start.strftime('%Y-%m-%dT00:00:00Z'), end.strftime('%Y-%m-%dT00:00:00Z'), 86400 if is_past else 900
    # Default: last 4 weeks
    start = now - timedelta(weeks=4)
    return start.strftime('%Y-%m-%dT00:00:00Z'), now.strftime('%Y-%m-%dT%H:%M:%SZ'), 900


def _compute_matrix(start_iso: str, end_iso: str):
    """Run parallel SF aggregate queries and compute cascade/decline metrics.

    Key insight: Most zones start at rank 2 (rank 1 is rare or placeholder like
    'LS - LOCKSMITH REQUIRED'). The 'primary' garage is the first real garage in
    the chain. ERS_Spotting_Number__c on the SA matches the rank of the accepting
    garage in the priority matrix chain.
    """

    # Placeholder garage prefixes to skip when finding primary
    _PLACEHOLDER_PREFIXES = ('LS ', '000-', '000 ')

    # 5 parallel SF queries
    data = sf_parallel(
        volume=lambda: sf_query_all(f"""
            SELECT ServiceTerritory.Name, ServiceTerritoryId,
                   Status, StatusCategory, ERS_Dispatch_Method__c,
                   ERS_Spotting_Number__c, ERS_PTA__c,
                   ERS_Cancellation_Reason__c,
                   WorkType.Name, CreatedDate
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ServiceTerritoryId != null
        """),
        declines=lambda: sf_query_all(f"""
            SELECT ERS_Facility_Decline_Reason__c,
                   ServiceTerritory.Name, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ERS_Facility_Decline_Reason__c != null
              AND ServiceTerritoryId != null
            GROUP BY ERS_Facility_Decline_Reason__c, ServiceTerritory.Name
            ORDER BY COUNT(Id) DESC
            LIMIT 2000
        """),
        cancellations=lambda: sf_query_all(f"""
            SELECT ERS_Cancellation_Reason__c,
                   ServiceTerritory.Name, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ERS_Cancellation_Reason__c != null
              AND ServiceTerritoryId != null
            GROUP BY ERS_Cancellation_Reason__c, ServiceTerritory.Name
            ORDER BY COUNT(Id) DESC
            LIMIT 2000
        """),
        matrix=lambda: sf_query_all("""
            SELECT ERS_Parent_Service_Territory__r.Name,
                   ERS_Parent_Service_Territory__c,
                   ERS_Spotted_Territory__r.Name,
                   ERS_Spotted_Territory__c,
                   ERS_Priority__c
            FROM ERS_Territory_Priority_Matrix__c
            WHERE ERS_Parent_Service_Territory__r.IsActive = true
            ORDER BY ERS_Parent_Service_Territory__r.Name, ERS_Priority__c
        """),
        hour_decline=lambda: sf_query_all(f"""
            SELECT HOUR_IN_DAY(CreatedDate) hr,
                   ServiceTerritory.Name, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {start_iso}
              AND CreatedDate < {end_iso}
              AND ERS_Facility_Decline_Reason__c != null
              AND ServiceTerritoryId != null
            GROUP BY HOUR_IN_DAY(CreatedDate), ServiceTerritory.Name
            ORDER BY COUNT(Id) DESC
            LIMIT 2000
        """),
        surveys=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name,
                   ERS_Overall_Satisfaction__c, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {start_iso}
              AND ERS_Work_Order__r.CreatedDate < {end_iso}
              AND ERS_Overall_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Overall_Satisfaction__c
            ORDER BY ERS_Work_Order__r.ServiceTerritory.Name
            LIMIT 2000
        """),
    )

    sa_list = data['volume']
    decline_rows = data['declines']
    cancel_rows = data['cancellations']
    matrix_rows = data['matrix']
    hour_decline_rows = data['hour_decline']
    survey_rows = data['surveys']

    # ── Build priority matrix lookup FIRST (needed for primary detection) ──
    zone_chains = defaultdict(list)
    for row in matrix_rows:
        pzone = (row.get('ERS_Parent_Service_Territory__r') or {}).get('Name', '')
        gname = (row.get('ERS_Spotted_Territory__r') or {}).get('Name', '')
        rank = row.get('ERS_Priority__c', 99)
        pid = row.get('ERS_Parent_Service_Territory__c', '')
        gid = row.get('ERS_Spotted_Territory__c', '')
        if pzone and gname:
            zone_chains[pzone].append({
                'rank': rank, 'garage_name': gname, 'garage_id': gid, 'zone_id': pid,
            })
    for chain in zone_chains.values():
        chain.sort(key=lambda x: x['rank'])

    def _is_placeholder(name):
        return any(name.startswith(p) for p in _PLACEHOLDER_PREFIXES)

    # For each zone, find the primary garage (first non-placeholder) and its rank
    zone_primary = {}  # zone -> {'garage': name, 'rank': float}
    for zname, chain in zone_chains.items():
        for entry in chain:
            if not _is_placeholder(entry['garage_name']):
                zone_primary[zname] = {'garage': entry['garage_name'], 'rank': entry['rank']}
                break

    # Build garage->primary_rank mapping (the min rank at which this garage is primary)
    garage_primary_ranks = defaultdict(set)
    for zname, info in zone_primary.items():
        garage_primary_ranks[info['garage']].add(info['rank'])

    # ── Build garage metrics ──
    garage_stats = defaultdict(lambda: {
        'total': 0, 'completed': 0, 'declined': 0,
        'primary_offered': 0, 'primary_accepted': 0,
        'cascaded_in': 0, 'cnw': 0, 'cnw_cascaded': 0,
        'dispatch_method': None, 'pta_sum': 0, 'pta_count': 0,
        'primary_pta_sum': 0, 'primary_pta_count': 0,
        'cascade_pta_sum': 0, 'cascade_pta_count': 0,
        'spot_dist': defaultdict(int),
    })

    for sa in sa_list:
        tname = (sa.get('ServiceTerritory') or {}).get('Name', '')
        if not tname or _is_placeholder(tname):
            continue
        # Exclude Tow Drop-Off (paired SAs, not real calls)
        wt_name = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt_name.lower():
            continue
        g = garage_stats[tname]
        g['total'] += 1
        status_cat = sa.get('StatusCategory', '')
        if status_cat == 'Completed':
            g['completed'] += 1

        dm = sa.get('ERS_Dispatch_Method__c', '')
        if dm and not g['dispatch_method']:
            g['dispatch_method'] = dm

        pta = sa.get('ERS_PTA__c')
        if pta and isinstance(pta, (int, float)) and pta > 0:
            g['pta_sum'] += pta
            g['pta_count'] += 1

        # Spotting number = rank of accepting garage in the zone chain
        spot = sa.get('ERS_Spotting_Number__c')
        primary_ranks = garage_primary_ranks.get(tname, set())

        if spot and isinstance(spot, (int, float)) and spot > 0:
            g['spot_dist'][int(spot)] += 1

            if primary_ranks and spot in primary_ranks:
                # This garage was the primary for the zone and accepted
                g['primary_accepted'] += 1
                if pta and isinstance(pta, (int, float)) and pta > 0:
                    g['primary_pta_sum'] += pta
                    g['primary_pta_count'] += 1
            elif primary_ranks and spot > min(primary_ranks):
                # This garage received a cascaded call (accepted at a rank higher
                # than its primary position -> it was a backup receiver)
                g['cascaded_in'] += 1
                if pta and isinstance(pta, (int, float)) and pta > 0:
                    g['cascade_pta_sum'] += pta
                    g['cascade_pta_count'] += 1
            elif not primary_ranks:
                # Garage isn't primary anywhere -- all its calls are cascade receives
                g['cascaded_in'] += 1
                if pta and isinstance(pta, (int, float)) and pta > 0:
                    g['cascade_pta_sum'] += pta
                    g['cascade_pta_count'] += 1

        # "Could Not Wait" tracking
        cancel_reason = sa.get('ERS_Cancellation_Reason__c', '') or ''
        if 'could not wait' in cancel_reason.lower():
            g['cnw'] += 1

    # Helper to extract territory name from aggregate row
    def _agg_tname(row):
        st = row.get('ServiceTerritory')
        if st and isinstance(st, dict):
            return st.get('Name', '')
        return row.get('Name') or ''

    # Decline reasons by garage
    decline_by_garage = defaultdict(list)
    for row in decline_rows:
        tname = _agg_tname(row)
        reason = row.get('ERS_Facility_Decline_Reason__c') or ''
        cnt = row.get('cnt') or row.get('expr0') or 0
        if tname and reason:
            decline_by_garage[tname].append({'reason': reason, 'count': cnt})
            garage_stats[tname]['declined'] += cnt

    # Estimate primary_offered = primary_accepted + declines (when garage is primary)
    for gname, gs in garage_stats.items():
        gs['primary_offered'] = gs['primary_accepted'] + gs['declined']

    # Cancellation reasons by garage
    cancel_by_garage = defaultdict(list)
    for row in cancel_rows:
        tname = _agg_tname(row)
        reason = row.get('ERS_Cancellation_Reason__c') or ''
        cnt = row.get('cnt') or row.get('expr0') or 0
        if tname and reason:
            cancel_by_garage[tname].append({'reason': reason, 'count': cnt})

    # Hourly decline pattern
    hour_decline_by_garage = defaultdict(lambda: defaultdict(int))
    for row in hour_decline_rows:
        tname = _agg_tname(row)
        hr = row.get('hr') or row.get('expr0') or 0
        cnt = row.get('cnt') or row.get('expr1') or 0
        if tname:
            hour_decline_by_garage[tname][int(hr)] += cnt

    # Survey satisfaction by garage
    # KPI = "% Totally Satisfied" (accreditation metric)
    survey_by_garage = defaultdict(lambda: {'total': 0, 'satisfied': 0})
    for row in survey_rows:
        st = row.get('ServiceTerritory')
        if not st:
            # Aggregate query returns nested under WorkOrder relationship
            st = (row.get('ERS_Work_Order__r') or {}).get('ServiceTerritory')
        tname = (st or {}).get('Name', '') if isinstance(st, dict) else ''
        if not tname:
            tname = row.get('Name', '')
        sat = (row.get('ERS_Overall_Satisfaction__c') or '').lower().strip()
        cnt = row.get('cnt') or row.get('expr0') or 0
        if tname:
            survey_by_garage[tname]['total'] += cnt
            if sat == 'totally satisfied':
                survey_by_garage[tname]['satisfied'] += cnt

    # ── Build zone health ──
    # NOTE: We can't map individual SAs to zones (no zone field on SA).
    # Zone metrics use the primary garage's performance as a proxy.
    zone_health = []
    for zname, chain in zone_chains.items():
        primary_info = zone_primary.get(zname)
        if not primary_info:
            continue
        p_name = primary_info['garage']
        p_rank = primary_info['rank']
        ps = garage_stats.get(p_name, {})

        # Primary accept rate = primary_accepted / primary_offered
        p_offered = ps.get('primary_offered', 0)
        p_accepted = ps.get('primary_accepted', 0)
        accept_pct = round(100 * p_accepted / p_offered, 1) if p_offered > 0 else None

        # Use primary garage's volume as zone proxy (not sum of all chain garages)
        p_total = ps.get('total', 0)
        p_declined = ps.get('declined', 0)
        p_cnw = ps.get('cnw', 0)

        # Cascade estimate: primary's decline count represents calls that cascaded
        cascade_pct = round(100 * p_declined / p_total, 1) if p_total > 0 else 0

        # Cascade delay estimate: ~8 min per cascade step (industry empirical)
        # Each decline -> redispatch cycle takes roughly 8 min
        _CASCADE_STEP_DELAY = 8

        # Build chain detail (skip placeholders)
        chain_detail = []
        for e in chain:
            if _is_placeholder(e['garage_name']):
                continue
            egs = garage_stats.get(e['garage_name'], {})
            e_offered = egs.get('primary_offered', 0)
            e_accepted = egs.get('primary_accepted', 0)
            chain_detail.append({
                'rank': e['rank'],
                'garage': e['garage_name'],
                'accept_pct': round(100 * e_accepted / e_offered, 1) if e_offered > 0 else None,
                'total': egs.get('total', 0),
                'declined': egs.get('declined', 0),
            })
            if len(chain_detail) >= 5:
                break

        zone_health.append({
            'zone': zname,
            'zone_id': chain[0].get('zone_id', ''),
            'primary_garage': p_name,
            'primary_rank': int(p_rank),
            'primary_accept_pct': accept_pct,
            'primary_volume': p_total,
            'primary_declined': p_declined,
            'cascade_pct': cascade_pct,
            'cascade_delay_min': _CASCADE_STEP_DELAY,
            'cnw': p_cnw,
            'satisfaction_pct': round(100 * survey_by_garage[p_name]['satisfied'] / survey_by_garage[p_name]['total'], 1) if survey_by_garage[p_name]['total'] >= 5 else None,
            'chain': chain_detail,
        })

    zone_health.sort(key=lambda z: z.get('cascade_pct', 0), reverse=True)

    # ── Build garage list ──
    garages_out = []
    for gname, gs in sorted(garage_stats.items(), key=lambda x: -x[1]['total']):
        if gs['total'] < 5 or _is_placeholder(gname):
            continue
        offered = gs['primary_offered']
        accepted = gs['primary_accepted']
        accept_pct = round(100 * accepted / offered, 1) if offered > 0 else None
        completion_pct = round(100 * gs['completed'] / gs['total'], 1) if gs['total'] > 0 else 0
        avg_pta = round(gs['pta_sum'] / gs['pta_count']) if gs['pta_count'] else None
        cnw_pct = round(100 * gs['cnw'] / gs['total'], 1) if gs['total'] > 0 else 0
        decline_pct = round(100 * gs['declined'] / gs['total'], 1) if gs['total'] > 0 else 0

        top_declines = sorted(decline_by_garage.get(gname, []), key=lambda x: -x['count'])[:3]
        top_cancels = sorted(cancel_by_garage.get(gname, []), key=lambda x: -x['count'])[:3]

        hr_map = hour_decline_by_garage.get(gname, {})
        hour_declines = [hr_map.get(h, 0) for h in range(24)]

        garages_out.append({
            'name': gname,
            'dispatch_method': gs['dispatch_method'],
            'total': gs['total'],
            'completed': gs['completed'],
            'completion_pct': completion_pct,
            'declined': gs['declined'],
            'decline_pct': decline_pct,
            'accept_pct': accept_pct,
            'avg_pta': avg_pta,
            'cnw': gs['cnw'],
            'cnw_pct': cnw_pct,
            'cascaded_in': gs['cascaded_in'],
            'top_decline_reasons': top_declines,
            'top_cancel_reasons': top_cancels,
            'hourly_declines': hour_declines,
            'satisfaction_pct': round(100 * survey_by_garage[gname]['satisfied'] / survey_by_garage[gname]['total'], 1) if survey_by_garage[gname]['total'] >= 5 else None,
            'survey_count': survey_by_garage[gname]['total'],
        })

    # ── Build recommendations ──
    recommendations = []
    for zh in zone_health:
        if not zh['primary_accept_pct'] or zh['primary_accept_pct'] >= 75:
            continue
        if zh['primary_volume'] < 20:
            continue
        # Find a better alternative in the chain
        best_alt = None
        for ce in zh['chain'][1:]:
            if ce['accept_pct'] and ce['accept_pct'] > zh['primary_accept_pct'] + 10 and ce['total'] >= 10:
                best_alt = ce
                break
        if not best_alt:
            continue

        calls_per_month = zh['primary_volume']
        current_decline_rate = 100 - zh['primary_accept_pct']
        projected_decline_rate = max(100 - best_alt['accept_pct'], 5)
        cascade_reduction = round(calls_per_month * (current_decline_rate - projected_decline_rate) / 100)
        delay_per_cascade = zh['cascade_delay_min']
        time_saved = cascade_reduction * delay_per_cascade

        # CNW avoided: proportion of CNW among declines
        cnw_rate = zh['cnw'] / max(zh['primary_volume'], 1)
        cnw_avoided = round(cascade_reduction * cnw_rate)

        # Include satisfaction for both current and suggested
        cur_survey = survey_by_garage.get(zh['primary_garage'], {'total': 0, 'satisfied': 0})
        alt_survey = survey_by_garage.get(best_alt['garage'], {'total': 0, 'satisfied': 0})

        recommendations.append({
            'zone': zh['zone'],
            'type': 'swap_primary',
            'current_primary': zh['primary_garage'],
            'current_accept_pct': zh['primary_accept_pct'],
            'current_satisfaction': round(100 * cur_survey['satisfied'] / cur_survey['total'], 1) if cur_survey['total'] >= 5 else None,
            'suggested_primary': best_alt['garage'],
            'suggested_accept_pct': best_alt['accept_pct'],
            'suggested_satisfaction': round(100 * alt_survey['satisfied'] / alt_survey['total'], 1) if alt_survey['total'] >= 5 else None,
            'impact': {
                'cascades_avoided': cascade_reduction,
                'minutes_saved': time_saved,
                'cnw_avoided': cnw_avoided,
                'primary_volume': calls_per_month,
            },
            'confidence': 'high' if calls_per_month >= 100 else 'medium',
        })

    recommendations.sort(key=lambda r: -r['impact']['minutes_saved'])

    # ── Cascade depth distribution (overall) ──
    spot_histogram = defaultdict(int)
    for gs in garage_stats.values():
        for spot_val, cnt in gs.get('spot_dist', {}).items():
            spot_histogram[spot_val] += cnt
    cascade_depth = [{'rank': k, 'count': v} for k, v in sorted(spot_histogram.items())]

    # ── Summary ──
    total_calls = sum(g['total'] for g in garage_stats.values())
    total_cascaded = sum(g['cascaded_in'] for g in garage_stats.values())
    total_cnw = sum(g['cnw'] for g in garage_stats.values())
    total_declined = sum(g['declined'] for g in garage_stats.values())

    return {
        'period': {'start': start_iso, 'end': end_iso},
        'summary': {
            'total_calls': total_calls,
            'total_cascaded': total_cascaded,
            'cascade_pct': round(100 * total_cascaded / max(total_calls, 1), 1),
            'total_cnw': total_cnw,
            'total_declined': total_declined,
            'zones_analyzed': len(zone_health),
            'garages_analyzed': len(garages_out),
            'recommendations_count': len(recommendations),
        },
        'zones': zone_health[:100],
        'garages': garages_out[:100],
        'recommendations': recommendations[:20],
        'cascade_depth': cascade_depth,
        'computed_at': datetime.now(_ET).isoformat(),
    }


@router.get("/api/matrix/health")
def matrix_health(period: str = Query('last_month')):
    """Priority Matrix cascade health analysis."""
    start_iso, end_iso, ttl = _matrix_period_bounds(period)
    cache_key = f"matrix_health:{period}"

    def _fetch():
        return _compute_matrix(start_iso, end_iso)

    return cache.cached_query(cache_key, _fetch, ttl=ttl)
