"""Unit tests for universal/universal.py shared functions."""

import pytest
from bs4 import BeautifulSoup

from universal.universal import (
    assert_every_degree_was_modelled,
    degree_effects_for,
    extract_bold_fields,
    extract_degree_effects,
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

    def test_the_extractor_sees_text_not_markup(self):
        # extract_result_blocks runs BEFORE the passes that unwrap <a> out of
        # field values, so a degree still carries its links here. The damage
        # type is routinely linked ("2d6 <a>fire</a> damage"), which no damage
        # pattern matches; feeding the extractor get_text() is what makes the
        # call position irrelevant. The stored value keeps its markup.
        html = (
            "<b>Failure</b> The creature takes 2d6 "
            '<a game-obj="Traits" aonid="1">fire</a> damage.'
        )
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs)
        assert "<a" in section["failure"], "the published value keeps its links"
        damage = section["degree_effects"][0]["damage"][0]
        assert damage["formula"] == "2d6"
        assert damage["damage_type"] == "fire"

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


class TestNodesAfterStopPredicate:
    """nodes_after is the canonical 'label's value run' walk.

    universal/ inlined the same walk in three places (PFSRD2-Parser-8fbe).
    Two now call this; the third is entangled with PFSRD2-Parser-nlf1.

    The `stop` predicate exists because extract_result_blocks cannot use the
    default: a degree's text may legitimately contain a bold that is not
    another degree, and stopping at it would truncate the degree.
    """

    def _bold(self, html):
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "html.parser").find("b")

    def test_the_default_stops_at_any_bold(self):
        from universal.utils import nodes_after

        bold = self._bold("<b>Label</b> value <b>Next</b> other")
        assert "".join(str(n) for n in nodes_after(bold)).strip() == "value"

    def test_a_predicate_lets_a_non_matching_bold_through(self):
        # The behaviour extract_result_blocks depends on: a bold inside the
        # value that is not a degree must NOT end the run.
        from universal.utils import nodes_after

        bold = self._bold("<b>Success</b> you gain <b>fire</b> resistance <b>Failure</b> no")
        run = "".join(
            str(n) for n in nodes_after(bold, stop=lambda n: n.get_text().strip() == "Failure")
        )
        assert "<b>fire</b>" in run
        assert "Failure" not in run

    def test_an_empty_string_node_does_not_end_the_run(self):
        # The inlined copies used `while node:`, and an empty NavigableString
        # is falsy — so a stray empty text node ended the run early and
        # silently truncated the value. `is not None` is the correct test.
        from bs4 import BeautifulSoup, NavigableString

        from universal.utils import nodes_after

        bs = BeautifulSoup("<b>Label</b>first<b>Next</b>", "html.parser")
        bold = bs.find("b")
        bold.insert_after(NavigableString(""))
        assert "first" in "".join(str(n) for n in nodes_after(bold))


class TestExtractResultBlocksWalksOnce:
    """The value and the extraction must describe the same nodes.

    extract_result_blocks used two separate loops, and they had already
    drifted: the value loop tested `while node:` and the extraction loop had
    no such test, so the stored value could describe less than what was
    removed from the soup. The tests below assert that equality directly
    rather than asserting the number of walks, which is not observable.
    """

    def test_the_value_describes_exactly_what_was_removed(self):
        # The invariant the single walk exists to hold. Reconstructs the old
        # divergence: a falsy NavigableString mid-run made the value stop
        # early while the extraction loop carried on removing.
        from bs4 import BeautifulSoup, NavigableString

        from universal.universal import extract_result_blocks

        bs = BeautifulSoup("<b>Success</b> first<b>Failure</b> second", "html.parser")
        bold = bs.find("b")
        bold.insert_after(NavigableString(""))
        section = {}
        extract_result_blocks(section, bs)
        # Exact equality, not containment: a truncated value is "" and every
        # truncation is a substring of the original, so `in` can never catch
        # one. An earlier version asserted containment against the whole
        # pre-extraction soup and passed with the two-loop shape restored —
        # it could not fail on the bug it is named for.
        assert section["success"] == "first"
        assert section["failure"] == "second"
        assert "first" not in str(bs), "value kept but node left in the soup"
        assert "second" not in str(bs)

    def test_a_non_degree_bold_inside_a_degree_survives_in_the_value(self):
        from bs4 import BeautifulSoup

        from universal.universal import extract_result_blocks

        bs = BeautifulSoup(
            "<b>Success</b> you gain <b>fire</b> resistance" "<b>Failure</b> you do not",
            "html.parser",
        )
        section = {}
        extract_result_blocks(section, bs)
        assert "<b>fire</b>" in section["success"]
        assert section["failure"] == "you do not"

    def test_break_on_any_bold_stops_at_the_inner_bold(self):
        from bs4 import BeautifulSoup

        from universal.universal import extract_result_blocks

        bs = BeautifulSoup("<b>Success</b> you gain <b>fire</b> resistance", "html.parser")
        section = {}
        extract_result_blocks(section, bs, break_on_any_bold=True)
        assert section["success"] == "you gain"
        assert "<b>fire</b>" in str(bs)


