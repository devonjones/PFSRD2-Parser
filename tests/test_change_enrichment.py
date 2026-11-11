import json
from unittest.mock import patch

import pytest

from pfsrd2.change_enrichment import _merge_enrichment, change_enrichment_pass
from pfsrd2.sql.enrichment import (
    fetch_changes_for_source,
    get_enrichment_db_connection,
    update_change_enriched_json,
)


class _NonClosingConnection:
    """Wrapper around sqlite3.Connection that ignores close() calls."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        pass  # No-op so the pass doesn't close our test connection

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def real_close(self):
        self._conn.close()


def _make_change(text):
    """Build a minimal change object matching parser output."""
    return {
        "type": "stat_block_section",
        "subtype": "change",
        "text": text,
        "sections": [],
    }


def _make_struct(source_type, name, changes, subtypes=None, adjustments=None):
    """Build a minimal struct for change_enrichment_pass."""
    obj = {"name": name, "changes": changes}
    if subtypes:
        obj["subtypes"] = subtypes
    if adjustments:
        obj["adjustments"] = adjustments
    return {
        "name": name,
        source_type: obj,
    }


class TestMergeEnrichment:
    def test_merges_category_and_effects(self):
        change = {"text": "Add the undead trait.", "type": "stat_block_section"}
        enriched_json = json.dumps(
            {
                "change_category": "traits",
                "effects": [{"target": "$.creature_type", "operation": "add_item"}],
            }
        )
        _merge_enrichment(change, enriched_json)
        assert change["change_category"] == "traits"
        assert len(change["effects"]) == 1

    def test_does_not_overwrite_existing_fields(self):
        change = {
            "text": "Add the undead trait.",
            "change_category": "existing_category",
        }
        enriched_json = json.dumps(
            {
                "change_category": "traits",
                "effects": [{"target": "$.creature_type", "operation": "add_item"}],
            }
        )
        _merge_enrichment(change, enriched_json)
        # Should NOT overwrite existing change_category
        assert change["change_category"] == "existing_category"
        # But should add effects since it wasn't present
        assert "effects" in change

    def test_does_not_modify_text(self):
        change = {"text": "Original text."}
        enriched_json = json.dumps(
            {
                "change_category": "traits",
                "text": "Modified text.",
            }
        )
        _merge_enrichment(change, enriched_json)
        assert change["text"] == "Original text."


class TestChangeEnrichmentPass:
    @pytest.fixture
    def mock_db(self):
        """Provide in-memory DB and patch get_enrichment_db_connection.

        The pass calls conn.close() internally. We wrap the connection
        so close() is a no-op, keeping it alive for test verification.
        """
        real_conn = get_enrichment_db_connection(db_path=":memory:")
        wrapper = _NonClosingConnection(real_conn)
        with patch("pfsrd2.change_enrichment.get_enrichment_db_connection", return_value=wrapper):
            yield real_conn
        real_conn.close()

    def test_populates_db_on_first_run(self, mock_db):
        changes = [_make_change("Add the undead trait.")]
        struct = _make_struct("monster_template", "Vampire", changes)
        change_enrichment_pass(struct, "monster_template")
        curs = mock_db.cursor()
        rows = fetch_changes_for_source(curs, "Vampire", "monster_template")
        assert len(rows) == 1
        assert rows[0]["source_name"] == "Vampire"

    def test_merges_enriched_data_on_second_run(self, mock_db):
        changes = [_make_change("Add the undead trait.")]
        struct = _make_struct("monster_template", "Vampire", changes)

        # First run: populates DB
        change_enrichment_pass(struct, "monster_template")

        # Simulate enrichment: store enriched data for the record
        curs = mock_db.cursor()
        rows = fetch_changes_for_source(curs, "Vampire", "monster_template")
        enriched = json.dumps({"change_category": "traits", "effects": []})
        update_change_enriched_json(curs, rows[0]["change_id"], enriched, 1, "regex")
        mock_db.commit()

        # Second run: should merge enrichment into change
        changes2 = [_make_change("Add the undead trait.")]
        struct2 = _make_struct("monster_template", "Vampire", changes2)
        change_enrichment_pass(struct2, "monster_template")
        assert changes2[0].get("change_category") == "traits"

    def test_handles_no_changes(self, mock_db):
        struct = _make_struct("monster_template", "Vampire", [])
        # Should not raise
        change_enrichment_pass(struct, "monster_template")

    def test_handles_struct_with_no_obj(self, mock_db):
        struct = {"name": "Empty"}
        # No monster_template key — should return without error
        change_enrichment_pass(struct, "monster_template")

    def test_handles_subtypes(self, mock_db):
        subtype_changes = [_make_change("Add the ghost trait.")]
        subtypes = [{"name": "Strigoi", "changes": subtype_changes}]
        struct = _make_struct("monster_family", "Vampire", [], subtypes=subtypes)
        change_enrichment_pass(struct, "monster_family")

        curs = mock_db.cursor()
        rows = fetch_changes_for_source(curs, "Vampire :: Strigoi", "monster_family")
        assert len(rows) == 1

    def test_handles_nested_subtypes(self, mock_db):
        """Nested subtypes should include full ancestry in source_name."""
        grandchild_changes = [_make_change("Add darkvision.")]
        child = {
            "name": "True Abilities",
            "changes": [],
            "subtypes": [{"name": "Elder", "changes": grandchild_changes}],
        }
        subtypes = [child]
        struct = _make_struct("monster_family", "Vampire", [], subtypes=subtypes)
        change_enrichment_pass(struct, "monster_family")

        curs = mock_db.cursor()
        rows = fetch_changes_for_source(
            curs, "Vampire :: True Abilities :: Elder", "monster_family"
        )
        assert len(rows) == 1

    def test_uses_object_name_not_struct_name(self, mock_db):
        """The pass should use obj['name'] (clean) not struct['name'] (may have HTML)."""
        changes = [_make_change("Add the undead trait.")]
        obj = {"name": "Clean Vampire", "changes": changes}
        struct = {
            "name": "<a>Dirty Vampire</a>",
            "monster_template": obj,
        }
        change_enrichment_pass(struct, "monster_template")

        curs = mock_db.cursor()
        rows = fetch_changes_for_source(curs, "Clean Vampire", "monster_template")
        assert len(rows) == 1

    def test_skips_empty_text_changes(self, mock_db):
        changes = [_make_change(""), _make_change("Add the undead trait.")]
        struct = _make_struct("monster_template", "Vampire", changes)
        change_enrichment_pass(struct, "monster_template")

        curs = mock_db.cursor()
        rows = fetch_changes_for_source(curs, "Vampire", "monster_template")
        # Only the non-empty change should be inserted
        assert len(rows) == 1


class TestFamilyLevelTable:
    """Families attach the starting-level table only to changes citing it,
    and a table that changes under an existing record stales it."""

    TABLE = [{"starting_level": "3-4", "hp_decrease": "-20"}]

    @pytest.fixture
    def mock_db(self):
        real_conn = get_enrichment_db_connection(db_path=":memory:")
        wrapper = _NonClosingConnection(real_conn)
        with patch("pfsrd2.change_enrichment.get_enrichment_db_connection", return_value=wrapper):
            yield real_conn
        real_conn.close()

    def _rows(self, db):
        rows = fetch_changes_for_source(db.cursor(), "Vampire", "monster_family")
        return {json.loads(r["raw_json"])["text"]: r for r in rows}

    def _run(self, texts, adjustments):
        changes = [_make_change(t) for t in texts]
        struct = _make_struct("monster_family", "Vampire", changes, adjustments=adjustments)
        change_enrichment_pass(struct, "monster_family")
        return changes

    def test_only_table_citing_changes_get_the_table(self, mock_db):
        cites = "Reduce its HP by the amount listed on the table."
        plain = "Increase their AC by 2."
        self._run([cites, plain], self.TABLE)
        rows = self._rows(mock_db)
        assert json.loads(rows[cites]["raw_json"])["_adjustments"] == self.TABLE
        assert "_adjustments" not in json.loads(rows[plain]["raw_json"])

    def test_see_below_counts_as_citing_the_table(self, mock_db):
        text = "They gain weakness to holy damage and more HP (see below)."
        self._run([text], self.TABLE)
        assert json.loads(self._rows(mock_db)[text]["raw_json"])["_adjustments"] == self.TABLE

    def test_templates_still_attach_to_every_change(self, mock_db):
        changes = [_make_change("Increase their AC by 2.")]
        struct = _make_struct("monster_template", "Elite", changes, adjustments=self.TABLE)
        change_enrichment_pass(struct, "monster_template")
        row = fetch_changes_for_source(mock_db.cursor(), "Elite", "monster_template")[0]
        assert json.loads(row["raw_json"])["_adjustments"] == self.TABLE

    def test_new_table_stales_existing_record_and_skips_merge(self, mock_db):
        text = "Reduce its HP by the amount listed on the table."
        self._run([text], None)
        row = self._rows(mock_db)[text]
        enriched = json.dumps({"change_category": "hit_points"})
        update_change_enriched_json(mock_db.cursor(), row["change_id"], enriched, 1, "regex")
        mock_db.commit()

        changes = self._run([text], self.TABLE)
        row = self._rows(mock_db)[text]
        assert row["stale"] == 1
        assert json.loads(row["raw_json"])["_adjustments"] == self.TABLE
        assert "change_category" not in changes[0]

    def test_unchanged_table_merges(self, mock_db):
        text = "Reduce its HP by the amount listed on the table."
        self._run([text], self.TABLE)
        row = self._rows(mock_db)[text]
        enriched = json.dumps({"change_category": "hit_points"})
        update_change_enriched_json(mock_db.cursor(), row["change_id"], enriched, 1, "regex")
        mock_db.commit()

        changes = self._run([text], self.TABLE)
        assert self._rows(mock_db)[text]["stale"] == 0
        assert changes[0]["change_category"] == "hit_points"

    def test_human_verified_record_is_not_staled(self, mock_db):
        text = "Reduce its HP by the amount listed on the table."
        self._run([text], None)
        row = self._rows(mock_db)[text]
        mock_db.execute(
            "UPDATE change_records SET human_verified = 1 WHERE change_id = ?", (row["change_id"],)
        )
        mock_db.commit()

        self._run([text], self.TABLE)
        assert self._rows(mock_db)[text]["stale"] == 0
