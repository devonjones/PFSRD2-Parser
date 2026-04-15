"""Tests for the creature_types enrichment table and trait-target routing."""

import pytest

from pfsrd2.enrichment import change_extractor
from pfsrd2.enrichment.change_extractor import _trait_target
from pfsrd2.sql.enrichment import (
    fetch_all_creature_types,
    get_enrichment_db_connection,
    upsert_creature_type,
)


class _KeepOpenConn:
    """Passthrough wrapper that ignores close() so multiple _trait_target calls
    can share a single in-memory sqlite connection."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass


@pytest.fixture
def db_with_types(monkeypatch):
    """In-memory enrichment DB seeded with a few creature types.

    Patches change_extractor's lazy DB opener to use the in-memory conn
    and resets the module cache between tests.
    """
    conn = get_enrichment_db_connection(db_path=":memory:")
    curs = conn.cursor()
    for name in ("Undead", "Vampire", "Aquatic"):
        upsert_creature_type(curs, name)
    conn.commit()
    wrapper = _KeepOpenConn(conn)

    monkeypatch.setattr(change_extractor, "get_enrichment_db_connection", lambda: wrapper)
    change_extractor.reset_creature_types_cache()
    yield conn
    change_extractor.reset_creature_types_cache()
    conn.close()


class TestCreatureTypesTable:
    def test_upsert_is_idempotent(self, db_with_types):
        curs = db_with_types.cursor()
        upsert_creature_type(curs, "Vampire")  # already there
        upsert_creature_type(curs, "Skeleton")  # new
        db_with_types.commit()
        names = fetch_all_creature_types(curs)
        assert "Vampire" in names
        assert "Skeleton" in names
        curs.execute("SELECT COUNT(*) as c FROM creature_types WHERE name='Vampire'")
        assert curs.fetchone()["c"] == 1


class TestTraitTargetDBLookup:
    def test_known_creature_type_routes_to_creature_types(self, db_with_types):
        assert _trait_target("Undead") == "$.creature_type.creature_types"
        assert _trait_target("Vampire") == "$.creature_type.creature_types"
        assert _trait_target("Aquatic") == "$.creature_type.creature_types"

    def test_unknown_name_routes_to_traits(self, db_with_types):
        assert _trait_target("Rare") == "$.traits"
        assert _trait_target("Uncommon") == "$.traits"
        assert _trait_target("SomeNewAncestry") == "$.traits"

    def test_cache_refreshes_after_reset(self, db_with_types):
        assert _trait_target("Newtype") == "$.traits"
        upsert_creature_type(db_with_types.cursor(), "Newtype")
        db_with_types.commit()
        change_extractor.reset_creature_types_cache()
        assert _trait_target("Newtype") == "$.creature_type.creature_types"

    def test_case_insensitive_lookup(self, db_with_types):
        """COLLATE NOCASE on the DB column + lowercased cache lets a change
        referring to 'undead' route the same as the canonical 'Undead'."""
        assert _trait_target("undead") == "$.creature_type.creature_types"
        assert _trait_target("VAMPIRE") == "$.creature_type.creature_types"


class TestCreatureTypeDBPass:
    def test_upserts_every_creature_type(self, db_with_types, monkeypatch):
        from pfsrd2 import creatures

        monkeypatch.setattr(
            creatures, "get_enrichment_db_connection", lambda: _KeepOpenConn(db_with_types)
        )
        struct = {
            "stat_block": {
                "creature_type": {"creature_types": ["Human", "Humanoid"]},
            }
        }
        creatures.creature_type_db_pass(struct)
        names = fetch_all_creature_types(db_with_types.cursor())
        assert "Human" in names
        assert "Humanoid" in names

    def test_no_creature_types_is_noop(self, db_with_types, monkeypatch):
        from pfsrd2 import creatures

        called = []
        monkeypatch.setattr(
            creatures,
            "get_enrichment_db_connection",
            lambda: (called.append(True) or _KeepOpenConn(db_with_types)),
        )
        creatures.creature_type_db_pass({"stat_block": {"creature_type": {}}})
        creatures.creature_type_db_pass({"stat_block": {"creature_type": {"creature_types": []}}})
        assert called == []  # short-circuits before opening a connection

    def test_asserts_on_empty_string(self, db_with_types, monkeypatch):
        from pfsrd2 import creatures

        monkeypatch.setattr(
            creatures, "get_enrichment_db_connection", lambda: _KeepOpenConn(db_with_types)
        )
        struct = {"stat_block": {"creature_type": {"creature_types": [""]}}}
        with pytest.raises(AssertionError):
            creatures.creature_type_db_pass(struct)

    def test_asserts_on_non_string(self, db_with_types, monkeypatch):
        from pfsrd2 import creatures

        monkeypatch.setattr(
            creatures, "get_enrichment_db_connection", lambda: _KeepOpenConn(db_with_types)
        )
        struct = {"stat_block": {"creature_type": {"creature_types": [None]}}}
        with pytest.raises(AssertionError):
            creatures.creature_type_db_pass(struct)
