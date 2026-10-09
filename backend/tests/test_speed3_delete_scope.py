"""Owner rule: the speed batch 3 code may only ever delete from its own four new tables, and never drop, alter or truncate."""
import re
from pathlib import Path

OWN_TABLES = {'driver_gps_points', 'driver_gps_samples', 'facts_day', 'facts_garage_day'}
FILES = ['gps_store.py', 'facts_store.py', 'facts_build.py', 'facts_job.py', 'speed3_db.py']
BACKEND = Path(__file__).resolve().parent.parent


def _sources():
    for name in FILES:
        path = BACKEND / name
        if path.exists():
            yield name, path.read_text()


def test_every_delete_targets_only_our_own_tables():
    found = 0
    for name, src in _sources():
        for table in re.findall(r'DELETE\s+FROM\s+(\w+)', src, re.I):
            found += 1
            assert table in OWN_TABLES, f'{name} deletes from {table}'
    assert found > 0


def test_no_drop_alter_truncate_or_update_of_other_tables():
    for name, src in _sources():
        assert not re.search(r'\b(DROP|TRUNCATE)\s+(TABLE|SCHEMA|INDEX)\b', src, re.I), name
        assert not re.search(r'\bALTER\s+TABLE\b', src, re.I), name
        for table in re.findall(r'\bUPDATE\s+(\w+)\s+SET\b', src, re.I):
            assert table in OWN_TABLES, f'{name} updates {table}'
