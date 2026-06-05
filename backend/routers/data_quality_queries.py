"""Salesforce query helpers for the data quality audit."""

from textwrap import dedent
from urllib.parse import urlencode

from sf_client import SF_API_VERSION

COMPOSITE_QUERY_KEYS = [
    "total",
    "completed",
    "has_actual_start",
    "has_actual_end",
    "has_sched_start",
    "has_pta",
    "pta_bad",
    "has_dispatch_method",
    "wo_count",
    "survey_count",
    "has_auto_assign",
    "has_assigned_resource",
    "has_parent_territory",
    "sa_history_count",
]


def _clean_soql(soql: str) -> str:
    return dedent(soql).strip()


def data_quality_soql(since: str) -> dict[str, str]:
    """Return keyed SOQL queries for the data quality audit."""
    return {
        "total": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "completed": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND Status = 'Completed'
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "has_actual_start": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND Status = 'Completed'
              AND ActualStartTime != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "has_actual_end": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND Status = 'Completed'
              AND ActualEndTime != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "has_sched_start": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND SchedStartTime != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "has_pta": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND ERS_PTA__c != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "pta_bad": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND ERS_PTA__c != null
              AND (ERS_PTA__c = 0 OR ERS_PTA__c >= 999)
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "has_dispatch_method": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND ERS_Dispatch_Method__c != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "dispatch_sample": _clean_soql(f"""
            SELECT ERS_Dispatch_Method__c
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND ERS_Dispatch_Method__c != null
              AND WorkType.Name != 'Tow Drop-Off'
            LIMIT 5000
        """),
        "wo_count": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM WorkOrder
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
        """),
        "survey_count": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM Survey_Result__c
            WHERE CreatedDate >= {since}
              AND ERS_Overall_Satisfaction__c != null
        """),
        "has_auto_assign": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND ERS_Auto_Assign__c = true
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "has_assigned_resource": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM AssignedResource
            WHERE ServiceAppointment.CreatedDate >= {since}
              AND ServiceAppointment.ServiceTerritoryId != null
              AND ServiceAppointment.Status = 'Completed'
        """),
        "has_parent_territory": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointment
            WHERE CreatedDate >= {since}
              AND ServiceTerritoryId != null
              AND ERS_Parent_Territory__c != null
              AND WorkType.Name != 'Tow Drop-Off'
        """),
        "sa_history_count": _clean_soql(f"""
            SELECT COUNT(Id) cnt
            FROM ServiceAppointmentHistory
            WHERE Field = 'ServiceTerritory'
              AND ServiceAppointment.CreatedDate >= {since}
        """),
    }


def data_quality_query_requests(since: str) -> list[dict[str, str]]:
    """Build Composite Batch GET requests for the data quality audit."""
    queries = data_quality_soql(since)
    requests = []
    for key in COMPOSITE_QUERY_KEYS:
        soql = queries[key]
        query = urlencode({"q": soql})
        requests.append({
            "method": "GET",
            "url": f"/services/data/{SF_API_VERSION}/query?{query}",
        })
    return requests


def parse_composite_query_results(keys: list[str], response: dict) -> dict[str, list[dict]]:
    """Return keyed record lists from a Salesforce Composite Batch response."""
    results = response.get("results") or []
    if len(results) != len(keys):
        raise RuntimeError(f"Salesforce composite returned {len(results)} results for {len(keys)} requests")

    parsed = {}
    for key, item in zip(keys, results):
        status = item.get("statusCode")
        if status != 200:
            raise RuntimeError(f"Salesforce composite subrequest {key} failed with {status}: {item.get('result')}")
        result = item.get("result") or {}
        parsed[key] = result.get("records") or []
    return parsed
