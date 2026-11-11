"""Level-scaled damage, one case per phrasing found in templates and families."""

import ast
import inspect
import json
import textwrap

import pytest

from pfsrd2 import monster_family, monster_template
from pfsrd2.ability_enrichment import _merge_enrichment
from pfsrd2.enrichment.change_extractor import name_filter
from pfsrd2.enrichment.level_scaling import (
    extract_level_scaling,
    formula_at_level,
    level_scaling_effects,
    level_scaling_effects_pass,
)

POWER_SURGE = (
    "deals 1d6 additional damage with its Strikes until the end of its turn. "
    "This additional damage increases to 2d6 if the experimental cryptid is 9th level or "
    "higher, 3d6 if the experimental cryptid is 15th level or higher, and 4d6 if the "
    "experimental cryptid is 18th level or higher."
)
CAUSTIC = (
    "creatures adjacent to the mutant take 1d6 acid damage (basic Reflex save). The damage "
    "increases to 2d6 if the mutant is at least 8th level and 3d6 if the mutant is at least "
    "15th level."
)
CLINGING = (
    "dealing 1d4 persistent piercing damage, increasing to 2d4 at 5th level, 3d4 at 10th "
    "level, 4d4 at 15th level, and 5d4 at 20th level."
)


@pytest.mark.parametrize(
    "text, steps",
    [
        (POWER_SURGE, [(9, "2d6"), (15, "3d6"), (18, "4d6")]),
        (CAUSTIC, [(8, "2d6"), (15, "3d6")]),
        (CLINGING, [(5, "2d4"), (10, "3d4"), (15, "4d4"), (20, "5d4")]),
    ],
)
def test_thresholds_are_read_as_printed(text, steps):
    base = "1d4" if "1d4" in text else "1d6"
    got = extract_level_scaling(text, base)
    assert [(s["min_level"], s["formula"]) for s in got["steps"]] == steps


# (text, base formula, expected scaling, {level: formula})
INCREMENTS = [
    (
        "deal 1d6 damage of the chosen type. The damage increases by 1d6 at 3rd level and "
        "every odd level thereafter.",
        "1d6",
        {"increment": "1d6", "per_levels": 2, "start_level": 3, "additive": True},
        {1: "1d6", 3: "2d6", 4: "2d6", 5: "3d6"},
    ),
    (
        "they deal 1d6 piercing damage. The damage increases by 1d6 at 4th level and every 3 "
        "levels thereafter.",
        "1d6",
        {"increment": "1d6", "per_levels": 3, "start_level": 4, "additive": True},
        {3: "1d6", 4: "2d6", 7: "3d6"},
    ),
    (
        "take 1d6 persistent poison damage (plus an additional 1d6 for every 6 levels the "
        "skeleton has).",
        "1d6",
        {"increment": "1d6", "per_levels": 6, "start_level": 6, "additive": True},
        {5: "1d6", 6: "2d6", 12: "3d6"},
    ),
    (
        "This damage increases by 1d6 for every 6 levels the zombie has.",
        "1d6",
        {"increment": "1d6", "per_levels": 6, "start_level": 6, "additive": True},
        {6: "2d6"},
    ),
    (
        "The target takes 1d6 negative damage + 1d6 per 2 levels with a basic Will save.",
        "1d6",
        {"increment": "1d6", "per_levels": 2, "start_level": 2, "additive": True},
        {1: "1d6", 2: "2d6", 4: "3d6"},
    ),
    (
        "a hand unarmed attack that deals 1d8 negative damage for every 3 levels",
        "1d8",
        {"increment": "1d8", "per_levels": 3, "start_level": 3, "additive": False},
        {2: "1d8", 3: "1d8", 9: "3d8"},
    ),
    (
        "an antler attack that deals 1d6+2 bludgeoning damage for every 3 levels",
        "1d6+2",
        {"increment": "1d6+2", "per_levels": 3, "start_level": 3, "additive": False},
        {6: "2d6+4"},
    ),
    (
        "erupts with divine energy in a 30-foot emanation, dealing 1d6 damage per level.",
        "1d6",
        {"increment": "1d6", "per_levels": 1, "start_level": 1, "additive": False},
        {0: "1d6", 1: "1d6", 7: "7d6"},
    ),
    (
        "The creature takes 1d4 mental damage per level of the blackfrost dead (minimum 2d4), "
        "with a basic Will save.",
        "1d4",
        {
            "increment": "1d4",
            "per_levels": 1,
            "start_level": 1,
            "additive": False,
            "minimum": "2d4",
        },
        {1: "2d4", 5: "5d4"},
    ),
    (
        "takes 1d8 bludgeoning damage per level of the floodslain creature (minimum 1d8) with "
        "a basic Reflex save",
        "1d8",
        {
            "increment": "1d8",
            "per_levels": 1,
            "start_level": 1,
            "additive": False,
            "minimum": "1d8",
        },
        {0: "1d8", 4: "4d8"},
    ),
    (
        "deals 1d12 acid damage per 3 levels of the zombie (or 1d6 acid damage below level 3).",
        "1d12",
        {
            "increment": "1d12",
            "per_levels": 3,
            "start_level": 3,
            "additive": False,
            "below_start": "1d6",
        },
        {2: "1d6", 3: "1d12", 6: "2d12"},
    ),
    (
        "Failure to do so deals the affected creature 1d6 mental damage, plus 1d6 for every 5 "
        "levels the visitant has.",
        "1d6",
        {"increment": "1d6", "per_levels": 5, "start_level": 5, "additive": True},
        {10: "3d6"},
    ),
]


