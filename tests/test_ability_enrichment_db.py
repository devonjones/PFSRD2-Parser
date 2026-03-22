import json
import pytest
from pfsrd2.sql.enrichment import (
    count_ability_records,
    fetch_abilities_by_name,
    fetch_abilities_for_creature,
    fetch_ability_by_hash,
    fetch_ability_by_id,
    fetch_creatures_for_ability,
    fetch_needing_enrichment,
    fetch_stale,
    fetch_unenriched,
    get_enrichment_db_connection,
    insert_ability_record,
    insert_creature_link,
    mark_human_verified,
    mark_stale,
    update_enriched_json,
)


@pytest.fixture
def db():
    """In-memory enrichment DB for testing."""
    conn = get_enrichment_db_connection(db_path=":memory:")
    yield conn
    conn.close()


class TestAbilityRecordCRUD:
    def test_insert_and_fetch_by_hash(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash123", '{"name": "Grab"}')
        db.commit()
        row = fetch_ability_by_hash(curs, "hash123")
        assert row is not None
        assert row["name"] == "Grab"
        assert row["identity_hash"] == "hash123"
        assert row["ability_id"] == aid
        assert row["enriched_json"] is None
        assert row["enrichment_version"] is None
        assert row["human_verified"] == 0
        assert row["stale"] == 0

    def test_fetch_by_id(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash123", '{"name": "Grab"}')
        db.commit()
        row = fetch_ability_by_id(curs, aid)
        assert row["name"] == "Grab"

    def test_fetch_by_name(self, db):
        curs = db.cursor()
        insert_ability_record(curs, "Grab", "hash1", '{}')
        insert_ability_record(curs, "Grab", "hash2", '{}')
        insert_ability_record(curs, "Push", "hash3", '{}')
        db.commit()
        rows = fetch_abilities_by_name(curs, "Grab")
        assert len(rows) == 2

    def test_unique_hash_constraint(self, db):
        curs = db.cursor()
        insert_ability_record(curs, "Grab", "hash123", '{}')
        db.commit()
        with pytest.raises(Exception):
            insert_ability_record(curs, "Grab", "hash123", '{}')

    def test_update_enrichment(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash123", '{}')
        db.commit()
        enriched = json.dumps({"name": "Grab", "saving_throw": {"dc": 20}})
        update_enriched_json(curs, aid, enriched, 1, "regex")
        db.commit()
        row = fetch_ability_by_id(curs, aid)
        assert row["enriched_json"] == enriched
        assert row["enrichment_version"] == 1
        assert row["extraction_method"] == "regex"
        assert row["stale"] == 0

    def test_mark_stale(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash123", '{"v": 1}')
        update_enriched_json(curs, aid, '{"enriched": true}', 1, "regex")
        db.commit()
        mark_stale(curs, aid, '{"v": 2}')
        db.commit()
        row = fetch_ability_by_id(curs, aid)
        assert row["stale"] == 1
        assert row["raw_json"] == '{"v": 2}'

    def test_mark_human_verified(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash123", '{}')
        db.commit()
        mark_human_verified(curs, aid, True)
        db.commit()
        row = fetch_ability_by_id(curs, aid)
        assert row["human_verified"] == 1

    def test_fetch_unenriched(self, db):
        curs = db.cursor()
        insert_ability_record(curs, "Grab", "hash1", '{}')
        aid2 = insert_ability_record(curs, "Push", "hash2", '{}')
        update_enriched_json(curs, aid2, '{}', 1, "regex")
        db.commit()
        rows = fetch_unenriched(curs)
        assert len(rows) == 1
        assert rows[0]["name"] == "Grab"

    def test_fetch_stale(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash1", '{}')
        insert_ability_record(curs, "Push", "hash2", '{}')
        mark_stale(curs, aid, '{"new": true}')
        db.commit()
        rows = fetch_stale(curs)
        assert len(rows) == 1
        assert rows[0]["name"] == "Grab"

    def test_fetch_needing_enrichment(self, db):
        curs = db.cursor()
        aid1 = insert_ability_record(curs, "Grab", "hash1", '{}')
        aid2 = insert_ability_record(curs, "Push", "hash2", '{}')
        aid3 = insert_ability_record(curs, "Trip", "hash3", '{}')
        # aid1: enriched at version 1
        update_enriched_json(curs, aid1, '{}', 1, "regex")
        # aid2: unenriched
        # aid3: enriched and human verified
        update_enriched_json(curs, aid3, '{}', 1, "manual")
        mark_human_verified(curs, aid3)
        db.commit()
        # current version 2: should get aid1 (old version) and aid2 (unenriched)
        rows = fetch_needing_enrichment(curs, 2)
        names = {r["name"] for r in rows}
        assert names == {"Grab", "Push"}


class TestCreatureLinkCRUD:
    def test_insert_and_fetch(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash1", '{}')
        insert_creature_link(
            curs, aid, "game-id-1", "Goblin Warrior", -1,
            ["Goblin", "Humanoid"], "Bestiary", "offensive"
        )
        db.commit()
        links = fetch_creatures_for_ability(curs, aid)
        assert len(links) == 1
        assert links[0]["creature_name"] == "Goblin Warrior"
        assert links[0]["creature_level"] == -1
        assert links[0]["ability_category"] == "offensive"
        assert json.loads(links[0]["creature_traits"]) == ["Goblin", "Humanoid"]

    def test_multiple_creatures_same_ability(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash1", '{}')
        insert_creature_link(curs, aid, "gid-1", "Goblin", -1, [], "Bestiary", "offensive")
        insert_creature_link(curs, aid, "gid-2", "Bugbear", 2, [], "Bestiary", "offensive")
        db.commit()
        links = fetch_creatures_for_ability(curs, aid)
        assert len(links) == 2

    def test_upsert_on_duplicate(self, db):
        curs = db.cursor()
        aid = insert_ability_record(curs, "Grab", "hash1", '{}')
        insert_creature_link(curs, aid, "gid-1", "Goblin", -1, [], "Bestiary", "offensive")
        # Update level for same creature+ability
        insert_creature_link(curs, aid, "gid-1", "Goblin", 0, [], "Bestiary", "offensive")
        db.commit()
        links = fetch_creatures_for_ability(curs, aid)
        assert len(links) == 1
        assert links[0]["creature_level"] == 0

    def test_fetch_abilities_for_creature(self, db):
        curs = db.cursor()
        aid1 = insert_ability_record(curs, "Grab", "hash1", '{}')
        aid2 = insert_ability_record(curs, "Push", "hash2", '{}')
        insert_creature_link(curs, aid1, "gid-1", "Goblin", -1, [], "B", "offensive")
        insert_creature_link(curs, aid2, "gid-1", "Goblin", -1, [], "B", "automatic")
        db.commit()
        abilities = fetch_abilities_for_creature(curs, "gid-1")
        assert len(abilities) == 2
        names = {a["name"] for a in abilities}
        assert names == {"Grab", "Push"}


class TestCounts:
    def test_count_ability_records(self, db):
        curs = db.cursor()
        aid1 = insert_ability_record(curs, "Grab", "h1", '{}')
        aid2 = insert_ability_record(curs, "Push", "h2", '{}')
        aid3 = insert_ability_record(curs, "Trip", "h3", '{}')
        update_enriched_json(curs, aid1, '{}', 1, "regex")
        mark_stale(curs, aid2, '{}')
        update_enriched_json(curs, aid3, '{}', 1, "manual")
        mark_human_verified(curs, aid3)
        db.commit()
        counts = count_ability_records(curs)
        assert counts["total"] == 3
        assert counts["enriched"] == 2
        assert counts["unenriched"] == 1
        assert counts["stale"] == 1
        assert counts["verified"] == 1
