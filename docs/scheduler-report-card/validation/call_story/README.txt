Call Story validation scripts (Henry, 2026-10-03). Read-only SOQL, sequential. Run from FSLAPP/ with ./.venv/bin/python3.
  story.py <SA Id>                         -> one call: SA, WOLI, WO, sibling SAs, full SAHistory (Old/New), AR, SMS_Send_Log__c, Survey_Result__c
  show.py  <story_SA-xxxx.json>            -> readable ET timeline of a story pull
  base.py  <territoryId> <tag> <fromZ> <toZ> -> SA list + Status/ServiceTerritory/ERS_Assigned_Resource__c history (COUNT-checked)
  dwell.py <base_tag.json> [h]             -> stage durations and time-in-status percentiles (+ by 4h block with 'h')
Golden calls: SA-1073520 (GOOD), SA-1074927 (BOUNCED), SA-1074304 (CAPACITY_SHORT), SA-1067245 (Towbook cascade + SPOT).
Grid/SPOT and busy-vs-free numbers in call-story-spec.md §5/§6 came from one-off pulls of
ServiceAppointmentHistory Field='ServiceTerritory' for 2026-09-28 (4,538 rows, COUNT-checked) and from base_wny_wk.json.