@pytest.mark.parametrize("text, base, expected, levels", INCREMENTS)
def test_increments(text, base, expected, levels):
    got = extract_level_scaling(text, base)
    assert {k: v for k, v in got.items() if k not in ("type", "subtype")} == expected
    for level, formula in levels.items():
        assert formula_at_level(base, got, level) == formula, level


def test_steps_resolve_by_level():
    s = extract_level_scaling(POWER_SURGE, "1d6")
    assert [formula_at_level("1d6", s, lv) for lv in (8, 9, 14, 15, 18)] == [
        "1d6",
        "2d6",
        "2d6",
        "3d6",
        "4d6",
    ]


@pytest.mark.parametrize(
    "text",
    [
        "deals 2d6 fire damage with a basic Reflex save.",
        # weapon dice, not a formula: Clobber stays text
        "If the experimental cryptid is at least 5th level, this Strike deals one additional "
        "weapon damage die of damage.",
        # another die's scaling is not this formula's
        "deals 1d6 fire damage plus 1d8 for every 3 levels.",
        # spell heightening, not creature level
        "deals 1d6 fire damage, plus 1d6 per spell level above 1st.",
        # the level of something else (skelm's Seize Prayer, a counteracted ability)
        "each take 1d6 mental damage per level of the triggering spell",
        "dealing 1d6 force damage per level of the ability she counteracted",
    ],
)
def test_no_scaling_is_none(text):
    assert extract_level_scaling(text, "1d6") is None


def _damage(formula, **extra):
    return {"type": "stat_block_section", "subtype": "attack_damage", "formula": formula, **extra}


def _merged(ability, *damage):
    _merge_enrichment(ability, json.dumps({"damage": list(damage)}))
    return ability["damage"]


def test_merge_marks_scaling_on_enriched_damage():
    (dmg,) = _merged({"name": "Power Surge", "text": POWER_SURGE}, _damage("1d6"))
    assert [s["min_level"] for s in dmg["level_scaling"]["steps"]] == [9, 15, 18]


SHOCKWAVE = (
    "Creatures on the ground within 30 feet of the primeval cryptid take 1d6 bludgeoning "
    "damage per level of the primeval cryptid (minimum 2d6 damage), with a basic Reflex save."
)


def test_merge_reads_the_effect_field_and_drops_the_floor_entry():
    # Shockwave's text is in `effect`; its "(minimum 2d6 damage)" is also
    # extracted as a damage entry, which would apply as extra damage
    (rate,) = _merged({"name": "Shockwave", "effect": SHOCKWAVE}, _damage("1d6"), _damage("2d6"))
    assert rate["level_scaling"]["minimum"] == "2d6"


@pytest.mark.parametrize(
    "text, other",
    [
        # unrelated damage on the same ability
        (SHOCKWAVE + " It also takes 1d4 fire damage.", _damage("1d4", damage_type="fire")),
        # the floor's dice also appear outside the parenthetical
        (SHOCKWAVE + " A creature that falls prone takes 2d6 damage.", _damage("2d6")),
        # a typed entry is real damage, not the floor's echo
        (SHOCKWAVE, _damage("2d6", damage_type="fire")),
        # typeless dice that are not the floor
        (SHOCKWAVE, _damage("3d6")),
    ],
)
def test_the_floor_drop_keeps_real_damage(text, other):
    rate, kept = _merged({"name": "Shockwave", "effect": text}, _damage("1d6"), other)
    assert "level_scaling" in rate and kept == other


