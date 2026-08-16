"""Continuation-line handling in _split_nodes (PR #133 review round)."""

import json

import pytest
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
        with pytest.raises(AssertionError, match="about to be dropped"):
            self._extract(
                "<b>Big Attack</b> The dragon breathes.<br/>"
                "<b>Success</b> Half damage.<br/>"
                "This trailing paragraph belongs to Big Attack and lives nowhere else."
            )

    def test_no_abilities_means_no_assert(self):
        # The caller only overwrites the section text inside `if abilities:`.
        # With none, the text is left alone and nothing is dropped — asserting
        # here would fail a build over content that still ships. The Related
        # Groups shape is live in 86 monster_family files.
        assert (
            self._extract(
                '<b>Related Groups</b> <a game-obj="MonsterFamilies" aonid="595">'
                "Geniekin</a><br/>Many immortals dwell upon the planes."
            )
            is None
        )

    def test_an_unclaimed_lead_in_fails_instead_of_vanishing(self):
        # _split_nodes has TWO paths that leave a node unclaimed, not one. The
        # _LEAD_IN_RE branch skips a lead-in because it "already lives in the
        # sections text" — true for monster_family, false here, because this
        # file overwrites that text with str(bs). No template is in this shape
        # today, and only by accident: ID_15's lead-in sits behind an <h3> so
        # collect_ability_nodes never sees it.
        with pytest.raises(AssertionError, match="about to be dropped"):
            self._extract(
                "<b>Old Power</b> Does a thing.<br/><br/>"
                "To make a dragon with this ability, replace Old Power with "
                "the following:<br/><b>New Power</b> Does a better thing."
            )

    def test_a_text_free_unclaimed_node_fails_too(self):
        # The guard tests node SHAPE, not emptiness. plain_text() measures an
        # attribute-only anchor as empty, so an emptiness test would let it
        # drop as silently as before.
        with pytest.raises(AssertionError, match="did not claim a <a>"):
            self._extract(
                "<b>Grab</b> The creature grabs.<br/>"
                '<a game-obj="Traits" aonid="1"></a>'
                "<br/><b>Success</b> Half damage."
            )


class TestMonsterFamilyKeepsItsSectionText:
    """The invariant the template guard's scope rests on.

    PFSRD2-Parser-4bcm was closed for monster_family on the grounds that it
    parses a COPY and never reassigns section["text"], so an unclaimed node is
    not lost there. That reasoning is only as durable as the invariant, and
    nothing enforced it — a later `section["text"] = str(bs)` in this file
    would make the loss real and silent, and would quietly expire the argument
    for not guarding families the way templates are guarded.
    """

    def test_unclaimed_prose_survives_in_the_section_text(self):
        from pfsrd2.monster_family import _extract_section_abilities

        # The shape the ability parser leaves unclaimed: a continuation after
        # a degree label. In a template this is dropped and now asserts; here
        # it must simply still be there afterwards.
        prose = "This trailing paragraph belongs to the dragon\u2019s Big Attack alone."
        struct = {
            "sections": [
                {
                    "type": "section",
                    "name": "Abilities",
                    "text": (
                        "<b>Big Attack</b> The dragon breathes.<br/>"
                        "<b>Success</b> Half damage.<br/>" + prose
                    ),
                    "sections": [],
                }
            ]
        }
        _extract_section_abilities(struct)
        section = struct["sections"][0]
        assert [a["name"] for a in section["abilities"]] == ["Big Attack"]
        # The prose must be genuinely UNCLAIMED, or this test passes for the
        # wrong reason: with the glue rules relaxed the parser attaches it to
        # Big Attack and the invariant is never exercised. PFSRD2-Parser-9oge
        # is the open ticket to change exactly that glue rule, so this guard
        # is what makes the test fail loudly instead of silently going inert.
        # ensure_ascii=False is load-bearing: json.dumps escapes non-ASCII by
        # default, so a single curly apostrophe in `prose` would make this
        # assertion vacuously true — and 44 of 55 template files carry one.
        # The guard against this test going inert must not itself go inert.
        assert prose not in json.dumps(section["abilities"], ensure_ascii=False), (
            "the prose was claimed by an ability, so this test is no longer "
            "exercising the unclaimed-node path it exists for"
        )
        assert prose in section["text"], (
            "monster_family reassigned or consumed its section text; the "
            "template guard's scope argument no longer holds"
        )
        assert "Big Attack" in section["text"]


