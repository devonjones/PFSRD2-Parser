"""Tests for equipment.py HTML5 migration functions.

Covers _remove_empty_values_pass, _extract_intelligent_item_section,
and _extract_h3_abilities.
"""

from bs4 import BeautifulSoup

from pfsrd2.equipment import (
    _extract_h3_abilities,
    _extract_intelligent_item_section,
    _remove_empty_values_pass,
)


# ---------------------------------------------------------------------------
# _remove_empty_values_pass
# ---------------------------------------------------------------------------
class TestRemoveEmptyValuesPass:
    """Tests for recursive empty-value cleanup."""

    def test_removes_empty_list(self):
        obj = {"name": "Sword", "tags": []}
        _remove_empty_values_pass(obj)
        assert "tags" not in obj
        assert obj["name"] == "Sword"

    def test_removes_empty_dict_from_list(self):
        obj = {"abilities": [{"name": "Strike"}, {}]}
        _remove_empty_values_pass(obj)
        assert obj["abilities"] == [{"name": "Strike"}]

    def test_nested_recursive_cleanup(self):
        obj = {"outer": [{"inner": []}]}
        _remove_empty_values_pass(obj)
        # inner list removed → dict becomes {} → pruned from outer → outer empty → removed
        assert "outer" not in obj

    def test_preserves_nonempty_values(self):
        obj = {"name": "Shield", "bonus": 0, "active": False, "note": None, "hp": 10}
        _remove_empty_values_pass(obj)
        assert obj == {"name": "Shield", "bonus": 0, "active": False, "note": None, "hp": 10}

    def test_preserves_nonempty_strings(self):
        obj = {"desc": "A sturdy shield", "items": ["a", "b"]}
        _remove_empty_values_pass(obj)
        assert obj == {"desc": "A sturdy shield", "items": ["a", "b"]}

    def test_list_becomes_empty_after_recursive_cleanup(self):
        obj = {"data": [{"sub": []}]}
        _remove_empty_values_pass(obj)
        assert "data" not in obj

    def test_already_clean_structure_unchanged(self):
        obj = {"name": "Dagger", "traits": [{"name": "agile"}]}
        _remove_empty_values_pass(obj)
        assert obj == {"name": "Dagger", "traits": [{"name": "agile"}]}

    def test_top_level_list(self):
        """Handles top-level list input (not just dict)."""
        obj = [{"a": []}, {"b": "keep"}]
        _remove_empty_values_pass(obj)
        assert obj == [{}, {"b": "keep"}]


