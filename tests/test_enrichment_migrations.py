"""Tests for the enrichment DB migration chain, especially v6/v7 creature_types."""

import sqlite3

import pytest

from pfsrd2.sql.enrichment import (
    _create_db_v_1,
    _create_db_v_2,
    _create_db_v_3,
    _create_db_v_4,
    _create_db_v_5,
    _create_db_v_6,
    _create_db_v_7,
    get_enrichment_db_connection,
)


@pytest.fixture
def fresh_conn():
    conn = get_enrichment_db_connection(db_path=":memory:")
    yield conn
    conn.close()


class TestFullMigrationChain:
    def test_fresh_db_ends_at_v7(self, fresh_conn):
        curs = fresh_conn.cursor()
        curs.execute("SELECT MAX(version) AS v FROM enrichment_db_version")
        assert curs.fetchone()["v"] == 7

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
        ver = _create_db_v_2(conn, curs, ver)
        ver = _create_db_v_3(conn, curs, ver)
        ver = _create_db_v_4(conn, curs, ver)
        ver = _create_db_v_5(conn, curs, ver)
        ver = _create_db_v_6(conn, curs, ver)
        assert ver == 6
        # Re-running v6 should be a no-op
        again = _create_db_v_6(conn, curs, ver)
        assert again == 6
        conn.close()

    def test_v7_idempotent_when_already_applied(self):
        conn = self._raw_conn()
        curs = conn.cursor()
        ver = _create_db_v_1(conn, curs)
        for fn in (_create_db_v_2, _create_db_v_3, _create_db_v_4, _create_db_v_5):
            ver = fn(conn, curs, ver)
        ver = _create_db_v_6(conn, curs, ver)
        ver = _create_db_v_7(conn, curs, ver)
        assert ver == 7
        again = _create_db_v_7(conn, curs, ver)
        assert again == 7
        conn.close()


class TestV7DropsAndRecreates:
    def _build_v6_db(self):
        """Build a raw DB stopped at v6 (no v7 applied), with a case-sensitive
        creature_types table containing a seeded row."""
        conn = sqlite3.connect(":memory:")
        curs = conn.cursor()
        ver = _create_db_v_1(conn, curs)
        for fn in (_create_db_v_2, _create_db_v_3, _create_db_v_4, _create_db_v_5):
            ver = fn(conn, curs, ver)
        ver = _create_db_v_6(conn, curs, ver)
        assert ver == 6
        curs.execute("INSERT INTO creature_types (name, created_at) VALUES ('Undead', 'now')")
        conn.commit()
        return conn, curs

    def test_v7_drops_rows_and_enforces_nocase(self):
        conn, curs = self._build_v6_db()
        # Before v7, the table has 1 row
        curs.execute("SELECT COUNT(*) FROM creature_types")
        assert curs.fetchone()[0] == 1

        ver = _create_db_v_7(conn, curs, 6)
        assert ver == 7

        # Rows dropped by the rebuild (documented behavior — re-seed required)
        curs.execute("SELECT COUNT(*) FROM creature_types")
        assert curs.fetchone()[0] == 0

        # New table is case-insensitive
        curs.execute("INSERT INTO creature_types (name, created_at) VALUES ('Undead', 'now')")
        with pytest.raises(sqlite3.IntegrityError):
            curs.execute("INSERT INTO creature_types (name, created_at) VALUES ('undead', 'now')")
        conn.close()
