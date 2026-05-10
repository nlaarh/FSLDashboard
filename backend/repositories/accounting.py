"""Accounting repository — rates, bonus tiers, and WOA reviews."""

import logging

import db_adapter

log = logging.getLogger("repo.accounting")


def get_accounting_rates() -> list[dict]:
    """Get all accounting reference rates, ordered by category then code."""
    with db_adapter.reader() as db:
        db.execute(
            """
            SELECT code, label, value, unit, notes, category, updated_at
            FROM accounting_rates
            ORDER BY category, code
            """
        )
        rows = db.fetchall()
    return rows


def get_accounting_rates_dict() -> dict:
    """Get accounting rates as {code: value} for quick lookup in audit logic."""
    with db_adapter.reader() as db:
        db.execute("SELECT code, value FROM accounting_rates")
        rows = db.fetchall()
    return {row["code"]: row["value"] for row in rows}


def set_accounting_rate(code: str, value: float) -> dict:
    """Update the value for a single accounting rate. Returns the updated row."""
    with db_adapter.writer() as db:
        db.execute(
            "UPDATE accounting_rates SET value = %s, updated_at = CURRENT_TIMESTAMP WHERE code = %s",
            (value, code),
        )
        db.execute(
            """
            SELECT code, label, value, unit, notes, category, updated_at
            FROM accounting_rates
            WHERE code = %s
            """,
            (code,),
        )
        row = db.fetchone()
    if not row:
        raise ValueError(f"Unknown accounting rate code: {code}")
    return row


def get_bonus_tiers() -> list[dict]:
    """Get all bonus tiers sorted by min_pct descending (highest first)."""
    with db_adapter.reader() as db:
        db.execute(
            """
            SELECT id, min_pct, bonus_per_sa, label, sort_order
            FROM bonus_tiers
            ORDER BY min_pct DESC
            """
        )
        rows = db.fetchall()
    return rows


def set_bonus_tiers(tiers: list):
    """Replace all bonus tiers. Each tier: {min_pct, bonus_per_sa, label}."""
    with db_adapter.writer() as db:
        db.execute("DELETE FROM bonus_tiers")
        for i, t in enumerate(tiers):
            db.execute(
                """
                INSERT INTO bonus_tiers (min_pct, bonus_per_sa, label, sort_order)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    t["min_pct"],
                    t["bonus_per_sa"],
                    t.get("label", f"≥{t['min_pct']}%"),
                    i,
                ),
            )


def bonus_for_pct(pct) -> tuple:
    """Return (bonus_per_sa, tier_label) for a given Technician Totally Satisfied %.
    Reads tiers from DB. Returns (0, '<lowest%') if below all tiers."""
    if pct is None:
        return 0, "N/A"
    tiers = get_bonus_tiers()
    for t in tiers:  # sorted descending by min_pct
        if pct >= t["min_pct"]:
            return t["bonus_per_sa"], t["label"]
    lowest = tiers[-1]["min_pct"] if tiers else 92
    return 0, f"<{lowest}%"


def get_woa_reviews_batch(woa_ids: list) -> dict:
    """Fetch review decisions for a batch of WOA IDs."""
    if not woa_ids:
        return {}
    placeholders = ",".join(["%s"] * len(woa_ids))
    with db_adapter.reader() as db:
        db.execute(
            f"""
            SELECT woa_id, status, note, reviewer, reviewed_at
            FROM woa_reviews
            WHERE woa_id IN ({placeholders})
            """,
            tuple(woa_ids),
        )
        rows = db.fetchall()
    return {row["woa_id"]: row for row in rows}


def set_woa_review(woa_id: str, status: str, note: str = "", reviewer: str = "") -> dict:
    """Upsert a WOA review decision."""
    with db_adapter.writer() as db:
        db.execute(
            """
            INSERT INTO woa_reviews (woa_id, status, note, reviewer, reviewed_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (woa_id) DO UPDATE SET
                status = EXCLUDED.status,
                note = EXCLUDED.note,
                reviewer = EXCLUDED.reviewer,
                reviewed_at = CURRENT_TIMESTAMP
            """,
            (woa_id, status, note or "", reviewer or ""),
        )
    return {"woa_id": woa_id, "status": status, "note": note, "reviewer": reviewer}
