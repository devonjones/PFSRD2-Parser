import json

from pfsrd2.enrichment.change_extractor import (
    _build_combat_stat_effects,
    _build_hit_points_effects,
    _build_speed_effects,
    _build_trait_effects,
    _categorize_change_text,
    _damage_adjustment_item,
    _level_text_to_conditional,
    _normalize_movement_type,
    enrich_change,
)


class TestCategorizeChangeText:
    def test_traits(self):
        assert _categorize_change_text("Add the undead trait.") == "traits"

    def test_combat_stats(self):
        assert (
            _categorize_change_text(
                "Increase AC, attack modifiers, DCs, saving throws, and skill modifiers by 2, and HP by 10."
            )
            == "combat_stats"
        )

    def test_damage(self):
        assert _categorize_change_text("Increase the damage of Strikes by 2.") == "damage"

    def test_senses(self):
        assert _categorize_change_text("Add darkvision.") == "senses"

    def test_immunities(self):
        assert _categorize_change_text("Add immunity to fire.") == "immunities"

    def test_speed(self):
        assert _categorize_change_text("Change Speed to 20 feet.") == "speed"

    def test_level(self):
        assert _categorize_change_text("Increase the creature\u2019s level by 1.") == "level"

    def test_hit_points(self):
        assert _categorize_change_text("hit points based on level") == "hit_points"

    def test_unknown(self):
        assert _categorize_change_text("random nonsense text") == "unknown"

    def test_empty_string(self):
        assert _categorize_change_text("") == "unknown"

    def test_whitespace_only(self):
        assert _categorize_change_text("   ") == "unknown"


class TestNormalizeMovementType:
    def test_land_to_walk(self):
        assert _normalize_movement_type("land") == "walk"

    def test_swim_unchanged(self):
        assert _normalize_movement_type("swim") == "swim"

    def test_fly_unchanged(self):
        assert _normalize_movement_type("fly") == "fly"

    def test_burrow_unchanged(self):
        assert _normalize_movement_type("burrow") == "burrow"


class TestDamageAdjustmentItem:
    def test_positive_value(self):
        item = _damage_adjustment_item(2)
        assert item["formula"] == "+2"
        assert item["type"] == "stat_block_section"
        assert item["subtype"] == "attack_damage"

    def test_negative_value(self):
        item = _damage_adjustment_item(-2)
        assert item["formula"] == "-2"

    def test_with_damage_type(self):
        item = _damage_adjustment_item(2, damage_type="fire")
        assert item["damage_type"] == "fire"

    def test_with_notes(self):
        item = _damage_adjustment_item(2, notes="Vampire")
        assert item["notes"] == "Vampire"

    def test_without_optional_fields(self):
        item = _damage_adjustment_item(3)
        assert "damage_type" not in item
        assert "notes" not in item

    def test_zero_value(self):
        item = _damage_adjustment_item(0)
        assert item["formula"] == "0"


