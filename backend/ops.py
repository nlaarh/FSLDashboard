"""Daily Operations endpoints — TODAY only, live SOQL, correct PTA/ATA metrics.

- Fleet ATA = ActualStartTime - CreatedDate
- Towbook ATA = ServiceAppointmentHistory 'On Location' timestamp - CreatedDate
  (ActualStartTime is a fake future estimate; real arrival is the 'On Location' event)
- ERS_Dispatch_Method__c = 'Field Services' or 'Towbook'
"""

from datetime import datetime, date, timedelta, timezone
from collections import defaultdict

from utils import _ET, parse_dt as _parse_dt, minutes_since as _minutes_since
from sf_client import sf_query_all, sf_parallel, sanitize_soql, get_towbook_on_location
import cache


def _calc_ata(sa, towbook_on_location=None):
    """Calculate ATA in minutes.
    - Fleet: ActualStartTime - CreatedDate
    - Towbook: 'On Location' history timestamp - CreatedDate
      (ActualStartTime is a fake future estimate written at completion)

    Args:
        towbook_on_location: dict {sa_id: iso_datetime} from get_towbook_on_location()
    """
    created = _parse_dt(sa.get('CreatedDate'))
    if not created:
        return None

    dispatch_method = (sa.get('ERS_Dispatch_Method__c') or '')
    if dispatch_method == 'Towbook':
        # Use real arrival from ServiceAppointmentHistory
        if not towbook_on_location:
            return None
        on_loc_str = towbook_on_location.get(sa.get('Id'))
        if not on_loc_str:
            return None
        on_loc = _parse_dt(on_loc_str)
        if not on_loc:
            return None
        diff = (on_loc - created).total_seconds() / 60
    else:
        actual_start = _parse_dt(sa.get('ActualStartTime'))
        if not actual_start:
            return None
        diff = (actual_start - created).total_seconds() / 60

    if diff <= 0 or diff >= 480:
        return None

    return round(diff)


def _get_priority_matrix():
    """Load the full territory priority matrix. Cached 10 min (rarely changes)."""
    def _fetch():
        rows = sf_query_all("""
            SELECT ERS_Parent_Service_Territory__c,
                   ERS_Spotted_Territory__c, ERS_Spotted_Territory__r.Name,
                   ERS_Priority__c, ERS_Worktype__c
            FROM ERS_Territory_Priority_Matrix__c
            ORDER BY ERS_Parent_Service_Territory__c, ERS_Priority__c
        """)
        # Build lookup: (parent_territory_id, spotted_territory_id) -> priority number
        # Also build: spotted_territory_id -> list of {parent_id, priority, work_types}
        by_pair = {}
        by_garage = defaultdict(list)
        for r in rows:
            parent_id = r.get('ERS_Parent_Service_Territory__c')
            spotted_id = r.get('ERS_Spotted_Territory__c')
            pri = r.get('ERS_Priority__c')
            wt = r.get('ERS_Worktype__c', '')
            if parent_id and spotted_id:
                by_pair[(parent_id, spotted_id)] = pri
                by_garage[spotted_id].append({
                    'parent_id': parent_id,
                    'priority': pri,
                    'work_types': wt,
                })
        # For each (parent, work_type_group), rank garages by priority number
        # Rank 1 = lowest priority number for that parent zone
        by_parent = defaultdict(list)
        for r in rows:
            parent_id = r.get('ERS_Parent_Service_Territory__c')
            spotted_id = r.get('ERS_Spotted_Territory__c')
            pri = r.get('ERS_Priority__c')
            if parent_id and spotted_id and pri is not None:
                by_parent[parent_id].append((pri, spotted_id))
        # For each parent, sort by priority and assign rank
        rank_lookup = {}  # (parent_id, spotted_id) -> rank (1=first call, 2=second call, etc.)
        for parent_id, entries in by_parent.items():
            entries.sort(key=lambda x: x[0])
            seen = set()
            rank = 0
            for pri, spotted_id in entries:
                if spotted_id not in seen:
                    seen.add(spotted_id)
                    rank += 1
                    rank_lookup[(parent_id, spotted_id)] = rank
        return {'by_pair': by_pair, 'by_garage': dict(by_garage), 'rank_lookup': rank_lookup}
    return cache.cached_query('priority_matrix', _fetch, ttl=600)


