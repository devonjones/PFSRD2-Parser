"""Tests for the regex extraction tier."""

from pfsrd2.enrichment.regex_extractor import (
    _apply_trailing_modifier,
    detect_keywords,
    extract_all,
    extract_area,
    extract_damage,
    extract_frequency,
    extract_range,
    extract_save_dc,
)


class TestExtractSaveDC:
    def test_dc_basic_reflex(self):
        text = "12d6 acid damage in an 80-foot line (DC 30 basic Reflex save)"
        results = extract_save_dc(text)
        assert len(results) == 1
        assert results[0]["dc"] == 30
        assert results[0]["save_type"] == "Ref"
        assert results[0]["basic"] is True

    def test_dc_basic_reflex_no_save_word(self):
        text = "deals 8d6 cold damage (DC 25 basic Reflex)"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 25
        assert results[0]["basic"] is True

    def test_dc_fortitude(self):
        text = "must succeed at a DC 28 Fortitude save or be knocked prone"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 28
        assert results[0]["save_type"] == "Fort"
        assert "basic" not in results[0]

    def test_dc_will(self):
        text = "must attempt a DC 38 Will save"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 38
        assert results[0]["save_type"] == "Will"

    def test_fortitude_dc(self):
        text = "Fortitude DC 22"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 22
        assert results[0]["save_type"] == "Fort"

    def test_bare_dc(self):
        text = "2d8+8 bludgeoning, DC 29"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 29
        assert "save_type" not in results[0]

    def test_dc_with_parenthetical_modifier(self):
        text = "2d8+8 bludgeoning, DC 25 (grabbed by claws only)"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 25
        assert "modifiers" in results[0]
        assert results[0]["modifiers"][0]["name"] == "grabbed by claws only"

    def test_dc_save_no_trailing_paren(self):
        text = "DC 30 basic Reflex save and is knocked prone"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 30
        assert "modifiers" not in results[0]

    def test_flat_check(self):
        text = "must attempt a DC 5 flat check"
        results = extract_save_dc(text)
        assert results[0]["dc"] == 5
        assert results[0]["save_type"] == "Flat Check"

    def test_no_dc(self):
        text = "The creature grabs its target."
        assert extract_save_dc(text) == []

    def test_none_input(self):
        assert extract_save_dc(None) == []

    def test_stat_block_structure(self):
        results = extract_save_dc("DC 30 basic Reflex save")
        assert results[0]["type"] == "stat_block_section"
        assert results[0]["subtype"] == "save_dc"
        assert "text" in results[0]

    def test_multiple_dcs(self):
        text = "deals 20d6 acid damage (DC 44 basic Reflex save). The fumes require a DC 42 Fortitude save."
        results = extract_save_dc(text)
        assert len(results) == 2
        dcs = {(r["dc"], r.get("save_type")) for r in results}
        assert (44, "Ref") in dcs
        assert (42, "Fort") in dcs

    def test_same_dc_not_duplicated(self):
        text = "DC 30 Reflex save. On a failure, another DC 30 Reflex save."
        results = extract_save_dc(text)
        assert len(results) == 1  # same DC+type = deduplicated

    def test_escape_dc_as_bare(self):
        text = "Escape DC 36. The dragon can't use Breath Weapon again."
        results = extract_save_dc(text)
        assert len(results) == 1
        assert results[0]["dc"] == 36


