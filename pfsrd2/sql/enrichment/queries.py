"""CRUD operations for the enrichment database."""

import json
from datetime import UTC, datetime


def _now():
    return datetime.now(UTC).isoformat()


# --- Ability record CRUD ---


def insert_ability_record(curs, name, identity_hash, raw_json):
    """Insert a new ability record. Returns the ability_id."""
    now = _now()
    sql = "\n".join(
        [
            "INSERT INTO ability_records",
            " (name, identity_hash, raw_json, created_at, updated_at)",
            " VALUES (?, ?, ?, ?, ?)",
        ]
    )
    curs.execute(sql, (name, identity_hash, raw_json, now, now))
    return curs.lastrowid


def fetch_ability_by_hash(curs, identity_hash):
    sql = "SELECT * FROM ability_records WHERE identity_hash = ?"
    curs.execute(sql, (identity_hash,))
    return curs.fetchone()


def fetch_ability_by_id(curs, ability_id):
    sql = "SELECT * FROM ability_records WHERE ability_id = ?"
    curs.execute(sql, (ability_id,))
    return curs.fetchone()


def fetch_abilities_by_name(curs, name):
    sql = "SELECT * FROM ability_records WHERE name = ?"
    curs.execute(sql, (name,))
    return curs.fetchall()


def fetch_unenriched(curs):
    """Fetch all ability records that haven't been enriched yet."""
    sql = "SELECT * FROM ability_records WHERE enrichment_version IS NULL"
    curs.execute(sql)
    return curs.fetchall()


def fetch_stale(curs):
    """Fetch all ability records marked as stale."""
    sql = "SELECT * FROM ability_records WHERE stale = 1"
    curs.execute(sql)
    return curs.fetchall()


def fetch_needing_enrichment(curs, current_version):
    """Fetch records that need (re-)enrichment.

    Returns unenriched records and records with enrichment_version
    below current_version, excluding human_verified records.
    """
    sql = "\n".join(
        [
            "SELECT * FROM ability_records",
            " WHERE human_verified = 0",
            " AND (enrichment_version IS NULL",
            "      OR enrichment_version < ?)",
        ]
    )
    curs.execute(sql, (current_version,))
    return curs.fetchall()


def update_enriched_json(curs, ability_id, enriched_json, enrichment_version, extraction_method):
    """Store enrichment results for an ability record."""
    sql = "\n".join(
        [
            "UPDATE ability_records",
            " SET enriched_json = ?,",
            "     enrichment_version = ?,",
            "     extraction_method = ?,",
            "     stale = 0,",
            "     updated_at = ?",
            " WHERE ability_id = ?",
        ]
    )
    curs.execute(sql, (enriched_json, enrichment_version, extraction_method, _now(), ability_id))


def mark_stale(curs, ability_id, new_raw_json):
    """Mark a record as stale and update its raw_json."""
    sql = "\n".join(
        [
            "UPDATE ability_records",
            " SET stale = 1,",
            "     raw_json = ?,",
            "     updated_at = ?",
            " WHERE ability_id = ?",
        ]
    )
    curs.execute(sql, (new_raw_json, _now(), ability_id))


def mark_human_verified(curs, ability_id, verified=True):
    sql = "\n".join(
        [
            "UPDATE ability_records",
            " SET human_verified = ?,",
            "     updated_at = ?",
            " WHERE ability_id = ?",
        ]
    )
    curs.execute(sql, (1 if verified else 0, _now(), ability_id))


def update_identity_hash(curs, ability_id, new_hash, new_raw_json):
    """Update the identity hash when the ability content changes."""
    sql = "\n".join(
        [
            "UPDATE ability_records",
            " SET identity_hash = ?,",
            "     raw_json = ?,",
            "     stale = 1,",
            "     updated_at = ?",
            " WHERE ability_id = ?",
        ]
    )
    curs.execute(sql, (new_hash, new_raw_json, _now(), ability_id))


# --- Creature link CRUD ---


def insert_creature_link(
    curs,
    ability_id,
    creature_game_id,
    creature_name,
    creature_level,
    creature_traits,
    source_name,
    ability_category,
):
    """Insert or update a creature link for an ability."""
    traits_json = json.dumps(creature_traits) if creature_traits else None
    sql = "\n".join(
        [
            "INSERT OR REPLACE INTO ability_creature_links",
            " (ability_id, creature_game_id, creature_name,",
            "  creature_level, creature_traits, source_name,",
            "  ability_category)",
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ]
    )
    curs.execute(
        sql,
        (
            ability_id,
            creature_game_id,
            creature_name,
            creature_level,
            traits_json,
            source_name,
            ability_category,
        ),
    )
    return curs.lastrowid


def fetch_creatures_for_ability(curs, ability_id):
    sql = "\n".join(
        [
            "SELECT * FROM ability_creature_links",
            " WHERE ability_id = ?",
        ]
    )
    curs.execute(sql, (ability_id,))
    return curs.fetchall()


def fetch_abilities_for_creature(curs, creature_game_id):
    sql = "\n".join(
        [
            "SELECT ar.* FROM ability_records ar",
            " JOIN ability_creature_links acl",
            "   ON ar.ability_id = acl.ability_id",
            " WHERE acl.creature_game_id = ?",
        ]
    )
    curs.execute(sql, (creature_game_id,))
    return curs.fetchall()