def test_a_longer_formula_does_not_hide_the_floor_echo():
    text = SHOCKWAVE + " A creature that falls prone takes 12d6 damage."
    (rate,) = _merged({"name": "Shockwave", "effect": text}, _damage("1d6"), _damage("2d6"))
    assert rate["level_scaling"]["minimum"] == "2d6"


def test_a_floor_equal_to_the_base_keeps_the_base_entry():
    vomit = "takes 1d8 bludgeoning damage per level of the floodslain creature (minimum 1d8)"
    (dmg,) = _merged({"name": "Vomit Flotsam", "text": vomit}, _damage("1d8"))
    assert dmg["level_scaling"]["minimum"] == "1d8"


def test_merge_keeps_an_existing_level_scaling():
    kept = {"type": "stat_block_section", "subtype": "level_scaling", "steps": []}
    (dmg,) = _merged(
        {"name": "Power Surge", "text": POWER_SURGE}, _damage("1d6", level_scaling=kept)
    )
    assert dmg["level_scaling"] == kept


def test_steps_only_after_the_intro_and_only_for_this_die():
    early = "deals 1d6 damage, 2d6 at 3rd level of fury. It increases to 2d6 at 9th level."
    assert extract_level_scaling(early, "1d6")["steps"] == [{"min_level": 9, "formula": "2d6"}]
    assert extract_level_scaling(POWER_SURGE, "1d8") is None
    mixed = "deals 1d6 damage. It increases to 2d6 at 9th level and 3d8 at 15th level."
    assert extract_level_scaling(mixed, "1d6")["steps"] == [{"min_level": 9, "formula": "2d6"}]


def test_an_unread_level_keyed_increase_fails_loudly():
    with pytest.raises(AssertionError, match="unread level scaling"):
        extract_level_scaling("increases to 2d6 when the creature reaches level 9.", "1d6")


def test_thereafter_needs_this_entrys_dice():
    text = "deals 1d6 fire. The damage increases by 1d8 at 3rd level and every 2 levels thereafter."
    assert extract_level_scaling(text, "1d6") is None


@pytest.mark.parametrize(
    "word, n", [("two", 2), ("three", 3), ("four", 4), ("five", 5), ("six", 6)]
)
def test_number_words(word, n):
    got = extract_level_scaling(f"plus an additional 1d6 for every {word} levels", "1d6")
    assert got["per_levels"] == n


def test_below_start_must_name_the_start_level():
    text = "deals 1d12 acid damage per 3 levels of the zombie (or 1d6 acid damage below level 4)."
    with pytest.raises(AssertionError, match="below level 4"):
        extract_level_scaling(text, "1d12")


@pytest.mark.parametrize(
    "text, formula",
    [
        ("deals 1d6 damage per level", None),
        ("deals 1d6 damage per level", ""),
        ("", "1d6"),
        # a flat bonus is not dice (Strikes' "+1" damage adjustments)
        ("It increases to 2d6 at 9th level.", "+1"),
    ],
)
def test_nothing_to_scale_is_none(text, formula):
    assert extract_level_scaling(text, formula) is None


def test_ritual_level_is_not_creature_level():
    assert extract_level_scaling("takes 1d6 damage per level of the ritual", "1d6") is None
    # ...but the creature's own level still reads, even when "ability" follows
    got = extract_level_scaling(
        "takes 1d6 damage per level of the creature using this ability", "1d6"
    )
    assert got["per_levels"] == 1


def test_steps_stay_in_their_sentence_and_in_level_order():
    text = (
        "deals 1d6 damage. It increases to 3d6 at 15th level and 2d6 at 9th level. "
        "A separate 4d6 at 20th level blast is another ability."
    )
    got = extract_level_scaling(text, "1d6")
    assert got["steps"] == [{"min_level": 9, "formula": "2d6"}, {"min_level": 15, "formula": "3d6"}]
    assert formula_at_level("1d6", got, 16) == "3d6"


