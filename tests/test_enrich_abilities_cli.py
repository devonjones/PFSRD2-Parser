"""End-to-end tests for bin/pf2_enrich_abilities' LLM path.

This is the path that produced 57 of the 63 poisoned records in
PFSRD2-Parser-l59s: an extractor loop identical to the inline one, with no
grounding guard at all. It was covered only by grep-for-a-substring tests,
which a reviewer showed the original defect would pass -- so it is driven for
real here, against an in-memory DB with a stubbed extractor.

The CLI guards `if __name__ == "__main__"`, so importing it runs nothing.
"""

import importlib.machinery
import importlib.util
import json
import os

import pytest

CLI = os.path.join(os.path.dirname(__file__), "..", "bin", "pf2_enrich_abilities")


def load_cli():
    spec = importlib.util.spec_from_loader(
        "pf2_enrich_abilities",
        importlib.machinery.SourceFileLoader("pf2_enrich_abilities", CLI),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Args:
    def __init__(self, **kw):
        # Only the flags the CLI actually defines. `limit` and `verbose` were
        # carried here for flags that do not exist, which makes the stub read
        # like documentation of an interface it is not.
        self.llm_type = kw.get("llm_type", "damage")
        self.dry_run = kw.get("dry_run", False)
        self.model = kw.get("model", "test-model")
        self.force_version = kw.get("force_version", False)


@pytest.fixture
def db():
    from pfsrd2.sql.enrichment import get_enrichment_db_connection

    conn = get_enrichment_db_connection(":memory:")
    yield conn
    conn.close()


def _flagged_record(conn, text, reason):
    from pfsrd2.sql.enrichment.queries import insert_ability_record, mark_needs_review

    curs = conn.cursor()
    raw = json.dumps({"name": "Test Ability", "text": text})
    ability_id = insert_ability_record(curs, "Test Ability", "hash-1", raw)
    mark_needs_review(curs, ability_id, reason)
    conn.commit()
    return ability_id


def _row(conn, ability_id):
    curs = conn.cursor()
    curs.execute("SELECT * FROM ability_records WHERE ability_id = ?", (ability_id,))
    return curs.fetchone()


class TestTheBatchPathIsGuarded:
    def test_an_invented_number_is_never_written_to_the_cache(self, db, monkeypatch):
        # The l59s defect exactly: the model returns a DC the source never
        # published. Before the guard reached this path, this value was cached
        # and shipped, indistinguishable from real game data.
        cli = load_cli()
        ability_id = _flagged_record(
            db, "a basic Reflex save of the same DC", "unextracted: dc(1) --llm-type dc"
        )
        monkeypatch.setattr(
            cli, "extract_dc_llm", lambda name, text, **kw: {"dc": 30, "text": "DC 30 basic Reflex"}
        )
        cli.run_llm(db, Args(llm_type="dc"))

        row = _row(db, ability_id)
        assert row["enriched_json"] is None, "an ungrounded value must not be cached"
        assert row["needs_review"] == 1
        assert "--llm-type dc" in row["review_reason"], "the record must stay re-queueable"

    def test_a_grounded_number_is_written(self, db, monkeypatch):
        # The guard must not reject real extractions -- an over-eager version
        # would quietly stop the whole pipeline enriching anything.
        cli = load_cli()
        ability_id = _flagged_record(
            db, "takes 4d6 fire damage", "unextracted: damage(1) --llm-type damage"
        )
        monkeypatch.setattr(
            cli,
            "extract_damage_llm",
            lambda name, text, **kw: [{"formula": "4d6", "damage_type": "fire"}],
        )
        cli.run_llm(db, Args(llm_type="damage"))

        row = _row(db, ability_id)
        assert row["enriched_json"] is not None
        assert "4d6" in row["enriched_json"]

    def test_the_guard_reads_the_field_the_type_maps_to(self, db, monkeypatch):
        # dc fills saving_throw. If the mapping were retyped wrongly the guard
        # would check the wrong field, and a mismapped CLI would still pass a
        # test that only greps for the call.
        cli = load_cli()
        assert cli.LLM_TYPE_FIELDS["dc"] == "saving_throw"
        ability_id = _flagged_record(
            db, "no numbers at all here", "unextracted: dc(1) --llm-type dc"
        )
        monkeypatch.setattr(cli, "extract_dc_llm", lambda name, text, **kw: {"dc": 99})
        cli.run_llm(db, Args(llm_type="dc"))
        assert "99" in _row(db, ability_id)["review_reason"]


class TestTheStrandedRequeue:
    def test_a_cleared_value_that_still_claims_a_version_is_requeued(self, db):
        # fetch_unenriched selects on enrichment_version IS NULL and
        # fetch_stale on stale = 1, so a row with a cleared enriched_json and a
        # version still set is in neither queue. 61 rows were left that way.
        cli = load_cli()
        from pfsrd2.sql.enrichment.queries import insert_ability_record

        curs = db.cursor()
        ability_id = insert_ability_record(curs, "A", "h", json.dumps({"name": "A"}))
        curs.execute(
            "UPDATE ability_records SET enriched_json = NULL, enrichment_version = 2,"
            " stale = 0 WHERE ability_id = ?",
            (ability_id,),
        )
        db.commit()

        cli.run_audit_enriched(db, Args())
        assert _row(db, ability_id)["enrichment_version"] is None

    def test_a_dry_run_does_not_requeue(self, db):
        cli = load_cli()
        from pfsrd2.sql.enrichment.queries import insert_ability_record

        curs = db.cursor()
        ability_id = insert_ability_record(curs, "A", "h", json.dumps({"name": "A"}))
        curs.execute(
            "UPDATE ability_records SET enriched_json = NULL, enrichment_version = 2,"
            " stale = 0 WHERE ability_id = ?",
            (ability_id,),
        )
        db.commit()

        cli.run_audit_enriched(db, Args(dry_run=True))
        assert _row(db, ability_id)["enrichment_version"] == 2


class TestReasonsSurviveTheRegexPass:
    """`run_regex` and `_update_review_flag` both rewrite review_reason, and the
    reason IS the queue: `run_llm` selects records by substring-matching it
    against --llm-type. Either one dropping a clause de-queues the record, and
    a record whose value was already cleared then has nothing to re-derive it.

    Both were previously covered only by a test that re-implemented the string
    split rather than calling either function.
    """

    def _flagged(self, conn, reason, text="no numbers here"):
        from pfsrd2.sql.enrichment.queries import insert_ability_record, mark_needs_review

        curs = conn.cursor()
        raw = json.dumps({"name": "Test Ability", "text": text})
        ability_id = insert_ability_record(curs, "Test Ability", "h", raw)
        mark_needs_review(curs, ability_id, reason)
        conn.commit()
        return curs, ability_id

    def _reason(self, conn, ability_id):
        curs = conn.cursor()
        curs.execute(
            "SELECT review_reason FROM ability_records WHERE ability_id = ?", (ability_id,)
        )
        return curs.fetchone()["review_reason"]

    def test_run_regex_does_not_replace_an_existing_l59s_reason(self, db):
        # run_regex used to call mark_needs_review, which replaces. Any record
        # it touched lost the l59s rejection that was re-queueing it.
        from pfsrd2.ability_enrichment import rejection_reason

        cli = load_cli()
        l59s = rejection_reason("damage", "9d9")
        curs, ability_id = self._flagged(
            db, l59s, text="The target is knocked prone and takes fire damage."
        )
        db.commit()
        cli.run_regex(db, Args())
        assert "--llm-type damage" in self._reason(db, ability_id)

    def test_resolving_one_type_keeps_the_clauses_it_did_not_resolve(self, db):
        # _update_review_flag rebuilds the "unextracted:" clause from scratch.
        # It must carry the other clauses across, or resolving a dc drops the
        # damage rejection.
        from pfsrd2.ability_enrichment import rejection_reason

        cli = load_cli()
        l59s = rejection_reason("damage", "9d9")
        curs, ability_id = self._flagged(db, f"unextracted: dc(1), damage(2); {l59s}")
        curs.execute("SELECT * FROM ability_records WHERE ability_id = ?", (ability_id,))
        record = curs.fetchone()

        cli._update_review_flag(curs, record, "dc", was_enriched=True)
        db.commit()

        reason = self._reason(db, ability_id)
        assert "--llm-type damage" in reason, "the l59s clause must survive"
        assert "dc(1)" not in reason, "the resolved type must be dropped"
        assert "damage(2)" in reason, "the unresolved type must remain"

    def test_resolving_the_last_type_still_keeps_a_foreign_clause(self, db):
        # With no unextracted types left, the record must NOT be cleared while
        # another finding is still outstanding against it.
        from pfsrd2.ability_enrichment import rejection_reason

        cli = load_cli()
        l59s = rejection_reason("damage", "9d9")
        curs, ability_id = self._flagged(db, f"unextracted: dc(1); {l59s}")
        curs.execute("SELECT * FROM ability_records WHERE ability_id = ?", (ability_id,))
        record = curs.fetchone()

        cli._update_review_flag(curs, record, "dc", was_enriched=True)
        db.commit()

        curs.execute(
            "SELECT needs_review, review_reason FROM ability_records WHERE ability_id = ?",
            (ability_id,),
        )
        row = curs.fetchone()
        assert row["needs_review"] == 1
        assert "--llm-type damage" in row["review_reason"]

    def test_a_dry_run_does_not_restale_either(self, db):
        # --dry-run guarded only the newest write in this function, so it
        # printed "would requeue N" and then re-staled records for real and
        # committed. A flag that promises not to write and then writes is
        # worse than no flag.
        cli = load_cli()
        from pfsrd2.sql.enrichment.queries import insert_ability_record

        curs = db.cursor()
        ability_id = insert_ability_record(
            curs, "A", "h", json.dumps({"name": "A", "text": "original text"})
        )
        # enriched_json embeds a raw that no longer matches raw_json, which is
        # exactly what the heal criterion re-stales on.
        curs.execute(
            "UPDATE ability_records SET enriched_json = ?, enrichment_version = 2,"
            " stale = 0, human_verified = 0 WHERE ability_id = ?",
            (json.dumps({"name": "A", "text": "DRIFTED"}), ability_id),
        )
        db.commit()

        cli.run_audit_enriched(db, Args(dry_run=True))
        assert _row(db, ability_id)["stale"] == 0, "a dry run must not re-stale"

        cli.run_audit_enriched(db, Args(dry_run=False))
        assert _row(db, ability_id)["stale"] == 1, "a real run must re-stale"


class TestTheRecordReachesATerminalState:
    """A flagged record must eventually stop being flagged.

    Every repair to this machinery asked "what did we wrongly drop?"; none
    asked "what do we now never drop?". The answer was the l59s rejection
    clause: it survived every pass, so a record rejected once stayed
    needs_review forever and was re-sent to the LLM on every run.
    """

    def _flagged(self, conn, reason):
        from pfsrd2.sql.enrichment.queries import insert_ability_record, mark_needs_review

        curs = conn.cursor()
        raw = json.dumps({"name": "A", "text": "takes 4d6 fire damage"})
        ability_id = insert_ability_record(curs, "A", "h", raw)
        mark_needs_review(curs, ability_id, reason)
        conn.commit()
        curs.execute("SELECT * FROM ability_records WHERE ability_id = ?", (ability_id,))
        return curs, ability_id, curs.fetchone()

    def test_a_grounded_value_retires_the_rejection_for_that_field(self, db):
        from pfsrd2.ability_enrichment import rejection_reason

        cli = load_cli()
        curs, ability_id, record = self._flagged(
            db, f"unextracted: damage(1); {rejection_reason('damage', '9d9')}"
        )
        cli._update_review_flag(curs, record, "damage", was_enriched=True)
        db.commit()
        curs.execute(
            "SELECT needs_review, review_reason FROM ability_records WHERE ability_id = ?",
            (ability_id,),
        )
        row = curs.fetchone()
        assert row["needs_review"] == 0, "nothing is outstanding, so the flag must clear"

    def test_a_rejection_for_a_DIFFERENT_field_is_not_retired(self, db):
        # Resolving damage says nothing about the dc rejection.
        from pfsrd2.ability_enrichment import rejection_reason

        cli = load_cli()
        curs, ability_id, record = self._flagged(
            db,
            f"unextracted: damage(1); {rejection_reason('saving_throw', 'DC 30')}",
        )
        cli._update_review_flag(curs, record, "damage", was_enriched=True)
        db.commit()
        curs.execute(
            "SELECT needs_review, review_reason FROM ability_records WHERE ability_id = ?",
            (ability_id,),
        )
        row = curs.fetchone()
        assert row["needs_review"] == 1
        assert "--llm-type dc" in row["review_reason"]

    def test_an_unenriched_pass_does_not_amnesty_the_rejection(self, db):
        # The LLM returning nothing is not the same as returning something
        # grounded. A rejected value that never gets replaced stays flagged.
        from pfsrd2.ability_enrichment import rejection_reason

        cli = load_cli()
        curs, ability_id, record = self._flagged(
            db, f"unextracted: damage(1); {rejection_reason('damage', '9d9')}"
        )
        cli._update_review_flag(curs, record, "damage", was_enriched=False)
        db.commit()
        curs.execute(
            "SELECT needs_review, review_reason FROM ability_records WHERE ability_id = ?",
            (ability_id,),
        )
        row = curs.fetchone()
        assert row["needs_review"] == 1
        assert "--llm-type damage" in row["review_reason"]

    def test_retirement_keys_on_the_FIELD_not_the_llm_type(self, db):
        # dc is the one type not spelled like its field (saving_throw). Using
        # the llm_type here would build the wrong marker and retire nothing --
        # invisible for the other three types, which are spelled alike.
        from pfsrd2.ability_enrichment import rejection_reason

        cli = load_cli()
        curs, ability_id, record = self._flagged(
            db, f"unextracted: dc(1); {rejection_reason('saving_throw', 'DC 30')}"
        )
        cli._update_review_flag(curs, record, "dc", was_enriched=True)
        db.commit()
        curs.execute(
            "SELECT needs_review FROM ability_records WHERE ability_id = ?", (ability_id,)
        )
        assert curs.fetchone()["needs_review"] == 0, (
            "a grounded dc must retire the saving_throw rejection"
        )
