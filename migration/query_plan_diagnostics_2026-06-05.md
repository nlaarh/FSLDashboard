# Salesforce Query Plan Diagnostics - 2026-06-05

## Change

Added a PIN-protected named diagnostic endpoint:

- `GET /api/admin/salesforce/query-plan/data-quality-total`

The endpoint does not accept arbitrary SOQL. It currently exposes only the
read-only data-quality total ServiceAppointment count query used by FSLPulse.

## Live Verification

Local API verification returned:

```json
{
  "status": 200,
  "name": "data-quality-total",
  "since": "2026-05-08T00:00:00Z",
  "has_plans": true,
  "plan_keys": ["plans", "sourceQuery"]
}
```

The request used the configured `ADMIN_PIN`, but the PIN was not printed.
