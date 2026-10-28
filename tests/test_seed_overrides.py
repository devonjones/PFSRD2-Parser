import json

import pytest

from pfsrd2.change_identity import compute_change_hash
from pfsrd2.enrichment.change_extractor import ENRICHMENT_VERSION
from pfsrd2.enrichment.overrides import (
    load_overrides,
    seed_ability_field_overrides,
    seed_ability_overrides,
    seed_change_overrides,
)
from pfsrd2.sql.enrichment import (
    fetch_ability_by_id,
    fetch_change_by_hash,
    get_enrichment_db_connection,
    insert_ability_record,
    insert_change_record,
    mark_change_needs_review,
)


@pytest.fixture
def db():
    """In-memory enrichment DB for testing."""
    conn = get_enrichment_db_connection(db_path=":memory:")
    yield conn
    conn.close()


def _change_override(text="- Increase the creature's level by 1."):
    return {
        "source_name": "Elite",
        "source_type": "monster_template",
        "change_text": text,
        "enriched": {
            "change_category": "level",
            "effects": [
                {
                    "operation": "adjustment",
                    "target": "$.creature_type.level",
                    "value": 1,
                }
            ],
        },
    }


class TestSeedChangeOverrides:
    def _insert_record(self, curs, override):
        identity_hash = compute_change_hash(
            override["source_name"], override["source_type"], override["change_text"]
        )
        change_id = insert_change_record(
            curs,
            override["source_name"],
            override["source_type"],
            identity_hash,
            json.dumps({"text": override["change_text"]}),
        )
        return identity_hash, change_id

    def test_seed_updates_matching_record(self, db):
        curs = db.cursor()
        override = _change_override()
        identity_hash, _ = self._insert_record(curs, override)

        seeded, misses = seed_change_overrides(curs, [override])

        assert seeded == 1
        assert misses == []
        row = fetch_change_by_hash(curs, identity_hash)
        assert row["extraction_method"] == "manual"
        assert row["human_verified"] == 1
        assert row["enrichment_version"] == ENRICHMENT_VERSION
        enriched = json.loads(row["enriched_json"])
        assert enriched == override["enriched"]

    def test_seed_clears_needs_review(self, db):
        curs = db.cursor()
        override = _change_override()
        identity_hash, change_id = self._insert_record(curs, override)
        mark_change_needs_review(curs, change_id, "unknown_category")

        seed_change_overrides(curs, [override])

        row = fetch_change_by_hash(curs, identity_hash)
        assert row["needs_review"] == 0
        assert row["review_reason"] is None

    def test_seed_is_idempotent(self, db):
        curs = db.cursor()
        override = _change_override()
        identity_hash, _ = self._insert_record(curs, override)

        seed_change_overrides(curs, [override])
        first = dict(fetch_change_by_hash(curs, identity_hash))
        seeded, misses = seed_change_overrides(curs, [override])
        second = dict(fetch_change_by_hash(curs, identity_hash))

        assert seeded == 1
        assert misses == []
        first.pop("updated_at")
        second.pop("updated_at")
        assert first == second

    def test_missing_record_is_reported_not_skipped(self, db):
        curs = db.cursor()
        override = _change_override("- Text that was never parsed.")

        seeded, misses = seed_change_overrides(curs, [override])

        assert seeded == 0
        assert misses == [override]

    def test_text_change_makes_override_stale(self, db):
        """A hash is over (source, type, text) — edited source text must miss."""
        curs = db.cursor()
        override = _change_override()
        self._insert_record(curs, override)
        edited = dict(override, change_text=override["change_text"] + " Errata.")

        seeded, misses = seed_change_overrides(curs, [edited])

        assert seeded == 0
        assert misses == [edited]


class TestLoadOverrides:
    def test_loads_overrides_list(self, tmp_path):
        doc = {"description": "test", "overrides": [{"name": "X"}]}
        (tmp_path / "change_overrides.json").write_text(json.dumps(doc))
        assert load_overrides("change_overrides.json", overrides_dir=tmp_path) == [{"name": "X"}]

    def test_missing_file_raises(self, tmp_path):
        # A silent [] here would no-op the whole seeding step on a broken
        # checkout or typo'd filename — must fail loudly.
        with pytest.raises(FileNotFoundError):
            load_overrides("nope.json", overrides_dir=tmp_path)

    def test_missing_overrides_key_raises(self, tmp_path):
        (tmp_path / "bad.json").write_text("{}")
        with pytest.raises(KeyError):
            load_overrides("bad.json", overrides_dir=tmp_path)

    def test_committed_override_files_load(self):
        # The real committed files must always parse and be non-empty.
        assert load_overrides("change_overrides.json")
        assert load_overrides("ability_overrides.json")


