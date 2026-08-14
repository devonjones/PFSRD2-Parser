"""Tests for the QA verifiers (pfsrd2/qa/rune_clauses.py, material_traits.py).

These modules are the oracle the rune and material work is trusted against,
so their matching logic is tested directly: an over-matching resolver would
silently pass dead clauses, and a propagation check that never compares
anything would report success on an empty set.
"""

from pfsrd2.qa.material_traits import (
    check_grades,
    check_propagation,
    check_rarity,
    check_statistics,
    check_variant_grades,
)
from pfsrd2.qa.rune_clauses import (
    check_clauses,
    check_review_exclusivity,
    clause_matches,
    resolve,
)

WEAPON = {
    "name": "Clan Dagger",
    "stat_block": {
        "statistics": {"category": "Martial"},
        "traits": [{"name": "Thrown"}, {"name": "Monk"}],
        "offense": {
            "weapon_modes": [
                {"weapon_type": "Melee", "damage": [{"damage_type": "piercing"}]},
            ]
        },
    },
}


class TestResolve:
    def test_plain_path(self):
        assert resolve(WEAPON, "$.name") == ["Clan Dagger"]

    def test_nested_path(self):
        assert resolve(WEAPON, "$.stat_block.statistics.category") == ["Martial"]

    def test_wildcard_flattens_lists(self):
        assert resolve(WEAPON, "$.stat_block.traits[*].name") == ["Thrown", "Monk"]

    def test_nested_wildcards(self):
        path = "$.stat_block.offense.weapon_modes[*].damage[*].damage_type"
        assert resolve(WEAPON, path) == ["piercing"]

    def test_missing_key_yields_nothing_rather_than_raising(self):
        assert resolve(WEAPON, "$.stat_block.defense.ac_bonus") == []

    def test_missing_intermediate_does_not_raise(self):
        assert resolve({}, "$.a.b[*].c") == []

    def test_scalar_where_a_wildcard_was_expected(self):
        doc = {"stat_block": {"traits": {"name": "Solo"}}}
        assert resolve(doc, "$.stat_block.traits[*].name") == ["Solo"]


class TestClauseMatches:
    def test_matches_case_insensitively(self):
        clause = {"path": "$.stat_block.statistics.category", "op": "in", "values": ["martial"]}
        assert clause_matches(WEAPON, clause)

    def test_any_value_matching_is_enough(self):
        clause = {
            "path": "$.stat_block.traits[*].name",
            "op": "in",
            "values": ["Bulwark", "Monk"],
        }
        assert clause_matches(WEAPON, clause)

    def test_no_match(self):
        clause = {
            "path": "$.stat_block.offense.weapon_modes[*].damage[*].damage_type",
            "op": "in",
            "values": ["bludgeoning"],
        }
        assert not clause_matches(WEAPON, clause)

    def test_missing_path_never_matches(self):
        clause = {"path": "$.stat_block.nope", "op": "in", "values": ["anything"]}
        assert not clause_matches(WEAPON, clause)


def _rune(name, host, requires=None, conflicts=None, needs_review=False):
    block = {"host": host}
    if requires:
        block["requires"] = requires
    if conflicts:
        block["conflicts_with"] = conflicts
    if needs_review:
        block["needs_review"] = True
    return {"name": name, "stat_block": {"rune": block}}


class TestCheckClauses:
    def test_live_clause_passes(self):
        rune = _rune(
            "Monk's",
            "weapon",
            [{"path": "$.stat_block.traits[*].name", "op": "in", "values": ["Monk"]}],
        )
        assert check_clauses([rune], {"weapon": [WEAPON]}) == []

    def test_dead_clause_is_reported(self):
        rune = _rune(
            "Ghostly",
            "weapon",
            [{"path": "$.stat_block.traits[*].name", "op": "in", "values": ["Nonexistent"]}],
        )
        problems = check_clauses([rune], {"weapon": [WEAPON]})
        assert len(problems) == 1
        assert "matches no weapon" in problems[0][1]

    def test_conflict_naming_an_unknown_rune_is_reported(self):
        rune = _rune("Holy", "weapon", conflicts=["nonexistent"])
        problems = check_clauses([rune], {"weapon": [WEAPON]})
        assert "conflicts_with unknown rune" in problems[0][1]

    def test_conflict_naming_a_real_rune_passes(self):
        holy = _rune("Holy", "weapon", conflicts=["unholy"])
        unholy = _rune("Unholy", "weapon")
        assert check_clauses([holy, unholy], {"weapon": [WEAPON]}) == []

    def test_rune_suffix_is_stripped_when_matching_conflicts(self):
        conflicting = _rune("Disrupting", "weapon", conflicts=["reinforcing"])
        reinforcing = _rune("Reinforcing Rune", "shield")
        assert check_clauses([conflicting, reinforcing], {"weapon": [WEAPON]}) == []

    def test_missing_rune_block_is_reported(self):
        assert check_clauses([{"name": "Bare", "stat_block": {}}], {})[0][1] == "no rune block"


