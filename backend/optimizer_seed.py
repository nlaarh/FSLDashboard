"""Seed realistic optimizer test data into DuckDB.

Generates 3 days × 96 runs/day (every 15 min) for territory 076DO,
grounded in the real Request/Response JSON payloads.

Usage:
    python optimizer_seed.py           # seeds last 3 days
    python optimizer_seed.py --clear   # wipe existing data first
"""

import sys
import random
import uuid
import argparse
from datetime import datetime, timezone, timedelta

import optimizer_db

# ── Seed constants (from real JSON files) ─────────────────────────────────────

TERRITORY_ID   = '0HhOy000000XFMrKAO'
TERRITORY_NAME = '076DO'
POLICY_ID      = 'a1ROy000005PpSfMAK'
POLICY_NAME    = 'Closest Driver'

# Real driver IDs/names from org roster
DRIVERS = [
    ('0HnOy0000007YeTKAU', 'Brandon Hadley'),
    ('0HnOy0000007YeUKAU', 'Raymond Rohauer'),
    ('0HnOy0000007YeVKAU', 'Ryan Burns'),
    ('0HnOy0000007YeWKAU', 'Adam Lucas'),
    ('0HnOy0000007YeXKAU', 'Anthony Mickiewicz'),
    ('0HnOy0000007YeYKAU', 'Austin Dobucki'),
    ('0HnOy0000007YeZKAU', 'Ben Tremblay'),
    ('0HnOy0000007YfAKAU', 'Daniel Rohauer'),
    ('0HnOy0000007YfBKAU', 'Hunter Mitchell'),
    ('0HnOy0000007YfCKAU', 'Connor Kurdziel'),
    ('0HnOy0000007YfDKAU', 'Kevin OBrien'),
    ('0HnOy0000007YfEKAU', 'Mike Szymanski'),
]

# SA pool — some recur across runs (normal: optimizer re-evaluates full horizon)
SA_POOL = [
    # (id, number, work_type, requires_special_skill)
    ('08pOy00000H1SZzIAN', 'SA-779531', 'Battery', False),
    ('08pOy00000H1SlFIAV', 'SA-779544', 'Tow Pick-Up', False),
    ('08pOy00000H1SaAIAV', 'SA-779534', 'Winch Out', True),    # recurring trouble SA
    ('08pOy00000H1SbBIAV', 'SA-779502', 'Tire Change', False),
    ('08pOy00000H1ScCIAV', 'SA-779488', 'Lockout', False),
    ('08pOy00000H1SdDIAV', 'SA-779561', 'Battery', False),
    ('08pOy00000H1SeEIAV', 'SA-779577', 'Tow Pick-Up', False),
    ('08pOy00000H1SfFIAV', 'SA-779590', 'Lockout', False),
    ('08pOy00000H1SgGIAV', 'SA-779612', 'Battery', False),
    ('08pOy00000H1ShHIAV', 'SA-779623', 'Passenger Transport', True),  # rule violation SA
    ('08pOy00000H1SiIIAV', 'SA-779635', 'Tire Change', False),
    ('08pOy00000H1SjJIAV', 'SA-779648', 'Battery', False),
    ('08pOy00000H1SkKIAV', 'SA-779659', 'Lockout', False),
    ('08pOy00000H1SlLIAV', 'SA-779671', 'Tow Pick-Up', False),
    ('08pOy00000H1SmMIAV', 'SA-779684', 'Battery', False),
    ('08pOy00000H1SnNIAV', 'SA-779695', 'Winch Out', True),
]

# Drivers that have the special skill (winch/passenger transport)
SKILLED_DRIVERS = {'0HnOy0000007YeTKAU', '0HnOy0000007YeVKAU', '0HnOy0000007YfAKAU'}

# Drivers absent during the seed period (creates interesting exclusion patterns)
ABSENT_DRIVERS_DAY_1 = {'0HnOy0000007YeYKAU', '0HnOy0000007YfCKAU'}  # Austin, Connor
ABSENT_DRIVERS_DAY_3 = {'0HnOy0000007YeWKAU'}  # Adam on day 3

# Territory-excluded drivers (2 drivers only cover a different zone — excluded for most SAs)
TERRITORY_LIMITED = {'0HnOy0000007YfDKAU', '0HnOy0000007YfEKAU'}  # Kevin, Mike

# Per-driver skill lists (every driver has the basics; only SKILLED_DRIVERS have special)
BASIC_SKILLS    = ['Battery', 'Tire Change', 'Lockout', 'Tow Pick-Up']
SPECIAL_SKILLS  = ['Winch Out', 'Passenger Transport']

# Per-driver home territory (most are 076DO; territory-limited live elsewhere)
DRIVER_HOME_TERRITORY = {
    '0HnOy0000007YfDKAU': '077DO',  # Kevin — outside 076DO
    '0HnOy0000007YfEKAU': '077DO',  # Mike — outside 076DO
}

