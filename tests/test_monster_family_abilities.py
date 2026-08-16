"""Degrees of success on monster family and template abilities.

A bold label the ability parser does not recognise starts a NEW ability. The
degree-of-success labels were not in DEFAULT_ADDON_LABELS, so every published
"Success" / "Failure" became its own entry sitting beside the ability that
rolled the check — 68 of them across monster_families/, and the text was
detached from the ability it belonged to.

Hazards already solved this by unioning RESULT_LABELS into their addon set;
families and templates now do the same.
"""

from bs4 import BeautifulSoup

from pfsrd2.monster_family import _FAMILY_ADDON_LABELS
from pfsrd2.monster_template import _FAMILY_ADDON_LABELS as _TEMPLATE_ADDON_LABELS
from universal.ability import DEFAULT_ADDON_LABELS, parse_abilities_from_nodes
from universal.universal import RESULT_LABELS

BREATH = (
    "<b>Cloud of Ashes</b> The dragon exhales a cloud of ash."
    "<br/><b>Success</b> The creature is unaffected."
    "<br/><b>Failure</b> The creature begins coughing."
    "<br/><b>Critical Failure</b> As failure, plus it spends its next action coughing."
)


def _abilities(html, labels=_FAMILY_ADDON_LABELS):
    nodes = list(BeautifulSoup(html, "html.parser").children)
    return parse_abilities_from_nodes(nodes, addon_labels=labels)


class TestAddonLabelSets:
    def test_the_family_set_covers_every_degree_of_success(self):
        assert set(RESULT_LABELS) <= _FAMILY_ADDON_LABELS

    def test_templates_use_the_same_set(self):
        assert _TEMPLATE_ADDON_LABELS == _FAMILY_ADDON_LABELS

    def test_it_is_a_superset_of_the_default(self):
        # Widened, not replaced — Trigger/Effect/Requirements still apply.
        assert DEFAULT_ADDON_LABELS < _FAMILY_ADDON_LABELS


class TestDegreesFoldIntoTheirAbility:
    def test_one_ability_not_four(self):
        abilities = _abilities(BREATH)
        assert [a["name"] for a in abilities] == ["Cloud of Ashes"]

    def test_the_degree_text_lands_on_the_ability(self):
        ability = _abilities(BREATH)[0]
        assert ability["success"] == "The creature is unaffected."
        assert ability["failure"] == "The creature begins coughing."
        assert ability["critical_failure"].startswith("As failure")

    def test_without_the_result_labels_they_split_apart(self):
        # Pins why the set has to be widened: this is the shipped bug.
        names = [a["name"] for a in _abilities(BREATH, labels=DEFAULT_ADDON_LABELS)]
        assert names == ["Cloud of Ashes", "Success", "Failure", "Critical Failure"]

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
