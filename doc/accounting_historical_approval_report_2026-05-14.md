# Accounting Historical Approval Report

Date: 2026-05-14

## Scope

- Source of truth: Salesforce `ERS_Work_Order_Adjustment__c`
- Window analyzed: `2025-07-01` through `2026-05-14`
- Included statuses: `Approved`, `Rejected`
- Excluded from this report: current `New` / open WOAs
- Resolved population analyzed: `19,528` WOAs

## Method

- Outcome came from Salesforce `Status__c`, not the app's current recommendation engine.
- Product line came from `Product__r.ProductCode`.
- Ask amount came from `Quantity__c`.
- Billing signal came from the linked `Work_Order_Line_Item__r.Quantity`.
- In the resolved set, the linked billed quantity usually matched the WOA ask exactly after approval. Across the major product lines, median `final billed qty - requested qty` was `0.0`.
- Accounting rationale was pulled primarily from `Description__c`. In many rejected WOAs, the accounting note is embedded inline as `Acctg: ...`.

## Executive Summary

- High-confidence / mostly approvable products: `TL`, `PG`, `BA`, `BC`, `TB`, `TT`, `TU`, `EM`
- Moderate approval with clear rule boundaries: `ER`, `TW`, `E1`, `MH`
- Low-confidence / manual-review products: `MI`, `E2`, `R1`, `RA`, `TJ`
- The most common rejection patterns are not random. They cluster around:
  - route or mileage mismatch
  - already paid / already updated / duplicate adjustment
  - wrong product code
  - not covered by contract or membership
  - special-case approval required from Business Advisor
  - no proof for second-truck / heavy-duty / toll claim

## Product Line Summary

| Code | Product | Approved | Rejected | Total | Approval % |
|---|---|---:|---:|---:|---:|
| BA | Base Rate | 353 | 7 | 360 | 98.1 |
| BC | Basic Cost | 138 | 11 | 149 | 92.6 |
| E1 | Extrication - 1st Truck | 1,998 | 250 | 2,248 | 88.9 |
| E2 | Extrication - 2nd Truck | 15 | 17 | 32 | 46.9 |
| EC | En route Miles (Contract C10) | 2 | 0 | 2 | 100.0 |
| EM | Extra Tow Mileage | 85 | 0 | 85 | 100.0 |
| ER | Enroute Miles | 5,485 | 1,012 | 6,497 | 84.4 |
| FL | Fuel Flat SC - Light Duty | 22 | 0 | 22 | 100.0 |
| HO | Holiday Bonus | 2 | 0 | 2 | 100.0 |
| HW | Night/Holiday/Weekend | 15 | 0 | 15 | 100.0 |
| LB | Labor Time | 1 | 0 | 1 | 100.0 |
| MC | Motorcycle Carrier | 5 | 0 | 5 | 100.0 |
| MH | Medium/Heavy Duty | 1,042 | 157 | 1,199 | 86.9 |
| MI | Miscellaneous / AAA Approval Reqd | 106 | 872 | 978 | 10.8 |
| ML | Fuel per Mile SC - Light Duty | 13 | 0 | 13 | 100.0 |
| MV | Fuel per Mile SC - Heavy Duty | 1 | 0 | 1 | 100.0 |
| PC | Plus Cost | 110 | 9 | 119 | 92.4 |
| PG | Plus/Premier Fuel | 467 | 28 | 495 | 94.3 |
| R1 | RV/Motorhome Service | 32 | 26 | 58 | 55.2 |
| RA | RV - Class A | 1 | 6 | 7 | 14.3 |
| TB | Tow Miles Basic | 138 | 2 | 140 | 98.6 |
| TJ | TireJect | 0 | 8 | 8 | 0.0 |
| TL | Tolls/Parking | 2,480 | 115 | 2,595 | 95.6 |
| TM | Tow Miles Premier | 15 | 0 | 15 | 100.0 |
| TT | Tow Miles Plus (5-30mi) | 1,206 | 1 | 1,207 | 99.9 |
| TU | Tow Miles Plus (30-100mi) | 371 | 1 | 372 | 99.7 |
| TW | Tow Miles | 2,006 | 895 | 2,901 | 69.1 |
| Z8 | RAP Extrication | 3 | 0 | 3 | 100.0 |

