"""Unit tests for universal/universal.py shared functions."""

from bs4 import BeautifulSoup

from universal.universal import (
    extract_bold_fields,
    extract_result_blocks,
    extract_source_from_bs,
)

# --- extract_source_from_bs ---


class TestExtractSourceFromBs:
    def test_basic_source(self):
        html = '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 100</a>'
        bs = BeautifulSoup(html, "html.parser")
        source = extract_source_from_bs(bs)
        assert source is not None
        assert source["name"] == "Core Rulebook"
        assert source["page"] == 100

    def test_no_source_tag(self):
        html = "<i>Some italic text</i>"
        bs = BeautifulSoup(html, "html.parser")
        assert extract_source_from_bs(bs) is None

    def test_source_with_errata(self):
        html = (
            '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 50</a>'
            '<sup><a href="/Errata.aspx?ID=1">2.0</a></sup>'
        )
        bs = BeautifulSoup(html, "html.parser")
        source = extract_source_from_bs(bs)
        assert source is not None
        assert source["name"] == "Core Rulebook"
        assert "errata" in source

    def test_trailing_comma_stripped(self):
        html = (
            '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 50</a>, '
            '<b>Source</b> <a href="/Sources.aspx?ID=2">Bestiary pg. 10</a>'
        )
        bs = BeautifulSoup(html, "html.parser")
        source = extract_source_from_bs(bs)
        assert source is not None
        assert source["name"] == "Core Rulebook"
        # Comma between sources should be consumed
        remaining = str(bs)
        assert not remaining.startswith(",")

    def test_trailing_br_stripped(self):
        html = '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 50</a><br/>'
        bs = BeautifulSoup(html, "html.parser")
        source = extract_source_from_bs(bs)
        assert source is not None
        # The br should be removed
        assert "<br" not in str(bs)

    def test_source_tag_decomposed(self):
        html = '<b>Source</b> <a href="/Sources.aspx?ID=1">Core Rulebook pg. 50</a> rest'
        bs = BeautifulSoup(html, "html.parser")
        extract_source_from_bs(bs)
        assert bs.find("b") is None
        assert bs.find("a") is None

    def test_non_link_after_source_returns_none(self):
        html = "<b>Source</b> just some text"
        bs = BeautifulSoup(html, "html.parser")
        assert extract_source_from_bs(bs) is None


# --- extract_result_blocks ---


class TestExtractResultBlocks:
    def test_all_four_result_types(self):
        html = (
            "<b>Critical Success</b> You crit."
            "<b>Success</b> You succeed."
            "<b>Failure</b> You fail."
            "<b>Critical Failure</b> You crit fail."
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs)
        assert section["critical_success"] == "You crit."
        assert section["success"] == "You succeed."
        assert section["failure"] == "You fail."
        assert section["critical_failure"] == "You crit fail."

    def test_partial_results(self):
        html = "<b>Success</b> You succeed.<b>Failure</b> You fail."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs)
        assert "critical_success" not in section
        assert section["success"] == "You succeed."
        assert section["failure"] == "You fail."
        assert "critical_failure" not in section

    def test_trailing_br_stripped(self):
        html = "<b>Success</b> You succeed.<br/>"
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs)
        assert section["success"] == "You succeed."

    def test_non_result_bold_preserved_default(self):
        """Default mode: non-result bolds don't break collection."""
        html = "<b>Success</b> You get <b>Special</b> stuff.<b>Failure</b> You fail."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs)
        assert "Special" in section["success"]
        assert section["failure"] == "You fail."

    def test_break_on_any_bold(self):
        """Feat mode: any bold breaks collection."""
        html = "<b>Success</b> You get <b>Special</b> stuff.<b>Failure</b> You fail."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs, break_on_any_bold=True)
        assert "Special" not in section["success"]
        assert section["success"] == "You get"
        assert section["failure"] == "You fail."

    def test_nodes_removed_from_soup(self):
        html = "<b>Success</b> You succeed."
        bs = BeautifulSoup(html, "html.parser")
        extract_result_blocks({}, bs)
        assert str(bs).strip() == ""

    def test_no_result_labels_noop(self):
        html = "<b>Special</b> Something else."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs)
        assert section == {}


# --- extract_bold_fields ---


class TestExtractBoldFields:
    def test_basic_extraction(self):
        labels = {"Trigger", "Requirements"}
        html = "<b>Trigger</b> An enemy moves.<b>Requirements</b> You have a shield."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels)
        assert section["trigger"] == "An enemy moves."
        assert section["requirement"] == "You have a shield."

    def test_key_override_requirements(self):
        labels = {"Requirements"}
        html = "<b>Requirements</b> Something."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels)
        assert "requirement" in section
        assert "requirements" not in section

    def test_key_override_prerequisites(self):
        labels = {"Prerequisites"}
        html = "<b>Prerequisites</b> Expert in Athletics."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels)
        assert "prerequisite" in section
        assert "prerequisites" not in section

    def test_trailing_semicolon_stripped(self):
        labels = {"Trigger"}
        html = "<b>Trigger</b> Something happens;"
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels)
        assert section["trigger"] == "Something happens"

    def test_decompose_true_removes_nodes(self):
        labels = {"Trigger"}
        html = "<b>Trigger</b> An enemy moves. Remaining text."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels, decompose=True)
        assert section["trigger"] == "An enemy moves. Remaining text."
        assert str(bs).strip() == ""

    def test_decompose_false_preserves_nodes(self):
        labels = {"Trigger"}
        html = "<b>Trigger</b> An enemy moves."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels, decompose=False)
        assert section["trigger"] == "An enemy moves."
        # Nodes should still be in the soup
        assert bs.find("b") is not None

    def test_unrecognized_labels_skipped(self):
        labels = {"Trigger"}
        html = "<b>Special</b> Something.<b>Trigger</b> An event."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels)
        assert "special" not in section
        assert section["trigger"] == "An event."

    def test_empty_labels_noop(self):
        html = "<b>Trigger</b> Something."
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, set())
        assert section == {}

    def test_trailing_br_stripped(self):
        labels = {"Trigger"}
        html = "<b>Trigger</b> Something.<br/>"
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels)
        assert section["trigger"] == "Something."

    def test_multi_word_key(self):
        labels = {"Saving Throw"}
        html = "<b>Saving Throw</b> DC 25 Fortitude"
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_bold_fields(section, bs, labels)
        assert section["saving_throw"] == "DC 25 Fortitude"
