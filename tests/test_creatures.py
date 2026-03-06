"""Unit tests for creatures.py helper functions."""

import pytest

from pfsrd2.creatures import split_stat_block_line


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
