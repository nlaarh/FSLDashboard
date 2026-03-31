# FSLAPP Documentation

Technical reference for the React + FastAPI dashboard application.
**This is the OUTPUT layer** — reads from the Salesforce org (see `../sf/`) and presents operational insights.

## Documents

### Architecture
- **[fslapp_architecture.md](fslapp_architecture.md)** — Stack, directory layout, auth, map system, cache, driver identification, PTA advisor, frontend patterns
- **[coding_rules.md](coding_rules.md)** — Mandatory checklist: Drop-Off exclusion, Towbook differentiation, work-type separation, DST, case sensitivity

### Metrics & Analytics
- **[METRICS_KNOWLEDGE_BASE.md](METRICS_KNOWLEDGE_BASE.md)** — All metric definitions, calculation logic, data sources
- **[weather_analysis.md](weather_analysis.md)** — Weather integration, severity classification, volume correlation

### Deployment
- **[deployment_lessons.md](deployment_lessons.md)** — Azure pipeline, Oryx caching, critical lessons
- **[DEPLOYMENT.md](DEPLOYMENT.md)** — Initial deployment setup
- **[DEPLOYMENT_COMPLETE.md](DEPLOYMENT_COMPLETE.md)** — Deployment completion checklist
- **[DEPLOYMENT_STATUS.md](DEPLOYMENT_STATUS.md)** — Current deployment state
- **[DEPLOY_INSTRUCTIONS.md](DEPLOY_INSTRUCTIONS.md)** — Step-by-step deploy guide
- **[MANUAL_DEPLOY.md](MANUAL_DEPLOY.md)** — Manual deployment procedure

### Design
- **[REDESIGN.md](REDESIGN.md)** — UI redesign notes

## Dependency on SF Org Docs
FSLAPP features should always be designed with SF org knowledge as input:
- **Garage Dashboard** → needs: operating_model, priority_matrix_cascade, pta_settings
- **Performance Metrics** → needs: sf_data_model (SA fields), dispatch_routing (ATA vs PTA)
- **PTA Advisor** → needs: pta_settings, fsl_scheduler_knowledge
- **Map/Dispatch View** → needs: dispatch_routing_mulesoft, priority_matrix_cascade
- **Queue Board** → needs: operating_model (SA lifecycle), sf_org_automation (status transitions)
