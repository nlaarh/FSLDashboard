"""Search endpoint — SA#, WO#, Member Number, Member Name.

GET /api/search?q=<query>

Returns grouped results (WO → SA list) for the top-nav search panel.
SA# is handled client-side; this endpoint covers WO#, Member#, Name.
"""

import logging
import re
from fastapi import APIRouter
from sf_client import sf_query_all, sf_rest_get, sanitize_soql
from utils import to_eastern as _to_eastern

log = logging.getLogger('search')
router = APIRouter()

_MAX_WO_RESULTS = 20
_SF_BASE = 'https://aaawcny.lightning.force.com'
_WO_SELECT = """
    SELECT Id, WorkOrderNumber, Customer_Name__c, Membership_ID__c,
           Facility_Name__c, CreatedDate
    FROM WorkOrder
"""


def _fmt_dt(sf_dt: str | None) -> str | None:
    if not sf_dt:
        return None
    et = _to_eastern(sf_dt)
    return et.strftime('%-m/%-d/%y %-I:%M %p') if et else None


def _fetch_sas_for_wos(wo_ids: list[str]) -> tuple[list, list]:
    """Return (sa_rows, woli_rows) for the given WO IDs."""
    if not wo_ids:
        return [], []
    id_list = ', '.join(f"'{sanitize_soql(i)}'" for i in wo_ids)
    try:
        woli_rows = sf_query_all(f"""
            SELECT Id, WorkOrderId
            FROM WorkOrderLineItem
            WHERE WorkOrderId IN ({id_list})
        """) or []
    except Exception as e:
        log.warning(f'WOLI fetch failed: {e}')
        return [], []
    if not woli_rows:
        return [], []
    woli_ids = ', '.join(f"'{sanitize_soql(w['Id'])}'" for w in woli_rows)
    try:
        sa_rows = sf_query_all(f"""
            SELECT Id, AppointmentNumber, Status, CreatedDate, ActualStartTime,
                   ParentRecordId, WorkType.Name, ServiceTerritory.Name
            FROM ServiceAppointment
            WHERE ParentRecordId IN ({woli_ids})
            ORDER BY CreatedDate ASC
        """) or []
    except Exception as e:
        log.warning(f'SA fetch failed: {e}')
        return [], woli_rows
    return sa_rows, woli_rows


def _build_results(wo_rows: list, sa_rows: list, woli_rows: list) -> list:
    """Group SAs under their parent WO and return result dicts."""
    from collections import defaultdict
    woli_map = {w['Id']: w['WorkOrderId'] for w in (woli_rows or [])}
    sa_by_wo: dict[str, list] = defaultdict(list)
    for sa in (sa_rows or []):
        wo_id = woli_map.get(sa.get('ParentRecordId', ''))
        if wo_id:
            sa_by_wo[wo_id].append(sa)

    results = []
    for wo in (wo_rows or []):
        wo_id = wo['Id']
        sas = [
            s for s in sa_by_wo.get(wo_id, [])
            if (s.get('WorkType') or {}).get('Name', '') != 'Tow Drop-Off'
        ]
        sas.sort(key=lambda s: s.get('CreatedDate') or '')
        primary = sas[0] if sas else None
        sa_numbers = [s['AppointmentNumber'] for s in sas if s.get('AppointmentNumber')]
        results.append({
            'wo_number':      wo.get('WorkOrderNumber'),
            'wo_sf_url':      f'{_SF_BASE}/{wo_id}',
            'sa_numbers':     sa_numbers,
            'primary_sa':     sa_numbers[0] if sa_numbers else None,
            'customer_name':  wo.get('Customer_Name__c'),
            'membership_id':  wo.get('Membership_ID__c'),
            'facility':       wo.get('Facility_Name__c'),
            'created':        _fmt_dt(wo.get('CreatedDate')),
            'service_datetime': (
                _fmt_dt(primary.get('ActualStartTime')) or _fmt_dt(primary.get('CreatedDate'))
                if primary else None
            ),
            'status':     (primary.get('Status') if primary else None),
            'work_type':  ((primary.get('WorkType') or {}).get('Name') if primary else None),
            'territory':  ((primary.get('ServiceTerritory') or {}).get('Name') if primary else None),
        })
    return results


_SOSL_SPECIAL = re.compile(r'[?&|!{}\[\]()\^~*:\"\'+\-\\]')
_WO_SOSL_FIELDS = (
    'Id, WorkOrderNumber, Customer_Name__c, Membership_ID__c, '
    'Facility_Name__c, CreatedDate'
)


def _sosl_name_search(q: str) -> list[dict]:
    """SOSL text search — uses SF indexes, far faster than LIKE '%...%'."""
    safe = _SOSL_SPECIAL.sub(' ', q).strip()
    if not safe:
        return []
    sosl = (
        f'FIND {{"{safe}"}} IN ALL FIELDS '
        f'RETURNING WorkOrder({_WO_SOSL_FIELDS} '
        f'ORDER BY CreatedDate DESC LIMIT {_MAX_WO_RESULTS})'
    )
    try:
        resp = sf_rest_get('/search', params={'q': sosl})
        return resp.get('searchRecords', []) if isinstance(resp, dict) else []
    except Exception as e:
        log.warning(f'SOSL name search failed, falling back to SOQL: {e}')
        # Fallback: exact-prefix LIKE (no leading wildcard — still fast)
        safe_soql = sanitize_soql(q)
        return sf_query_all(f"""
            {_WO_SELECT}
            WHERE Customer_Name__c LIKE '{safe_soql}%'
            ORDER BY CreatedDate DESC
            LIMIT {_MAX_WO_RESULTS}
        """) or []


@router.get('/api/search')
def search(q: str = ''):
    q = q.strip()
    if len(q) < 2:
        return {'type': 'empty', 'results': []}

    qu = q.upper()
    is_wo     = qu.startswith('WO-')
    is_member = q.isdigit() and len(q) >= 6

    try:
        if is_wo:
            # SF stores WorkOrderNumber without the 'WO-' prefix
            wo_num = q[3:] if qu.startswith('WO-') else q
            wo_rows = sf_query_all(
                f"{_WO_SELECT} WHERE WorkOrderNumber = '{sanitize_soql(wo_num)}' LIMIT 1"
            ) or []
            search_type = 'wo'
        elif is_member:
            # Limit to last 3 years to avoid full-table scan on non-indexed field
            wo_rows = sf_query_all(f"""
                {_WO_SELECT}
                WHERE Membership_ID__c = '{sanitize_soql(q)}'
                AND CreatedDate >= LAST_N_YEARS:3
                ORDER BY CreatedDate DESC
                LIMIT {_MAX_WO_RESULTS}
            """) or []
            search_type = 'member'
        else:
            if len(q) < 3:
                return {'type': 'name', 'results': []}
            wo_rows = _sosl_name_search(q)
            search_type = 'name'
    except Exception as e:
        log.error(f'WO search failed for {q!r}: {e}')
        return {'type': 'error', 'results': [], 'detail': str(e)[:200]}

    if not wo_rows:
        return {'type': search_type, 'results': []}

    wo_ids = [w['Id'] for w in wo_rows]
    sa_rows, woli_rows = _fetch_sas_for_wos(wo_ids)
    results = _build_results(wo_rows, sa_rows, woli_rows)
    return {'type': search_type, 'results': results}
