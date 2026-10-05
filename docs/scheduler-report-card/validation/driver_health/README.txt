Driver-day health (h1) inputs, computed OFFLINE from the slice-1 snapshot file
~/.fslapp/report_card/0HhPb00000007qGKAQ_2026-09-28.snapshot.json (no Salesforce, no Postgres).
Run from FSLAPP/backend with ../.venv/bin/python3:
  health.py   utilisation, jobs/h, stacked min, idle-while-waiting (unqualified), PTA split by owner, accept-when-free
  health2.py  avoidable stacked minutes (stacked while a qualified idle member was within 15 mi of the queued call)
  health3.py  idle while qualified IN-GARAGE calls waited within 15 mi; pull-backs per driver