def get_ops_garages():
    """All garage territories with location, phone, and zone count for map layer."""
    def _fetch():
        rows = sf_query_all("""
            SELECT Id, Name, Latitude, Longitude,
                   ERS_Facility_Account__r.Name, ERS_Facility_Account__r.Phone,
                   ERS_Facility_Account__r.Dispatch_Method__c,
                   Street, City, State
            FROM ServiceTerritory
            WHERE Id IN (SELECT ERS_Spotted_Territory__c FROM ERS_Territory_Priority_Matrix__c)
              AND IsActive = true
              AND Latitude != null AND Longitude != null
        """)
        matrix = _get_priority_matrix()
        garages = []
        for r in rows:
            tid = r.get('Id')
            acct = r.get('ERS_Facility_Account__r') or {}
            zone_entries = matrix['by_garage'].get(tid, [])
            # Count how many zones this garage is primary (rank 1) vs secondary (rank 2+)
            primary_zones = 0
            secondary_zones = 0
            for entry in zone_entries:
                rank = matrix['rank_lookup'].get((entry['parent_id'], tid))
                if rank == 1:
                    primary_zones += 1
                elif rank and rank >= 2:
                    secondary_zones += 1
            garages.append({
                'id': tid,
                'name': r.get('Name', ''),
                'lat': r.get('Latitude'),
                'lon': r.get('Longitude'),
                'phone': acct.get('Phone') or None,
                'facility_name': acct.get('Name') or None,
                'address': f"{r.get('Street') or ''}, {r.get('City') or ''} {r.get('State') or ''}".strip(', '),
                'primary_zones': primary_zones,
                'secondary_zones': secondary_zones,
                'total_zones': len(zone_entries),
                'dispatch_method': acct.get('Dispatch_Method__c') or 'Unknown',
            })
        garages.sort(key=lambda g: g['name'])
        return garages
    return cache.cached_query('ops_garages', _fetch, ttl=600)


