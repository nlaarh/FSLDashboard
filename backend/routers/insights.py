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

_SETTINGS_FILE = os.path.expanduser('~/.fslapp/settings.json')

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


# ── Rule-Based Recommendation Generators ──────────────────────────────────────

_INSIGHT_PROMPTS = {
    'garage': """You are an FSL operations analyst for AAA roadside assistance. Analyze the garage performance data and return a JSON array of the top 15 garages that need improvement. For each garage, provide specific, actionable recommendations based on the data.

Return ONLY valid JSON (no markdown, no code fences):
[
  {
    "garage": "Garage Name",
    "severity": "critical" | "warning" | "monitor",
    "issues": ["issue1", "issue2"],
    "recommendations": ["specific action 1", "specific action 2"],
    "impact": "expected improvement description"
  }
]

Focus on: coverage gaps (too few drivers for call volume), high decline rates (garages refusing calls), slow response times, poor customer satisfaction, fleet vs contractor imbalance. Be specific with numbers from the data.""",

    'driver': """You are an FSL operations analyst for AAA roadside assistance. Analyze the driver performance data and return a JSON array of the top 15 drivers that need attention. For each driver, provide specific, actionable recommendations.

Return ONLY valid JSON (no markdown, no code fences):
[
  {
    "driver": "Driver Name",
    "type": "Fleet Driver" | "Contractor",
    "severity": "critical" | "warning" | "monitor",
    "issues": ["issue1", "issue2"],
    "recommendations": ["specific action 1", "specific action 2"],
    "impact": "expected improvement description"
  }
]

Focus on: high ATA (slow response), low completion rate, stale GPS (fleet drivers not transmitting location), high no-show/cancel rate. Be specific with numbers from the data.""",

    'dispatch': """You are an FSL operations analyst for AAA roadside assistance. Analyze the dispatch system data and return a JSON object with system-level recommendations.

Return ONLY valid JSON (no markdown, no code fences):
{
  "system_health": "good" | "warning" | "critical",
  "kpis": {
    "overall_completion_rate": number,
    "cascade_rate": number,
    "total_volume": number
  },
  "findings": [
    {
      "area": "area name",
      "severity": "critical" | "warning" | "monitor",
      "finding": "description of what the data shows",
      "recommendation": "specific action to take",
      "impact": "expected improvement"
    }
  ]
}

Focus on: cascade efficiency (too many re-dispatches), auto vs manual dispatch balance, work type patterns, completion rate by dispatch method. Be specific with numbers.""",
}


