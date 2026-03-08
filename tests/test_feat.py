"""Unit tests for feat.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.feat import (
    _extract_action_type,
    _extract_bold_fields,
    _extract_called_actions_from_section,
    _extract_result_blocks,
    _extract_source_from_bs,
    _parse_called_action,
    feat_extract_pass,
    find_feat,
    restructure_feat_pass,
)
from universal.universal import build_object


# --- find_feat ---


class TestFindFeat:
    def test_finds_feat_section(self):
        struct = {
            "sections": [
                {"type": "stat_block_section", "subtype": "feat", "name": "Test"},
                {"type": "section", "name": "Other"},
            ]
        }
        result = find_feat(struct)
        assert result is not None
        assert result["name"] == "Test"

    def test_returns_none_when_no_feat(self):
        struct = {"sections": [{"type": "section", "name": "Other"}]}
        assert find_feat(struct) is None


# --- _extract_action_type ---


class TestExtractActionType:
    def test_single_action(self):
        feat = {"_name_html": '<span class="action" title="Single Action"></span>'}
        _extract_action_type(feat)
        assert feat["action_type"]["name"] == "One Action"
        assert feat["action_type"]["subtype"] == "action_type"

    def test_reaction(self):
        feat = {"_name_html": '<span class="action" title="Reaction"></span>'}
        _extract_action_type(feat)
        assert feat["action_type"]["name"] == "Reaction"

    def test_two_actions(self):
        feat = {"_name_html": '<span class="action" title="Two Actions"></span>'}
        _extract_action_type(feat)
        assert feat["action_type"]["name"] == "Two Actions"

    def test_three_actions(self):
        feat = {"_name_html": '<span class="action" title="Three Actions"></span>'}
        _extract_action_type(feat)
        assert feat["action_type"]["name"] == "Three Actions"

    def test_free_action(self):
        feat = {"_name_html": '<span class="action" title="Free Action"></span>'}
        _extract_action_type(feat)
        assert feat["action_type"]["name"] == "Free Action"

    def test_no_action_span(self):
        feat = {"_name_html": "<span>Feat 1</span>"}
        _extract_action_type(feat)
        assert "action_type" not in feat

    def test_empty_name_html(self):
        feat = {"_name_html": ""}
        _extract_action_type(feat)
        assert "action_type" not in feat

    def test_pops_name_html(self):
        feat = {"_name_html": '<span class="action" title="Reaction"></span>'}
        _extract_action_type(feat)
        assert "_name_html" not in feat

    def test_unknown_action_raises(self):
        feat = {"_name_html": '<span class="action" title="Unknown"></span>'}
        with pytest.raises(AssertionError, match="Unknown action title"):
            _extract_action_type(feat)


# --- _extract_source_from_bs ---


class TestExtractSourceFromBs:
    def test_basic_source(self):
        html = '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1"><i>Core Rulebook pg. 36</i></a><br/>'
        bs = BeautifulSoup(html, "html.parser")
        source = _extract_source_from_bs(bs)
        assert source is not None
        assert source["name"] == "Core Rulebook"
        assert source["page"] == 36
        assert source["type"] == "source"

    def test_source_with_errata(self):
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            '<i>Core Rulebook pg. 36</i></a> '
            '<sup><a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">4.0</a></sup><br/>'
        )
        bs = BeautifulSoup(html, "html.parser")
        source = _extract_source_from_bs(bs)
        assert source is not None
        assert "errata" in source
        assert source["errata"]["name"] == "4.0"

    def test_no_source_tag(self):
        bs = BeautifulSoup("<b>Prerequisites</b> trained in Nature", "html.parser")
        source = _extract_source_from_bs(bs)
        assert source is None

    def test_removes_source_from_bs(self):
        html = '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1"><i>Core Rulebook pg. 36</i></a><br/>remaining text'
        bs = BeautifulSoup(html, "html.parser")
        _extract_source_from_bs(bs)
        assert "Source" not in str(bs)
        assert "remaining text" in str(bs)


# --- _extract_bold_fields ---


class TestExtractBoldFields:
    def test_prerequisites(self):
        html = "<b>Prerequisites</b> trained in Nature"
        section = {}
        _extract_bold_fields(section, html)
        assert section["prerequisite"] == "trained in Nature"

    def test_singular_prerequisite(self):
        html = "<b>Prerequisite</b> expert in Arcana"
        section = {}
        _extract_bold_fields(section, html)
        assert section["prerequisite"] == "expert in Arcana"

    def test_requirements(self):
        html = "<b>Requirements</b> You are wielding a shield."
        section = {}
        _extract_bold_fields(section, html)
        assert section["requirement"] == "You are wielding a shield."

    def test_trigger(self):
        html = "<b>Trigger</b> An enemy within your reach hits an ally."
        section = {}
        _extract_bold_fields(section, html)
        assert section["trigger"] == "An enemy within your reach hits an ally."

    def test_frequency(self):
        html = "<b>Frequency</b> once per day"
        section = {}
        _extract_bold_fields(section, html)
        assert section["frequency"] == "once per day"

    def test_multiple_fields(self):
        html = "<b>Prerequisites</b> trained in Nature<br/><b>Trigger</b> You fail a check"
        section = {}
        _extract_bold_fields(section, html)
        assert section["prerequisite"] == "trained in Nature"
        assert section["trigger"] == "You fail a check"

    def test_strips_trailing_semicolons(self):
        html = "<b>Prerequisites</b> trained in Nature;"
        section = {}
        _extract_bold_fields(section, html)
        assert section["prerequisite"] == "trained in Nature"

    def test_strips_trailing_br(self):
        html = "<b>Cost</b> 1 Focus Point<br/>"
        section = {}
        _extract_bold_fields(section, html)
        assert section["cost"] == "1 Focus Point"

    def test_ignores_unknown_labels(self):
        html = "<b>Unknown</b> some value"
        section = {}
        _extract_bold_fields(section, html)
        assert "unknown" not in section


# --- _extract_result_blocks ---


class TestExtractResultBlocks:
    def test_all_four_results(self):
        html = (
            "<b>Critical Success</b> You heal 4d8 damage."
            "<b>Success</b> You heal 2d8 damage."
            "<b>Failure</b> No effect."
            "<b>Critical Failure</b> You take 1d8 damage."
        )
        section = {}
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(section, bs)
        assert section["critical_success"] == "You heal 4d8 damage."
        assert section["success"] == "You heal 2d8 damage."
        assert section["failure"] == "No effect."
        assert section["critical_failure"] == "You take 1d8 damage."

    def test_partial_results(self):
        html = "<b>Success</b> You succeed.<b>Failure</b> You fail."
        section = {}
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(section, bs)
        assert section["success"] == "You succeed."
        assert section["failure"] == "You fail."
        assert "critical_success" not in section

    def test_ignores_non_result_bold(self):
        html = "<b>Note</b> some text<b>Success</b> You win."
        section = {}
        bs = BeautifulSoup(html, "html.parser")
        _extract_result_blocks(section, bs)
        assert section["success"] == "You win."
        assert "note" not in section


# --- _parse_called_action ---


class TestParseCalledAction:
    def _make_div(self, html):
        bs = BeautifulSoup(html, "html.parser")
        return bs.find("div")

    def test_basic_called_action(self):
        html = (
            '<div class="calledAction">'
            '<h3 class="title"><a href="Actions.aspx?ID=2900" game-obj="Actions" aonid="2900">Call Companion</a></h3>'
            '<span class="trait"><a href="/Traits.aspx?ID=595" game-obj="Traits" aonid="595">Exploration</a></span>'
            "<br/>"
            '<b>Source</b> <a href="Sources.aspx?ID=227" game-obj="Sources" aonid="227"><i>Player Core 2 pg. 189</i></a>'
            "<hr/>"
            "You spend 1 minute calling for a different animal companion."
            "</div>"
        )
        div = self._make_div(html)
        ability = _parse_called_action(div)
        assert ability["name"] == "Call Companion"
        assert ability["type"] == "stat_block_section"
        assert ability["subtype"] == "ability"
        assert ability["ability_type"] == "called"
        assert ability["link"]["game-obj"] == "Actions"
        assert ability["link"]["aonid"] == 2900
        assert len(ability["traits"]) == 1
        assert ability["traits"][0]["name"] == "Exploration"
        assert len(ability["sources"]) == 1
        assert ability["sources"][0]["name"] == "Player Core 2"
        assert "calling for a different animal companion" in ability["text"]

    def test_no_traits(self):
        html = (
            '<div class="calledAction">'
            '<h3 class="title"><a href="Actions.aspx?ID=100" game-obj="Actions" aonid="100">Simple Action</a></h3>'
            "<hr/>"
            "Do something simple."
            "</div>"
        )
        div = self._make_div(html)
        ability = _parse_called_action(div)
        assert ability["name"] == "Simple Action"
        assert "traits" not in ability
        assert ability["text"] == "Do something simple."


# --- _extract_called_actions_from_section ---


class TestExtractCalledActionsFromSection:
    def test_extracts_called_action_from_text(self):
        section = {
            "type": "section",
            "text": (
                "Some intro text."
                '<div class="calledAction">'
                '<h3 class="title"><a href="Actions.aspx?ID=100" game-obj="Actions" aonid="100">Test Action</a></h3>'
                "<hr/>Action description.</div>"
            ),
            "sections": [],
        }
        _extract_called_actions_from_section(section)
        assert "abilities" in section
        assert len(section["abilities"]) == 1
        assert section["abilities"][0]["name"] == "Test Action"
        assert "calledAction" not in section["text"]
        assert "Some intro text." in section["text"]

    def test_no_called_action(self):
        section = {"type": "section", "text": "Just normal text.", "sections": []}
        _extract_called_actions_from_section(section)
        assert "abilities" not in section

    def test_no_text_field(self):
        section = {"type": "section", "sections": []}
        _extract_called_actions_from_section(section)
        assert "abilities" not in section


# --- restructure_feat_pass ---


class TestRestructureFeatPass:
    def test_standard_structure(self):
        """Standard feat: name in text, content in Feat N section."""
        details = [
            {
                "name": "PFS stuff",
                "text": '<a game-obj="Feats" aonid="1">Dwarven Lore</a>',
                "sections": [
                    {
                        "name": "Feat 1",
                        "text": '<b>Source</b> <a href="Sources.aspx?ID=1"><i>Core Rulebook pg. 36</i></a><hr/>You know stuff.',
                        "sections": [],
                    }
                ],
            }
        ]
        result = restructure_feat_pass(details)
        assert result["name"] == "Dwarven Lore"
        assert result["type"] == "feat"
        feat = find_feat(result)
        assert feat is not None
        assert feat["name"] == "Dwarven Lore"
        assert feat["level"] == 1
        assert "Source" in feat["text"]

    def test_legacy_marker(self):
        details = [
            {
                "name": "PFS",
                "text": '<a game-obj="Feats" aonid="1">Test</a>',
                "sections": [
                    {
                        "name": "Feat 1",
                        "sections": [
                            {
                                "name": "Legacy Content",
                                "text": '<b>Source</b> <a href="x"><i>Book pg. 1</i></a><hr/>Desc.',
                                "sections": [],
                            }
                        ],
                    }
                ],
            }
        ]
        result = restructure_feat_pass(details)
        legacy_sections = [s for s in result["sections"] if s.get("name") == "Legacy Content"]
        assert len(legacy_sections) == 1

    def test_extra_sections_preserved(self):
        details = [
            {
                "name": "PFS",
                "text": '<a game-obj="Feats" aonid="1">Test</a>',
                "sections": [
                    {
                        "name": "Feat 2",
                        "text": '<b>Source</b> <a href="x"><i>Book pg. 1</i></a><hr/>Desc.',
                        "sections": [],
                    },
                    {
                        "name": "Leads To...",
                        "text": "Some links",
                        "sections": [],
                    },
                ],
            }
        ]
        result = restructure_feat_pass(details)
        extra = [s for s in result["sections"] if s.get("name") == "Leads To..."]
        assert len(extra) == 1


# --- feat_extract_pass (integration) ---


class TestFeatExtractPass:
    def _make_struct(self, feat_text, name_html=""):
        feat = {
            "name": "Test Feat",
            "type": "stat_block_section",
            "subtype": "feat",
            "text": feat_text,
            "level": 1,
            "sections": [],
            "_name_html": name_html,
        }
        return {"name": "Test Feat", "type": "feat", "sections": [feat]}

    def test_extracts_traits(self):
        html = (
            '<span class="trait"><a href="/Traits.aspx?ID=54" game-obj="Traits" aonid="54">Dwarf</a></span>'
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1"><i>Core Rulebook pg. 36</i></a><br/>'
            "<hr/>You know dwarven lore."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert "traits" in feat
        assert feat["traits"][0]["name"] == "Dwarf"

    def test_extracts_valued_trait(self):
        html = (
            '<span class="trait"><a href="/Traits.aspx?ID=4" game-obj="Traits" aonid="4">Additive 1</a></span>'
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1"><i>Core Rulebook pg. 36</i></a><br/>'
            "<hr/>Some feat."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert feat["traits"][0]["name"] == "Additive"
        assert feat["traits"][0]["value"] == "1"

    def test_extracts_uncommon_trait(self):
        html = (
            '<span class="traituncommon"><a href="/Traits.aspx?ID=159" game-obj="Traits" aonid="159">Uncommon</a></span>'
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1"><i>Core Rulebook pg. 36</i></a><br/>'
            "<hr/>Desc."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert any(t["name"] == "Uncommon" for t in feat["traits"])

    def test_extracts_source(self):
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<hr/>Desc."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert len(feat["sources"]) == 1
        assert feat["sources"][0]["name"] == "Core Rulebook"
        assert feat["sources"][0]["page"] == 36

    def test_extracts_bold_fields(self):
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<b>Prerequisites</b> trained in Nature<br/>"
            "<b>Trigger</b> You fail a check<br/>"
            "<hr/>Desc."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert feat["prerequisite"] == "trained in Nature"
        assert feat["trigger"] == "You fail a check"

    def test_extracts_action_type(self):
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<hr/>Desc."
        )
        name_html = '<span class="action" title="Reaction"></span>'
        struct = self._make_struct(html, name_html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert feat["action_type"]["name"] == "Reaction"

    def test_extracts_result_blocks(self):
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<hr/>Make a check."
            "<b>Critical Success</b> Great success."
            "<b>Success</b> Normal success."
            "<b>Failure</b> Nothing happens."
            "<b>Critical Failure</b> Bad things."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert feat["critical_success"] == "Great success."
        assert feat["success"] == "Normal success."
        assert feat["failure"] == "Nothing happens."
        assert feat["critical_failure"] == "Bad things."
