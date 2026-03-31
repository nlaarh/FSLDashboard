# FSL Enhanced Scheduler — Documented Behavior

## Scoring Formula
```
Score = (ASAP Grade × ASAP Weight) + (Travel Grade × Travel Weight) + Priority
```
- Grades are 0-100, linearly distributed between best and worst candidate
- Source: https://help.salesforce.com/s/articleView?id=sf.pfs_optimization_theory_service_objectives.htm

## ASAP Objective
- Scores based on earliest possible completion time
- Grade 100 = earliest slot, Grade 0 = latest slot
- "Earliest start date of each appointment has a grade of 100 and the latest has a grade of 0"
- Source: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_theory_service_objectives_asap.htm

## Minimize Travel Objective
- Scores based on travel distance/time to the appointment
- Grade 100 = closest driver, Grade 0 = farthest
- "Travel is calculated linearly between closest and furthest"
- Has option "Exclude Home Base Travel" — when enabled, only appointment-to-appointment travel counts
- Source: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_theory_service_objectives_min_travel.htm

## Travel Calculation
- First job of day: from home base (ServiceTerritoryMember.Address)
- Subsequent jobs: from last appointment location
- "Travel is calculated first from the home location, then from the last appointment location"
- Without SLR: aerial/straight-line distance × correction factor
- With SLR: road-based routing (Google Maps)
- Source: https://help.salesforce.com/s/articleView?id=000382870&language=en_US&type=1

## Maximum Travel From Home Work Rule
- Limits how far a driver can be sent from their home base
- Requires Address on ServiceTerritoryMember to function
- Source: https://help.salesforce.com/s/articleView?id=service.pfs_optimization_theory_work_rules_max_travel_home.htm

## Street Level Routing (SLR)
- Optional: uses actual roads instead of aerial distance
- Requires TravelMode on territories and SLR enabled in settings
- Source: https://help.salesforce.com/s/articleView?id=service.pfs_streetlevelrouting.htm

## Key Insight for This Org
The problem is NOT that the scheduler can't find driver locations mid-day. It CAN and DOES use last-job coordinates. The problem is the 90/10 ASAP/Travel weight ratio — ASAP dominates scoring so distance is nearly irrelevant. With 9x ASAP weight, a 5-minute ASAP advantage beats a 20-mile distance advantage.
