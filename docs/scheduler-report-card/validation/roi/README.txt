Henry's ROI-baseline scripts (roi-baseline.md). Analysis code, not app code. Read-only SOQL, strictly sequential.
Run from FSLAPP/ with ./.venv/bin/python3. Each script reads/writes its JSON next to itself (copy to a scratch dir first;
never commit the JSON outputs: they hold SA-level data).
  build_all.py   20 garage-day snapshots via report_card_build (Ruby's builder) -> ~/.fslapp/report_card/, + ERS_PTA__c history
                 (adds a 60 s cool-down retry and 40-id GPS batches; the 076DO ServiceResourceHistory read timed out once at 45 s)
  analyze.py     snapshots -> rows.json (per-SA ROI fields; r1 verdicts; idle-while-waited minute sweep; member cancels)
  summarize.py   rows.json -> summary.json (per-day measures, weekday/weekend averages, month extrapolation, survey link)
  surveys.py     SA -> WOLI -> WorkOrder -> Survey_Result__c (batched, COUNT() checked)
  report.py      markdown tables in roi-baseline.md section 6 (+ conservative miles drive-time check)
  r2.py / r2c.py r1 vs r2 (original-promise PTA, cs1 5 s window); PTA edits after 5 s; pull-back actors; WNY S6 baseline
  s789.py        S7 / S8 segment baselines from the same snapshots (call-story O5)
  flowkeys.py, flows_prod.py   prod active Flow versions (Tooling API) vs local 8/13 metadata (call-story O7)
  bounce.py, byactor.py, drive.py   checks quoted in the caveats
  build_all2.py  section 11 extension: 800 Central Fleet + 421 Action Towing, same 10 Sep dates (builder rc-build-1.1)
  ng.py, ldc421.py   421 not-graded diagnosis (no GPS) and who made its LATE_DESPITE_CAPACITY picks
  integ*.py      integration-account verdict (metrics-spec B4a): pick timing vs SA creation / SF optimizer runs / FSL
                 auto-schedule batch windows (AsyncApexJob, last 2 days), user profile + permission sets, prod class bodies