def _driver_skills(driver_id: str) -> str:
    """Return comma-separated skill list for a driver."""
    skills = list(BASIC_SKILLS)
    if driver_id in SKILLED_DRIVERS:
        skills.extend(SPECIAL_SKILLS)
    return ', '.join(skills)


def _driver_territory(driver_id: str) -> str:
    """Return the driver's home territory name."""
    return DRIVER_HOME_TERRITORY.get(driver_id, TERRITORY_NAME)

UNSCHEDULED_REASONS = [
    'Rule Violation — Assign Passenger Transport Tows by Truck Passenger Space',
    'Rule Violation — Skill Requirement: Winch Out Certified',
    'No eligible driver within overtime limits',
    'Optimization: lower priority than scheduled work',
]


def _run_id(day_offset: int, slot_idx: int) -> str:
    """Deterministic fake SF ID — a1J prefix like real OR records."""
    return f"a1JSEEDd{day_offset:02d}s{slot_idx:03d}SEED00"


def _pick_sas(hour: int) -> list[tuple]:
    """Return a subset of SA_POOL realistic for this hour."""
    if 0 <= hour < 6:
        # Overnight: very few active SAs (just context horizon holds)
        return random.sample(SA_POOL[:8], k=random.randint(2, 5))
    elif 6 <= hour < 9:
        # Morning ramp-up
        return random.sample(SA_POOL, k=random.randint(5, 10))
    elif 9 <= hour < 18:
        # Peak — most SAs visible
        return random.sample(SA_POOL, k=random.randint(10, 16))
    else:
        # Evening wind-down
        return random.sample(SA_POOL, k=random.randint(4, 8))


def _pick_drivers(run_dt: datetime, absent_set: set) -> list[tuple]:
    """Return on-shift drivers for this run (8 per shift, 12 overlap at peak)."""
    hour = run_dt.hour
    if 6 <= hour < 18:
        n = random.randint(9, 12)
    elif 18 <= hour < 22:
        n = random.randint(6, 9)
    else:
        n = random.randint(3, 6)
    eligible = [d for d in DRIVERS if d[0] not in absent_set]
    return random.sample(eligible, k=min(n, len(eligible)))


def _travel_time(dist_mi: float) -> float:
    """Estimate travel minutes from miles at ~25 mph with some variance."""
    return round(dist_mi / 25.0 * 60 * random.uniform(0.8, 1.3), 1)


