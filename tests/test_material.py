"""Tests for material slot decoration (pfsrd2/material.py)."""

import pytest

from pfsrd2.material import (
    combine_rarity,
    granted_traits,
    material_pass,
    parse_stat_table,
)


def _material(name, traits, variants=None, table=None, edition="remastered"):
    stat_block = {
        "type": "stat_block",
        "subtype": "equipment",
        "item_category": "Materials",
        "traits": [{"name": t} for t in traits],
    }
    if variants:
        stat_block["variants"] = [{"name": v} for v in variants]
    if table:
        stat_block["sections"] = [{"type": "section", "name": f"{name} Items", "text": table}]
    return {"name": name, "edition": edition, "stat_block": stat_block}


def _use(name, kind, variants):
    return {
        "name": name,
        "stat_block": {
            "type": "stat_block",
            "subtype": "equipment",
            "item_category": kind,
            "item_subcategory": f"Precious Material {kind}",
            "variants": variants,
        },
    }


# The five table layouts AoN publishes.

ADAMANTINE_TABLE = """|  |  |  |  |
| --- | --- | --- | --- |
| **Adamantine Items** | **Hardness** | **HP** | **BT** |
| **Thin Items** |  |
| Standard-grade | 10 | 40 | 20 |
| High-grade | 13 | 52 | 26 |
| **Items** |  |
| Standard-grade | 14 | 56 | 28 |
| High-grade | 17 | 68 | 34 |
| **Structure** |  |
| Standard-grade | 28 | 112 | 56 |
| High-grade | 34 | 136 | 68 |"""

GRISANTIAN_TABLE = """|  |  |  |  |
| --- | --- | --- | --- |
| **Thin Items** | **Hardness** | **HP** | **BT** |
| Standard-grade | 6 | 24 | 12 |
| High-grade | 8 | 32 | 16 |
| **Items** | **Hardness** | **HP** | **BT** |
| Standard-grade | 9 | 36 | 18 |
| High-grade | 11 | 44 | 22 |"""

STONE_TABLE = """|  |  |  |  |
| --- | --- | --- | --- |
|  | **Hardness** | **HP** | **BT** |
| Thin Items  | 4  | 16  | 8 |
| Items  | 7  | 24  | 12 |
| Structures  | 14  | 48  | 24 |"""

KEEP_STONE_TABLE = """|  |  |  |  |
| --- | --- | --- | --- |
| Keep Stone Items | Hardness | HP | BT |
| Thin Items |  |
| High-Grade | 10 | 46 | 24 |
| Items |  |
| High-Grade | 14 | 60 | 30 |
| Structures |  |
| High-Grade | 30 |  122 | 61 |"""

DRAGON_TYPE_TABLE = """|  |  |
| --- | --- |
| **Dragon Type** | **Resistance** |
| Black or copper | Acid |
| Blue or bronze | Electricity |"""


class TestParseStatTable:
    def test_bold_form_headers_with_grade_rows(self):
        rows = parse_stat_table(ADAMANTINE_TABLE)
        assert len(rows) == 6
        assert rows[0] == {
            "type": "stat_block_section",
            "subtype": "material_statistics",
            "form": "thin",
            "grade": "standard",
            "hardness": 10,
            "hit_points": 40,
            "break_threshold": 20,
        }
        assert [(r["form"], r["grade"]) for r in rows] == [
            ("thin", "standard"), ("thin", "high"),
            ("item", "standard"), ("item", "high"),
            ("structure", "standard"), ("structure", "high"),
        ]

    def test_form_header_carrying_column_labels(self):
        rows = parse_stat_table(GRISANTIAN_TABLE)
        assert [(r["form"], r["grade"], r["hardness"]) for r in rows] == [
            ("thin", "standard", 6), ("thin", "high", 8),
            ("item", "standard", 9), ("item", "high", 11),
        ]

    def test_common_material_rows_have_no_grade(self):
        rows = parse_stat_table(STONE_TABLE)
        assert [(r["form"], r["hardness"]) for r in rows] == [
            ("thin", 4), ("item", 7), ("structure", 14)
        ]
        assert all("grade" not in r for r in rows)

    def test_plain_headers_and_stray_whitespace(self):
        rows = parse_stat_table(KEEP_STONE_TABLE)
        assert [(r["form"], r["grade"], r["hardness"], r["hit_points"]) for r in rows] == [
            ("thin", "high", 10, 46),
            ("item", "high", 14, 60),
            ("structure", "high", 30, 122),
        ]

    def test_structures_and_structure_normalize_together(self):
        assert parse_stat_table(STONE_TABLE)[2]["form"] == "structure"
        assert parse_stat_table(ADAMANTINE_TABLE)[4]["form"] == "structure"

    def test_standard_items_is_the_same_form_as_items(self):
        table = ADAMANTINE_TABLE.replace("**Items**", "**Standard Items**")
        assert [r["form"] for r in parse_stat_table(table)][2:4] == ["item", "item"]

    def test_a_non_stat_table_yields_nothing(self):
        # Legacy Dragonhide's table is Dragon Type -> Resistance.
        assert parse_stat_table(DRAGON_TYPE_TABLE) == []


class TestTraitPropagation:
    def test_precious_does_not_travel_to_the_item(self):
        assert granted_traits(["Uncommon", "Precious"]) == ["Uncommon"]

    def test_common_material_grants_nothing(self):
        assert granted_traits(["Precious"]) == []

    def test_rarity_takes_the_more_restrictive(self):
        assert combine_rarity("uncommon", "rare") == "rare"
        assert combine_rarity("rare", "uncommon") == "rare"
        assert combine_rarity(None, "uncommon") == "uncommon"
        assert combine_rarity("rare", None) == "rare"
        assert combine_rarity(None, None) == "common"
        assert combine_rarity("unique", "rare") == "unique"

    def test_unknown_rarity_fails_loudly(self):
        with pytest.raises(AssertionError):
            combine_rarity("legendary", "rare")


