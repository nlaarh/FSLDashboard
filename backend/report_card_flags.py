"""Work-order flags for the Garage Replay list: RAP, out of territory, coverage level and member texts.

Read-only. Three sequential SELECTs per garage-day (WOLI -> work order, work order fields, text log), cached by the route.
A member "got no text" only when no text TO THE MEMBER was sent; opt-in confirmations, surveys and dispatcher
notifications don't count. Why there was none: opted out (not a problem) vs opted in and still nothing (the problem).
"""

from call_story_config import CS1 as CONFIG
from call_story_sms import label
from utils import parse_dt
from case_trail import actor

LOG_START = CONFIG['sms']['log_start_utc']
NOT_TO_MEMBER = {'Opt_in_Confirmation', 'Survey_IC_SMS', *CONFIG['sms']['exclude_definitions']}
COVERAGE = {'B': 'Basic', 'PLUS': 'Plus', 'PLRV': 'Plus RV', 'PREMIER': 'Premier', 'PMRV': 'Premier RV'}


def text_state(wo: dict, logs: list) -> dict:
    """state: ok | opted_out | missing (opted in, none sent: the problem) | no_data (before the log existed)."""
    made = parse_dt(wo.get('CreatedDate'))
    if made and made < parse_dt(LOG_START):
        return {'state': 'no_data', 'sent': 0, 'tip': 'Text log starts 1 Sep 2026: no text data for this day'}
    member = [r for r in logs if (r.get('Message_Definition__c') or '') not in NOT_TO_MEMBER]
    sent = [r for r in member if r.get('Outcome__c') == 'Sent']
    if sent:
        return {'state': 'ok', 'sent': len(sent), 'tip': f"{len(sent)} text(s) sent: " + ', '.join(dict.fromkeys(label(r['Message_Definition__c']) for r in sent))}
    if wo.get('SMS_Opt_In__c') is False:
        return {'state': 'opted_out', 'sent': 0, 'tip': 'No texts: member is not opted in to texts'}
    skipped = [r for r in member if r.get('Outcome__c')]
    why = ('; '.join(dict.fromkeys(f"{label(r.get('Message_Definition__c'))}: {r.get('Error_Message__c') or r['Outcome__c']}" for r in skipped))
           if skipped else 'no text was even attempted')
    return {'state': 'missing', 'sent': 0, 'tip': f'Opted in but got no text: {why}'}


def survey_of(rows: list) -> dict | None:
    """The member's survey for this work order (latest if several). None = no survey."""
    if not rows:
        return None
    r = max(rows, key=lambda x: x.get('ERS_Survey_Completed_Date__c') or '')
    nps = r.get('ERS_NPS__c')   # 0-10 "how likely to recommend"; x10 gives the 0-100 survey score
    return {'overall': r.get('ERS_Overall_Satisfaction__c'), 'response': r.get('ERS_Response_Time_Satisfaction__c'),
            'tech': r.get('ERS_Technician_Satisfaction__c'), 'nps': nps,
            'score': None if nps is None else round(float(nps) * 10),
            'totally': (r.get('ERS_Overall_Satisfaction__c') or '').lower() == 'totally satisfied'}


def compose(sas: list, woli_to_wo: dict, wos: dict, logs_by_wo: dict, surveys_by_wo: dict | None = None, cases_by_wo: dict | None = None) -> dict:
    out = {}
    for sa in sas:
        wo = wos.get(woli_to_wo.get(sa.get('woli_id')))
        if not wo:
            continue
        out[sa['id']] = {
            'rap': wo.get('Type__c') == 'RAP' or wo.get('Source__c') == 'RAP',
            'out_of_territory': bool(wo.get('Out_of_Territory__c')),
            'opted_in': wo.get('SMS_Opt_In__c'),
            'coverage': COVERAGE.get(wo.get('Coverage__c'), wo.get('Coverage__c')),
            'text': text_state(wo, logs_by_wo.get(wo['Id'], [])),
            'survey': survey_of((surveys_by_wo or {}).get(wo['Id'], [])),
            'wo_id': wo['Id'],
            'cases': (cases_by_wo or {}).get(wo['Id'], {'total': 0, 'open': 0, 'human': 0, 'auto': 0}),
        }
    return out


