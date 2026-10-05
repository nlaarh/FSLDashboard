Henry's validation scripts for metrics-spec.md (read-only SOQL only). Analysis code, not app code.
They need FSLAPP/.venv and backend/sf_client.py. Pulls are cached as JSON in $RC_SCRATCH (default /tmp/rc).
  pull.py  <territoryId> <tag-suffix> <dayStartUTC> <dayEndUTC>       -> SA, AssignedResource, SAHistory
  pull2.py <territoryId> <tag-suffix> <dayStartUTC> <dayEndUTC> <histStart> <histEnd> -> members, AssetHistory, GPS, absences, skills
  q17.py (WOLI SkillRequirement), q23.py (truck capabilities), then:
  SKMODE=combo python analyze.py <tag> <dayStartUTC> <dayEndUTC>
The tag is the last 4 characters of the territory Id + "_" + suffix (e.g. GKAQ_0928).
output_*.txt files are the exact outputs quoted in metrics-spec.md.