def test_additive_scaling_on_other_dice_is_rejected():
    scaling = {"increment": "1d6", "per_levels": 2, "start_level": 2, "additive": True}
    with pytest.raises(AssertionError):
        formula_at_level("1d8", scaling, 4)


def test_additive_keeps_the_base_modifier_and_signed_modifiers_parse():
    s = extract_level_scaling(
        "deals 1d6+2 damage plus an additional 1d6+2 for every 3 levels", "1d6+2"
    )
    assert formula_at_level("1d6+2", s, 6) == "3d6+6"
    s = extract_level_scaling("deals 1d6-1 damage for every 2 levels", "1d6-1")
    assert formula_at_level("1d6-1", s, 4) == "2d6-2"


def test_a_spaced_modifier_is_normalised():
    s = extract_level_scaling(
        "an antler attack that deals 1d6 + 2 damage for every 3 levels", "1d6+2"
    )
    assert s["increment"] == "1d6+2"


def test_minimum_holds_below_the_first_step():
    s = extract_level_scaling(SHOCKWAVE, "1d6")
    assert [formula_at_level("1d6", s, lv) for lv in (-1, 0, 1, 3)] == ["2d6", "2d6", "2d6", "3d6"]


# --- level_scaling_effects -------------------------------------------------


def _change(*abilities, effects=None, category="abilities"):
    return {"change_category": category, "abilities": list(abilities), "effects": effects or []}


def _level_change(value):
    adjust = {"operation": "adjustment", "target": "$.creature_type.level", "value": value}
    return _change(category="level", effects=[adjust])


def _add_items(name, target):
    return {"operation": "add_items", "names": [name], "target": target, "source": "x"}


def _scaled(name, formula, scaling):
    return {"name": name, "damage": [_damage(formula, level_scaling=scaling)]}


POWER = {"steps": [{"min_level": 9, "formula": "2d6"}, {"min_level": 15, "formula": "3d6"}]}


def _replaces(change):
    return [
        (e["target"], e["value"], e["conditional"])
        for e in change["effects"]
        if e["operation"] == "replace"
    ]


def test_effects_band_the_starting_level_and_wrap_offensive_actions():
    change = _change(
        _scaled("Power Surge", "1d6", POWER),
        effects=[_add_items("Power Surge", "$.offense.offensive_actions")],
    )
    # templates change the level first: that +1 is already in the conditional's
    # level, so it must not shift the bands
    level_scaling_effects([_level_change(1), change])
    path = "$.offense.offensive_actions[?(@.name=='Power Surge')].ability.damage[?(@.formula=='1d6')].formula"
    assert _replaces(change) == [
        (path, "2d6", "$.creature_type.level >= 9 && $.creature_type.level <= 14"),
        (path, "3d6", "$.creature_type.level >= 15"),
    ]


def test_a_later_level_change_shifts_the_bands():
    # families run their level change last: a +1 creature that starts at 8
    # ends at 9, so the 9th-level step applies from starting level 8
    level = _level_change(1)
    change = _change(
        _scaled("X", "1d6", POWER), effects=[_add_items("X", "$.interaction_abilities")]
    )
    level_scaling_effects([change, level])
    assert _replaces(change)[0] == (
        "$.interaction_abilities[?(@.name=='X')].damage[?(@.formula=='1d6')].formula",
        "2d6",
        "$.creature_type.level >= 8 && $.creature_type.level <= 13",
    )


def test_select_options_count_as_placements():
    select = {
        "operation": "select",
        "target": "t",
        "selection": {"options": [_add_items("X", "$.interaction_abilities")]},
    }
    change = _change(_scaled("X", "1d6", POWER), effects=[select])
    level_scaling_effects([change])
    # selections apply after every change, so the replaces ride in the option
    assert _replaces(change) == []
    (bundle,) = select["selection"]["options"]
    add, *replaces = bundle["effects"]
    assert add["operation"] == "add_items"
    assert [e["value"] for e in replaces] == ["2d6", "3d6"]


def test_an_option_without_scaling_is_left_unbundled():
    options = [
        _add_items("X", "$.interaction_abilities"),
        _add_items("Y", "$.interaction_abilities"),
    ]
    select = {"operation": "select", "target": "t", "selection": {"options": options}}
    unscaled = {"name": "Y", "damage": [_damage("1d6")]}
    level_scaling_effects([_change(_scaled("X", "1d6", POWER), unscaled, effects=[select])])
    assert "effects" in options[0] and options[1]["operation"] == "add_items"


