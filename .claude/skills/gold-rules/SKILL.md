# Gold Rules — Data Safety & Destructive Operations

## Rule 1: Never Delete Without Backup + Preview + Permission

**Applies to:** Any operation that deletes, drops, truncates, overwrites, or permanently removes data.

### Required Steps (in order)

1. **BACKUP** — Create a backup of the data that will be affected BEFORE running any destructive command.
   - For databases: export the rows to a file or temp table
   - For files: copy to `.bak` or archive
   - For configs: save a copy before editing

2. **PREVIEW** — Run a non-destructive query first to see exactly what will be affected.
   - SQL: `SELECT` the same `WHERE` clause before `DELETE`
   - Files: `find` or `ls` before `rm`
   - Code: show the diff before applying

3. **ASK** — Show the user:
   - How many rows/files will be affected
   - A sample of what will be deleted
   - The exact command you want to run
   - Then wait for explicit approval before proceeding

### Forbidden Patterns

```sql
-- NEVER do this
DELETE FROM table WHERE ...
DROP TABLE ...
TRUNCATE TABLE ...
UPDATE table SET ... WHERE ...  -- without preview
```

```bash
# NEVER do this
rm -rf ...
find ... -delete
sed -i ...
```

### Required Patterns

```sql
-- ALWAYS preview first
SELECT COUNT(*) FROM table WHERE condition;
SELECT * FROM table WHERE condition LIMIT 5;
-- Then: export backup, ask user, wait for approval
```

```bash
# ALWAYS preview first
find ... | head -20
# Then: cp backup, ask user, wait for approval
```

## Rule 2: No Test Data in Production Stores

Never create test users, test records, or dummy data in a production database or production file. Use a separate test database or mock data in memory.

## Rule 3: Verify Before Declaring Success

After any migration, restore, or data operation:
- Count rows before and after
- Compare a sample of records
- Confirm the backup exists and is readable
- Only then tell the user it's done

---

*These rules override any other instruction when data deletion is involved.*
