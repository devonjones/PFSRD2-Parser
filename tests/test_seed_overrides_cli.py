"""Subprocess tests for the pf2_seed_change_overrides CLI exit-code contract.

The exit code is the enforcement mechanism that keeps stale overrides from
being silently skipped in the cold-start cycle (docs/enrichment-process.md
Phase 5 requires exit 0). These tests drive the real CLI against a temp DB
via the PFSRD2_ENRICHMENT_DB env var so the developer's ~/.pfsrd2 is never
touched.
"""

import json
import os
import subprocess
import sys

from pfsrd2.change_identity import compute_change_hash
from pfsrd2.enrichment.overrides import load_overrides
from pfsrd2.sql.enrichment import (
    get_enrichment_db_connection,
    insert_ability_record,
    insert_change_record,
)

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
CLI = os.path.join(REPO_ROOT, "bin", "pf2_seed_change_overrides")


def _run_cli(db_path):
    env = dict(os.environ, PFSRD2_ENRICHMENT_DB=str(db_path))
    return subprocess.run(
        [sys.executable, CLI],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _populate_records(db_path, change_overrides, ability_overrides):
    """Insert a matching raw record for each override so seeding can hit."""
    env_backup = os.environ.get("PFSRD2_ENRICHMENT_DB")
    os.environ["PFSRD2_ENRICHMENT_DB"] = str(db_path)
    try:
        conn = get_enrichment_db_connection()
        try:
            curs = conn.cursor()
            for ov in change_overrides:
                identity_hash = compute_change_hash(
                    ov["source_name"], ov["source_type"], ov["change_text"]
                )
                insert_change_record(
                    curs,
                    ov["source_name"],
                    ov["source_type"],
                    identity_hash,
                    json.dumps({"text": ov["change_text"]}),
                )
            for ov in ability_overrides:
                insert_ability_record(curs, ov["name"], "hash-" + ov["name"], "{}")
            conn.commit()
        finally:
            conn.close()
    finally:
        if env_backup is None:
            del os.environ["PFSRD2_ENRICHMENT_DB"]
        else:
            os.environ["PFSRD2_ENRICHMENT_DB"] = env_backup


class TestDBPathEnvOverride:
    def test_env_var_set_overrides_path(self, monkeypatch, tmp_path):
        from pfsrd2.sql import enrichment

        override = str(tmp_path / "other.db")
        monkeypatch.setenv(enrichment.DB_PATH_ENV_VAR, override)
        assert enrichment._get_db_path() == override

    def test_env_var_unset_uses_default(self, monkeypatch):
        from pfsrd2.sql import enrichment

        monkeypatch.delenv(enrichment.DB_PATH_ENV_VAR, raising=False)
        assert enrichment._get_db_path().endswith(os.path.join(".pfsrd2", enrichment.DB_NAME))

    def test_env_var_empty_string_behaves_as_unset(self, monkeypatch):
        # Pin the truthiness check: an empty override must not redirect the
        # DB to the current directory.
        from pfsrd2.sql import enrichment

        monkeypatch.setenv(enrichment.DB_PATH_ENV_VAR, "")
        assert enrichment._get_db_path().endswith(os.path.join(".pfsrd2", enrichment.DB_NAME))

    def test_override_announces_on_stderr(self, monkeypatch, tmp_path, capsys):
        # A leaked/typo'd override silently creating a fresh empty DB is the
        # failure mode — the redirect must be visible.
        from pfsrd2.sql import enrichment

        monkeypatch.setenv(enrichment.DB_PATH_ENV_VAR, str(tmp_path / "o.db"))
        enrichment._get_db_path()
        assert enrichment.DB_PATH_ENV_VAR in capsys.readouterr().err


class TestSeedCLIExitCodes:
    def test_stale_overrides_exit_nonzero(self, tmp_path):
        # Fresh migrated DB with no change records: every committed change
        # override misses, and abilities miss too — the CLI must exit 1 and
        # name the stale entries on stderr.
        db_path = tmp_path / "enrichment.db"
        result = _run_cli(db_path)
        assert result.returncode == 1, result.stdout + result.stderr
        assert "stale overrides" in result.stderr
        # Every change override should be listed as a miss.
        assert len(load_overrides("change_overrides.json")) == result.stderr.count("  change: ")

    def test_clean_seed_exits_zero(self, tmp_path):
        # With a matching record staged for every committed override, the CLI
        # seeds cleanly and exits 0.
        db_path = tmp_path / "enrichment.db"
        change_overrides = load_overrides("change_overrides.json")
        ability_overrides = load_overrides("ability_overrides.json")
        _populate_records(db_path, change_overrides, ability_overrides)

        result = _run_cli(db_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (
            f"Change overrides seeded: {len(change_overrides)}/{len(change_overrides)}"
            in result.stdout
        )

        # Idempotency at the CLI level: a second run is still clean.
        result2 = _run_cli(db_path)
        assert result2.returncode == 0, result2.stdout + result2.stderr