class TestEveryDegreeWasModelled:
    """The one failure mode in this feature that is otherwise silent.

    A new place that writes a degree, or a fixed key-list that copies degrees
    without their structure, produces output that is VALID and simply missing
    a field. Two review rounds found six such holes and none of them tripped
    anything. The guard recomputes from finished output and compares.
    """

    def _struct(self, **extra):
        return {
            "name": "Rockfall",
            "sections": [
                {
                    "name": "Rockfall",
                    "subtype": "ability",
                    "failure": "The creature takes 2d6 bludgeoning damage.",
                    **extra,
                }
            ],
        }

    def test_a_degree_whose_damage_was_never_modelled_fails(self):
        with pytest.raises(AssertionError, match="never called extract_degree_effects"):
            assert_every_degree_was_modelled(self._struct(), "creature.schema.json")

    def test_a_degree_that_was_modelled_passes(self):
        struct = self._struct()
        extract_degree_effects(struct["sections"][0])
        assert_every_degree_was_modelled(struct, "creature.schema.json")

    def test_a_degree_with_no_damage_needs_nothing(self):
        struct = {"failure": "The creature is unaffected.", "subtype": "ability"}
        assert_every_degree_was_modelled(struct, "creature.schema.json")

    def test_the_equipment_deferral_is_scoped_to_equipment(self):
        # PFSRD2-Parser-qj3v: the equipment parser has a degree-writer that
        # does not model yet. The exemption must not leak to anything else --
        # if it did, the guard would go quiet exactly where it is needed.
        struct = self._struct()
        assert_every_degree_was_modelled(struct, "equipment.schema.json")
        for other in ("creature.schema.json", "hazard.schema.json", "feat.schema.json"):
            with pytest.raises(AssertionError):
                assert_every_degree_was_modelled(struct, other)

    def test_degree_effects_for_does_not_touch_the_object(self):
        section = self._struct()["sections"][0]
        before = dict(section)
        effects = degree_effects_for(section)
        assert effects and section == before


