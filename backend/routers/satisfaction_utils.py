"""Satisfaction shared utilities — insights, executive briefing, zone mapping, day assembly."""

from collections import defaultdict

import cache
from utils import parse_dt as _parse_dt
from routers.dispatch_shared import _is_real_garage  # noqa: F401 — re-exported


def _satisfaction_insights(sat_pct, avg_ata, pta_miss_pct, rt_sat_pct, volume):
    """Rule-based insights for satisfaction data. Returns list of insight dicts."""
    insights = []
    if volume is not None and volume < 5:
        insights.append({'type': 'caution', 'text': 'Small sample size — interpret with caution', 'icon': '⚠'})
        return insights  # Don't generate other insights on tiny samples
    if sat_pct is not None and sat_pct < 60:
        insights.append({'type': 'critical', 'text': f'Critical: {sat_pct}% satisfaction — investigate individual comments', 'icon': '🔴'})
    if avg_ata is not None and sat_pct is not None and avg_ata > 45 and sat_pct < 80:
        insights.append({'type': 'warning', 'text': f'High ATA ({avg_ata}m) likely driving low satisfaction ({sat_pct}%)', 'icon': '🕐'})
    if pta_miss_pct is not None and pta_miss_pct > 30 and sat_pct is not None and sat_pct < 80:
        insights.append({'type': 'warning', 'text': f'Broken promises damaging satisfaction — {pta_miss_pct}% PTA violations', 'icon': '💔'})
    if rt_sat_pct is not None and sat_pct is not None and rt_sat_pct < sat_pct - 10:
        insights.append({'type': 'info', 'text': f'Wait time is the pain point — response time satisfaction ({rt_sat_pct}%) trails overall ({sat_pct}%)', 'icon': '⏱'})
    elif rt_sat_pct is not None and sat_pct is not None and rt_sat_pct >= sat_pct and sat_pct < 75:
        insights.append({'type': 'info', 'text': 'Response time OK but overall low — issue may be technician quality or communication', 'icon': '🔧'})
    if sat_pct is not None and sat_pct >= 90:
        insights.append({'type': 'success', 'text': f'Excellent performance — {sat_pct}% totally satisfied', 'icon': '🌟'})
    return insights


def _get_previous_month_sat(current_month):
    """Get previous month's satisfaction % from disk cache (no extra SF query)."""
    import calendar
    year, mon = int(current_month[:4]), int(current_month[5:7])
    if mon == 1:
        prev_year, prev_mon = year - 1, 12
    else:
        prev_year, prev_mon = year, mon - 1
    prev_key = f'satisfaction_overview_{prev_year}-{prev_mon:02d}'
    prev_data = cache.disk_get_stale(prev_key)
    if prev_data and prev_data.get('summary', {}).get('totally_satisfied_pct') is not None:
        return {
            'totally_satisfied_pct': prev_data['summary']['totally_satisfied_pct'],
            'month_name': calendar.month_name[prev_mon],
        }
    return None