## Major Product Patterns

### ER - Enroute Miles

- Volume: `6,497`
- Approval rate: `84.4%`
- Median ask:
  - approved: `7.7`
  - rejected: `9.41`
- Common approved ask patterns:
  - `enroute miles`
  - `full enroute`
  - `adding original`
- Common rejection/accounting patterns:
  - `res code`
  - `priced res`
  - `already paying`
  - route mismatch versus Google / fastest route
- Draft automation rule:
  - auto-approve when requested ER is close to the route baseline and there is no duplicate / already-paid note
  - auto-reject or manual review when accounting note says route is shorter, already paying, wrong resolution code, or duplicate adjustment

### TW - Tow Miles

- Volume: `2,901`
- Approval rate: `69.1%`
- Median ask:
  - approved: `7.0`
  - rejected: `7.5`
- Common approved ask patterns:
  - `tow miles`
  - `miles towed`
  - duplicate cleared on the wrong WO, then re-added correctly
- Common rejection/accounting patterns:
  - `already paying`
  - `vehicle towed` mismatch
  - `google maps`
  - service actually cleared as a different work type
- Draft automation rule:
  - auto-approve when tow miles align with the linked tow call and product/work type agree
  - manual review or reject when accounting note references duplicate prior WOA, non-tow resolution, or Google mismatch

### TL - Tolls/Parking

- Volume: `2,595`
- Approval rate: `95.6%`
- Median ask:
  - approved: `3.0`
  - rejected: `4.0`
- Common approved ask patterns:
  - `grand island`
  - `tolls grand`
  - `island bridge`
- Common rejection/accounting patterns:
  - `toll road` not supported by route
  - test / disregard submission
  - wrong product code, then manually repaid under another code
- Draft automation rule:
  - auto-approve standard recurring toll corridors like Grand Island when route plausibility exists
  - reject / manual review when accounting note says no toll route, wrong product code, or duplicate/manual fix already done

### E1 - Extrication - 1st Truck

- Volume: `2,248`
- Approval rate: `88.9%`
- Median ask:
  - approved: `15`
  - rejected: `17`
- Common approved ask patterns:
  - `winch time`
  - `winch out`
  - `recover vehicle`
- Common rejection/accounting patterns:
  - `already paid`
  - `base rate`
  - `skates dollies`
  - wrong program / RAP mismatch
- Draft automation rule:
  - auto-approve documented winch / recovery time on real extrication cases
  - reject when accounting says the winch time was already paid, product should have been base-rate only, or the scenario is a skates/dollies / non-extrication situation

### MH - Medium/Heavy Duty

- Volume: `1,199`
- Approval rate: `86.9%`
- Median ask:
  - approved: `1`
  - rejected: `1`
- Common approved ask patterns:
  - `med heavy`
  - `medium duty`
  - specific vehicle examples like `E450`
- Common rejection/accounting patterns:
  - `curb weight`
  - `under 10k`
  - `rsi website`
- Draft automation rule:
  - auto-approve when vehicle classification clearly qualifies
  - reject when curb weight is under 10k or accounting explicitly states the vehicle is not MH-eligible

### MI - Miscellaneous / AAA Approval Reqd

- Volume: `978`
- Approval rate: `10.8%`
- Median ask:
  - approved: `7.8`
  - rejected: `42.0`
- Common approved ask patterns:
  - limited edge cases, usually pricing cleanup
  - some `wait time`, `night rate`, `jump start` corrections
- Common rejection/accounting patterns:
  - `wait time`
  - `business advisor`
  - `itemized current contract`
  - `special circumstances`