class TestExtractArea:
    def test_line(self):
        text = "acid damage in an 80-foot line"
        results = extract_area(text)
        assert len(results) == 1
        assert results[0]["shape"] == "line"
        assert results[0]["size"] == 80
        assert results[0]["unit"] == "feet"

    def test_cone(self):
        text = "in a 60-foot cone (DC 41 basic Reflex save)"
        results = extract_area(text)
        assert results[0]["shape"] == "cone"
        assert results[0]["size"] == 60

    def test_burst(self):
        text = "explodes into a 20-foot burst of freezing mist"
        results = extract_area(text)
        assert results[0]["shape"] == "burst"
        assert results[0]["size"] == 20

    def test_emanation(self):
        text = "creatures in a 30-foot emanation"
        results = extract_area(text)
        assert results[0]["shape"] == "emanation"
        assert results[0]["size"] == 30

    def test_wall(self):
        text = "creates a 60-foot wall of fire"
        results = extract_area(text)
        assert results[0]["shape"] == "wall"
        assert results[0]["size"] == 60

    def test_radius(self):
        text = "in a 10-foot radius"
        results = extract_area(text)
        assert results[0]["shape"] == "burst"  # radius maps to burst in PF2e
        assert results[0]["size"] == 10

    def test_no_area(self):
        text = "The creature grabs its target."
        assert extract_area(text) == []

    def test_none_input(self):
        assert extract_area(None) == []

    def test_stat_block_structure(self):
        results = extract_area("a 30-foot cone")
        assert results[0]["type"] == "stat_block_section"
        assert results[0]["subtype"] == "area"
        assert results[0]["text"] == "30-foot cone"

    def test_multiple_areas(self):
        text = "in either a 30-foot cone or a 90-foot line"
        results = extract_area(text)
        assert len(results) == 2
        shapes = {r["shape"] for r in results}
        assert shapes == {"cone", "line"}

    def test_same_area_not_duplicated(self):
        text = "in a 30-foot cone. Another 30-foot cone."
        results = extract_area(text)
        assert len(results) == 1


class TestExtractRange:
    def test_within_feet(self):
        text = "a target within 90 feet"
        result = extract_range(text)
        assert result["range"] == 90
        assert result["unit"] == "feet"

    def test_within_miles(self):
        text = "any creature within 1 mile"
        result = extract_range(text)
        assert result["range"] == 1
        assert result["unit"] == "miles"

    def test_range_of(self):
        text = "a range of 120 feet"
        result = extract_range(text)
        assert result["range"] == 120
        assert result["unit"] == "feet"

    def test_no_range(self):
        text = "The creature grabs its target."
        assert extract_range(text) is None

    def test_stat_block_structure(self):
        result = extract_range("within 60 feet")
        assert result["type"] == "stat_block_section"
        assert result["subtype"] == "range"


class TestExtractDamage:
    def test_simple_damage(self):
        text = "deals 12d6 acid damage"
        result = extract_damage(text)
        assert len(result) == 1
        assert result[0]["formula"] == "12d6"
        assert result[0]["damage_type"] == "acid"

    def test_damage_with_modifier(self):
        text = "2d8+8 bludgeoning damage"
        result = extract_damage(text)
        assert len(result) == 1
        assert result[0]["formula"] == "2d8+8"
        assert result[0]["damage_type"] == "bludgeoning"

    def test_multiple_damage_types(self):
        text = "10d6 fire damage and 5d12 bludgeoning damage"
        result = extract_damage(text)
        assert len(result) == 2
        types = {d["damage_type"] for d in result}
        assert types == {"fire", "bludgeoning"}

    def test_persistent_damage(self):
        text = "takes 3d6 persistent poison damage"
        result = extract_damage(text)
        assert len(result) == 1
        assert result[0]["formula"] == "3d6"
        assert result[0]["damage_type"] == "poison"
        assert result[0]["persistent"] is True

    def test_persistent_bleed(self):
        text = "2d8 persistent bleed damage"
        result = extract_damage(text)
        assert len(result) == 1
        assert result[0]["damage_type"] == "bleed"
        assert result[0]["persistent"] is True

    def test_no_damage(self):
        text = "The creature is frightened 1."
        assert extract_damage(text) == []

    def test_none_input(self):
        assert extract_damage(None) == []

    def test_negative_modifier(self):
        text = "1d6-1 fire damage"
        result = extract_damage(text)
        assert len(result) == 1
        assert result[0]["formula"] == "1d6-1"

    def test_stat_block_structure(self):
        result = extract_damage("2d6 fire damage")
        assert result[0]["type"] == "stat_block_section"
        assert result[0]["subtype"] == "attack_damage"

    def test_constrict_format(self):
        text = "2d10+17 bludgeoning plus 2d6 evil, DC 43"
        # "2d6 evil" doesn't have "damage" after it, so should only get the first
        result = extract_damage(text)
        # Constrict format doesn't always say "damage" — this tests conservatism
        assert len(result) == 0  # no "damage" word present


