"""Tests for equipment.py parse_universal rebuild functions."""

import pytest
from bs4 import BeautifulSoup

from pfsrd2.equipment import (
    _remove_supplementary_sections,
    _restructure_h1_title,
    _sidebar_filter,
    _strip_equipment_nav,
    restructure_equipment_v2_pass,
)
from universal.universal import edition_from_alternate_link
from universal.utils import (
    extract_modifier,
    extract_pfs_availability,
    extract_pfs_note,
    normalize_pfs_to_object,
    parse_section_modifiers,
    rebuilt_split_modifiers,
    split_stat_block_line,
)


# ---------------------------------------------------------------------------
# extract_modifier (moved from creatures.py)
# ---------------------------------------------------------------------------
class TestExtractModifier:
    def test_no_parens(self):
        assert extract_modifier("simple text") == ("simple text", None)

    def test_basic_modifier(self):
        text, mod = extract_modifier("longsword (magical)")
        assert text == "longsword"
        assert mod == "magical"

    def test_modifier_with_trailing_text(self):
        text, mod = extract_modifier("damage (fire) extra")
        assert text == "damage extra"
        assert mod == "fire"

    def test_empty_parens(self):
        text, mod = extract_modifier("value ()")
        assert text == "value"
        assert mod == ""


# ---------------------------------------------------------------------------
# split_stat_block_line (moved from creatures.py)
# ---------------------------------------------------------------------------
class TestSplitStatBlockLine:
    def test_simple_comma_split(self):
        assert split_stat_block_line("a, b, c") == ["a", "b", "c"]

    def test_semicolon_split(self):
        assert split_stat_block_line("a; b") == ["a", "b"]

    def test_respects_parens(self):
        result = split_stat_block_line("swim 20 (underwater only), fly 30")
        assert result == ["swim 20 (underwater only)", "fly 30"]

    def test_strips_whitespace(self):
        assert split_stat_block_line("  a , b  ") == ["a", "b"]


# ---------------------------------------------------------------------------
# rebuilt_split_modifiers (moved from creatures.py)
# ---------------------------------------------------------------------------
class TestRebuiltSplitModifiers:
    def test_no_parens(self):
        assert rebuilt_split_modifiers(["a", "b", "c"]) == ["a", "b", "c"]

    def test_rejoins_split_parens(self):
        parts = ["swim 20 (underwater", "cold)", "fly 30"]
        assert rebuilt_split_modifiers(parts) == ["swim 20 (underwater, cold)", "fly 30"]


# ---------------------------------------------------------------------------
# parse_section_modifiers (moved from creatures.py)
# ---------------------------------------------------------------------------
class TestParseSectionModifiers:
    def test_no_modifier(self):
        section = {"name": "Perception"}
        result = parse_section_modifiers(section, "name")
        assert result["name"] == "Perception"
        assert "modifiers" not in result

    def test_with_modifier(self):
        section = {"name": "Perception (darkvision)"}
        result = parse_section_modifiers(section, "name")
        assert result["name"] == "Perception"
        assert len(result["modifiers"]) == 1
        assert result["modifiers"][0]["name"] == "darkvision"


