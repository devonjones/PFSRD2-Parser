"""Tests for spell range/area structured parsing."""

from pfsrd2.spell import (
    _parse_distance,
    _parse_single_area,
    _parse_spell_area,
    _parse_spell_range,
)


class TestParseDistance:
    def test_feet(self):
        assert _parse_distance("30 feet") == (30, "feet")

    def test_feet_uppercase(self):
        assert _parse_distance("120 Feet") == (120, "feet")

    def test_mile(self):
        assert _parse_distance("1 mile") == (1, "miles")

    def test_miles(self):
        assert _parse_distance("10 miles") == (10, "miles")

    def test_comma_number(self):
        assert _parse_distance("1,000 feet") == (1000, "feet")

    def test_no_match(self):
        assert _parse_distance("touch") is None

    def test_with_parenthetical(self):
        assert _parse_distance("30 feet (burst only)") == (30, "feet")


class TestParseSpellRange:
    def test_numeric_feet(self):
        result = _parse_spell_range("30 feet")
        assert result["range"] == 30
        assert result["unit"] == "feet"
        assert result["text"] == "30 feet"
        assert "touch" not in result

    def test_numeric_miles(self):
        result = _parse_spell_range("1 mile")
        assert result["range"] == 1
        assert result["unit"] == "miles"

    def test_touch(self):
        result = _parse_spell_range("touch")
        assert result["touch"] is True
        assert result["range"] == 0
        assert result["unit"] == "feet"

    def test_touch_or_feet(self):
        result = _parse_spell_range("touch or 30 feet")
        assert result["touch"] is True
        assert result["range"] == 30
        assert result["unit"] == "feet"

    def test_varies(self):
        result = _parse_spell_range("varies")
        assert result["text"] == "varies"
        assert "range" not in result

    def test_planetary(self):
        result = _parse_spell_range("planetary")
        assert result["text"] == "planetary"
        assert "range" not in result

    def test_area_in_range(self):
        result = _parse_spell_range("30-foot cone")
        assert result["range"] == 30
        assert result["unit"] == "feet"

    def test_stat_block_structure(self):
        result = _parse_spell_range("120 feet")
        assert result["type"] == "stat_block_section"
        assert result["subtype"] == "range"


class TestParseSingleArea:
    def test_cone(self):
        result = _parse_single_area("30-foot cone")
        assert result["shape"] == "cone"
        assert result["size"] == 30
        assert result["unit"] == "feet"

    def test_line(self):
        result = _parse_single_area("60-foot line")
        assert result["shape"] == "line"
        assert result["size"] == 60

    def test_burst(self):
        result = _parse_single_area("10-foot burst")
        assert result["shape"] == "burst"
        assert result["size"] == 10

    def test_emanation(self):
        result = _parse_single_area("20-foot emanation")
        assert result["shape"] == "emanation"
        assert result["size"] == 20

    def test_radius_emanation(self):
        result = _parse_single_area("15-foot-radius emanation")
        assert result["shape"] == "emanation"
        assert result["size"] == 15

    def test_cylinder(self):
        result = _parse_single_area("10-foot radius, 50-foot-tall cylinder")
        assert result["shape"] == "cylinder"
        assert result["size"] == 10

    def test_no_match(self):
        assert _parse_single_area("1 5-foot square") is None

    def test_stat_block_structure(self):
        result = _parse_single_area("30-foot cone")
        assert result["type"] == "stat_block_section"
        assert result["subtype"] == "area"


class TestParseSpellArea:
    def test_simple_area(self):
        result = _parse_spell_area("30-foot cone")
        assert result["shape"] == "cone"
        assert result["size"] == 30

    def test_compound_keeps_first_match(self):
        # Compound areas match the first area shape in the string
        result = _parse_spell_area("30-foot cone or 10-foot emanation")
        assert result["shape"] == "cone"
        assert result["size"] == 30
        # Full text preserved
        assert "or" in result["text"]

    def test_unparseable(self):
        result = _parse_spell_area("1 5-foot square")
        assert result["text"] == "1 5-foot square"
        assert "shape" not in result

    def test_compound_comma_keeps_first(self):
        result = _parse_spell_area("10-foot-radius burst, 30-foot cone, or 60-foot line")
        assert result["shape"] == "burst"
        assert result["size"] == 10

    def test_emanation_with_qualifier(self):
        result = _parse_spell_area("100-foot emanation, which includes you")
        assert result["shape"] == "emanation"
        assert result["size"] == 100
