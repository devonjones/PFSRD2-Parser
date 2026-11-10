"""ability_category is anchored: the LLM suggests, a human pins (PFSRD2-Parser-aiub).

The v3 rebuild missed the LLM cache and reshuffled published categories
(Ghostly Hand -> special_sense, Unholy Speed -> interaction). Driven for real
against an in-memory DB with the model stubbed.
"""

import importlib.machinery
import importlib.util
import json
import os

import pytest

from pfsrd2.ability_placement import NO_CATEGORY
from pfsrd2.enrichment.overrides import load_overrides, seed_ability_overrides
from pfsrd2.sql.enrichment import (
    fetch_ability_by_id,
    get_enrichment_db_connection,
    insert_ability_record,
    mark_human_verified,
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


OPERA = "5 gp general admission, 20 gp box seats;"


def _link(curs, ability_id, category):
    curs.execute(
        "INSERT INTO ability_creature_links"
        " (ability_id, creature_game_id, creature_name, ability_category)"
        " VALUES (?, ?, ?, ?)",
        (ability_id, f"g{ability_id}", f"c{ability_id}", category),
    )


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

    def test_a_null_pin_is_the_sentinel_and_stays_out_of_the_classify_queue(self, db):
        curs = db.cursor()
        aid = _record(curs, "Opera", OPERA, "h1")
        update_ability_category(curs, aid, "special_sense")

        seed_ability_overrides(curs, [{"name": "Opera", "text": OPERA, "ability_category": None}])

        assert fetch_ability_by_id(curs, aid)["ability_category"] == NO_CATEGORY
        assert aid not in [r["ability_id"] for r in fetch_uncategorized_abilities(curs)]

    @pytest.mark.parametrize("pinned", [None, "offensive"])
    def test_a_pin_that_contradicts_the_action_type_is_a_miss(self, db, pinned):
        # run_classify Step 0 would overwrite it with "reactive".
        curs = db.cursor()
        raw = {"name": "Snap", "text": "It snaps.", "action_type": {"name": "Reaction"}}
        aid = insert_ability_record(curs, "Snap", "h1", json.dumps(raw))
        pin = {"name": "Snap", "text": "It snaps.", "ability_category": pinned}

        assert seed_ability_overrides(curs, [pin]) == (0, [pin])
        assert fetch_ability_by_id(curs, aid)["human_verified"] == 0

    def test_one_conflicting_record_among_several_makes_the_pin_a_miss(self, db):
        # Same name and text, two editions: one plain, one a Reaction.
        curs = db.cursor()
        plain = insert_ability_record(
            curs, "Snap", "h1", json.dumps({"name": "Snap", "text": "It snaps."})
        )
        raw = {"name": "Snap", "text": "It snaps.", "action_type": {"name": "Reaction"}}
        insert_ability_record(curs, "Snap", "h2", json.dumps(raw))
        pin = {"name": "Snap", "text": "It snaps.", "ability_category": "automatic"}

        assert seed_ability_overrides(curs, [pin]) == (0, [pin])
        assert fetch_ability_by_id(curs, plain)["ability_category"] is None

    def test_a_pin_that_agrees_with_the_action_type_seeds(self, db):
        curs = db.cursor()
        raw = {"name": "Snap", "text": "It snaps.", "action_type": {"name": "Reaction"}}
        insert_ability_record(curs, "Snap", "h1", json.dumps(raw))
        pin = {"name": "Snap", "text": "It snaps.", "ability_category": "reactive"}

        assert seed_ability_overrides(curs, [pin]) == (1, [])

    def test_a_field_verified_record_with_no_category_is_still_queued(self, db):
        # bin/pf2_ability_review verify/edit set human_verified for checked
        # FIELDS; that must not take the record out of classification.
        curs = db.cursor()
        aid = _record(curs, "New Ability", "Text.", "h1")
        mark_human_verified(curs, aid)
        assert aid in [r["ability_id"] for r in fetch_uncategorized_abilities(curs)]


class TestPinnedNoCategorySurvivesClassification:
    """Both vote-filling steps see the pin and leave it alone."""

    @pytest.fixture
    def pinned(self, db):
        curs = db.cursor()
        aid = _record(curs, "Opera", OPERA, "h1")
        seed_ability_overrides(curs, [{"name": "Opera", "text": OPERA, "ability_category": None}])
        # A creature somewhere has an ability called Opera, so a name vote exists.
        voter = _record(curs, "Opera", "A creature's song.", "h2")
        _link(curs, voter, "interaction")
        return aid

    def test_the_name_vote_step(self, db, pinned):
        load_cli().run_classify(db, Args())
        assert fetch_ability_by_id(db.cursor(), pinned)["ability_category"] == NO_CATEGORY

    def test_the_uma_step(self, db, pinned, monkeypatch):
        cli = load_cli()
        db.execute("UPDATE ability_records SET is_uma = 1 WHERE ability_id = ?", (pinned,))
        main = get_enrichment_db_connection(db_path=":memory:")
        monkeypatch.setattr(cli, "get_db_connection", lambda *_a, **_k: main)
        monkeypatch.setattr(cli, "fetch_monster_abilities_by_name", lambda *_a: [])

        cli.run_uma_detection(db, Args())

        assert fetch_ability_by_id(db.cursor(), pinned)["ability_category"] == NO_CATEGORY


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
            _link(curs, _record(curs, "Tied", f"text {i}", f"h{i}"), cat)

        assert fetch_majority_category_for_name(curs, "Tied")[0] == "automatic"
