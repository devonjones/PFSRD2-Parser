"""Placement lookups: where a template-added ability lands in the schema.

When a template says "the creature gains Grab", nothing in that sentence says
whether Grab is an offensive action or a defensive one. ability_placement
answers that from the ability's own action_type where it can, and otherwise
from what category the same ability name carries across creatures that already
have it.

Getting it wrong is silent: the ability still ships, just in the wrong part of
the creature. So the interesting cases here are the ones where two answers are
available and the code has to prefer one — action_type over DB history, the
most common category over a rarer one — and the ones where no answer exists at
all and the default has to be taken deliberately rather than by accident.
"""

import json

import pytest

from pfsrd2.ability_placement import (
    CATEGORY_TARGETS,
    DEFAULT_TARGET,
    ability_target,
    deterministic_ability_category,
    lookup_ability_categories,
    lookup_ability_category,
)
from pfsrd2.sql.enrichment import get_enrichment_db_connection
from pfsrd2.sql.enrichment.queries import insert_ability_record, insert_creature_link


@pytest.fixture
def db():
    conn = get_enrichment_db_connection(db_path=":memory:")
    yield conn
    conn.close()


def _record(db, name, *categories):
    """Give `name` one creature link per category listed."""
    curs = db.cursor()
    aid = insert_ability_record(curs, name, f"hash-{name}", json.dumps({"name": name}))
    for i, category in enumerate(categories):
        insert_creature_link(
            curs,
            aid,
            f"game-id-{name}-{i}",
            f"Creature {i}",
            1,
            None,
            "Bestiary",
            category,
        )
    db.commit()
    return aid


class TestLookupAbilityCategory:
    def test_an_unknown_name_takes_the_default_rather_than_failing(self, db):
        # A template may name an ability no creature has yet. That is not an
        # error; it is the case DEFAULT_TARGET exists for.
        assert lookup_ability_category("Nonexistent", conn=db) == (None, DEFAULT_TARGET)

    def test_the_most_common_category_wins(self, db):
        # The whole point of counting: one creature filing Grab as reactive
        # should not outvote three that file it as offensive.
        _record(db, "Grab", "offensive", "offensive", "offensive", "reactive")
        category, target = lookup_ability_category("Grab", conn=db)
        assert category == "offensive"
        assert target == CATEGORY_TARGETS["offensive"]

    def test_the_lookup_is_case_insensitive(self, db):
        # Sources capitalise inconsistently and a template quotes the name as
        # printed, so a case-sensitive match would silently miss and default.
        _record(db, "Darkvision", "special_sense")
        assert lookup_ability_category("darkvision", conn=db)[0] == "special_sense"
        assert lookup_ability_category("DARKVISION", conn=db)[0] == "special_sense"

    def test_a_category_with_no_target_falls_back_to_the_default(self, db):
        # The DB can hold a category string CATEGORY_TARGETS has no entry for.
        # The category is still reported truthfully; only the target defaults.
        _record(db, "Odd One", "not_a_real_category")
        category, target = lookup_ability_category("Odd One", conn=db)
        assert category == "not_a_real_category"
        assert target == DEFAULT_TARGET

    def test_an_ability_with_no_creature_links_is_a_miss(self, db):
        # The record exists but nothing says where it belongs, so there is no
        # evidence to place it on.
        curs = db.cursor()
        insert_ability_record(curs, "Orphan", "hash-orphan", '{"name": "Orphan"}')
        db.commit()
        assert lookup_ability_category("Orphan", conn=db) == (None, DEFAULT_TARGET)

    def test_every_mapped_category_resolves_to_its_own_target(self, db):
        # Guards the mapping itself: a typo in CATEGORY_TARGETS would quietly
        # send a whole category to DEFAULT_TARGET.
        for category, expected in CATEGORY_TARGETS.items():
            _record(db, f"Ability {category}", category)
            assert lookup_ability_category(f"Ability {category}", conn=db) == (
                category,
                expected,
            )