class TestDiceTheDegreeDoesNotDeal:
    """A degree IS a save outcome, so dice carrying their OWN save are not its.

    PFSRD2-Parser-bsw3: these stay prose. Three shipped hazards were wrong --
    two claimed damage from a second, differently-gated effect, and one turned
    a per-revolution rate into a flat amount.
    """

    def _f(self, text):
        return [
            (x.get("formula"), x.get("damage_type"))
            for e in degree_effects_for({"failure": text})
            for x in e["damage"]
        ]

    def test_a_rate_is_not_an_amount(self):
        # test_of_endurance: 1d6 is per revolution, up to seven of them. The
        # bare 1d6 is the damage at exactly one revolution and nowhere else.
        assert (
            self._f(
                "The creature takes 1d6 cold damage for each revolution the wheel "
                "has been rotated (max 7d6)."
            )
            == []
        )

    def test_dice_with_their_own_save_are_dropped_and_the_degrees_own_are_kept(self):
        # wind_surge: the 20d6 is this degree's outcome; the 6d6 hits creatures
        # in the water and rolls its own DC 29.
        assert self._f(
            "The creature takes 20d6 bludgeoning damage, is pushed 45 feet along "
            "the line, is knocked prone, and is stunned 1 for 1 round.If the line "
            "overlaps a body of water, the winds cause massive waves that deal 6d6 "
            "bludgeoning damage to creatures in the water or within 15 feet of the "
            "waterline (DC 29 basic Reflex save)."
        ) == [("20d6", "bludgeoning")]

    def test_a_nested_save_inside_the_degree_drops_only_its_own_dice(self):
        # the_putrid_rise: 16d6 is the Vomit save's outcome; the 4d6 from the
        # tumble is gated behind a second DC 32.
        # the_putrid_rise, verbatim. The subject of the second sentence is "A
        # creature that falls down the steps", NOT the degree's own subject --
        # that is what separates it from gorlak's "The creature takes 2d10+9
        # ... (DC 25 basic Fortitude save)", which IS the degree's own damage.
        # A paraphrased fixture saying "The creature takes an additional 4d6"
        # made this test pass for the wrong reason and hid that distinction.
        assert self._f(
            "The creature takes 16d6 acid damage, is sickened 3, is knocked "
            "prone, and then tumbles down the stairs. A creature that falls "
            "down the steps takes an additional 4d6 bludgeoning damage "
            "(DC 32 basic Reflex save) from the tumble."
        ) == [("16d6", "acid")]

    def test_the_degrees_own_basic_save_damage_is_kept(self):
        # gorlak's Fling Foe. A basic save printed right after the dice is the
        # standard way of writing the degree's OWN damage. Dropping it published
        # degree_effects: null on all three degrees, while ran-to's Whirlwind
        # Toss -- same ability shape -- kept its damage only because the source
        # put the parenthetical further away than the window. That was the rule
        # reading layout instead of attribution.
        assert self._f(
            "The creature takes 2d10+9 piercing damage (DC 25 basic Fortitude "
            "save) as the hook rips free and is hurled 15 feet away."
        ) == [("2d10+9", "piercing")]

    def test_an_escape_dc_after_the_damage_does_not_suppress_it(self):
        # The guard must not fire on a DC that gates something OTHER than the
        # damage. An Escape DC is a way out of a condition, not a damage save.
        assert self._f(
            "The creature takes 2d6 bludgeoning damage and is immobilized by "
            "rubble (Escape DC 25)."
        ) == [("2d6", "bludgeoning")]

    def test_an_escape_dc_with_the_verb_OUTSIDE_the_parens_also_does_not(self):
        # The spelling above is the one I invented; these two are the ones the
        # corpus actually uses, and the first version of this guard fired on
        # both -- dropping each degree's OWN damage and keeping the recurring
        # damage instead. A parenthetical only counts if it names a save.
        assert self._f(
            "The creature's clothing is pulled into the clockworks. The creature "
            "takes 4d8+18 bludgeoning damage and is restrained. Until the creature "
            "Escapes (DC 24), it takes 2d8+9 bludgeoning damage each round."
        ) == [("4d8+18", "bludgeoning"), ("2d8+9", "bludgeoning")]
        assert self._f(
            "As failure, but 30d6 piercing damage, 2d6 persistent bleed damage, "
            "and is restrained until they escape (DC 37)."
        ) == [("30d6", "piercing"), ("2d6", "bleed")]

    def test_two_ordinary_instances_both_survive(self):
        assert self._f("The creature takes 6d6 fire damage and 1d6 persistent fire damage.") == [
            ("6d6", "fire"),
            ("1d6", "fire"),
        ]


