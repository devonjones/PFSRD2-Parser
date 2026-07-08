"""Tests for prose change extraction in family creation sections.

Legacy families (pre-remaster) carry their "change its statistics" steps
as <br>-separated prose instead of a <ul> (e.g. Bestiary Lich), and both
editions bury level changes in intro sentences.
"""

from pfsrd2.monster_family import _extract_changes_from_section


def _section(text):
    return {"name": "Creating a Thing", "text": text, "sections": []}


class TestProseChanges:
    def test_br_separated_imperatives(self):
        # Bestiary Lich shape: no <ul>, imperative lines split on <br>
        s = _section(
            "A lich can be any type of spellcaster. To create a lich, follow "
            "these steps.<br/> Increase the spellcaster's level by 1 and "
            "change its statistics as follows.<br/> Increase spell DCs and "
            "spell attack roll by 2."
        )
        _extract_changes_from_section(s)
        texts = [c["text"] for c in s["changes"]]
        assert texts == [
            "Increase the spellcaster's level by 1 and change its statistics as follows.",
            "Increase spell DCs and spell attack roll by 2.",
        ]

    def test_gains_trait_line_with_link(self):
        s = _section(
            'A lich gains the <a aonid="160" game-obj="Traits">undead</a> '
            "trait and becomes evil. Liches lose all abilities that come "
            "from being a living creature."
        )
        _extract_changes_from_section(s)
        change = s["changes"][0]
        assert "undead" in change["text"]
        assert "<a" not in change["text"]
        assert change["links"][0]["name"] == "undead"

    def test_level_sentence_buried_in_intro(self):
        # Remastered Lich: level bump mid-sentence before the <ul>
        s = _section(
            "A lich can be any type of spellcaster as long as they qualify. "
            "To create a lich, increase the spellcaster's level by 1 and "
            "change their statistics as follows. <ul><li>It gains the undead "
            "trait.</li></ul>"
        )
        _extract_changes_from_section(s)
        texts = [c["text"] for c in s["changes"]]
        assert texts[0].startswith("To create a lich, increase the spellcaster's level by 1")
        # prose change precedes the <li> change (document order)
        assert "undead" in texts[1]

    def test_bold_led_ability_lines_excluded(self):
        # "<b>Change Shape</b> ..." leads with the imperative verb "Change"
        # but is an ability definition, owned by the ability parsing path.
        s = _section(
            "<b>Change Shape</b> The vampire transforms into a bat.<br/>"
            "<b>Climb Speed</b> Vampires gain a climb Speed equal to their "
            "land Speed and the sneaky trait."
        )
        _extract_changes_from_section(s)
        assert "changes" not in s

    def test_narrative_and_conditional_lines_excluded(self):
        s = _section(
            "Ministers gain additional jiang-shi abilities, as detailed "
            "below.<br/> Increase the zombie's level by 1 if you give it "
            "this ability.<br/> A lich gains the following abilities."
        )
        _extract_changes_from_section(s)
        assert "changes" not in s

    def test_flavor_gain_without_mechanics_noun_excluded(self):
        s = _section("Ghouls gain sustenance from the flesh of the dead.")
        _extract_changes_from_section(s)
        assert "changes" not in s

    def test_ul_only_section_unchanged_behavior(self):
        s = _section("<ul><li>Increase the creature's level by 1.</li></ul>")
        _extract_changes_from_section(s)
        assert len(s["changes"]) == 1
        assert s["text"] == ""
