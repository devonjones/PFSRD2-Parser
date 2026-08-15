"""Tests for rune slot decoration (pfsrd2/rune.py)."""

import pytest

from pfsrd2.rune import parse_usage, rune_pass


def _stat_block(name, subcategory, usage=None, variants=None):
    stat_block = {
        "type": "stat_block",
        "subtype": "equipment",
        "item_category": "Runes",
        "item_subcategory": subcategory,
    }
    if usage:
        stat_block["statistics"] = {
            "type": "stat_block_section",
            "subtype": "statistics",
            "usage": {
                "type": "stat_block_section",
                "subtype": "usage",
                "text": usage,
            },
        }
    if variants:
        stat_block["variants"] = [{"name": v} for v in variants]
    return {"name": name, "stat_block": stat_block}


def _rune(struct):
    return struct["stat_block"]["rune"]


class TestParseUsage:
    def test_bare_weapon_has_no_clauses(self):
        requires, conflicts, parsed = parse_usage("etched onto a weapon")
        assert requires == []
        assert conflicts == []
        assert parsed

    def test_armor_category_single(self):
        requires, _, parsed = parse_usage("etched onto light armor")
        assert parsed
        assert requires == [
            {
                "path": "$.stat_block.statistics.category",
                "op": "in",
                "values": ["Light"],
            }
        ]

    def test_armor_category_pair(self):
        requires, _, parsed = parse_usage("etched onto medium or heavy armor")
        assert parsed
        assert requires[0]["values"] == ["Medium", "Heavy"]

    def test_melee_damage_type_combination(self):
        requires, _, parsed = parse_usage("etched onto a piercing or slashing melee weapon")
        assert parsed
        paths = {clause["path"]: clause["values"] for clause in requires}
        assert paths["$.stat_block.offense.weapon_modes[*].damage[*].damage_type"] == [
            "piercing",
            "slashing",
        ]
        assert paths["$.stat_block.offense.weapon_modes[*].weapon_type"] == ["Melee"]

    def test_thrown_and_monk_are_traits(self):
        requires, _, parsed = parse_usage("etched onto a thrown weapon")
        assert parsed
        assert requires == [
            {"path": "$.stat_block.traits[*].name", "op": "in", "values": ["Thrown"]}
        ]
        requires, _, parsed = parse_usage("etched onto a melee weapon with the monk trait")
        assert parsed
        assert {"path": "$.stat_block.traits[*].name", "op": "in", "values": ["Monk"]} in requires

    def test_clan_dagger_matches_by_name(self):
        requires, _, parsed = parse_usage("etched onto a clan dagger")
        assert parsed
        assert requires == [{"path": "$.name", "op": "in", "values": ["Clan Dagger"]}]

    def test_rune_exclusion_becomes_conflict(self):
        requires, conflicts, parsed = parse_usage(
            "etched onto a weapon without a *disrupting* rune"
        )
        assert parsed
        assert requires == []
        assert conflicts == ["disrupting"]

    def test_trait_exclusion_becomes_conflict(self):
        _, conflicts, parsed = parse_usage("etched into a weapon that isn't holy")
        assert parsed
        assert conflicts == ["holy"]

    def test_etched_on_lead_in_variant(self):
        requires, _, parsed = parse_usage("etched on a slashing or piercing weapon")
        assert parsed
        assert requires[0]["values"] == ["piercing", "slashing"]

    def test_material_usage_is_not_partially_parsed(self):
        # Armor has no material field; a Medium/Heavy-only clause would claim
        # every medium armor is legal for a rune that needs a metal one.
        requires, _, parsed = parse_usage("etched onto a metal medium or heavy armor")
        assert requires == []
        assert not parsed

    def test_missing_usage_is_not_parsed(self):
        assert parse_usage(None) == ([], [], False)


