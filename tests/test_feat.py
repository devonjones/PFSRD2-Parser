"""Unit tests for feat.py helper functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.feat import (
    _attach_archetype_note,
    _clean_html_fields,
    _convert_feat_text,
    _detect_archetype_level,
    _extract_action_type,
    _extract_archetypes,
    _extract_bold_fields,
    _extract_bold_fields_from_bs,
    _extract_called_actions_from_section,
    _extract_result_blocks,
    _extract_source_from_bs,
    _extract_trailing_sections,
    _parse_called_action,
    _promote_feat_fields,
    feat_extract_pass,
    feat_link_pass,
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


# --- _extract_bold_fields_from_bs ---


class TestExtractBoldFieldsFromBs:
    def test_extracts_and_removes_from_bs(self):
        html = "Some description.<b>Special</b> You can take this feat multiple times."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_bold_fields_from_bs(section, bs)
        assert section["special"] == "You can take this feat multiple times."
        assert "Special" not in str(bs)
        assert "You can take this feat multiple times" not in str(bs)
        assert "Some description." in str(bs)

    def test_multiple_fields_removed(self):
        html = "Desc.<b>Trigger</b> An enemy strikes you.<br/><b>Requirement</b> You are wielding a shield."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_bold_fields_from_bs(section, bs)
        assert section["trigger"] == "An enemy strikes you."
        assert section["requirement"] == "You are wielding a shield."
        remaining = str(bs).strip()
        assert "Trigger" not in remaining
        assert "Requirement" not in remaining

    def test_preserves_non_matching_bold(self):
        html = "<b>Note</b> some text<b>Special</b> You can select this twice."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_bold_fields_from_bs(section, bs)
        assert section["special"] == "You can select this twice."
        assert "<b>Note</b>" in str(bs)


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

    def test_extracts_trigger_and_requirements(self):
        html = (
            '<div class="calledAction">'
            '<h3 class="title"><a href="Actions.aspx?ID=3" game-obj="Actions" aonid="3">Reactive Strike</a></h3>'
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1"><i>Core Rulebook pg. 84</i></a>'
            "<b>Trigger</b> A creature within your reach uses a manipulate action.<br/>"
            "<b>Requirements</b> You aren't fatigued."
            "<hr/>"
            "You lash out at a foe that leaves an opening."
            "</div>"
        )
        div = self._make_div(html)
        ability = _parse_called_action(div)
        assert ability["name"] == "Reactive Strike"
        assert ability["trigger"] == "A creature within your reach uses a manipulate action."
        assert ability["requirement"] == "You aren't fatigued."
        assert ability["text"] == "You lash out at a foe that leaves an opening."
        assert "Trigger" not in ability.get("text", "")

    def test_extracts_frequency(self):
        html = (
            '<div class="calledAction">'
            '<h3 class="title"><a href="Actions.aspx?ID=755" game-obj="Actions" aonid="755">Spellstrike</a></h3>'
            "<b>Frequency</b> until recharged (see below)"
            "<hr/>"
            "You channel a spell into an attack."
            "</div>"
        )
        div = self._make_div(html)
        ability = _parse_called_action(div)
        assert ability["frequency"] == "until recharged (see below)"
        assert ability["text"] == "You channel a spell into an attack."


# --- _extract_trailing_sections ---


class TestExtractTrailingSections:
    def test_extracts_leads_to_section(self):
        html = (
            'Description text.'
            '<h2 class="title">Test Feat Leads To...</h2>'
            '<u><a href="Feats.aspx?ID=100">Other Feat</a></u>'
        )
        bs = BeautifulSoup(html, "html.parser")
        struct = {"sections": []}
        _extract_trailing_sections(struct, bs)
        assert len(struct["sections"]) == 1
        assert struct["sections"][0]["name"] == "Test Feat Leads To..."
        assert "Other Feat" in struct["sections"][0]["text"]
        assert "Leads To" not in str(bs)
        assert "Description text." in str(bs)

    def test_extracts_traits_section_and_drops_it(self):
        """Traits h2 sections are extracted but dropped (name == 'Traits')."""
        html = (
            'Description.'
            '<h2 class="title">Traits</h2>'
            '<div class="trait-entry"><b>Archetype:</b> <p>This feat belongs to an archetype.</p></div>'
        )
        bs = BeautifulSoup(html, "html.parser")
        struct = {"sections": []}
        _extract_trailing_sections(struct, bs)
        # Traits sections are dropped entirely
        assert len(struct["sections"]) == 0
        assert "Traits" not in str(bs)
        assert "trait-entry" not in str(bs)

    def test_extracts_multiple_h2_sections(self):
        """Leads To is kept, Traits is dropped."""
        html = (
            'Desc.'
            '<h2 class="title">Leads To...</h2>links'
            '<h2 class="title">Traits</h2>'
            '<div class="trait-entry"><b>X:</b> <p>Y</p></div>'
        )
        bs = BeautifulSoup(html, "html.parser")
        struct = {"sections": []}
        _extract_trailing_sections(struct, bs)
        assert len(struct["sections"]) == 1
        assert struct["sections"][0]["name"] == "Leads To..."
        assert "Desc." in str(bs)

    def test_no_h2_is_noop(self):
        html = "Just normal text."
        bs = BeautifulSoup(html, "html.parser")
        struct = {"sections": []}
        _extract_trailing_sections(struct, bs)
        assert len(struct["sections"]) == 0


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

    def test_extracts_post_hr_special(self):
        """Special field appearing after <hr> in description text."""
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<hr/>You gain a benefit."
            "<b>Special</b> You can take this feat multiple times."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert feat["special"] == "You can take this feat multiple times."
        assert "Special" not in feat["text"]

    def test_extracts_post_hr_trigger_and_requirement(self):
        """Trigger and Requirement appearing after <hr> in description text."""
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<hr/>Description text."
            "<b>Trigger</b> An enemy hits you."
            "<b>Requirement</b> You have a shield raised."
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        assert feat["trigger"] == "An enemy hits you."
        assert feat["requirement"] == "You have a shield raised."
        assert "Trigger" not in feat["text"]

    def test_calledaction_extracted_before_bold_fields(self):
        """calledAction div with bold fields shouldn't leak into feat fields."""
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<hr/>Description."
            "<b>Special</b> You can't select another dedication feat."
            '<div class="calledAction">'
            '<h3 class="title"><a href="Actions.aspx?ID=3" game-obj="Actions" aonid="3">Rage</a></h3>'
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1"><i>Core Rulebook pg. 84</i></a>'
            "<b>Requirements</b> You aren't fatigued.<hr/>"
            "You gain temporary HP."
            "</div>"
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        # Special should be the feat's special, not include calledAction content
        assert feat["special"] == "You can't select another dedication feat."
        # calledAction should be extracted as ability
        assert "abilities" in feat
        assert feat["abilities"][0]["name"] == "Rage"
        # Requirements from calledAction should NOT be on the feat
        assert "requirement" not in feat

    def test_trailing_h2_sections_extracted(self):
        """h2 Leads To is extracted, Traits is dropped."""
        html = (
            '<b>Source</b> <a href="Sources.aspx?ID=1" game-obj="Sources" aonid="1">'
            "<i>Core Rulebook pg. 36</i></a><br/>"
            "<hr/>Description."
            '<h2 class="title">Test Leads To...</h2>'
            '<u><a href="Feats.aspx?ID=100">Other Feat</a></u>'
            '<h2 class="title">Traits</h2>'
            '<div class="trait-entry"><b>Archetype:</b> <p>Belongs to archetype.</p></div>'
        )
        struct = self._make_struct(html)
        feat_extract_pass(struct)
        feat = find_feat(struct)
        # h2 sections should not be in feat text
        assert "Leads To" not in feat["text"]
        assert "trait-entry" not in feat["text"]
        # Leads To is kept, Traits is dropped
        extra_names = [s["name"] for s in struct["sections"] if s.get("type") == "section"]
        assert "Test Leads To..." in extra_names
        assert "Traits" not in extra_names


