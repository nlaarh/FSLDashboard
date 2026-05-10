"""Helper functions extracted from _build_woa_data to keep accounting_audit.py under 600 lines."""
import json as _json
from utils import parse_dt as _parse_dt
from routers.accounting_calc import _fmt_et, _safe_float


def _build_sa_timeline(sa_history: list, status_transitions: list) -> list:
    """Build ordered status-change timeline for a single SA."""
    timeline = []
    _prev_ts = None
    for h in sa_history:
        nv = h.get('NewValue', '')
        if nv in status_transitions:
            _cur_ts = _parse_dt(h.get('CreatedDate'))
            _elapsed = round((_cur_ts - _prev_ts).total_seconds()) if (_prev_ts and _cur_ts) else None
            timeline.append({
                'time': _fmt_et(h.get('CreatedDate')),
                'from': h.get('OldValue') or '',
                'to': nv,
                'elapsed_seconds': _elapsed,
            })
            if _cur_ts is not None:
                _prev_ts = _cur_ts
    return timeline


def _extract_sa_timestamps(sa_history: list) -> tuple:
    """Extract (enroute_ts, on_loc_ts, completed_ts) from SA history."""
    on_loc_ts = completed_ts = enroute_ts = None
    for h in sa_history:
        nv = h.get('NewValue', '')
        ts = _parse_dt(h.get('CreatedDate'))
        if nv == 'En Route' and enroute_ts is None:
            enroute_ts = ts
        if nv == 'On Location' and on_loc_ts is None:
            on_loc_ts = ts
        if nv == 'Completed' and completed_ts is None:
            completed_ts = ts
    return enroute_ts, on_loc_ts, completed_ts


def _build_secondary_sa_timelines(secondary_sa_rows: list, parallel_data: dict, status_transitions: list) -> list:
    """Build timeline entries for secondary SAs on a multi-SA work order."""
    result = []
    for i, sec_sa in enumerate(secondary_sa_rows[:3]):
        sec_history = parallel_data.get(f'sa_history_{i+2}') or []
        sec_timeline = _build_sa_timeline(sec_history, status_transitions)
        if sec_timeline:
            result.append({
                'sa_number': sec_sa.get('AppointmentNumber', ''),
                'sa_id': sec_sa.get('Id', ''),
                'work_type': (sec_sa.get('WorkType') or {}).get('Name', ''),
                'status': sec_sa.get('Status', ''),
                'timeline': sec_timeline,
            })
    return result


def _parse_rflib_gps(rflib_logs: list) -> tuple:
    """Parse Towbook rflib GPS logs → (dispatched_gps, enroute_gps, on_location_gps).

    Each result is a dict with lat/lon/driver_name/truck/timestamp/source, or None.
    DISPATCHED = last known location when call was assigned (best mileage origin).
    EN_ROUTE = driver tapped En Route in Towbook app (may be missing).
    """
    dispatched = enroute = on_location = None
    for rlog in rflib_logs:
        try:
            req = _json.loads(rlog.get('ERS_Request__c') or '{}')
            status = req.get('status', '')
            drv = req.get('driver') or {}
            lat = _safe_float(drv.get('latitude'))
            lon = _safe_float(drv.get('longitude'))
            if not (lat and lon):
                continue
            if status == 'DISPATCHED' and not dispatched:
                dispatched = {
                    'lat': lat, 'lon': lon,
                    'driver_name': drv.get('name', ''),
                    'truck': drv.get('truckName', ''),
                    'timestamp': rlog.get('CreatedDate'),
                    'source': 'towbook_gps_dispatched',
                }
            elif status == 'EN_ROUTE' and not enroute:
                enroute = {
                    'lat': lat, 'lon': lon,
                    'driver_name': drv.get('name', ''),
                    'truck': drv.get('truckName', ''),
                    'timestamp': rlog.get('CreatedDate'),
                    'source': 'towbook_gps_enroute',
                }
            elif status == 'ON_LOCATION' and not on_location:
                on_location = {
                    'lat': lat, 'lon': lon,
                    'driver_name': drv.get('name', ''),
                    'truck': drv.get('truckName', ''),
                    'timestamp': rlog.get('CreatedDate'),
                    'source': 'towbook_gps_on_location',
                }
        except Exception:
            pass
    return dispatched, enroute, on_location
