"""Unit tests for universal/creatures.py helper functions."""

import pytest

from universal.creatures import universal_handle_special_senses


class TestUniversalHandleSpecialSenses:
    """Tests for universal_handle_special_senses."""

    def test_basic_sense(self):
        """Should parse a simple sense name."""
        result = universal_handle_special_senses(["darkvision"])
        assert len(result) == 1
        assert result[0]["name"] == "darkvision"

    def test_sense_name_stripped(self):
        """Sense name with leading/trailing whitespace should be stripped.

        Regression test for .strip() fix at universal/creatures.py:354.
        """
        result = universal_handle_special_senses([" lifesense "])
        assert len(result) == 1
        assert result[0]["name"] == "lifesense"

    def test_sense_with_range(self):
        """Should parse sense with range like 'darkvision 60 feet'."""
        result = universal_handle_special_senses(["darkvision 60 feet"])
        assert len(result) == 1
        assert result[0]["name"] == "darkvision"
        assert result[0]["range"]["range"] == 60
        assert result[0]["range"]["unit"] == "feet"

    def test_sense_with_modifier(self):
        """Should parse sense with parenthetical modifier."""
        result = universal_handle_special_senses(["blindsense (scent)"])
        assert len(result) == 1
        assert result[0]["name"] == "blindsense"
        assert len(result[0]["modifiers"]) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