# ---------------------------------------------------------------------------
# _extract_intelligent_item_section
# ---------------------------------------------------------------------------
class TestExtractIntelligentItemSection:
    """Tests for intelligent item stat block extraction."""

    def test_no_hr_returns_zero(self):
        html = "<b>Source</b> Player Core<br/>Description text"
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        result = _extract_intelligent_item_section(soup, sb)
        assert result == 0
        assert "intelligent_item" not in sb

    def test_hr_but_not_perception_returns_zero(self):
        html = "<hr/><b>Source</b> Player Core<br/>Description text"
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        result = _extract_intelligent_item_section(soup, sb)
        assert result == 0
        assert "intelligent_item" not in sb

    def test_valid_full_intelligent_item(self):
        html = (
            "<b>Source</b> book<br/>"
            "<hr/>"
            "<b>Perception</b> +20; darkvision<br/>"
            "<b>Communication</b> speech<br/>"
            "<b>Skills</b> Diplomacy +18<br/>"
            "<b>Int</b> +2, <b>Wis</b> +3, <b>Cha</b> +4<br/>"
            "<b>Will</b> +15<br/>"
            "<hr/>"
            "<b>Effect</b> something"
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        result = _extract_intelligent_item_section(soup, sb)
        assert result == 0
        assert "intelligent_item" in sb
        section = sb["intelligent_item"]
        assert section["type"] == "stat_block_section"
        assert section["subtype"] == "intelligent_item"
        assert section["perception"] == "+20; darkvision"
        assert section["communication"] == "speech"
        assert section["skills"] == "Diplomacy +18"
        assert section["int_mod"] == "+2"
        assert section["wis_mod"] == "+3"
        assert section["cha_mod"] == "+4"
        assert section["will"] == "+15"

    def test_partial_fields(self):
        html = "<hr/>" "<b>Perception</b> +10<br/>" "<b>Will</b> +8<br/>" "<hr/>"
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_intelligent_item_section(soup, sb)
        section = sb["intelligent_item"]
        assert section["perception"] == "+10"
        assert section["will"] == "+8"
        assert "communication" not in section
        assert "skills" not in section

    def test_links_extracted(self):
        html = (
            "<hr/>"
            '<b>Perception</b> +15; <a game-obj="Spells" aonid="1">detect magic</a><br/>'
            "<b>Will</b> +12<br/>"
            "<hr/>"
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_intelligent_item_section(soup, sb)
        section = sb["intelligent_item"]
        assert "links" in section
        assert len(section["links"]) == 1
        assert section["links"][0]["name"] == "detect magic"

    def test_elements_removed_from_soup(self):
        html = "before<hr/>" "<b>Perception</b> +10<br/>" "<b>Will</b> +8<br/>" "<hr/>after"
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_intelligent_item_section(soup, sb)
        text = soup.get_text()
        assert "before" in text
        assert "after" in text
        # Intelligent item content and first hr should be gone
        assert "Perception" not in text
        assert soup.find("hr") is not None  # second hr remains


# ---------------------------------------------------------------------------
# _extract_h3_abilities
# ---------------------------------------------------------------------------
class TestExtractH3Abilities:
    """Tests for h3-based ability extraction."""

    def test_no_h3_abilities_returns_zero(self):
        html = "<p>Regular description text.</p>"
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        result = _extract_h3_abilities(soup, sb)
        assert result == 0
        assert "statistics" not in sb

    def test_h3_without_action_link_ignored(self):
        """h3.title without action link or span is not treated as ability."""
        html = '<h3 class="title">Regular Heading</h3><p>Text</p>'
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)
        assert "statistics" not in sb

    def test_single_ability_with_action_link(self):
        html = (
            '<h3 class="title">'
            '<a game-obj="Actions" aonid="72">Detect Alignment</a> '
            '<span class="action" title="Single Action">[one-action]</span>'
            "</h3>"
            '<b>Source</b> <a game-obj="Sources" aonid="1">Player Core</a><br/>'
            "<b>Frequency</b> once per day"
            "<hr/>"
            "You detect evil creatures nearby."
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)

        abilities = sb["statistics"]["abilities"]
        assert len(abilities) == 1
        ability = abilities[0]
        assert ability["name"] == "Detect Alignment"
        assert ability["type"] == "stat_block_section"
        assert ability["subtype"] == "ability"
        assert ability["ability_type"] == "offensive"
        assert ability["action_type"]["name"] == "One Action"
        assert ability["frequency"] == "once per day"
        assert "You detect evil creatures nearby." in ability["effect"]
        # Should have links: action link + source link
        assert len(ability["links"]) == 2

    def test_ability_with_save_outcomes(self):
        html = (
            '<h3 class="title">'
            '<a game-obj="Actions" aonid="1">Blast</a> '
            '<span class="action" title="Two Actions">[two-actions]</span>'
            "</h3>"
            "<hr/>"
            "<b>Critical Success</b> No damage<br/>"
            "<b>Success</b> Half damage<br/>"
            "<b>Failure</b> Full damage<br/>"
            "<b>Critical Failure</b> Double damage"
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)

        # Save outcomes go into effect text since they're after the hr
        ability = sb["statistics"]["abilities"][0]
        assert ability["name"] == "Blast"
        assert ability["action_type"]["name"] == "Two Actions"

    def test_source_links_extracted_but_source_not_field(self):
        """Source links are collected but Source is not added as an ability field."""
        html = (
            '<h3 class="title">'
            '<a game-obj="Actions" aonid="1">Strike</a>'
            "</h3>"
            '<b>Source</b> <a game-obj="Sources" aonid="5">GM Core</a>'
            "<hr/>"
            "Make a melee Strike."
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)

        ability = sb["statistics"]["abilities"][0]
        assert "source" not in ability
        # Source link should be in links list
        source_links = [l for l in ability["links"] if l.get("game-obj") == "Sources"]
        assert len(source_links) == 1

    def test_multiple_abilities_extracted_in_order(self):
        html = (
            '<h3 class="title">'
            '<a game-obj="Actions" aonid="1">First</a>'
            "</h3>"
            "<hr/>First effect."
            '<h3 class="title">'
            '<a game-obj="Actions" aonid="2">Second</a>'
            "</h3>"
            "<hr/>Second effect."
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)

        abilities = sb["statistics"]["abilities"]
        assert len(abilities) == 2
        assert abilities[0]["name"] == "First"
        assert abilities[1]["name"] == "Second"

    def test_elements_removed_from_desc_soup(self):
        """h3 ability and all its content siblings are removed from soup."""
        html = (
            "<p>Description before.</p>"
            '<h3 class="title">'
            '<a game-obj="Actions" aonid="1">Ability</a>'
            "</h3>"
            "<hr/>Effect text."
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)

        remaining = soup.get_text()
        assert "Description before." in remaining
        # h3 and its content (hr + effect) should be gone
        assert "Ability" not in remaining
        assert "Effect text." not in remaining

    def test_ability_with_action_span_only(self):
        """h3 with action span but no action link (empty anchor case)."""
        html = (
            '<h3 class="title">'
            '<span class="action" title="Reaction">[reaction]</span>'
            "</h3>"
            "<hr/>React to the trigger."
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)

        abilities = sb["statistics"]["abilities"]
        assert len(abilities) == 1
        assert abilities[0]["action_type"]["name"] == "Reaction"
        assert "React to the trigger." in abilities[0]["effect"]

    def test_single_action_title_normalized(self):
        """'Single Action' title is normalized to 'One Action'."""
        html = (
            '<h3 class="title">'
            '<a game-obj="Actions" aonid="1">Strike</a> '
            '<span class="action" title="Single Action">[one-action]</span>'
            "</h3>"
            "<hr/>Make a Strike."
        )
        soup = BeautifulSoup(html, "html.parser")
        sb = {}
        _extract_h3_abilities(soup, sb)

        assert sb["statistics"]["abilities"][0]["action_type"]["name"] == "One Action"
