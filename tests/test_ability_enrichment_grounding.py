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

from pfsrd2.ability_enrichment import (
    a_number_the_source_never_published as ungrounded,
)
from pfsrd2.ability_enrichment import reject_if_ungrounded, rejection_reason

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
        monkeypatch.setattr(ae, "add_review_reason", lambda c, i, r: marked.append((i, r)))
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
        monkeypatch.setattr(ae, "add_review_reason", lambda c, i, r: marked.append((i, r)))
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


class TestTheRejectionCanBeRequeued:
    """A flagged record is re-queued by substring-matching its review_reason
    against run_llm's --llm-type. A reason that does not contain the type is a
    record nothing will ever pick up again -- and because the row is also
    cached, nothing will re-derive it either. Nine real saving_throw rows were
    parked exactly that way.
    """

    def test_a_field_whose_type_is_spelled_differently_still_names_the_type(self):
        reason = rejection_reason("saving_throw", "DC 20")
        assert "dc" in reason
        assert "saving_throw" in reason

    def test_every_extractor_field_produces_a_requeueable_reason(self):
        # Three of the four rows used to be unfalsifiable: the field name is
        # already in the reason, so for damage/area/frequency the assertion
        # held no matter what the map said. Checking the "--llm-type <x>"
        # marker instead makes every row depend on the mapping.
        for field, llm_type in (
            ("damage", "damage"),
            ("saving_throw", "dc"),
            ("area", "area"),
            ("frequency", "frequency"),
        ):
            assert f"--llm-type {llm_type}" in rejection_reason(field, "9d9")

    def test_the_map_is_derived_from_one_table_not_retyped(self):
        # A fifth extractor added without a mapping would park its rejections
        # forever, so the two directions must come from one source. They used
        # to be three hand-written copies that agreed by coincidence: dc fills
        # saving_throw, and the other three are spelled the same on both sides,
        # so a wrong entry would only ever show up as a stuck record.
        from pfsrd2.ability_enrichment import _LLM_TYPE_OF_FIELD, LLM_TYPE_FIELDS

        assert {f: t for t, f in LLM_TYPE_FIELDS.items()} == _LLM_TYPE_OF_FIELD
        assert LLM_TYPE_FIELDS["dc"] == "saving_throw"


class TestTheNumberIsMatchedWhole:
    """Both boundaries and the sign normalisation, each pinned separately.

    Every one of these was a real bug in the first version of the guard, found
    by measuring the corpus rather than by reading the regex: without them the
    guard either rejected every dice formula it saw or accepted numbers the
    source never wrote.
    """

    def test_a_number_is_not_grounded_by_a_longer_one_ending_in_it(self):
        # "20" occurs inside "120", but the source never says 20.
        assert ungrounded({"dc": 20}, "a cone 120 feet long") == "20"

    def test_a_number_is_not_grounded_by_a_longer_one_starting_with_it(self):
        assert ungrounded({"dc": 20}, "a cone 201 feet long") == "20"

    def test_a_dice_formula_is_not_grounded_by_a_longer_one(self):
        assert ungrounded({"damage": "1d6"}, "takes 11d6 fire damage") == "1d6"

    def test_spacing_around_a_sign_does_not_make_a_formula_ungrounded(self):
        # The source pretty-prints "4d6 + 2"; the extractor returns "4d6+2".
        # Without normalising the source, every signed formula read as
        # invented and the guard rejected real data.
        assert ungrounded({"damage": "4d6+2"}, "takes 4d6 + 2 slashing") is None

    def test_a_non_ascii_character_is_not_read_as_digits(self):
        # json.dumps escapes non-ASCII unless ensure_ascii=False, and an en-dash
        # becomes \u2013 -- whose digits the number regex then reads as "20132",
        # a value no source could ever contain. Every record with a dash in its
        # extracted text would be rejected as fabricated. This was found by
        # measurement, not by reading the line.
        assert ungrounded({"damage": "1\u20132 fire"}, "takes 1-2 fire damage") is None

    def test_a_grounded_formula_passes(self):
        assert ungrounded({"damage": "2d10+9"}, "takes 2d10+9 piercing") is None

    def test_the_d_in_the_lookbehind_is_load_bearing(self):
        # The lookbehind excludes a preceding "d" as well as a digit. Without
        # it, the bare number 6 would be grounded by the "6" inside "1d6" --
        # which is how a fabricated DC 6 could read as published.
        assert ungrounded({"dc": 6}, "takes 1d6 fire damage") == "6"

    def test_a_negative_modifier_is_normalised_too(self):
        # The sign normalisation strips spaces around BOTH signs. Only "+" was
        # pinned, so dropping "-" from the character class cost nothing.
        assert ungrounded({"damage": "4d6-1"}, "takes 4d6 - 1 slashing") is None


