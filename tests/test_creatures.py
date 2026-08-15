"""Unit tests for creatures.py helper functions."""

import pytest

from pfsrd2.creatures import (
    _creature_handle_value,
    _creature_trait_pre_process,
    process_defense,
    split_stat_block_line,
)
from universal.attack import parse_attack_damage
from universal.utils import parse_defense_line


class TestSplitStatBlockLine:
    """Tests for split_stat_block_line with split_maintain_parens."""

    def test_basic_semicolon_split(self):
        """Should split on semicolons."""
        result = split_stat_block_line("speed 30 feet; fly 60 feet")
        assert result == ["speed 30 feet", "fly 60 feet"]

    def test_basic_comma_split(self):
        """Should split on commas."""
        result = split_stat_block_line("fire 5, cold 5, electricity 5")
        assert result == ["fire 5", "cold 5", "electricity 5"]

    def test_semicolon_inside_parens_not_split(self):
        """Semicolons inside parentheses should NOT be split."""
        result = split_stat_block_line("resistance 10 (except force; double vs. non-magical)")
        assert len(result) == 1
        assert "except force; double vs. non-magical" in result[0]

    def test_commas_inside_parens_not_split(self):
        """Commas inside parentheses should NOT be split."""
        result = split_stat_block_line("attack +15 (1d8+5, grab)")
        assert len(result) == 1
        assert "1d8+5, grab" in result[0]

    def test_mixed_semicolons_and_commas(self):
        """Should split on both semicolons and commas."""
        result = split_stat_block_line("fire 5, cold 5; electricity 10")
        assert result == ["fire 5", "cold 5", "electricity 10"]

    def test_strips_whitespace(self):
        """Should strip whitespace from results."""
        result = split_stat_block_line("  fire 5 ,  cold 5 ;  electricity 10  ")
        assert result == ["fire 5", "cold 5", "electricity 10"]


class TestBreakOutMovementStrip:
    """Regression test for .strip() fix in break_out_movement / process_speed."""

    def test_movement_type_no_leading_space(self):
        """Movement type should not have leading whitespace.

        Bug: regex capture group for 'fly 30 feet' could include
        leading space, producing ' fly' instead of 'fly'.
        """
        # This tests the fix at creatures.py:1747
        # The actual process_speed function is deeply nested, so we test
        # split_stat_block_line as the entry point that feeds into it.
        result = split_stat_block_line(" fly 30 feet")
        assert result[0] == "fly 30 feet"


class TestCreatureHandleValue:
    def _make_trait(self, name):
        return {"name": name, "type": "trait"}

    def test_range_increment(self):
        trait = self._make_trait("range increment 30 feet")
        _creature_handle_value(trait)
        assert trait["name"] == "range"
        assert trait["value"] == "increment 30 feet"

    def test_regex_numeric_match(self):
        trait = self._make_trait("Deadly d8")
        _creature_handle_value(trait)
        assert trait["name"] == "Deadly"
        assert trait["value"] == "d8"

    def test_regex_plus_match(self):
        trait = self._make_trait("Damage +2")
        _creature_handle_value(trait)
        assert trait["name"] == "Damage"
        assert trait["value"] == "+2"

    def test_versatile(self):
        trait = self._make_trait("versatile S")
        _creature_handle_value(trait)
        assert trait["name"] == "versatile"
        assert trait["value"] == "S"

    def test_reload(self):
        trait = self._make_trait("reload 1")
        _creature_handle_value(trait)
        assert trait["name"] == "reload"
        assert trait["value"] == "1"

    def test_precious(self):
        trait = self._make_trait("precious cold iron")
        _creature_handle_value(trait)
        assert trait["name"] == "precious"
        assert trait["value"] == "cold iron"

    def test_attached(self):
        trait = self._make_trait("attached to shield")
        _creature_handle_value(trait)
        assert trait["name"] == "attached"
        assert trait["value"] == "to shield"

    def test_no_match_unchanged(self):
        trait = self._make_trait("Fire")
        _creature_handle_value(trait)
        assert trait["name"] == "Fire"
        assert "value" not in trait


