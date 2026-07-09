from bs4 import BeautifulSoup

from pfsrd2.change_extraction import (
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

    def test_ability_prose_removed_from_change_text(self):
        li = _make_li(
            "Add the following abilities: "
            "<b>Grab</b> The creature grabs.<br/>"
            "<b>Push</b> The creature pushes."
        )
        change = parse_change(li)
        assert "Add the following abilities:" in change["text"]
        assert "The creature grabs" not in change["text"]
        assert "Grab" not in change["text"]
        assert "Push" not in change["text"]

    def test_unparsed_plain_links_stay_in_text(self):
        # zombie.json pattern: Darkvision/Negative Healing are plain <a>
        # links the ability parser cannot capture — they must survive in
        # the change text (and links) or the grants vanish entirely.
        li = _make_li(
            "Add the following abilities.  "
            '<a href="x" game-obj="MonsterAbilities" aonid="12">Darkvision</a><br/>'
            '<a href="x" game-obj="MonsterAbilities" aonid="42">Negative Healing</a><br/>'
            "<b>Slow</b> A zombie is permanently slowed 1."
        )
        change = parse_change(li)
        assert "abilities" in change
        assert [a["name"] for a in change["abilities"]] == ["Slow"]
        assert "Darkvision" in change["text"]
        assert "Negative Healing" in change["text"]
        assert "permanently slowed" not in change["text"]

    def test_lead_in_line_stays_in_text(self):
        li = _make_li(
            "Add the following abilities: "
            "<b>Grab</b> The creature grabs.<br/>"
            "To make one with this ability, do the following.<br/>"
            "<b>Push</b> The creature pushes."
        )
        change = parse_change(li)
        assert [a["name"] for a in change["abilities"]] == ["Grab", "Push"]
        assert "To make one with this ability" in change["text"]


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