class TestRejectIfUngrounded:
    """The single shared copy of the guard, which both LLM paths now call.

    Driven against a real in-memory enrichment DB rather than a stub cursor:
    the behaviour that matters here is what lands in review_reason, and a stub
    that just records calls cannot see it.
    """

    def _db(self):
        from pfsrd2.sql.enrichment import get_enrichment_db_connection
        from pfsrd2.sql.enrichment.queries import insert_ability_record

        conn = get_enrichment_db_connection(":memory:")
        curs = conn.cursor()
        return conn, curs, insert_ability_record(curs, "Test Ability", "hash-1", "{}")

    def _reason(self, curs, ability_id):
        curs.execute(
            "SELECT review_reason FROM ability_records WHERE ability_id = ?",
            (ability_id,),
        )
        row = curs.fetchone()
        return row["review_reason"] if isinstance(row, dict) else row[0]

    def test_an_invented_number_is_rejected_and_flagged(self, capsys):
        conn, curs, aid = self._db()
        assert reject_if_ungrounded(
            {"dc": 30}, "a basic Reflex save", "saving_throw", (curs, aid, "X")
        )
        assert "dc" in self._reason(curs, aid)
        assert "REJECTED" in capsys.readouterr().err
        conn.close()

    def test_a_grounded_number_is_not_rejected_and_nothing_is_flagged(self, capsys):
        conn, curs, aid = self._db()
        assert not reject_if_ungrounded(
            {"damage": "2d6"}, "takes 2d6 fire", "damage", (curs, aid, "X")
        )
        assert self._reason(curs, aid) is None
        assert capsys.readouterr().err == ""
        conn.close()

    def test_a_dry_run_warns_without_writing(self, capsys):
        # The CLI passes mark=not args.dry_run. A dry run that wrote to the DB
        # would be the opposite of what the flag promises.
        conn, curs, aid = self._db()
        assert reject_if_ungrounded(
            {"dc": 30}, "a basic Reflex save", "saving_throw", (curs, aid, "X"), mark=False
        )
        assert self._reason(curs, aid) is None
        assert "REJECTED" in capsys.readouterr().err
        conn.close()

    def test_a_second_rejection_does_not_de_queue_the_first(self):
        # The bug this replaced. mark_needs_review REPLACES review_reason, and
        # bin/pf2_enrich_abilities selects records by substring-matching that
        # reason against --llm-type. So a record rejected for damage and then
        # for dc kept only the dc reason and silently fell out of the damage
        # queue -- with its damage value already cleared, nothing would ever
        # re-derive it.
        conn, curs, aid = self._db()
        reject_if_ungrounded({"damage": "9d9"}, "no dice here", "damage", (curs, aid, "X"))
        reject_if_ungrounded({"dc": 30}, "no dice here", "saving_throw", (curs, aid, "X"))
        reason = self._reason(curs, aid)
        assert "damage" in reason
        assert "dc" in reason
        conn.close()

    def test_the_same_rejection_twice_does_not_grow_the_reason(self):
        conn, curs, aid = self._db()
        reject_if_ungrounded({"damage": "9d9"}, "no dice here", "damage", (curs, aid, "X"))
        once = self._reason(curs, aid)
        reject_if_ungrounded({"damage": "9d9"}, "no dice here", "damage", (curs, aid, "X"))
        assert self._reason(curs, aid) == once
        conn.close()