class TestMaterialPass:
    def test_precious_material_gets_grades_with_caps(self):
        struct = _material(
            "Adamantine",
            ["Uncommon", "Precious"],
            variants=["Adamantine Chunk", "Adamantine Object (Standard-Grade)",
                      "Adamantine Object (High-Grade)"],
            table=ADAMANTINE_TABLE,
        )
        material_pass(struct)
        block = struct["stat_block"]["material"]
        assert block["precious"] is True
        assert block["grants_traits"] == ["Uncommon"]
        assert [g["grade"] for g in block["grades"]] == ["standard", "high"]
        standard, high = block["grades"]
        assert standard["max_rune_level"] == 15 and standard["max_item_level"] == 15
        # High grade is unbounded — expressed by omission, not a null.
        assert "max_rune_level" not in high
        assert len(block["statistics"]) == 6

    def test_grades_are_ordered_low_standard_high(self):
        struct = _material(
            "Silver", ["Precious"],
            variants=["Silver Object (High-Grade)", "Silver Object (Low-Grade)",
                      "Silver Object (Standard-Grade)"],
        )
        material_pass(struct)
        grades = struct["stat_block"]["material"]["grades"]
        assert [g["grade"] for g in grades] == ["low", "standard", "high"]
        assert grades[0]["max_rune_level"] == 8

    def test_common_material_is_never_graded_despite_its_variant_name(self):
        # Stone's only variant is published as "Stone Object (Low-Grade)".
        # Reading a grade off that name would wrongly cap its rune levels.
        struct = _material("Stone", [], variants=["Stone Object (Low-Grade)"], table=STONE_TABLE)
        material_pass(struct)
        block = struct["stat_block"]["material"]
        assert block["precious"] is False
        assert "grades" not in block
        assert len(block["statistics"]) == 3

    def test_precious_material_without_grade_variants_fails_loudly(self):
        struct = _material("Bogusite", ["Rare", "Precious"], variants=["Bogusite Chunk"])
        with pytest.raises(AssertionError, match="no"):
            material_pass(struct)

    def test_material_with_no_stat_table_still_decorates(self):
        struct = _material(
            "Dragonhide", ["Uncommon", "Precious"],
            variants=["Dragonhide Object (Standard-Grade)", "Dragonhide Object (High-Grade)"],
            table=DRAGON_TYPE_TABLE,
        )
        material_pass(struct)
        assert "statistics" not in struct["stat_block"]["material"]
        assert struct["stat_block"]["material"]["grants_traits"] == ["Uncommon"]


class TestUsePass:
    def test_shield_variants_split_into_form_and_grade(self):
        struct = _use("Adamantine Shield", "Shields", [
            {"name": "Adamantine Buckler (Standard-Grade)",
             "text": "The shield has Hardness 8, HP 32, and BT 16."},
            {"name": "Adamantine Shield (Standard-Grade)",
             "text": "The shield has Hardness 10, HP 40, and BT 20."},
            {"name": "Adamantine Buckler (High-Grade)",
             "text": "The shield has Hardness 11, HP 44, and BT 22."},
        ])
        material_pass(struct)
        uses = [v["material_use"] for v in struct["stat_block"]["variants"]]
        assert [(u["form"], u["grade"], u["hardness"]) for u in uses] == [
            ("buckler", "standard", 8),
            ("shield", "standard", 10),
            ("buckler", "high", 11),
        ]
        assert uses[0]["host"] == "shield"

    def test_tower_shield_is_its_own_form(self):
        struct = _use("Darkwood Shield", "Shields", [
            {"name": "Darkwood Tower Shield (Standard-Grade)",
             "text": "The shield has Hardness 5, HP 20, and BT 10."},
        ])
        material_pass(struct)
        assert struct["stat_block"]["variants"][0]["material_use"]["form"] == "tower shield"

    def test_armor_and_weapon_variants_fall_back_to_the_host_form(self):
        armor = _use("Adamantine Armor", "Armor", [
            {"name": "Adamantine Armor (Standard-Grade)",
             "text": "The initial raw materials must include adamantine worth at least 200 gp."},
        ])
        material_pass(armor)
        use = armor["stat_block"]["variants"][0]["material_use"]
        assert use["form"] == "armor"
        assert use["grade"] == "standard"
        # Armor states no stats — it inherits the material page's grid.
        assert "hardness" not in use

    def test_specific_armor_falls_back_to_the_host_form(self):
        # Elven Chain is a specific armor that happens to be dawnsilver, so
        # its name carries no material to strip and nothing distinguishes the
        # form. "armor" is the honest answer; guessing "elven chain" from the
        # leftover would be a naming coincidence, not a form.
        struct = _use("Elven Chain", "Armor", [
            {"name": "Elven Chain (Standard-Grade)"},
        ])
        material_pass(struct)
        assert struct["stat_block"]["variants"][0]["material_use"]["form"] == "armor"

    def test_variant_without_a_grade_suffix_fails_loudly(self):
        struct = _use("Duskwood Armor", "Armor", [{"name": "Duskwood Armor (Standard-Grade"}])
        with pytest.raises(AssertionError, match="grade suffix"):
            material_pass(struct)

    def test_non_material_equipment_is_untouched(self):
        struct = {"name": "Longsword", "stat_block": {"item_category": "Weapons"}}
        material_pass(struct)
        assert "material" not in struct["stat_block"]
        assert "material_use" not in struct["stat_block"]
