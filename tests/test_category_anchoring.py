"""ability_category is anchored: the LLM suggests, a human pins (PFSRD2-Parser-aiub).

The v3 rebuild missed the LLM cache and reshuffled 36 published categories
(Ghostly Hand -> special_sense, Unholy Speed -> interaction). Driven for real
against an in-memory DB with the model stubbed.
"""

import importlib.machinery
import importlib.util
import json
import os

import pytest

from pfsrd2.enrichment.overrides import load_overrides, seed_ability_overrides
from pfsrd2.sql.enrichment import (
    fetch_ability_by_id,
    get_enrichment_db_connection,
    insert_ability_record,
    update_ability_category,
)
from pfsrd2.sql.enrichment.queries import (
    fetch_majority_category_for_name,
    fetch_uncategorized_abilities,
)

CLI = os.path.join(os.path.dirname(__file__), "..", "bin", "pf2_enrich_abilities")


def load_cli():
    spec = importlib.util.spec_from_loader(
        "pf2_enrich_abilities",
        importlib.machinery.SourceFileLoader("pf2_enrich_abilities", CLI),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Args:
    dry_run = False
    model = "test-model"


@pytest.fixture
def db():
    conn = get_enrichment_db_connection(db_path=":memory:")
    yield conn
    conn.close()


def _record(curs, name, text, ident):
    raw = (
        json.dumps({"name": name, "text": text}) if text is not None else json.dumps({"name": name})
    )
    return insert_ability_record(curs, name, ident, raw)


class TestTheLlmOnlySuggests:
    def test_a_suggestion_is_flagged_and_never_written_as_the_category(self, db, monkeypatch):
        cli = load_cli()
        monkeypatch.setattr(cli, "classify_ability_category_llm", lambda *a, **k: "special_sense")
        curs = db.cursor()
        aid = _record(curs, "Ghostly Hand", "All ghosts have a ghostly hand unarmed attack.", "h1")

        cli.run_llm_classify(db, Args())

        row = fetch_ability_by_id(curs, aid)
        assert row["ability_category"] is None
        assert row["needs_review"] == 1
        assert "LLM suggests special_sense" in row["review_reason"]

    def test_a_rerun_does_not_stack_suggestions(self, db, monkeypatch):
        cli = load_cli()
        curs = db.cursor()
        aid = _record(curs, "Ghostly Hand", "All ghosts have a ghostly hand unarmed attack.", "h1")
        monkeypatch.setattr(cli, "classify_ability_category_llm", lambda *a, **k: "special_sense")
        cli.run_llm_classify(db, Args())
        monkeypatch.setattr(cli, "classify_ability_category_llm", lambda *a, **k: "offensive")
        cli.run_llm_classify(db, Args())

        reason = fetch_ability_by_id(curs, aid)["review_reason"]
        assert "LLM suggests offensive" in reason
        assert "special_sense" not in reason


class TestPins:
    def test_a_text_keyed_pin_leaves_a_same_named_ability_alone(self, db):
        curs = db.cursor()
        siabrae = _record(
            curs, "Speed", "The siabrae gains a burrow Speed equal to their land Speed.", "h1"
        )
        other = _record(curs, "Speed", "Something else entirely.", "h2")
        pin = {
            "name": "Speed",
            "text": "The siabrae gains a burrow Speed equal to their land Speed.",
            "ability_category": "offensive",
        }

        seeded, misses = seed_ability_overrides(curs, [pin])

        assert (seeded, misses) == (1, [])
        assert fetch_ability_by_id(curs, siabrae)["ability_category"] == "offensive"
        assert fetch_ability_by_id(curs, other)["ability_category"] is None
        assert fetch_ability_by_id(curs, other)["human_verified"] == 0

    def test_changed_text_is_a_miss_to_re_review(self, db):
        curs = db.cursor()
        _record(curs, "Speed", "Errata'd text.", "h1")
        pin = {"name": "Speed", "text": "The old text.", "ability_category": "offensive"}

        assert seed_ability_overrides(curs, [pin]) == (0, [pin])

    def test_an_ability_with_no_text_key_matches_an_empty_text_pin(self, db):
        curs = db.cursor()
        aid = _record(curs, "Kiai!", None, "h1")

        seeded, _ = seed_ability_overrides(
            curs, [{"name": "Kiai!", "text": "", "ability_category": "offensive"}]
        )

        assert seeded == 1
        assert fetch_ability_by_id(curs, aid)["ability_category"] == "offensive"

    def test_a_null_pin_clears_the_category_and_stays_out_of_the_classify_queue(self, db):
        curs = db.cursor()
        aid = _record(curs, "Opera", "5 gp general admission, 20 gp box seats;", "h1")
        update_ability_category(curs, aid, "special_sense")

        seed_ability_overrides(
            curs,
            [
                {
                    "name": "Opera",
                    "text": "5 gp general admission, 20 gp box seats;",
                    "ability_category": None,
                }
            ],
        )

        row = fetch_ability_by_id(curs, aid)
        assert row["ability_category"] is None
        assert row["human_verified"] == 1
        assert aid not in [r["ability_id"] for r in fetch_uncategorized_abilities(curs)]

    def test_an_unpinned_null_is_still_queued(self, db):
        curs = db.cursor()
        aid = _record(curs, "New Ability", "Text.", "h1")
        assert aid in [r["ability_id"] for r in fetch_uncategorized_abilities(curs)]


class TestTheCommittedPins:
    def test_every_pin_is_valid_and_keyed_once(self, db):
        pins = load_overrides("ability_overrides.json")
        keys = [(p["name"].lower(), p.get("text")) for p in pins]
        assert len(keys) == len(set(keys))
        # The seeder's own validation, against an empty DB: every pin a miss,
        # none an invalid category.
        seeded, misses = seed_ability_overrides(db.cursor(), pins)
        assert seeded == 0 and len(misses) == len(pins)


class TestMajorityVoteIsDeterministic:
    def test_a_tie_breaks_by_category_name(self, db):
        curs = db.cursor()
        for i, cat in enumerate(["special_sense", "automatic"]):
            aid = _record(curs, "Tied", f"text {i}", f"h{i}")
            curs.execute(
                "INSERT INTO ability_creature_links"
                " (ability_id, creature_game_id, creature_name, ability_category)"
                " VALUES (?, ?, ?, ?)",
                (aid, f"g{i}", f"c{i}", cat),
            )

        assert fetch_majority_category_for_name(curs, "Tied")[0] == "automatic"
