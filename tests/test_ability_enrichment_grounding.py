"""Numbers an LLM returns must occur in the text it was given.

PFSRD2-Parser-l59s: extract_dc_llm returned "DC 30 basic Reflex" -- character for
character its own few-shot example in DC_PROMPT -- for the adamantine dragon's
Repelling Blast, whose text says only "a basic Reflex save of the same DC". The
string "DC 30" occurs nowhere on that source page. The value was indistinguishable
from real game data and took a corpus sweep to find.

The prompt ALREADY tells the model not to extract a DC that refers to another
creature's, so this is not a prompting problem and better wording will not close
it. The guard is deterministic instead: a model cannot invent a number that is
already in its input.
"""

import json

from pfsrd2.ability_enrichment import a_number_the_source_never_published as ungrounded

REPELLING_BLAST = (
    "The dragon expels scales from their body in a 50-foot emanation. Creatures "
    "in the area take slashing damage equal to the dragon's Avalanche Breath "
    "(with a basic Reflex save of the same DC)."
)
A_REAL_SAVE = (
    "Each creature must attempt a DC 32 Fortitude save or take 4d6+2 poison "
    "damage and 1d6 persistent fire damage."
)


class TestUngroundedNumbers:
    def test_the_l59s_case_is_caught(self):
        assert (
            ungrounded(
                [{"dc": 30, "save_type": "Ref", "text": "DC 30 basic Reflex"}],
                REPELLING_BLAST,
            )
            == "30"
        )

    def test_a_number_the_text_does_state_is_accepted(self):
        assert ungrounded([{"range": 50, "text": "50 feet"}], REPELLING_BLAST) is None
        assert ungrounded([{"dc": 32, "text": "DC 32 Fortitude"}], A_REAL_SAVE) is None

    def test_dice_are_matched_whole(self):
        # The first version of this guard split "4d6+2" into 4, 6 and 2 and then
        # looked for a bare 4. In "4d6" the digit is followed by a word
        # character, so there is no word boundary and EVERY dice formula read as
        # ungrounded.
        assert ungrounded([{"formula": "4d6+2"}], A_REAL_SAVE) is None
        assert ungrounded([{"formula": "1d6"}], A_REAL_SAVE) is None

    def test_dice_the_text_does_not_state_are_caught(self):
        assert ungrounded([{"formula": "9d6"}], A_REAL_SAVE) == "9d6"

    def test_a_bare_number_is_not_grounded_by_a_longer_one(self):
        # "5" must not be satisfied by the "50" in "50-foot emanation".
        assert ungrounded([{"dc": 5, "text": "DC 5"}], REPELLING_BLAST) == "5"

    def test_words_are_not_checked_only_digits(self):
        # A model may legitimately normalise a damage type or save name; those
        # are not what it fabricates. Only numbers are checked.
        assert ungrounded([{"formula": "4d6+2", "damage_type": "void"}], A_REAL_SAVE) is None

    def test_nothing_extracted_is_not_a_violation(self):
        assert ungrounded(None, A_REAL_SAVE) is None
        assert ungrounded([], A_REAL_SAVE) is None


class TestTheRejectPathActuallyRejects:
    """The guard's *effect*, not just its predicate.

    PFSRD2-Parser-l59s. Round 3 found this branch had zero coverage: mutations
    that never rejected, that logged and then assigned anyway, and that silenced
    the warning ALL left the suite green. The predicate was tested; what the
    caller does with it was not.
    """

    UNGROUNDED = [{"dc": 30, "save_type": "Ref", "text": "DC 30 basic Reflex"}]
    SOURCE = "Creatures take slashing damage (with a basic Reflex save of the same DC)."

    def _run(self, monkeypatch, llm_result):
        """Drive _try_inline_enrich with a stubbed extractor and a fake cursor."""
        import pfsrd2.ability_enrichment as ae

        marked = []
        monkeypatch.setattr(
            ae,
            "extract_all",
            lambda j: (json.loads(j) if isinstance(j, str) else dict(j), ["dc"]),
        )
        monkeypatch.setattr(ae, "update_enriched_json", lambda *a, **k: None)
        monkeypatch.setattr(ae, "mark_needs_review", lambda c, i, r: marked.append((i, r)))
        import pfsrd2.enrichment.llm_extractor as le

        monkeypatch.setattr(le, "extract_dc_llm", lambda name, text: llm_result)
        raw = json.dumps({"name": "Repelling Blast", "text": self.SOURCE, "type": "ability"})
        out = ae._try_inline_enrich(object(), 17662, raw)
        return json.loads(out) if out else None, marked

    def test_an_ungrounded_value_is_not_assigned(self, monkeypatch, capsys):
        result, marked = self._run(monkeypatch, self.UNGROUNDED)
        assert not (result or {}).get(
            "saving_throw"
        ), "a number absent from the ability text must not reach the record"
        assert "REJECTED" in capsys.readouterr().err
        assert marked, "the rejection must be durable, not only on stderr"
        assert "l59s" in marked[0][1]

    def test_a_grounded_value_is_assigned(self, monkeypatch):
        # Same path, a number the text does state -- proves the reject branch is
        # selective rather than always-on.
        import pfsrd2.ability_enrichment as ae

        marked = []
        monkeypatch.setattr(
            ae,
            "extract_all",
            lambda j: (json.loads(j) if isinstance(j, str) else dict(j), ["dc"]),
        )
        monkeypatch.setattr(ae, "update_enriched_json", lambda *a, **k: None)
        monkeypatch.setattr(ae, "mark_needs_review", lambda c, i, r: marked.append((i, r)))
        import pfsrd2.enrichment.llm_extractor as le

        monkeypatch.setattr(
            le, "extract_dc_llm", lambda n, t: [{"dc": 25, "text": "DC 25 basic Reflex"}]
        )
        raw = json.dumps(
            {
                "name": "Fling Foe",
                "text": "The creature takes damage (DC 25 basic Fortitude save).",
                "type": "ability",
            }
        )
        out = ae._try_inline_enrich(object(), 1, raw)
        assert json.loads(out)["saving_throw"][0]["dc"] == 25
        assert marked == []