def _build_executive_insight(month, sat_pct, rt_pct, tech_pct, total_surveys,
                              avg_ata, pta_miss_pct, daily_trend, all_garages):
    """VP monthly briefing — 5-8 lines, bottom line up front.

    Not a data dump. A concise analysis: what happened, why, who's responsible, what to do.
    """
    import calendar
    from datetime import date as _date

    year, mon = int(month[:4]), int(month[5:7])
    month_name = calendar.month_name[mon]
    target = 82

    if sat_pct is None or total_surveys == 0:
        return {'headline': f'No satisfaction data for {month_name} {year}.', 'body': [], 'actions': []}

    # Classify garages
    bad_garages = sorted(
        [g for g in all_garages if g['totally_satisfied_pct'] is not None
         and g['totally_satisfied_pct'] < target and g['surveys'] >= 5],
        key=lambda g: g['totally_satisfied_pct']
    )
    good_count = sum(1 for g in all_garages
                     if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] >= target)
    total_garages = len([g for g in all_garages if g['surveys'] >= 2])

    # Diagnose: wait time vs driver quality
    if rt_pct is not None and tech_pct is not None:
        if rt_pct < target and tech_pct >= target:
            diagnosis = 'wait_time'
        elif tech_pct < target and rt_pct >= target:
            diagnosis = 'technician'
        elif rt_pct < target and tech_pct < target:
            diagnosis = 'both'
        else:
            diagnosis = 'on_target'
    else:
        diagnosis = None

    # Month-over-month
    prev_month_data = _get_previous_month_sat(month)
    prev_pct = prev_month_data.get('totally_satisfied_pct') if prev_month_data else None
    prev_name = prev_month_data.get('month_name', 'last month') if prev_month_data else None

    # Worst days
    bad_days = sorted(
        [d for d in daily_trend
         if d.get('totally_satisfied_pct') is not None and d['totally_satisfied_pct'] < target
         and d.get('surveys', 0) >= 10],
        key=lambda d: d['totally_satisfied_pct']
    )

    # ── Build the briefing (5-8 lines) ──
    body = []

    # Line 1: Headline with trend context
    if sat_pct >= target:
        trend_ctx = ''
        if prev_pct is not None:
            delta = sat_pct - prev_pct
            if delta > 0:
                trend_ctx = f', up {delta} from {prev_name}'
            elif delta < 0:
                trend_ctx = f', down {abs(delta)} from {prev_name}'
        risk = ''
        if diagnosis == 'wait_time':
            risk = ' Response time is the risk.'
        elif diagnosis == 'technician':
            risk = ' Driver quality is the risk.'
        body.append(f"On target at {sat_pct}%{trend_ctx}.{risk}")
    else:
        gap = target - sat_pct
        body.append(f"{gap} {'point' if gap == 1 else 'points'} below target at {sat_pct}%.")

    # Line 2: Root cause — one sentence
    if diagnosis == 'wait_time':
        body.append(f"Technician quality is strong ({tech_pct}%), but members are unhappy with wait times — Response Time satisfaction is only {rt_pct}%.")
    elif diagnosis == 'technician':
        body.append(f"Wait times are acceptable ({rt_pct}% RT satisfaction), but driver quality is the problem — Technician satisfaction is {tech_pct}%.")
    elif diagnosis == 'both':
        body.append(f"Both wait times ({rt_pct}% RT) and driver quality ({tech_pct}% Tech) are below target.")

    # Line 3: ATA + PTA — the operational evidence
    ata_pta_parts = []
    if avg_ata and avg_ata > 45:
        ata_pta_parts.append(f"average response was {avg_ata} minutes")
    if pta_miss_pct and pta_miss_pct > 15:
        ata_pta_parts.append(f"{pta_miss_pct}% of calls missed their promised arrival time")
    if ata_pta_parts:
        body.append(f"{' and '.join(ata_pta_parts).capitalize()} — these broken promises drive the most dissatisfied surveys.")

    # Line 4: Who's responsible — specific facilities
    if bad_garages:
        bottom = bad_garages[:3]
        garage_details = []
        for g in bottom:
            name = g['name'].split(' - ')[-1].strip() if ' - ' in g['name'] else g['name']
            garage_details.append(f"{name} ({g['totally_satisfied_pct']}%)")
        body.append(f"Three facilities account for most of the damage: {', '.join(garage_details)}. The remaining {good_count} garages are performing above target.")

    # Line 5: Worst days (brief)
    if bad_days:
        day_strs = []
        for d in bad_days[:3]:
            day_num = d['date'].split('-')[-1].lstrip('0')
            day_strs.append(f"{month_name} {day_num} ({d['totally_satisfied_pct']}%)")
        body.append(f"Worst days: {', '.join(day_strs)} — click any day above to see what went wrong.")

    # ── Actions (1-2 lines) ──
    actions = []
    if bad_garages:
        names = ', '.join(g['name'].split(' - ')[-1].strip() for g in bad_garages[:3])
        if diagnosis == 'wait_time':
            actions.append(f"Capacity review at {names} — are they taking more calls than they can handle?")
        elif diagnosis == 'technician':
            actions.append(f"Driver quality review at {names} — check customer comments for patterns.")
        else:
            actions.append(f"Review operations at {names}.")

    if pta_miss_pct and pta_miss_pct > 25:
        actions.append(f"PTA promises need recalibration — {pta_miss_pct}% miss rate means we're over-promising on arrival times.")

    if not actions:
        actions.append("On track. Monitor response times to maintain margin above 82%.")

    return {
        'headline': f"{month_name} {year}: {sat_pct}% — {'on target' if sat_pct >= target else f'{target - sat_pct} below target'}.",
        'body': body,
        'actions': actions,
        'diagnosis': diagnosis,
    }


