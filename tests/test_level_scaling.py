"""Level-scaled damage, one case per phrasing found in templates and families."""

import pytest

from pfsrd2.enrichment.level_scaling import extract_level_scaling, formula_at_level

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
    ],
)
def test_no_scaling_is_none(text):
    assert extract_level_scaling(text, "1d6") is None


def test_merge_marks_scaling_on_enriched_damage():
    import json

    from pfsrd2.ability_enrichment import _merge_enrichment

    ability = {"name": "Power Surge", "text": POWER_SURGE}
    _merge_enrichment(
        ability,
        json.dumps(
            {
                "damage": [
                    {"type": "stat_block_section", "subtype": "attack_damage", "formula": "1d6"}
                ]
            }
        ),
    )
    (dmg,) = ability["damage"]
    assert [s["min_level"] for s in dmg["level_scaling"]["steps"]] == [9, 15, 18]