# ---------------------------------------------------------------------------
# _strip_equipment_nav
# ---------------------------------------------------------------------------
class TestStripEquipmentNav:
    def test_strips_nav_before_direct_child_hr(self):
        html = """<div id="main">
        <span><h1>Nav</h1><hr/></span>
        <span><h2>Sub Nav</h2></span>
        <hr/>
        <h1 class="title">Content</h1>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        _strip_equipment_nav(soup)
        main = soup.find(id="main")
        assert "Nav" not in main.get_text()
        assert "Sub Nav" not in main.get_text()
        assert "Content" in main.get_text()

    def test_no_hr_asserts(self):
        html = '<div id="main"><h1 class="title">Content</h1></div>'
        soup = BeautifulSoup(html, "html.parser")
        with pytest.raises(AssertionError, match="No direct-child"):
            _strip_equipment_nav(soup)


# ---------------------------------------------------------------------------
# _restructure_h1_title
# ---------------------------------------------------------------------------
class TestRestructureH1Title:
    def test_pfs_icon_with_sibling_name_link(self):
        html = """<div id="main">
        <h1 class="title"><a href="PFS.aspx"><img alt="PFS Standard"/></a></h1>
        <a href="Armor.aspx?ID=1">Padded Armor</a>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        _restructure_h1_title(main, h1)
        assert "Padded Armor" in h1.get_text()
        assert "__EQ_META:Standard:0__" in h1.get_text()

    def test_name_already_in_h1(self):
        html = """<div id="main">
        <h1 class="title"><a href="Weapons.aspx?ID=1">Dagger</a></h1>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        _restructure_h1_title(main, h1)
        assert "Dagger" in h1.get_text()
        assert "__EQ_META:Standard:0__" in h1.get_text()

    def test_plain_text_name_in_h1(self):
        html = """<div id="main">
        <h1 class="title">Ring of Truth<span style="margin-left:auto">Item 10</span></h1>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        _restructure_h1_title(main, h1)
        assert "Ring of Truth" in h1.get_text()
        assert "__EQ_META:Standard:10__" in h1.get_text()

    def test_level_inside_h1(self):
        html = """<div id="main">
        <h1 class="title">Ballista<span style="margin-left:auto; margin-right:0">Item 8</span></h1>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        _restructure_h1_title(main, h1)
        assert "__EQ_META:Standard:8__" in h1.get_text()

    def test_vehicle_level_span(self):
        html = """<div id="main">
        <h1 class="title">Raft<span style="margin-left:auto; margin-right:0">Vehicle 12</span></h1>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        _restructure_h1_title(main, h1)
        assert "Raft" in h1.get_text()
        assert "__EQ_META:Standard:12__" in h1.get_text()

    def test_negative_level(self):
        html = """<div id="main">
        <h1 class="title">Raft<span style="margin-left:auto; margin-right:0">Vehicle -1</span></h1>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        _restructure_h1_title(main, h1)
        assert "__EQ_META:Standard:-1__" in h1.get_text()

    def test_pfs_limited(self):
        html = """<div id="main">
        <h1 class="title"><a href="PFS.aspx"><img alt="PFS Limited"/></a></h1>
        <a href="Equipment.aspx?ID=1">Thingy</a>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        h1 = main.find("h1", class_="title")
        _restructure_h1_title(main, h1)
        assert "__EQ_META:Limited:0__" in h1.get_text()


# ---------------------------------------------------------------------------
# _remove_supplementary_sections
# ---------------------------------------------------------------------------
class TestRemoveSupplementarySections:
    def test_removes_traits_section(self):
        html = """<div id="main">
        <b>Price</b> 5 gp
        <h2 class="title">Traits</h2>
        <div class="trait-entry">Comfort: ...</div>
        <h2 class="title">Armor Specialization Effects</h2>
        <b>Source</b> Core Rulebook
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        _remove_supplementary_sections(main)
        assert "5 gp" in main.get_text()
        assert "Comfort" not in main.get_text()
        assert "Specialization" not in main.get_text()

    def test_keeps_variant_h2s(self):
        html = """<div id="main">
        <h2 class="title">Item 3</h2>
        <b>Price</b> 10 gp
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        _remove_supplementary_sections(main)
        assert "Item 3" in main.get_text()
        assert "10 gp" in main.get_text()


# ---------------------------------------------------------------------------
# _sidebar_filter
# ---------------------------------------------------------------------------
class TestSidebarFilter:
    def test_removes_sidebar_divs(self):
        html = """<div id="main">
        <div class="sidebar">Sidebar content</div>
        <p>Real content</p>
        </div>"""
        soup = BeautifulSoup(html, "html.parser")
        _sidebar_filter(soup)
        assert "Sidebar" not in soup.get_text()
        assert "Real content" in soup.get_text()