class TestSeedAbilityOverrides:
    def test_seed_sets_category_and_verified(self, db):
        curs = db.cursor()
        ability_id = insert_ability_record(curs, "Cold Stasis", "hash1", "{}")

        seeded, misses = seed_ability_overrides(
            curs, [{"name": "Cold Stasis", "ability_category": "automatic"}]
        )

        assert seeded == 1
        assert misses == []
        row = fetch_ability_by_id(curs, ability_id)
        assert row["ability_category"] == "automatic"
        assert row["human_verified"] == 1

    def test_seed_matches_case_insensitively_and_all_variants(self, db):
        curs = db.cursor()
        id_a = insert_ability_record(curs, "Cold Stasis", "hash1", "{}")
        id_b = insert_ability_record(curs, "cold stasis", "hash2", "{}")

        seeded, _ = seed_ability_overrides(
            curs, [{"name": "COLD STASIS", "ability_category": "automatic"}]
        )

        assert seeded == 1
        for ability_id in (id_a, id_b):
            row = fetch_ability_by_id(curs, ability_id)
            assert row["ability_category"] == "automatic"
            assert row["human_verified"] == 1

    def test_missing_ability_is_reported(self, db):
        curs = db.cursor()
        override = {"name": "Never Parsed", "ability_category": "offensive"}

        seeded, misses = seed_ability_overrides(curs, [override])

        assert seeded == 0
        assert misses == [override]

    def test_invalid_category_asserts(self, db):
        curs = db.cursor()
        insert_ability_record(curs, "Cold Stasis", "hash1", "{}")
        override = {"name": "Cold Stasis", "ability_category": "automatc"}

        with pytest.raises(AssertionError, match="Invalid ability category"):
            seed_ability_overrides(curs, [override])


class TestSeedAbilityFieldOverrides:
    TEXT = "Each creature takes 3d6 nonlethal bludgeoning damage (DC 21 basic Reflex save)."
    DAMAGE = [{"formula": "3d6", "damage_type": "nonlethal"}]

    def _record(self, curs, text=TEXT, enriched=None):
        raw = json.dumps({"name": "Bola Hurl", "text": text})
        ability_id = insert_ability_record(curs, "Bola Hurl", "hash1", raw)
        if enriched is not None:
            curs.execute(
                "UPDATE ability_records SET enriched_json = ? WHERE ability_id = ?",
                (json.dumps(enriched), ability_id),
            )
        return ability_id

    def _override(self, text=TEXT, enriched=None):
        return {"name": "Bola Hurl", "text": text, "enriched": enriched or {"damage": self.DAMAGE}}

    def test_seed_replaces_only_the_listed_field(self, db):
        curs = db.cursor()
        save = [{"dc": 21, "save_type": "Ref"}]
        ability_id = self._record(
            curs,
            enriched={"name": "Bola Hurl", "damage": [{"formula": "3d6"}], "saving_throw": save},
        )

        seeded, misses = seed_ability_field_overrides(curs, [self._override()])

        assert (seeded, misses) == (1, [])
        row = fetch_ability_by_id(curs, ability_id)
        enriched = json.loads(row["enriched_json"])
        assert enriched["damage"] == self.DAMAGE
        assert enriched["saving_throw"] == save, "fields the override does not name are kept"
        assert row["human_verified"] == 1
        assert row["extraction_method"] == "manual"

    def test_changed_text_is_a_miss_not_a_silent_apply(self, db):
        # AoN errata: the override was verified against text that no longer
        # exists, so it must be re-reviewed rather than applied.
        curs = db.cursor()
        self._record(curs, text=self.TEXT.replace("3d6", "4d6"))
        override = self._override()

        seeded, misses = seed_ability_field_overrides(curs, [override])

        assert (seeded, misses) == (0, [override])

    def test_a_field_enrichment_never_writes_asserts(self, db):
        curs = db.cursor()
        self._record(curs)
        with pytest.raises(AssertionError, match="enrichment never writes"):
            seed_ability_field_overrides(curs, [self._override(enriched={"hp": 5})])
