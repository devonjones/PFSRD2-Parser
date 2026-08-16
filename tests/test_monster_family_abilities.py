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

    None occur in the current corpus. They are pinned here so a future
    refactor can tell the current behaviour from an intention, and so the two
    that are still open (PFSRD2-Parser-4bcm, PFSRD2-Parser-mgz4) fail loudly
    here the day they are fixed rather than silently changing shape.
    """

    def test_a_repeated_degree_silently_overwrites(self):
        # PFSRD2-Parser-xzij. Two "Failure" blocks used to be two visible
        # entries; folding them onto one parent means the second clobbers the
        # first and FIRST outcome exists nowhere. The guard for this fires on
        # 13 files with real pre-existing loss, so it lands with those fixes.
        html = (
            "<b>Twin Gaze</b> Two saves."
            "<br/><b>Failure</b> FIRST outcome."
            "<br/><b>Failure</b> SECOND outcome."
        )
        ability = _abilities(html)[0]
        assert ability["failure"] == "SECOND outcome."
        assert "FIRST outcome" not in json.dumps(ability)

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

    def test_an_empty_degree_disappears(self):
        # PFSRD2-Parser-mgz4. `_apply_addon` guards with `if value:`, so an
        # empty published degree leaves no trace at all — before the wider set
        # it was at least a visible (if wrong) entry.
        html = "<b>Gaze</b> Save.<br/><b>Success</b><br/><b>Failure</b> Dazzled."
        ability = _abilities(html)[0]
        assert ability["failure"] == "Dazzled."
        assert "success" not in ability