# ---------------------------------------------------------------------------
# _remove_empty_links
# ---------------------------------------------------------------------------
class TestRemoveEmptyLinks:
    def test_removes_empty_anchors(self):
        from pfsrd2.equipment import _remove_empty_links

        html = '<div id="main"><a></a><a>  </a><a><img src="x"/></a><a href="x">Real</a></div>'
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        _remove_empty_links(main)
        anchors = main.find_all("a")
        assert len(anchors) == 2
        texts = [a.get_text(strip=True) for a in anchors]
        assert "Real" in texts

    def test_removes_empty_pfs_links(self):
        from pfsrd2.equipment import _remove_empty_links

        html = '<div id="main"><a href="PFS.aspx"></a><a href="PFS.aspx">PFS Note</a></div>'
        soup = BeautifulSoup(html, "html.parser")
        main = soup.find(id="main")
        _remove_empty_links(main)
        anchors = main.find_all("a")
        # Empty PFS link removed, PFS Note link kept
        assert len(anchors) == 1
        assert "PFS Note" in anchors[0].get_text()


# ---------------------------------------------------------------------------
# extract_pfs_availability
# ---------------------------------------------------------------------------
class TestExtractPfsAvailability:
    def test_no_img_returns_standard(self):
        bs = BeautifulSoup("<b>Source</b> Core", "html.parser")
        assert extract_pfs_availability(bs) == "Standard"

    def test_extracts_standard(self):
        bs = BeautifulSoup('<img alt="PFS Standard" src="x.png"/>', "html.parser")
        assert extract_pfs_availability(bs) == "Standard"
        assert bs.find("img") is None  # img removed

    def test_extracts_limited(self):
        bs = BeautifulSoup('<img alt="PFS Limited" src="x.png"/>', "html.parser")
        assert extract_pfs_availability(bs) == "Limited"

    def test_extracts_restricted(self):
        bs = BeautifulSoup('<img alt="PFS Restricted" src="x.png"/>', "html.parser")
        assert extract_pfs_availability(bs) == "Restricted"

    def test_cleans_empty_parent_wrapper(self):
        bs = BeautifulSoup(
            '<a href="PFS.aspx"><span><img alt="PFS Standard"/></span></a>', "html.parser"
        )
        extract_pfs_availability(bs)
        assert bs.find("a") is None  # empty wrapper removed
        assert bs.find("span") is None

    def test_asserts_on_invalid_availability(self):
        bs = BeautifulSoup('<img alt="PFS Exclusive" src="x.png"/>', "html.parser")
        with pytest.raises(AssertionError, match="Unknown PFS availability"):
            extract_pfs_availability(bs)


# ---------------------------------------------------------------------------
# normalize_pfs_to_object
# ---------------------------------------------------------------------------
class TestNormalizePfsToObject:
    def test_converts_string(self):
        struct = {"pfs": "Limited"}
        normalize_pfs_to_object(struct)
        assert struct["pfs"]["availability"] == "Limited"
        assert struct["pfs"]["type"] == "stat_block_section"

    def test_noop_on_dict(self):
        obj = {"type": "stat_block_section", "subtype": "pfs", "availability": "Standard"}
        struct = {"pfs": obj}
        normalize_pfs_to_object(struct)
        assert struct["pfs"] is obj  # same object, not replaced

    def test_asserts_on_none(self):
        struct = {}
        with pytest.raises(AssertionError, match="must be set"):
            normalize_pfs_to_object(struct)


