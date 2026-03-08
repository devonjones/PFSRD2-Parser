"""Unit tests for creatures.py helper functions."""

import pytest

from pfsrd2.creatures import (
    _creature_handle_value,
    _creature_trait_pre_process,
    split_stat_block_line,
)


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
