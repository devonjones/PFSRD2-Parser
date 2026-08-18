"""Degrees of success on monster family and template abilities.

A bold label the ability parser does not recognise starts a NEW ability. The
degree-of-success labels were not in DEFAULT_ADDON_LABELS, so every published
"Success" / "Failure" became its own entry sitting beside the ability that
rolled the check — 68 of them across monster_families/, and the text was
detached from the ability it belonged to.

Hazards already solved this by unioning RESULT_LABELS into their addon set;
families and templates now do the same.
"""

import json

import pytest
from bs4 import BeautifulSoup

from universal.ability import (
    ADDON_LABELS_WITH_RESULTS,
    DEFAULT_ADDON_LABELS,
    parse_abilities_from_nodes,
)
from universal.universal import RESULT_LABELS

BREATH = (
    "<b>Cloud of Ashes</b> The dragon exhales a cloud of ash."
    "<br/><b>Critical Success</b> The creature avoids the cloud entirely."
    "<br/><b>Success</b> The creature is unaffected."
    "<br/><b>Failure</b> The creature begins coughing."
    "<br/><b>Critical Failure</b> As failure, plus it spends its next action coughing."
)


def _abilities(html, labels=ADDON_LABELS_WITH_RESULTS):
    nodes = list(BeautifulSoup(html, "html.parser").children)
    return parse_abilities_from_nodes(nodes, addon_labels=labels)


class TestAddonLabelSets:
    def test_the_family_set_covers_every_degree_of_success(self):
        assert set(RESULT_LABELS) <= ADDON_LABELS_WITH_RESULTS

    def test_hazards_families_and_templates_share_one_set(self):
        # Three copies of `DEFAULT_ADDON_LABELS | set(RESULT_LABELS)` existed
        # before this; the set now lives once in universal/ability.py.
        import pfsrd2.hazard
        import pfsrd2.monster_family
        import pfsrd2.monster_template

        assert (
            pfsrd2.hazard.ADDON_LABELS_WITH_RESULTS
            is pfsrd2.monster_family.ADDON_LABELS_WITH_RESULTS
            is pfsrd2.monster_template.ADDON_LABELS_WITH_RESULTS
            is ADDON_LABELS_WITH_RESULTS
        )

    def test_it_is_a_superset_of_the_default(self):
        # Widened, not replaced — Trigger/Effect/Requirements still apply.
        assert DEFAULT_ADDON_LABELS < ADDON_LABELS_WITH_RESULTS


class TestDegreesFoldIntoTheirAbility:
    def test_one_ability_not_four(self):
        abilities = _abilities(BREATH)
        assert [a["name"] for a in abilities] == ["Cloud of Ashes"]

    def test_the_degree_text_lands_on_the_ability(self):
        ability = _abilities(BREATH)[0]
        # All four degrees, not three: narrowing the set to drop just
        # "Critical Success" otherwise passes, and 17 shipped files carry one.
        assert ability["critical_success"] == "The creature avoids the cloud entirely."
        assert ability["success"] == "The creature is unaffected."
        assert ability["failure"] == "The creature begins coughing."
        assert ability["critical_failure"].startswith("As failure")

    def test_without_the_result_labels_they_split_apart(self):
        # Pins why the set has to be widened: this is the shipped bug.
        names = [a["name"] for a in _abilities(BREATH, labels=DEFAULT_ADDON_LABELS)]
        assert names == [
            "Cloud of Ashes",
            "Critical Success",
            "Success",
            "Failure",
            "Critical Failure",
        ]

    def test_a_real_ability_after_the_degrees_still_starts_its_own_entry(self):
        html = BREATH + "<br/><b>Change Shape</b> The dragon takes another form."
        assert [a["name"] for a in _abilities(html)] == ["Cloud of Ashes", "Change Shape"]


