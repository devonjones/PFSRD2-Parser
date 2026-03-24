"""Enrichment database — separate from the main pfsrd2.db.

This DB persists at ~/.pfsrd2/enrichment.db and survives
main DB rebuilds. It has its own migration chain.
"""

import os
import sqlite3

# Re-export queries for convenient access
from pfsrd2.sql.enrichment.queries import (  # noqa: F401
    clear_needs_review,
    count_ability_records,
    count_change_records,
    fetch_abilities_by_name,
    fetch_abilities_for_creature,
    fetch_ability_by_hash,
    fetch_ability_by_id,
    fetch_change_by_hash,
    fetch_changes_for_source,
    fetch_changes_needing_enrichment,
    fetch_creatures_for_ability,
    fetch_needing_enrichment,
    fetch_needs_review,
    fetch_stale,
    fetch_unenriched,
    insert_ability_record,
    insert_change_record,
    insert_creature_link,
    mark_change_human_verified,
    mark_change_needs_review,
    mark_change_stale,
    mark_human_verified,
    mark_needs_review,
    mark_stale,
    update_change_enriched_json,
    update_enriched_json,
    update_identity_hash,
)
from pfsrd2.sql.enrichment.tables import (
    create_ability_creature_links_index,
    create_ability_creature_links_table,
    create_ability_records_index,
    create_ability_records_table,
    create_change_records_index,
    create_change_records_table,
)

DB_NAME = "enrichment.db"


def _get_db_path():
    path = os.path.expanduser("~/.pfsrd2")
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.join(path, DB_NAME)


def _dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def _check_version(curs):
    sql = "SELECT MAX(version) FROM enrichment_db_version"
    curs.execute(sql)
    row = curs.fetchone()
    return row[0]


def _set_version(curs, ver):
    sql = "INSERT INTO enrichment_db_version (version) VALUES (?)"
    curs.execute(sql, (str(ver),))


# --- Migration chain ---


def _create_db_v_1(conn, curs):
    """Version 1: Create version tracking table."""
    sql = "\n".join(
        [
            "CREATE TABLE IF NOT EXISTS enrichment_db_version(",
            "  id INTEGER PRIMARY KEY,",
            "  version INTEGER)",
        ]
    )
    curs.execute(sql)
    ver = _check_version(curs)
    if not ver:
        ver = 1
        _set_version(curs, ver)
    conn.commit()
    return ver


def _create_db_v_2(conn, curs, ver):
    """Version 2: Create ability_records and ability_creature_links tables."""
    if ver >= 2:
        return ver
    ver = 2
    create_ability_records_table(curs)
    create_ability_records_index(curs)
    create_ability_creature_links_table(curs)
    create_ability_creature_links_index(curs)
    _set_version(curs, ver)
    conn.commit()
    return ver


def _create_db_v_3(conn, curs, ver):
    """Version 3: Add needs_review flag and review_reason to ability_records."""
    if ver >= 3:
        return ver
    ver = 3
    curs.execute("ALTER TABLE ability_records" " ADD COLUMN needs_review INTEGER DEFAULT 0")
    curs.execute("ALTER TABLE ability_records" " ADD COLUMN review_reason TEXT")
    curs.execute("CREATE INDEX ability_records_needs_review" " ON ability_records (needs_review)")
    _set_version(curs, ver)
    conn.commit()
    return ver


def _create_db_v_4(conn, curs, ver):
    """Version 4: Create change_records table for template/family rule enrichment."""
    if ver >= 4:
        return ver
    ver = 4
    create_change_records_table(curs)
    create_change_records_index(curs)
    _set_version(curs, ver)
    conn.commit()
    return ver


# --- Connection ---


def get_enrichment_db_connection(db_path=None):
    """Get a connection to the enrichment database.

    Creates the DB and runs migrations if needed.
    Pass db_path=":memory:" for testing.
    """
    if db_path is None:
        db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    curs = conn.cursor()
    try:
        ver = _create_db_v_1(conn, curs)
        ver = _create_db_v_2(conn, curs, ver)
        ver = _create_db_v_3(conn, curs, ver)
        ver = _create_db_v_4(conn, curs, ver)
    finally:
        curs.close()
    conn.row_factory = _dict_factory
    return conn
