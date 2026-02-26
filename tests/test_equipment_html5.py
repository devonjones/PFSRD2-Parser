"""Tests for equipment.py HTML5 migration functions.

Covers _remove_empty_values_pass, _extract_intelligent_item_section,
_count_links_in_html (HTML5-specific exclusions), and _extract_h3_abilities.
"""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.equipment import (
    _count_links_in_html,
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
        html = (
            "<hr/>"
            "<b>Perception</b> +10<br/>"
            "<b>Will</b> +8<br/>"
            "<hr/>"
        )
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
        html = (
            "before<hr/>"
            "<b>Perception</b> +10<br/>"
            "<b>Will</b> +8<br/>"
            "<hr/>after"
        )
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
# _count_links_in_html — HTML5-specific exclusion patterns
# (Basic exclusions already tested in test_equipment_helpers.py)
# ---------------------------------------------------------------------------
class TestCountLinksInHtmlHtml5Exclusions:
    """Tests for HTML5-specific link exclusion patterns in _count_links_in_html."""

    def test_excludes_alternate_edition_link(self):
        """Links inside siderbarlook div with Legacy/Remastered version text excluded."""
        html = (
            '<div class="siderbarlook">'
            'There is a <a game-obj="Equipment" aonid="99">Legacy version</a> of this item.'
            "</div>"
            '<a game-obj="Spells" aonid="1">fireball</a>'
        )
        assert _count_links_in_html(html) == 1

    def test_keeps_siderbarlook_without_version_text(self):
        """Links in siderbarlook div without version text are NOT excluded."""
        html = (
            '<div class="siderbarlook">'
            '<a game-obj="Equipment" aonid="99">Some other thing</a>'
            "</div>"
        )
        assert _count_links_in_html(html) == 1

    def test_excludes_sidebar_links(self):
        """Links inside <div class='sidebar'> excluded."""
        html = (
            '<div class="sidebar">'
            '<a game-obj="Rules" aonid="5">Sidebar Rule</a>'
            "</div>"
            '<a game-obj="Spells" aonid="1">spell</a>'
        )
        assert _count_links_in_html(html) == 1

    def test_excludes_combination_weapon_trait_entry_links(self):
        """Links inside trait-entry divs excluded when combination weapon detected."""
        html = (
            '<h2 class="title">Melee</h2>'
            "<p>melee stats</p>"
            '<h2 class="title">Ranged</h2>'
            "<p>ranged stats</p>"
            '<h2 class="title">Traits</h2>'
            '<div class="trait-entry">'
            '<a game-obj="Traits" aonid="10">Deadly</a>'
            "</div>"
        )
        # "Deadly" is inside trait-entry → excluded. No other countable links.
        assert _count_links_in_html(html) == 0

    def test_trait_entry_not_excluded_without_combination(self):
        """Without Melee/Ranged h2s, trait-entry links are NOT excluded."""
        html = (
            '<div class="trait-entry">'
            '<a game-obj="Traits" aonid="10">Deadly</a>'
            "</div>"
        )
        assert _count_links_in_html(html) == 1

    def test_mixed_html5_exclusions(self):
        """Multiple HTML5 exclusion types in one block."""
        html = (
            # sidebar link — excluded
            '<div class="sidebar"><a game-obj="Rules" aonid="1">rule</a></div>'
            # alternate edition link — excluded
            '<div class="siderbarlook">There is a '
            '<a game-obj="Equipment" aonid="2">Remastered version</a></div>'
            # PFS link — excluded
            '<a href="PFS.aspx?ID=1">PFS</a>'
            # real content links — counted
            '<a game-obj="Spells" aonid="3">spell1</a>'
            '<a game-obj="Spells" aonid="4">spell2</a>'
        )
        assert _count_links_in_html(html) == 2

    def test_self_reference_requires_both_name_and_game_obj(self):
        """Self-reference exclusion with game-obj requires BOTH to match."""
        html = (
            '<a game-obj="Equipment" aonid="1">Flaming Sword</a>'
            '<a game-obj="Spells" aonid="2">Flaming Sword</a>'
        )
        # Only Equipment/Flaming Sword excluded, Spells/Flaming Sword kept
        count = _count_links_in_html(
            html, exclude_name="Flaming Sword", exclude_game_obj="Equipment"
        )
        assert count == 1

    def test_trait_span_with_list_classes(self):
        """Trait span with multiple CSS classes (list format) still excluded."""
        html = '<span class="trait trait-uncommon"><a game-obj="Traits" aonid="1">Uncommon</a></span>'
        assert _count_links_in_html(html) == 0


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