class TestADegreeStopsAtAParagraphBreak:
    """The LAST degree has no bold after it, so without this it swallows the page.

    Both shapes below were SHIPPED that way before this guard: the text itself
    was wrong in committed data, and degree_effects then read the buried dice as
    the degree's own damage. 21 spells carry a folded affliction block
    (PFSRD2-Parser-t132); 6 more carry a trailing paragraph (-xqzp).
    """

    def _blocks(self, html):
        bs = BeautifulSoup(html, "html.parser")
        section = {}
        extract_result_blocks(section, bs)
        return section, str(bs)

    def test_an_affliction_stat_block_is_not_part_of_the_degree(self):
        # purple_worm_sting. The critical failure inflicts the venom AT stage 2;
        # the stage table is the venom's, not the degree's.
        section, soup = self._blocks(
            "<b>Critical Failure</b> The target is afflicted with purple worm venom"
            " at stage 2.<br /><br /><b>Purple Worm Venom</b> (poison); <b>Level</b>"
            " 11; <b>Stage 1</b> 3d6 poison damage; <b>Stage 2</b> 4d6 poison damage."
        )
        assert section["critical_failure"] == (
            "The target is afflicted with purple worm venom at stage 2."
        )
        assert "degree_effects" not in section, "13d6 at once is not what it deals"
        assert "Purple Worm Venom" in soup, "the stage table stays on the page"

    def test_a_trailing_paragraph_is_not_part_of_the_degree(self):
        # door_to_beyond. The 4d6 hits anyone ending their turn in the space,
        # with no save at all -- it is not the critical failure's damage.
        section, soup = self._blocks(
            "<b>Critical Failure</b> The creature is pulled 20 feet toward the door."
            "<br /><br />The cracks are too thin, but decompressive effects deal 4d6"
            " slashing damage to any creature that ends its turn in the space."
        )
        assert section["critical_failure"] == ("The creature is pulled 20 feet toward the door.")
        assert "degree_effects" not in section
        assert "decompressive" in soup

    def test_a_result_table_is_not_part_of_the_degree(self):
        # unfathomable_song. There is no paragraph break here at all -- the
        # <h2> and <table> ARE the separator, so the blank-line rule alone
        # would still swallow the whole result table into critical_failure.
        section, soup = self._blocks(
            "<b>Critical Failure</b> Roll 1d4+1 on the table below."
            '<h2>Unfathomable Song</h2><table class="inner">'
            "<tr><td>1</td><td>The target is frightened 2.</td></tr>"
            "<tr><td>2</td><td>The target takes 4d6 sonic damage.</td></tr></table>"
        )
        assert section["critical_failure"] == "Roll 1d4+1 on the table below."
        assert "degree_effects" not in section, "the table's dice are not the degree's"
        assert "Unfathomable Song" in soup and "frightened 2" in soup

    def test_an_affliction_with_no_separator_still_leaves_the_last_degree(self):
        # curse_of_death. There is no <br/> at all before the affliction's
        # bold, so the paragraph and block rules cannot see a boundary. After
        # the LAST degree a new bold introduces a new thing, so it ends there.
        section, soup = self._blocks(
            "<b>Critical Failure</b> The target is afflicted with the curse of"
            " death at stage 2. <b>Curse of Death</b> (curse, death, void)"
            " <b>Stage 1</b> 4d6 void damage; <b>Stage 2</b> 8d6 void damage."
        )
        assert section["critical_failure"] == (
            "The target is afflicted with the curse of death at stage 2."
        )
        assert "degree_effects" not in section, "24d6 at once is not what it deals"
        assert "Curse of Death" in soup

    def test_a_middle_degree_keeps_a_bold_of_its_own(self):
        # The narrower predicate stays on middle degrees: a bold between two
        # degrees can belong to the first. Only the LAST degree stops at any
        # bold, because only it lacks a terminator.
        section, _ = self._blocks(
            "<b>Failure</b> The target is pushed back <b>10 feet</b> and falls"
            " prone.<br /><b>Critical Failure</b> As failure, but 2d6 damage."
        )
        assert "10 feet" in section["failure"]
        assert "falls prone" in section["failure"]

    def test_a_middle_degree_keeps_its_own_paragraphs(self):
        # tanglecurse. Failure says "roll 1d4 and consult the results below"
        # and the results sit between it and Critical Failure -- so they are
        # Failure's own content. The boundary must not fire here: a middle
        # degree already has a terminator, the next degree's bold. Applying it
        # anyway left the degree pointing at nothing.
        section, _ = self._blocks(
            "<b>Failure</b> The target is affected by the spores--roll 1d4 and"
            " consult the results below.<br /><br /><b>1:</b> The target is"
            " clumsy 1.<br /><b>2:</b> The target takes 2d6 poison damage."
            "<br /><b>Critical Failure</b> As failure, but the bloom is 20 feet."
        )
        assert "consult the results below" in section["failure"]
        assert "clumsy 1" in section["failure"], "the results are Failure's own"
        assert "2d6 poison damage" in section["failure"]
        assert section["critical_failure"] == "As failure, but the bloom is 20 feet."

    def test_a_single_break_still_separates_degrees(self):
        # The guard must not fire on the ordinary separator, or every degree
        # after the first would be lost.
        # The LAST degree carries a single <br/> mid-content on purpose. Only a
        # DOUBLE break ends a degree, so that sentence must stay. Without it
        # nothing here reaches _starts_a_blank_line at all, and this test
        # passed with that function hardwired to True.
        section, _ = self._blocks(
            "<b>Success</b> Half damage.<br /><b>Failure</b> The creature takes"
            " 6d6 fire damage.<br /><b>Critical Failure</b> Double damage.<br />"
            "The creature is also knocked prone."
        )
        assert section["success"] == "Half damage."
        assert section["failure"] == "The creature takes 6d6 fire damage."
        assert section["critical_failure"] == (
            "Double damage.<br/>The creature is also knocked prone."
        )
        assert [e["degree"] for e in section["degree_effects"]] == ["failure"]

    def test_whitespace_between_the_two_breaks_still_counts(self):
        # The source pretty-prints, so the pair is rarely adjacent.
        section, _ = self._blocks(
            "<b>Failure</b> The creature is pushed back.<br />\n  <br />\n"
            "Something else entirely deals 9d6 fire damage."
        )
        assert section["failure"] == "The creature is pushed back."
        assert "degree_effects" not in section