def _build_run(day_offset: int, slot_idx: int, run_dt: datetime, rng: random.Random) -> dict:
    """Build one complete run dict: run_row, sa_decisions, driver_verdicts."""

    run_id = _run_id(day_offset, slot_idx)
    run_at_str = run_dt.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Determine absent/limited drivers for this day
    absent = ABSENT_DRIVERS_DAY_1 if day_offset == 0 else (
             ABSENT_DRIVERS_DAY_3 if day_offset == 2 else set())

    active_drivers = _pick_drivers(run_dt, absent)
    active_sas = _pick_sas(run_dt.hour)

    horizon_start = (run_dt - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    horizon_end   = (run_dt + timedelta(hours=47)).strftime('%Y-%m-%dT%H:%M:%SZ')

    # Pre-KPI: how many were scheduled before this run
    pre_sched  = rng.randint(max(0, len(active_sas) - 4), len(active_sas))
    pre_travel = rng.randint(200, 1800)

    sa_decisions   = []
    driver_verdicts = []
    post_sched = 0

    for (sa_id, sa_number, work_type, needs_skill) in active_sas:
        is_passenger_transport = work_type == 'Passenger Transport'
        is_winch = work_type == 'Winch Out'

        # Determine which drivers can serve this SA
        eligible_drivers = []
        for (drv_id, drv_name) in active_drivers:
            territory_ok = drv_id not in TERRITORY_LIMITED or rng.random() > 0.7
            skill_ok     = (not needs_skill) or (drv_id in SKILLED_DRIVERS)
            absent_ok    = drv_id not in absent

            if territory_ok and skill_ok and absent_ok:
                eligible_drivers.append((drv_id, drv_name))

        # Decide action
        if is_passenger_transport and not eligible_drivers:
            # No driver has required skill → rule violation every time
            action           = 'Unscheduled'
            unsch_reason     = 'Rule Violation — Assign Passenger Transport Tows by Truck Passenger Space'
            winner_drv_id    = None
            winner_drv_name  = None
            winner_tt        = None
            winner_dist      = None
        elif is_winch and rng.random() < 0.35:
            # Winch sometimes violates too (only 3 skilled drivers)
            action           = 'Unscheduled'
            unsch_reason     = 'Rule Violation — Skill Requirement: Winch Out Certified'
            winner_drv_id    = None
            winner_drv_name  = None
            winner_tt        = None
            winner_dist      = None
        elif eligible_drivers:
            action       = 'Scheduled'
            unsch_reason = None
            post_sched  += 1
            # Winner = closest (lowest travel time), with some randomness
            winner_dist  = round(rng.uniform(1.5, 18.0), 2)
            winner_tt    = _travel_time(winner_dist)
            winner_drv_id, winner_drv_name = rng.choice(eligible_drivers)
        else:
            action           = 'Unscheduled'
            unsch_reason     = rng.choice(UNSCHEDULED_REASONS)
            winner_drv_id    = None
            winner_drv_name  = None
            winner_tt        = None
            winner_dist      = None

        sa_decisions.append({
            'id':                     f"{run_id}_{sa_id}",
            'run_id':                 run_id,
            'sa_id':                  sa_id,
            'sa_number':              sa_number,
            'sa_work_type':           work_type,
            'action':                 action,
            'unscheduled_reason':     unsch_reason,
            'winner_driver_id':       winner_drv_id,
            'winner_driver_name':     winner_drv_name,
            'winner_travel_time_min': winner_tt,
            'winner_travel_dist_mi':  winner_dist,
            'run_at':                 run_at_str,
        })

        # Driver verdicts — every active driver gets evaluated
        for (drv_id, drv_name) in active_drivers:
            is_winner = (drv_id == winner_drv_id)
            absent_here = drv_id in absent

            if absent_here:
                status = 'excluded'
                reason = 'absent'
            elif drv_id in TERRITORY_LIMITED and rng.random() < 0.7:
                status = 'excluded'
                reason = 'territory'
            elif needs_skill and drv_id not in SKILLED_DRIVERS:
                status = 'excluded'
                reason = 'skill'
            elif is_winner:
                status = 'winner'
                reason = None
            else:
                status = 'eligible'
                reason = None

            # Synthetic per-driver distance — winner is closest, others farther.
            # Real optimizer JSON only includes the winner's travel; for richer
            # demo we fabricate plausible distances for every considered driver.
            if is_winner:
                t_dist = winner_dist
                t_time = winner_tt
            elif status == 'eligible':
                # Runner-up: 1.2× to 3× winner distance
                t_dist = round(winner_dist * rng.uniform(1.2, 3.0), 2) if winner_dist else round(rng.uniform(8, 30), 2)
                t_time = _travel_time(t_dist)
            else:
                # Excluded: still report a rough distance for context (no time)
                t_dist = round(rng.uniform(5, 40), 2)
                t_time = None

            driver_verdicts.append({
                'id':               f"{run_id}_{sa_id}_{drv_id}",
                'run_id':           run_id,
                'sa_id':            sa_id,
                'driver_id':        drv_id,
                'driver_name':      drv_name,
                'status':           status,
                'exclusion_reason': reason,
                'travel_time_min':  t_time,
                'travel_dist_mi':   t_dist,
                'driver_skills':    _driver_skills(drv_id),
                'driver_territory': _driver_territory(drv_id),
                'run_at':           run_at_str,
            })

    unscheduled_count = sum(1 for d in sa_decisions if d['action'] == 'Unscheduled')

    run_row = {
        'id':                  run_id,
        'name':                f"Seed-076DO-d{day_offset}-s{slot_idx}",
        'territory_id':        TERRITORY_ID,
        'territory_name':      TERRITORY_NAME,
        'policy_id':           POLICY_ID,
        'policy_name':         POLICY_NAME,
        'run_at':              run_at_str,
        'horizon_start':       horizon_start,
        'horizon_end':         horizon_end,
        'resources_count':     len(active_drivers),
        'services_count':      len(active_sas),
        'pre_scheduled':       pre_sched,
        'post_scheduled':      post_sched,
        'unscheduled_count':   unscheduled_count,
        'pre_travel_time_s':   pre_travel,
        'post_travel_time_s':  max(0, pre_travel + rng.randint(-300, 300)),
        'pre_response_avg_s':  round(rng.uniform(18000, 28000), 1),
        'post_response_avg_s': round(rng.uniform(16000, 26000), 1),
    }

    return run_row, sa_decisions, driver_verdicts


def _insert_batch(runs_data: list[tuple]):
    """Bulk-insert a batch of (run_row, sa_decisions, driver_verdicts) tuples."""
    with optimizer_db.get_conn() as conn:
        for run_row, sa_decisions, driver_verdicts in runs_data:
            conn.execute("""
                INSERT OR IGNORE INTO opt_runs
                    (id, name, territory_id, territory_name, policy_id, policy_name,
                     run_at, horizon_start, horizon_end,
                     resources_count, services_count,
                     pre_scheduled, post_scheduled, unscheduled_count,
                     pre_travel_time_s, post_travel_time_s,
                     pre_response_avg_s, post_response_avg_s)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [
                run_row['id'], run_row['name'], run_row['territory_id'],
                run_row['territory_name'], run_row['policy_id'], run_row['policy_name'],
                run_row['run_at'], run_row['horizon_start'], run_row['horizon_end'],
                run_row['resources_count'], run_row['services_count'],
                run_row['pre_scheduled'], run_row['post_scheduled'], run_row['unscheduled_count'],
                run_row['pre_travel_time_s'], run_row['post_travel_time_s'],
                run_row['pre_response_avg_s'], run_row['post_response_avg_s'],
            ])

            if sa_decisions:
                conn.executemany("""
                    INSERT OR IGNORE INTO opt_sa_decisions
                        (id, run_id, sa_id, sa_number, sa_work_type, action,
                         unscheduled_reason, winner_driver_id, winner_driver_name,
                         winner_travel_time_min, winner_travel_dist_mi, run_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, [[
                    d['id'], d['run_id'], d['sa_id'], d['sa_number'], d['sa_work_type'],
                    d['action'], d['unscheduled_reason'], d['winner_driver_id'],
                    d['winner_driver_name'], d['winner_travel_time_min'],
                    d['winner_travel_dist_mi'], d['run_at'],
                ] for d in sa_decisions])

            if driver_verdicts:
                conn.executemany("""
                    INSERT OR IGNORE INTO opt_driver_verdicts
                        (id, run_id, sa_id, driver_id, driver_name,
                         status, exclusion_reason, travel_time_min, travel_dist_mi,
                         driver_skills, driver_territory, run_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, [[
                    v['id'], v['run_id'], v['sa_id'], v['driver_id'], v['driver_name'],
                    v['status'], v['exclusion_reason'], v['travel_time_min'],
                    v['travel_dist_mi'], v['driver_skills'], v['driver_territory'],
                    v['run_at'],
                ] for v in driver_verdicts])


def seed(clear: bool = False):
    optimizer_db.init_db()

    if clear:
        with optimizer_db.get_conn() as conn:
            conn.execute("DELETE FROM opt_driver_verdicts")
            conn.execute("DELETE FROM opt_sa_decisions")
            conn.execute("DELETE FROM opt_runs")
        print("Cleared existing data.")

    # Also seed resource names so chat can resolve IDs to names
    optimizer_db.upsert_resource_names([{'id': did, 'name': dname} for did, dname in DRIVERS])

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    rng = random.Random(42)  # deterministic seed for reproducibility

    total_runs = 0
    total_sas  = 0
    total_verd = 0

    for day_offset in range(3):  # 0 = 3 days ago, 1 = 2 days ago, 2 = yesterday
        day_start = now - timedelta(days=3 - day_offset)
        batch = []

        for slot_idx in range(96):  # 96 × 15-min = 24 hours
            run_dt = day_start + timedelta(minutes=15 * slot_idx)
            run_row, sa_dec, drv_verd = _build_run(day_offset, slot_idx, run_dt, rng)
            batch.append((run_row, sa_dec, drv_verd))
            total_sas  += len(sa_dec)
            total_verd += len(drv_verd)
            total_runs += 1

            # Insert in chunks of 24 runs (every 6 hours)
            if len(batch) >= 24:
                _insert_batch(batch)
                batch = []

        if batch:
            _insert_batch(batch)

        date_label = (day_start).strftime('%Y-%m-%d')
        print(f"  Day {day_offset + 1}/3 ({date_label}): 96 runs inserted")

    print(f"\nDone. Inserted {total_runs} runs, {total_sas} SA decisions, {total_verd} driver verdicts.")
    print(f"DB: {optimizer_db.DB_PATH}")

    # Quick stats
    with optimizer_db.get_conn(read_only=True) as conn:
        n_runs   = conn.execute("SELECT COUNT(*) FROM opt_runs").fetchone()[0]
        n_sas    = conn.execute("SELECT COUNT(*) FROM opt_sa_decisions").fetchone()[0]
        n_unsch  = conn.execute("SELECT COUNT(*) FROM opt_sa_decisions WHERE action='Unscheduled'").fetchone()[0]
        n_verd   = conn.execute("SELECT COUNT(*) FROM opt_driver_verdicts").fetchone()[0]
        n_excl   = conn.execute("SELECT COUNT(*) FROM opt_driver_verdicts WHERE status='excluded'").fetchone()[0]

    print(f"\nDB totals:")
    print(f"  opt_runs:           {n_runs:,}")
    print(f"  opt_sa_decisions:   {n_sas:,}  ({n_unsch:,} unscheduled)")
    print(f"  opt_driver_verdicts:{n_verd:,}  ({n_excl:,} excluded)")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--clear', action='store_true', help='Wipe data before seeding')
    args = parser.parse_args()
    seed(clear=args.clear)
