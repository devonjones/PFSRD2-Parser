"""Hermetic tests for the degree-exemption verifier's pure functions.

Same reasoning as the rune verifier: the walkers are the oracle the verifier
trusts, so an over-matching walker would report every dead entry as live and
the check would pass forever. They take already-loaded docs, so they test
without touching the data repo.
"""

from pfsrd2.qa.degree_exemptions import (
    count_deferred_carriers,
    dead_entries,
    published_degree_keys,
)


class TestPublishedDegreeKeys:
    def test_a_named_carrier_keys_on_its_own_name(self):
        doc = {"name": "Endsong", "critical_failure": "its Strikes resonate"}
        assert published_degree_keys([doc]) == {("Endsong", "critical_failure")}

    def test_an_unnamed_carrier_keys_on_the_nearest_enclosing_name(self):
        # This is the case that matters: spell_defense, save_results and
        # routine_results have no name, and 836 of the corpus's 2582 degree
        # carriers are one of those three. Keying them on None would make
        # every exemption for them read as dead.
        doc = {
            "name": "Rewrite Memory",
            "defense": {"subtype": "spell_defense", "failure": "the 5 minutes"},
        }
        assert published_degree_keys([doc]) == {("Rewrite Memory", "failure")}

    def test_the_nearest_name_wins_over_an_outer_one(self):
        doc = {
            "name": "Gorlak",
            "abilities": [{"name": "Fling Foe", "success": "1d10+9 piercing"}],
        }
        assert published_degree_keys([doc]) == {("Fling Foe", "success")}

    def test_an_empty_degree_is_not_published(self):
        # An empty string is a degree the parser wrote nothing into. Counting
        # it would keep an exemption alive on a degree that no longer says
        # anything -- exactly the dead entry this verifier hunts.
        assert published_degree_keys([{"name": "X", "failure": "   "}]) == set()

    def test_a_non_string_degree_is_not_published(self):
        assert published_degree_keys([{"name": "X", "failure": None}]) == set()


class TestDeadEntries:
    _TABLE = {("Endsong", "critical_failure"): ("its Strikes", "not its damage")}

    def test_a_matched_key_is_not_dead(self):
        assert dead_entries(self._TABLE, {("Endsong", "critical_failure")}) == []

    def test_an_unmatched_key_is_dead_and_carries_its_reason(self):
        assert dead_entries(self._TABLE, {("Endsong", "success")}) == [
            (("Endsong", "critical_failure"), "not its damage")
        ]

    def test_a_rename_reads_as_dead(self):
        # The failure mode the verifier exists for. The pinned phrase never
        # fires on a rename, because the pin is only consulted once the KEY
        # matches -- so the suppressed dice would republish silently.
        assert len(dead_entries(self._TABLE, {("Endsong Reprise", "critical_failure")})) == 1


class TestCountDeferredCarriers:
    def test_counts_the_carrier_not_the_degrees_on_it(self):
        doc = {"a": {"success": "x", "failure": "y"}}
        assert count_deferred_carriers([doc]) == 1

    def test_counts_through_lists(self):
        doc = {"items": [{"success": "x"}, {"failure": "y"}, {"name": "no degrees"}]}
        assert count_deferred_carriers([doc]) == 2