class TestExtractFrequency:
    def test_cant_use_again_for_rounds(self):
        text = "It can\u2019t use Breath Weapon again for 1d4 rounds."
        assert extract_frequency(text) == "1d4 rounds"

    def test_cant_use_again_for_minute(self):
        text = "a giant wolverine can't use Wolverine Rage again for 1 minute."
        assert extract_frequency(text) == "1 minute"

    def test_once_per_day(self):
        text = "The dragon can use this ability once per day."
        assert extract_frequency(text) == "once per day"

    def test_once_per_round(self):
        text = "She can do this once per round."
        assert extract_frequency(text) == "once per round"

    def test_cannot_use_again(self):
        text = "The dragon cannot use Breath Weapon again for 2 rounds."
        assert extract_frequency(text) == "2 rounds"

    def test_once_per_month(self):
        text = "a glabrezu can grant a mortal the effects once per month"
        assert extract_frequency(text) == "once per month"

    def test_no_frequency(self):
        text = "The creature grabs its target."
        assert extract_frequency(text) is None

    def test_none_input(self):
        assert extract_frequency(None) is None


class TestFalseAlarmFiltering:
    def test_damage_bonus_not_flagged(self):
        text = "gains a +4 status bonus to damage rolls for 1 minute"
        assert "damage" not in detect_keywords(text)

    def test_resistance_to_damage_not_flagged(self):
        text = "gains resistance 15 to physical and spirit damage"
        assert "damage" not in detect_keywords(text)

    def test_hardness_not_flagged(self):
        text = "This Hardness reduces any damage it takes by an amount equal to the Hardness."
        assert "damage" not in detect_keywords(text)

    def test_real_damage_still_flagged(self):
        text = "deals massive sonic damage to nearby creatures"
        assert "damage" in detect_keywords(text)

    def test_creature_fortitude_dc_not_flagged(self):
        text = "attempts an Athletics check against the creature's Fortitude DC"
        assert "dc" not in detect_keywords(text)

    def test_real_dc_still_flagged(self):
        text = "must succeed at a DC 28 check or be stunned"
        assert "dc" in detect_keywords(text)

    def test_speed_bonus_not_flagged(self):
        text = "gains a +10-foot circumstance bonus to Speed"
        assert "area" not in detect_keywords(text)

    def test_troop_movement_not_flagged(self):
        text = "condense into a 20-foot-by-20-foot area"
        assert "area" not in detect_keywords(text)

    def test_real_area_still_flagged(self):
        text = "creatures in a 40-foot radius take damage"
        assert "area" in detect_keywords(text)

    def test_extra_reactions_not_flagged(self):
        text = "gains an extra reaction per round for each head"
        assert "frequency" not in detect_keywords(text)

    def test_real_frequency_still_flagged(self):
        text = "can only do this once per day"
        assert "frequency" in detect_keywords(text)

    def test_attack_and_damage_modifiers_not_flagged(self):
        text = "This doesn't change their attack and damage modifiers with their Strikes."
        assert "damage" not in detect_keywords(text)

    def test_damaged_by_trigger_not_flagged(self):
        text = "immediately upon being damaged by a critical hit"
        assert "damage" not in detect_keywords(text)


