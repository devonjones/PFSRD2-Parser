import json

import pytest

from pfsrd2 import ability_placement
from pfsrd2.enrichment import change_extractor
from pfsrd2.enrichment.change_extractor import (
    _build_ability_effects,
    _build_attribute_effects,
    _build_combat_stat_effects,
    _build_damage_effects,
    _build_hit_points_effects,
    _build_speed_effects,
    _build_trait_effects,
    _categorize_change_text,
    _damage_adjustment_item,
    _extract_names_from_text,
    _level_text_to_conditional,
    _mirror_creature_type_removals,
    _normalize_movement_type,
    enrich_change,
)
from pfsrd2.enrichment.change_extractor import (
    _build_strike_effects as _build_strike_effects_public,
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


def _type_adds(effects):
    """add_item effects on the creature-type list (badge mirrors excluded)."""
    return [
        e
        for e in effects
        if e["operation"] == "add_item" and e["target"] == "$.creature_type.creature_types"
    ]


def _badge_adds(effects):
    return [
        e
        for e in effects
        if e["operation"] == "add_item" and e["target"] == "$.creature_type.traits"
    ]


class TestBuildTraitEffects:
    def test_add_multiple_traits(self):
        effects = _build_trait_effects("Add the ghost, spirit, and undead traits.")
        adds = _type_adds(effects)
        assert len(adds) == 3
        names = {e["name"] for e in adds}
        assert names == {"Ghost", "Spirit", "Undead"}
        # every type-list add mirrors into the badge array (v25)
        badge_names = {e["item"]["name"] for e in _badge_adds(effects)}
        assert names <= badge_names

    def test_gains_traits(self):
        effects = _build_trait_effects("The creature gains the undead and vampire traits.")
        adds = _type_adds(effects)
        assert len(adds) == 2
        names = {e["name"] for e in adds}
        assert names == {"Undead", "Vampire"}
        badge_names = {e["item"]["name"] for e in _badge_adds(effects)}
        assert names <= badge_names

    def test_replace_trait(self, monkeypatch):
        # Pin the creature-type set so the test is deterministic regardless
        # of the local enrichment DB state (empty in CI).
        monkeypatch.setattr(change_extractor, "_CREATURE_TYPES_CACHE", frozenset({"human"}))
        effects = _build_trait_effects("Replace the human trait with the dwarf trait.")
        remove_effects = [e for e in effects if e["operation"] == "remove_item"]
        add_effects = [e for e in effects if e["operation"] == "add_item"]
        # Removing a creature type also removes its badge copy from
        # $.creature_type.traits (mirrored removal).
        assert len(remove_effects) == 2
        assert all(e["name"] == "Human" for e in remove_effects)
        assert [e["target"] for e in remove_effects] == [
            "$.creature_type.creature_types",
            "$.creature_type.traits",
        ]
        assert len(add_effects) == 1
        # Badge-array adds carry the full canonical trait object (a
        # name-only badge crashes the display's trait.classes access).
        item = add_effects[0]["item"]
        assert item["name"].lower() == "dwarf"
        assert item["game-id"]
        assert "classes" in item

    def test_mirror_inserts_traits_removal_after_type_removal(self):
        effects = _mirror_creature_type_removals(
            [
                {
                    "name": "Human",
                    "operation": "remove_item",
                    "target": "$.creature_type.creature_types",
                },
                {
                    "name": "Orc",
                    "operation": "add_item",
                    "target": "$.creature_type.creature_types",
                },
            ]
        )
        assert effects == [
            {
                "name": "Human",
                "operation": "remove_item",
                "target": "$.creature_type.creature_types",
            },
            {
                "name": "Human",
                "operation": "remove_item",
                "target": "$.creature_type.traits",
            },
            {
                "name": "Orc",
                "operation": "add_item",
                "target": "$.creature_type.creature_types",
            },
        ]

    def test_mirror_conditional_removal_carries_conditional(self):
        conditional = "$.creature_type.creature_types[?(@ == 'Aquatic')]"
        effects = _mirror_creature_type_removals(
            [
                {
                    "name": "Aquatic",
                    "operation": "remove_item",
                    "target": "$.creature_type.creature_types",
                    "conditional": conditional,
                }
            ]
        )
        assert len(effects) == 2
        mirror = effects[1]
        assert mirror["target"] == "$.creature_type.traits"
        assert mirror["conditional"] == conditional

    def test_mirror_skips_plain_trait_removals(self):
        effects = _mirror_creature_type_removals(
            [{"name": "Mindless", "operation": "remove_item", "target": "$.traits"}]
        )
        assert len(effects) == 1

    def test_link_based_extraction_avoids_fragments(self):
        """pfsrd2-bfy: use Traits links instead of regex to avoid sentence fragments."""
        text = "Add the skeleton and undead traits and, optionally, the mindless trait."
        links = [
            {"type": "link", "name": "skeleton", "game-obj": "Traits", "aonid": 236},
            {"type": "link", "name": "undead", "game-obj": "Traits", "aonid": 160},
            {"type": "link", "name": "mindless", "game-obj": "Traits", "aonid": 108},
        ]
        effects = _build_trait_effects(text, links)
        # Skeleton and Undead are mandatory add_item
        mandatory = {e["name"] for e in _type_adds(effects)} | {
            e["item"]["name"] for e in _badge_adds(effects)
        }
        assert {"Skeleton", "Undead"} <= mandatory
        # Mindless is optional (select with min=0)
        selects = [e for e in effects if e["operation"] == "select"]
        assert len(selects) == 1
        assert selects[0]["selection"]["min"] == 0
        assert selects[0]["selection"]["max"] == 1
        # Options are full effect objects
        opts = selects[0]["selection"]["options"]
        assert len(opts) == 1
        assert opts[0]["name"] == "Mindless"
        assert opts[0]["operation"] == "add_item"
        # Should NOT contain fragments
        for e in effects:
            assert "Traits And" not in e.get("name", "")
            assert "Optionally" not in e.get("name", "")

    def test_link_based_extraction_water_template(self):
        """Water template: 'either the amphibious or aquatic' is a choice of one."""
        text = "Add the water trait and either the amphibious or aquatic trait."
        links = [
            {"type": "link", "name": "water", "game-obj": "Traits", "aonid": 165},
            {"type": "link", "name": "amphibious", "game-obj": "Traits", "aonid": 13},
            {"type": "link", "name": "aquatic", "game-obj": "Traits", "aonid": 14},
        ]
        effects = _build_trait_effects(text, links)
        # Water is mandatory
        mandatory = {
            e.get("name") or (e.get("item") or {}).get("name")
            for e in effects
            if e["operation"] == "add_item"
        }
        assert mandatory == {"Water"}
        # Amphibious/Aquatic is a choice (select with min=1, max=1)
        selects = [e for e in effects if e["operation"] == "select"]
        assert len(selects) == 1
        assert selects[0]["selection"]["min"] == 1
        assert selects[0]["selection"]["max"] == 1
        # Options are full effect objects
        opts = selects[0]["selection"]["options"]
        assert len(opts) == 2
        opt_names = {o["name"] for o in opts}
        assert opt_names == {"Amphibious", "Aquatic"}
        assert all(o["operation"] == "add_item" for o in opts)

    def test_non_trait_links_ignored(self):
        """Links with game-obj != Traits should not be extracted as traits."""
        text = "Add the undead trait."
        links = [
            {"type": "link", "name": "undead", "game-obj": "Traits", "aonid": 160},
            {"type": "link", "name": "Bestiary", "game-obj": "Sources", "aonid": 2},
        ]
        effects = _build_trait_effects(text, links)
        names = {e.get("name") or (e.get("item") or {}).get("name") for e in effects}
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

    def test_attack_emits_spell_attack_target(self):
        """pfsrd2-j7ko: 'attack modifiers' must bump strike attack AND spell attack."""
        text = "Increase attack modifiers by 2."
        effects = _build_combat_stat_effects(text)
        targets = [e["target"] for e in effects]
        assert "$.offense.offensive_actions[*].attack.bonus.bonuses" in targets
        assert "$.offense.offensive_actions[*].spells.spell_attack" in targets


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

    def test_en_dash_range(self):
        """pfsrd2-sz3: en-dash should be treated as range separator."""
        result = _level_text_to_conditional("4\u20138")
        assert result == "$.creature_type.level >= 4 && $.creature_type.level <= 8"

    def test_em_dash_range(self):
        result = _level_text_to_conditional("9\u201413")
        assert result == "$.creature_type.level >= 9 && $.creature_type.level <= 13"


class TestExtractNamesFromText:
    def test_simple_list(self):
        result = _extract_names_from_text("immunities: fire, cold, poison.", "immunities:")
        assert result == ["fire", "cold", "poison"]

    def test_colon_after_descriptive_text(self):
        """pfsrd2-3e5: colon separates description from actual names."""
        result = _extract_names_from_text(
            "weaknesses, with a value based on the creature's level: force, ghost touch, positive.",
            "weaknesses",
        )
        assert result == ["force", "ghost touch", "positive"]

    def test_no_match(self):
        result = _extract_names_from_text("no marker here", "immunities:")
        assert result == []


class TestBuildDamageEffects:
    def test_magical_trait_added(self):
        """pfsrd2-yyr: 'Strikes are magical' should add magical trait."""
        text = "The damage of physical Strikes changes to negative damage, and those Strikes are magical."
        effects = _build_damage_effects(text, "Ghost")
        ops = [e["operation"] for e in effects]
        assert "replace" in ops
        assert "add_item" in ops
        magical = [
            e
            for e in effects
            if e.get("operation") == "add_item" and e.get("item", {}).get("name") == "magical"
        ]
        assert len(magical) == 1

    def test_no_magical_without_keyword(self):
        text = "The damage of physical Strikes changes to negative damage."
        effects = _build_damage_effects(text, "Ghost")
        magical = [e for e in effects if e.get("operation") == "add_item"]
        assert len(magical) == 0

    def test_limited_use_emits_spell_notes_annotation(self):
        """pfsrd2-97fv: 'increase damage by N instead' (limited use) annotates spells.notes.

        Spells have no integer damage field — individual spells may or may not deal
        damage — so the +N instead bump is communicated as a string note.
        """
        text = (
            "Increase the damage of its Strikes and other offensive abilities by 2. "
            "If the creature has limits on how many times or how often it can use an ability "
            "(such as a spellcaster's spells or a dragon's Breath Weapon), "
            "increase the damage by 4 instead."
        )
        effects = _build_damage_effects(text, "Elite")
        notes_effects = [
            e for e in effects if e.get("target") == "$.offense.offensive_actions[*].spells.notes"
        ]
        assert len(notes_effects) == 1
        assert notes_effects[0]["operation"] == "add_item"
        assert notes_effects[0]["item"] == "+4 damage (Elite, limited use)"

    def test_limited_use_negative_spell_notes(self):
        """Weak template: -2 base, -4 limited use → notes string uses bare '-4'."""
        text = (
            "Decrease the damage of its Strikes and other offensive abilities by 2. "
            "If the creature has limits on how many times or how often it can use an ability, "
            "decrease the damage by 4 instead."
        )
        effects = _build_damage_effects(text, "Weak")
        notes_effects = [
            e for e in effects if e.get("target") == "$.offense.offensive_actions[*].spells.notes"
        ]
        assert len(notes_effects) == 1
        assert notes_effects[0]["item"] == "-4 damage (Weak, limited use)"


class TestBuildAbilityEffects:
    def test_empty_abilities_falls_back_to_blanket_target(self):
        effects = _build_ability_effects(None)
        assert effects == [
            {
                "target": "$.defense.automatic_abilities",
                "operation": "add_items",
                "source": "$.changes[*].abilities",
            }
        ]

    def test_empty_list_falls_back(self):
        assert _build_ability_effects([]) == _build_ability_effects(None)

    def test_routes_per_ability_by_action_type(self):
        """One-action → offensive, reaction → reactive, three actions → offensive."""
        abilities = [
            {"name": "A", "action_type": {"name": "One Action"}},
            {"name": "B", "action_type": {"name": "Reaction"}},
            {"name": "C", "action_type": {"name": "Three Actions"}},
        ]
        effects = _build_ability_effects(abilities)
        assert len(effects) == 3
        by_name = {e["source"].split("'")[1]: e["target"] for e in effects}
        assert by_name["A"] == "$.offense.offensive_actions"
        assert by_name["B"] == "$.defense.reactive_abilities"
        assert by_name["C"] == "$.offense.offensive_actions"

    def test_escapes_quotes_and_backslashes_in_source(self):
        abilities = [{"name": "Bob's \\Backslash", "action_type": {"name": "Reaction"}}]
        effects = _build_ability_effects(abilities)
        assert len(effects) == 1
        # Single-quote escaped and backslash escaped so JSONPath stays valid
        assert r"Bob\'s \\Backslash" in effects[0]["source"]
        assert effects[0]["target"] == "$.defense.reactive_abilities"

    def test_asserts_on_unnamed_ability(self):
        """Strategic fragility — parser bug should not be swallowed."""
        abilities = [{"action_type": {"name": "One Action"}}]
        with pytest.raises(AssertionError):
            _build_ability_effects(abilities)


class TestDeterministicAbilityCategory:
    def test_reaction(self):
        assert (
            ability_placement.deterministic_ability_category({"action_type": {"name": "Reaction"}})
            == "reactive"
        )

    def test_one_two_three_action_offensive(self):
        for n in ("One Action", "Two Actions", "Three Actions"):
            assert (
                ability_placement.deterministic_ability_category({"action_type": {"name": n}})
                == "offensive"
            )

    def test_free_action_with_trigger_is_reactive(self):
        ability = {"action_type": {"name": "Free Action"}, "trigger": "something"}
        assert ability_placement.deterministic_ability_category(ability) == "reactive"

    def test_free_action_without_trigger_is_none(self):
        assert (
            ability_placement.deterministic_ability_category(
                {"action_type": {"name": "Free Action"}}
            )
            is None
        )

    def test_missing_or_non_dict_action_type(self):
        assert ability_placement.deterministic_ability_category({}) is None
        assert ability_placement.deterministic_ability_category({"action_type": None}) is None
        assert (
            ability_placement.deterministic_ability_category({"action_type": "One Action"}) is None
        )


class TestAbilityTarget:
    def test_uses_deterministic_category_when_available(self):
        ability = {"name": "Anything", "action_type": {"name": "Reaction"}}
        assert ability_placement.ability_target(ability) == "$.defense.reactive_abilities"

    def test_missing_name_asserts(self):
        with pytest.raises(AssertionError):
            ability_placement.ability_target({})

    def test_interaction_category_targets_top_level_path(self):
        # Regression: CATEGORY_TARGETS["interaction"] used to point at
        # $.stat_block.interaction_abilities — a path that doesn't exist in
        # the creature schema (interaction_abilities lives directly on the
        # stat block), so interaction abilities (e.g. Zombie's Slow) were
        # routed to a dead path and silently vanished on template apply.
        from pfsrd2.sql.enrichment import (
            get_enrichment_db_connection,
            insert_ability_record,
            insert_creature_link,
        )

        conn = get_enrichment_db_connection(db_path=":memory:")
        try:
            curs = conn.cursor()
            ability_id = insert_ability_record(curs, "Slow", "hash_slow", "{}")
            insert_creature_link(
                curs, ability_id, "1234", "Zombie Shambler", 1, "[]", "Bestiary", "interaction"
            )
            category, target = ability_placement.lookup_ability_category("Slow", conn=conn)
            assert category == "interaction"
            assert target == "$.interaction_abilities"
        finally:
            conn.close()


class TestBuildSpeedEffectsRemoveAll:
    def test_replace_highest_with_remove_all(self):
        """pfsrd2-3b0: should have item template and remove_all_except."""
        text = "Change its highest Speed to a fly Speed. Remove all other Speeds."
        effects = _build_speed_effects(text)
        assert len(effects) == 2
        assert effects[0]["operation"] == "replace_highest_with"
        assert "item" in effects[0]
        assert effects[0]["item"]["movement_type"] == "fly"
        assert effects[1]["operation"] == "remove_all_except"

    def test_replace_highest_without_remove(self):
        text = "Change its highest Speed to a fly Speed."
        effects = _build_speed_effects(text)
        assert len(effects) == 1
        assert effects[0]["operation"] == "replace_highest_with"


class TestBuildAttributeEffects:
    def test_threshold_floor_targets_statistics(self):
        # Regression: the threshold form targeted
        # $.creature_type.intelligence_modifier — a path that exists on no
        # creature, so Broodpiercer/cryptid Int floors never fired.
        effects = _build_attribute_effects(
            "If the creature's Intelligence modifier is –4 or lower, increase it to –3."
        )
        assert effects == [
            {
                "conditional": "$.statistics.int <= -4",
                "target": "$.statistics.int",
                "operation": "replace",
                "value": -3,
            }
        ]

    def test_plain_modifier_form_unchanged(self):
        effects = _build_attribute_effects("It has a Strength modifier of +5.")
        assert effects == [{"target": "$.statistics.str", "operation": "replace", "value": 5}]

    def test_threshold_variants(self):
        # ASCII hyphen, "set it to" wording, non-int attribute
        effects = _build_attribute_effects(
            "If the creature's Wisdom modifier is -2 or lower, set it to -1."
        )
        assert effects == [
            {
                "conditional": "$.statistics.wis <= -2",
                "target": "$.statistics.wis",
                "operation": "replace",
                "value": -1,
            }
        ]

    def test_threshold_unknown_attribute_asserts(self):
        # Blind [:3] truncation must never map an unknown word onto a valid
        # stat path ("internal" -> int).
        with pytest.raises(AssertionError, match="unknown stat"):
            _build_attribute_effects(
                "If the creature's Internal modifier is -4 or lower, increase it to -3."
            )

    def test_plain_form_skips_non_attribute_modifiers(self):
        # The scanning branch must skip prose mentioning non-attribute
        # modifiers instead of emitting a bogus $.statistics.per.
        effects = _build_attribute_effects(
            "It has a Strength modifier of +5 and a Perception modifier of +10."
        )
        assert effects == [{"target": "$.statistics.str", "operation": "replace", "value": 5}]


class TestTraitTargetFallback:
    def test_non_creature_type_routes_to_badge_array(self, monkeypatch):
        # $.traits exists on zero creatures — the badge array is the only
        # trait array a remove/add can actually hit.
        monkeypatch.setattr(change_extractor, "_CREATURE_TYPES_CACHE", frozenset({"undead"}))
        from pfsrd2.enrichment.change_extractor import _trait_target

        assert _trait_target("Undead") == "$.creature_type.creature_types"
        assert _trait_target("Uncommon") == "$.creature_type.traits"


class TestStrikeRenameOrdering:
    def test_name_replace_precedes_weapon_replace(self):
        # Sequential application: the weapon replace kills the =='fist'
        # filter, so the name replace must come first (Lizardfolk's Claw
        # rename silently never fired).
        effects = _build_strike_effects_public(
            "Replace any fist attacks with claw attacks. They deal slashing "
            "damage instead of bludgeoning."
        )
        targets = [e["target"] for e in effects]
        assert targets[0].endswith(".attack.name")
        assert targets[1].endswith(".attack.weapon")
        assert "=='claw'" in targets[2]

    def test_set_reach_targets_attack(self):
        effects = _build_strike_effects_public(
            "Reduce the reach of the creature's melee Strikes to 5 feet."
        )
        assert effects[0]["operation"] == "set_reach"
        assert effects[0]["target"].endswith(".attack")


# Bound at import time, before the autouse stub_trait_items fixture patches
# the module attribute — these tests exercise the real lookup.
_REAL_TRAIT_ITEM = change_extractor._trait_item


class TestTraitItem:
    def test_unknown_trait_raises(self, monkeypatch):
        monkeypatch.setattr(change_extractor, "_TRAIT_ITEM_CACHE", {})
        monkeypatch.setattr(
            change_extractor, "fetch_trait_by_name_preferring_edition", lambda c, n: None
        )
        monkeypatch.setattr(change_extractor, "get_db_connection", lambda p: _FakeConn())
        with pytest.raises(change_extractor.TraitLookupError):
            _REAL_TRAIT_ITEM("Revulsion")

    def test_known_trait_builds_full_object(self, monkeypatch):
        row = {
            "trait": json.dumps(
                {
                    "name": "Uncommon",
                    "game-id": "f317",
                    "game-obj": "Traits",
                    "aonid": 99,
                    "schema_version": 1.1,
                    "license": {"name": "OGL"},
                    "type": "trait",
                }
            ),
            "classes": json.dumps([]),
        }
        monkeypatch.setattr(change_extractor, "_TRAIT_ITEM_CACHE", {})
        monkeypatch.setattr(
            change_extractor, "fetch_trait_by_name_preferring_edition", lambda c, n: row
        )
        monkeypatch.setattr(change_extractor, "get_db_connection", lambda p: _FakeConn())
        item = _REAL_TRAIT_ITEM("Uncommon")
        assert item["name"] == "Uncommon"
        # rarity class derived; license/schema noise stripped — the badge
        # trait definition is additionalProperties: false
        assert item["classes"] == ["rarity"]
        assert "aonid" not in item
        assert "license" not in item
        assert "schema_version" not in item
        # cached second call takes the no-DB path and returns a fresh copy
        item2 = _REAL_TRAIT_ITEM("Uncommon")
        assert item2 == item and item2 is not item


class _FakeConn:
    def cursor(self):
        return None

    def close(self):
        pass


class TestChoiceAbilityEffects:
    ABILITIES = [
        {"name": "Hybrid Form", "action_type": {"name": "One Action"}},
        {"name": "Howl", "action_type": {"name": "Two Actions"}},
    ]

    def test_choice_pool_builds_select(self):
        effects = _build_ability_effects(
            self.ABILITIES,
            "The rumored cryptid might have one or both of the following " "optional abilities.",
        )
        assert len(effects) == 1
        sel = effects[0]["selection"]
        assert effects[0]["operation"] == "select"
        assert (sel["min"], sel["max"]) == (0, 2)
        assert len(sel["options"]) == 2
        assert sel["options"][0]["operation"] == "add_items"
        assert sel["options"][0]["names"] == ["Hybrid Form"]
        assert "one or both" in sel["description"]

    def test_all_or_two_pool_maxes_at_pool_size(self):
        effects = _build_ability_effects(
            self.ABILITIES
            + [
                {"name": "A", "action_type": {"name": "Reaction"}},
                {"name": "B", "action_type": {"name": "Reaction"}},
            ],
            "A mutant cryptid should typically either have all four the "
            "following abilities or just two abilities, not including "
            "unusual bane.",
        )
        sel = effects[0]["selection"]
        assert (sel["min"], sel["max"]) == (2, 4)
        assert "not including unusual bane" in sel["description"]

    def test_granting_text_stays_flat(self):
        effects = _build_ability_effects(
            self.ABILITIES, "All host creatures gain the following abilities."
        )
        assert [e["operation"] for e in effects] == ["add_items", "add_items"]

    def test_three_from_list_bounds(self):
        effects = _build_ability_effects(
            self.ABILITIES + [{"name": "C", "action_type": {"name": "Reaction"}}],
            "The creature gains three abilities from the list below.",
        )
        sel = effects[0]["selection"]
        assert (sel["min"], sel["max"]) == (3, 3)

    def test_every_detected_choice_has_bounds(self):
        # Structural guarantee: parser detection IS choice_bounds, so any
        # wording that creates a choice change must produce bounds — a
        # choice pool can never fall through to auto-applied add_items.
        from pfsrd2.enrichment.change_extractor import choice_bounds
        from pfsrd2.monster_template import _GRANTS_ABILITIES

        for text in (
            "might have one or both of the following optional abilities.",
            "should typically either have all four the following abilities or just two",
            "gain two abilities from the list below.",
            "gains four abilities from the list below.",
        ):
            assert choice_bounds(text) is not None
            assert not _GRANTS_ABILITIES.search(text)


class TestSpellScopedCombatStats:
    """v24: spell-scoped stat phrases must not fan out to melee attacks,
    AC, or non-spell ability DCs (Lich: 'Increase spell DCs and spell
    attack roll by 2')."""

    def test_spell_only_line_emits_exactly_spell_targets(self):
        for text in (
            "Increase spell DCs and spell attack roll by 2.",
            "It increases spell DCs and spell attack modifier by 2.",
        ):
            effects = _build_combat_stat_effects(text)
            targets = sorted(e["target"] for e in effects)
            assert targets == [
                "$.offense.offensive_actions[*].spells.saving_throw.dc",
                "$.offense.offensive_actions[*].spells.spell_attack",
            ], text
            assert all(e["value"] == 2 for e in effects)

    def test_generic_line_keeps_full_fanout(self):
        text = "Increase AC, attack bonuses, DCs, saving throws, and skill modifiers by 1."
        effects = _build_combat_stat_effects(text)
        targets = [e["target"] for e in effects]
        assert "$.defense.ac.value" in targets
        assert "$.offense.offensive_actions[*].attack.bonus.bonuses" in targets
        assert "$.offense.offensive_actions[*].spells.spell_attack" in targets
        assert "$.defense.saves.fort.value" in targets
        assert "$.statistics.skills[*].value" in targets
        # spell targets not duplicated by the scoped pass
        assert len(targets) == len(set(targets))

    def test_ac_requires_word_boundary(self):
        # 'reACh' fired the substring gate: Primeval Cryptid grew a bogus
        # AC+5 from 'increase the reach of all its Strikes by 5 feet'.
        text = (
            "Increase the creature's size by one size. If this makes the "
            "creature Huge or Gargantuan, increase the reach of all its "
            "Strikes by 5 feet."
        )
        effects = _build_combat_stat_effects(text)
        assert not any(e["target"] == "$.defense.ac.value" for e in effects)


class TestGeneralizedLevelSubject:
    def test_any_possessive_subject_categorizes_and_builds(self):
        from pfsrd2.enrichment.change_extractor import (
            _build_level_effects,
            _categorize_change_text,
        )

        text = "Increase the dragon’s level by 2 and change their statistics as follows."
        assert _categorize_change_text(text) == "level"
        assert _build_level_effects(text) == [
            {"target": "$.creature_type.level", "operation": "adjustment", "value": 2}
        ]


class TestTraitAddBadgeMirror:
    """v25: creature-type adds mirror into the badge array (display renders
    badges — Catfolk/Amphibious/Athamaru adds were invisible without it)."""

    def test_type_list_add_gains_badge_mirror(self):
        from pfsrd2.enrichment.change_extractor import canonicalize_trait_effects

        effects = canonicalize_trait_effects(
            [
                {
                    "target": "$.creature_type.creature_types",
                    "operation": "add_item",
                    "name": "Catfolk",
                }
            ]
        )
        badge = [
            e
            for e in effects
            if e["target"] == "$.creature_type.traits" and e["operation"] == "add_item"
        ]
        assert len(badge) == 1
        assert badge[0]["item"]["name"] == "Catfolk"

    def test_name_only_badge_add_upgraded_to_item(self):
        from pfsrd2.enrichment.change_extractor import canonicalize_trait_effects

        effects = canonicalize_trait_effects(
            [
                {
                    "target": "$.creature_type.traits",
                    "operation": "add_item",
                    "name": "Amphibious",
                }
            ]
        )
        assert "name" not in effects[0]
        assert effects[0]["item"]["name"] == "Amphibious"

    def test_no_double_badge_when_already_present(self):
        from pfsrd2.enrichment.change_extractor import canonicalize_trait_effects

        effects = canonicalize_trait_effects(
            [
                {
                    "target": "$.creature_type.creature_types",
                    "operation": "add_item",
                    "name": "Catfolk",
                },
                {
                    "target": "$.creature_type.traits",
                    "operation": "add_item",
                    "name": "Catfolk",
                },
            ]
        )
        badges = [
            e
            for e in effects
            if e["target"] == "$.creature_type.traits" and e["operation"] == "add_item"
        ]
        assert len(badges) == 1

    def test_replace_with_added_trait_tail(self):
        # Athamaru: "Replace the human trait with the athamaru trait and add
        # the amphibious trait."
        import json as _json

        from pfsrd2.enrichment.change_extractor import enrich_change

        raw = _json.dumps(
            {
                "text": "- Replace the human trait with the athamaru trait "
                "and add the amphibious trait.",
                "subtype": "change",
                "type": "stat_block_section",
            }
        )
        enriched_json, method = enrich_change(raw, "Athamaru")
        eff = _json.loads(enriched_json)["effects"]
        added = {
            (e.get("name") or (e.get("item") or {}).get("name"))
            for e in eff
            if e["operation"] == "add_item"
        }
        assert "Athamaru" in added or "athamaru" in {str(a).lower() for a in added}
        assert any(str(a).lower() == "amphibious" for a in added)


class TestStrikeTraitRouting:
    def test_strike_traits_target_attacks_not_badges(self):
        effects = _build_trait_effects(
            "Their Strikes gain the magical trait (and the finesse trait, "
            "for melee Strikes) and the phantom gets the phantom touch ability."
        )
        by_name = {e["item"]["name"]: e["target"] for e in effects}
        assert by_name["magical"] == "$.offense.offensive_actions[*].attack.traits"
        assert by_name["finesse"] == (
            "$.offense.offensive_actions[?(@.attack.attack_type=='melee')].attack.traits"
        )
        assert all("creature_type" not in e["target"] for e in effects)

    def test_multi_trait_strike_grant(self):
        effects = _build_trait_effects(
            "Their Strikes gain the magical and force traits (and the finesse "
            "trait, for melee Strikes) and deal force damage instead."
        )
        names = [e["item"]["name"] for e in effects]
        assert names == ["magical", "force", "finesse"]
