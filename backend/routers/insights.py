"""AI Insights endpoint -- LLM-powered and rule-based operational insights."""

import os
import json as _json
import logging
import re as _re
from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import requests as _requests

from sf_client import sf_query_all, sf_parallel
from utils import _ET, is_fleet_territory
import cache

router = APIRouter()


# ── Settings ──────────────────────────────────────────────────────────────────


def _load_settings():
    try:
        import database
        return database.get_all_settings()
    except Exception:
        return {}


# ── LLM Caller ───────────────────────────────────────────────────────────────

def _call_llm_insights(messages: list) -> tuple:
    """Call configured LLM with primary/fallback. Returns (text, model_used) or (None, None)."""
    settings = _load_settings()
    cb = settings.get('chatbot', {})
    if not cb.get('enabled') or not cb.get('api_key'):
        return None, None
    provider = cb.get('provider', '')
    api_key = cb['api_key']
    primary = cb.get('primary_model', '')
    fallback = cb.get('fallback_model', '')

    def _call(model_id):
        if provider == "openai":
            resp = _requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model_id, "messages": messages, "max_tokens": 4096, "temperature": 0.3},
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        elif provider == "anthropic":
            system_msg = ""
            user_msgs = []
            for m in messages:
                if m["role"] == "system":
                    system_msg = m["content"]
                else:
                    user_msgs.append(m)
            resp = _requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                json={"model": model_id, "max_tokens": 4096, "system": system_msg, "messages": user_msgs},
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]
        elif provider == "google":
            system_text = ""
            parts = []
            for m in messages:
                if m["role"] == "system":
                    system_text = m["content"]
                else:
                    role = "user" if m["role"] == "user" else "model"
                    parts.append({"role": role, "parts": [{"text": m["content"]}]})
            body = {"contents": parts}
            if system_text:
                body["systemInstruction"] = {"parts": [{"text": system_text}]}
            body["generationConfig"] = {"maxOutputTokens": 4096, "temperature": 0.3}
            resp = _requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}",
                headers={"Content-Type": "application/json"},
                json=body,
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            return None

    try:
        return _call(primary), primary
    except Exception:
        if fallback and fallback != primary:
            try:
                return _call(fallback), fallback
            except Exception:
                pass
    return None, None


