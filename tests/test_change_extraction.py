from bs4 import BeautifulSoup

from pfsrd2.change_extraction import (
    extract_inline_abilities,
    parse_ability_nodes,
    parse_adjustments_table,
    parse_change,
)


def _make_li(html):
    """Wrap HTML in <li> and return the Tag."""
    bs = BeautifulSoup(f"<li>{html}</li>", "html.parser")
    return bs.find("li")


class TestParseChange:
    def test_extracts_text(self):
        li = _make_li("Add the undead trait.")
        change = parse_change(li)
        assert "Add the undead trait." in change["text"]
        assert change["type"] == "stat_block_section"
        assert change["subtype"] == "change"

    def test_extracts_links(self):
        li = _make_li('Add the <a href="/Traits.aspx?ID=1">undead</a> trait.')
        change = parse_change(li)
        assert "links" in change
        assert len(change["links"]) == 1
        assert change["links"][0]["name"] == "undead"

    def test_strips_leading_trailing_br(self):
        li = _make_li("<br/>Add the undead trait.<br/>")
        change = parse_change(li)
        assert not change["text"].startswith("<br")
        assert not change["text"].endswith("<br/>")

    def test_removes_empty_name(self):
        li = _make_li("Some change text.")
        change = parse_change(li)
        assert "name" not in change

    def test_extracts_abilities_when_following_present(self):
        li = _make_li(
            "Add the following abilities: "
            "<b>Grab</b> The creature grabs.<br/>"
            "<b>Push</b> The creature pushes."
        )
        change = parse_change(li)
        assert "abilities" in change
        assert len(change["abilities"]) == 2
        assert change["abilities"][0]["name"] == "Grab"


class TestExtractInlineAbilities:
    def test_extracts_abilities_delimited_by_br(self):
        html = (
            "<div>Some intro text. <b>Grab</b> The creature grabs.<br/><b>Push</b> It pushes.</div>"
        )
        bs = BeautifulSoup(html, "html.parser")
        div = bs.find("div")
        abilities = extract_inline_abilities(div)
        assert abilities is not None
        assert len(abilities) == 2
        assert abilities[0]["name"] == "Grab"
        assert abilities[1]["name"] == "Push"

    def test_returns_none_when_no_bold(self):
        html = "<div>Some text without any bold elements.</div>"
        bs = BeautifulSoup(html, "html.parser")
        div = bs.find("div")
        abilities = extract_inline_abilities(div)
        assert abilities is None

    def test_linked_ability_pattern(self):
        """parse_ability_nodes handles <a><b>Name</b></a> when passed directly."""
        html = '<a href="/Abilities.aspx?ID=1"><b>Grab</b></a> The creature grabs.'
        bs = BeautifulSoup(html, "html.parser")
        nodes = list(bs.children)
        abilities = parse_ability_nodes(nodes)
        assert abilities is not None
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Grab"
        assert "link" in abilities[0]

    def test_action_type_extraction(self):
        html = (
            '<div><b>Breath Weapon</b> <span class="action" title="Two Actions">aa</span>'
            " The dragon breathes fire.</div>"
        )
        bs = BeautifulSoup(html, "html.parser")
        div = bs.find("div")
        abilities = extract_inline_abilities(div)
        assert abilities is not None
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Breath Weapon"
        assert "action_type" in abilities[0]
        assert abilities[0]["action_type"]["name"] == "Two Actions"


class TestParseAdjustmentsTable:
    def test_parses_html_table(self):
        html = """
        <table>
            <tr><th>Starting Level</th><th>HP Adjustment</th></tr>
            <tr><td>2-4</td><td>10</td></tr>
            <tr><td>5+</td><td>20</td></tr>
        </table>
        """
        result = parse_adjustments_table(html)
        assert result is not None
        assert len(result) == 2
        assert result[0]["starting_level"] == "2-4"
        assert result[0]["hp_adjustment"] == "10"
        assert result[1]["starting_level"] == "5+"

    def test_parses_markdown_table(self):
        text = """
| Starting Level | HP |
| --- | --- |
| 1-3 | 5 |
| 4-6 | 15 |
"""
        result = parse_adjustments_table(text)
        assert result is not None
        assert len(result) == 2
        assert result[0]["starting_level"] == "1-3"
        assert result[0]["hp"] == "5"

    def test_returns_none_for_insufficient_rows(self):
        html = "<table><tr><th>Level</th></tr></table>"
        result = parse_adjustments_table(html)
        assert result is None

    def test_returns_none_for_short_markdown(self):
        text = "| Level |\n| --- |"
        result = parse_adjustments_table(text)
        assert result is None