class TestRunePass:
    def test_fundamental_weapon_slots(self):
        struct = _stat_block(
            "Striking",
            "Fundamental Weapon Runes",
            usage="etched onto a weapon",
            variants=["Striking", "Striking (Greater)", "Striking (Major)"],
        )
        rune_pass(struct)
        assert _rune(struct) == {
            "type": "stat_block_section",
            "subtype": "rune",
            "form": "fundamental",
            "slot": "striking",
            "host": "weapon",
            "usage_text": "etched onto a weapon",
        }
        dice = [v["effects"][0] for v in struct["stat_block"]["variants"]]
        assert [d["value"] for d in dice] == [2, 3, 4]
        assert all(d["operation"] == "replace" for d in dice)
        assert all(
            d["target"] == "$.stat_block.offense.weapon_modes[*].damage[*].dice_count"
            for d in dice
        )

    def test_potency_grants_property_slots(self):
        struct = _stat_block(
            "Weapon Potency",
            "Fundamental Weapon Runes",
            usage="etched onto a weapon",
            variants=["Weapon Potency (+1)", "Weapon Potency (+2)", "Weapon Potency (+3)"],
        )
        rune_pass(struct)
        variants = struct["stat_block"]["variants"]
        # Capacity is metadata on the rune block, not an effect: it mutates
        # nothing on the host.
        assert [v["rune"]["grants_property_slots"] for v in variants] == [1, 2, 3]
        attack = [e for v in variants for e in v["effects"]]
        assert [a["modifier"]["bonus_value"] for a in attack] == [1, 2, 3]
        assert all(a["modifier"]["bonus_type"] == "item" for a in attack)
        assert all(a["operation"] == "add_modifier" for a in attack)
        assert all(
            a["target"] == "$.stat_block.offense.weapon_modes[*].modifiers" for a in attack
        )

    def test_armor_potency_grants_an_item_bonus_to_ac(self):
        struct = _stat_block(
            "Armor Potency",
            "Fundamental Armor Runes",
            usage="etched onto armor",
            variants=["Armor Potency (+1)", "Armor Potency (+2)", "Armor Potency (+3)"],
        )
        rune_pass(struct)
        ac = [effect for v in struct["stat_block"]["variants"] for effect in v["effects"]]
        assert [a["modifier"]["bonus_value"] for a in ac] == [1, 2, 3]
        assert all(a["target"] == "$.stat_block.defense.modifiers" for a in ac)
        assert all(
            a["modifier"]
            == {
                "type": "bonus",
                "subtype": "ac",
                "bonus_type": "item",
                "bonus_value": a["modifier"]["bonus_value"],
            }
            for a in ac
        )

    def test_resilient_grants_an_item_bonus_to_saves(self):
        struct = _stat_block(
            "Resilient",
            "Fundamental Armor Runes",
            usage="etched onto armor",
            variants=["Resilient", "Resilient (Greater)", "Resilient (Major)"],
        )
        rune_pass(struct)
        saves = [v["effects"][0] for v in struct["stat_block"]["variants"]]
        assert [s["modifier"]["bonus_value"] for s in saves] == [1, 2, 3]
        assert all(s["modifier"]["subtype"] == "save" for s in saves)

    def test_reinforcing_carries_caps_on_each_subject(self):
        struct = _stat_block(
            "Reinforcing Rune",
            "Shield Runes",
            usage="etched onto a shield",
            variants=["Reinforcing Rune (Minor)", "Reinforcing Rune (Supreme)"],
        )
        rune_pass(struct)
        minor, supreme = struct["stat_block"]["variants"]
        assert [(e["target"], e["value"], e["maximum"]) for e in minor["effects"]] == [
            ("$.stat_block.defense.hitpoints.hardness", 3, 8),
            ("$.stat_block.defense.hitpoints.hp", 44, 64),
            ("$.stat_block.defense.hitpoints.break_threshold", 22, 32),
        ]
        assert all(e["operation"] == "adjustment" for e in minor["effects"])
        assert supreme["effects"][0]["maximum"] == 20

    def test_missing_grade_effects_fail_loudly(self):
        struct = _stat_block(
            "Striking",
            "Fundamental Weapon Runes",
            usage="etched onto a weapon",
            variants=["Striking", "Striking (Supreme)"],
        )
        with pytest.raises(AssertionError, match="no effects"):
            rune_pass(struct)

    def test_effects_are_not_shared_between_items(self):
        first = _stat_block(
            "Mythic Striking", "Fundamental Weapon Runes", usage="etched onto a weapon"
        )
        second = _stat_block(
            "Mythic Striking", "Fundamental Weapon Runes", usage="etched onto a weapon"
        )
        rune_pass(first)
        rune_pass(second)
        first["stat_block"]["effects"][0]["value"] = 99
        assert second["stat_block"]["effects"][0]["value"] == 5

    def test_mythic_rune_effects_hang_off_the_stat_block(self):
        struct = _stat_block(
            "Mythic Striking", "Fundamental Weapon Runes", usage="etched onto a weapon"
        )
        rune_pass(struct)
        assert struct["stat_block"]["effects"][0]["value"] == 5

    def test_mythic_resilient_typo_still_resolves_its_slot(self):
        # AoN publishes it as "Mythic Resilent".
        struct = _stat_block(
            "Mythic Resilent", "Fundamental Armor Runes", usage="etched onto armor"
        )
        rune_pass(struct)
        assert _rune(struct)["slot"] == "resilient"

    def test_property_rune_shares_the_property_slot(self):
        struct = _stat_block("Giant-Killing", "Weapon Property Runes", usage="etched onto a weapon")
        rune_pass(struct)
        assert _rune(struct)["form"] == "property"
        assert _rune(struct)["slot"] == "property"

    def test_accessory_runes_stay_prose_without_review_flag(self):
        struct = _stat_block(
            "Presentable", "Accessory Runes", usage="applied to any visible article of clothing"
        )
        rune_pass(struct)
        rune = _rune(struct)
        assert rune["host"] == "accessory"
        assert "requires" not in rune
        assert "needs_review" not in rune

    def test_filigree_without_usage_falls_back_to_subcategory(self):
        struct = _stat_block("Trudd's Strength", "Clan Dagger Filigrees")
        rune_pass(struct)
        assert _rune(struct)["requires"] == [
            {"path": "$.name", "op": "in", "values": ["Clan Dagger"]}
        ]

    def test_unparsed_usage_flags_review_and_drops_clauses(self):
        struct = _stat_block(
            "Shadow", "Armor Property Runes", usage="etched onto light or medium nonmetallic armor"
        )
        rune_pass(struct)
        assert _rune(struct)["needs_review"] is True
        assert "requires" not in _rune(struct)

    def test_unknown_fundamental_rune_fails_loudly(self):
        struct = _stat_block(
            "Weapon Potency", "Fundamental Weapon Runes", usage="etched onto a weapon"
        )
        struct["name"] = "Astonishing Potency"
        # Fails in _slot_for, before the effects-coverage assert.
        with pytest.raises(AssertionError, match="no slot for"):
            rune_pass(struct)

    def test_variantless_fundamental_without_effects_fails_loudly(self):
        # Reaches the variantless branch of the coverage assert: the name
        # resolves to a slot, but no effects are authored for it.
        struct = _stat_block("Striking", "Fundamental Weapon Runes", usage="etched onto a weapon")
        struct["name"] = "Mythic Striking Prime"
        with pytest.raises(AssertionError, match="no effects"):
            rune_pass(struct)

    def test_missing_usage_on_a_normal_rune_fails_loudly(self):
        # Only clan dagger filigrees legitimately lack a Usage line (accessory
        # runes have one, they just skip parsing it). Anything else silently
        # becoming needs_review would hide an upstream extraction regression
        # across the whole corpus.
        struct = _stat_block("Keen", "Weapon Property Runes")
        with pytest.raises(AssertionError, match="no usage text"):
            rune_pass(struct)

    def test_blank_usage_is_treated_as_missing(self):
        # Whitespace is truthy, so it would skip the missing-usage raise and
        # then parse to "fully parsed, no requirements" — a rune claiming it
        # fits every host item.
        struct = _stat_block("Keen", "Weapon Property Runes", usage="   ")
        with pytest.raises(AssertionError, match="no usage text"):
            rune_pass(struct)

    def test_conflicts_survive_an_unparsable_usage(self):
        # conflicts_with is decided independently of the residue, so it is
        # kept while requires is dropped. Pins the documented asymmetry.
        struct = _stat_block(
            "Warding",
            "Armor Property Runes",
            usage="etched onto metal armor without a *disrupting* rune",
        )
        rune_pass(struct)
        rune = _rune(struct)
        assert rune["needs_review"] is True
        assert "requires" not in rune
        assert rune["conflicts_with"] == ["disrupting"]

    def test_conflict_capture_ignores_articles(self):
        # "that isn't a shield" would otherwise capture the article as a
        # conflicting rune name.
        _, conflicts, _ = parse_usage("etched onto a weapon that isn't a shield")
        assert conflicts == []

    def test_residue_path_drops_partial_clauses_and_flags_review(self):
        # Usage naming something with no structured counterpart: the armor
        # category clause parses, the rest doesn't. Shipping just the category
        # would call every light armor legal for a rune that needs more.
        requires, _, parsed = parse_usage("etched onto light armor blessed by a dragon")
        assert requires and not parsed
        struct = _stat_block(
            "Dragonblessed",
            "Armor Property Runes",
            usage="etched onto light armor blessed by a dragon",
        )
        rune_pass(struct)
        assert _rune(struct)["needs_review"] is True
        assert "requires" not in _rune(struct)

    def test_variant_rune_blocks_do_not_share_mutable_state(self):
        struct = _stat_block(
            "Giant-Killing",
            "Weapon Property Runes",
            usage="etched onto a slashing melee weapon",
            variants=["Giant-Killing", "Giant-Killing (Greater)"],
        )
        rune_pass(struct)
        base = struct["stat_block"]["rune"]
        first, second = (v["rune"] for v in struct["stat_block"]["variants"])
        assert first["requires"] is not base["requires"]
        assert first["requires"] is not second["requires"]
        first["requires"][0]["values"].append("mutated")
        assert "mutated" not in base["requires"][0]["values"]
        assert "mutated" not in second["requires"][0]["values"]

    def test_subcategory_requires_constant_is_not_aliased(self):
        first = _stat_block("Trudd's Strength", "Clan Dagger Filigrees")
        second = _stat_block("Bolka's Blessing", "Clan Dagger Filigrees")
        rune_pass(first)
        first["stat_block"]["rune"]["requires"][0]["values"].append("mutated")
        rune_pass(second)
        assert second["stat_block"]["rune"]["requires"][0]["values"] == ["Clan Dagger"]

    def test_unknown_subcategory_fails_loudly(self):
        struct = _stat_block("Whatever", "Sandwich Runes", usage="etched onto a weapon")
        with pytest.raises(AssertionError):
            rune_pass(struct)

    def test_non_rune_equipment_is_untouched(self):
        struct = {"name": "Longsword", "stat_block": {"item_category": "Weapons"}}
        rune_pass(struct)
        assert "rune" not in struct["stat_block"]
