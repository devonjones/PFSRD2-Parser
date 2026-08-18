"""Hermetic tests for the degree-exemption verifier's pure functions.

Same reasoning as the rune verifier: the walkers are the oracle the verifier
trusts, so an over-matching walker would report every dead entry as live and
the check would pass forever. They take already-loaded docs, so they test
without touching the data repo.
"""

from pfsrd2.qa.degree_exemptions import (
    count_deferred_carriers,
    dead_entries,
    published_degree_texts,
)


class TestPublishedDegreeTexts:
    def test_a_named_carrier_keys_on_its_own_name(self):
        doc = {"name": "Endsong", "critical_failure": "its Strikes resonate"}
        assert published_degree_texts([doc]) == {
            ("Endsong", "critical_failure"): ["its Strikes resonate"]
        }

    def test_an_unnamed_carrier_keys_on_the_nearest_enclosing_name(self):
        # This is the case that matters: spell_defense, save_results and
        # routine_results have no name, and 836 of the corpus's 2582 degree
        # carriers are one of those three. Keying them on None would make
        # every exemption for them read as dead.
        doc = {
            "name": "Rewrite Memory",
            "defense": {"subtype": "spell_defense", "failure": "the 5 minutes"},
        }
        assert list(published_degree_texts([doc])) == [("Rewrite Memory", "failure")]

    def test_the_nearest_name_wins_over_an_outer_one(self):
        doc = {
            "name": "Gorlak",
            "abilities": [{"name": "Fling Foe", "success": "1d10+9 piercing"}],
        }
        assert list(published_degree_texts([doc])) == [("Fling Foe", "success")]

    def test_an_empty_degree_is_not_published(self):
        # An empty string is a degree the parser wrote nothing into. Counting
        # it would keep an exemption alive on a degree that no longer says
        # anything -- exactly the dead entry this verifier hunts.
        assert published_degree_texts([{"name": "X", "failure": "   "}]) == {}

    def test_a_non_string_degree_is_not_published(self):
        assert published_degree_texts([{"name": "X", "failure": None}]) == {}

    def test_two_carriers_under_one_name_both_land_under_the_key(self):
        # A name is not a unique handle -- 28 keys in the corpus match two
        # carriers in the same file. The phrase check needs to see both, which
        # is why this returns a list and not a set of keys.
        doc = {
            "name": "Activate",
            "a": {"failure": "first text"},
            "b": {"failure": "second text"},
        }
        assert published_degree_texts([doc])[("Activate", "failure")] == [
            "first text",
            "second text",
        ]


class TestDeadEntries:
    _TABLE = {("Endsong", "critical_failure"): ("its Strikes", "not its damage")}

    def test_a_matched_key_with_its_phrase_is_not_dead(self):
        texts = {("Endsong", "critical_failure"): ["its Strikes resonate"]}
        assert dead_entries(self._TABLE, texts) == []

    def test_an_unmatched_key_is_dead_and_carries_its_reason(self):
        texts = {("Endsong", "success"): ["its Strikes resonate"]}
        dead = dead_entries(self._TABLE, texts)
        assert len(dead) == 1
        assert dead[0][0] == ("Endsong", "critical_failure")
        assert dead[0][1] == "not its damage"

    def test_a_rename_reads_as_dead(self):
        # The key never matches, so no per-parse assert can fire -- the
        # suppressed dice would republish silently.
        texts = {("Endsong Reprise", "critical_failure"): ["its Strikes resonate"]}
        assert len(dead_entries(self._TABLE, texts)) == 1

    def test_a_reword_reads_as_dead_even_though_the_key_still_matches(self):
        # The second way an exemption dies, and the one a parse cannot see: the
        # object is still there under the same name, but the sentence the
        # exemption was granted for is gone.
        texts = {("Endsong", "critical_failure"): ["the target takes 1d6 sonic"]}
        dead = dead_entries(self._TABLE, texts)
        assert len(dead) == 1
        assert "pinned phrase" in dead[0][2]

    def test_the_phrase_only_has_to_survive_in_ONE_matching_carrier(self):
        # With two carriers under one name, the exemption still applies to the
        # one that kept the phrase. Requiring it in all of them would report a
        # live exemption as dead every time a same-named neighbour exists.
        texts = {
            ("Endsong", "critical_failure"): [
                "the target takes 4d6 sonic damage",
                "its Strikes resonate with the song",
            ]
        }
        assert dead_entries(self._TABLE, texts) == []