def _rulebased_garage(garage_data):
    """Generate 360-degree rule-based recommendations from garage data -- prioritize high-volume."""
    recs = []
    # Sort by volume first, then by problem score, to prioritize impactful garages
    sorted_data = sorted(garage_data, key=lambda g: (-g['total_calls'], -g['problem_score']))

    for g in sorted_data[:25]:
        issues = []
        actions = []
        severity = 'monitor'
        name = g['garage']
        vol = g['total_calls']
        comp = g['completion_rate']
        ata = g['avg_ata_min']
        decl_rate = g['decline_rate']
        decl_count = g['decline_count']
        csat = g['csat_avg']
        csat_n = g['csat_responses']
        drivers = g['driver_count']  # None for contractors
        fleet_pct = g['fleet_pct']
        is_contractor = g.get('is_contractor', False)

        # -- Completion Rate --
        if comp < 60:
            incomplete = vol - g['completed']
            issues.append(f"Critical completion: {comp}% -- {incomplete} calls failed in 7 days")
            severity = 'critical'
        elif comp < 80:
            incomplete = vol - g['completed']
            issues.append(f"Below-target completion: {comp}% ({incomplete} incomplete of {vol} calls)")
            severity = 'warning'

        # -- Decline Rate --
        if decl_rate > 30:
            reasons = ', '.join(g['top_decline_reasons'][:2]) if g['top_decline_reasons'] else 'unknown'
            issues.append(f"High decline rate: {decl_rate}% ({decl_count} declines). Top reasons: {reasons}")
            severity = 'critical'
        elif decl_rate > 15:
            issues.append(f"Elevated declines: {decl_rate}% ({decl_count} declines this week)")
            if severity != 'critical':
                severity = 'warning'

        # -- ATA (only if we have data) --
        if ata > 55:
            issues.append(f"Slow ATA: {ata} min average (target: <45 min)")
            if severity != 'critical':
                severity = 'warning'
        elif ata > 45 and ata > 0:
            issues.append(f"ATA approaching target: {ata} min (target: <45 min)")

        # -- CSAT --
        if csat > 0 and csat < 60:
            issues.append(f"Low satisfaction: only {csat}% 'Totally Satisfied' ({csat_n} surveys)")
            if severity != 'critical':
                severity = 'warning'

        # -- Staffing (FLEET ONLY -- contractor driver counts in SF are just placeholders) --
        if not is_contractor and drivers is not None:
            if drivers < 3 and vol > 20:
                issues.append(f"Understaffed: only {drivers} drivers handling {vol} calls/week")
                if severity != 'critical':
                    severity = 'warning'
            elif drivers > 0 and vol / drivers > 25:
                issues.append(f"High load: {round(vol/drivers)} calls/driver/week ({drivers} drivers)")

        if not issues:
            continue  # Only show garages with real, actionable problems

        # -- Generate paragraph recommendations (context-aware for contractor vs fleet) --
        if comp < 80:
            recoverable = round(vol * (80 - comp) / 100)
            if is_contractor:
                actions.append(
                    f"Completion is at {comp}% with {vol} weekly calls -- {recoverable} calls going incomplete. "
                    f"As a contractor garage, reach out to discuss capacity constraints. "
                    f"Are they declining certain work types? Are there time-of-day coverage gaps? "
                    f"Consider redistributing overflow to nearby garages."
                )
            else:
                actions.append(
                    f"Completion is at {comp}% with {vol} weekly calls -- {recoverable} calls going incomplete. "
                    f"Review driver availability during peak hours, work type coverage gaps, "
                    f"and whether territory boundaries match driver locations."
                )
        if decl_count > 5:
            reasons_str = ', '.join(g['top_decline_reasons'][:3]) if g['top_decline_reasons'] else 'unspecified'
            verb = 'Schedule a performance review with this contractor.' if is_contractor else 'Review dispatch rules and driver schedules.'
            actions.append(
                f"Declined {decl_count} calls ({decl_rate}%) last week. "
                f"Top reasons: {reasons_str}. {verb}"
            )
        if ata > 45:
            if is_contractor:
                actions.append(
                    f"Average response time is {ata} min. Discuss with contractor whether their "
                    f"driver positioning is optimal or if coverage area is too large for their capacity."
                )
            else:
                actions.append(
                    f"Average response time is {ata} min, above the 45-min target. "
                    f"Check driver pre-positioning and consider splitting the territory."
                )
        if csat > 0 and csat < 60:
            actions.append(
                f"Satisfaction is low at {csat}% ({csat_n} responses). "
                f"Review survey feedback -- common issues: communication gaps, long waits, professionalism."
            )
        if not is_contractor and drivers is not None and drivers < 3 and vol > 20:
            actions.append(
                f"Only {drivers} driver(s) for {vol} calls/week. "
                f"Add at least {max(1, 3 - drivers)} more or redistribute volume."
            )
        if not actions:
            actions.append(f"Performing well at {comp}% completion with {vol} calls/week. Continue monitoring.")

        # -- Impact --
        impact_parts = []
        if comp < 80:
            recoverable = round(vol * (80 - comp) / 100)
            impact_parts.append(f"~{recoverable} additional completed calls/week at 80% target")
        if decl_count > 5:
            impact_parts.append(f"{decl_count} fewer member delays from declined calls")
        if ata > 45:
            impact_parts.append(f"Faster response improves SLA and member retention")

        type_label = f"Contractor \u2022 {vol} calls/wk" if is_contractor else f"Fleet \u2022 {drivers or '?'} drivers \u2022 {vol} calls/wk"

        recs.append({
            'garage': name,
            'type': type_label,
            'severity': severity,
            'issues': issues,
            'recommendations': actions,
            'impact': '. '.join(impact_parts) if impact_parts else f"High-volume garage: {vol} calls/week -- improvements here have outsized impact",
        })
    return recs[:15]


