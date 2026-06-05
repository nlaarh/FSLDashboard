# Salesforce GraphQL Capability Probe - 2026-06-05

## Result

Salesforce GraphQL is available on the org at API `v65.0`, and
`ServiceAppointment` is visible through the GraphQL schema/UI API query surface.

This is not implemented as a replacement for production SOQL paths yet because
the measured minimal query did not outperform equivalent SOQL.

## Verified Probes

GraphQL schema probe:

- Request: `POST /services/data/v65.0/graphql`
- Query: `__type(name: "ServiceAppointment")`
- Result: returned `data.__type.fields`, including `Status` and many FSL fields
- First observed elapsed time: 18.5s

GraphQL minimal record probe:

- Query shape: `uiapi.query.ServiceAppointment(first: 1)`
- Fields: `Id`, `CreatedDate.value`, `Status.value`
- Result: 1 edge returned

## Timing Comparison

Warmed local comparison against the same org:

| Query path | Run 1 seconds | Run 2 seconds | Records |
| --- | ---: | ---: | ---: |
| GraphQL `uiapi.query.ServiceAppointment(first: 1)` | 0.633 | 0.135 | 1 |
| REST SOQL `SELECT Id, Status, CreatedDate FROM ServiceAppointment LIMIT 1` | 0.161 | 0.133 | 1 |

## Decision

Added a small tested `sf_graphql()` helper in `backend/sf_client.py` so future
read-only probes use the same auth, retry, stats, and circuit breaker path as
other Salesforce REST calls.

Do not move FSLPulse hot paths to GraphQL until a specific endpoint-level probe
shows fewer Salesforce round trips or faster wall time with the exact required
objects and fields.
