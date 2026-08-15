"""Tests for the QA verifiers (pfsrd2/qa/rune_clauses.py, material_traits.py).

These modules are the oracle the rune and material work is trusted against,
so their matching logic is tested directly: an over-matching resolver would
silently pass dead clauses, and a propagation check that never compares
anything would report success on an empty set.
"""

import json

import pytest

from pfsrd2.qa import data_dir, load_equipment, load_json_dir
from pfsrd2.qa.material_traits import (
    check_grades,
    check_propagation,
    check_rarity,
    check_statistics,
    check_variant_grades,
)
from pfsrd2.qa.material_traits import main as material_main
from pfsrd2.qa.rune_clauses import (
    check_clauses,
    check_review_exclusivity,
    clause_matches,
    resolve,
)
from pfsrd2.qa.rune_clauses import main as rune_main

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

    def test_descending_past_a_scalar_yields_nothing(self):
        # The isinstance(value, dict) guard: statistics resolves to a string,
        # so the next segment has nothing to descend into.
        doc = {"stat_block": {"statistics": "not-a-dict"}}
        assert resolve(doc, "$.stat_block.statistics.category") == []

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

    def test_known_page_without_base_material_is_skipped(self):
        # Elven Chain is a specific armor, not a generic material use page.
        use = _use("Elven Chain", "Dawnsilver", [])
        del use["stat_block"]["base_material"]
        problems, checked = check_propagation({}, [use])
        assert problems == [] and checked == 0

    def test_unknown_page_without_base_material_is_reported(self):
        # Scoped exception, not a blanket skip: any other page missing a base
        # material is one this verifier silently could not check.
        use = _use("Mystery Armor", "Dawnsilver", [])
        del use["stat_block"]["base_material"]
        problems, checked = check_propagation({}, [use])
        assert checked == 0
        assert "has no base_material" in problems[0]

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

    def test_variant_missing_grade_is_reported(self):
        use = _use(
            "A Armor",
            "A",
            [],
            variants=[
                {"name": "A Armor (Standard-Grade)", "material_use": {"item_form": "armor"}},
            ],
        )
        problems = check_variant_grades([use])
        assert len(problems) == 1 and "no grade" in problems[0]

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


class TestLoaders:
    """pfsrd2/qa/__init__.py — hermetic, via the PF2_DATA_DIR override that
    exists on this module specifically to make it testable."""

    @pytest.fixture
    def data_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PF2_DATA_DIR", str(tmp_path))
        return tmp_path

    def _write(self, root, relative, doc):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def test_data_dir_honours_the_override(self, data_root):
        assert data_dir() == str(data_root)

    def test_data_dir_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.delenv("PF2_DATA_DIR", raising=False)
        assert data_dir().endswith("pfsrd2-data")

    def test_load_json_dir_reads_nested_files(self, data_root):
        self._write(data_root, "equipment/book/a.json", {"name": "A"})
        self._write(data_root, "equipment/book/deeper/b.json", {"name": "B"})
        assert sorted(d["name"] for d in load_json_dir("equipment")) == ["A", "B"]

    def test_load_json_dir_spans_several_directories(self, data_root):
        self._write(data_root, "weapons/w.json", {"name": "W"})
        self._write(data_root, "armor/a.json", {"name": "A"})
        assert sorted(d["name"] for d in load_json_dir("weapons", "armor")) == ["A", "W"]

    def test_load_json_dir_on_a_missing_directory_is_empty(self, data_root):
        assert load_json_dir("nope") == []

    def test_load_equipment_without_a_predicate_returns_everything(self, data_root):
        self._write(data_root, "equipment/book/a.json", {"name": "A"})
        self._write(data_root, "equipment/book/b.json", {"name": "B"})
        assert len(load_equipment()) == 2

    def test_load_equipment_applies_the_predicate(self, data_root):
        self._write(
            data_root,
            "equipment/book/rune.json",
            {"name": "Striking", "stat_block": {"item_category": "Runes"}},
        )
        self._write(
            data_root,
            "equipment/book/other.json",
            {"name": "Rope", "stat_block": {"item_category": "Adventuring Gear"}},
        )
        kept = load_equipment(lambda d: d.get("stat_block", {}).get("item_category") == "Runes")
        assert [d["name"] for d in kept] == ["Striking"]


