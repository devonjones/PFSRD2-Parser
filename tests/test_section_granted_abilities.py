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