- Draft automation rule:
  - default MI to manual review
  - reject unless a known contract exception or named accounting/business approval exists

### PG - Plus/Premier Fuel

- Volume: `495`
- Approval rate: `94.3%`
- Median ask:
  - approved: `7.5`
  - rejected: `7.0`
- Common approved ask patterns:
  - `fuel cost`
  - `gallons fuel`
  - `fuel delivery`
- Common rejection/accounting patterns:
  - wrong resolution code
  - `basic member` not covered for fuel cost
- Draft automation rule:
  - auto-approve fuel reimbursement on covered fuel-delivery cases
  - reject when the member coverage is Basic or when accounting flags wrong resolution coding

### E2 - Extrication - 2nd Truck

- Volume: `32`
- Approval rate: `46.9%`
- Common approved ask patterns:
  - explicit second-truck statements
  - approval notes from named reviewers
- Common rejection/accounting patterns:
  - no photos confirming second truck
  - member not covered for higher-tier service
- Draft automation rule:
  - never auto-approve E2 without proof of second truck
  - require photos or explicit accounting/BA authorization

### R1 / RA - RV Rates

- `R1` volume: `58`, approval rate `55.2%`
- `RA` volume: `7`, approval rate `14.3%`
- Approved RV patterns:
  - `paying at RV rates`
  - `RV tow`
  - explicit minute caps or named approval
- Rejected RV patterns:
  - wrong RV class
  - already updated / already approved elsewhere
  - RV pricing not allowed on the actual service type
- Draft automation rule:
  - keep RV products in manual review unless class, coverage, cap, and service type all match

### TJ - TireJect

- Volume: `8`
- Approval rate: `0%`
- Rejection patterns:
  - wrong product code, should have been `TL`
  - not itemized under current contract
  - duplicate payment under another call
- Draft automation rule:
  - do not auto-approve `TJ`
  - route to reject/manual correction unless contract explicitly itemizes it

## Overall Rejection Themes

Most common accounting rejection language across products:

- `wait time`
- `business advisor`
- `enroute miles`
- `res code`
- `base rate`
- `tow miles`
- `already paying`
- `duplicate`
- `itemized current contract`

Interpretation:

- A material portion of rejected WOAs are not “bad asks”; they are administrative duplicates, already-paid items, or wrong-code submissions.
- The cleanest automation wins are product-code routing and eligibility checks before human review:
  - wrong product code
  - duplicate / already updated
  - contract-ineligible product
  - route mismatch
  - proof-required products

## Recommended Automation Rules

### High Confidence Auto-Approve

- `TL` when the ask matches recurring known toll situations and there is no accounting conflict
- `PG` for covered fuel-delivery reimbursement
- `BA`, `BC`, `TB`, `TT`, `TU`, `EM` when the request matches a standard priced adjustment and there is no duplicate / prior-fix note

### High Confidence Manual Review / Reject

- `MI` by default
- `TJ` by default
- `E2` without evidence of second truck
- `MH` when vehicle weight/class does not qualify
- `ER` / `TW` when accounting note references Google mismatch, already paid, duplicate, or wrong resolution code
- `PG` when member is Basic or fuel cost is not covered

### Needs Rule Engine + Data Checks

- `ER`, `TW`, `TT`, `TU`, `TB`:
  - compare ask to route baseline
  - check duplicate/already-updated comments
  - verify product matches actual service cleared
- `E1`:
  - compare requested minutes to documented winch/recovery context
  - block if already paid or wrong product/program
- `R1`, `RA`:
  - require RV class, cap, and service-type match

## Important Caveat

Rejected status is sometimes used operationally to close out a WOA after accounting already fixed the issue another way. Examples in the historical set include:

- already approved under another WOA
- manually updated in the call already
- rejected because a different product code was added instead

So the automation layer should separate:

- true denial
- duplicate / superseded
- wrong product code / rerouted
- already paid / already updated

That split will matter if you want clean approval-policy automation rather than just status mimicry.