class TestReasonsSurviveOtherPasses:
    """A reason is the queue. Anything that rewrites it can de-queue a record.

    The l59s rejection reason is what makes a cleared record selectable again,
    so every other pass that touches review_reason has to leave it alone. Two
    did not: the regex pass replaced the whole string, and the resolve path
    rebuilt it from the "unextracted:" clause only.
    """

    def _db(self):
        from pfsrd2.sql.enrichment import get_enrichment_db_connection
        from pfsrd2.sql.enrichment.queries import insert_ability_record

        conn = get_enrichment_db_connection(":memory:")
        curs = conn.cursor()
        return conn, curs, insert_ability_record(curs, "A", "h", "{}")

    def _reason(self, curs, aid):
        curs.execute("SELECT review_reason FROM ability_records WHERE ability_id = ?", (aid,))
        return curs.fetchone()["review_reason"]

    def test_a_later_flag_does_not_replace_an_l59s_reason(self):
        from pfsrd2.sql.enrichment.queries import add_review_reason

        conn, curs, aid = self._db()
        add_review_reason(curs, aid, rejection_reason("damage", "9d9"))
        add_review_reason(curs, aid, "unextracted: dc(1)")
        reason = self._reason(curs, aid)
        assert "--llm-type damage" in reason, "the l59s reason must survive"
        assert "unextracted: dc(1)" in reason
        conn.close()


class TestAddReviewReasonIsClauseWise:
    """The reason is the queue key, so how it merges is load-bearing."""

    def _db(self):
        from pfsrd2.sql.enrichment import get_enrichment_db_connection
        from pfsrd2.sql.enrichment.queries import insert_ability_record

        conn = get_enrichment_db_connection(":memory:")
        curs = conn.cursor()
        return conn, curs, insert_ability_record(curs, "A", "h", "{}")

    def _reason(self, curs, aid):
        curs.execute(
            "SELECT review_reason FROM ability_records WHERE ability_id = ?", (aid,)
        )
        return curs.fetchone()["review_reason"]

    def test_a_narrowed_reason_is_not_swallowed_as_already_present(self):
        # `reason in existing` is a substring test, and a narrowed reason is a
        # substring of the wider one it replaces. A pass that resolved damage
        # and re-flagged the remainder would have been dropped silently,
        # leaving the stale wider reason in the queue.
        from pfsrd2.sql.enrichment.queries import add_review_reason

        conn, curs, aid = self._db()
        add_review_reason(curs, aid, "unextracted: dc(1), damage(2)")
        add_review_reason(curs, aid, "unextracted: dc(1)")
        assert self._reason(curs, aid).count("unextracted:") == 2
        conn.close()

    def test_an_identical_clause_is_still_deduped(self):
        from pfsrd2.sql.enrichment.queries import add_review_reason

        conn, curs, aid = self._db()
        add_review_reason(curs, aid, "unextracted: dc(1)")
        add_review_reason(curs, aid, "unextracted: dc(1)")
        assert self._reason(curs, aid) == "unextracted: dc(1)"
        conn.close()

    def test_a_missing_record_raises_rather_than_silently_doing_nothing(self):
        # A wrong ability_id used to be a no-op UPDATE: the caller believed it
        # had flagged a record and nothing was flagged.
        import pytest

        from pfsrd2.sql.enrichment.queries import add_review_reason

        conn, curs, _ = self._db()
        with pytest.raises(ValueError, match="no ability_record"):
            add_review_reason(curs, 999999, "unextracted: dc(1)")
        conn.close()
