"""Map endpoints: grid boundaries, driver GPS, weather."""

import re
import requests as _requests
from fastapi import APIRouter

from utils import to_eastern as _to_eastern
from sf_client import sf_query_all, sf_parallel
import cache

router = APIRouter()

# WMO weather interpretation codes (Open-Meteo standard)
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm+hail", 99: "Thunderstorm+heavy hail",
}


def _parse_kml_coords(kml: str) -> list:
    """Extract [[lon, lat], ...] from a KML string."""
    m = re.search(r'<coordinates[^>]*>(.*?)</coordinates>', kml, re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    coords = []
    for point in m.group(1).strip().split():
        parts = point.split(',')
        if len(parts) >= 2:
            try:
                coords.append([float(parts[0]), float(parts[1])])
            except ValueError:
                pass
    return coords


# ── Map — Grid Boundaries ────────────────────────────────────────────────────

@router.get("/api/map/grids")
def get_map_grids():
    """All FSL polygon boundaries as GeoJSON FeatureCollection."""
    def _fetch():
        recs = sf_query_all("""
            SELECT Id, Name, FSL__Service_Territory__c,
                   FSL__Service_Territory__r.Name,
                   FSL__Color__c, FSL__KML__c
            FROM FSL__Polygon__c
            ORDER BY Name
        """)
        features = []
        for rec in recs:
            kml = rec.get('FSL__KML__c') or ''
            if not kml:
                continue
            coords = _parse_kml_coords(kml)
            if len(coords) < 3:
                continue
            color = rec.get('FSL__Color__c') or '#818cf8'
            features.append({
                'type': 'Feature',
                'properties': {
                    'id': rec['Id'],
                    'name': rec.get('Name', ''),
                    'territory_name': (rec.get('FSL__Service_Territory__r') or {}).get('Name', ''),
                    'territory_id': rec.get('FSL__Service_Territory__c', ''),
                    'color': color,
                },
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [coords],
                },
            })
        return {'type': 'FeatureCollection', 'features': features}

    return cache.cached_query('map_grids', _fetch, ttl=3600)


# ── Map — Driver GPS Positions ────────────────────────────────────────────────

@router.get("/api/map/drivers")
def get_map_drivers():
    """Active drivers logged into vehicles with last known GPS positions (cached 2 minutes)."""
    def _fetch():
        from sf_client import sf_query_all as _sqa_local, sf_parallel as _sf_par

        def _drv():
            return _sqa_local("""
                SELECT Id, Name,
                       LastKnownLatitude, LastKnownLongitude, LastKnownLocationDate,
                       ERS_Driver_Type__c, ERS_Tech_ID__c,
                       RelatedRecord.Phone
                FROM ServiceResource
                WHERE IsActive = true
                  AND ResourceType = 'T'
                  AND LastKnownLatitude != null
                  AND ERS_Driver_Type__c IN ('Fleet Driver', 'On-Platform Contractor Driver')
                ORDER BY Name
            """)

        def _trucks():
            return _sqa_local("""
                SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c, ERS_LegacyTruckID__c
                FROM Asset
                WHERE RecordType.Name = 'ERS Truck'
                  AND ERS_Driver__c != null
            """)

        fetched = _sf_par(drivers=_drv, trucks=_trucks)
        drivers = fetched['drivers']
        logged_in_ids = set()
        truck_map = {}
        for asset in fetched['trucks']:
            dr_id = asset.get('ERS_Driver__c')
            if dr_id:
                logged_in_ids.add(dr_id)
                truck_map[dr_id] = {
                    'truck_name': asset.get('Name', ''),
                    'truck_capabilities': asset.get('ERS_Truck_Capabilities__c', ''),
                }

        result = []
        for d in drivers:
            # Only show drivers logged into a vehicle
            if d['Id'] not in logged_in_ids:
                continue
            gps_date = _to_eastern(d.get('LastKnownLocationDate'))
            rr = d.get('RelatedRecord') or {}
            truck = truck_map.get(d['Id'], {})
            # Flag stale GPS (>2 hours old)
            stale = False
            if gps_date:
                from datetime import datetime as _dt
                now_et = _dt.now(gps_date.tzinfo) if gps_date.tzinfo else _dt.now()
                age_min = (now_et - gps_date).total_seconds() / 60
                stale = age_min > 120
            else:
                stale = True
            result.append({
                'id': d['Id'],
                'name': d.get('Name', '?'),
                'lat': float(d['LastKnownLatitude']),
                'lon': float(d['LastKnownLongitude']),
                'gps_time': gps_date.strftime('%I:%M %p') if gps_date else '?',
                'gps_stale': stale,
                'driver_type': d.get('ERS_Driver_Type__c', ''),
                'tech_id': d.get('ERS_Tech_ID__c', ''),
                'phone': rr.get('Phone') or None,
                'truck': truck.get('truck_name', ''),
                'truck_capabilities': truck.get('truck_capabilities', ''),
            })
        return result

    return cache.cached_query('map_drivers', _fetch, ttl=120)


# ── Map — Weather ─────────────────────────────────────────────────────────────

@router.get("/api/map/weather")
def get_map_weather():
    """Current weather at Buffalo, Rochester, Syracuse from Open-Meteo (cached 15 min)."""
    def _fetch():
        stations = [
            {'name': 'Buffalo',   'lat': 42.89, 'lon': -78.86},
            {'name': 'Rochester', 'lat': 43.15, 'lon': -77.61},
            {'name': 'Syracuse',  'lat': 43.05, 'lon': -76.15},
        ]
        results = []
        for s in stations:
            try:
                r = _requests.get(
                    'https://api.open-meteo.com/v1/forecast',
                    params={
                        'latitude': s['lat'],
                        'longitude': s['lon'],
                        'current': 'temperature_2m,precipitation,snowfall,weathercode,windspeed_10m',
                        'temperature_unit': 'fahrenheit',
                        'timezone': 'America/New_York',
                        'forecast_days': 1,
                    },
                    timeout=10,
                )
                data = r.json().get('current', {})
                code = data.get('weathercode', 0)
                results.append({
                    'name': s['name'],
                    'lat': s['lat'], 'lon': s['lon'],
                    'temp_f': data.get('temperature_2m'),
                    'precipitation_mm': data.get('precipitation'),
                    'snowfall_cm': data.get('snowfall'),
                    'wind_mph': data.get('windspeed_10m'),
                    'condition': _WMO_CODES.get(code, f'Code {code}'),
                    'weather_code': code,
                })
            except Exception as e:
                results.append({
                    'name': s['name'],
                    'lat': s['lat'], 'lon': s['lon'],
                    'error': str(e),
                })
        return results

    return cache.cached_query('map_weather', _fetch, ttl=900)