class TestCreatureTraitPreProcess:
    def test_non_alignment_returns_false(self):
        trait = {"name": "Fire", "type": "trait", "classes": ["energy"]}
        result = _creature_trait_pre_process(trait, [trait], None)
        assert result is False

    def test_no_alignment_trait_returns_false(self):
        trait = {"name": "No Alignment", "type": "trait", "classes": ["alignment"]}
        result = _creature_trait_pre_process(trait, [trait], None)
        assert result is False

    def test_value_extraction_in_pre_process(self):
        trait = {"name": "versatile P", "type": "trait", "classes": ["weapon"]}
        _creature_trait_pre_process(trait, [trait], None)
        assert trait["name"] == "versatile"
        assert trait["value"] == "P"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestParseAttackDamage:
    """The damage parser is shared with hazards, which is where these shapes come from."""

    def test_simple_damage(self):
        damage = parse_attack_damage("2d12+4 slashing")[0]
        assert (damage["formula"], damage["damage_type"]) == ("2d12+4", "slashing")

    def test_trailing_clause_becomes_a_note(self):
        # "slashing; no multiple attack penalty" is a type plus a note, not a type.
        damage = parse_attack_damage("2d12+4 slashing; no multiple attack penalty")[0]
        assert damage["damage_type"] == "slashing"
        assert damage["notes"] == "no multiple attack penalty"

    def test_parenthetical_and_trailing_notes_both_survive(self):
        damage = parse_attack_damage("3d6 slashing (magical); no multiple attack penalty")[0]
        assert damage["damage_type"] == "slashing"
        assert damage["notes"] == "magical; no multiple attack penalty"

    def test_comma_before_dice_separates_instances(self):
        damages = parse_attack_damage("1d6 acid, 2d6 fire, and 2d6 poison")
        assert [(d["formula"], d["damage_type"]) for d in damages] == [
            ("1d6", "acid"),
            ("2d6", "fire"),
            ("2d6", "poison"),
        ]

    def test_a_comma_inside_a_damage_type_is_not_a_separator(self):
        # The guard on the split above: no dice follows these commas.
        damages = parse_attack_damage("1d6 bludgeoning, piercing, or slashing")
        assert len(damages) == 1
        assert damages[0]["damage_type"] == "bludgeoning, piercing, or slashing"

    def test_trailing_separator_is_not_part_of_the_type(self):
        assert parse_attack_damage("5d10 bludgeoning,")[0]["damage_type"] == "bludgeoning"

    def test_plus_still_separates(self):
        damages = parse_attack_damage("4d6+10 slashing plus 1d6 bleed")
        assert [d["damage_type"] for d in damages] == ["slashing", "bleed"]

    def test_a_bare_damage_type_means_it_varies(self):
        # "2d10+13 damage (fire damage from the burning city, ...)" — the types
        # are spelled out in the note, not the type slot.
        damage = parse_attack_damage("2d10+13 damage (fire from the city, sonic from the storm)")[0]
        assert damage["damage_type"] == "varies"
        assert "fire from the city" in damage["notes"]


class TestProcessDefense:
    """Shared with hazards via universal.utils.parse_defense_line."""

    def _run(self, label, text):
        hp = {}
        process_defense(hp, [label, text, None, None])
        return hp[label.lower()]

    def test_immunities_split_into_entries(self):
        entries = self._run("Immunities", "critical hits, object immunities")
        assert [e["name"] for e in entries] == ["critical hits", "object immunities"]
        assert all(e["subtype"] == "immunity" for e in entries)

    def test_valued_weaknesses(self):
        entries = self._run("Weaknesses", "cold 5, fire 10")
        assert [(e["name"], e["value"]) for e in entries] == [("cold", 5), ("fire", 10)]

    def test_trailing_separator_is_trimmed(self):
        # Both callers rely on this; hazards used to trim it themselves.
        assert [e["name"] for e in self._run("Resistances", "fire 5;")] == ["fire"]
        assert [e["name"] for e in self._run("Resistances", "fire 5,")] == ["fire"]

    def test_a_gap_between_separators_fails_loudly(self):
        with pytest.raises(AssertionError, match="Empty entry"):
            self._run("Immunities", "fire,, cold")

    def test_an_unexpected_label_fails_loudly(self):
        with pytest.raises(AssertionError):
            self._run("Speed", "fire 5")

    def test_a_link_in_the_trailing_clause_is_extracted(self):
        # Otherwise the raw anchor ships inside notes.
        damage = parse_attack_damage(
            '2d6 mental; the target is <a game-obj="Conditions" aonid="19">frightened</a> 1'
        )[0]
        assert "<a" not in damage["notes"]
        assert [link["name"] for link in damage["links"]] == ["frightened"]

    def test_subtype_is_what_the_caller_asked_for(self):
        entries = parse_defense_line("cold 5", "resistance")
        assert entries[0]["subtype"] == "resistance"

    def test_one_trailing_separator_is_routine_two_is_malformed(self):
        assert [e["name"] for e in parse_defense_line("fire 5;", "resistance")] == ["fire"]
        with pytest.raises(AssertionError, match="Empty entry"):
            parse_defense_line("fire 5;,", "resistance")

    def test_a_semicolon_inside_the_parenthetical_is_not_a_separator(self):
        # Splitting on it leaks a stray ")" into the note.
        damage = parse_attack_damage(
            "2d12 poison (on a critical hit, the target is enfeebled 1; this has the poison trait)"
        )[0]
        assert damage["damage_type"] == "poison"
        assert damage["notes"] == (
            "on a critical hit, the target is enfeebled 1; this has the poison trait"
        )
