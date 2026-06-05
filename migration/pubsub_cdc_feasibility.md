# Pub/Sub and CDC Feasibility - 2026-06-05

## Result

Do not add a production Pub/Sub subscriber yet.

The Salesforce org exposes ChangeEvent object describe metadata for the three
FSL objects FSLPulse would care about most:

| Source object | ChangeEvent object | REST describe | Queryable | Replicateable |
| --- | --- | --- | --- | --- |
| `ServiceAppointment` | `ServiceAppointmentChangeEvent` | OK | false | false |
| `AssignedResource` | `AssignedResourceChangeEvent` | OK | false | false |
| `ServiceResource` | `ServiceResourceChangeEvent` | OK | false | false |

Sample fields were visible on each event object, including `ReplayId` and
`ChangeEventHeader`, which are required for replay-aware subscribers.

## Requires Confirmation

These items cannot be proven safely from code alone and must be confirmed in
Salesforce Setup before implementation:

- Change Data Capture is actively selected for `ServiceAppointment`,
  `AssignedResource`, and `ServiceResource`
- Event allocation is sufficient for expected FSL production update volume
- Replay retention requirements are acceptable for FSLPulse outage recovery
- Connected app and OAuth scopes are approved for Pub/Sub API access
- Durable replay storage location is approved, likely PostgreSQL rather than
  memory or local disk

## Implementation Gate

Only build a production subscriber after the Setup confirmation above. The first
safe implementation should be a sidecar worker that writes durable replay IDs
and invalidates/refills existing FSLAPP cache keys. It should not replace the
current scheduled/proactive cache refresh until event coverage has been measured
against live Salesforce changes.