def _rulebased_driver(driver_data):
    """Generate rule-based recommendations from fleet driver data."""
    recs = []
    for d in driver_data[:15]:
        if not d['flags']:
            continue
        issues = []
        actions = []
        severity = 'monitor'
        territory = d.get('territory', 'Unknown')

        if 'low_completion' in d['flags']:
            incomplete = d['total_calls'] - d['completed']
            issues.append(f"Low completion rate: {d['completion_rate']}% ({d['completed']}/{d['total_calls']} calls)")
            actions.append(f"Check why {incomplete} calls went incomplete -- cancellations, no-shows, or inability to service")
            severity = 'warning'
            if d['completion_rate'] < 50:
                severity = 'critical'
        if 'high_ata' in d['flags']:
            issues.append(f"Slow response: {d['avg_ata_min']} min avg ATA ({d.get('calls_over_60min', 0)} calls over 60 min)")
            actions.append(f"Review positioning in {territory} -- may need to pre-stage closer to high-demand zones")
            severity = 'warning'
        if 'gps_stale' in d['flags']:
            hrs = d['gps_age_hours']
            issues.append(f"GPS offline: last signal {hrs:.0f}h ago -- scheduler can't route calls to this driver accurately")
            actions.append("Verify FSL mobile app is running and location services are enabled on driver's device")
            severity = 'critical' if hrs and hrs > 72 else 'warning'
        if 'high_no_show' in d['flags']:
            issues.append(f"High no-show/cancel: {d['no_show_count']} in 7 days")
            actions.append("Review with driver -- frequent no-shows suggest scheduling conflicts or call acceptance issues")
            if d['no_show_count'] > 5:
                severity = 'critical'

        impact_parts = []
        if d.get('calls_over_60min', 0) > 0:
            impact_parts.append(f"Fixing ATA could bring {d['calls_over_60min']} calls under 60 min")
        if d['completion_rate'] < 80:
            recoverable = round(d['total_calls'] * (80 - d['completion_rate']) / 100)
            if recoverable > 0:
                impact_parts.append(f"Reaching 80% completion = ~{recoverable} more completed calls/week")

        recs.append({
            'driver': d['driver'],
            'type': d['type'],
            'severity': severity,
            'issues': issues,
            'recommendations': actions,
            'impact': '. '.join(impact_parts) if impact_parts else f"Driver handling {d['total_calls']} calls/week in {territory}",
        })
    return recs


def _rulebased_dispatch(dispatch_data):
    """Generate rule-based recommendations from dispatch data -- returns array matching card format."""
    recs = []
    total_calls = dispatch_data['total_calls']
    comp_rate = dispatch_data['overall_completion_rate']
    cascade_rate = dispatch_data['cascade_rate']

    # Overall completion analysis
    if comp_rate < 80:
        severity = 'critical' if comp_rate < 70 else 'warning'
        recs.append({
            'driver': f'System Completion Rate: {comp_rate}%',
            'type': 'System KPI',
            'severity': severity,
            'issues': [
                f"Overall completion at {comp_rate}% -- {'critically ' if comp_rate < 70 else ''}below 80% target",
                f"{total_calls} total calls in 7 days, {round(total_calls * comp_rate / 100)} completed",
            ],
            'recommendations': [
                "Focus on garages with highest decline/incomplete rates",
                "Review cascade patterns -- calls bouncing between garages add delay",
            ],
            'impact': f"Each 1% improvement = ~{round(total_calls * 0.01)} more completed calls/week",
        })

    # Cascade analysis
    if cascade_rate > 15:
        severity = 'critical' if cascade_rate > 30 else 'warning'
        cascade_depth = dispatch_data.get('cascade_depth', [])
        high_cascade = [c for c in cascade_depth if isinstance(c.get('spotting_number'), (int, float)) and c['spotting_number'] >= 3]
        high_count = sum(c['count'] for c in high_cascade)
        recs.append({
            'driver': f'Cascade Rate: {cascade_rate}%',
            'type': 'System KPI',
            'severity': severity,
            'issues': [
                f"{cascade_rate}% of calls require re-dispatch (spotting > 1)",
                f"{high_count} calls went through 3+ dispatches this week" if high_count else "Multiple re-dispatches adding member wait time",
            ],
            'recommendations': [
                "Improve initial territory-to-garage matching to reduce bouncing",
                "Check if garages are declining calls they should accept based on their coverage",
            ],
            'impact': f"Reducing cascades by 5% saves ~{round(total_calls * 0.05)} re-dispatches/week",
        })

    # Dispatch method breakdown
    for m in dispatch_data['dispatch_methods']:
        if m['total'] > 20 and m['completion_rate'] < 60:
            recs.append({
                'driver': f"Method: {m['method']}",
                'type': 'Dispatch Method',
                'severity': 'warning',
                'issues': [
                    f"{m['method']} has only {m['completion_rate']}% completion ({m['completed']}/{m['total']} calls)",
                ],
                'recommendations': [
                    f"Investigate why {m['method']} dispatches underperform vs other methods",
                ],
                'impact': f"Fixing could improve overall completion by ~{(80 - m['completion_rate']) * m['total'] / max(total_calls, 1):.1f}%",
            })

    # Work type analysis -- only named types with significant volume
    wt_list = dispatch_data.get('work_types', [])
    for wt in wt_list[:5]:
        wt_name = wt.get('type', '')
        if wt_name and wt_name != 'Unknown' and wt['count'] > 200:
            pct = round(100 * wt['count'] / max(total_calls, 1))
            recs.append({
                'driver': f"Work Type: {wt_name}",
                'type': 'Volume Analysis',
                'severity': 'info',
                'issues': [f"{wt['count']} calls this week ({pct}% of volume)"],
                'recommendations': [f"Ensure adequate staffing and skill coverage for {wt_name}"],
                'impact': f"Top work type -- even 1% improvement impacts ~{round(wt['count'] * 0.01)} calls/week",
            })

    if not recs:
        recs.append({
            'driver': 'System Health: Good',
            'type': 'System KPI',
            'severity': 'info',
            'issues': [f"System performing well: {comp_rate}% completion, {cascade_rate}% cascade rate, {total_calls} calls/week"],
            'recommendations': ["Continue monitoring -- no urgent actions needed"],
            'impact': "Maintain current performance levels",
        })

    return recs