# --- _extract_archetypes ---


class TestExtractArchetypes:
    def test_single_archetype_with_link(self):
        html = '<b>Archetype</b> <u><a href="Archetypes.aspx?ID=47" game-obj="Archetypes" aonid="47">Archer</a></u><br/>'
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_archetypes(section, bs)
        assert len(section["archetype"]) == 1
        assert section["archetype"][0]["name"] == "Archer"
        assert section["archetype"][0]["type"] == "feat_archetype"
        assert section["archetype"][0]["link"]["game-obj"] == "Archetypes"
        assert section["archetype"][0]["link"]["aonid"] == 47
        assert "Archetype" not in str(bs)

    def test_multiple_archetypes(self):
        html = (
            '<b>Archetypes</b> '
            '<u><a href="Archetypes.aspx?ID=238" game-obj="Archetypes" aonid="238">Archer</a></u>, '
            '<u><a href="Archetypes.aspx?ID=121" game-obj="Archetypes" aonid="121">Sniping Duo</a></u><br/>'
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_archetypes(section, bs)
        assert len(section["archetype"]) == 2
        assert section["archetype"][0]["name"] == "Archer"
        assert section["archetype"][1]["name"] == "Sniping Duo"

    def test_star_marker_detected(self):
        html = '<b>Archetype</b> <u><a href="Archetypes.aspx?ID=47" game-obj="Archetypes" aonid="47">Archer</a></u>*<br/>'
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_archetypes(section, bs)
        assert section["archetype"][0].get("star") is True

    def test_star_with_inline_note(self):
        html = (
            '<b>Archetype</b> '
            '<u><a href="Archetypes.aspx?ID=47" game-obj="Archetypes" aonid="47">Archer</a></u>*'
            '<br/>* This archetype offers Assisting Shot at a different level than displayed here.'
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_archetypes(section, bs)
        assert len(section["archetype"]) == 1
        arch = section["archetype"][0]
        assert arch["name"] == "Archer"
        assert "note" in arch
        assert "This archetype offers" in arch["note"]
        assert "star" not in arch  # star removed after note attached

    def test_multiple_starred_with_note(self):
        html = (
            '<b>Archetypes</b> '
            '<u><a href="Archetypes.aspx?ID=238" game-obj="Archetypes" aonid="238">Archer</a></u>*, '
            '<u><a href="Archetypes.aspx?ID=121" game-obj="Archetypes" aonid="121">Sniping Duo</a></u>*'
            '<br/>* This archetype offers Assisting Shot at a different level than displayed here.'
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_archetypes(section, bs)
        assert len(section["archetype"]) == 2
        for arch in section["archetype"]:
            assert "note" in arch
            assert "star" not in arch

    def test_no_archetype_is_noop(self):
        html = "<b>Prerequisites</b> trained in Nature"
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_archetypes(section, bs)
        assert "archetype" not in section

    def test_removes_nodes_from_bs(self):
        html = (
            'Before.<b>Archetype</b> '
            '<u><a href="Archetypes.aspx?ID=47" game-obj="Archetypes" aonid="47">Archer</a></u><br/>'
            'After.'
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_archetypes(section, bs)
        remaining = str(bs)
        assert "Before." in remaining
        assert "Archetype" not in remaining
        assert "Archer" not in remaining


# --- _attach_archetype_note ---


class TestAttachArchetypeNote:
    def test_extracts_note_from_requirement(self):
        section = {
            "archetype": [
                {"name": "Archer", "type": "feat_archetype", "star": True},
            ],
            "requirement": "You are wielding a ranged weapon. \n* This archetype offers it at a different level.",
        }
        _attach_archetype_note(section)
        assert section["archetype"][0]["note"] == "This archetype offers it at a different level."
        assert "star" not in section["archetype"][0]
        assert section["requirement"] == "You are wielding a ranged weapon."

    def test_skips_when_note_already_present(self):
        section = {
            "archetype": [
                {"name": "Archer", "type": "feat_archetype", "star": True, "note": "Already set"},
            ],
            "requirement": "Some text * This archetype offers stuff.",
        }
        _attach_archetype_note(section)
        assert section["archetype"][0]["note"] == "Already set"
        # requirement not modified
        assert "This archetype" in section["requirement"]

    def test_no_archetypes_is_noop(self):
        section = {"requirement": "some text * This archetype offers stuff."}
        _attach_archetype_note(section)
        assert "archetype" not in section

    def test_does_not_scan_text_field(self):
        """Should not scan the 'text' description field for notes."""
        section = {
            "archetype": [
                {"name": "Test", "type": "feat_archetype", "star": True},
            ],
            "text": "Long description with * This archetype offers something.",
        }
        _attach_archetype_note(section)
        # text field should NOT be scanned, so no note added
        assert "note" not in section["archetype"][0]

    def test_attaches_to_all_when_none_starred(self):
        section = {
            "archetype": [
                {"name": "Archer", "type": "feat_archetype"},
                {"name": "Sniping Duo", "type": "feat_archetype"},
            ],
            "prerequisite": "expert in Stealth * This version offers it differently.",
        }
        _attach_archetype_note(section)
        for arch in section["archetype"]:
            assert "note" in arch


# --- _extract_result_blocks (break on non-result bold) ---


class TestExtractResultBlocksBreakOnBold:
    def test_breaks_on_non_result_bold(self):
        """Success should not absorb Special's content."""
        html = (
            "<b>Success</b> You succeed at the check."
            "<b>Special</b> You can take this feat multiple times."
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_result_blocks(section, bs)
        assert section["success"] == "You succeed at the check."
        # Special should remain in BS for bold field extraction
        assert "Special" in str(bs)
        assert "special" not in section

    def test_all_results_with_trailing_special(self):
        html = (
            "<b>Critical Success</b> Great."
            "<b>Success</b> Good."
            "<b>Failure</b> Bad."
            "<b>Critical Failure</b> Terrible."
            "<b>Special</b> Can take multiple times."
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        _extract_result_blocks(section, bs)
        assert section["critical_success"] == "Great."
        assert section["success"] == "Good."
        assert section["failure"] == "Bad."
        assert section["critical_failure"] == "Terrible."
        assert "Special" in str(bs)


# --- _parse_called_action h2 extraction ---


class TestParseCalledActionH2:
    def _make_div(self, html):
        bs = BeautifulSoup(html, "html.parser")
        return bs.find("div")

    def test_extracts_h2_section(self):
        html = (
            '<div class="calledAction">'
            '<h3 class="title"><a href="Actions.aspx?ID=755" game-obj="Actions" aonid="755">Spellstrike</a></h3>'
            "<hr/>"
            "You channel a spell."
            '<h2 class="title">Spellstrike Specifics</h2>'
            "Details about spellstrike."
            "</div>"
        )
        div = self._make_div(html)
        ability = _parse_called_action(div)
        assert ability["name"] == "Spellstrike"
        assert "You channel a spell." in ability["text"]
        assert len(ability["sections"]) == 1
        assert ability["sections"][0]["name"] == "Spellstrike Specifics"
        assert "Details about spellstrike." in ability["sections"][0]["text"]


# --- feat_link_pass processes abilities ---


class TestFeatLinkPassAbilities:
    def test_processes_ability_fields(self):
        """Links in ability trigger/requirement fields should be extracted."""
        struct = {
            "name": "Test Feat",
            "type": "feat",
            "sections": [
                {
                    "name": "Test Feat",
                    "type": "stat_block_section",
                    "subtype": "feat",
                    "level": 1,
                    "text": "Description text.",
                    "abilities": [
                        {
                            "type": "stat_block_section",
                            "subtype": "ability",
                            "ability_type": "called",
                            "name": "Test Action",
                            "trigger": 'A <a href="Traits.aspx?ID=1" game-obj="Traits" aonid="1">creature</a> attacks.',
                            "text": "You react.",
                            "sections": [],
                        }
                    ],
                    "sections": [],
                }
            ],
        }
        feat_link_pass(struct)
        ability = struct["sections"][0]["abilities"][0]
        # Link should be extracted and tag unwrapped
        assert "links" in ability
        assert any(l["game-obj"] == "Traits" for l in ability["links"])
        # Anchor tag should be unwrapped to plain text
        assert "<a " not in ability["trigger"]

    def test_processes_archetype_notes(self):
        """Links in archetype note fields should be extracted."""
        struct = {
            "name": "Test Feat",
            "type": "feat",
            "sections": [
                {
                    "name": "Test Feat",
                    "type": "stat_block_section",
                    "subtype": "feat",
                    "level": 1,
                    "text": "Description.",
                    "archetype": [
                        {
                            "name": "Archer",
                            "type": "feat_archetype",
                            "note": 'This <a href="Archetypes.aspx?ID=47" game-obj="Archetypes" aonid="47">archetype</a> offers it differently.',
                        }
                    ],
                    "sections": [],
                }
            ],
        }
        feat_link_pass(struct)
        arch = struct["sections"][0]["archetype"][0]
        assert "<a " not in arch["note"]
        assert "links" in arch


# --- _detect_archetype_level ---


class TestDetectArchetypeLevel:
    def test_detects_level_from_archlevel_file(self, tmp_path):
        """Creates a fake ArchLevel file and verifies detection."""
        base = tmp_path / "Feats.aspx.ID_364"
        base.write_text("base file")
        archlevel = tmp_path / "Feats.aspx.ID_364.ArchLevel_4"
        archlevel.write_text("variant")
        struct = {
            "sections": [
                {"type": "stat_block_section", "subtype": "feat", "name": "Test", "level": 2}
            ]
        }
        _detect_archetype_level(struct, str(base))
        feat = find_feat(struct)
        assert feat["archetype_level"] == 4

    def test_no_archlevel_file(self, tmp_path):
        """No ArchLevel file means no archetype_level field."""
        base = tmp_path / "Feats.aspx.ID_100"
        base.write_text("base file")
        struct = {
            "sections": [
                {"type": "stat_block_section", "subtype": "feat", "name": "Test", "level": 1}
            ]
        }
        _detect_archetype_level(struct, str(base))
        feat = find_feat(struct)
        assert "archetype_level" not in feat

    def test_extracts_correct_level_number(self, tmp_path):
        base = tmp_path / "Feats.aspx.ID_1499"
        base.write_text("base")
        archlevel = tmp_path / "Feats.aspx.ID_1499.ArchLevel_10"
        archlevel.write_text("variant")
        struct = {
            "sections": [
                {"type": "stat_block_section", "subtype": "feat", "name": "Test", "level": 8}
            ]
        }
        _detect_archetype_level(struct, str(base))
        assert find_feat(struct)["archetype_level"] == 10


# --- _convert_feat_text ---


class TestConvertFeatText:
    def test_converts_html_to_markdown(self):
        feat = {"text": "You gain a <strong>bonus</strong> to attacks."}
        _convert_feat_text(feat)
        assert "**bonus**" in feat["text"]

    def test_removes_nethys_note(self):
        feat = {"text": "<i>Note from Nethys: this is a test</i>Actual description."}
        _convert_feat_text(feat)
        assert "Note from Nethys" not in feat["text"]
        assert "Actual description" in feat["text"]

    def test_deletes_empty_text(self):
        feat = {"text": "<i>Note from Nethys: only note here</i>"}
        _convert_feat_text(feat)
        assert "text" not in feat

    def test_no_text_field_is_noop(self):
        feat = {"name": "Test"}
        _convert_feat_text(feat)
        assert "text" not in feat


# --- _promote_feat_fields ---


class TestPromoteFeatFields:
    def test_promotes_name_and_sources(self):
        feat = {
            "name": "Power Attack",
            "sources": [{"name": "Core Rulebook", "type": "source"}],
            "sections": [],
        }
        struct = {"name": "", "sections": [feat]}
        _promote_feat_fields(struct, feat)
        assert struct["name"] == "Power Attack"
        assert struct["sources"] == [{"name": "Core Rulebook", "type": "source"}]
        assert "sources" not in feat
        assert "sections" not in feat

    def test_keeps_existing_sources_if_none_in_feat(self):
        feat = {"name": "Test", "sections": []}
        struct = {"name": "", "sections": [feat], "sources": [{"name": "Existing"}]}
        _promote_feat_fields(struct, feat)
        assert struct["sources"] == [{"name": "Existing"}]

    def test_empty_sources_when_none_anywhere(self):
        feat = {"name": "Test", "sections": []}
        struct = {"name": "", "sections": [feat]}
        _promote_feat_fields(struct, feat)
        assert struct["sources"] == []


# --- _clean_html_fields ---


class TestCleanHtmlFields:
    def test_renames_html_to_text(self):
        struct = {
            "sections": [
                {"name": "Desc", "html": "<p>Content</p>", "sections": []}
            ]
        }
        _clean_html_fields(struct)
        assert struct["sections"][0]["text"] == "<p>Content</p>"
        assert "html" not in struct["sections"][0]

    def test_recursive_rename(self):
        struct = {
            "sections": [
                {
                    "name": "Outer",
                    "html": "outer html",
                    "sections": [
                        {"name": "Inner", "html": "inner html", "sections": []}
                    ],
                }
            ]
        }
        _clean_html_fields(struct)
        assert struct["sections"][0]["text"] == "outer html"
        assert struct["sections"][0]["sections"][0]["text"] == "inner html"

    def test_no_html_key_is_noop(self):
        struct = {"sections": [{"name": "Test", "text": "already text", "sections": []}]}
        _clean_html_fields(struct)
        assert struct["sections"][0]["text"] == "already text"
