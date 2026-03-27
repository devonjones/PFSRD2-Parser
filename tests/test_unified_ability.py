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
        # Trait links must use real <a game-obj="Traits"> elements, not bare text
        # like "(manipulate)". The parser uses strategic fragility to assert that
        # parenthesized text at the start of an ability has proper trait links.
        # Bare trait text triggers an assertion — the fix is in the HTML, not the parser.
        nodes = _make_nodes(
            "<b>Consume Flesh</b> "
            '<span class="action" title="Single Action">[one-action]</span> '
            '(<a href="Traits.aspx?ID=104" game-obj="Traits" aonid="104">manipulate</a>) '
            "<b>Requirements</b> Adjacent to corpse. "
            "<b>Effect</b> Devours chunk."
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Consume Flesh"
        assert "requirement" in abilities[0]
        assert "effect" in abilities[0]
        assert abilities[0]["action_type"]["name"] == "One Action"
        assert len(abilities[0]["traits"]) == 1
        assert abilities[0]["traits"][0]["name"] == "manipulate"

    def test_affliction_detection(self):
        # Trait links must be real <a game-obj="Traits"> — see test_addon_merging comment.
        nodes = _make_nodes(
            '<b>Ghoul Fever</b> (<a href="Traits.aspx?ID=46" game-obj="Traits" aonid="46">disease</a>) '
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
            '<b>Ghoul Fever</b> (<a href="Traits.aspx?ID=46" game-obj="Traits" aonid="46">disease</a>) '
            '<b>Saving Throw</b> Fortitude; '
            '<b>Stage 1</b> carrier; '
            '<b>Stage 2</b> damage<br/>'
            '<b>Paralysis</b> (<a href="Traits.aspx?ID=93" game-obj="Traits" aonid="93">incapacitation</a>) Text.'
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
            '<b>Ghoul Fever</b> (<a href="Traits.aspx?ID=46" game-obj="Traits" aonid="46">disease</a>) '
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
        # Trait links must be real <a game-obj="Traits"> — see TestParseAbilitiesFromNodes
        # test_addon_merging comment for why bare "(disease)" would fail.
        html = (
            '(<a href="Traits.aspx?ID=46" game-obj="Traits" aonid="46">disease</a>) '
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


class TestBoldWrappedLinkPattern:
    """Tests for <b><a>Name</a></b> pattern (link inside bold)."""

    def test_bold_wrapping_link(self):
        """<b><a href="MonsterAbilities.aspx?ID=12">Darkvision</a></b> should extract the link."""
        nodes = _make_nodes(
            '<b><a style="text-decoration:underline" href="MonsterAbilities.aspx?ID=12" '
            'game-obj="MonsterAbilities" aonid="12">Darkvision</a></b>'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["name"] == "Darkvision"
        assert abilities[0]["link"]["game-obj"] == "MonsterAbilities"

    def test_bold_wrapping_link_triggers_uma(self):
        """<b><a> to MonsterAbilities should trigger UMA skeleton detection."""
        nodes = _make_nodes(
            '<b><a href="MonsterAbilities.aspx?ID=42" '
            'game-obj="MonsterAbilities" aonid="42">Negative Healing</a></b>'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert "universal_monster_ability" in abilities[0]
        assert abilities[0]["universal_monster_ability"]["game-obj"] == "MonsterAbilities"

    def test_multiple_bold_wrapped_links(self):
        """Multiple <b><a>Name</a></b> abilities separated by <br>."""
        nodes = _make_nodes(
            '<b><a href="MonsterAbilities.aspx?ID=12" game-obj="MonsterAbilities" '
            'aonid="12">Darkvision</a></b><br/>'
            '<b><a href="MonsterAbilities.aspx?ID=42" game-obj="MonsterAbilities" '
            'aonid="42">Negative Healing</a></b>'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 2
        assert abilities[0]["link"]["game-obj"] == "MonsterAbilities"
        assert abilities[1]["link"]["game-obj"] == "MonsterAbilities"


class TestTraitExtractionCleanup:
    """Tests for text cleanup after trait extraction."""

    def test_semicolon_after_traits_removed(self):
        """Leading semicolon after trait extraction should be cleaned."""
        nodes = _make_nodes(
            '<b>Drain Life</b> (<a href="Traits.aspx?ID=48" '
            'game-obj="Traits" aonid="48">divine</a>, '
            '<a href="Traits.aspx?ID=117" game-obj="Traits" '
            'aonid="117">necromancy</a>); When the creature damages a target.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert abilities[0]["text"].startswith("When")
        assert not abilities[0]["text"].startswith(";")

    def test_non_trait_parentheses_preserved(self):
        """Parenthesized text that isn't a trait should be preserved in text."""
        nodes = _make_nodes(
            '<b>Mythic Weakness</b> (Frailty) A mythic ambusher relies on stealth.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert "(Frailty)" in abilities[0]["text"]


class TestAuraParsing:
    """Tests for aura stat extraction from ability text."""

    def test_aura_range_extracted(self):
        """Aura with range should extract structured range object."""
        nodes = _make_nodes(
            '<b>Stench</b> (<a href="Traits.aspx?ID=206" game-obj="Traits" '
            'aonid="206">aura</a>, <a href="Traits.aspx?ID=246" game-obj="Traits" '
            'aonid="246">olfactory</a>) 30 feet. A creature entering the area.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert len(abilities) == 1
        assert "range" in abilities[0]
        assert abilities[0]["range"]["range"] == 30
        assert abilities[0]["range"]["unit"] == "feet"
        # Stats sentence removed from text
        assert abilities[0]["text"] == "A creature entering the area."

    def test_aura_range_and_dc(self):
        """Aura with range and DC should extract both."""
        nodes = _make_nodes(
            '<b>Frightful Presence</b> (<a href="Traits.aspx?ID=206" game-obj="Traits" '
            'aonid="206">aura</a>) 30 feet, DC 22 Will. Creatures in the area.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        ab = abilities[0]
        assert ab["range"]["range"] == 30
        assert len(ab["saving_throw"]) == 1
        assert ab["saving_throw"][0]["dc"] == 22
        assert ab["text"] == "Creatures in the area."

    def test_aura_with_damage(self):
        """Aura with damage should extract structured damage."""
        nodes = _make_nodes(
            '<b>Heat</b> (<a href="Traits.aspx?ID=206" game-obj="Traits" '
            'aonid="206">aura</a>) 10 feet, 2d6 fire damage. Burns nearby.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        ab = abilities[0]
        assert ab["range"]["range"] == 10
        assert "damage" in ab
        assert ab["text"] == "Burns nearby."

    def test_non_aura_trait_no_extraction(self):
        """Abilities without aura trait should not trigger aura parsing."""
        nodes = _make_nodes(
            '<b>Fire Shield</b> (<a href="Traits.aspx?ID=48" game-obj="Traits" '
            'aonid="48">divine</a>) 30 feet. A wall of flame.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        # No range extracted because no aura trait
        assert "range" not in abilities[0]

    def test_aura_no_stats_in_text(self):
        """Aura without stats in first sentence should not extract."""
        nodes = _make_nodes(
            '<b>Calm Emotions</b> (<a href="Traits.aspx?ID=206" game-obj="Traits" '
            'aonid="206">aura</a>) Allies nearby feel at peace.'
        )
        abilities = parse_abilities_from_nodes(nodes)
        assert "range" not in abilities[0]
        assert "Allies nearby feel at peace" in abilities[0]["text"]