def _build_zone_satisfaction(all_garages, matrix):
    """Map each zone to its primary garage's satisfaction score.

    Returns: {zone_territory_id: {garage_name, sat_pct, surveys, avg_ata, tier}}
    The frontend uses zone_territory_id to match against GeoJSON feature territory_id.
    """
    # Build garage satisfaction lookup: garage_name -> data
    garage_by_name = {g['name']: g for g in all_garages}

    # Build garage ID -> name from the priority matrix + garage list
    garage_id_to_name = {}
    try:
        from ops import get_ops_garages
        ops_garages = get_ops_garages()
        for g in ops_garages:
            garage_id_to_name[g['id']] = g['name']
    except Exception:
        pass

    # For each zone (parent_territory_id), find rank-1 garage
    zone_sat = {}
    rank_lookup = matrix.get('rank_lookup', {})
    by_parent = {}
    for (parent_id, spotted_id), rank in rank_lookup.items():
        if rank == 1:  # Primary garage
            by_parent[parent_id] = spotted_id

    for zone_id, garage_id in by_parent.items():
        garage_name = garage_id_to_name.get(garage_id, '')
        g = garage_by_name.get(garage_name)
        if g:
            zone_sat[zone_id] = {
                'garage_name': garage_name,
                'sat_pct': g.get('totally_satisfied_pct'),
                'surveys': g.get('surveys', 0),
                'avg_ata': g.get('avg_ata'),
                'tier': g.get('tier'),
            }
        else:
            zone_sat[zone_id] = {
                'garage_name': garage_name,
                'sat_pct': None,
                'surveys': 0,
                'avg_ata': None,
                'tier': None,
            }

    return zone_sat


