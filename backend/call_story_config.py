"""Call Story rules `cs1`: call-story-spec.md section 12 verbatim, plus the call-story-architecture.md additions
(stuck types, norm fallback level 4 approved as O5, Salesforce call cap). Thresholds live here, never in code."""

import copy

CS1 = {
    'rules_version': 'cs1',
    'inputs': {'sa': r'^(SA-)?\d{6,7}$', 'wo': r'^(WO-)?0\d{7}$', 'call_key': r'^\d{3}-\d{8}-\d{8}$',
               'source_call_id': r'^\d{8}$', 'id': r'^(08p|0WO|1WL)[A-Za-z0-9]{12}([A-Za-z0-9]{3})?$',
               'source_call_id_field': 'ERS_Source_Call_ID__c'},
    'event_group_window_sec': 0,
    'pta': {'initial_window_sec': 5, 'skip_le': 0, 'skip_ge': 999},
    'optimizer_attribution': {'before_sec': 90, 'after_sec': 0, 'log_match_sec': 10},
    'decline_auto_sec': 60,
    'reason_attach_sec': 60,
    'baseline': {'lookback_days': 56, 'hour_block': 4, 'split_weekend': True, 'min_n': 30,
                 'fallback': ['garage_channel_segment', 'channel_segment'],
                 'pooled_all_channels_segments': ['S7', 'S8', 'S9'],   # level 4, O5 approved 2026-10-04
                 's3_split_by_driver_state': True, 's6_by_work_type': True},
    'severity': {'slow': 'p75', 'stuck': 'p90', 'critical': 'p95',
                 'critical_if_pta_passed': {'enabled': True, 'pta_basis': 'initial', 'min_severity': 'SLOW',
                                            'segments': ['S1', 'S2', 'S3', 'S4', 'S5', 'S7', 'S8', 'S9']}},
    'floors_min': {'S1': 5, 'S2': 15, 'S3': 15, 'S4': 10, 'S5': 45, 'S6': 60, 'S7': 10, 'S8': 10, 'S9': 5},
    'always_flag': ['S7', 'S8', 'S9'],
    'grid': {'zone_regex': r'^(WM|WR|CM|CR|RM|RR)\d{3}$', 'spot_prefixes': ['000-'], 'spot_contains': ['SPOT'],
             'unassigned_name': 'SPOT - UNASSIGNED GRIDS'},
    'sms': {'log_start_utc': '2026-09-01T20:08:44Z', 'session_match_sec': 10,
            'exclude_definitions': ['ERS_Send_SMS_Notification_to_Dispatchers_Contacts'],
            'not_accepted_checkpoints_min': [30, 50, 80], 'not_accepted_entry_statuses': ['Assigned', 'Dispatched']},
    'cache_ttl_sec': {'closed': 86400, 'open': 120},
    # architecture additions
    'stuck_types': {'S7': 'NO_OWNER', 'S8': 'PARKED_IN_SPOT', 'S9': 'NO_OWNER'},
    'segment_owner': {'S1': 'system', 'S2': 'optimizer', 'S3': 'driver', 'S4': 'driver', 'S5': 'driver',
                      'S6': 'driver', 'S7': 'dispatcher', 'S8': 'dispatcher', 'S9': 'system'},
    'max_sf_calls': 12,
    'max_history_days': 540,
    'closed_grace_hours': 2,
    'rate_limit_per_min': 10,
}

SEVERITY_ORDER = ['OK', 'SLOW', 'STUCK', 'CRITICAL']
PRE_ARRIVAL = ('S1', 'S2', 'S3', 'S4', 'S5', 'S7', 'S8', 'S9')
TERMINAL = ('Completed', 'Unable to Complete', 'Cancel Call - Service Not En Route', 'Cancel Call - Service En Route',
            'Canceled', 'No-Show')


def cs1() -> dict:
    return copy.deepcopy(CS1)