class TestAlternativesAreNotCumulative:
    """ "2d6 ... or 6d6" offers a choice; emitting both reads as 8d6.

    Keeping the base case is the same call PFSRD2-Parser-bsw3 makes for scaling.
    The false-positive tests matter more than the true positives here: an
    unanchored "or" suppressed four files' worth of real damage, because
    ordinary English "or" is everywhere.
    """

    def _f(self, text):
        return [
            x.get("formula") for e in degree_effects_for({"failure": text}) for x in e["damage"]
        ]

    def test_or_between_two_dice_drops_the_alternative(self):
        assert self._f(
            "You deal 2d6 damage of the chosen alignment type, or 6d6 damage if"
            " you have legendary proficiency in Religion."
        ) == ["2d6"]

    def test_either_or_branch_is_not_added_to_the_base(self):
        # kareq: the 6d6 always lands; the 1d6 only in the fire branch.
        assert self._f(
            "The creature takes 6d6 damage of the appropriate type and either is"
            " deafened for 1 minute (if sonic damage) or takes 1d6 persistent"
            " fire damage (if fire damage)."
        ) == ["6d6"]

    def test_instead_marks_the_alternative_not_the_value(self):
        assert self._f(
            "They take 3d8 mental damage. This ability is less effective if you"
            " choose a basic action; the target takes 3d4 mental damage instead"
            " if you choose a basic action."
        ) == ["3d8"]

    def test_instead_OF_is_the_value_itself(self):
        # explosive_death_drop: "6d6 instead of 12d6" -- 6d6 IS the success
        # damage, replacing another degree's. Suppressing it loses the outcome.
        assert self._f(
            "As critical success, but the target takes 6d6 fire damage instead"
            " of 12d6, and creatures don't take persistent fire damage."
        ) == ["6d6"]

    def test_regained_hit_points_are_not_damage(self):
        # morlock_engineer's Uncanny Tinker, verbatim. The previous fixture was
        # "The target regains 8d6 Hit Points and a +1 bonus." -- with no
        # "damage" after the dice, extract_all returned nothing at all, so the
        # assertion held even with the healing guard deleted entirely. This
        # sentence has BOTH a heal and a damage clause, which is the only shape
        # in which the guard can be shown to do anything.
        assert (
            self._f(
                "The target regains 8d6 Hit Points and a +1 circumstance bonus to"
                " attack rolls for 1 minute. Alternately, the morlock can deal 8d6"
                " damage (bludgeoning, piercing, or slashing)."
            )
            == []
        )

    def test_or_in_a_size_clause_is_not_an_alternative(self):
        # rusted_cage_trap. No dice precede the "or", so it is ordinary English.
        assert self._f(
            "A Medium or smaller creature becomes trapped inside the cage"
            " (Escape DC 20). A Large or larger creature takes 2d6+5"
            " bludgeoning damage and is knocked prone."
        ) == ["2d6+5"]

    def test_or_in_a_subject_clause_is_not_an_alternative(self):
        # lifes_flowing_river
        assert self._f(
            "If the creature is undead or a nindoru fiend, it takes 2d6 mental" " damage."
        ) == ["2d6"]

    def test_or_in_a_quantity_is_not_an_alternative(self):
        # memory_of_nothing
        assert self._f(
            "For the next 3 rounds, if the target performs an activity that"
            " requires three or more actions, they take 12d8 mental damage."
        ) == ["12d8"]

    def test_an_or_beyond_the_window_is_not_an_alternative(self):
        # aegis_for_the_innocent. Renamed to say what it actually pins.
        #
        # This case is protected TWICE over -- there is no dice expression
        # before the "or" (so the anchor rejects it) and the "or" is ~50
        # characters from the dice (so the {0,30} tail rejects it too). Neither
        # unanchoring the rule nor widening _QUALIFIER_WINDOW makes it fail,
        # which means it does not cover the anchor even though it sits in a
        # class about the anchor.
        #
        # It is kept rather than deleted because the window bound is real and
        # otherwise unpinned. The anchor's coverage comes from the three tests
        # above: measured over the corpus, exactly three files are protected by
        # the anchor alone, and those three ARE those tests.
        assert self._f(
            "If a creature would be pushed into a solid barrier or another"
            " creature, it stops at that point and takes 2d6 bludgeoning damage."
        ) == ["2d6"]