class TestEnrichChange:
    def test_trait_change(self):
        raw = json.dumps({"text": "Add the undead trait."})
        enriched_str, method = enrich_change(raw, "Vampire")
        assert enriched_str is not None
        assert method == "regex"
        enriched = json.loads(enriched_str)
        assert enriched["change_category"] == "traits"
        assert "effects" in enriched

    def test_unknown_text_returns_none(self):
        raw = json.dumps({"text": "random nonsense text"})
        enriched_str, method = enrich_change(raw, "Test")
        assert enriched_str is None
        assert method is None

    def test_empty_text_returns_none(self):
        raw = json.dumps({"text": ""})
        enriched_str, method = enrich_change(raw, "Test")
        assert enriched_str is None
        assert method is None

    def test_combat_stats_includes_dc_targets(self):
        raw = json.dumps(
            {"text": "Increase AC, attack modifiers, DCs, saving throws by 2, and HP by 10."}
        )
        enriched_str, _ = enrich_change(raw, "Template")
        enriched = json.loads(enriched_str)
        assert enriched["change_category"] == "combat_stats"
        targets = [e["target"] for e in enriched["effects"]]
        # Should have DC targets for spells, automatic abilities, reactive abilities, offensive abilities
        dc_targets = [t for t in targets if "dc" in t.lower()]
        assert len(dc_targets) == 4

    def test_damage_produces_attack_damage_items(self):
        raw = json.dumps({"text": "Increase the damage of Strikes by 2."})
        enriched_str, _ = enrich_change(raw, "Vampire")
        enriched = json.loads(enriched_str)
        assert enriched["change_category"] == "damage"
        # Should have effects with attack_damage items
        for eff in enriched["effects"]:
            if "item" in eff:
                assert eff["item"]["subtype"] == "attack_damage"
                assert eff["item"]["notes"] == "Vampire"

    def test_speed_uses_walk_not_land(self):
        # "swim" triggers speed category; test that "land" normalizes to "walk"
        raw = json.dumps({"text": "Add a swim Speed of 30 feet."})
        enriched_str, _ = enrich_change(raw, "Test")
        enriched = json.loads(enriched_str)
        assert enriched["change_category"] == "speed"
        for eff in enriched["effects"]:
            if "item" in eff:
                assert eff["item"]["movement_type"] == "swim"

    def test_speed_land_normalizes_to_walk(self):
        # Test _build_speed_effects directly since "land" alone doesn't trigger speed category
        effects = _build_speed_effects("Add a land Speed of 30 feet.")
        assert len(effects) == 1
        assert effects[0]["item"]["movement_type"] == "walk"

    def test_hit_points_with_adjustments(self):
        adjustments = [
            {"type": "stat_block_section", "subtype": "adjustment", "level": "2-4", "hp": "10"},
            {"type": "stat_block_section", "subtype": "adjustment", "level": "5+", "hp": "20"},
        ]
        raw = json.dumps(
            {"text": "Increase hit points based on level.", "_adjustments": adjustments}
        )
        enriched_str, _ = enrich_change(raw, "Template")
        enriched = json.loads(enriched_str)
        assert enriched["change_category"] == "hit_points"
        assert len(enriched["effects"]) == 2
        # Should have level conditionals
        for eff in enriched["effects"]:
            assert "conditional" in eff
            assert "creature_type.level" in eff["conditional"]


class TestBuildSpeedEffects:
    def test_add_swim_speed(self):
        effects = _build_speed_effects("Add a swim Speed of 25 feet.")
        assert len(effects) == 1
        assert effects[0]["item"]["movement_type"] == "swim"
        assert effects[0]["item"]["value"] == 25

    def test_change_speed_to_value(self):
        effects = _build_speed_effects("Change Speed to 20 feet if higher.")
        assert len(effects) == 1
        assert effects[0]["operation"] == "replace"
        assert effects[0]["value"] == 20
        assert "walk" in effects[0]["target"]

    def test_half_land_speed_normalizes_to_walk(self):
        effects = _build_speed_effects(
            "Add a fly Speed equal to half its land Speed, minimum 20 feet."
        )
        assert len(effects) == 1
        assert effects[0]["item"]["movement_type"] == "fly"
        assert "walk" in effects[0]["value_from"]