class TestTemplateGuardPermissiveDirection:
    """The half of the guard the whole corpus depends on.

    Every mutation run against this guard so far attacked the strict
    direction — making it accept something it should reject. Nothing pinned
    the permissive direction: turning the whitespace assert into
    `assert False` survived the entire suite.

    It survived for a reason worth stating rather than hiding. That branch
    keeps ZERO templates green today — all 24 unclaimed nodes in the corpus
    are <br/>, and the newlines that do reach the node list arrive with
    `current` truthy and get consumed. The whitespace allowance is a hedge
    against a shape the corpus does not currently contain, which is exactly
    the kind of branch that gets "cleaned up" by a future edit. Hence a test.
    """

    def _extract(self, html):
        from pfsrd2.monster_template import _extract_abilities_from_bs

        return _extract_abilities_from_bs(BeautifulSoup(html, "html.parser"))

    def test_pretty_printer_whitespace_is_not_a_dropped_node(self):
        # A newline between the <br/> and the next <b>. The <br/> is CONSUMED
        # here, so test_separators_alone_are_not_a_failure does not stand in
        # for this — the unclaimed node is the bare newline string.
        #
        # 27 of 55 template files contain this byte shape, but none of them
        # reach the guard with the newline unclaimed. This fixture constructs
        # the case rather than sampling it.
        abilities = self._extract(
            "<b>Grab</b> The creature grabs.<br/>\n<b>Constrict</b> It squeezes.<br/>\n"
        )
        assert [a["name"] for a in abilities] == ["Grab", "Constrict"]


class TestTemplateCallerWriteBackOrdering:
    """Why `if abilities:` is a safe gate — pinned, not just asserted in prose.

    The guard runs only when there are abilities, because that is when the
    caller overwrites the section text. The <ul> branch DOES also write, but it does so BEFORE collect_ability_nodes
    mutates the tree, so it snapshots the pre-extraction string.

    Ordering is the whole safety argument, and nothing held it in place:
    moving that write-back below the extraction call, or ungating the
    ability write-back, both survived the entire suite while emptying a
    section outright.
    """

    def test_a_section_with_no_parseable_abilities_keeps_its_text(self):
        from pfsrd2.monster_template import _try_extract_changes

        # Related Groups yields no abilities, and is live in 86 family files.
        # The <ul> is load-bearing, not decoration: the write this class is
        # named for is the one inside the <ul> branch. Without a <ul>
        # that branch never runs and the test pins only the gate — moving
        # that write below the extraction call survived the whole suite, and
        # with a <ul> present it empties the section outright.
        html = (
            "<ul><li>Increase the creature's level by 1.</li></ul>"
            '<b>Related Groups</b> <a game-obj="MonsterFamilies" aonid="595">Geniekin</a>'
            "<br/>Many immortals dwell upon the planes."
        )
        source_section = {"type": "section", "name": "S", "text": html, "sections": []}
        _try_extract_changes(source_section, {})
        assert "Many immortals dwell upon the planes." in source_section["text"]
        assert "Related Groups" in source_section["text"]

    def test_the_ul_changes_survive_extraction(self):
        # A second consequence of the same ordering, and a worse one than lost
        # text: collect_ability_nodes extracts from the first non-table <b>
        # onward, so a <b> standing BEFORE the <ul> takes the whole <ul> with
        # it. Run the extraction first and bs.find("ul") returns None, every
        # <li> change is silently lost, and `found` still comes back True.
        from pfsrd2.monster_template import _try_extract_changes

        html = (
            "<b>All host creatures gain the following abilities.</b>"
            "<ul><li>Increase the creature's level by 1.</li></ul>"
            "<b>Grab</b> The creature grabs."
        )
        mt = {}
        source_section = {"type": "section", "name": "S", "text": html, "sections": []}
        _try_extract_changes(source_section, mt)
        assert mt.get("changes"), "the <ul> changes were lost"
        assert any(
            "Increase the creature's level" in json.dumps(c, ensure_ascii=False)
            for c in mt["changes"]
        )

    def test_a_section_with_abilities_gives_up_its_markup(self):
        # The positive half, and the one the whole guard is premised on: when
        # there ARE abilities the caller overwrites the section text with what
        # survived extraction. That write is what makes an unclaimed node a
        # LOSS rather than a duplicate — without it the abilities ship twice,
        # once structurally and once as raw markup left in the text.
        #
        # Deleting it left the suite green. It hides from the granted-ability
        # tests because the _GRANTS_ABILITIES / choice_bounds branch reassigns
        # the text a few lines further down; only the plain-pool path is
        # exposed, and nothing looked at the text there.
        #
        # <b> surviving into a text field is this project's tripwire for a
        # parser that failed to extract structure, so the assertion is on <b>
        # specifically, not just on the text having changed.
        from pfsrd2.monster_template import _try_extract_changes

        source_section = {
            "type": "section",
            "name": "S",
            "text": "<b>Grab</b> The creature grabs.<br/><b>Constrict</b> It squeezes.",
            "sections": [],
        }
        _try_extract_changes(source_section, {})
        assert "<b>" not in source_section["text"], (
            "the ability markup survived in the section text, so the abilities "
            "ship twice and an unclaimed node would be a duplicate, not a loss"
        )