def _parse_llm_json(text: str):
    """Extract and parse JSON from LLM response, tolerating markdown fences."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return _json.loads(cleaned)
    except Exception:
        return None


# ── Data Gatherers ────────────────────────────────────────────────────────────

def _insights_garage_data():
    """Gather and aggregate 7-day garage performance data."""
    now_utc = datetime.now(timezone.utc)
    seven_ago = (now_utc - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')

    data = sf_parallel(
        appts=lambda: sf_query_all(f"""
            SELECT ServiceTerritory.Name, ServiceTerritoryId,
                   Status, ERS_Dispatch_Method__c,
                   CreatedDate, ActualStartTime
            FROM ServiceAppointment
            WHERE CreatedDate >= {seven_ago}
              AND ServiceTerritoryId != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        declines=lambda: sf_query_all(f"""
            SELECT ServiceTerritory.Name, ERS_Facility_Decline_Reason__c, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {seven_ago}
              AND ERS_Facility_Decline_Reason__c != null
              AND ServiceTerritoryId != null
            GROUP BY ServiceTerritory.Name, ERS_Facility_Decline_Reason__c
        """),
        csat=lambda: sf_query_all(f"""
            SELECT ERS_Work_Order__r.ServiceTerritory.Name,
                   ERS_Overall_Satisfaction__c, COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE ERS_Work_Order__r.CreatedDate >= {seven_ago}
              AND ERS_Overall_Satisfaction__c != null
              AND ERS_Work_Order__r.ServiceTerritoryId != null
            GROUP BY ERS_Work_Order__r.ServiceTerritory.Name, ERS_Overall_Satisfaction__c
        """),
        drivers_stm=lambda: sf_query_all("""
            SELECT ServiceTerritoryId, ServiceResourceId
            FROM ServiceTerritoryMember
            WHERE TerritoryType IN ('P','S')
              AND ServiceResource.IsActive = true
              AND ServiceResource.ResourceType = 'T'
        """),
        trucks=lambda: sf_query_all("""
            SELECT ERS_Driver__c
            FROM Asset
            WHERE RecordType.Name = 'ERS Truck'
              AND ERS_Driver__c != null
        """),
    )

    # Build per-garage stats
    garages = {}
    for r in data.get('appts', []):
        name = (r.get('ServiceTerritory') or {}).get('Name', 'Unknown')
        tid = r.get('ServiceTerritoryId', '')
        g = garages.setdefault(tid, {
            'name': name, 'total': 0, 'completed': 0,
            'ata_sum': 0, 'ata_count': 0, 'fleet': 0, 'towbook': 0,
        })
        g['total'] += 1
        if r.get('Status') == 'Completed':
            g['completed'] += 1
        method = (r.get('ERS_Dispatch_Method__c') or '').lower()
        if 'field services' in method:
            g['fleet'] += 1
        elif 'towbook' in method:
            g['towbook'] += 1
        # ATA: only use ActualStartTime for Fleet SAs (Towbook ActualStartTime is bulk-updated at midnight)
        created = r.get('CreatedDate')
        actual = r.get('ActualStartTime')
        if created and actual and 'towbook' not in method:
            try:
                c = datetime.fromisoformat(created.replace('Z', '+00:00'))
                a = datetime.fromisoformat(actual.replace('Z', '+00:00'))
                ata_min = (a - c).total_seconds() / 60
                if 0 < ata_min < 480:
                    g['ata_sum'] += ata_min
                    g['ata_count'] += 1
            except Exception:
                pass

    # Decline counts
    decline_map = defaultdict(lambda: defaultdict(int))
    for r in data.get('declines', []):
        name = (r.get('ServiceTerritory') or {}).get('Name', 'Unknown')
        reason = r.get('ERS_Facility_Decline_Reason__c', 'Unknown')
        decline_map[name][reason] += r.get('cnt', 0)

    # CSAT -- compute % "Totally Satisfied" per garage
    csat_raw = defaultdict(lambda: {'satisfied': 0, 'total': 0})
    for r in data.get('csat', []):
        wo = r.get('ERS_Work_Order__r') or {}
        st = wo.get('ServiceTerritory') or {}
        name = st.get('Name', 'Unknown')
        cnt = r.get('cnt', 0)
        sat_val = (r.get('ERS_Overall_Satisfaction__c', '') or '').lower().strip()
        csat_raw[name]['total'] += cnt
        if sat_val == 'totally satisfied':
            csat_raw[name]['satisfied'] += cnt
    csat_map = {}
    for name, vals in csat_raw.items():
        pct = round(100 * vals['satisfied'] / max(vals['total'], 1), 1)
        csat_map[name] = {'avg': pct, 'count': vals['total']}

    # Driver counts -- on-shift only (Asset vehicle login intersected with STM territory)
    logged_in_set = {t.get('ERS_Driver__c') for t in data.get('trucks', []) if t.get('ERS_Driver__c')}
    driver_map = defaultdict(int)
    for r in data.get('drivers_stm', []):
        d_id = r.get('ServiceResourceId')
        tid_d = r.get('ServiceTerritoryId')
        if d_id and tid_d and d_id in logged_in_set:
            driver_map[tid_d] += 1

    # Assemble final list
    result = []
    for tid, g in garages.items():
        name = g['name']
        total = g['total']
        completed = g['completed']
        comp_rate = round(100 * completed / max(total, 1), 1)
        avg_ata = round(g['ata_sum'] / max(g['ata_count'], 1), 1)
        decl = decline_map.get(name, {})
        decline_total = sum(decl.values())
        decline_rate = round(100 * decline_total / max(total, 1), 1)
        top_reasons = sorted(decl.items(), key=lambda x: -x[1])[:3]
        csat = csat_map.get(name, {})
        drivers = driver_map.get(tid, 0)
        fleet_pct = round(100 * g['fleet'] / max(total, 1), 1)
        towbook_pct = round(100 * g['towbook'] / max(total, 1), 1)

        # Fleet = territory 100*/800*. Everything else = contractor.
        is_contractor = not is_fleet_territory(name)
        # For contractors, driver_count from STM is meaningless (just a placeholder)
        effective_drivers = drivers if not is_contractor else None

        # Problem score: higher = worse
        score = 0
        score += max(0, 80 - comp_rate) * 2          # low completion
        score += decline_rate * 1.5                    # high decline
        score += max(0, avg_ata - 40) * 0.5           # slow ATA
        score += max(0, 70 - csat.get('avg', 80)) * 0.5  # low CSAT (% scale)
        # Only penalize staffing for fleet territories (we can't see contractor staffing)
        if not is_contractor and drivers < 3 and total > 10:
            score += 30                                # understaffed

        result.append({
            'garage': name,
            'total_calls': total,
            'completed': completed,
            'completion_rate': comp_rate,
            'avg_ata_min': avg_ata,
            'decline_count': decline_total,
            'decline_rate': decline_rate,
            'top_decline_reasons': [f"{r}: {c}" for r, c in top_reasons],
            'csat_avg': round(csat.get('avg', 0), 2),
            'csat_responses': csat.get('count', 0),
            'driver_count': effective_drivers,
            'fleet_pct': fleet_pct,
            'towbook_pct': towbook_pct,
            'is_contractor': is_contractor,
            'problem_score': round(score, 1),
        })

    # Filter out non-garage territories:
    code_only_pat = _re.compile(r'^(WM|CR|RM|CL)\d{2,3}$')
    result = [
        g for g in result
        if not g['garage'].startswith('000-')
        and 'SPOT' not in g['garage'].upper()
        and 'LOCKSMITH' not in g['garage'].upper()
        and 'Office' not in g['garage']
        and not code_only_pat.match(g['garage'].strip())
        and g['total_calls'] >= 10
    ]
    result.sort(key=lambda x: -x['problem_score'])
    return result


