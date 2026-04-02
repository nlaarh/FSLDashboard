"""AI Insights — rule-based recommendation generators and LLM prompt templates."""

import json as _json
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException

from utils import _ET
import cache

router = APIRouter()


# ── LLM Prompt Templates ─────────────────────────────────────────────────────

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


# ── Rule-Based Recommendation Generators ──────────────────────────────────────

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


# ── Main Insight Endpoint ─────────────────────────────────────────────────────

@router.get("/api/insights/{category}")
def get_insights(category: str):
    """AI-powered operational insights with LLM analysis and rule-based fallback."""
    from routers.insights import (
        _insights_garage_data, _insights_driver_data, _insights_dispatch_data,
        _call_llm_insights, _parse_llm_json,
    )

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
