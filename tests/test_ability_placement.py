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

    def test_an_unmapped_category_fails_instead_of_defaulting(self, db):
        # This used to return the category with DEFAULT_TARGET. The fallback
        # could only fire when someone added a category without adding its
        # mapping, so it existed solely to hide that — and hid it by routing a
        # whole category into $.defense.automatic_abilities, where it reads as
        # a real placement decision.
        _record(db, "Odd One", "not_a_real_category")
        with pytest.raises(AssertionError, match="no CATEGORY_TARGETS entry"):
            lookup_ability_category("Odd One", conn=db)

    def test_an_ability_with_no_creature_links_is_a_miss(self, db):
        # The record exists but nothing says where it belongs, so there is no
        # evidence to place it on.
        curs = db.cursor()
        insert_ability_record(curs, "Orphan", "hash-orphan", '{"name": "Orphan"}')
        db.commit()
        assert lookup_ability_category("Orphan", conn=db) == (None, DEFAULT_TARGET)

    # Literal, not derived from CATEGORY_TARGETS. Looping the mapping and
    # asserting production returns the same item compares it against itself:
    # repointing special_sense at "$.senses.wrong_place" survived the entire
    # suite, because nothing anywhere pinned these JSONPaths.
    EXPECTED_TARGETS = {
        "automatic": "$.defense.automatic_abilities",
        "reactive": "$.defense.reactive_abilities",
        "hp_automatic": "$.defense.hitpoints[*].automatic_abilities",
        "interaction": "$.interaction_abilities",
        "communication": "$.statistics.languages.communication_abilities",
        "offensive": "$.offense.offensive_actions",
        "special_sense": "$.senses.special_senses",
    }

    def test_the_mapping_is_exactly_these_seven_targets(self):
        # Set equality, so a new key cannot appear without this test naming it,
        # and a JSONPath cannot be edited without failing here.
        assert CATEGORY_TARGETS == self.EXPECTED_TARGETS

    def test_the_default_target_is_one_of_them(self):
        assert self.EXPECTED_TARGETS["automatic"] == DEFAULT_TARGET

    @pytest.mark.parametrize("category", sorted(EXPECTED_TARGETS))
    def test_each_category_resolves_to_its_literal_target(self, db, category):
        _record(db, f"Ability {category}", category)
        assert lookup_ability_category(f"Ability {category}", conn=db) == (
            category,
            self.EXPECTED_TARGETS[category],
        )


class TestLookupAbilityCategoriesBatch:
    """The batch form had no test at all.

    It used to carry its own copy of the single form's SQL — and a third copy
    lived in queries.fetch_majority_category_for_name, which is the helper both
    should have been calling. They now do, so these tests guard against the
    duplication coming back rather than against drift between two live copies.
    """

    def test_it_answers_for_every_name_including_the_misses(self, db):
        # A caller indexes the result by name; a missing key would be a
        # KeyError at a distance from the cause.
        _record(db, "Grab", "offensive")
        result = lookup_ability_categories(["Grab", "Nonexistent"], conn=db)
        assert set(result) == {"Grab", "Nonexistent"}
        assert result["Grab"] == ("offensive", CATEGORY_TARGETS["offensive"])
        assert result["Nonexistent"] == (None, DEFAULT_TARGET)

    def test_it_agrees_with_the_single_lookup(self, db):
        # Both forms now call queries.fetch_majority_category_for_name, so this
        # is a guard against either growing its own copy again. The case
        # variants matter: with every name spelled as inserted, removing
        # LOWER() from the batch query alone survived the whole suite.
        _record(db, "Grab", "offensive", "offensive", "reactive")
        _record(db, "Darkvision", "special_sense")
        names = ["Grab", "darkvision", "DARKVISION", "Missing"]
        batch = lookup_ability_categories(names, conn=db)
        assert batch == {n: lookup_ability_category(n, conn=db) for n in names}

    def test_an_empty_request_is_an_empty_answer(self, db):
        assert lookup_ability_categories([], conn=db) == {}


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

    def test_a_nameless_ability_fails_even_with_a_decisive_action_type(self):
        # This test used to assert the opposite, and by doing so it protected a
        # gap: the only production caller already guarantees a name, so the
        # nameless-but-typed case was unreachable, and allowing it meant the
        # assert did not mean what its message said. Hardening the code broke
        # exactly one test in the repo — this one.
        with pytest.raises(AssertionError, match="missing required 'name'"):
            ability_target({"action_type": {"name": "Reaction"}})


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


