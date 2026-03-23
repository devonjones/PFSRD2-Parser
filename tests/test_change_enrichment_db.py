import json
import sqlite3

import pytest

from pfsrd2.sql.enrichment import (
    count_change_records,
    fetch_change_by_hash,
    fetch_changes_for_source,
    fetch_changes_needing_enrichment,
    get_enrichment_db_connection,
    insert_change_record,
    mark_change_human_verified,
    mark_change_needs_review,
    mark_change_stale,
    update_change_enriched_json,
)


@pytest.fixture
def db():
    """In-memory enrichment DB for testing."""
    conn = get_enrichment_db_connection(db_path=":memory:")
    yield conn
    conn.close()


class TestChangeRecordCRUD:
    def test_insert_and_fetch_by_hash(self, db):
        curs = db.cursor()
        cid = insert_change_record(
            curs, "Vampire", "monster_template", "hash_abc", '{"text": "Add undead."}'
        )
        db.commit()
        row = fetch_change_by_hash(curs, "hash_abc")
        assert row is not None
        assert row["source_name"] == "Vampire"
        assert row["source_type"] == "monster_template"
        assert row["identity_hash"] == "hash_abc"
        assert row["change_id"] == cid
        assert row["enriched_json"] is None
        assert row["enrichment_version"] is None
        assert row["human_verified"] == 0
        assert row["stale"] == 0
        assert row["needs_review"] == 0

    def test_fetch_by_hash_returns_none_for_missing(self, db):
        curs = db.cursor()
        row = fetch_change_by_hash(curs, "nonexistent_hash")
        assert row is None

    def test_unique_hash_constraint(self, db):
        curs = db.cursor()
        insert_change_record(curs, "Vampire", "monster_template", "hash_dup", "{}")
        db.commit()
        with pytest.raises(sqlite3.IntegrityError):
            insert_change_record(curs, "Zombie", "monster_template", "hash_dup", "{}")

    def test_fetch_changes_for_source(self, db):
        curs = db.cursor()
        insert_change_record(curs, "Vampire", "monster_template", "h1", "{}")
        insert_change_record(curs, "Vampire", "monster_template", "h2", "{}")
        insert_change_record(curs, "Zombie", "monster_template", "h3", "{}")
        insert_change_record(curs, "Vampire", "monster_family", "h4", "{}")
        db.commit()
        rows = fetch_changes_for_source(curs, "Vampire", "monster_template")
        assert len(rows) == 2

    def test_fetch_changes_needing_enrichment(self, db):
        curs = db.cursor()
        cid1 = insert_change_record(curs, "Vampire", "monster_template", "h1", "{}")
        insert_change_record(curs, "Zombie", "monster_template", "h2", "{}")
        cid3 = insert_change_record(curs, "Ghost", "monster_template", "h3", "{}")
        # cid1: enriched at version 1
        update_change_enriched_json(curs, cid1, '{"enriched": true}', 1, "regex")
        # cid3: enriched and human verified
        update_change_enriched_json(curs, cid3, '{"enriched": true}', 1, "regex")
        mark_change_human_verified(curs, cid3)
        db.commit()
        # current version 2: should get cid1 (old version) and cid2 (unenriched)
        rows = fetch_changes_needing_enrichment(curs, 2)
        names = {r["source_name"] for r in rows}
        assert names == {"Vampire", "Zombie"}

    def test_fetch_changes_needing_enrichment_skips_human_verified(self, db):
        curs = db.cursor()
        cid1 = insert_change_record(curs, "Vampire", "monster_template", "h1", "{}")
        update_change_enriched_json(curs, cid1, "{}", 1, "regex")
        mark_change_human_verified(curs, cid1)
        db.commit()
        rows = fetch_changes_needing_enrichment(curs, 5)
        assert len(rows) == 0

    def test_update_change_enriched_json(self, db):
        curs = db.cursor()
        cid = insert_change_record(curs, "Vampire", "monster_template", "h1", "{}")
        db.commit()
        enriched = json.dumps({"change_category": "traits", "effects": []})
        update_change_enriched_json(curs, cid, enriched, 2, "regex")
        db.commit()
        row = fetch_change_by_hash(curs, "h1")
        assert row["enriched_json"] == enriched
        assert row["enrichment_version"] == 2
        assert row["extraction_method"] == "regex"
        assert row["stale"] == 0

    def test_mark_change_stale(self, db):
        curs = db.cursor()
        cid = insert_change_record(curs, "Vampire", "monster_template", "h1", '{"v": 1}')
        update_change_enriched_json(curs, cid, '{"enriched": true}', 1, "regex")
        db.commit()
        mark_change_stale(curs, cid, '{"v": 2}')
        db.commit()
        row = fetch_change_by_hash(curs, "h1")
        assert row["stale"] == 1
        assert row["raw_json"] == '{"v": 2}'

    def test_mark_change_human_verified(self, db):
        curs = db.cursor()
        cid = insert_change_record(curs, "Vampire", "monster_template", "h1", "{}")
        db.commit()
        mark_change_human_verified(curs, cid, True)
        db.commit()
        row = fetch_change_by_hash(curs, "h1")
        assert row["human_verified"] == 1

    def test_mark_change_needs_review(self, db):
        curs = db.cursor()
        cid = insert_change_record(curs, "Vampire", "monster_template", "h1", "{}")
        db.commit()
        mark_change_needs_review(curs, cid, "unknown category")
        db.commit()
        row = fetch_change_by_hash(curs, "h1")
        assert row["needs_review"] == 1
        assert row["review_reason"] == "unknown category"

    def test_count_change_records(self, db):
        curs = db.cursor()
        cid1 = insert_change_record(curs, "Vampire", "monster_template", "h1", "{}")
        cid2 = insert_change_record(curs, "Zombie", "monster_template", "h2", "{}")
        cid3 = insert_change_record(curs, "Ghost", "monster_template", "h3", "{}")
        update_change_enriched_json(curs, cid1, "{}", 1, "regex")
        mark_change_stale(curs, cid2, "{}")
        update_change_enriched_json(curs, cid3, "{}", 1, "regex")
        mark_change_human_verified(curs, cid3)
        mark_change_needs_review(curs, cid2, "test reason")
        db.commit()
        counts = count_change_records(curs)
        assert counts["total"] == 3
        assert counts["enriched"] == 2
        assert counts["unenriched"] == 1
        assert counts["stale"] == 1
        assert counts["verified"] == 1
        assert counts["needs_review"] == 1