class TestTheCallSitesAreWired:
    """The label set is only useful if the parsers actually pass it.

    Testing parse_abilities_from_nodes directly proves the set works; it does
    not prove monster_family.py and monster_template.py hand it over. Dropping
    `addon_labels=` at either call site leaves every test above passing.
    """

    def test_monster_family_passes_the_labels(self):
        from pfsrd2.monster_family import _extract_abilities_from_bs

        abilities, _spells = _extract_abilities_from_bs(BeautifulSoup(BREATH, "html.parser"))
        assert [a["name"] for a in abilities] == ["Cloud of Ashes"]
        assert abilities[0]["success"] == "The creature is unaffected."

    def test_monster_template_passes_the_labels(self):
        from pfsrd2.monster_template import _extract_abilities_from_bs

        abilities = _extract_abilities_from_bs(BeautifulSoup(BREATH, "html.parser"))
        assert [a["name"] for a in abilities] == ["Cloud of Ashes"]
        assert abilities[0]["critical_failure"].startswith("As failure")

    def test_change_extraction_passes_the_labels(self):
        # "Add the following abilities" blocks on templates and families go
        # through a fourth call site. No <li> in the current corpus publishes a
        # degree bold, so a regression here would be invisible to a parser run.
        from bs4 import NavigableString

        from pfsrd2.change_extraction import _extract_abilities_from_li

        html = f"<li>The creature gains the following abilities: {BREATH}</li>"
        li = BeautifulSoup(html, "html.parser").find("li")
        assert any(
            isinstance(n, NavigableString) and "following abilit" in str(n) for n in li.children
        )
        abilities = _extract_abilities_from_li(li)
        assert [a["name"] for a in abilities] == ["Cloud of Ashes"]


class TestShapesWhereTheWiderSetCostsSomething:
    """Widening the label set makes three lossy shapes reachable.

    None occur in the current corpus on this path. They are pinned here so a
    future refactor can tell the current behaviour from an intention, and so
    that the tickets they name fail loudly here the day they are fixed rather
    than silently changing shape.

    That is not hypothetical: PFSRD2-Parser-4bcm and PFSRD2-Parser-mgz4 were
    open when this was written and are now fixed, and both DID fail here
    first, which is what the class is for.
    """

    def test_a_repeated_degree_fails_instead_of_overwriting(self):
        # Two "Failure" blocks on one ability meant the second clobbered the
        # first and FIRST outcome existed nowhere. That is how
        # confounding_betrayal shipped without Unmask's first Critical Success.
        html = (
            "<b>Twin Gaze</b> Two saves."
            "<br/><b>Failure</b> FIRST outcome."
            "<br/><b>Failure</b> SECOND outcome."
        )
        with pytest.raises(AssertionError, match="publishes 'Failure' twice"):
            _abilities(html)

    def test_a_continuation_after_a_degree_is_currently_dropped(self):
        # PFSRD2-Parser-4bcm. The paragraph belongs to Big Attack and lives
        # nowhere else; families/templates do not thread `consumed`, so it is
        # gone. Pinned, not endorsed.
        html = (
            "<b>Big Attack</b> The dragon breathes."
            "<br/><b>Success</b> Half damage."
            "<br/>This trailing paragraph belongs to Big Attack."
        )
        abilities = _abilities(html)
        assert [a["name"] for a in abilities] == ["Big Attack"]
        assert abilities[0]["success"] == "Half damage."
        assert "trailing paragraph" not in json.dumps(abilities)

    def test_an_empty_degree_fails_instead_of_disappearing(self):
        # Was PFSRD2-Parser-mgz4, and this test used to pin the bug rather than
        # the fix: `_apply_addon` guarded with `if value:`, so an empty
        # published degree left no trace at all — not an empty field, not an
        # error. Before the wider label set it was at least a visible (wrong)
        # ability entry; after it, nothing.
        html = "<b>Gaze</b> Save.<br/><b>Success</b><br/><b>Failure</b> Dazzled."
        with pytest.raises(AssertionError, match="publishes 'Success' with no value"):
            _abilities(html)