def get_ops_territories():
    """All territories with today's KPIs — correct PTA/ATA."""
    now_utc = datetime.now(timezone.utc)
    # Today = midnight ET to now (DST-aware)
    now_et = now_utc.astimezone(_ET)
    today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    cutoff = today_start.strftime('%Y-%m-%dT%H:%M:%SZ')

    def _fetch():
        sas = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   ActualStartTime, ActualEndTime, SchedStartTime,
                   ERS_PTA__c, ERS_PTA_Due__c, ERS_Dispatch_Method__c,
                   ERS_Parent_Territory__c,
                   ServiceTerritoryId, ServiceTerritory.Name,
                   ServiceTerritory.Latitude, ServiceTerritory.Longitude,
                   WorkType.Name, Latitude, Longitude
            FROM ServiceAppointment
            WHERE CreatedDate >= {cutoff}
              AND ServiceTerritoryId != null
              AND Status IN ('Dispatched','Completed','Canceled',
                             'Cancel Call - Service Not En Route',
                             'Cancel Call - Service En Route',
                             'Unable to Complete','Assigned','No-Show')
            ORDER BY CreatedDate ASC
        """)

        by_territory = defaultdict(list)
        for sa in sas:
            tid = sa.get('ServiceTerritoryId')
            if tid:
                by_territory[tid].append(sa)

        # Collect IDs needed by both history queries
        towbook_completed_ids = [
            sa['Id'] for sa in sas
            if (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook'
            and sa.get('Status') == 'Completed'
            and sa.get('Id')
        ]
        all_sa_ids = [sa['Id'] for sa in sas if sa.get('Id')]

        from sf_batch import batch_soql_parallel
        # Both queries depend on sas but not on each other — run in parallel
        _hist = sf_parallel(
            towbook=lambda: get_towbook_on_location(towbook_completed_ids),
            sa_hist=lambda: batch_soql_parallel("""
                SELECT ServiceAppointmentId, NewValue, CreatedDate
                FROM ServiceAppointmentHistory
                WHERE Field = 'ServiceTerritory'
                  AND ServiceAppointmentId IN ('{id_list}')
                ORDER BY ServiceAppointmentId, CreatedDate ASC
            """, all_sa_ids, chunk_size=200) if all_sa_ids else [],
        )
        towbook_on_location = _hist['towbook']
        sa_hist_rows = _hist['sa_hist']

        matrix = _get_priority_matrix()
        rank_lookup = matrix['rank_lookup']

        # Build first-territory map: sa_id -> first territory ID assigned
        sa_first_territory = {}
        for h in sa_hist_rows:
            sa_id = h.get('ServiceAppointmentId')
            if sa_id in sa_first_territory:
                continue
            nv = h.get('NewValue', '') or ''
            if nv.startswith('0Hh'):
                sa_first_territory[sa_id] = nv

        territories = []
        for tid, sa_list_raw in by_territory.items():
            st = sa_list_raw[0]
            t_name = (st.get('ServiceTerritory') or {}).get('Name') or '?'
            t_lat = (st.get('ServiceTerritory') or {}).get('Latitude')
            t_lon = (st.get('ServiceTerritory') or {}).get('Longitude')
            if not t_lat or not t_lon:
                continue

            # Exclude Tow Drop-Off from counts (paired SAs, not real calls)
            sa_list = [s for s in sa_list_raw
                       if 'drop' not in ((s.get('WorkType') or {}).get('Name', '') or '').lower()]
            total = len(sa_list)
            open_list = [s for s in sa_list if s.get('Status') in ('Dispatched', 'Assigned')]
            completed = [s for s in sa_list if s.get('Status') == 'Completed']
            canceled = [s for s in sa_list if s.get('Status') not in ('Dispatched', 'Assigned', 'Completed')]

            # PTA stats (all SAs with PTA)
            pta_values = []
            for s in sa_list:
                pta = s.get('ERS_PTA__c')
                if pta is not None and 0 < float(pta) < 999:
                    pta_values.append(float(pta))

            avg_pta = round(sum(pta_values) / len(pta_values)) if pta_values else None
            pta_under_60 = sum(1 for p in pta_values if p <= 60)
            pta_under_60_pct = round(100 * pta_under_60 / max(len(pta_values), 1)) if pta_values else None

            # ATA stats (Fleet: ActualStartTime, Towbook: On Location from history)
            ata_values = []
            fleet_pta_values = []
            for s in completed:
                wt = (s.get('WorkType') or {}).get('Name', '')
                if 'drop' in wt.lower():
                    continue
                ata = _calc_ata(s, towbook_on_location)
                if ata is not None:
                    ata_values.append(ata)
                pta = s.get('ERS_PTA__c')
                if pta is not None and 0 < float(pta) < 999:
                    fleet_pta_values.append(float(pta))

            avg_ata = round(sum(ata_values) / len(ata_values)) if ata_values else None
            ata_under_45 = sum(1 for a in ata_values if a <= 45)
            ata_under_45_pct = round(100 * ata_under_45 / max(len(ata_values), 1)) if ata_values else None

            # Open call wait times
            open_waits = []
            for s in open_list:
                wait = _minutes_since(s.get('CreatedDate'), now_utc)
                if wait and 0 < wait < 1440:
                    open_waits.append(wait)
            avg_wait = round(sum(open_waits) / len(open_waits)) if open_waits else 0
            max_wait = max(open_waits) if open_waits else 0

            completion_rate = round(100 * len(completed) / max(total, 1))

            # Health status
            if total < 3:
                status = 'good'
            elif max_wait > 90 or (avg_pta and avg_pta > 120):
                status = 'critical'
            elif max_wait > 45 or completion_rate < 55:
                status = 'behind'
            else:
                status = 'good'

            # Response time: ATA if available, else PTA as estimate
            resp_time = avg_ata if avg_ata is not None else avg_pta
            resp_source = 'ata' if avg_ata is not None else ('pta' if avg_pta is not None else None)

            # Primary/secondary: based on actual SA assignment history
            # Primary = this garage was the FIRST territory assigned (1st call)
            # Secondary = SA was originally assigned elsewhere, then cascaded here
            primary_total = 0
            primary_completed = 0
            secondary_total = 0
            secondary_completed = 0
            for s in sa_list:
                wt = (s.get('WorkType') or {}).get('Name', '')
                if 'drop' in wt.lower():
                    continue
                first_tid = sa_first_territory.get(s.get('Id'))
                is_secondary = first_tid is not None and first_tid != tid
                if is_secondary:
                    secondary_total += 1
                    if s.get('Status') == 'Completed':
                        secondary_completed += 1
                else:
                    primary_total += 1
                    if s.get('Status') == 'Completed':
                        primary_completed += 1

            pct_primary_completion = round(100 * primary_completed / primary_total) if primary_total else None
            pct_secondary_completion = round(100 * secondary_completed / secondary_total) if secondary_total else None

            territories.append({
                'id': tid,
                'name': t_name,
                'lat': t_lat,
                'lon': t_lon,
                'total': total,
                'open': len(open_list),
                'completed': len(completed),
                'canceled': len(canceled),
                'completion_rate': completion_rate,
                'primary_total': primary_total,
                'primary_completed': primary_completed,
                'pct_primary_completion': pct_primary_completion,
                'secondary_total': secondary_total,
                'secondary_completed': secondary_completed,
                'pct_secondary_completion': pct_secondary_completion,
                'avg_pta': avg_pta,
                'pta_sample_size': len(pta_values),
                'pta_under_60_pct': pta_under_60_pct,
                'avg_ata': avg_ata,
                'ata_under_45_pct': ata_under_45_pct,
                'ata_sample_size': len(ata_values),
                'resp_time': resp_time,
                'resp_source': resp_source,
                'avg_wait': avg_wait,
                'max_wait': max_wait,
                'status': status,
            })

        territories.sort(key=lambda t: t['total'], reverse=True)

        # Summary
        total_open = sum(t['open'] for t in territories)
        total_completed = sum(t['completed'] for t in territories)
        total_sas = sum(t['total'] for t in territories)
        all_pta = [t['avg_pta'] for t in territories if t['avg_pta'] is not None]

        return {
            'territories': territories,
            'summary': {
                'total_territories': len(territories),
                'total_open': total_open,
                'total_completed': total_completed,
                'total_sas': total_sas,
                'fleet_avg_pta': round(sum(all_pta) / len(all_pta)) if all_pta else None,
                'critical': sum(1 for t in territories if t['status'] == 'critical'),
                'behind': sum(1 for t in territories if t['status'] == 'behind'),
            },
        }

    return cache.cached_query('ops_territories', _fetch, ttl=120)


def get_ops_territory_detail(territory_id: str):
    """Single territory today — SA list with PTA/ATA per call."""
    territory_id = sanitize_soql(territory_id)
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(_ET)
    today_start = now_et.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    cutoff = today_start.strftime('%Y-%m-%dT%H:%M:%SZ')

    def _fetch():
        sas = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate,
                   ActualStartTime, ActualEndTime, SchedStartTime,
                   ERS_PTA__c, ERS_PTA_Due__c, ERS_Dispatch_Method__c,
                   ERS_Parent_Territory__c, ERS_Parent_Territory__r.Name,
                   ERS_Cancellation_Reason__c, ERS_Facility_Decline_Reason__c,
                   WorkType.Name, Street, City, PostalCode,
                   Latitude, Longitude
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {cutoff}
              AND Status IN ('Dispatched','Completed','Canceled',
                             'Cancel Call - Service Not En Route',
                             'Cancel Call - Service En Route',
                             'Unable to Complete','Assigned','No-Show')
            ORDER BY CreatedDate DESC
        """)

        # Fetch real arrival times for Towbook SAs
        tb_ids = [s['Id'] for s in sas
                  if (s.get('ERS_Dispatch_Method__c') or '') == 'Towbook'
                  and s.get('Status') == 'Completed' and s.get('Id')]
        towbook_on_location = get_towbook_on_location(tb_ids)

        # Load priority matrix for rank lookup
        matrix = _get_priority_matrix()

        sa_rows = []
        pta_values = []
        ata_values = []
        status_counts = defaultdict(int)
        wt_counts = defaultdict(int)
        # Track completion by priority rank
        rank_stats = defaultdict(lambda: {'total': 0, 'completed': 0, 'canceled': 0})

        for sa in sas:
            wt = (sa.get('WorkType') or {}).get('Name', 'Unknown')
            status = sa.get('Status', 'Unknown')
            dispatch = sa.get('ERS_Dispatch_Method__c', '')
            pta = sa.get('ERS_PTA__c')
            created = sa.get('CreatedDate')
            is_dropoff = 'drop' in wt.lower()

            # Determine priority rank from matrix
            parent_tid = sa.get('ERS_Parent_Territory__c')
            priority_rank = matrix['rank_lookup'].get((parent_tid, territory_id)) if parent_tid else None

            if not is_dropoff:
                status_counts[status] += 1
            if not is_dropoff:
                wt_counts[wt] += 1
                # Track completion by rank (exclude drop-offs)
                rk = priority_rank if priority_rank is not None else 0  # 0 = unranked
                rank_stats[rk]['total'] += 1
                if status == 'Completed':
                    rank_stats[rk]['completed'] += 1
                elif status not in ('Dispatched', 'Assigned'):
                    rank_stats[rk]['canceled'] += 1

            # PTA
            pta_min = None
            if pta is not None and 0 < float(pta) < 999:
                pta_min = round(float(pta))
                if not is_dropoff:
                    pta_values.append(pta_min)

            # ATA (Fleet: ActualStartTime, Towbook: On Location history)
            ata_min = None
            if not is_dropoff:
                ata_min = _calc_ata(sa, towbook_on_location)
                if ata_min is not None:
                    ata_values.append(ata_min)

            # Wait time for open calls
            wait = None
            if status in ('Dispatched', 'Assigned'):
                wait = _minutes_since(created, now_utc)

            # On-site duration (arrival → end)
            # Towbook: use On Location from history; Fleet: use ActualStartTime
            onsite = None
            actual_end = _parse_dt(sa.get('ActualEndTime'))
            if actual_end:
                if dispatch == 'Towbook':
                    on_loc_str = towbook_on_location.get(sa.get('Id')) if towbook_on_location else None
                    arrival = _parse_dt(on_loc_str) if on_loc_str else None
                else:
                    arrival = _parse_dt(sa.get('ActualStartTime'))
                if arrival:
                    onsite = round((actual_end - arrival).total_seconds() / 60)
                    if onsite < 0 or onsite > 480:
                        onsite = None

            sa_rows.append({
                'id': sa.get('Id'),
                'number': sa.get('AppointmentNumber'),
                'work_type': wt,
                'status': status,
                'dispatch_method': dispatch,
                'pta_min': pta_min,
                'ata_min': ata_min,
                'wait_min': wait,
                'onsite_min': onsite,
                'created': created,
                'address': sa.get('Street') or sa.get('City') or '',
                'lat': sa.get('Latitude'),
                'lon': sa.get('Longitude'),
                'cancel_reason': sa.get('ERS_Cancellation_Reason__c'),
                'decline_reason': sa.get('ERS_Facility_Decline_Reason__c'),
                'is_dropoff': is_dropoff,
                'priority_rank': priority_rank,
                'parent_zone': (sa.get('ERS_Parent_Territory__r') or {}).get('Name'),
            })

        # Summary KPIs (exclude Tow Drop-Off from counts)
        non_dropoff = [s for s in sa_rows if not s['is_dropoff']]
        total = len(non_dropoff)
        completed = sum(1 for s in non_dropoff if s['status'] == 'Completed')
        open_count = sum(1 for s in non_dropoff if s['status'] in ('Dispatched', 'Assigned'))
        avg_pta = round(sum(pta_values) / len(pta_values)) if pta_values else None
        avg_ata = round(sum(ata_values) / len(ata_values)) if ata_values else None
        median_ata = round(sorted(ata_values)[len(ata_values) // 2]) if ata_values else None
        ata_under_45 = sum(1 for a in ata_values if a <= 45)

        # PTA-ATA delta
        pta_ata_delta = None
        if avg_pta is not None and avg_ata is not None:
            pta_ata_delta = round(avg_ata - avg_pta)  # positive = behind, negative = ahead

        # Build completion-by-rank summary
        completion_by_rank = []
        ranked_keys = sorted(k for k in rank_stats.keys() if k > 0)
        has_ranked = len(ranked_keys) > 0

        # If we have ranked data, show ranked entries; unranked (0) shown separately
        # If NO ranked data at all, treat unranked as "All calls" (fallback)
        if has_ranked:
            for rank in ranked_keys:
                rs = rank_stats[rank]
                label = {1: '1st call', 2: '2nd call', 3: '3rd call'}.get(rank, f'{rank}th call')
                completion_by_rank.append({
                    'rank': rank,
                    'label': label,
                    'total': rs['total'],
                    'completed': rs['completed'],
                    'canceled': rs['canceled'],
                    'completion_pct': round(100 * rs['completed'] / max(rs['total'], 1), 1),
                })
            if 0 in rank_stats and rank_stats[0]['total'] > 0:
                rs = rank_stats[0]
                completion_by_rank.append({
                    'rank': 0,
                    'label': 'Unranked',
                    'total': rs['total'],
                    'completed': rs['completed'],
                    'canceled': rs['canceled'],
                    'completion_pct': round(100 * rs['completed'] / max(rs['total'], 1), 1),
                })
        elif 0 in rank_stats and rank_stats[0]['total'] > 0:
            rs = rank_stats[0]
            completion_by_rank.append({
                'rank': 1,
                'label': 'All calls',
                'total': rs['total'],
                'completed': rs['completed'],
                'canceled': rs['canceled'],
                'completion_pct': round(100 * rs['completed'] / max(rs['total'], 1), 1),
            })

        return {
            'territory_id': territory_id,
            'period': 'today',
            'total': total,
            'completed': completed,
            'open': open_count,
            'completion_pct': round(100 * completed / max(total, 1), 1),
            'kpi': {
                'avg_pta': avg_pta,
                'avg_ata': avg_ata,
                'median_ata': median_ata,
                'pta_ata_delta': pta_ata_delta,
                'ata_under_45': ata_under_45,
                'ata_under_45_pct': round(100 * ata_under_45 / max(len(ata_values), 1), 1) if ata_values else None,
                'ata_sample_size': len(ata_values),
                'ata_note': 'ATA includes all dispatch methods (Field Services + Towbook).',
            },
            'completion_by_rank': completion_by_rank,
            'status_counts': dict(status_counts),
            'work_type_counts': dict(wt_counts),
            'service_appointments': sa_rows,
        }

    return cache.cached_query(f'ops_territory_{territory_id}', _fetch, ttl=120)
