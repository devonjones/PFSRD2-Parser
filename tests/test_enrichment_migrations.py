"""Tests for the enrichment DB migration chain, especially v6 creature_types."""

import sqlite3

import pytest

from pfsrd2.sql.enrichment import (
    _create_db_v_1,
    _create_db_v_2,
    _create_db_v_3,
    _create_db_v_4,
    _create_db_v_5,
    _create_db_v_6,
    get_enrichment_db_connection,
)


@pytest.fixture
def fresh_conn():
    conn = get_enrichment_db_connection(db_path=":memory:")
    yield conn
    conn.close()


class TestFullMigrationChain:
    def test_fresh_db_ends_at_v6(self, fresh_conn):
        curs = fresh_conn.cursor()
        curs.execute("SELECT MAX(version) AS v FROM enrichment_db_version")
        assert curs.fetchone()["v"] == 6

    def test_creature_types_table_exists_and_is_nocase(self, fresh_conn):
        curs = fresh_conn.cursor()
        curs.execute("INSERT INTO creature_types (name, created_at) VALUES ('Undead', 'now')")
        # Same name, different case — COLLATE NOCASE + UNIQUE should reject
        with pytest.raises(sqlite3.IntegrityError):
            curs.execute("INSERT INTO creature_types (name, created_at) VALUES ('undead', 'now')")

    def test_insert_or_ignore_dedupes_case_insensitively(self, fresh_conn):
        curs = fresh_conn.cursor()
        curs.execute(
            "INSERT OR IGNORE INTO creature_types (name, created_at) VALUES ('Undead', 'now')"
        )
        curs.execute(
            "INSERT OR IGNORE INTO creature_types (name, created_at) VALUES ('UNDEAD', 'now')"
        )
        curs.execute("SELECT COUNT(*) AS c FROM creature_types")
        assert curs.fetchone()["c"] == 1


class TestMigrationIdempotency:
    def _raw_conn(self):
        """A raw sqlite3 connection without running any migrations yet.

        No row_factory — the migration code uses positional row[0] internally.
        """
        return sqlite3.connect(":memory:")

    def test_v6_idempotent_when_already_applied(self):
        conn = self._raw_conn()
        curs = conn.cursor()
        ver = _create_db_v_1(conn, curs)
        for fn in (_create_db_v_2, _create_db_v_3, _create_db_v_4, _create_db_v_5):
            ver = fn(conn, curs, ver)
        ver = _create_db_v_6(conn, curs, ver)
        assert ver == 6
        # Re-running v6 should be a no-op
        again = _create_db_v_6(conn, curs, ver)
        assert again == 6
        conn.close()