class TestAFormulaTheTextDoesNotSpell:
    """The `at == -1` branch: extract_all returned a formula that is not a
    literal substring of the degree.

    Every suppression rule reads a WINDOW around the formula's position, so
    with no position there is nothing to read. The branch keeps the entry,
    which is the conservative direction -- an unjudgeable formula publishes
    rather than vanishing. Dropping it instead would make a normalisation
    change upstream silently delete damage.
    """

    def _f(self, damage, plain):
        from universal.universal import _damage_the_degree_itself_deals

        return [d["formula"] for d in _damage_the_degree_itself_deals(damage, plain)]

    def test_a_formula_not_found_in_the_text_is_kept(self):
        assert self._f([{"formula": "2d6+3"}], "the target takes 2d6 + 3 damage") == ["2d6+3"]

    def test_it_is_kept_even_inside_a_sentence_that_would_suppress_it(self):
        # "(DC 30 basic Reflex save)" would drop this formula if the window
        # could be located. It cannot, so the entry survives -- proving the
        # branch returns early rather than falling through to the rules.
        assert self._f(
            [{"formula": "4d10"}],
            "a creature that falls takes 4 d10 damage (DC 30 basic Reflex save)",
        ) == ["4d10"]

    def test_a_missing_formula_key_is_kept(self):
        from universal.universal import _damage_the_degree_itself_deals

        entry = {"damage_type": "acid"}
        assert _damage_the_degree_itself_deals([entry], "some acid damage") == [entry]