class TestTemplateAbilityEnrichmentPass:
    """What makes the template pass different from the creature pass.

    Its docstring's distinguishing claim is that it creates NO creature links,
    because a template's abilities describe what to ADD to a creature rather
    than what some creature has. Nothing tested that, so the pass could have
    started writing links — poisoning the very category votes that
    lookup_ability_category reads — with a green suite.
    """

    @pytest.fixture(autouse=True)
    def _no_llm(self, monkeypatch):
        # Belt and braces: inline enrichment reaches for the LLM extractor on
        # new records. For these abilities extract_all() finds nothing and
        # short-circuits before any import, so this is currently inert — but it
        # stops a richer fixture from quietly acquiring a model dependency.
        # monkeypatch, not set_inline_enrich(True) in teardown: the latter
        # restores a guessed value rather than the prior one, and would turn
        # the LLM ON for everything after if the flag were ever off on entry.
        import pfsrd2.ability_enrichment as ae

        monkeypatch.setattr(ae, "_inline_enrich", False)

    def _struct(self, *abilities):
        return {
            "edition": "remastered",
            "sections": [{"abilities": list(abilities)}],
        }

    def test_it_creates_no_creature_links(self, db):
        from pfsrd2.ability_enrichment import template_ability_enrichment_pass

        struct = self._struct({"name": "Grab", "subtype": "ability", "text": "The creature grabs."})
        template_ability_enrichment_pass(struct, conn=db)
        curs = db.cursor()
        curs.execute("SELECT COUNT(*) AS n FROM ability_creature_links")
        assert curs.fetchone()["n"] == 0

    def test_it_records_the_ability(self, db):
        from pfsrd2.ability_enrichment import template_ability_enrichment_pass

        struct = self._struct({"name": "Grab", "subtype": "ability", "text": "The creature grabs."})
        template_ability_enrichment_pass(struct, conn=db)
        curs = db.cursor()
        curs.execute("SELECT name FROM ability_records")
        assert [r["name"] for r in curs.fetchall()] == ["Grab"]

    def test_it_applies_the_deterministic_category_in_place(self, db):
        from pfsrd2.ability_enrichment import template_ability_enrichment_pass

        ability = {
            "name": "Retributive Strike",
            "subtype": "ability",
            "action_type": {"name": "Reaction"},
            "text": "The creature strikes back.",
        }
        template_ability_enrichment_pass(self._struct(ability), conn=db)
        assert ability["ability_category"] == "reactive"

    def test_the_same_ability_twice_reuses_one_record(self, db):
        # Two templates granting the same ability must not each mint a record.
        # What this pins is the fetch-by-hash reuse; that the hash covers more
        # than the name is pinned by tests/test_ability_identity.py.
        from pfsrd2.ability_enrichment import template_ability_enrichment_pass

        make = lambda: {  # noqa: E731
            "name": "Grab",
            "subtype": "ability",
            "text": "The creature grabs.",
        }
        template_ability_enrichment_pass(self._struct(make()), conn=db)
        template_ability_enrichment_pass(self._struct(make()), conn=db)
        curs = db.cursor()
        curs.execute("SELECT COUNT(*) AS n FROM ability_records")
        assert curs.fetchone()["n"] == 1

    def test_enrich_abilities_guards_subtype_itself(self, db):
        # _walk_all_abilities already filters by subtype, so a test driven
        # through the pass cannot fail when this guard is deleted — the two are
        # redundant along that path. Drive _enrich_abilities directly so the
        # guard is pinned on its own rather than by its neighbour.
        from pfsrd2.ability_enrichment import _enrich_abilities

        spell = {"name": "Fireball", "subtype": "spell", "text": "It burns."}
        _enrich_abilities([spell], db)
        db.commit()
        curs = db.cursor()
        curs.execute("SELECT COUNT(*) AS n FROM ability_records")
        assert curs.fetchone()["n"] == 0

    def test_a_category_already_on_the_record_is_applied(self, db):
        # The half of the categorization decision that is NOT action_type: an
        # ability with no decisive action gets its category from what the DB
        # already learned. Deleting that branch left the whole suite green, so
        # the silent-misplacement mode the module exists to prevent was dark.
        from pfsrd2.ability_enrichment import template_ability_enrichment_pass
        from pfsrd2.sql.enrichment.queries import update_ability_category

        first = {"name": "Darkvision", "subtype": "ability", "text": "It sees."}
        template_ability_enrichment_pass(self._struct(first), conn=db)
        assert "ability_category" not in first

        curs = db.cursor()
        curs.execute("SELECT ability_id FROM ability_records WHERE name = 'Darkvision'")
        update_ability_category(curs, curs.fetchone()["ability_id"], "special_sense")
        db.commit()

        second = {"name": "Darkvision", "subtype": "ability", "text": "It sees."}
        template_ability_enrichment_pass(self._struct(second), conn=db)
        assert second["ability_category"] == "special_sense"

    def test_a_decisive_action_type_is_not_overwritten_by_the_record(self, db):
        # The branch is guarded on "ability_category" not already being set.
        # The ability's own action_type is direct evidence and must win.
        from pfsrd2.ability_enrichment import template_ability_enrichment_pass
        from pfsrd2.sql.enrichment.queries import update_ability_category

        first = {
            "name": "Retributive Strike",
            "subtype": "ability",
            "action_type": {"name": "Reaction"},
            "text": "It strikes back.",
        }
        template_ability_enrichment_pass(self._struct(first), conn=db)
        curs = db.cursor()
        curs.execute("SELECT ability_id FROM ability_records WHERE name = 'Retributive Strike'")
        update_ability_category(curs, curs.fetchone()["ability_id"], "offensive")
        db.commit()

        second = dict(first)
        template_ability_enrichment_pass(self._struct(second), conn=db)
        assert second["ability_category"] == "reactive"