def _build_day_result(date, cache_key, surveys, sas, wo_to_sa, towbook_on_loc):
    """Assemble the day analysis result from pre-fetched data."""
    # ── Aggregate surveys by garage ──
    garage_surveys = defaultdict(lambda: {'totally_satisfied': 0, 'satisfied': 0, 'dissatisfied': 0,
                                          'totally_dissatisfied': 0, 'neither': 0, 'total': 0})
    total_ts, total_s, total_d, total_td, total_n = 0, 0, 0, 0, 0
    problem_surveys = []  # dissatisfied/totally dissatisfied with details

    for sv in surveys:
        garage = ((sv.get('ERS_Work_Order__r') or {}).get('ServiceTerritory') or {}).get('Name', '') or 'Unknown'
        sat_val = (sv.get('ERS_Overall_Satisfaction__c') or '').strip().lower()
        g = garage_surveys[garage]
        g['total'] += 1

        if sat_val == 'totally satisfied':
            g['totally_satisfied'] += 1
            total_ts += 1
        elif sat_val == 'satisfied':
            g['satisfied'] += 1
            total_s += 1
        elif sat_val == 'dissatisfied':
            g['dissatisfied'] += 1
            total_d += 1
        elif sat_val == 'totally dissatisfied':
            g['totally_dissatisfied'] += 1
            total_td += 1
        else:
            g['neither'] += 1
            total_n += 1

        # Collect problem surveys (dissatisfied or worse, OR has negative comment)
        if sat_val in ('dissatisfied', 'totally dissatisfied', 'neither satisfied nor dissatisfied'):
            wo_id = (sv.get('ERS_Work_Order__r') or {}).get('Id', '')
            sa_info = wo_to_sa.get(wo_id, {})
            problem_surveys.append({
                'garage': garage,
                'overall': sv.get('ERS_Overall_Satisfaction__c') or '',
                'response_time': sv.get('ERS_Response_Time_Satisfaction__c') or '',
                'technician': sv.get('ERS_Technician_Satisfaction__c') or '',
                'wo_number': sv.get('ERS_Work_Order_Number__c') or '',
                'comment': sv.get('Customer_Comments__c') or '',
                'sa_number': sa_info.get('sa_number', ''),
                'call_date': sa_info.get('call_date', ''),
                'driver': sa_info.get('driver', ''),
            })

    # ── Aggregate SAs by garage ──
    garage_ops = defaultdict(lambda: {'total': 0, 'completed': 0, 'cancelled': 0, 'ata_sum': 0.0,
                                      'ata_count': 0, 'sla_hits': 0, 'sla_eligible': 0,
                                      'ata_under_30': 0, 'ata_30_45': 0, 'ata_45_60': 0, 'ata_over_60': 0})
    cancel_reasons = defaultdict(int)
    long_ata_sas = []  # SAs with ATA > 60min

    for sa in sas:
        wt = (sa.get('WorkType') or {}).get('Name', '') or ''
        if 'drop' in wt.lower():
            continue
        garage = (sa.get('ServiceTerritory') or {}).get('Name', '') or 'Unknown'
        g = garage_ops[garage]
        g['total'] += 1

        status = sa.get('Status') or ''
        if status == 'Completed':
            g['completed'] += 1
        if 'Cancel' in status:
            g['cancelled'] += 1
            reason = sa.get('ERS_Cancellation_Reason__c') or 'Unknown'
            cancel_reasons[reason] += 1

        # ATA calculation
        if status == 'Completed':
            dm = sa.get('ERS_Dispatch_Method__c') or ''
            created = _parse_dt(sa.get('CreatedDate'))
            arrival = None
            if dm == 'Field Services':
                arrival = _parse_dt(sa.get('ActualStartTime'))
            elif dm == 'Towbook':
                arrival = towbook_on_loc.get(sa.get('Id'))
            else:
                arrival = _parse_dt(sa.get('ActualStartTime'))

            if created and arrival:
                diff = (arrival - created).total_seconds() / 60
                if 0 < diff < 480:
                    g['ata_sum'] += diff
                    g['ata_count'] += 1
                    g['sla_eligible'] += 1
                    if diff <= 45:
                        g['sla_hits'] += 1
                    if diff < 30:
                        g['ata_under_30'] += 1
                    elif diff <= 45:
                        g['ata_30_45'] += 1
                    elif diff <= 60:
                        g['ata_45_60'] += 1
                    else:
                        g['ata_over_60'] += 1
                    if diff > 60:
                        long_ata_sas.append({
                            'number': sa.get('AppointmentNumber', ''),
                            'garage': garage,
                            'ata_min': round(diff),
                            'work_type': wt,
                            'dispatch_method': dm,
                        })

    # ── Build garage breakdown (with lat/lon from ops garages cache) ──
    from ops import get_ops_garages
    garage_locations = {}
    try:
        for g in get_ops_garages():
            if g.get('lat') and g.get('lon'):
                garage_locations[g['name']] = {'lat': g['lat'], 'lon': g['lon']}
    except Exception:
        pass

    all_garage_names = sorted(set(list(garage_surveys.keys()) + list(garage_ops.keys())))
    garage_breakdown = []
    for name in all_garage_names:
        if not _is_real_garage(name):
            continue
        sv = garage_surveys.get(name, {'totally_satisfied': 0, 'total': 0})
        ops = garage_ops.get(name, {'total': 0, 'completed': 0, 'cancelled': 0, 'ata_sum': 0, 'ata_count': 0, 'sla_hits': 0, 'sla_eligible': 0})
        ts_pct = round(100 * sv['totally_satisfied'] / sv['total']) if sv['total'] else None
        avg_ata = round(ops['ata_sum'] / ops['ata_count']) if ops['ata_count'] else None
        sla = round(100 * ops['sla_hits'] / ops['sla_eligible']) if ops['sla_eligible'] else None
        tier = ('excellent' if ts_pct is not None and ts_pct >= 90 else 'ok' if ts_pct is not None and ts_pct >= 82
                else 'below' if ts_pct is not None and ts_pct >= 60 else 'critical' if ts_pct is not None else None)
        loc = garage_locations.get(name, {})
        garage_breakdown.append({
            'name': name,
            'totally_satisfied_pct': ts_pct,
            'surveys': sv['total'],
            'dissatisfied': sv.get('dissatisfied', 0) + sv.get('totally_dissatisfied', 0),
            'sa_total': ops['total'],
            'sa_completed': ops['completed'],
            'sa_cancelled': ops['cancelled'],
            'avg_ata': avg_ata,
            'sla_pct': sla,
            'tier': tier,
            'lat': loc.get('lat'),
            'lon': loc.get('lon'),
        })
    # Sort: garages with low satisfaction first, then by volume
    garage_breakdown.sort(key=lambda g: (
        g['totally_satisfied_pct'] if g['totally_satisfied_pct'] is not None else 999,
        -(g['surveys'] or 0),
    ))

    # ── Summary stats ──
    total_surveys = sum(1 for _ in surveys)
    total_sas = sum(g['total'] for g in garage_ops.values())
    total_completed = sum(g['completed'] for g in garage_ops.values())
    total_cancelled = sum(g['cancelled'] for g in garage_ops.values())
    total_ata_sum = sum(g['ata_sum'] for g in garage_ops.values())
    total_ata_count = sum(g['ata_count'] for g in garage_ops.values())

    ts_pct = round(100 * total_ts / total_surveys) if total_surveys else None
    avg_ata = round(total_ata_sum / total_ata_count) if total_ata_count else None
    comp_pct = round(100 * total_completed / total_sas) if total_sas else None
    total_sla_hits = sum(g['sla_hits'] for g in garage_ops.values())
    total_sla_eligible = sum(g['sla_eligible'] for g in garage_ops.values())
    sla_pct = round(100 * total_sla_hits / total_sla_eligible) if total_sla_eligible else None
    total_ata_under_30 = sum(g['ata_under_30'] for g in garage_ops.values())
    total_ata_30_45 = sum(g['ata_30_45'] for g in garage_ops.values())
    total_ata_45_60 = sum(g['ata_45_60'] for g in garage_ops.values())
    total_ata_over_60 = sum(g['ata_over_60'] for g in garage_ops.values())

    # ── VP Briefing — Bottom Line Up Front ──
    insights = _build_day_insights(
        ts_pct, total_surveys, avg_ata, total_d, total_td,
        garage_breakdown, problem_surveys,
    )

    # Sort long ATA SAs by worst first
    long_ata_sas.sort(key=lambda x: -x['ata_min'])

    # Top cancel reasons
    top_cancels = sorted(cancel_reasons.items(), key=lambda x: -x[1])[:5]

    result = {
        'date': date,
        'summary': {
            'totally_satisfied_pct': ts_pct,
            'total_surveys': total_surveys,
            'dissatisfied_count': total_d + total_td,
            'neither_count': total_n,
            'satisfied_count': total_s,
            'totally_satisfied_count': total_ts,
            'avg_ata': avg_ata,
            'sla_pct': sla_pct,
            'sla_hits': total_sla_hits,
            'sla_eligible': total_sla_eligible,
            'ata_under_30': total_ata_under_30,
            'ata_30_45': total_ata_30_45,
            'ata_45_60': total_ata_45_60,
            'ata_over_60': total_ata_over_60,
            'total_sas': total_sas,
            'completed': total_completed,
            'completion_pct': comp_pct,
            'cancelled': total_cancelled,
        },
        'insights': insights,
        'garage_breakdown': garage_breakdown,
        'problem_surveys': problem_surveys[:30],  # cap at 30
        'long_ata_sas': long_ata_sas[:20],  # cap at 20
        'cancel_reasons': [{'reason': r, 'count': c} for r, c in top_cancels],
    }

    cache.put(cache_key, result, 7200)
    cache.disk_put(cache_key, result, 7200)
    return result


