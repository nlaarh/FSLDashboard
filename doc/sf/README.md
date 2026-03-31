# Salesforce Org Documentation

Complete technical reference for the AAA ERS Salesforce FSL org implementation.
**This is the INPUT layer** — FSLAPP reads from this org, so understanding it is prerequisite to building good features.

## Documents

### Core Architecture
- **[sf_org_automation.md](sf_org_automation.md)** — 27 Apex triggers, 377 Flows, field usage map, SA lifecycle state machine, dispatch routing, cost rollups
- **[sf_data_model.md](sf_data_model.md)** — Complete org data model (all domains, all objects, all fields)
- **[operating_model.md](operating_model.md)** — Two-channel dispatch (Fleet vs Towbook), call flow, driver login, SA lifecycle, performance metrics

### Dispatch & Routing
- **[dispatch_routing_mulesoft.md](dispatch_routing_mulesoft.md)** — How Mulesoft dispatches (bypasses FSL scheduler), Field Services vs Towbook decision, cascade mechanics, platform events, data elements
- **[priority_matrix_cascade.md](priority_matrix_cascade.md)** — 1,100-record Territory Priority Matrix: worktype-aware cascade, priority levels P2-P10, regional fallbacks, grid zone naming
- **[pta_settings.md](pta_settings.md)** — 180 PTA records (promised time to member), worktype overrides, entitlement structure (835K active)
- **[fleet_dispatch_analysis.md](fleet_dispatch_analysis.md)** — Auto vs manual dispatch findings, weekly %, SOQL lessons

### Scheduling Engine
- **[scheduler_policy_analysis.md](scheduler_policy_analysis.md)** — Reverse-engineered auto-scheduler policy from 349 SAs: Travel-heavy ("Closest Driver"), GPS→STM auto-sync discovery, why assignments vary
- **[fsl_scheduler_knowledge.md](fsl_scheduler_knowledge.md)** — Scoring formula, ASAP/Travel objectives, travel calc, this org's 90/10 weight problem
- **[fsl_travel_scoring.md](fsl_travel_scoring.md)** — Exact travel time calculation (aerial/Haversine), driver scoring formula, policy weights (ASAP 9,000 / Travel 1,000), worked examples, candidate pool generation, why closest driver loses 74% of the time
- **[fsl_scheduling_config.md](fsl_scheduling_config.md)** — Complete FSL Admin Settings dump: Automated Scheduling (recipes all inactive), General Logic (sliding, pin criteria, geocode delay), Optimization jobs (1 active), Dispatch (auto-dispatch OFF). No global default policy exists.

### Operational Data
- **[service_resource_roster.md](service_resource_roster.md)** — Driver roster (Fleet, On-Platform, Off-Platform)
- **[dispatcher_roster.md](dispatcher_roster.md)** — Human dispatchers
- **[CLOSEST_DRIVER_CHALLENGE.md](CLOSEST_DRIVER_CHALLENGE.md)** — Why closest driver is picked only 26% of the time

## Key Facts
- **FSL Scheduler NOT used for dispatch** — Mulesoft's ERS_SA_AutoSchedule does its own logic
- **74% Towbook / 26% Fleet** dispatch split
- **Priority Matrix** routes calls by geography + worktype, not FSL scheduler
- **PTA** = promised time to member (60-120 min depending on garage)
- **Entitlements** = member coverage (Plus/Basic), gates service eligibility