class TestLookupAbilityCategoriesBatch:
    """The batch form had no test at all, and it duplicates the single form's
    SQL rather than calling it — so the two can drift apart silently."""

    def test_it_answers_for_every_name_including_the_misses(self, db):
        # A caller indexes the result by name; a missing key would be a
        # KeyError at a distance from the cause.
        _record(db, "Grab", "offensive")
        result = lookup_ability_categories(["Grab", "Nonexistent"], conn=db)
        assert set(result) == {"Grab", "Nonexistent"}
        assert result["Grab"] == ("offensive", CATEGORY_TARGETS["offensive"])
        assert result["Nonexistent"] == (None, DEFAULT_TARGET)

    def test_it_agrees_with_the_single_lookup(self, db):
        # Pins the duplication. If either query changes, this fails.
        _record(db, "Grab", "offensive", "offensive", "reactive")
        _record(db, "Darkvision", "special_sense")
        names = ["Grab", "Darkvision", "Missing"]
        batch = lookup_ability_categories(names, conn=db)
        assert batch == {n: lookup_ability_category(n, conn=db) for n in names}

    def test_an_empty_request_is_an_empty_answer(self, db):
        assert lookup_ability_categories([], conn=db) == {}

    def test_a_repeated_name_collapses_rather_than_duplicating(self, db):
        _record(db, "Grab", "offensive")
        assert lookup_ability_categories(["Grab", "Grab"], conn=db) == {
            "Grab": ("offensive", CATEGORY_TARGETS["offensive"])
        }


class TestAbilityTarget:
    def test_action_type_beats_db_history(self, monkeypatch):
        # The ability's own action_type is direct evidence; the DB is a vote of
        # other creatures. A Reaction is reactive even if every creature that
        # has this name filed it as offensive.
        def _boom(*args, **kwargs):
            raise AssertionError("DB consulted despite a decisive action_type")

        monkeypatch.setattr("pfsrd2.ability_placement.lookup_ability_category", _boom)
        ability = {"name": "Grab", "action_type": {"name": "Reaction"}}
        assert ability_target(ability) == CATEGORY_TARGETS["reactive"]

    def test_it_falls_back_to_the_db_when_action_type_says_nothing(self, monkeypatch):
        monkeypatch.setattr(
            "pfsrd2.ability_placement.lookup_ability_category",
            lambda name, conn=None: ("special_sense", CATEGORY_TARGETS["special_sense"]),
        )
        assert ability_target({"name": "Darkvision"}) == CATEGORY_TARGETS["special_sense"]

    def test_a_nameless_ability_fails_instead_of_defaulting(self):
        # Documented as a parser bug rather than a placement question: with no
        # name there is nothing to look up, and defaulting would file it
        # somewhere plausible and wrong.
        with pytest.raises(AssertionError, match="missing required 'name'"):
            ability_target({"text": "Something happened."})

    def test_a_nameless_ability_with_a_decisive_action_type_still_places(self):
        # The assert guards the DB path only. action_type alone is enough, so
        # this must NOT raise — otherwise the assert is too eager.
        assert ability_target({"action_type": {"name": "Reaction"}}) == CATEGORY_TARGETS["reactive"]


class TestDeterministicAbilityCategory:
    """Covered elsewhere for the happy paths; these pin the boundaries."""

    @pytest.mark.parametrize("action_name", ["One Action", "Two Actions", "Three Actions"])
    def test_counted_actions_are_offensive(self, action_name):
        assert deterministic_ability_category({"action_type": {"name": action_name}}) == "offensive"

    def test_a_free_action_needs_a_trigger_to_be_reactive(self):
        # Without a trigger there is nothing reactive about it, and guessing
        # would file passive free actions as reactions.
        assert deterministic_ability_category({"action_type": {"name": "Free Action"}}) is None
        assert (
            deterministic_ability_category(
                {"action_type": {"name": "Free Action"}, "trigger": "An enemy moves."}
            )
            == "reactive"
        )

    def test_a_missing_or_malformed_action_type_is_undecidable(self):
        # Returning None sends the caller to the DB; returning a category here
        # would invent evidence the ability does not carry.
        assert deterministic_ability_category({}) is None
        assert deterministic_ability_category({"action_type": None}) is None
        assert deterministic_ability_category({"action_type": "Reaction"}) is None
        assert deterministic_ability_category({"action_type": {}}) is None