class TestVerifierMain:
    """main() end to end, hermetically.

    The vacuous-success guards live here, and they are the whole reason the
    verifiers can be trusted — a dropped return or an inverted condition would
    silently restore the failure mode three reviewers independently flagged.
    Both modules reach the filesystem only through load_equipment/load_json_dir,
    so a PF2_DATA_DIR override drives them with no mocking.
    """

    @pytest.fixture
    def data_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PF2_DATA_DIR", str(tmp_path))
        return tmp_path

    def _write(self, root, relative, doc):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def _material_doc(self, name, grants):
        return {
            "name": name,
            "edition": "remastered",
            "stat_block": {
                "item_category": "Materials",
                "material": {
                    "precious": True,
                    "grants_traits": grants,
                    "grades": [{"grade": "high"}],
                    "statistics": [{"form": "item", "hardness": 1}],
                },
            },
        }

    def _use_doc(self, name, base, traits, with_base=True):
        stat_block = {
            "material_use": {"host": "armor"},
            "traits": [{"name": t} for t in traits],
            "variants": [
                {
                    "name": f"{name} (High-Grade)",
                    "material_use": {"grade": "high", "item_form": "armor"},
                }
            ],
        }
        if with_base:
            stat_block["base_material"] = {"name": base}
        return {"name": name, "edition": "remastered", "stat_block": stat_block}

    def test_material_main_passes_on_agreeing_data(self, data_root):
        self._write(
            data_root, "equipment/b/adamantine.json", self._material_doc("Adamantine", ["Uncommon"])
        )
        self._write(
            data_root,
            "equipment/b/adamantine_armor.json",
            self._use_doc("Adamantine Armor", "Adamantine", ["Uncommon"]),
        )
        assert material_main() == 0

    def test_material_main_fails_when_nothing_was_compared(self, data_root, capsys):
        # Use pages exist but none names a base_material, so checked == 0.
        # Without the guard this prints success and exits 0.
        self._write(
            data_root, "equipment/b/adamantine.json", self._material_doc("Adamantine", ["Uncommon"])
        )
        self._write(
            data_root,
            "equipment/b/elven_chain.json",
            self._use_doc("Elven Chain", "Adamantine", [], with_base=False),
        )
        assert material_main() == 1
        assert "no propagation comparisons ran" in capsys.readouterr().out

    def test_material_main_fails_with_no_use_pages(self, data_root):
        self._write(
            data_root, "equipment/b/adamantine.json", self._material_doc("Adamantine", ["Uncommon"])
        )
        assert material_main() == 1

    def test_material_main_fails_on_a_propagation_mismatch(self, data_root, capsys):
        self._write(
            data_root, "equipment/b/adamantine.json", self._material_doc("Adamantine", ["Uncommon"])
        )
        self._write(
            data_root,
            "equipment/b/adamantine_armor.json",
            self._use_doc("Adamantine Armor", "Adamantine", ["Rare"]),
        )
        assert material_main() == 1
        assert "PROBLEMS" in capsys.readouterr().out

    def _rune_doc(self, name, requires=None):
        block = {"host": "weapon"}
        if requires:
            block["requires"] = requires
        return {
            "name": name,
            "edition": "remastered",
            "stat_block": {"item_category": "Runes", "rune": block},
        }

    def _hosts(self, root):
        for kind, doc in (
            ("weapons", WEAPON),
            ("armor", {"name": "Chain Shirt"}),
            ("shields", {"name": "Buckler"}),
        ):
            self._write(root, f"{kind}/x.json", doc)

    def test_rune_main_passes_on_live_clauses(self, data_root):
        self._hosts(data_root)
        self._write(
            data_root,
            "equipment/b/monks.json",
            self._rune_doc(
                "Monk's", [{"path": "$.stat_block.traits[*].name", "op": "in", "values": ["Monk"]}]
            ),
        )
        assert rune_main() == 0

    def test_rune_main_fails_when_a_host_directory_is_empty(self, data_root, capsys):
        # weapons/ and armor/ exist, shields/ does not. Every shield-host rune
        # has empty requires in real data, so without this guard a missing
        # shields/ directory verifies nothing and still exits 0.
        self._write(data_root, "weapons/x.json", WEAPON)
        self._write(data_root, "armor/x.json", {"name": "Chain Shirt"})
        self._write(data_root, "equipment/b/monks.json", self._rune_doc("Monk's"))
        assert rune_main() == 1
        assert "shield" in capsys.readouterr().out

    def test_rune_main_fails_on_a_dead_clause(self, data_root, capsys):
        self._hosts(data_root)
        self._write(
            data_root,
            "equipment/b/ghostly.json",
            self._rune_doc(
                "Ghostly",
                [{"path": "$.stat_block.traits[*].name", "op": "in", "values": ["Nonexistent"]}],
            ),
        )
        assert rune_main() == 1
        assert "DEAD CLAUSES" in capsys.readouterr().out

    def test_rune_main_fails_with_no_rune_data(self, data_root):
        self._hosts(data_root)
        assert rune_main() == 1


