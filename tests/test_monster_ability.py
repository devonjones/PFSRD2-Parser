"""Monster ability parsing."""


class TestDegreeEffectsSurviveTheMergeList:
    """section_pass rebuilds the struct from _MERGE_FIELDS.

    The parsed ability is discarded after the copy, so a degree field missing
    from that tuple is gone with no trace. degree_effects was missing: the
    schema gained the property and no writer could ever fill it. Latent rather
    than live only because no published universal monster ability has damage
    in a degree yet -- which is precisely the shape of defect that ships.
    """

    def test_the_merge_list_carries_degree_effects(self):
        from pfsrd2.monster_ability import section_pass

        struct = {
            "name": "Test Breath",
            "type": "monster_ability",
            "text": (
                "The creature breathes."
                "<br/><b>Failure</b> The creature takes 2d6 fire damage."
                "<br/><b>Critical Failure</b> The creature takes 4d6 fire damage."
            ),
        }
        section_pass(struct)
        effects = {e["degree"]: e for e in struct["degree_effects"]}
        assert sorted(effects) == ["critical_failure", "failure"]
        assert effects["failure"]["damage"][0]["formula"] == "2d6"
        assert effects["failure"]["damage"][0]["damage_type"] == "fire"
        assert effects["critical_failure"]["damage"][0]["formula"] == "4d6"
