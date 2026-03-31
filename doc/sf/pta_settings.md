# PTA Settings & Entitlements (Verified Mar 15, 2026)

## PTA Configuration: ERS_Service_Appointment_PTA__c

**180 records** — one per territory + work type combination.
This is what gets promised to the member ("Your driver will arrive in X minutes").

### Object Fields
| Field | Type | Purpose |
|-------|------|---------|
| `ERS_Service_Territory__c` | Lookup(ServiceTerritory) | Which garage |
| `ERS_Type__c` | Picklist | Work type category |
| `ERS_Minutes__c` | Number | PTA in minutes |

### PTA Types
| Type | Records | Min | Max | Avg | Meaning |
|------|---------|-----|-----|-----|---------|
| **D** (Default) | 173 | 60 | 120 | 78.7 | Default PTA for all work types |
| **Battery** | 3 | 45 | 90 | 65.0 | Battery-specific override |
| **F** | 2 | 88 | 88 | 88.0 | Unknown (test records?) |
| **BA** | 1 | 88 | 88 | 88.0 | Unknown (test?) |
| **Lockout** | 1 | 88 | 88 | 88.0 | Lockout-specific override |

### Key Findings

1. **Most garages only have "D" type** — a single default PTA for all work types
2. **Only 4 garages have worktype-specific overrides** (Battery: 076DO, 053, 421; Lockout: Test)
3. **PTA range**: 60-120 min. Distribution:
   - 60 min: ~50 garages (mostly urban/close)
   - 75 min: ~5 garages
   - 88 min: ~80 garages (the most common — probably the system default)
   - 90 min: ~15 garages
   - 120 min: 1 garage (100 - WNY FLEET — the fleet territory)
4. **Fleet vs Towbook**: Fleet territory (100) has 120 min PTA, most Towbook garages have 60-88 min

### How PTA is Set (Apex Logic)

From `ERS_ServiceAppointmentTriggerHandler.setERSptaforSA()`:
```
1. Look up ERS_Service_Appointment_PTA__c WHERE territory = SA.ServiceTerritoryId
2. If worktype-specific record exists → use it
3. Else → use "D" (default) record
4. SA.ERS_PTA__c = matched ERS_Minutes__c
5. SA.DueDate = SA.EarliestStartTime.addMinutes(ERS_PTA__c)
```

### FSLAPP Implications

- **PTA Advisor** already uses this data for projections
- **Opportunity**: Most garages have uniform 88 min PTA regardless of work type. Battery calls take ~38 min, tow calls take ~115 min — the PTA should be differentiated
- **Monitoring**: Compare actual response times vs PTA promises per garage to identify where PTAs are unrealistic

---

## Member Entitlements

### Overview
- **835,217 active** entitlements (all "Phone Support" type)
- **798,766 expired**
- **1,208 inactive**
- Total: ~1.6M entitlements

### Structure
| Field | Value | Notes |
|-------|-------|-------|
| Type | "Phone Support" | Only type used |
| Name | "{LastName} - {Coverage Type}" | e.g., "Russo - Plus Coverage" |
| StartDate | ~2025-05-08 (most) | When coverage began |
| EndDate | ~2026-05-15 (most) | When coverage expires |
| IsPerIncident | false | Not per-incident |
| CasesPerEntitlement | null | No case count limit |
| WorkOrdersPerEntitlement | null | No WO count limit |
| AccountId | Person Account | Linked to member |

### Coverage Types (from Name field)
- **Plus Coverage** — premium tier (more calls allowed, additional services)
- **Basic Coverage** — standard tier

### How Entitlements Gate Service

From Flow logic (`Master Work Order Flow`):
```
1. WO created → Flow checks: is member entitled?
2. Entitlement consumption logic:
   - Standard: consume if Non_Count_Call = false AND Status ≠ New
   - Feedback: consume if Non_Count_Call = false
   - Back Office: consume if Status = Closed AND Non_Count_Call = false
   - Unable-To-Complete Dupes: consume if Status transitions from New
3. If not entitled → WO may be blocked or flagged
```

### FSLAPP Implications
- Entitlements are member-level, not facility-level — not directly relevant to garage dashboards
- Could be useful for member-facing features (call history, remaining benefits)
- Coverage type (Plus vs Basic) could correlate with satisfaction scores