# ── Main Endpoint ─────────────────────────────────────────────────────────────

@router.get("/api/insights/{category}")
def get_insights(category: str):
    """AI-powered operational insights with LLM analysis and rule-based fallback."""
    if category not in ('garage', 'driver', 'dispatch'):
        raise HTTPException(status_code=400, detail="Category must be one of: garage, driver, dispatch")

    cache_key = f"insights:{category}"

    def _fetch():
        log = logging.getLogger('insights')

        # Step 1: Gather data
        if category == 'garage':
            raw_data = _insights_garage_data()
            top_data = raw_data  # pass all -- rulebased_garage sorts by volume internally
            rulebased_fn = _rulebased_garage
        elif category == 'driver':
            raw_data = _insights_driver_data()
            top_data = raw_data[:20]
            rulebased_fn = _rulebased_driver
        else:
            raw_data = _insights_dispatch_data()
            top_data = raw_data
            rulebased_fn = _rulebased_dispatch

        # Step 2: Try LLM analysis -- send top data by volume for garages, otherwise top_data
        llm_data = sorted(top_data, key=lambda x: -x.get('total_calls', 0))[:25] if category == 'garage' else top_data
        system_prompt = _INSIGHT_PROMPTS[category]
        user_content = _json.dumps(llm_data, indent=2, default=str)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Here is the {category} performance data for the last 7 days:\n\n{user_content}"},
        ]

        llm_text, model_used = _call_llm_insights(messages)
        parsed = _parse_llm_json(llm_text)

        if parsed is not None:
            return {
                'source': 'ai',
                'model': model_used,
                'recommendations': parsed,
                'generated_at': datetime.now(_ET).isoformat(),
                'period': '7 days',
            }

        # Step 3: Fall back to rule-based
        if llm_text:
            log.warning(f"Insights/{category}: LLM returned unparseable JSON, falling back to rules")
        else:
            log.info(f"Insights/{category}: LLM unavailable, using rule-based analysis")

        rules_result = rulebased_fn(top_data if category != 'dispatch' else raw_data)
        return {
            'source': 'rules',
            'model': None,
            'recommendations': rules_result,
            'generated_at': datetime.now(_ET).isoformat(),
            'period': '7 days',
        }

    return cache.cached_query(cache_key, _fetch, ttl=21600)  # 6 hours