class TestEveryCheckReachesTheExitCode:
    """Each check must be wired into main(), not merely defined.

    Every check below is unit-tested in isolation, but a check that gets
    unwired from main() stops failing the build while its own tests keep
    passing — the same silent-disabling failure mode the vacuous-success
    guards exist to prevent. These drive main() with data that violates one
    check at a time and assert a non-zero exit.
    """

    @pytest.fixture
    def data_root(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PF2_DATA_DIR", str(tmp_path))
        return tmp_path

    def _write(self, root, relative, doc):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc))

    def _material(self, grants=("Uncommon",), precious=True, grades=("high",), stats=True):
        block = {"precious": precious, "grants_traits": list(grants)}
        if grades:
            block["grades"] = [{"grade": g} for g in grades]
        if stats:
            block["statistics"] = [{"form": "item", "hardness": 1}]
        return {
            "name": "Adamantine",
            "edition": "remastered",
            "stat_block": {"item_category": "Materials", "material": block},
        }

    def _use(self, traits=("Uncommon",), variant_use=None):
        return {
            "name": "Adamantine Armor",
            "edition": "remastered",
            "stat_block": {
                "material_use": {"host": "armor"},
                "base_material": {"name": "Adamantine"},
                "traits": [{"name": t} for t in traits],
                "variants": [
                    {
                        "name": "Adamantine Armor (High-Grade)",
                        "material_use": (
                            variant_use
                            if variant_use is not None
                            else {"grade": "high", "item_form": "armor"}
                        ),
                    }
                ],
            },
        }

    def _seed(self, root, material, use):
        self._write(root, "equipment/b/material.json", material)
        self._write(root, "equipment/b/use.json", use)

    def test_baseline_is_clean(self, data_root):
        self._seed(data_root, self._material(), self._use())
        assert material_main() == 0

    def test_check_grades_reaches_the_exit_code(self, data_root):
        # precious but no grades
        self._seed(data_root, self._material(grades=()), self._use())
        assert material_main() == 1

    def test_check_statistics_reaches_the_exit_code(self, data_root):
        self._seed(data_root, self._material(stats=False), self._use())
        assert material_main() == 1

    def test_check_rarity_reaches_the_exit_code(self, data_root):
        self._seed(
            data_root,
            self._material(grants=("Rare", "Uncommon")),
            self._use(traits=("Rare", "Uncommon")),
        )
        assert material_main() == 1

    def test_check_variant_grades_reaches_the_exit_code(self, data_root):
        self._seed(data_root, self._material(), self._use(variant_use={"item_form": "armor"}))
        assert material_main() == 1

    def test_check_review_exclusivity_reaches_the_exit_code(self, data_root):
        for kind, doc in (
            ("weapons", WEAPON),
            ("armor", {"name": "Chain Shirt"}),
            ("shields", {"name": "Buckler"}),
        ):
            self._write(data_root, f"{kind}/x.json", doc)
        self._write(
            data_root,
            "equipment/b/shadow.json",
            {
                "name": "Shadow",
                "edition": "remastered",
                "stat_block": {
                    "item_category": "Runes",
                    "rune": {
                        "host": "weapon",
                        "needs_review": True,
                        "requires": [
                            {"path": "$.stat_block.traits[*].name", "op": "in", "values": ["Monk"]}
                        ],
                    },
                },
            },
        )
        assert rune_main() == 1
