"""Chatbot context — classify questions and fetch live operational data for LLM."""

import re as _re
import json as _json

import cache
from dispatch import get_live_queue, recommend_drivers, _driver_tier

from routers.chatbot_knowledge import CHATBOT_SYSTEM_BASE  # noqa: F401 — re-exported


def _classify_and_fetch_context(question: str) -> str:
    """Always inject cached operational data. Cache protects Salesforce — no keyword guessing needed."""
    # Lazy imports to avoid circular dependency with main.py
    from routers.command_center import command_center
    from routers.pta import pta_advisor
    from routers.misc import _lookup_sa_impl

    q = question.lower()
    context_parts = []

    try:
        # ── 1. Operations overview + garage performance (cached 2min) ──
        try:
            cc = cache.cached_query('command_center_24', lambda: command_center(24), ttl=120)
            if cc:
                s = cc.get('summary', {})
                overview = {
                    'total_calls_today': s.get('total_sas', 0),
                    'total_open': s.get('total_open', 0),
                    'total_completed': s.get('total_completed', 0),
                    'garages_good': s.get('good', 0),
                    'garages_behind': s.get('behind', 0),
                    'garages_critical': s.get('critical', 0),
                    'total_territories': s.get('total_territories', 0),
                }
                context_parts.append(f"=== Operations Overview (last 24h) ===\n{_json.dumps(overview, default=str, indent=1)}")

                if cc.get('territories'):
                    garage_summary = []
                    for t in cc['territories'][:25]:
                        garage_summary.append({
                            'name': t.get('name', ''),
                            'total_calls': t.get('total', 0),
                            'completed': t.get('completed', 0),
                            'canceled': t.get('canceled', 0),
                            'open': t.get('open', 0),
                            'completion_rate_pct': t.get('completion_rate'),
                            'sla_pct': t.get('sla_pct'),
                            'avg_response_min': t.get('avg_response'),
                            'avg_wait_min': t.get('avg_wait'),
                            'max_wait_min': t.get('max_wait'),
                            'status': t.get('status', ''),
                            'available_drivers': t.get('avail_drivers', 0),
                            'capacity': t.get('capacity'),
                        })
                    context_parts.append(f"=== Garage Performance (last 24h, top 25) ===\n{_json.dumps(garage_summary, default=str, indent=1)}")
        except Exception:
            pass

        # ── 2. Live dispatch queue (cached 30s) ──
        try:
            queue_data = get_live_queue()
            items = queue_data if isinstance(queue_data, list) else queue_data.get('queue', [])
            summary_data = queue_data.get('summary', {}) if isinstance(queue_data, dict) else {}
            queue_snapshot = {
                'total_open': summary_data.get('total_open', len(items)),
                'breached': summary_data.get('breached_count', 0),
                'avg_wait_min': summary_data.get('avg_wait', 0),
                'max_wait_min': summary_data.get('max_wait', 0),
                'calls': []
            }
            for sa in items[:20]:
                queue_snapshot['calls'].append({
                    'number': sa.get('number', ''),
                    'status': sa.get('status', ''),
                    'territory': sa.get('territory_name', ''),
                    'work_type': sa.get('work_type', ''),
                    'wait_min': sa.get('wait_min', ''),
                    'pta_promise_min': sa.get('pta_promise', ''),
                    'pta_breached': sa.get('pta_breached', False),
                    'dispatch_method': sa.get('dispatch_method', ''),
                    'urgency': sa.get('urgency', ''),
                    'address': sa.get('address', ''),
                    'escalation_suggestion': sa.get('escalation_suggestion'),
                })
            context_parts.append(f"=== Dispatch Queue (open calls) ===\n{_json.dumps(queue_snapshot, default=str, indent=1)}")
        except Exception:
            pass

        # ── 3. Active drivers snapshot (cached 3min) ──
        try:
            def _fetch_active_drivers():
                from ops import sf_query_all as _sq
                # On-shift drivers from Asset (vehicle login = on shift)
                trucks = _sq(
                    "SELECT ERS_Driver__c, Name, ERS_Truck_Capabilities__c"
                    " FROM Asset"
                    " WHERE RecordType.Name = 'ERS Truck'"
                    " AND ERS_Driver__c != null"
                )
                logged_in = {}
                for t in trucks:
                    dr_id = t.get('ERS_Driver__c')
                    if dr_id:
                        logged_in[dr_id] = {
                            'truck': t.get('Name', ''),
                            'caps': t.get('ERS_Truck_Capabilities__c', ''),
                        }
                if not logged_in:
                    return []
                # Get territory + name for on-shift drivers via STM
                rows = _sq(
                    "SELECT ServiceResourceId, ServiceResource.Name,"
                    " ServiceResource.ERS_Driver_Type__c,"
                    " ServiceTerritory.Name, TerritoryType"
                    " FROM ServiceTerritoryMember"
                    " WHERE TerritoryType IN ('P','S')"
                    " AND ServiceResource.IsActive = true"
                    " AND ServiceResource.ResourceType = 'T'"
                )
                drivers = {}
                for r in rows:
                    d_id = r.get('ServiceResourceId')
                    if d_id not in logged_in:
                        continue
                    sr = r.get('ServiceResource') or {}
                    name = sr.get('Name', '')
                    if not name or name.lower().startswith('towbook'):
                        continue
                    if name not in drivers:
                        truck_info = logged_in[d_id]
                        drivers[name] = {
                            'name': name,
                            'type': sr.get('ERS_Driver_Type__c', ''),
                            'territory': (r.get('ServiceTerritory') or {}).get('Name', ''),
                            'truck': truck_info['truck'],
                            'tier': _driver_tier(truck_info['caps']),
                        }
                return sorted(drivers.values(), key=lambda d: d['name'])

            active_drivers = cache.cached_query('chat_active_drivers', _fetch_active_drivers, ttl=180)
            if active_drivers:
                context_parts.append(f"=== Active Drivers (on-shift via vehicle login, fleet only) ===\nTotal on shift: {len(active_drivers)}\n{_json.dumps(active_drivers[:40], default=str, indent=1)}")
        except Exception:
            pass

        # ── 4. PTA Advisor snapshot (cached via pta_advisor endpoint) ──
        try:
            pta = cache.cached_query('pta_advisor_chat', lambda: pta_advisor(), ttl=180)
            if pta and pta.get('garages'):
                pta_summary = {
                    'total_queue': pta.get('totals', {}).get('total_queue', 0),
                    'total_drivers': pta.get('totals', {}).get('total_drivers', 0),
                    'total_idle': pta.get('totals', {}).get('total_idle', 0),
                    'garages': []
                }
                for g in pta['garages'][:20]:
                    pta_summary['garages'].append({
                        'name': g.get('name', ''),
                        'queue_depth': g.get('queue_depth', 0),
                        'drivers': g.get('drivers', 0),
                        'completed_today': g.get('completed_today', 0),
                        'avg_projected_pta_min': g.get('avg_projected_pta'),
                        'longest_wait_min': g.get('longest_wait'),
                    })
                context_parts.append(f"=== PTA Advisor (projected wait times) ===\n{_json.dumps(pta_summary, default=str, indent=1)}")
        except Exception:
            pass

        # ── 5. Dispatch method + dispatcher productivity (cached 3min) ──
        if any(w in q for w in ['dispatch', 'system', 'manual', 'auto', 'mulesoft', 'dispatcher', 'productive', 'who dispatch']):
            try:
                def _fetch_dispatch_stats():
                    from ops import sf_query_all as _sq
                    from datetime import datetime, timezone, timedelta
                    now_utc = datetime.now(timezone.utc)
                    start_utc = now_utc.replace(hour=5, minute=0, second=0, microsecond=0)
                    if now_utc < start_utc:
                        start_utc -= timedelta(days=1)
                    rows = _sq(
                        "SELECT Id, CreatedBy.Name"
                        " FROM AssignedResource"
                        f" WHERE CreatedDate >= {start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                    )
                    system_users = {'it system user', 'mulesoft integration', 'replicant integration user',
                                    'automated process', 'integration user', 'mulesoft user'}
                    system_count = 0
                    human_counts = {}
                    for r in rows:
                        cb = (r.get('CreatedBy') or {}).get('Name', 'Unknown')
                        if cb.lower().strip() in system_users:
                            system_count += 1
                        else:
                            human_counts[cb] = human_counts.get(cb, 0) + 1
                    total = system_count + sum(human_counts.values())
                    top_dispatchers = sorted(human_counts.items(), key=lambda x: -x[1])[:15]
                    return {
                        'total_dispatches': total,
                        'system_auto': system_count,
                        'system_pct': round(system_count / total * 100, 1) if total else 0,
                        'human_manual': sum(human_counts.values()),
                        'human_pct': round(sum(human_counts.values()) / total * 100, 1) if total else 0,
                        'top_dispatchers': [{'name': n, 'dispatches': c} for n, c in top_dispatchers],
                    }
                dispatch_stats = cache.cached_query('chat_dispatch_stats', _fetch_dispatch_stats, ttl=180)
                if dispatch_stats:
                    context_parts.append(f"=== Dispatch Method Breakdown (today) ===\n{_json.dumps(dispatch_stats, default=str, indent=1)}")
            except Exception:
                pass

        # ── 6. Decline analysis / wasted time (cached 3min) ──
        if any(w in q for w in ['decline', 'reject', 'waste', 'accept', 'cascade', 'refuse']):
            try:
                def _fetch_decline_stats():
                    from ops import sf_query_all as _sq
                    from datetime import datetime, timezone, timedelta
                    now_utc = datetime.now(timezone.utc)
                    start_utc = now_utc.replace(hour=5, minute=0, second=0, microsecond=0)
                    if now_utc < start_utc:
                        start_utc -= timedelta(days=1)
                    rows = _sq(
                        "SELECT Id, ServiceTerritory.Name, ERS_Facility_Decline_Reason__c,"
                        " CreatedDate, SchedStartTime"
                        " FROM ServiceAppointment"
                        f" WHERE CreatedDate >= {start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                        " AND ERS_Facility_Decline_Reason__c != null"
                    )
                    total_sa = _sq(
                        "SELECT COUNT(Id) cnt FROM ServiceAppointment"
                        f" WHERE CreatedDate >= {start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                    )
                    total_count = (total_sa[0].get('cnt', 0) if total_sa else 0)
                    reason_counts = {}
                    garage_declines = {}
                    for r in rows:
                        reason = r.get('ERS_Facility_Decline_Reason__c', 'Unknown')
                        reason_counts[reason] = reason_counts.get(reason, 0) + 1
                        g = (r.get('ServiceTerritory') or {}).get('Name', 'Unknown')
                        garage_declines[g] = garage_declines.get(g, 0) + 1
                    decline_count = len(rows)
                    return {
                        'total_declines': decline_count,
                        'total_sas_today': total_count,
                        'decline_rate_pct': round(decline_count / total_count * 100, 1) if total_count else 0,
                        'est_wasted_time_min': decline_count * 18,
                        'est_wasted_time_note': 'Estimated ~18 min wasted per decline (re-dispatch + cascade delay)',
                        'by_reason': dict(sorted(reason_counts.items(), key=lambda x: -x[1])[:10]),
                        'by_garage': dict(sorted(garage_declines.items(), key=lambda x: -x[1])[:10]),
                    }
                decline_stats = cache.cached_query('chat_decline_stats', _fetch_decline_stats, ttl=180)
                if decline_stats:
                    context_parts.append(f"=== Decline / Wasted Time Analysis (today) ===\n{_json.dumps(decline_stats, default=str, indent=1)}")
            except Exception:
                pass

        # ── 7. SLA achievement breakdown (cached 3min) ──
        if any(w in q for w in ['sla', '45 min', '45-min', 'goal', 'target', 'achievement', 'on time', 'on-time']):
            try:
                def _fetch_sla_breakdown():
                    from ops import sf_query_all as _sq
                    from datetime import datetime, timezone, timedelta
                    now_utc = datetime.now(timezone.utc)
                    start_utc = now_utc.replace(hour=5, minute=0, second=0, microsecond=0)
                    if now_utc < start_utc:
                        start_utc -= timedelta(days=1)
                    rows = _sq(
                        "SELECT Id, ServiceTerritory.Name, ActualStartTime, CreatedDate,"
                        " WorkType.Name, ERS_PTA__c"
                        " FROM ServiceAppointment"
                        f" WHERE CreatedDate >= {start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                        " AND Status = 'Completed'"
                        " AND ActualStartTime != null"
                    )
                    under_45 = 0
                    b45_90 = 0
                    b90_120 = 0
                    over_120 = 0
                    by_worktype = {}
                    pta_met = 0
                    pta_total = 0
                    for r in rows:
                        wt = (r.get('WorkType') or {}).get('Name', 'Unknown')
                        if 'drop' in wt.lower():
                            continue
                        try:
                            ast = datetime.fromisoformat(r['ActualStartTime'].replace('Z', '+00:00'))
                            cd = datetime.fromisoformat(r['CreatedDate'].replace('Z', '+00:00'))
                            ata = (ast - cd).total_seconds() / 60
                        except Exception:
                            continue
                        if ata <= 0 or ata >= 480:
                            continue
                        if ata <= 45:
                            under_45 += 1
                        elif ata <= 90:
                            b45_90 += 1
                        elif ata <= 120:
                            b90_120 += 1
                        else:
                            over_120 += 1
                        if wt not in by_worktype:
                            by_worktype[wt] = {'under_45': 0, 'total': 0}
                        by_worktype[wt]['total'] += 1
                        if ata <= 45:
                            by_worktype[wt]['under_45'] += 1
                        pta = r.get('ERS_PTA__c')
                        if pta and 0 < pta < 999:
                            pta_total += 1
                            if ata <= pta:
                                pta_met += 1
                    total_valid = under_45 + b45_90 + b90_120 + over_120
                    wt_summary = {}
                    for wt, d in by_worktype.items():
                        wt_summary[wt] = {
                            'sla_pct': round(d['under_45'] / d['total'] * 100, 1) if d['total'] else 0,
                            'total': d['total'],
                        }
                    return {
                        'total_completed_with_ata': total_valid,
                        'under_45_min': under_45,
                        'sla_hit_rate_pct': round(under_45 / total_valid * 100, 1) if total_valid else 0,
                        'buckets': {
                            'under_45': under_45,
                            '45_to_90': b45_90,
                            '90_to_120': b90_120,
                            'over_120': over_120,
                        },
                        'pta_accuracy_pct': round(pta_met / pta_total * 100, 1) if pta_total else 0,
                        'pta_evaluated': pta_total,
                        'by_work_type': dict(sorted(wt_summary.items(), key=lambda x: -x[1]['total'])[:10]),
                    }
                sla_stats = cache.cached_query('chat_sla_breakdown', _fetch_sla_breakdown, ttl=180)
                if sla_stats:
                    context_parts.append(f"=== SLA Achievement Breakdown (today) ===\n{_json.dumps(sla_stats, default=str, indent=1)}")
            except Exception:
                pass

        # ── 8. SA-specific lookup — match "SA-717120" or bare 6-8 digit number ──
        sa_match = _re.search(r'\b(?:SA-)?(\d{6,8})\b', q, _re.IGNORECASE)
        if sa_match:
            sa_num = f'SA-{sa_match.group(1)}'
            try:
                data = cache.cached_query(f'sa_lookup_{sa_num}', lambda: _lookup_sa_impl(sa_num), ttl=30)
                if data:
                    safe = {k: v for k, v in data.items()
                            if k not in ('member_name', 'member_phone', 'member_email', 'contact_name', 'contact_phone')}
                    context_parts.append(f"=== SA {sa_num} Detail ===\n{_json.dumps(safe, default=str, indent=1)}")
                    # Driver recommendations if asking about assignment
                    if any(w in q for w in ['driver', 'closest', 'fastest', 'who', 'recommend', 'assign', 'send', 'near', 'eta', 'available']):
                        sa_id = data.get('sa', {}).get('id')
                        if sa_id:
                            try:
                                recs = recommend_drivers(sa_id)
                                if recs and 'recommendations' in recs:
                                    rec_summary = [{'rank': i+1, 'driver': r.get('driver_name',''), 'type': r.get('driver_type',''),
                                                    'eta_min': r.get('eta_min'), 'distance_mi': round(r.get('distance_mi',0),1) if r.get('distance_mi') else None,
                                                    'skill_match': r.get('skill_match',''), 'active_jobs': r.get('active_jobs',0)}
                                                   for i, r in enumerate(recs['recommendations'][:5])]
                                    context_parts.append(f"=== Driver Recommendations for SA {sa_num} ===\n{_json.dumps({'top_drivers': rec_summary, 'scoring': 'ETA 40%, Skill 25%, Workload 20%, Shift 15%'}, default=str, indent=1)}")
                            except Exception:
                                pass
            except Exception:
                pass

    except Exception:
        pass

    return "\n\n".join(context_parts)


def _sanitize_response(answer: str) -> str:
    """Strip any PII or sensitive info the LLM might have leaked."""
    # Remove email addresses
    _email_rx = _re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    answer = _email_rx.sub('[email removed]', answer)
    # Remove anything that looks like an API key
    answer = _re.sub(r'(sk-[a-zA-Z0-9]{20,})', '[key removed]', answer)
    answer = _re.sub(r'(Bearer\s+[a-zA-Z0-9._-]{20,})', '[token removed]', answer)
    # Remove file paths
    answer = _re.sub(r'(/[a-zA-Z0-9._-]+){3,}\.py', '[path removed]', answer)
    return answer
