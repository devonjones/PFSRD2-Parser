import pytest
from bs4 import BeautifulSoup

from pfsrd2.sql.traits import strip_nested_metadata
from universal.universal import get_links
from universal.utils import (
    content_filter,
    filter_entities,
    recursive_filter_entities,
    strip_block_tags,
)


class TestFilterEntities:
    def test_mojibake_emdash(self):
        assert filter_entities("\u00e2\u0080\u0094") == "\u2014"

    def test_mojibake_endash(self):
        assert filter_entities("\u00e2\u0080\u0093") == "\u2013"

    def test_mojibake_right_single_quote(self):
        assert filter_entities("\u00e2\u0080\u0099") == "\u2019"

    def test_mojibake_left_single_quote(self):
        assert filter_entities("\u00e2\u0080\u0098") == "\u2018"

    def test_mojibake_left_double_quote(self):
        assert filter_entities("\u00e2\u0080\u009c") == "\u201c"

    def test_mojibake_right_double_quote(self):
        assert filter_entities("\u00e2\u0080\u009d") == "\u201d"

    def test_mojibake_ellipsis(self):
        assert filter_entities("\u00e2\u0080\u00a6") == "\u2026"

    def test_mojibake_multiplication(self):
        assert filter_entities("\u00c3\u0097") == "\u00d7"

    def test_mojibake_degree(self):
        assert filter_entities("\u00c2\u00ba") == "\u00ba"

    def test_mojibake_nonbreaking_hyphen(self):
        assert filter_entities("\u00e2\u0080\u0091") == "\u2011"

    def test_percent_encoded_backslash(self):
        assert filter_entities("%5C") == "\\"

    def test_amp_entity(self):
        assert filter_entities("&amp;") == "&"

    def test_modifier_letter_apostrophe(self):
        assert filter_entities("\u00ca\u00bc") == "\u2019"

    def test_nbsp_c2a0(self):
        assert filter_entities("a\u00c2\u00a0b") == "a b"

    def test_nbsp_a0(self):
        assert filter_entities("a\u00a0b") == "a b"

    def test_html_entity_emdash(self):
        assert filter_entities("\u00e2\u20ac\u201d") == "\u2014"

    def test_html_entity_endash(self):
        assert filter_entities("\u00e2\u20ac\u201c") == "\u2013"

    def test_html_entity_right_single_quote(self):
        assert filter_entities("\u00e2\u20ac\u2122") == "\u2019"

    def test_html_entity_left_double_quote(self):
        assert filter_entities("\u00e2\u20ac\u0153") == "\u201c"

    def test_html_entity_right_double_quote(self):
        assert filter_entities("\u00e2\u20ac\u009d") == "\u201d"

    def test_newline_normalization(self):
        assert filter_entities("line one\nline two") == "line one line two"

    def test_newline_strips_surrounding_whitespace(self):
        assert filter_entities("a \n b") == "a b"


class TestRecursiveFilterEntities:
    def test_nested_dict(self):
        data = {"a": "\u00e2\u0080\u0094", "b": {"c": "\u00e2\u0080\u0093"}}
        recursive_filter_entities(data)
        assert data == {"a": "\u2014", "b": {"c": "\u2013"}}

    def test_nested_list(self):
        data = ["\u00e2\u0080\u0094", ["\u00e2\u0080\u0093"]]
        recursive_filter_entities(data)
        assert data == ["\u2014", ["\u2013"]]

    def test_mixed_structure(self):
        data = {"items": [{"name": "\u00e2\u0080\u0099test"}]}
        recursive_filter_entities(data)
        assert data == {"items": [{"name": "\u2019test"}]}

    def test_does_not_normalize_newlines(self):
        data = {"text": "line one\nline two"}
        recursive_filter_entities(data)
        assert data["text"] == "line one\nline two"

    def test_non_string_values_unchanged(self):
        data = {"count": 42, "flag": True, "empty": None}
        recursive_filter_entities(data)
        assert data == {"count": 42, "flag": True, "empty": None}