class TestReviewExclusivity:
    def test_review_with_clauses_is_reported(self):
        rune = _rune(
            "Shadow",
            "armor",
            requires=[{"path": "$.x", "op": "in", "values": ["y"]}],
            needs_review=True,
        )
        assert check_review_exclusivity([rune])

    def test_review_without_clauses_is_fine(self):
        assert check_review_exclusivity([_rune("Shadow", "armor", needs_review=True)]) == []

    def test_clauses_without_review_are_fine(self):
        rune = _rune("Keen", "weapon", requires=[{"path": "$.x", "op": "in", "values": ["y"]}])
        assert check_review_exclusivity([rune]) == []


def _material(name, precious=True, grants=None, grades=None, stats=True):
    block = {"precious": precious}
    if grants:
        block["grants_traits"] = grants
    if grades:
        block["grades"] = [{"grade": g} for g in grades]
    if stats:
        block["statistics"] = [{"form": "item", "hardness": 1}]
    return {"name": name, "edition": "remastered", "stat_block": {"material": block}}


def _use(name, material, traits, variants=None):
    return {
        "name": name,
        "edition": "remastered",
        "stat_block": {
            "material_use": {"host": "armor"},
            "base_material": {"name": material},
            "traits": [{"name": t} for t in traits],
            "variants": variants or [],
        },
    }


class TestMaterialChecks:
    def test_propagation_match_passes(self):
        materials = {("Adamantine", "remastered"): _material("Adamantine", grants=["Uncommon"])}
        uses = [_use("Adamantine Armor", "Adamantine", ["Uncommon"])]
        problems, checked = check_propagation(materials, uses)
        assert problems == []
        assert checked == 1

    def test_propagation_mismatch_is_reported(self):
        materials = {("Adamantine", "remastered"): _material("Adamantine", grants=["Uncommon"])}
        uses = [_use("Adamantine Armor", "Adamantine", ["Rare"])]
        problems, checked = check_propagation(materials, uses)
        assert len(problems) == 1 and checked == 1

    def test_use_page_without_base_material_is_skipped_not_failed(self):
        use = _use("Elven Chain", "Dawnsilver", [])
        del use["stat_block"]["base_material"]
        problems, checked = check_propagation({}, [use])
        assert problems == [] and checked == 0

    def test_unknown_base_material_is_reported(self):
        problems, _ = check_propagation({}, [_use("X Armor", "Nonexistent", [])])
        assert "has no material page" in problems[0]

    def test_precious_without_grades_is_reported(self):
        assert check_grades({("A", "remastered"): _material("A", precious=True)})

    def test_common_with_grades_is_reported(self):
        materials = {("Stone", "remastered"): _material("Stone", precious=False, grades=["low"])}
        assert check_grades(materials)

    def test_common_without_grades_is_fine(self):
        assert check_grades({("Stone", "remastered"): _material("Stone", precious=False)}) == []

    def test_missing_statistics_is_reported(self):
        assert check_statistics({("A", "remastered"): _material("A", grades=["high"], stats=False)})

    def test_present_statistics_pass(self):
        assert check_statistics({("A", "remastered"): _material("A", grades=["high"])}) == []

    def test_multiple_rarities_reported(self):
        materials = {("A", "remastered"): _material("A", grants=["Rare", "Uncommon"])}
        assert check_rarity(materials)

    def test_single_rarity_passes(self):
        assert check_rarity({("A", "remastered"): _material("A", grants=["Rare"])}) == []

    def test_variant_missing_grade_or_form_is_reported(self):
        use = _use(
            "A Armor",
            "A",
            [],
            variants=[
                {"name": "A Armor (Standard-Grade)", "material_use": {"grade": "standard"}},
            ],
        )
        problems = check_variant_grades([use])
        assert len(problems) == 1 and "item_form" in problems[0]

    def test_complete_variant_passes(self):
        use = _use(
            "A Armor",
            "A",
            [],
            variants=[
                {
                    "name": "A Armor (Standard-Grade)",
                    "material_use": {"grade": "standard", "item_form": "armor"},
                },
            ],
        )
        assert check_variant_grades([use]) == []
