from pfsrd2.monster_template import _try_extract_changes


def _section(text):
    return {"name": "Host Abilities", "text": text, "sections": []}


GRANTING = (
    "All host creatures gain the following abilities.<br/>"
    "<b>Cold Stasis</b> The creature is vulnerable to cold.<br/>"
    "<b>Fumbling Dodge</b> <span class='action' title='Reaction'></span> "
    "The creature ducks awkwardly."
)

CHOOSING = (
    "The creature gains one of the following mutations.<br/>"
    "<b>Unusual Bane</b> Choose a creature type.<br/>"
    "<b>Explosive End</b> When the creature dies, it explodes."
)


class TestSectionGrantedAbilities:
    def test_granting_section_becomes_change(self):
        # "gain the following abilities" is a construction instruction: the
        # engine only auto-applies mt.abilities for templates with no changes
        # at all, so Broodpiercer's host abilities were silently dropped when
        # they lived at mt.abilities alongside its stat changes.
        mt = {"name": "Broodpiercer"}
        section = _section(GRANTING)
        assert _try_extract_changes(section, mt)
        assert "abilities" not in mt
        changes = mt["changes"]
        assert len(changes) == 1
        assert changes[0]["text"].startswith("All host creatures gain")
        names = [a["name"] for a in changes[0]["abilities"]]
        assert names == ["Cold Stasis", "Fumbling Dodge"]

    def test_choosing_section_stays_pool(self):
        # Choose-from pools must never become auto-applied changes.
        mt = {"name": "Mutant Cryptid"}
        section = _section(CHOOSING)
        assert _try_extract_changes(section, mt)
        assert "changes" not in mt
        assert [a["name"] for a in mt["abilities"]] == [
            "Unusual Bane",
            "Explosive End",
        ]

    def test_stat_block_inline_abilities_stay_pool(self):
        # Abilities inline in the stat block itself (source_section is mt)
        # keep the existing pool behavior even with granting wording.
        mt = {"name": "X", "text": GRANTING}
        assert _try_extract_changes(mt, mt)
        assert "changes" not in mt
        assert len(mt["abilities"]) == 2

    def test_granting_with_links_extracts_links(self):
        mt = {"name": "Experimental Cryptid"}
        html = (
            'A cryptid gains the <a aonid="6" game-obj="Traits">alchemical</a> '
            "trait. An experimental cryptid gains the following abilities.<br/>"
            "<b>Augmented</b> Body parts replaced."
        )
        section = _section(html)
        assert _try_extract_changes(section, mt)
        change = mt["changes"][0]
        assert "<a" not in change["text"]
        assert change["links"][0]["name"] == "alchemical"

    def test_granting_with_no_parseable_abilities_is_noop(self):
        mt = {"name": "X"}
        section = _section("All hosts gain the following abilities. Nothing here.")
        assert not _try_extract_changes(section, mt)
        assert "changes" not in mt

    def test_grant_before_ul_keeps_li_changes_first(self):
        # A granting section processed before the <ul> section must neither
        # block <li> extraction nor displace the primary change list.
        mt = {"name": "X"}
        assert _try_extract_changes(_section(GRANTING), mt)
        ul_section = _section("<ul><li>Increase the creature's level by 1.</li></ul>")
        assert _try_extract_changes(ul_section, mt)
        texts = [c["text"] for c in mt["changes"]]
        assert "Increase the creature's level" in texts[0]
        assert texts[1].startswith("All host creatures gain")

    def test_modal_grant_stays_pool(self):
        # "may gain the following abilities" is a choice, not a grant.
        mt = {"name": "X"}
        section = _section(
            "The creature may gain the following abilities.<br/>"
            "<b>Optional Thing</b> Something optional."
        )
        assert _try_extract_changes(section, mt)
        assert "changes" not in mt
        assert mt["abilities"][0]["name"] == "Optional Thing"

    def test_choice_abilities_section_becomes_change(self):
        # Choose-from ability pools become changes too — enrichment encodes
        # them as select effects the engine surfaces but never auto-applies.
        mt = {"name": "Rumored Cryptid"}
        section = _section(
            "The rumored cryptid might have one or both of the following "
            "optional abilities.<br/><b>Hybrid Form</b> Something.<br/>"
            "<b>Howl</b> Something else."
        )
        assert _try_extract_changes(section, mt)
        assert "abilities" not in mt
        change = mt["changes"][0]
        assert [a["name"] for a in change["abilities"]] == ["Hybrid Form", "Howl"]
