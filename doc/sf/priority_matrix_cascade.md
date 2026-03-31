# Territory Priority Matrix & Cascade Logic (Verified Mar 15, 2026)

## Overview

The **Priority Matrix** (`ERS_Territory_Priority_Matrix__c`) is the core dispatch routing table.
It determines which garages get offered a call, in what order, based on where the member is stranded.

**1,100 records** define the complete cascade map for the entire org.

## Object: ERS_Territory_Priority_Matrix__c (16 fields)

| Field | Type | Purpose |
|-------|------|---------|
| `ERS_Spotted_Territory__c` | Lookup(ServiceTerritory) | The garage that "owns" the geographic zone where the call originated |
| `ERS_Parent_Service_Territory__c` | Lookup(ServiceTerritory) | The **grid zone** (WM001, WR008, etc.) that gets offered the call |
| `ERS_Priority__c` | Number | Cascade order: lower = first offered. P2 → P3 → P4 → ... |
| `ERS_Worktype__c` | Multi-picklist | Which work types this cascade entry covers |
| `ERS_Operating_Hours__c` | Lookup(OperatingHours) | When this cascade entry is active (all found = "AAA 24/7/365") |

## How the Cascade Works

```
Member stranded at GPS coordinates
  → Apex: ERS_Utilities.getSpottedTerritory(lat, lng)
  → SA.ServiceTerritoryId = spotted garage (e.g., "076DO - TRANSIT AUTO DETAIL")
  → Mulesoft reads Priority Matrix WHERE ERS_Spotted_Territory__c = {garage}
  → Offers call to garages in priority order:
      P2 → nearby grids (WM006, WR030, WR032, ...) — first offer
      P3 → next ring of grids (WM015, WM043, WR031, ...) — if P2 declines
      P4 → wider ring (WR023, WR028, WM032, ...) — if P3 declines
      P5 → even wider (WR009, WR001, WR004)
      P6 → distant (WR010, WR005)
      P7 → last resort before fallback (WR002, WR024, WR003)
      P10 → 000-SPOT catch-all (ALL garages in region, ~30-70 entries)
```

## Key Design Patterns

### 1. Worktype-Aware Cascade
The matrix is NOT flat — it routes differently by work type:

**Example: Garage 053 - MICHAEL BELLRENG**
- P2 for **Light Service** (Fuel/Lockout/Battery/Tire/Jumpstart) → WM013, WM035, WM040, WM037...
- P2 for **Tow/Winch** (Tow Pick-Up/Drop-off/Winch Out) → WM035, WM017, WM002
- P3 for **Tow** → same garages that were P2 for light (expanded tow coverage)
- P4 for **Full Service** → WM015, WM016, WM013, WM023 (any work type)

**Implication**: A grid zone might be offered light service calls at P2 but only get tow calls at P3.
This reflects capability: not all garages have tow trucks.

### 2. Three Worktype Categories
| Category | Picklist Values | Meaning |
|----------|----------------|---------|
| Light Service | Fuel / Miscellaneous; Lockout; Battery; Tire; Jumpstart | Light truck work |
| Tow | Winch Out; Tow Pick-Up; Tow Drop-off | Heavy truck required |
| Full Service | Full Service | Any work type (catch-all) |

### 3. Priority Levels Found
| Priority | Meaning | Usage |
|----------|---------|-------|
| P2 | Primary cascade — first garages offered | Most common |
| P3 | Secondary cascade | Second ring |
| P4 | Tertiary | Third ring |
| P5 | Extended | Fourth ring |
| P6 | Far extended | Fifth ring |
| P7 | Last resort | Rare, distant |
| P10 | Catch-all (000-SPOT) | Every garage in region |
| P93 | Effectively disabled | Found on 201 - J'S AUTO (WR006, WR007) |

**Note: No P1 found.** The spotted garage itself (the territory the call lands in) is implicitly P1 — it's the SA's ServiceTerritoryId.

### 4. Regional Catch-All Territories (000-SPOT)
Four "000-SPOT" territories serve as last-resort fallbacks:
- **000- WNY M SPOT** — 39 garages (WM region), all at P10
- **000- ROC M SPOT** — 31 garages (RM/RR region), all at P10
- **000- CNY M / NC SPOT** — 72 garages (CR/CM/RR region), all at P10
- **000- ST SPOT** — 58 garages (RR/WR/CR region), all at P10

All entries are "Full Service" type and "24/7/365" hours.

### 5. Grid Zone Naming Convention
| Prefix | Region | Type |
|--------|--------|------|
| WM | Western NY Metro | Grid zone |
| WR | Western NY Rural | Grid zone |
| RM | Rochester Metro | Grid zone |
| RR | Rochester Rural / Regional | Grid zone |
| CR | Central NY Rural | Grid zone |
| CM | Central NY Metro | Grid zone |

## Example: Full Cascade for 076DO (Transit Auto Detail)

```
SPOTTED: 076DO - TRANSIT AUTO DETAIL (Towbook garage, PTA=60 min)

P2 (16 grids, Full Service):
  WM006, WR030, WR032, WR013, WR036, WM034, WM033, WM030,
  WM005, WM003, WM029, WM026, WM009, WR014, WM004, WM008,
  WM036, WR012

P3 (19 grids, Full Service):
  WM015, WM043, WR031, WR017, WR019, WM007, WR033, WR035,
  WM044, WM045, WM046, WM018, WM016, WM010, WM028, WM019,
  WM025, WR034, WM024, WM022, WM021, WM014, WM020, WM027

P4 (8 grids, Full Service):
  WR023, WR028, WR027, WR016, WR015, WM032, WR011, WM031,
  WM011, WM012

P5 (3 grids): WR009, WR001, WR004
P6 (2 grids): WR010, WR005
P7 (3 grids): WR002, WR024, WR003
```

Total: 51 grid zones in the cascade before hitting 000-SPOT fallback.

## How Mulesoft Uses This

1. Call comes in → SA.ServiceTerritoryId = spotted garage
2. Mulesoft queries Priority Matrix for that spotted territory
3. Filters by worktype match
4. Checks operating hours (all 24/7 currently)
5. Offers to P2 garages first
6. If declined or no response → cascades to P3, P4, etc.
7. If all decline → hits 000-SPOT (P10) catch-all
8. Cascade tracking: `ServiceAppointmentHistory.Field = 'ServiceTerritory'` records each reassignment

## FSLAPP Implications

- **Cascade visualization**: Can show which garages are in a territory's cascade and at what priority
- **Decline tracking**: SA history shows each territory reassignment = one cascade step
- **1st vs 2nd call analysis**: History-based (already implemented in performance endpoint)
- **Matrix coverage gaps**: Some garages may have incomplete cascades (missing worktypes)
- **Response time by cascade depth**: P2 should be fastest, P7 slowest — trackable via SA history
