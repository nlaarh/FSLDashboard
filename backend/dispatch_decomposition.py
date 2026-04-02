"""Response-time decomposition, driver leaderboard, decline/cancel analysis, demand forecast.

Split from dispatch.py — imported by routers/garages.py, dispatch_drill.py, dispatch_trends.py.
"""

import math
import os
import sys
from datetime import date, timedelta
from collections import defaultdict

from utils import parse_dt as _parse_dt, is_fleet_territory, CYCLE_TIMES
from sf_client import sf_query_all, sf_parallel, sanitize_soql, get_towbook_on_location
import cache

# ── Constants (forecast-specific) ────────────────────────────────────────────
BLOCK_MIN = 120  # 2-hour shift blocks

DOW_WEATHER_MULTIPLIERS = {
    'Clear': 1.0, 'Mild': 1.05, 'Moderate': 1.10, 'Severe': 1.25, 'Extreme': 1.40,
}


# ── Feature 4: Enhanced Scorecard (decomposition + decline analysis) ─────────

def get_response_decomposition(territory_id: str, period_start: str, period_end: str):
    """Break response time into dispatch, travel, on-site segments."""
    territory_id = sanitize_soql(territory_id)
    period_start = sanitize_soql(period_start)
    period_end = sanitize_soql(period_end)

    def _fetch():
        # Get territory name for fleet/contractor classification
        _t_rows = sf_query_all(f"SELECT Name FROM ServiceTerritory WHERE Id = '{territory_id}' LIMIT 1")
        territory_name = _t_rows[0].get('Name', '') if _t_rows else ''
        _is_fleet = is_fleet_territory(territory_name)

        next_day = (date.fromisoformat(period_end) + timedelta(days=1)).isoformat()
        since = f"{period_start}T00:00:00Z"
        until = f"{next_day}T00:00:00Z"

        data = sf_parallel(
            sas=lambda: sf_query_all(f"""
                SELECT Id, Status, CreatedDate, SchedStartTime,
                       ActualStartTime, ActualEndTime,
                       ERS_PTA__c, ERS_Dispatch_Method__c,
                       Off_Platform_Truck_Id__c,
                       Off_Platform_Driver__c, Off_Platform_Driver__r.Name,
                       WorkType.Name
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND Status = 'Completed'
                  AND ActualStartTime != null
                  AND ActualEndTime != null
                ORDER BY CreatedDate ASC
            """),
            declines=lambda: sf_query_all(f"""
                SELECT ERS_Facility_Decline_Reason__c reason, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND ERS_Facility_Decline_Reason__c != null
                GROUP BY ERS_Facility_Decline_Reason__c
                ORDER BY COUNT(Id) DESC
            """),
            cancels=lambda: sf_query_all(f"""
                SELECT ERS_Cancellation_Reason__c reason, COUNT(Id) cnt
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND ERS_Cancellation_Reason__c != null
                GROUP BY ERS_Cancellation_Reason__c
                ORDER BY COUNT(Id) DESC
            """),
            drivers=lambda: sf_query_all(f"""
                SELECT ServiceResource.Name, ServiceResource.Id,
                       COUNT(Id) total_calls
                FROM AssignedResource
                WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
                  AND ServiceAppointment.CreatedDate >= {since}
                  AND ServiceAppointment.CreatedDate < {until}
                  AND ServiceAppointment.Status = 'Completed'
                GROUP BY ServiceResource.Name, ServiceResource.Id
                ORDER BY COUNT(Id) DESC
                LIMIT 25
            """),
            driver_sas=lambda: sf_query_all(f"""
                SELECT ServiceResource.Name, ServiceResource.Id,
                       ServiceAppointment.CreatedDate, ServiceAppointment.ActualStartTime,
                       ServiceAppointment.ActualEndTime, ServiceAppointment.ERS_PTA__c,
                       ServiceAppointment.WorkType.Name,
                       ServiceAppointment.ERS_Facility_Decline_Reason__c,
                       ServiceAppointment.ERS_Dispatch_Method__c
                FROM AssignedResource
                WHERE ServiceAppointment.ServiceTerritoryId = '{territory_id}'
                  AND ServiceAppointment.CreatedDate >= {since}
                  AND ServiceAppointment.CreatedDate < {until}
                  AND ServiceAppointment.Status = 'Completed'
                  AND ServiceAppointment.ActualStartTime != null
                ORDER BY ServiceResource.Name
                LIMIT 2000
            """),
            # Towbook garage: decline SAs with Off_Platform_Truck_Id for per-contractor decline tracking
            decline_sas=lambda: sf_query_all(f"""
                SELECT Off_Platform_Driver__c, ERS_Facility_Decline_Reason__c
                FROM ServiceAppointment
                WHERE ServiceTerritoryId = '{territory_id}'
                  AND CreatedDate >= {since}
                  AND CreatedDate < {until}
                  AND ERS_Facility_Decline_Reason__c != null
                LIMIT 2000
            """),
        )

        # Response time decomposition
        decomp_by_wt = defaultdict(lambda: {'dispatch': [], 'travel': [], 'onsite': [], 'total': [], 'count': 0})
        all_dispatch = []
        all_travel = []
        all_onsite = []
        all_total = []

        # Towbook ActualStartTime is NOT real arrival — the integration writes a
        # future estimated time. Real arrival = ServiceAppointmentHistory 'On Location'.
        def _is_towbook(sa):
            return (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook'

        _tb_count = sum(1 for sa in data['sas'] if _is_towbook(sa))
        is_towbook_garage = _tb_count > len(data['sas']) * 0.5

        # Fetch real On Location timestamps for Towbook SAs
        _towbook_completed_ids = [
            sa['Id'] for sa in data['sas']
            if _is_towbook(sa) and sa.get('Id')
        ]
        _on_loc_map = get_towbook_on_location(_towbook_completed_ids) if _towbook_completed_ids else {}

        for sa in data['sas']:
            wt = (sa.get('WorkType') or {}).get('Name', '') or ''
            if 'drop' in wt.lower():
                continue

            created = _parse_dt(sa.get('CreatedDate'))
            sched = _parse_dt(sa.get('SchedStartTime'))
            started = _parse_dt(sa.get('ActualStartTime'))
            ended = _parse_dt(sa.get('ActualEndTime'))

            if not created:
                continue

            if _is_towbook(sa):
                # Towbook: use real On Location timestamp from ServiceAppointmentHistory
                on_loc_str = _on_loc_map.get(sa.get('Id'))
                on_loc = _parse_dt(on_loc_str) if on_loc_str else None
                if not on_loc or not created:
                    continue
                response = (on_loc - created).total_seconds() / 60
                if response <= 0 or response > 480:
                    continue
                # Can't decompose dispatch/travel for Towbook — use total response
                dispatch_val = response
                travel_val = 0
                # On-site: use On Location → End if both exist
                if on_loc and ended:
                    onsite = (ended - on_loc).total_seconds() / 60
                    if onsite < 0 or onsite > 240:
                        onsite = 0
                else:
                    onsite = 0
                total_min = response + onsite
            else:
                # Fleet: use real ATA timestamps
                if not started or not ended:
                    continue

                total_min = (ended - created).total_seconds() / 60
                if total_min <= 0 or total_min > 480:
                    continue

                onsite = (ended - started).total_seconds() / 60
                if onsite < 0 or onsite > 240:
                    continue

                response = (started - created).total_seconds() / 60
                if response < 0:
                    continue

                if sched and created < sched < started:
                    dispatch_val = (sched - created).total_seconds() / 60
                    travel_val = (started - sched).total_seconds() / 60
                else:
                    dispatch_val = response
                    travel_val = 0

            wt_key = wt if wt else 'Other'
            d = decomp_by_wt[wt_key]
            d['dispatch'].append(dispatch_val)
            d['travel'].append(travel_val)
            d['onsite'].append(onsite)
            d['total'].append(total_min)
            d['count'] += 1

            all_dispatch.append(dispatch_val)
            all_travel.append(travel_val)
            all_onsite.append(onsite)
            all_total.append(total_min)

        def _avg(lst):
            return round(sum(lst) / max(len(lst), 1)) if lst else None

        def _median(lst):
            if not lst:
                return None
            s = sorted(lst)
            return round(s[len(s) // 2])

        decomposition = {
            'avg_dispatch_min': _avg(all_dispatch),
            'avg_travel_min': _avg(all_travel),
            'avg_onsite_min': _avg(all_onsite),
            'avg_total_min': _avg(all_total),
            'median_dispatch_min': _median(all_dispatch),
            'median_travel_min': _median(all_travel),
            'median_onsite_min': _median(all_onsite),
            'median_total_min': _median(all_total),
            'sample_size': len(all_total),
            'method_note': 'ATA from On Location history (Towbook garages)' if is_towbook_garage else 'ATA-based (real arrival times)',
            'response_metric': 'ATA (actual)',
            'by_work_type': {},
        }
        for wt_key, d in decomp_by_wt.items():
            decomposition['by_work_type'][wt_key] = {
                'dispatch': _avg(d['dispatch']),
                'travel': _avg(d['travel']),
                'onsite': _avg(d['onsite']),
                'total': _avg(d['total']),
                'count': d['count'],
            }

        # Decline analysis
        total_sas_for_decline = len(data['sas'])
        decline_rows = data['declines']
        total_declines = sum(r.get('cnt', 0) for r in decline_rows)
        decline_analysis = {
            'total_declines': total_declines,
            'decline_rate': round(100 * total_declines / max(total_sas_for_decline + total_declines, 1), 1),
            'by_reason': [
                {'reason': r.get('reason', 'Unknown'), 'count': r.get('cnt', 0),
                 'pct': round(100 * r.get('cnt', 0) / max(total_declines, 1), 1)}
                for r in decline_rows
            ],
            'top_reason': decline_rows[0].get('reason') if decline_rows else None,
        }

        # Cancellation analysis
        cancel_rows = data['cancels']
        total_cancels = sum(r.get('cnt', 0) for r in cancel_rows)
        cancel_analysis = {
            'total_cancellations': total_cancels,
            'by_reason': [
                {'reason': r.get('reason', 'Unknown'), 'count': r.get('cnt', 0),
                 'pct': round(100 * r.get('cnt', 0) / max(total_cancels, 1), 1)}
                for r in cancel_rows
            ],
        }

        # Fleet = territory 100*/800*. Everything else = contractor.
        tb_sa_count = sum(1 for sa in data['sas'] if (sa.get('ERS_Dispatch_Method__c') or '') == 'Towbook')
        is_towbook_garage = not _is_fleet and tb_sa_count > len(data['sas']) * 0.5

        missing_truck_id_count = 0

        if is_towbook_garage:
            # Towbook garage: build leaderboard from driver (Off_Platform_Driver__c)
            contractor_stats = {}
            # Build per-driver decline counts
            driver_decline_counts = defaultdict(int)
            for d in data['decline_sas']:
                did = d.get('Off_Platform_Driver__c') or ''
                if did:
                    driver_decline_counts[did] += 1

            for sa in data['sas']:
                wt = (sa.get('WorkType') or {}).get('Name', '') or ''
                if 'drop' in wt.lower():
                    continue

                driver_id = sa.get('Off_Platform_Driver__c') or ''
                if not driver_id:
                    missing_truck_id_count += 1
                    continue

                driver_name = (sa.get('Off_Platform_Driver__r') or {}).get('Name', '') or 'Unknown Driver'

                if driver_id not in contractor_stats:
                    contractor_stats[driver_id] = {
                        'name': driver_name, 'id': driver_id,
                        'total_calls': 0, 'response_times': [],
                        'onsite_times': [], 'declines': driver_decline_counts.get(driver_id, 0),
                    }

                cs = contractor_stats[driver_id]
                if driver_name != 'Unknown Driver' and cs['name'] == 'Unknown Driver':
                    cs['name'] = driver_name
                cs['total_calls'] += 1

                # Use real On Location timestamp for Towbook response time
                created_lb = _parse_dt(sa.get('CreatedDate'))
                on_loc_str = _on_loc_map.get(sa.get('Id'))
                on_loc = _parse_dt(on_loc_str) if on_loc_str else None
                if created_lb and on_loc:
                    rt = (on_loc - created_lb).total_seconds() / 60
                    if 0 < rt < 480:
                        cs['response_times'].append(rt)

                # On-site duration: On Location → End
                ended_lb = _parse_dt(sa.get('ActualEndTime'))
                if on_loc and ended_lb:
                    ot = (ended_lb - on_loc).total_seconds() / 60
                    if 0 < ot < 240:
                        cs['onsite_times'].append(ot)

            leaderboard = []
            for cs in contractor_stats.values():
                rts = cs['response_times']
                ots = cs['onsite_times']
                leaderboard.append({
                    'name': cs['name'],
                    'id': cs['id'],
                    'total_calls': cs['total_calls'],
                    'avg_response_min': round(sum(rts) / len(rts)) if rts else None,
                    'median_response_min': round(sorted(rts)[len(rts) // 2]) if rts else None,
                    'avg_onsite_min': round(sum(ots) / len(ots)) if ots else None,
                    'declines': cs['declines'],
                    'decline_rate': round(100 * cs['declines'] / max(cs['total_calls'] + cs['declines'], 1), 1),
                    'response_metric': 'ATA (actual)',
                })
            leaderboard.sort(key=lambda d: d['total_calls'], reverse=True)
        else:
            # Fleet/On-Platform garage: build leaderboard from AssignedResource
            driver_stats = {}
            for r in data['driver_sas']:
                sa_data = r
                sa_ref = sa_data.get('ServiceAppointment') or sa_data

                # Exclude Tow Drop-Off SAs (paired SAs, not real member calls)
                wt_name = ((sa_ref.get('WorkType') or {}).get('Name', '') or '')
                if 'drop' in wt_name.lower():
                    continue

                # Skip Towbook SAs — ActualStartTime is unreliable (midnight bulk-update)
                dispatch_method = (sa_ref.get('ERS_Dispatch_Method__c') or '')
                if dispatch_method == 'Towbook':
                    continue

                drv = (r.get('ServiceResource') or {}).get('Name', '?')
                drv_id = (r.get('ServiceResource') or {}).get('Id', '')

                if drv_id not in driver_stats:
                    driver_stats[drv_id] = {
                        'name': drv, 'id': drv_id,
                        'total_calls': 0, 'response_times': [],
                        'onsite_times': [], 'declines': 0,
                    }

                ds = driver_stats[drv_id]
                ds['total_calls'] += 1

                created = _parse_dt(sa_ref.get('CreatedDate'))
                started = _parse_dt(sa_ref.get('ActualStartTime'))
                ended = _parse_dt(sa_ref.get('ActualEndTime'))

                if created and started:
                    rt = (started - created).total_seconds() / 60
                    if 0 < rt < 480:
                        ds['response_times'].append(rt)
                if started and ended:
                    ot = (ended - started).total_seconds() / 60
                    if 0 < ot < 240:
                        ds['onsite_times'].append(ot)
                if sa_ref.get('ERS_Facility_Decline_Reason__c'):
                    ds['declines'] += 1

            leaderboard = []
            for ds in driver_stats.values():
                rts = ds['response_times']
                ots = ds['onsite_times']
                leaderboard.append({
                    'name': ds['name'],
                    'id': ds['id'],
                    'total_calls': ds['total_calls'],
                    'avg_response_min': round(sum(rts) / len(rts)) if rts else None,
                    'median_response_min': round(sorted(rts)[len(rts) // 2]) if rts else None,
                    'avg_onsite_min': round(sum(ots) / len(ots)) if ots else None,
                    'declines': ds['declines'],
                    'decline_rate': round(100 * ds['declines'] / max(ds['total_calls'], 1), 1),
                })
            leaderboard.sort(key=lambda d: d.get('avg_response_min') or 999)

        return {
            'garage_type': 'fleet' if _is_fleet else ('towbook' if is_towbook_garage else 'contractor'),
            'response_decomposition': decomposition,
            'decline_analysis': decline_analysis,
            'cancel_analysis': cancel_analysis,
            'driver_leaderboard': leaderboard,
            'missing_truck_id_count': missing_truck_id_count,
        }

    return cache.cached_query(f'decomp_{territory_id}_{period_start}_{period_end}', _fetch, ttl=3600)


# ── Feature 5: Demand Forecast ───────────────────────────────────────────────

def get_forecast(territory_id: str, weeks_history: int = 8):
    """16-day demand forecast using DOW patterns + weather."""
    territory_id = sanitize_soql(territory_id)

    def _fetch():
        days_back = weeks_history * 7
        cutoff = (date.today() - timedelta(days=days_back)).isoformat()
        since = f"{cutoff}T00:00:00Z"

        # Historical volume by DOW
        hist = sf_query_all(f"""
            SELECT DAY_IN_WEEK(CreatedDate) dow, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE ServiceTerritoryId = '{territory_id}'
              AND CreatedDate >= {since}
              AND Status IN ('Dispatched','Completed','Canceled','Assigned')
              AND WorkType.Name != 'Tow Drop-Off'
            GROUP BY DAY_IN_WEEK(CreatedDate)
        """)

        # SOQL DOW: 1=Sun..7=Sat
        _DOW_MAP = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
        _DOW_NUM = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
        dow_totals = {}
        for r in hist:
            day_name = _DOW_MAP.get(int(r.get('dow', 0)), '?')
            dow_totals[day_name] = r.get('cnt', 0)

        dow_avg = {d: round(v / max(weeks_history, 1)) for d, v in dow_totals.items()}

        # Get weather forecast
        weather_forecast = []
        try:
            weather_api_path = os.path.join(os.path.dirname(__file__), '..', '..', '..')
            sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
            from weather import WeatherAnalyzer
            wx = WeatherAnalyzer()
            fc = wx.get_forecast(forecast_days=16)
            if fc is not None and len(fc) > 0:
                for _, row in fc.iterrows():
                    weather_forecast.append({
                        'date': row['date'].strftime('%Y-%m-%d') if hasattr(row['date'], 'strftime') else str(row['date'])[:10],
                        'temp_max_f': round(row.get('temp_max_f', 0)),
                        'temp_min_f': round(row.get('temp_min_f', 0)),
                        'snow_in': round(row.get('snow_in', 0), 1),
                        'precip_in': round(row.get('precip_in', 0), 1),
                        'wind_max_mph': round(row.get('wind_max_mph', 0)),
                        'severity': row.get('severity', 'Clear'),
                        'weather_desc': row.get('weather_desc', ''),
                        'weather_code': int(row.get('weather_code', 0)),
                    })
        except Exception:
            # Fallback: generate 16 days without weather
            for i in range(16):
                d = date.today() + timedelta(days=i)
                weather_forecast.append({
                    'date': d.isoformat(),
                    'temp_max_f': None, 'temp_min_f': None,
                    'snow_in': 0, 'precip_in': 0, 'wind_max_mph': 0,
                    'severity': 'Clear', 'weather_desc': 'No forecast data',
                    'weather_code': 0,
                })

        # Build 16-day forecast
        forecast_days = []
        for wx_day in weather_forecast:
            d = date.fromisoformat(wx_day['date'])
            dow_name = d.strftime('%a')
            base_vol = dow_avg.get(dow_name, 0)
            multiplier = DOW_WEATHER_MULTIPLIERS.get(wx_day['severity'], 1.0)
            adjusted = round(base_vol * multiplier)

            # Driver needs per 2-hour block
            call_tier_split = {'tow': 0.48, 'battery': 0.30, 'light': 0.22}
            peak_block_calls = round(adjusted * 0.15)  # ~15% of daily volume in peak 2h block
            peak_tow = math.ceil(peak_block_calls * call_tier_split['tow'] * CYCLE_TIMES['tow'] / BLOCK_MIN)
            peak_bl = math.ceil(peak_block_calls * (call_tier_split['battery'] + call_tier_split['light']) * CYCLE_TIMES['battery'] / BLOCK_MIN)

            forecast_days.append({
                'date': wx_day['date'],
                'day_of_week': dow_name,
                'weather': wx_day,
                'base_volume': base_vol,
                'weather_multiplier': multiplier,
                'adjusted_volume': adjusted,
                'driver_needs': {
                    'peak_tow': peak_tow,
                    'peak_batt_light': peak_bl,
                    'peak_total': peak_tow + peak_bl,
                    'peak_block': '12-2pm',
                },
                'confidence': 'high' if base_vol > 10 else 'medium' if base_vol > 0 else 'low',
            })

        return {
            'forecast': forecast_days,
            'model': {
                'weeks_analyzed': weeks_history,
                'dow_averages': dow_avg,
                'weather_multipliers': DOW_WEATHER_MULTIPLIERS,
            },
        }

    return cache.cached_query(f'forecast_{territory_id}_{weeks_history}', _fetch, ttl=3600)
