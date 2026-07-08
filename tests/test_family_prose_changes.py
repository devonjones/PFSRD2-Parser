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
            'A siabrae gains the <a aonid="160" game-obj="Traits">undead</a> '
            "trait and becomes evil."
        )
        _extract_changes_from_section(s)
        change = s["changes"][0]
        assert "undead" in change["text"]
        assert "<a" not in change["text"]
        assert change["links"][0]["name"] == "undead"

    def test_mixed_polarity_line_splits_per_sentence(self):
        # One change per polarity — a combined gain+lose change made the
        # enrichment assign a single polarity (graveknight shipped add_item
        # Human/Humanoid from the "such as human and humanoid" lose clause).
        s = _section(
            "A graveknight gains the graveknight, undead, and unholy traits. "
            "They lose any abilities that come from being a living creature "
            "and any traits that represent their life, such as human and "
            "humanoid."
        )
        _extract_changes_from_section(s)
        texts = [c["text"] for c in s["changes"]]
        assert len(texts) == 2
        assert texts[0].startswith("A graveknight gains")
        assert texts[1].startswith("They lose")

    def test_level_sentence_inside_excluded_line(self):
        # Ghoul: the level instruction shares a line with a "following
        # steps" marker and leads with "First," — sentence-level rescue.
        s = _section(
            "You can turn a living creature into a ghoul by completing the "
            "following steps. First, increase the creature's level by 1 and "
            "change its statistics as follows."
        )
        _extract_changes_from_section(s)
        texts = [c["text"] for c in s["changes"]]
        assert texts == [
            "First, increase the creature's level by 1 and change its statistics as follows."
        ]

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


class TestTemplateProseChanges:
    def test_template_ul_intro_level_sentence(self):
        # Experimental Cryptid class: the level instruction sits in intro
        # prose before the <ul> and must become the FIRST change.
        from pfsrd2.monster_template import _try_extract_changes

        mt = {"name": "Experimental Cryptid"}
        section = {
            "name": "Experimental Cryptid Adjustments",
            "text": (
                "You can turn an existing creature into an experimental "
                "cryptid by completing the following steps. Increase the "
                "creature's level by 1 and change its statistics as follows. "
                "<ul><li>Increase the creature's AC by 1.</li></ul>"
            ),
            "sections": [],
        }
        assert _try_extract_changes(section, mt)
        texts = [c["text"] for c in mt["changes"]]
        assert texts[0].startswith("Increase the creature's level by 1")
        assert "AC by 1" in texts[1]

    def test_parenthetical_before_instruction_splits(self):
        # Legacy werecreature: "(These changes reflect a werecreature in its
        # hybrid form.) Increase the creature's level by 1..." — the split
        # must break after ".)" so the paren exclusion can't swallow the
        # level instruction (user-reported: level text on page, absent from
        # the rules).
        s = _section(
            "You can turn a living creature into a werecreature by "
            "completing the following steps. (These changes reflect a "
            "werecreature in its hybrid form.) Increase the creature's "
            "level by 1 and change its statistics as follows."
        )
        _extract_changes_from_section(s)
        texts = [c["text"] for c in s["changes"]]
        assert any(t.startswith("Increase the creature's level by 1") for t in texts)