class TestNamedExemptions:
    """Degrees the extractor cannot judge, listed by name in constants.py.

    The list exists because the markers involved ("if", "until", "its Strikes")
    are ordinary degree prose -- keying a rule on them suppressed four files of
    real damage. What makes it more than a silent allowlist is the pinned
    phrase: the exemption asserts if the sentence it was granted for changes.
    """

    def test_a_listed_degree_emits_nothing(self):
        obj = {
            "name": "Endsong",
            "critical_failure": "As failure, but the target is confused for 1"
            " hour. While confused, its Strikes resonate with Volnagur's song,"
            " dealing an additional 1d6 sonic damage.",
        }
        assert degree_effects_for(obj) == []

    def test_the_exemption_fires_through_a_real_degree_writer(self):
        # The unit tests above call degree_effects_for directly, so they would
        # all still pass if the key the WRITER builds disagreed with the key the
        # table is written in. It did: a third of degree carriers (spell_defense,
        # save_results, routine_results) have no name of their own, so an
        # exemption for one of them could never fire. This drives the real
        # writer, on a carrier whose name comes from its parent.
        from universal.universal import extract_result_blocks

        section = {"subtype": "spell_defense"}
        html = (
            "<b>Critical Failure</b> As failure, but the target is confused for"
            " 1 hour. While confused, its Strikes resonate with Volnagur's song,"
            " dealing an additional 1d6 sonic damage."
        )
        extract_result_blocks(section, BeautifulSoup(html, "html.parser"))
        # No name anywhere: the exemption cannot resolve, so the dice publish.
        assert section.get("degree_effects")

        section = {"name": "Endsong", "subtype": "spell_defense"}
        extract_result_blocks(section, BeautifulSoup(html, "html.parser"))
        assert section.get("degree_effects") is None

    def test_an_unnamed_carrier_inherits_its_owners_exemption(self):
        # extract_degree_effects takes owner_name for exactly this: hazard
        # routine_results carries degrees but never a name.
        from universal.universal import extract_degree_effects

        carrier = {
            "subtype": "routine_results",
            "critical_failure": "While confused, its Strikes resonate with"
            " Volnagur's song, dealing an additional 1d6 sonic damage.",
        }
        extract_degree_effects(carrier, owner_name="Endsong")
        assert carrier.get("degree_effects") is None

    def test_an_unlisted_degree_of_the_same_ability_is_untouched(self):
        obj = {
            "name": "Endsong",
            "failure": "The target takes 4d6 sonic damage.",
        }
        assert [x["formula"] for e in degree_effects_for(obj) for x in e["damage"]] == ["4d6"]

    def test_the_same_text_on_an_unlisted_ability_is_not_exempt(self):
        # The key is (name, degree). A different ability with similar wording
        # does not inherit the exemption.
        obj = {
            "name": "Some Other Ability",
            "critical_failure": "While confused, its Strikes resonate, dealing"
            " an additional 1d6 sonic damage.",
        }
        assert [x["formula"] for e in degree_effects_for(obj) for x in e["damage"]] == ["1d6"]

    def test_a_reworded_degree_stops_being_exempt(self):
        # An exemption must not outlive the sentence it was granted for. If AoN
        # rewrites the page, the phrase stops matching and the damage publishes
        # again -- the exemption simply stops applying rather than suppressing
        # a sentence nobody has read.
        obj = {
            "name": "Endsong",
            "critical_failure": "As failure, but the target takes 1d6 sonic damage directly.",
        }
        assert [x["formula"] for e in degree_effects_for(obj) for x in e["damage"]] == ["1d6"]

    def test_a_same_named_neighbour_does_not_inherit_the_exemption(self):
        # The reason the phrase is part of the MATCH and not an assert after it.
        # A name is not a unique handle on a degree: 28 (name, degree) keys in
        # the corpus already match two carriers in the same file. Asserting on
        # the phrase after a key match would halt the parse on the neighbour,
        # which is a worse failure than the one the pin exists to prevent.
        neighbour = {
            "name": "Endsong",
            "critical_failure": "The target takes 4d6 sonic damage.",
        }
        assert [x["formula"] for e in degree_effects_for(neighbour) for x in e["damage"]] == ["4d6"]

    def test_the_writer_and_the_guard_agree_however_they_reached_the_object(self):
        # The divergence this replaced: the guard inherits the nearest enclosing
        # name while a writer only gets one if its caller passes it, so the two
        # could resolve different keys for the same degree and the guard would
        # then blame the writer for its own answer. With the phrase in the
        # match, both ask the same question of the same text.
        from universal.universal import assert_every_degree_was_modelled

        carrier = {
            "subtype": "spell_defense",
            "critical_failure": "While confused, its Strikes resonate with"
            " Volnagur's song, dealing an additional 1d6 sonic damage.",
        }
        extract_degree_effects(carrier, owner_name="Endsong")
        # Whatever the writer decided, the guard must agree with it.
        assert_every_degree_was_modelled(
            {"name": "Endsong", "sections": [carrier]}, "spell.schema.json"
        )