def count_ability_records(curs):
    """Return counts for reporting: total, enriched, stale, verified."""
    curs.execute("SELECT COUNT(*) FROM ability_records")
    total = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM ability_records" " WHERE enrichment_version IS NOT NULL")
    enriched = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM ability_records WHERE stale = 1")
    stale = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM ability_records WHERE human_verified = 1")
    verified = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM ability_records WHERE needs_review = 1")
    needs_review = curs.fetchone()["COUNT(*)"]
    return {
        "total": total,
        "enriched": enriched,
        "unenriched": total - enriched,
        "stale": stale,
        "verified": verified,
        "needs_review": needs_review,
    }


def mark_needs_review(curs, ability_id, reason):
    """Flag an ability as needing manual or LLM review."""
    sql = "\n".join(
        [
            "UPDATE ability_records",
            " SET needs_review = 1,",
            "     review_reason = ?,",
            "     updated_at = ?",
            " WHERE ability_id = ?",
        ]
    )
    curs.execute(sql, (reason, _now(), ability_id))


def clear_needs_review(curs, ability_id):
    sql = "\n".join(
        [
            "UPDATE ability_records",
            " SET needs_review = 0,",
            "     review_reason = NULL,",
            "     updated_at = ?",
            " WHERE ability_id = ?",
        ]
    )
    curs.execute(sql, (_now(), ability_id))


def fetch_needs_review(curs):
    sql = "SELECT * FROM ability_records WHERE needs_review = 1"
    curs.execute(sql)
    return curs.fetchall()


# --- Change record CRUD (template/family rule enrichment) ---


def insert_change_record(curs, source_name, source_type, identity_hash, raw_json):
    """Insert a new change record. Returns the change_id."""
    now = _now()
    sql = "\n".join(
        [
            "INSERT INTO change_records",
            " (source_name, source_type, identity_hash, raw_json, created_at, updated_at)",
            " VALUES (?, ?, ?, ?, ?, ?)",
        ]
    )
    curs.execute(sql, (source_name, source_type, identity_hash, raw_json, now, now))
    return curs.lastrowid


def fetch_change_by_hash(curs, identity_hash):
    sql = "SELECT * FROM change_records WHERE identity_hash = ?"
    curs.execute(sql, (identity_hash,))
    return curs.fetchone()


def fetch_changes_for_source(curs, source_name, source_type):
    sql = "SELECT * FROM change_records WHERE source_name = ? AND source_type = ?"
    curs.execute(sql, (source_name, source_type))
    return curs.fetchall()


def fetch_changes_needing_enrichment(curs, current_version):
    """Fetch change records that need (re-)enrichment."""
    sql = "\n".join(
        [
            "SELECT * FROM change_records",
            " WHERE human_verified = 0",
            " AND (enrichment_version IS NULL",
            "      OR enrichment_version < ?)",
        ]
    )
    curs.execute(sql, (current_version,))
    return curs.fetchall()


def update_change_enriched_json(
    curs, change_id, enriched_json, enrichment_version, extraction_method
):
    """Store enrichment results for a change record."""
    sql = "\n".join(
        [
            "UPDATE change_records",
            " SET enriched_json = ?,",
            "     enrichment_version = ?,",
            "     extraction_method = ?,",
            "     stale = 0,",
            "     updated_at = ?",
            " WHERE change_id = ?",
        ]
    )
    curs.execute(sql, (enriched_json, enrichment_version, extraction_method, _now(), change_id))


def mark_change_stale(curs, change_id, new_raw_json):
    """Mark a change record as stale and update its raw_json."""
    sql = "\n".join(
        [
            "UPDATE change_records",
            " SET stale = 1,",
            "     raw_json = ?,",
            "     updated_at = ?",
            " WHERE change_id = ?",
        ]
    )
    curs.execute(sql, (new_raw_json, _now(), change_id))


def mark_change_human_verified(curs, change_id, verified=True):
    sql = "\n".join(
        [
            "UPDATE change_records",
            " SET human_verified = ?,",
            "     updated_at = ?",
            " WHERE change_id = ?",
        ]
    )
    curs.execute(sql, (1 if verified else 0, _now(), change_id))


def mark_change_needs_review(curs, change_id, reason):
    sql = "\n".join(
        [
            "UPDATE change_records",
            " SET needs_review = 1,",
            "     review_reason = ?,",
            "     updated_at = ?",
            " WHERE change_id = ?",
        ]
    )
    curs.execute(sql, (reason, _now(), change_id))


def count_change_records(curs):
    """Return counts for reporting."""
    curs.execute("SELECT COUNT(*) FROM change_records")
    total = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM change_records WHERE enrichment_version IS NOT NULL")
    enriched = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM change_records WHERE stale = 1")
    stale = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM change_records WHERE human_verified = 1")
    verified = curs.fetchone()["COUNT(*)"]
    curs.execute("SELECT COUNT(*) FROM change_records WHERE needs_review = 1")
    needs_review = curs.fetchone()["COUNT(*)"]
    return {
        "total": total,
        "enriched": enriched,
        "unenriched": total - enriched,
        "stale": stale,
        "verified": verified,
        "needs_review": needs_review,
    }