class TestExtractAll:
    def test_breath_weapon(self):
        ability = {
            "name": "Breath Weapon",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "text": "The dragon breathes a spray of acid that deals 12d6 acid damage in an 80-foot line (DC 30 basic Reflex save). It can\u2019t use Breath Weapon again for 1d4 rounds.",
        }
        result, missed = extract_all(ability)
        assert result is not None
        assert missed == {}
        assert len(result["saving_throw"]) == 1
        assert result["saving_throw"][0]["dc"] == 30
        assert result["saving_throw"][0]["save_type"] == "Ref"
        assert result["saving_throw"][0]["basic"] is True
        assert result["area"][0]["shape"] == "line"
        assert result["area"][0]["size"] == 80
        assert len(result["damage"]) == 1
        assert result["damage"][0]["formula"] == "12d6"
        assert result["damage"][0]["damage_type"] == "acid"
        assert result["frequency"] == "1d4 rounds"
        # Original fields preserved
        assert result["name"] == "Breath Weapon"
        assert result["text"] == ability["text"]

    def test_no_extractions_no_keywords(self):
        ability = {
            "name": "Draconic Momentum",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "text": "The dragon recharges their Breath Weapon whenever they score a critical hit with a Strike.",
        }
        result, missed = extract_all(ability)
        assert result is None
        assert missed == {}

    def test_missed_keywords_flagged(self):
        ability = {
            "name": "Weird Ability",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "text": "The creature deals massive damage to everything nearby at 100 foot altitude.",
        }
        result, missed = extract_all(ability)
        # "damage" keyword detected but no XdY pattern — (1, 0)
        assert "damage" in missed
        assert missed["damage"] == (1, 0)
        # "foot" detected but neither area shape nor "within/range of" pattern
        assert "area" in missed
        assert missed["area"] == (1, 0)

    def test_skips_existing_fields(self):
        ability = {
            "name": "Test",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "text": "DC 30 basic Reflex save, 10d6 fire damage in a 30-foot cone",
            "saving_throw": {"existing": True},
        }
        result, missed = extract_all(ability)
        assert result is not None
        # Should NOT overwrite existing saving_throw
        assert result["saving_throw"] == {"existing": True}
        # But should add area and damage
        assert result["area"][0]["shape"] == "cone"
        assert len(result["damage"]) == 1

    def test_effect_field_searched(self):
        ability = {
            "name": "Corrupt Water",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "frequency": "Once per day",
            "effect": "The dragon permanently befouls 10 cubic feet of liquid within 90 feet. A creature can attempt a DC 28 Will save to protect liquids.",
        }
        result, missed = extract_all(ability)
        assert result is not None
        assert result["saving_throw"][0]["dc"] == 28
        assert result["saving_throw"][0]["save_type"] == "Will"
        # frequency already exists, should not be in missed
        assert "frequency" not in missed

    def test_json_string_input(self):
        import json

        ability = {
            "name": "Test",
            "type": "stat_block_section",
            "subtype": "ability",
            "ability_type": "offensive",
            "text": "deals 5d6 fire damage (DC 20 basic Reflex save) in a 30-foot cone",
        }
        result, missed = extract_all(json.dumps(ability))
        assert result is not None
        assert result["saving_throw"][0]["dc"] == 20


class TestApplyTrailingModifier:
    def test_adds_modifier_when_present(self):
        result = {"dc": 25}
        text = "DC 25 (grabbed by claws only) and stuff"
        # match_end points right after "DC 25"
        _apply_trailing_modifier(result, text, 5)
        assert "modifiers" in result
        assert result["modifiers"][0]["name"] == "grabbed by claws only"

    def test_no_modifier_when_absent(self):
        result = {"dc": 30}
        text = "DC 30 basic Reflex save"
        _apply_trailing_modifier(result, text, 5)
        assert "modifiers" not in result

    def test_does_not_overwrite_existing_keys(self):
        result = {"dc": 25, "save_type": "Ref"}
        text = "DC 25 (with penalty)"
        _apply_trailing_modifier(result, text, 5)
        assert result["save_type"] == "Ref"
        assert result["dc"] == 25
        assert "modifiers" in result