def pull_flags(sas: list, puller) -> dict:
    """sas: snapshot SA records (non-drop-off). puller: report_card_build.Puller (one query at a time).
    Cost per garage-day: 1 query for all work orders (parent fields read through the line item) + 1 for the text log
    (none when every call predates it) + 1 for surveys (completed calls only) + 1 aggregate for case counts. Rows are filtered in SOQL, only needed columns are read."""
    woli_ids = sorted({s['woli_id'] for s in sas if s.get('woli_id')})
    woli_to_wo, wos = {}, {}
    for r in puller.batched(
            "SELECT Id, WorkOrderId, WorkOrder.CreatedDate, WorkOrder.Type__c, WorkOrder.Source__c, "
            "WorkOrder.Out_of_Territory__c, WorkOrder.Coverage__c, WorkOrder.SMS_Opt_In__c "
            "FROM WorkOrderLineItem WHERE Id IN ({ids})", woli_ids, size=200):
        w = r.get('WorkOrder') or {}
        woli_to_wo[r['Id']] = r['WorkOrderId']
        wos[r['WorkOrderId']] = {'Id': r['WorkOrderId'], **{k: v for k, v in w.items() if k != 'attributes'}}
    cutoff = parse_dt(LOG_START)
    log_ids = [i for i, w in wos.items() if (parse_dt(w.get('CreatedDate')) or cutoff) >= cutoff]
    skip = ','.join(f"'{d}'" for d in sorted(NOT_TO_MEMBER))
    logs_by_wo = {}
    for r in puller.batched("SELECT Work_Order__c, Message_Definition__c, Outcome__c FROM SMS_Send_Log__c "
                            f"WHERE Work_Order__c IN ({{ids}}) AND Message_Definition__c NOT IN ({skip})", log_ids, size=200):
        logs_by_wo.setdefault(r['Work_Order__c'], []).append(r)
    done = {woli_to_wo[s['woli_id']] for s in sas if s.get('status') == 'Completed' and s.get('woli_id') in woli_to_wo}
    surveys_by_wo = {}
    for r in puller.batched("SELECT ERS_Work_Order__c, ERS_Overall_Satisfaction__c, ERS_Response_Time_Satisfaction__c, "
                            "ERS_Technician_Satisfaction__c, ERS_NPS__c, ERS_Survey_Completed_Date__c FROM Survey_Result__c "
                            "WHERE ERS_Work_Order__c IN ({ids})", sorted(done), size=200):
        surveys_by_wo.setdefault(r['ERS_Work_Order__c'], []).append(r)
    # One aggregate query: how many cases (open, and opened by a person vs an automation) each work order has.
    # The list shows counts; the cases themselves and who touched them load only when someone opens them.
    cases_by_wo = {}
    for r in puller.batched("SELECT ERS_Work_Order__c, IsClosed, CreatedBy.Profile.Name prof, COUNT(Id) n FROM Case "
                            "WHERE ERS_Work_Order__c IN ({ids}) GROUP BY ERS_Work_Order__c, IsClosed, CreatedBy.Profile.Name", sorted(wos), size=200):
        c = cases_by_wo.setdefault(r['ERS_Work_Order__c'], {'total': 0, 'open': 0, 'human': 0, 'auto': 0})
        c['total'] += r['n']
        c['human' if actor(None, r.get('prof'))['kind'] == 'person' else 'auto'] += r['n']
        if not r['IsClosed']:
            c['open'] += r['n']
    return compose(sas, woli_to_wo, wos, logs_by_wo, surveys_by_wo, cases_by_wo)