class TestSetOnceCoversItsOwnCallSites:
    """_set_once guards three call sites; only the generic one was tested.

    The docstring on _set_once names the Saving Throw path specifically, and
    both Saving Throw and Damage reach it through their own branches in
    _apply_addon rather than through the generic `else`. Reverting either to a
    bare assignment left the whole suite green, so the guard's own docstring
    was an untested claim.
    """

    def test_a_repeated_saving_throw_fails_instead_of_overwriting(self):
        html = (
            "<b>Withering Gaze</b> The creature stares."
            "<br/><b>Saving Throw</b> DC 20 Will"
            "<br/><b>Saving Throw</b> DC 30 Fortitude"
        )
        with pytest.raises(AssertionError, match="publishes 'Saving Throw' twice"):
            _abilities(html)

    def test_a_repeated_damage_fails_instead_of_overwriting(self):
        html = (
            "<b>Rending Bite</b> The creature bites."
            "<br/><b>Damage</b> 1d6 piercing"
            "<br/><b>Damage</b> 2d6 fire"
        )
        with pytest.raises(AssertionError, match="publishes 'Damage' twice"):
            _abilities(html)


class TestEveryBranchThatCanVanishIsGuarded:
    """_apply_addon has four branches; only one had a guard.

    Stage N and Saving Throw are covered by schema backstops — every schema
    that receives an affliction_stage or a save_dc lists `text` in its
    required set, so an empty one fails at validation. The generic `else`
    branch had no backstop and now asserts. Damage had neither: an empty
    value makes _parse_damage return [], _set_once writes it, and
    remove_empty_fields deletes it before validation, which is the same
    silent-vanish outcome five lines from the assert that condemns it.
    """

    def test_an_empty_damage_fails_instead_of_vanishing(self):
        html = "<b>Claw</b> It swipes.<br/><b>Damage</b><br/><b>Effect</b> Bleeding."
        with pytest.raises(AssertionError, match="publishes 'Damage' with no value"):
            _abilities(html)

    def test_an_empty_generic_addon_fails(self):
        html = "<b>Gaze</b> Save.<br/><b>Effect</b><br/><b>Failure</b> Dazzled."
        with pytest.raises(AssertionError, match="publishes 'Effect' with no value"):
            _abilities(html)

    def test_a_populated_damage_is_untouched(self):
        # The guard must not disturb the ordinary case.
        html = "<b>Claw</b> It swipes.<br/><b>Damage</b> 2d6 slashing"
        ability = _abilities(html)[0]
        assert ability["damage"][0]["formula"] == "2d6"


class TestDegreeEffects:
    """A degree is a string, so what it says is modelled on the parent.

    Before the degrees were folded in, each was (wrongly) its own ability, so
    the enrichment pipeline enriched it and its damage came back as structure.
    Folding removed the record that carried that. degree_effects[] puts it
    back on the parent, keyed by degree (PFSRD2-Parser-e01u).
    """

    BREATH = (
        "<b>Forceful Screech</b> The haunt screams."
        "<br/><b>Critical Success</b> The creature is unaffected."
        "<br/><b>Failure</b> The creature takes 2d8+9 force damage."
        "<br/><b>Critical Failure</b> The creature takes 4d8+9 force damage."
    )

    def test_each_damage_bearing_degree_gets_an_effect(self):
        ability = _abilities(self.BREATH)[0]
        effects = {e["degree"]: e for e in ability["degree_effects"]}
        assert sorted(effects) == ["critical_failure", "failure"]
        assert effects["failure"]["damage"][0]["formula"] == "2d8+9"
        assert effects["failure"]["damage"][0]["damage_type"] == "force"
        assert effects["critical_failure"]["damage"][0]["formula"] == "4d8+9"

    def test_a_degree_with_no_damage_gets_no_effect(self):
        # critical_success here is "The creature is unaffected." — modelling an
        # empty effect for it would be noise, not structure.
        ability = _abilities(self.BREATH)[0]
        assert "critical_success" not in {e["degree"] for e in ability["degree_effects"]}

    def test_the_degree_text_is_left_alone(self):
        # degree_effects is additive: the string field is untouched, which is
        # what makes this non-breaking for existing consumers.
        ability = _abilities(self.BREATH)[0]
        assert ability["failure"] == "The creature takes 2d8+9 force damage."

    def test_an_ability_with_no_degrees_gets_no_key(self):
        # Absent rather than empty — remove_empty_fields would drop [] anyway,
        # and an empty array would read as "checked, found nothing".
        ability = _abilities("<b>Grab</b> The creature grabs.")[0]
        assert "degree_effects" not in ability

    def test_a_dc_in_degree_text_does_NOT_become_a_saving_throw(self):
        # Deliberate scope limit. 163 DCs appear in degree text corpus-wide and
        # only 46 are saves: 64 are Escape DCs, 45 are flat checks and 7 are
        # skill checks. Typing those as save_dc would claim something the source
        # does not say, so saving_throw waits for PFSRD2-Parser-2cby.
        #
        # The degree carries damage AND an Escape DC on purpose. A degree with
        # only a DC produces no effect at all, so a test written on one asserts
        # over an empty list and cannot fail.
        html = (
            "<b>Collapse</b> The ceiling gives way."
            "<br/><b>Failure</b> The creature takes 2d6 bludgeoning damage"
            " and is immobilized by rubble (Escape DC 25)."
        )
        effects = _abilities(html)[0]["degree_effects"]
        assert len(effects) == 1, effects
        assert effects[0]["damage"][0]["formula"] == "2d6"
        # The whole key set, not a "saving_throw not in" spot check: this fails
        # if ANY new structure starts claiming the DC.
        assert set(effects[0]) == {"type", "subtype", "degree", "damage"}