class TestBuildTraitEffects:
    def test_add_multiple_traits(self):
        effects = _build_trait_effects("Add the ghost, spirit, and undead traits.")
        add_effects = [e for e in effects if e["operation"] == "add_item"]
        assert len(add_effects) == 3
        names = {e["name"] for e in add_effects}
        assert "Ghost" in names
        assert "Spirit" in names
        assert "Undead" in names

    def test_gains_traits(self):
        effects = _build_trait_effects("The creature gains the undead and vampire traits.")
        add_effects = [e for e in effects if e["operation"] == "add_item"]
        assert len(add_effects) == 2
        names = {e["name"] for e in add_effects}
        assert "Undead" in names
        assert "Vampire" in names

    def test_replace_trait(self):
        effects = _build_trait_effects("Replace the human trait with the dwarf trait.")
        remove_effects = [e for e in effects if e["operation"] == "remove_item"]
        add_effects = [e for e in effects if e["operation"] == "add_item"]
        assert len(remove_effects) == 1
        assert remove_effects[0]["name"] == "Human"
        assert len(add_effects) == 1
        assert add_effects[0]["name"] == "Dwarf"

    def test_link_based_extraction_avoids_fragments(self):
        """pfsrd2-bfy: use Traits links instead of regex to avoid sentence fragments."""
        text = "Add the skeleton and undead traits and, optionally, the mindless trait."
        links = [
            {"type": "link", "name": "skeleton", "game-obj": "Traits", "aonid": 236},
            {"type": "link", "name": "undead", "game-obj": "Traits", "aonid": 160},
            {"type": "link", "name": "mindless", "game-obj": "Traits", "aonid": 108},
        ]
        effects = _build_trait_effects(text, links)
        names = {e["name"] for e in effects if e["operation"] == "add_item"}
        assert names == {"Skeleton", "Undead", "Mindless"}
        # Should NOT contain fragments like "Undead Traits And" or "Optionally"
        for e in effects:
            assert "Traits And" not in e.get("name", "")
            assert "Optionally" not in e.get("name", "")

    def test_link_based_extraction_water_template(self):
        """Water template: 'either the amphibious or aquatic' should extract both."""
        text = "Add the water trait and either the amphibious or aquatic trait."
        links = [
            {"type": "link", "name": "water", "game-obj": "Traits", "aonid": 165},
            {"type": "link", "name": "amphibious", "game-obj": "Traits", "aonid": 13},
            {"type": "link", "name": "aquatic", "game-obj": "Traits", "aonid": 14},
        ]
        effects = _build_trait_effects(text, links)
        names = {e["name"] for e in effects if e["operation"] == "add_item"}
        assert names == {"Water", "Amphibious", "Aquatic"}

    def test_non_trait_links_ignored(self):
        """Links with game-obj != Traits should not be extracted as traits."""
        text = "Add the undead trait."
        links = [
            {"type": "link", "name": "undead", "game-obj": "Traits", "aonid": 160},
            {"type": "link", "name": "Bestiary", "game-obj": "Sources", "aonid": 2},
        ]
        effects = _build_trait_effects(text, links)
        names = {e["name"] for e in effects}
        assert "Undead" in names
        assert "Bestiary" not in names


class TestBuildCombatStatEffects:
    def test_increase_ac_attack_dcs_saves(self):
        text = "Increase AC, attack modifiers, DCs, saving throws by 2."
        effects = _build_combat_stat_effects(text)
        targets = [e["target"] for e in effects]
        # Should include AC
        assert any("ac" in t for t in targets)
        # Should include attack
        assert any("attack" in t for t in targets)
        # Should include 4 DC targets
        dc_targets = [t for t in targets if "dc" in t.lower()]
        assert len(dc_targets) == 4
        # Should include saves
        save_targets = [t for t in targets if "saves" in t]
        assert len(save_targets) == 3  # fort, ref, will
        # All values positive
        for eff in effects:
            assert eff["value"] == 2

    def test_decrease_negative_values(self):
        text = "Decrease AC, attack modifiers by 2."
        effects = _build_combat_stat_effects(text)
        for eff in effects:
            assert eff["value"] == -2


class TestBuildHitPointsEffects:
    def test_with_adjustments(self):
        adjustments = [
            {"type": "stat_block_section", "subtype": "adjustment", "level": "1-4", "hp": "5"},
            {"type": "stat_block_section", "subtype": "adjustment", "level": "5+", "hp": "15"},
        ]
        effects = _build_hit_points_effects("Increase hit points based on level.", adjustments)
        assert len(effects) == 2
        assert all(e["target"] == "$.defense.hitpoints[*].hp" for e in effects)
        assert all("conditional" in e for e in effects)

    def test_without_adjustments(self):
        effects = _build_hit_points_effects("Increase hit points based on level.", None)
        assert effects == []


class TestLevelTextToConditional:
    def test_range(self):
        result = _level_text_to_conditional("2-4")
        assert result == "$.creature_type.level >= 2 && $.creature_type.level <= 4"

    def test_plus_suffix(self):
        result = _level_text_to_conditional("20+")
        assert result == "$.creature_type.level >= 20"

    def test_or_lower(self):
        result = _level_text_to_conditional("1 or lower")
        assert result == "$.creature_type.level <= 1"

    def test_single_number(self):
        result = _level_text_to_conditional("5")
        assert result == "$.creature_type.level == 5"