class TestGetLinks:
    """Tests for get_links in universal.py."""

    def test_extracts_game_obj_links(self):
        """Should extract links with game-obj attribute."""
        html = '<a href="Spells.aspx?ID=1" game-obj="Spells">fireball</a>'
        soup = BeautifulSoup(html, "html.parser")

        links = get_links(soup)

        assert len(links) == 1
        assert links[0]["name"] == "fireball"

    def test_extracts_non_game_obj_links(self):
        """Should extract links WITHOUT game-obj attribute (new behavior)."""
        html = '<a href="Rules.aspx?ID=123">some rule</a>'
        soup = BeautifulSoup(html, "html.parser")

        links = get_links(soup)

        assert len(links) == 1
        assert links[0]["name"] == "some rule"

    def test_excludes_pfs_links(self):
        """Should exclude PFS icon links."""
        html = (
            '<a href="PFS.aspx?ID=1">PFS Standard</a>'
            '<a href="Spells.aspx?ID=1" game-obj="Spells">fireball</a>'
        )
        soup = BeautifulSoup(html, "html.parser")

        links = get_links(soup)

        assert len(links) == 1
        assert links[0]["name"] == "fireball"

    def test_unwrap_removes_pfs_tags(self):
        """Should unwrap PFS links when unwrap=True."""
        html = '<a href="PFS.aspx?ID=1">PFS</a> text'
        soup = BeautifulSoup(html, "html.parser")

        get_links(soup, unwrap=True)

        assert soup.find("a") is None  # PFS link tag was unwrapped

    def test_mixed_links(self):
        """Should handle a mix of game-obj, non-game-obj, and PFS links."""
        html = (
            '<a href="Spells.aspx?ID=1" game-obj="Spells">fireball</a>'
            '<a href="Rules.aspx?ID=5">rule</a>'
            '<a href="PFS.aspx?ID=1">PFS</a>'
        )
        soup = BeautifulSoup(html, "html.parser")

        links = get_links(soup)

        assert len(links) == 2
        names = [l["name"] for l in links]
        assert "fireball" in names
        assert "rule" in names


class TestStripNestedMetadata:
    def test_strips_matching_version(self):
        obj = {"name": "Fire", "schema_version": 1.1}
        strip_nested_metadata(obj, 1.1)
        assert "schema_version" not in obj
        assert obj["name"] == "Fire"

    def test_assertion_on_version_mismatch(self):
        obj = {"name": "Fire", "schema_version": 2.0}
        with pytest.raises(AssertionError, match="expected 1.1"):
            strip_nested_metadata(obj, 1.1)

    def test_assertion_on_missing_version(self):
        obj = {"name": "Fire"}
        with pytest.raises(AssertionError, match="expected 1.1"):
            strip_nested_metadata(obj, 1.1)


class TestContentFilter:
    def test_strips_nav_before_hr(self):
        html = '<div id="main"><nav>Nav</nav><hr/><span><h1>Title</h1>Content</span></div>'
        soup = BeautifulSoup(html, "html.parser")
        content_filter(soup)
        main = soup.find(id="main")
        assert main.find("nav") is None
        assert main.find("hr") is None

    def test_unwraps_span_with_h1(self):
        html = '<div id="main"><span><h1>Title</h1>Content</span></div>'
        soup = BeautifulSoup(html, "html.parser")
        content_filter(soup)
        main = soup.find(id="main")
        assert main.find("h1") is not None
        # span should be unwrapped (content accessible directly)
        assert main.find("span") is None

    def test_no_hr_does_not_crash(self):
        html = '<div id="main"><span><h1>Title</h1></span></div>'
        soup = BeautifulSoup(html, "html.parser")
        content_filter(soup)  # Should not raise

    def test_no_main_does_nothing(self):
        html = "<div>No main div</div>"
        soup = BeautifulSoup(html, "html.parser")
        content_filter(soup)  # Should not raise


class TestStripBlockTagsExtraTags:
    def test_strips_extra_tags(self):
        struct = {"text": "<u>underlined</u> normal"}
        strip_block_tags(struct, extra_tags=["u"])
        assert "<u>" not in struct["text"]
        assert "underlined" in struct["text"]

    def test_strips_nethys_search(self):
        struct = {"text": "before<nethys-search>search</nethys-search>after"}
        strip_block_tags(struct)
        assert "nethys-search" not in struct["text"]
        assert "before" in struct["text"]
        assert "after" in struct["text"]

    def test_strips_margin_left_span(self):
        struct = {"text": 'before<span style="margin-left:auto">junk</span>after'}
        strip_block_tags(struct)
        assert "junk" not in struct["text"]

    def test_strips_corrupted_tags(self):
        struct = {"text": "before<spells%6%%>corrupted</spells%6%%>after"}
        strip_block_tags(struct)
        assert "%" not in struct["text"] or "corrupted" not in struct["text"]

    def test_extra_tags_h2_h3(self):
        struct = {"text": "<h2>heading</h2><h3>sub</h3>text"}
        strip_block_tags(struct, extra_tags=["h2", "h3"])
        assert "<h2>" not in struct["text"]
        assert "<h3>" not in struct["text"]
        assert "heading" in struct["text"]