class TestCountDeferredCarriers:
    def test_counts_the_carrier_not_the_degrees_on_it(self):
        doc = {"a": {"success": "x", "failure": "y"}}
        assert count_deferred_carriers([doc]) == 1

    def test_counts_through_lists(self):
        doc = {"items": [{"success": "x"}, {"failure": "y"}, {"name": "no degrees"}]}
        assert count_deferred_carriers([doc]) == 2


class TestMain:
    """The function bin/pf2_verify_degree_exemptions actually runs.

    Driven through the PF2_DATA_DIR override, the same way the other qa
    verifiers are tested. Without this the module's pure walkers were covered
    and the thing calling them was not -- which is the shape of the bug that
    put 57 of the 63 l59s records past a guard that existed.
    """

    def _corpus(self, tmp_path, docs):
        import json

        for name, doc in docs.items():
            directory = tmp_path / "monsters"
            directory.mkdir(exist_ok=True)
            (directory / f"{name}.json").write_text(json.dumps(doc))

    def test_a_live_exemption_passes(self, tmp_path, monkeypatch, capsys):
        from pfsrd2.constants import DEGREE_EFFECT_NOT_THE_SUBJECTS
        from pfsrd2.qa import degree_exemptions

        # Publish every exemption's own key AND its pinned phrase, so nothing
        # is dead. Built from the table rather than hand-listed: adding a
        # seventh exemption must not make this test wrong.
        docs = {}
        for i, ((name, degree), (phrase, _why)) in enumerate(
            list(DEGREE_EFFECT_NOT_THE_SUBJECTS.items())
        ):
            docs.setdefault(f"doc{i}", {"name": name})[degree] = f"... {phrase} ..."
        from pfsrd2.constants import DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK

        for i, ((name, degree), (phrase, _why)) in enumerate(
            list(DEGREE_CONTINUES_PAST_A_PARAGRAPH_BREAK.items())
        ):
            docs[f"cont{i}"] = {"name": name, degree: f"... {phrase} ..."}
        self._corpus(tmp_path, docs)
        monkeypatch.setenv("PF2_DATA_DIR", str(tmp_path))
        assert degree_exemptions.main() == 0
        assert "still names a real, published degree" in capsys.readouterr().out

    def test_an_empty_corpus_fails_rather_than_reporting_success(
        self, tmp_path, monkeypatch, capsys
    ):
        # The trap every corpus verifier has: with no data loaded, every
        # exemption reads as dead OR every check passes vacuously. Either way
        # the answer is meaningless, so it must not exit 0 quietly.
        monkeypatch.setenv("PF2_DATA_DIR", str(tmp_path))
        assert degree_exemptions_main() == 1
        assert "no data found" in capsys.readouterr().out

    def test_a_dead_exemption_fails_and_names_it(self, tmp_path, monkeypatch, capsys):
        from pfsrd2.qa import degree_exemptions

        self._corpus(tmp_path, {"unrelated": {"name": "Nothing", "failure": "x"}})
        monkeypatch.setenv("PF2_DATA_DIR", str(tmp_path))
        assert degree_exemptions.main() == 1
        out = capsys.readouterr().out
        assert "DEAD EXEMPTIONS" in out
        assert "Endsong" in out


def degree_exemptions_main():
    from pfsrd2.qa import degree_exemptions

    return degree_exemptions.main()
