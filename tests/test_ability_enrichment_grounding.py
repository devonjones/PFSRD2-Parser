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

from pfsrd2.ability_enrichment import _a_number_the_source_never_published as ungrounded

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
