"""Tests for the unified ability parser in universal/ability.py."""

from bs4 import BeautifulSoup

from universal.ability import (
    parse_abilities_from_nodes,
    parse_ability_from_html,
)


def _make_nodes(html):
    """Parse HTML and return child nodes."""
    bs = BeautifulSoup(html, "html.parser")
    return list(bs.children)


class TestParseAbilitiesFromNodes:
    def test_simple_ability(self):
        nodes = _make_nodes('<b>Grab</b> The creature grabs.')
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Grab"
        assert "text" in abilities[0]

    def test_multiple_abilities(self):
        nodes = _make_nodes(
            '<b>Grab</b> The creature grabs.<br/><b>Push</b> It pushes.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 2
        assert abilities[0]["name"] == "Grab"
        assert abilities[1]["name"] == "Push"

    def test_linked_ability(self):
        nodes = _make_nodes(
            '<a href="/Abilities.aspx?ID=1"><b>Grab</b></a> The creature grabs.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Grab"
        assert "link" in abilities[0]

    def test_action_type_from_span(self):
        nodes = _make_nodes(
            '<b>Swift Leap</b> <span class="action" title="Single Action">'
            "[one-action]</span> The ghoul jumps."
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["action_type"]["name"] == "One Action"

    def test_parenthesized_traits(self):
        nodes = _make_nodes(
            '<b>Paralysis</b> (<a style="text-decoration:underline" href="Traits.aspx?ID=93" '
            'game-obj="Traits" aonid="93">incapacitation</a>, '
            '<a style="text-decoration:underline" href="Traits.aspx?ID=120" '
            'game-obj="Traits" aonid="120">occult</a>, '
            '<a style="text-decoration:underline" href="Traits.aspx?ID=117" '
            'game-obj="Traits" aonid="117">necromancy</a>) Any creature hit.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert len(abilities[0]["traits"]) == 3
        trait_names = {t["name"] for t in abilities[0]["traits"]}
        assert "incapacitation" in trait_names
        assert "occult" in trait_names

    def test_addon_merging(self):
        nodes = _make_nodes(
            "<b>Consume Flesh</b> "
            '<span class="action" title="Single Action">[one-action]</span> '
            "(manipulate) "
            "<b>Requirements</b> Adjacent to corpse. "
            "<b>Effect</b> Devours chunk."
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Consume Flesh"
        assert "requirement" in abilities[0]
        assert "effect" in abilities[0]
        assert abilities[0]["action_type"]["name"] == "One Action"

    def test_affliction_detection(self):
        nodes = _make_nodes(
            '<b>Ghoul Fever</b> (disease) '
            '<b>Saving Throw</b> DC 26 Fortitude; '
            '<b>Stage 1</b> carrier (1 day); '
            '<b>Stage 2</b> 3d8 negative damage (1 day); '
            '<b>Stage 3</b> dead'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Ghoul Fever"
        assert abilities[0]["ability_type"] == "affliction"
        assert "saving_throw" in abilities[0]
        assert len(abilities[0]["stages"]) == 3
        assert abilities[0]["stages"][0]["name"] == "Stage 1"

    def test_mixed_abilities_and_affliction(self):
        nodes = _make_nodes(
            '<b>Darkvision</b><br/>'
            '<b>Negative Healing</b><br/>'
            '<b>Ghoul Fever</b> (disease) '
            '<b>Saving Throw</b> Fortitude; '
            '<b>Stage 1</b> carrier; '
            '<b>Stage 2</b> damage<br/>'
            '<b>Paralysis</b> (incapacitation) Text.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 4
        assert abilities[0]["name"] == "Darkvision"
        assert abilities[2]["name"] == "Ghoul Fever"
        assert abilities[2]["ability_type"] == "affliction"
        assert abilities[3]["name"] == "Paralysis"
        assert abilities[3].get("ability_type") != "affliction"

    def test_saving_throw_as_array(self):
        """Saving Throw addon should produce array of save_dc objects."""
        nodes = _make_nodes(
            '<b>Ghoul Fever</b> (disease) '
            '<b>Saving Throw</b> DC 26 Fortitude; '
            '<b>Stage 1</b> carrier (1 day)'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        st = abilities[0]["saving_throw"]
        assert isinstance(st, list)
        assert len(st) == 1
        assert st[0]["subtype"] == "save_dc"
        assert st[0]["dc"] == 26
        assert st[0]["save_type"] == "Fort"

    def test_saving_throw_without_dc(self):
        """Freeform saving throw text should still produce array."""
        nodes = _make_nodes(
            '<b>Curse</b> '
            '<b>Saving Throw</b> Fortitude; '
            '<b>Stage 1</b> doomed 1'
        )
        abilities = parse_abilities_from_nodes(nodes)
        st = abilities[0]["saving_throw"]
        assert isinstance(st, list)
        assert st[0]["save_type"] == "Fort"
        assert "dc" not in st[0]

    def test_no_abilities(self):
        nodes = _make_nodes("just some text")
        result = parse_abilities_from_nodes(nodes)
        assert result is None

    def test_post_process_hook(self):
        processed = []

        def hook(ability):
            processed.append(ability["name"])

        nodes = _make_nodes("<b>Grab</b> text")
        parse_abilities_from_nodes(nodes, fxn_post_process=hook)
        assert processed == ["Grab"]


class TestParseAbilityFromHtml:
    def test_basic_ability(self):
        ability = parse_ability_from_html("Grab", "The creature grabs.")
        assert ability["name"] == "Grab"
        assert ability["text"] == "The creature grabs."

    def test_pre_extracted_action_type(self):
        action = {"type": "stat_block_section", "subtype": "action_type", "name": "One Action"}
        ability = parse_ability_from_html("Push", "It pushes.", action_type=action)
        assert ability["action_type"]["name"] == "One Action"

    def test_action_type_from_span(self):
        html = '<span class="action" title="Reaction">[reaction]</span> When hit.'
        ability = parse_ability_from_html("Shield Block", html)
        assert ability["action_type"]["name"] == "Reaction"

    def test_parenthesized_traits(self):
        html = (
            '(<a href="Traits.aspx?ID=46" game-obj="Traits" aonid="46">disease</a>, '
            '<a href="Traits.aspx?ID=126" game-obj="Traits" aonid="126">poison</a>) '
            "DC 20 Fort."
        )
        ability = parse_ability_from_html("Poison", html)
        assert len(ability["traits"]) == 2

    def test_bold_fields(self):
        html = "<b>Trigger</b> An enemy moves. <b>Effect</b> Strike."
        ability = parse_ability_from_html("Attack of Opportunity", html)
        assert ability["trigger"] == "An enemy moves."
        assert ability["effect"] == "Strike."

    def test_result_blocks(self):
        html = (
            "Make a check. "
            "<b>Critical Success</b> Great effect. "
            "<b>Success</b> Good effect. "
            "<b>Failure</b> Bad effect. "
            "<b>Critical Failure</b> Terrible effect."
        )
        ability = parse_ability_from_html("Recall Knowledge", html)
        assert "critical_success" in ability
        assert "success" in ability
        assert "failure" in ability
        assert "critical_failure" in ability

    def test_affliction(self):
        html = (
            "(disease) "
            "<b>Saving Throw</b> DC 26 Fortitude; "
            "<b>Stage 1</b> carrier (1 day); "
            "<b>Stage 2</b> damage (1 day)"
        )
        ability = parse_ability_from_html("Brain Rot", html)
        assert ability["ability_type"] == "affliction"
        assert "saving_throw" in ability
        assert len(ability["stages"]) == 2

    def test_custom_addon_labels(self):
        html = "<b>Access</b> Member of guild."
        # Default labels include Access
        ability = parse_ability_from_html("Guild Entry", html)
        assert ability.get("access") == "Member of guild."

        # Custom labels without Access
        ability2 = parse_ability_from_html(
            "Guild Entry", html, addon_labels={"Trigger"}
        )
        assert "access" not in ability2

    def test_link_extraction(self):
        html = 'Deals <a href="/Traits.aspx?ID=1">fire</a> damage.'
        ability = parse_ability_from_html("Burn", html)
        assert "links" in ability

    def test_post_process_hook(self):
        def hook(ability):
            ability["custom_field"] = True

        ability = parse_ability_from_html("Test", "text", fxn_post_process=hook)
        assert ability["custom_field"] is True