# ---------------------------------------------------------------------------
# extract_pfs_note
# ---------------------------------------------------------------------------
class TestExtractPfsNote:
    def test_extracts_note(self):
        html = '<u><a href="PFS.aspx"><b><i>PFS Note</i></b></a></u> All Pathfinders have access.<br><br><b>Price</b>'
        bs = BeautifulSoup(html, "html.parser")
        struct = {"pfs": "Standard"}
        extract_pfs_note(bs, struct)
        assert isinstance(struct["pfs"], dict)
        assert struct["pfs"]["availability"] == "Standard"
        assert struct["pfs"]["note"] == "All Pathfinders have access."
        # NavigableString note text should be removed from soup
        assert "All Pathfinders" not in bs.get_text()

    def test_no_pfs_note(self):
        html = "<b>Source</b> Core Rulebook<br><b>Price</b> 5 gp"
        bs = BeautifulSoup(html, "html.parser")
        struct = {"pfs": "Standard"}
        extract_pfs_note(bs, struct)
        # pfs stays as string when no note found
        assert struct["pfs"] == "Standard"

    def test_stops_at_hr(self):
        html = '<u><a href="PFS.aspx"><b><i>PFS Note</i></b></a></u> Note text.<br><hr>Description here.'
        bs = BeautifulSoup(html, "html.parser")
        struct = {"pfs": "Limited"}
        extract_pfs_note(bs, struct)
        assert struct["pfs"]["note"] == "Note text."
        assert struct["pfs"]["availability"] == "Limited"
        # Description should remain in soup
        assert "Description here" in bs.get_text()

    def test_strips_leading_colon(self):
        html = '<u><a href="PFS.aspx"><b><i>PFS Note</i></b></a></u>: Note with colon.<br><br>'
        bs = BeautifulSoup(html, "html.parser")
        struct = {"pfs": "Standard"}
        extract_pfs_note(bs, struct)
        assert struct["pfs"]["note"] == "Note with colon."

    def test_preserves_pfs_availability(self):
        html = '<u><a href="PFS.aspx"><b><i>PFS Note</i></b></a></u> Restricted note<br><br>'
        bs = BeautifulSoup(html, "html.parser")
        struct = {"pfs": "Restricted"}
        extract_pfs_note(bs, struct)
        assert struct["pfs"]["availability"] == "Restricted"

    def test_asserts_on_missing_u_wrapper(self):
        html = "<b><i>PFS Note</i></b> orphan note"
        bs = BeautifulSoup(html, "html.parser")
        struct = {"pfs": "Standard"}
        with pytest.raises(AssertionError, match="expected <u> wrapper"):
            extract_pfs_note(bs, struct)


# ---------------------------------------------------------------------------
# edition_from_alternate_link - list handling
# ---------------------------------------------------------------------------
class TestEditionFromAlternateLinkList:
    def test_single_dict(self):
        struct = {"alternate_link": {"alternate_type": "remastered"}}
        assert edition_from_alternate_link(struct) == "legacy"

    def test_list_with_consistent_types(self):
        struct = {
            "alternate_link": [
                {"alternate_type": "remastered"},
                {"alternate_type": "remastered"},
            ]
        }
        assert edition_from_alternate_link(struct) == "legacy"

    def test_list_with_conflicting_types_asserts(self):
        struct = {
            "alternate_link": [
                {"alternate_type": "remastered"},
                {"alternate_type": "legacy"},
            ]
        }
        with pytest.raises(AssertionError, match="Conflicting"):
            edition_from_alternate_link(struct)

    def test_no_alternate_link(self):
        assert edition_from_alternate_link({}) is None


# ---------------------------------------------------------------------------
# restructure_equipment_v2_pass
# ---------------------------------------------------------------------------
class TestRestructureEquipmentV2Pass:
    def test_basic_restructure(self):
        details = [
            {
                "type": "section",
                "name": "__EQ_META:Standard:5__ Longsword",
                "text": '<a aonid="1" game-obj="Weapons">Longsword</a><b>Source</b> Core',
                "sections": [],
            }
        ]
        struct = restructure_equipment_v2_pass(details, "weapon")
        assert struct["name"] == "Longsword"
        assert struct["pfs"] == "Standard"
        assert struct["type"] == "weapon"
        sb = struct["sections"][0]
        assert sb["level"] == 5
        assert sb["type"] == "stat_block"
        assert sb["subtype"] == "weapon"

    def test_negative_level(self):
        details = [
            {
                "type": "section",
                "name": "__EQ_META:Standard:-1__ Raft",
                "text": '<a aonid="77" game-obj="Vehicles">Raft</a><b>Source</b> GM Core',
                "sections": [],
            }
        ]
        struct = restructure_equipment_v2_pass(details, "vehicle")
        assert struct["name"] == "Raft"
        sb = struct["sections"][0]
        assert sb["level"] == -1

    def test_missing_meta_prefix_asserts(self):
        details = [{"type": "section", "name": "No Prefix", "text": "", "sections": []}]
        with pytest.raises(AssertionError, match="__EQ_META__"):
            restructure_equipment_v2_pass(details, "armor")