def _build_day_insights(ts_pct, total_surveys, avg_ata, total_d, total_td,
                        garage_breakdown, problem_surveys):
    """Build VP briefing insights for a single day."""
    insights = []
    target = 82
    dissat_count = total_d + total_td
    comments_with_text = [s for s in problem_surveys if s.get('comment')]

    # 1. Classify struggling garages
    struggling = [g for g in garage_breakdown
                  if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] < 70 and g['surveys'] >= 2]
    good_garages = [g for g in garage_breakdown
                    if g['totally_satisfied_pct'] is not None and g['totally_satisfied_pct'] >= 82 and g['surveys'] >= 2]

    # 2. Analyze comment themes
    theme_wait = 0      # long wait, hours, took forever
    theme_noshow = 0    # never showed, no one came, never received
    theme_comm = 0      # no communication, no update, no callback
    theme_quality = 0   # rude, unprofessional, wrong truck, refused
    theme_cancel = 0    # cancelled, gave up

    for sv in comments_with_text:
        c = (sv.get('comment') or '').lower()
        if any(w in c for w in ['hour', 'wait', 'took', 'long time', 'forever', 'stranded']):
            theme_wait += 1
        if any(w in c for w in ['never showed', 'no one came', 'never received', 'nobody', 'never got']):
            theme_noshow += 1
        if any(w in c for w in ['no communication', 'no update', 'no call', 'no follow', 'no notification', 'no status']):
            theme_comm += 1
        if any(w in c for w in ['rude', 'unprofessional', 'refused', 'wrong truck', 'condescend', 'smug', 'attitude']):
            theme_quality += 1
        if any(w in c for w in ['cancel', 'gave up', 'could not wait']):
            theme_cancel += 1

    # 3. Build garage-specific diagnoses
    garage_diagnoses = []
    for g in struggling[:3]:
        name = g['name'].split(' - ')[-1].strip() if ' - ' in g['name'] else g['name']
        ata = g.get('avg_ata')
        total = g.get('sa_total', 0)
        cancelled = g.get('sa_cancelled', 0)
        dissat = g.get('dissatisfied', 0)

        if ata and ata > 90:
            garage_diagnoses.append(f"{name} had {ata}-minute average wait times across {total} calls — severely overwhelmed")
        elif ata and ata > 60:
            garage_diagnoses.append(f"{name} averaged {ata}m response on {total} calls with {dissat} dissatisfied surveys")
        elif cancelled > 2:
            garage_diagnoses.append(f"{name} had {cancelled} cancellations out of {total} calls — members gave up waiting")
        elif dissat > 0:
            garage_diagnoses.append(f"{name} had {dissat} dissatisfied out of {g['surveys']} surveys ({g['totally_satisfied_pct']}%)")

    # 4. Build the briefing
    if ts_pct is not None and ts_pct < target:
        # ── BELOW TARGET ──
        gap = target - ts_pct

        # Headline
        pts = 'point' if gap == 1 else 'points'
        headline = f"{gap} {pts} below target. "
        if theme_wait > theme_quality and theme_wait > 0:
            headline += "Long wait times are the primary driver of dissatisfaction."
        elif theme_quality > theme_wait and theme_quality > 0:
            headline += "Driver quality and professionalism issues are driving dissatisfaction."
        elif theme_noshow > 0:
            headline += "Members reported service no-shows — calls dispatched but drivers never arrived."
        else:
            headline += f"{dissat_count} members reported dissatisfaction."

        insights.append({'type': 'critical', 'text': headline})

        # Garage details
        if garage_diagnoses:
            insights.append({
                'type': 'warning',
                'text': f"Facilities that drove the score down: {'. '.join(garage_diagnoses)}.",
            })

        # Comment themes
        themes = []
        if theme_wait > 0:
            themes.append(f"{theme_wait} members complained about long wait times")
        if theme_noshow > 0:
            themes.append(f"{theme_noshow} reported service never arrived")
        if theme_comm > 0:
            themes.append(f"{theme_comm} cited lack of communication or status updates")
        if theme_quality > 0:
            themes.append(f"{theme_quality} reported driver quality or professionalism issues")
        if themes:
            insights.append({
                'type': 'info',
                'text': f"Common themes from member feedback: {'; '.join(themes)}.",
            })

        # Network context
        if good_garages:
            insights.append({
                'type': 'info',
                'text': f"The problem was concentrated — {len(good_garages)} of {len(garage_breakdown)} garages met target. "
                        f"Corrective action should focus on the {len(struggling)} underperforming facilities.",
            })

    else:
        # ── MET TARGET ──
        risks = []
        if struggling:
            garage_strs = [f"{g['name'].split(' - ')[-1].strip()} ({g['totally_satisfied_pct']}%)"
                           for g in struggling[:3]]
            risks.append(f"weak spots at {', '.join(garage_strs)}")
        if avg_ata and avg_ata > 50:
            risks.append(f"average response time at {avg_ata} minutes (above 45m SLA)")

        if risks and dissat_count > 0:
            insights.append({
                'type': 'warning' if len(risks) > 1 else 'success',
                'text': f"On target at {ts_pct}%, but with {', '.join(risks)}. "
                        f"The rest of the network ({len(good_garages)} garages) is performing well enough to compensate.",
            })

            # Garage details for struggling facilities
            if garage_diagnoses:
                insights.append({
                    'type': 'warning',
                    'text': f"Facilities needing attention: {'. '.join(garage_diagnoses)}.",
                })

            # Comment themes even when meeting target
            themes = []
            if theme_wait > 0:
                themes.append(f"{theme_wait} complained about wait times")
            if theme_quality > 0:
                themes.append(f"{theme_quality} reported driver quality issues")
            if theme_noshow > 0:
                themes.append(f"{theme_noshow} reported no-shows")
            if theme_comm > 0:
                themes.append(f"{theme_comm} cited poor communication")
            if themes:
                insights.append({
                    'type': 'info',
                    'text': f"From the {dissat_count} dissatisfied members: {'; '.join(themes)}. "
                            f"Address these to build margin above the 82% target.",
                })
        elif ts_pct and ts_pct >= 90:
            insights.append({
                'type': 'success',
                'text': f"Strong day — {ts_pct}% across {total_surveys} surveys with {avg_ata}m average response. "
                        f"Both speed and driver quality performing well across the network.",
            })
        else:
            insights.append({
                'type': 'success',
                'text': f"Steady performance at {ts_pct}%. No major issues identified.",
            })

    return insights
