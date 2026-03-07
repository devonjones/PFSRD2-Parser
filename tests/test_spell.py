"""Unit tests for spell.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.spell import (
    _clean_spell_name,
    _extract_heightened,
    _extract_legacy_marker,
    _extract_result_blocks,
    _extract_stat_fields,
    _extract_traits,
    _label_to_key,
    _parse_heightened_label,
    find_spell,
)
from universal.universal import handle_alternate_link
from universal.utils import is_empty, remove_empty_fields


# --- _clean_spell_name ---


class TestCleanSpellName:
    def test_strips_trailing_or(self):
        assert _clean_spell_name("Heal or") == "Heal"

    def test_strips_trailing_to(self):
        assert _clean_spell_name("Heal to") == "Heal"

    def test_strips_trailing_or_more(self):
        assert _clean_spell_name("Heal or more") == "Heal"

    def test_collapses_multiple_spaces(self):
        assert _clean_spell_name("Heal  Me   Now") == "Heal Me Now"

    def test_passthrough_clean_name(self):
        assert _clean_spell_name("Fireball") == "Fireball"

    def test_strips_whitespace(self):
        assert _clean_spell_name("  Fireball  ") == "Fireball"


# --- handle_alternate_link ---


class TestExtractAlternateLinks:
    def test_returns_none_for_empty_details(self):
        assert handle_alternate_link([]) is None

    def test_returns_none_for_non_string_first(self):
        assert handle_alternate_link([{"type": "section"}]) is None

    def test_returns_none_for_no_version_text(self):
        assert handle_alternate_link(["Some random text"]) is None

    def test_single_legacy_link(self):
        html = (
            '<div>Legacy version: '
            '<a href="/Spells.aspx?ID=207" game-obj="Spells" aonid="207">'
            'Neutralize Poison</a></div>'
        )
        details = [html]
        result = handle_alternate_link(details)
        assert result is not None
        assert result["type"] == "alternate_link"
        assert result["game-obj"] == "Spells"
        assert result["aonid"] == 207
        assert result["alternate_type"] == "legacy"
        assert len(details) == 0  # consumed from details

    def test_single_remastered_link(self):
        html = (
            '<div>Remastered version: '
            '<a href="/Spells.aspx?ID=1467" game-obj="Spells" aonid="1467">'
            'Cleanse Affliction</a></div>'
        )
        details = [html]
        result = handle_alternate_link(details)
        assert result["alternate_type"] == "remastered"
        assert result["aonid"] == 1467

    def test_multi_link_returns_array(self):
        html = (
            '<div>Legacy versions: '
            '<a href="/Spells.aspx?ID=207" game-obj="Spells" aonid="207">Neutralize Poison</a>, '
            '<a href="/Spells.aspx?ID=251" game-obj="Spells" aonid="251">Remove Disease</a>, '
            '<a href="/Spells.aspx?ID=250" game-obj="Spells" aonid="250">Remove Curse</a></div>'
        )
        details = [html]
        result = handle_alternate_link(details, allow_multiple=True)
        assert isinstance(result, list)
        assert len(result) == 3
        assert result[0]["aonid"] == 207
        assert result[1]["aonid"] == 251
        assert result[2]["aonid"] == 250
        assert all(r["alternate_type"] == "legacy" for r in result)

    def test_multi_link_asserts_without_allow_multiple(self):
        html = (
            '<div>Legacy versions: '
            '<a href="/Spells.aspx?ID=207" game-obj="Spells" aonid="207">Neutralize Poison</a>, '
            '<a href="/Spells.aspx?ID=251" game-obj="Spells" aonid="251">Remove Disease</a></div>'
        )
        details = [html]
        with pytest.raises(AssertionError):
            handle_alternate_link(details)

    def test_does_not_consume_non_matching(self):
        details = ["Some other text", "more stuff"]
        handle_alternate_link(details)
        assert len(details) == 2


# --- _label_to_key ---


class TestLabelToKey:
    def test_traditions(self):
        assert _label_to_key("Traditions") == "traditions"

    def test_saving_throw(self):
        assert _label_to_key("Saving Throw") == "saving_throw"

    def test_bloodline_singular(self):
        assert _label_to_key("Bloodline") == "bloodline"

    def test_bloodlines_plural(self):
        assert _label_to_key("Bloodlines") == "bloodline"

    def test_unknown_label_asserts(self):
        with pytest.raises(AssertionError, match="No key mapping"):
            _label_to_key("UnknownLabel")

    def test_cast(self):
        assert _label_to_key("Cast") == "cast"

    def test_pfs_note(self):
        assert _label_to_key("PFS Note") == "pfs_note"


# --- _parse_heightened_label ---


class TestParseHeightenedLabel:
    def test_increment(self):
        result = _parse_heightened_label("Heightened (+1)")
        assert result["type"] == "stat_block_section"
        assert result["subtype"] == "heightened"
        assert result["increment"] == 1
        assert "level" not in result
        assert "amp" not in result

    def test_level(self):
        result = _parse_heightened_label("Heightened (4th)")
        assert result["level"] == 4
        assert "increment" not in result

    def test_amp_increment(self):
        result = _parse_heightened_label("Amp Heightened (+2)")
        assert result["amp"] is True
        assert result["increment"] == 2

    def test_tenth_level(self):
        result = _parse_heightened_label("Heightened (10th)")
        assert result["level"] == 10

    def test_missing_parens_asserts(self):
        with pytest.raises(AssertionError, match="without parenthetical"):
            _parse_heightened_label("Heightened")


# --- _extract_stat_fields ---


class TestExtractStatFields:
    def test_extracts_range(self):
        spell = {}
        text = "<b>Range</b> 30 feet<br/>"
        _extract_stat_fields(spell, text)
        assert spell["range"] == "30 feet"

    def test_extracts_duration(self):
        spell = {}
        text = "<b>Duration</b> 1 minute<br/>"
        _extract_stat_fields(spell, text)
        assert spell["duration"] == "1 minute"

    def test_strips_trailing_semicolon(self):
        spell = {}
        text = "<b>Targets</b> 1 creature;"
        _extract_stat_fields(spell, text)
        assert spell["targets"] == "1 creature"

    def test_skips_source_label(self):
        spell = {}
        text = "<b>Source</b> Core Rulebook<br/><b>Range</b> 30 feet"
        _extract_stat_fields(spell, text)
        assert "source" not in spell
        assert spell["range"] == "30 feet"

    def test_multiple_fields(self):
        spell = {}
        text = "<b>Range</b> 120 feet<br/><b>Targets</b> 1 creature<br/><b>Duration</b> sustained"
        _extract_stat_fields(spell, text)
        assert spell["range"] == "120 feet"
        assert spell["targets"] == "1 creature"
        assert spell["duration"] == "sustained"


# --- _extract_traits ---


class TestExtractTraits:
    def test_extracts_trait_with_link(self):
        spell = {}
        html = '<span class="trait"><a href="/Traits.aspx?ID=1" game-obj="Traits" aonid="1">Fire</a></span>'
        bs = BeautifulSoup(html, "html.parser")
        _extract_traits(bs, spell)
        assert len(spell["traits"]) == 1
        assert spell["traits"][0]["name"] == "Fire"

    def test_removes_letter_spacing_spans(self):
        html = (
            '<span class="trait"><a href="/Traits.aspx?ID=1" game-obj="Traits" aonid="1">Fire</a></span>'
            '<span style="letter-spacing: 3px;"> </span>'
            '<span class="trait"><a href="/Traits.aspx?ID=2" game-obj="Traits" aonid="2">Evocation</a></span>'
        )
        bs = BeautifulSoup(html, "html.parser")
        _extract_traits(bs, spell := {})
        assert len(spell["traits"]) == 2
        # Letter-spacing spans should be removed
        assert not bs.find_all("span", style=lambda s: s and "letter-spacing" in s)

    def test_no_traits(self):
        bs = BeautifulSoup("<p>No traits here</p>", "html.parser")
        spell = {}
        _extract_traits(bs, spell)
        assert "traits" not in spell


# --- _extract_legacy_marker ---


class TestExtractLegacyMarker:
    def test_adds_legacy_section(self):
        struct = {"sections": []}
        bs = BeautifulSoup('<h3 class="title">Legacy Content</h3>', "html.parser")
        _extract_legacy_marker(bs, struct)
        assert len(struct["sections"]) == 1
        assert struct["sections"][0]["name"] == "Legacy Content"
        assert not bs.find("h3")  # h3 decomposed

    def test_no_legacy_marker(self):
        struct = {"sections": []}
        bs = BeautifulSoup("<p>Regular content</p>", "html.parser")
        _extract_legacy_marker(bs, struct)
        assert len(struct["sections"]) == 0


# --- _extract_result_blocks ---


class TestExtractResultBlocks:
    def test_extracts_all_four_results(self):
        spell = {}
        html = (
            "<b>Critical Success</b> No damage"
            "<br/><b>Success</b> Half damage"
            "<br/><b>Failure</b> Full damage"
            "<br/><b>Critical Failure</b> Double damage"
        )
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(spell, bs)
        assert spell["critical_success"] == "No damage"
        assert spell["success"] == "Half damage"
        assert spell["failure"] == "Full damage"
        assert spell["critical_failure"] == "Double damage"

    def test_partial_results(self):
        spell = {}
        html = "<b>Success</b> You resist<br/><b>Failure</b> You take damage"
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(spell, bs)
        assert "critical_success" not in spell
        assert spell["success"] == "You resist"
        assert spell["failure"] == "You take damage"

    def test_non_result_bold_preserved(self):
        spell = {}
        html = "<b>Other Label</b> Some text<br/><b>Success</b> You win"
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(spell, bs)
        assert spell["success"] == "You win"
        assert "other_label" not in spell
        # Non-result bold should still be in the soup
        assert bs.find("b", string="Other Label")


# --- _extract_heightened ---


class TestExtractHeightened:
    def test_increment_heightened(self):
        spell = {}
        text = "<b>Heightened (+1)</b> Damage increases by 1d6"
        _extract_heightened(spell, text)
        assert len(spell["heightened"]) == 1
        h = spell["heightened"][0]
        assert h["increment"] == 1
        assert h["text"] == "Damage increases by 1d6"

    def test_level_heightened(self):
        spell = {}
        text = "<b>Heightened (4th)</b> Target up to 4 creatures"
        _extract_heightened(spell, text)
        assert spell["heightened"][0]["level"] == 4

    def test_amp_heightened(self):
        spell = {}
        text = "<b>Amp Heightened (+2)</b> Extra focus damage"
        _extract_heightened(spell, text)
        h = spell["heightened"][0]
        assert h["amp"] is True
        assert h["increment"] == 2

    def test_multiple_heightened(self):
        spell = {}
        text = (
            "<b>Heightened (+1)</b> More damage<br/>"
            "<b>Heightened (4th)</b> Extra targets"
        )
        _extract_heightened(spell, text)
        assert len(spell["heightened"]) == 2

    def test_no_heightened(self):
        spell = {}
        text = "<b>Some other label</b> Not heightened"
        _extract_heightened(spell, text)
        assert "heightened" not in spell


# --- find_spell ---


class TestFindSpell:
    def test_finds_spell_section(self):
        struct = {
            "sections": [
                {
                    "type": "stat_block_section",
                    "subtype": "spell",
                    "name": "Fireball",
                }
            ]
        }
        result = find_spell(struct)
        assert result is not None
        assert result["name"] == "Fireball"

    def test_returns_none_when_not_found(self):
        struct = {"sections": [{"type": "section", "name": "Description"}]}
        assert find_spell(struct) is None


# --- is_empty ---


class TestIsEmpty:
    def test_noneis_empty(self):
        assert is_empty(None) is True

    def test_empty_stringis_empty(self):
        assert is_empty("") is True

    def test_whitespace_stringis_empty(self):
        assert is_empty("   ") is True

    def test_empty_listis_empty(self):
        assert is_empty([]) is True

    def test_empty_dictis_empty(self):
        assert is_empty({}) is True

    def test_non_empty_string(self):
        assert is_empty("hello") is False

    def test_non_empty_list(self):
        assert is_empty([1]) is False

    def test_zero_is_not_empty(self):
        assert is_empty(0) is False

    def test_false_is_not_empty(self):
        assert is_empty(False) is False


# --- remove_empty_fields ---


class TestRemoveEmptyFields:
    def test_removes_none_values(self):
        obj = {"a": 1, "b": None}
        remove_empty_fields(obj)
        assert obj == {"a": 1}

    def test_removes_empty_strings(self):
        obj = {"a": "hello", "b": ""}
        remove_empty_fields(obj)
        assert obj == {"a": "hello"}

    def test_removes_whitespace_strings(self):
        obj = {"a": "hello", "b": "   "}
        remove_empty_fields(obj)
        assert obj == {"a": "hello"}

    def test_removes_empty_lists(self):
        obj = {"a": [1], "b": []}
        remove_empty_fields(obj)
        assert obj == {"a": [1]}

    def test_removes_empty_dicts(self):
        obj = {"a": {"x": 1}, "b": {}}
        remove_empty_fields(obj)
        assert obj == {"a": {"x": 1}}

    def test_recursive_cleanup(self):
        obj = {"a": {"nested": None, "keep": "yes"}}
        remove_empty_fields(obj)
        assert obj == {"a": {"keep": "yes"}}

    def test_preserves_zero_and_false(self):
        obj = {"a": 0, "b": False, "c": None}
        remove_empty_fields(obj)
        assert obj == {"a": 0, "b": False}

    def test_list_cleanup(self):
        obj = {"items": [{"a": 1}, {"b": None}]}
        remove_empty_fields(obj)
        assert obj == {"items": [{"a": 1}]}
