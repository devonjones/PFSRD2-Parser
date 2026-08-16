"""Continuation-line handling in _split_nodes (PR #133 review round)."""

from bs4 import BeautifulSoup

from universal.ability import parse_abilities_from_nodes


def _nodes(html):
    return list(BeautifulSoup(html, "html.parser").children)


class TestContinuationLines:
    def test_continuation_paragraph_glues_to_ability(self):
        # Power Surge: <br><br> continuation carries level scaling
        html = (
            "<b>Power Surge</b> Deals 1d6 additional damage.<br/><br/>"
            "This additional damage increases to 2d6 at 9th level."
        )
        abilities = parse_abilities_from_nodes(_nodes(html))
        assert len(abilities) == 1
        assert "increases to 2d6" in abilities[0]["text"]
        # single-space join, no doubled spaces
        assert "  " not in abilities[0]["text"]

    def test_lead_in_for_next_ability_does_not_glue_backward(self):
        # Dragon alternates: the lead-in introduces the NEXT ability and
        # already lives in the sections text — never append to the previous
        html = (
            "<b>Old Power</b> Does a thing.<br/><br/>"
            "To make a dragon with this ability, replace Old Power with "
            "the following.<br/>"
            "<b>New Power</b> Does a new thing."
        )
        abilities = parse_abilities_from_nodes(_nodes(html))
        names = [a["name"] for a in abilities]
        assert names == ["Old Power", "New Power"]
        assert "replace Old Power" not in abilities[0]["text"]

    def test_continuation_never_reopens_addon_entries(self):
        # prose after an addon line must not be absorbed into the addon value
        html = (
            "<b>Venom</b> Poison bite.<br/>"
            "<b>Frequency</b> once per day<br/>"
            "Loose prose that must not join the frequency value."
        )
        abilities = parse_abilities_from_nodes(_nodes(html))
        assert abilities[0].get("frequency") == "once per day"

    def test_excluded_label_value_does_not_glue(self):
        html = "<b>Slam</b> Hits hard.<br/>" "<b>Source</b> <i>Bestiary pg. 5</i>"
        abilities = parse_abilities_from_nodes(_nodes(html))
        assert "Bestiary" not in abilities[0]["text"]


class TestTemplateUnclaimedNodesFailLoudly:
    """A template's unclaimed ability nodes are dropped, so they must assert.

    collect_ability_nodes EXTRACTS its nodes from the tree, and
    monster_template writes str(bs) back over the section text — so anything
    the ability parser does not claim is gone from the output with nothing
    said. monster_family is not exposed to this: it parses a COPY and never
    reassigns section["text"].

    PFSRD2-Parser-4bcm proposed putting the unclaimed nodes back. Measured
    across all 55 templates, the only unclaimed nodes are the <br/> separators
    between abilities, so restoring them would render as stray hard breaks and
    fix nothing. The guard is the useful half.
    """

    def _extract(self, html):
        from bs4 import BeautifulSoup

        from pfsrd2.monster_template import _extract_abilities_from_bs

        return _extract_abilities_from_bs(BeautifulSoup(html, "html.parser"))

    def test_separators_alone_are_not_a_failure(self):
        # The shape every real template is in today: <br/> between abilities,
        # nothing else unclaimed. This must stay quiet or the guard is useless.
        abilities = self._extract(
            "<b>Grab</b> The creature grabs.<br/><br/>"
            "<b>Constrict</b> The creature squeezes.<br/>"
        )
        assert [a["name"] for a in abilities] == ["Grab", "Constrict"]

    def test_unclaimed_prose_fails_instead_of_vanishing(self):
        # The shape 4bcm was filed for: _split_nodes blocks the continuation
        # branch after a degree label, so this paragraph is claimed by nothing
        # and would be dropped silently. No template is in this shape today —
        # the guard is here so that stays true.
        import pytest

        with pytest.raises(AssertionError, match="about to be dropped"):
            self._extract(
                "<b>Big Attack</b> The dragon breathes.<br/>"
                "<b>Success</b> Half damage.<br/>"
                "This trailing paragraph belongs to Big Attack and lives nowhere else."
            )