class TestADegreeThatContinuesPastItsBreak:
    """A named few last degrees own the paragraph after their break.

    The markup is identical to the affliction fold -- "<b>Critical Failure</b>
    ...<br /><br />..." either way -- so only the meaning separates them, and
    that is why this is a list rather than a rule (PFSRD2-Parser-ts9n).
    """

    TEXT = (
        "<b>Failure</b> During the first 5 minutes of the spell's duration, you"
        " can Sustain the spell to modify a memory once each round.<br /><br />"
        "Any memories you've altered remain changed as long as the spell is"
        " active. If the target moves out of range before the 5 minutes is up,"
        " you can't alter any further memories."
    )

    def _blocks(self, name, html):
        bs = BeautifulSoup(html, "html.parser")
        section = {"name": name}
        extract_result_blocks(section, bs)
        return section

    def test_a_listed_degree_keeps_its_trailing_paragraph(self):
        section = self._blocks("Rewrite Memory", self.TEXT)
        assert "Any memories you've altered" in section["failure"]
        assert (
            "the 5 minutes is up" in section["failure"]
        ), "the antecedent for 'the 5 minutes' is in the degree itself"

    def test_an_unlisted_spell_with_the_same_shape_is_still_bounded(self):
        # The exemption is keyed (name, degree); nothing else inherits it.
        section = self._blocks("Some Other Spell", self.TEXT)
        assert "Any memories you've altered" not in section["failure"]
        assert section["failure"].endswith("once each round.")

    def test_a_reworded_paragraph_fails_loudly(self):
        html = (
            "<b>Failure</b> You can modify a memory once each round.<br /><br />"
            "The spell ends if you are interrupted."
        )
        with pytest.raises(AssertionError, match="no longer in the text"):
            self._blocks("Rewrite Memory", html)


class TestTheGuardIsActuallyWired:
    """`validate_against_schema` must CALL the degree guard, not merely have one.

    Round 3 mutation M34 unwired the call and the whole suite stayed green: the
    guard against silent misses could itself go missing silently. Every parser
    reaches degrees through this one function, so this is the single point where
    the wiring is worth pinning.
    """

    def test_validate_against_schema_runs_the_degree_guard(self):
        import pytest as _pytest

        from pfsrd2.schema import validate_against_schema

        # An ability whose degree states damage no degree_effects models. The
        # guard must fire BEFORE jsonschema, since this document is otherwise
        # schema-valid.
        struct = {
            "name": "Rockfall",
            "sections": [
                {
                    "name": "Rockfall",
                    "subtype": "ability",
                    "failure": "The creature takes 2d6 bludgeoning damage.",
                }
            ],
        }
        with _pytest.raises(AssertionError, match="never called extract_degree_effects"):
            validate_against_schema(struct, "creature.schema.json")

    def test_the_equipment_deferral_still_reaches_this_call_site(self):
        # The exemption has to be honoured through validate_against_schema too,
        # or every equipment run breaks. PFSRD2-Parser-qj3v.
        from pfsrd2.schema import validate_against_schema

        struct = {"failure": "The creature takes 2d6 bludgeoning damage."}
        try:
            validate_against_schema(struct, "equipment.schema.json")
        except AssertionError as exc:  # pragma: no cover - would be the bug
            raise AssertionError(f"equipment deferral not honoured: {exc}") from exc
        except Exception:
            pass  # jsonschema rejecting the stub document is fine; the guard did not fire