def _insights_driver_data():
    """Gather and aggregate 7-day driver performance data."""
    now_utc = datetime.now(timezone.utc)
    seven_ago = (now_utc - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')

    data = sf_parallel(
        assigned=lambda: sf_query_all(f"""
            SELECT ServiceResource.Name, ServiceResourceId,
                   ServiceResource.ERS_Driver_Type__c,
                   ServiceResource.LastKnownLatitude,
                   ServiceResource.LastKnownLocationDate,
                   ServiceAppointment.Status,
                   ServiceAppointment.CreatedDate,
                   ServiceAppointment.ActualStartTime,
                   ServiceAppointment.ERS_Dispatch_Method__c,
                   ServiceAppointment.ServiceTerritory.Name
            FROM AssignedResource
            WHERE ServiceAppointment.CreatedDate >= {seven_ago}
              AND ServiceAppointment.WorkType.Name != 'Tow Drop-Off'
              AND ServiceResource.IsActive = true
              AND ServiceResource.ResourceType = 'T'
        """),
        fleet_gps=lambda: sf_query_all("""
            SELECT Id, Name, LastKnownLatitude, LastKnownLocationDate, ERS_Driver_Type__c
            FROM ServiceResource
            WHERE IsActive = true AND ResourceType = 'T'
              AND ERS_Driver_Type__c = 'Fleet Driver'
        """),
    )

    drivers = {}
    for r in data.get('assigned', []):
        sr = r.get('ServiceResource') or {}
        sr_id = r.get('ServiceResourceId', '')
        sa = r.get('ServiceAppointment') or {}
        st = sa.get('ServiceTerritory') or {}
        d = drivers.setdefault(sr_id, {
            'name': sr.get('Name', 'Unknown'),
            'type': sr.get('ERS_Driver_Type__c', 'Unknown'),
            'total': 0, 'completed': 0, 'ata_sum': 0, 'ata_count': 0,
            'over_60': 0, 'no_show': 0,
            'gps_lat': sr.get('LastKnownLatitude'),
            'gps_date': sr.get('LastKnownLocationDate'),
            'territory': st.get('Name', 'Unknown'),
        })
        d['total'] += 1
        status = sa.get('Status', '')
        if status == 'Completed':
            d['completed'] += 1
        if status in ('Cannot Complete', 'Customer Cancel'):
            d['no_show'] += 1
        created = sa.get('CreatedDate')
        actual = sa.get('ActualStartTime')
        dispatch_method = (sa.get('ERS_Dispatch_Method__c') or '').lower()
        # Only use ActualStartTime for Fleet SAs (Towbook ActualStartTime is fake midnight bulk-update)
        if created and actual and 'towbook' not in dispatch_method:
            try:
                c = datetime.fromisoformat(created.replace('Z', '+00:00'))
                a = datetime.fromisoformat(actual.replace('Z', '+00:00'))
                ata_min = (a - c).total_seconds() / 60
                if 0 < ata_min < 480:
                    d['ata_sum'] += ata_min
                    d['ata_count'] += 1
                    if ata_min > 60:
                        d['over_60'] += 1
            except Exception:
                pass

    # GPS stale check for fleet
    fleet_gps = {}
    for r in data.get('fleet_gps', []):
        fleet_gps[r.get('Id', '')] = r.get('LastKnownLocationDate')

    now_utc = datetime.now(timezone.utc)
    result = []
    for sr_id, d in drivers.items():
        total = d['total']
        completed = d['completed']
        comp_rate = round(100 * completed / max(total, 1), 1)
        avg_ata = round(d['ata_sum'] / max(d['ata_count'], 1), 1)

        gps_age_hours = None
        gps_date_str = fleet_gps.get(sr_id) or d.get('gps_date')
        if gps_date_str and d['type'] == 'Fleet Driver':
            try:
                gps_dt = datetime.fromisoformat(gps_date_str.replace('Z', '+00:00'))
                gps_age_hours = round((now_utc - gps_dt).total_seconds() / 3600, 1)
            except Exception:
                pass

        # Flag calculation
        flags = []
        if avg_ata > 50:
            flags.append('high_ata')
        if comp_rate < 70:
            flags.append('low_completion')
        if gps_age_hours is not None and gps_age_hours > 24:
            flags.append('gps_stale')
        if d['no_show'] > 2:
            flags.append('high_no_show')

        problem_score = 0
        problem_score += max(0, avg_ata - 40) * 0.5
        problem_score += max(0, 80 - comp_rate) * 1.5
        if gps_age_hours and gps_age_hours > 24:
            problem_score += 20
        problem_score += d['no_show'] * 5

        result.append({
            'driver': d['name'],
            'type': d['type'],
            'territory': d['territory'],
            'total_calls': total,
            'completed': completed,
            'completion_rate': comp_rate,
            'avg_ata_min': avg_ata,
            'calls_over_60min': d['over_60'],
            'no_show_count': d['no_show'],
            'gps_age_hours': gps_age_hours,
            'flags': flags,
            'problem_score': round(problem_score, 1),
        })

    # Filter: fleet drivers only, exclude placeholder/test/office resources, min 3 calls
    _exclude_prefixes = ('000-', '0 ', '100a ', 'test ', 'towbook')
    result = [
        d for d in result
        if d['type'] == 'Fleet Driver'
        and not any(d['driver'].lower().startswith(p) for p in _exclude_prefixes)
        and 'SPOT' not in d['driver'].upper()
        and d['driver'] != 'Travel User'
        and d['total_calls'] >= 3
    ]
    result.sort(key=lambda x: -x['problem_score'])
    return result


def _insights_dispatch_data():
    """Gather 7-day dispatch/system-level data."""
    now_utc = datetime.now(timezone.utc)
    seven_ago = (now_utc - timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ')

    data = sf_parallel(
        raw=lambda: sf_query_all(f"""
            SELECT ERS_Spotting_Number__c, ERS_Dispatch_Method__c, Status,
                   WorkType.Name
            FROM ServiceAppointment
            WHERE CreatedDate >= {seven_ago}
              AND ServiceTerritoryId != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        worktype=lambda: sf_query_all(f"""
            SELECT WorkType.Name, COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {seven_ago}
              AND ServiceTerritoryId != null
              AND WorkType.Name != 'Tow Drop-Off'
            GROUP BY WorkType.Name
        """),
    )

    # Aggregate cascade depth in Python (field not groupable in SOQL)
    cascade_counts = defaultdict(int)
    method_stats = defaultdict(lambda: {'total': 0, 'completed': 0})
    for r in data.get('raw', []):
        spot = r.get('ERS_Spotting_Number__c')
        cascade_counts[spot] += 1
        method = r.get('ERS_Dispatch_Method__c') or 'Unknown'
        method_stats[method]['total'] += 1
        if r.get('Status') == 'Completed':
            method_stats[method]['completed'] += 1

    cascade = [{'spotting_number': k, 'count': v} for k, v in cascade_counts.items()]
    cascade.sort(key=lambda x: x.get('spotting_number') or 999)

    # Work type distribution
    wt_stats = {}
    for r in data.get('worktype', []):
        wt = (r.get('WorkType') or {}).get('Name', 'Unknown')
        wt_stats[wt] = {'count': r.get('cnt', 0)}

    methods_out = []
    for method, s in method_stats.items():
        methods_out.append({
            'method': method,
            'total': s['total'],
            'completed': s['completed'],
            'completion_rate': round(100 * s['completed'] / max(s['total'], 1), 1),
        })
    methods_out.sort(key=lambda x: -x['total'])

    total_calls = sum(m['total'] for m in methods_out)
    total_completed = sum(m['completed'] for m in methods_out)
    cascade_total = sum(c['count'] for c in cascade)
    # Cascade rate = % of calls that went through 3+ spotting rounds (real re-dispatches)
    spot_3plus = sum(c['count'] for c in cascade
                     if isinstance(c.get('spotting_number'), (int, float)) and c['spotting_number'] >= 3)
    cascade_rate = round(100 * spot_3plus / max(cascade_total, 1), 1)

    return {
        'total_calls': total_calls,
        'total_completed': total_completed,
        'overall_completion_rate': round(100 * total_completed / max(total_calls, 1), 1),
        'cascade_rate': cascade_rate,
        'cascade_depth': cascade,
        'work_types': [{'type': k, **v} for k, v in sorted(wt_stats.items(), key=lambda x: -x[1]['count'])],
        'dispatch_methods': methods_out,
    }

# NOTE: /api/insights/{category} endpoint moved to routers/insights_health.py