def test_an_ability_placed_twice_fails():
    effects = [_add_items("X", "$.a"), _add_items("X", "$.b")]
    with pytest.raises(AssertionError, match="placed twice"):
        level_scaling_effects([_change(_scaled("X", "1d6", POWER), effects=effects)])


def test_a_level_effect_it_cannot_count_fails():
    level = _change(
        category="level",
        effects=[{"operation": "replace", "target": "$.creature_type.level", "value": 5}],
    )
    change = _change(_scaled("X", "1d6", POWER), effects=[_add_items("X", "$.a")])
    with pytest.raises(AssertionError, match="cannot count"):
        level_scaling_effects([change, level])


def test_only_level_changes_after_this_one_shift_the_bands():
    # a later non-level change that happens to adjust the level is not counted,
    # and a level adjustment inside this change has already run
    other = _change(
        category="hit_points",
        effects=[{"operation": "adjustment", "target": "$.creature_type.level", "value": 9}],
    )
    change = _level_change(1)
    change["abilities"] = [_scaled("X", "1d6", POWER)]
    change["effects"].append(_add_items("X", "$.a"))
    level_scaling_effects([change, other])
    assert _replaces(change)[0][2] == "$.creature_type.level >= 9 && $.creature_type.level <= 14"


def test_a_scaled_ability_with_no_placement_fails():
    with pytest.raises(AssertionError, match="no add_items placement"):
        level_scaling_effects([_change(_scaled("X", "1d6", POWER))])


def test_unscaled_damage_adds_no_effects():
    change = _change(
        {"name": "X", "damage": [_damage("1d6")]},
        effects=[_add_items("X", "$.interaction_abilities")],
    )
    level_scaling_effects([change])
    assert _replaces(change) == []


def test_a_floor_from_the_lowest_level_has_no_lower_bound():
    scaling = {
        "increment": "1d6",
        "per_levels": 1,
        "start_level": 1,
        "additive": False,
        "minimum": "2d6",
    }
    change = _change(
        _scaled("Shockwave", "1d6", scaling),
        effects=[_add_items("Shockwave", "$.interaction_abilities")],
    )
    level_scaling_effects([change])
    assert _replaces(change)[0][1:] == ("2d6", "$.creature_type.level <= 2")


def test_the_pass_reaches_subtypes():
    sub = _change(_scaled("X", "1d6", POWER), effects=[_add_items("X", "$.interaction_abilities")])
    level_scaling_effects_pass({"changes": [], "subtypes": [{"changes": [sub]}]})
    assert len(_replaces(sub)) == 2


@pytest.mark.parametrize(
    "module", [monster_template.parse_monster_template, monster_family.parse_monster_family]
)
def test_parsers_run_the_pass_after_ability_enrichment(module):
    # a full parse needs the enrichment DBs, which CI lacks; pin the wiring:
    # both are unconditional top-level calls, enrichment first
    (fn,) = ast.parse(textwrap.dedent(inspect.getsource(module))).body
    lines = {
        stmt.value.func.id: stmt.lineno
        for stmt in fn.body
        if isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Call)
        and isinstance(stmt.value.func, ast.Name)
    }
    assert lines["template_ability_enrichment_pass"] < lines["level_scaling_effects_pass"]


@pytest.mark.parametrize(
    "name, field, expected",
    [
        ("Power Surge", "name", "[?(@.name=='Power Surge')]"),
        ("Pyre's Memory", "name", "[?(@.name=='Pyre\\'s Memory')]"),
        ("a\\b", "name", "[?(@.name=='a\\\\b')]"),
        ("1d6", "formula", "[?(@.formula=='1d6')]"),
    ],
)
def test_name_filter_quotes(name, field, expected):
    assert name_filter(name, field) == expected


def test_two_scaled_entries_share_one_bundle():
    ability = {
        "name": "X",
        "damage": [
            _damage("1d6", level_scaling=POWER),
            _damage("1d8", level_scaling={"steps": [{"min_level": 5, "formula": "2d8"}]}),
        ],
    }
    options = [_add_items("X", "$.interaction_abilities")]
    select = {"operation": "select", "target": "t", "selection": {"options": options}}
    level_scaling_effects([_change(ability, effects=[select])])
    (bundle,) = options
    add, *replaces = bundle["effects"]
    assert add["operation"] == "add_items" and len(replaces) == 3