class TestCreatureAddonDegrees:
    """Creatures write their degrees where no other writer reaches.

    They bypass parse_ability_from_html's bold-field extraction entirely
    (addon_labels=set()) and hand the degrees over as pre-consumed sections,
    which _apply_addons writes on AFTER that function has returned. Without a
    call there, every automatic, reactive and interaction ability in the
    creature corpus keeps unmodelled degrees.
    universal.extract_degree_effects holds the list of writers; the count does
    not get re-stated here, because a copy of it is a copy that goes stale.
    """

    SECTION = ("Rockfall", "The ceiling gives way.", None, None)
    # The damage TYPE is wrapped, which is how it arrives from the source. A
    # plain-text fixture cannot fail when the extractor stops stripping markup,
    # or stops running at all.
    ADDONS = [
        ("Failure", "The creature takes 2d6 <i>bludgeoning</i> damage.", None, None),
        (
            "Critical Failure",
            "The creature takes 4d6 <i>bludgeoning</i> damage.",
            None,
            None,
        ),
    ]

    def _defensive(self):
        from pfsrd2.creatures import process_defensive_ability

        sb = {"defense": {}}
        process_defensive_ability(self.SECTION, list(self.ADDONS), sb)
        return sb["defense"]["automatic_abilities"][0]

    def test_a_creature_degree_arriving_as_an_addon_gets_an_effect(self):
        ability = self._defensive()
        effects = {e["degree"]: e for e in ability["degree_effects"]}
        assert sorted(effects) == ["critical_failure", "failure"]
        assert effects["failure"]["damage"][0]["formula"] == "2d6"
        assert effects["failure"]["damage"][0]["damage_type"] == "bludgeoning"
        assert effects["critical_failure"]["damage"][0]["formula"] == "4d6"

    def test_the_addon_degree_string_keeps_its_markup(self):
        # Two halves, and the old version of this test had only the first: the
        # published string is untouched, AND the extractor read through the
        # markup to the damage. Asserting only the string left the test green
        # under a total no-op of the extractor.
        ability = self._defensive()
        assert ability["failure"] == "The creature takes 2d6 <i>bludgeoning</i> damage."
        effect = next(e for e in ability["degree_effects"] if e["degree"] == "failure")
        assert effect["damage"][0]["damage_type"] == "bludgeoning"

    def test_an_interaction_ability_takes_the_same_path(self):
        from pfsrd2.creatures import process_interaction_ability

        ability = process_interaction_ability({}, self.SECTION, list(self.ADDONS))
        assert [e["degree"] for e in ability["degree_effects"]] == [
            "failure",
            "critical_failure",
        ]
