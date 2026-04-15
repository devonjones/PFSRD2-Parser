"""Tests for bin/pf2_seed_creature_types."""

import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path


def _load_seed_module():
    """Load the seed script as a module (it has no .py extension)."""
    path = Path(__file__).resolve().parents[1] / "bin" / "pf2_seed_creature_types"
    loader = SourceFileLoader("pf2_seed_creature_types", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


seed = _load_seed_module()


def _write_monster(data_dir, rel, creature_types):
    """Helper: write a minimal monster JSON with the given creature_types."""
    path = Path(data_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"stat_block": {"creature_type": {"creature_types": creature_types}}})
    )


class TestIterCreatureTypeNames:
    def test_yields_from_monsters_and_npcs(self, tmp_path):
        _write_monster(tmp_path, "monsters/bestiary/goblin.json", ["Goblin", "Humanoid"])
        _write_monster(tmp_path, "npcs/core/guard.json", ["Human"])
        result = list(seed._iter_creature_type_names(str(tmp_path)))
        assert "Goblin" in result
        assert "Humanoid" in result
        assert "Human" in result

    def test_malformed_json_is_skipped_with_warning(self, tmp_path, capsys):
        good = tmp_path / "monsters/bestiary/ok.json"
        good.parent.mkdir(parents=True)
        good.write_text(
            json.dumps({"stat_block": {"creature_type": {"creature_types": ["Aberration"]}}})
        )
        bad = tmp_path / "monsters/bestiary/bad.json"
        bad.write_text("{ this is not json")

        result = list(seed._iter_creature_type_names(str(tmp_path)))

        assert result == ["Aberration"]
        err = capsys.readouterr().err
        assert "bad.json" in err
        assert "skipping" in err

    def test_unwraps_dict_name_entries(self, tmp_path):
        path = tmp_path / "monsters/bestiary/fancy.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "stat_block": {
                        "creature_type": {"creature_types": [{"name": "Dragon"}, {"name": "Fire"}]}
                    }
                }
            )
        )
        assert list(seed._iter_creature_type_names(str(tmp_path))) == ["Dragon", "Fire"]

    def test_filters_blank_and_non_string_names(self, tmp_path):
        _write_monster(tmp_path, "monsters/bestiary/weird.json", ["", "   ", None, "Valid"])
        assert list(seed._iter_creature_type_names(str(tmp_path))) == ["Valid"]

    def test_strips_whitespace(self, tmp_path):
        _write_monster(tmp_path, "monsters/bestiary/sp.json", ["  Undead  "])
        assert list(seed._iter_creature_type_names(str(tmp_path))) == ["Undead"]


class TestSeedMain:
    def test_exits_2_with_no_arg_and_no_env(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["pf2_seed_creature_types"])
        monkeypatch.delenv("PF2_DATA_DIR", raising=False)
        assert seed.main() == 2

    def test_exits_2_on_missing_dir(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["pf2_seed_creature_types", "/does/not/exist/xyz"])
        monkeypatch.delenv("PF2_DATA_DIR", raising=False)
        assert seed.main() == 2

    def test_dedups_before_upsert(self, tmp_path, monkeypatch, capsys):
        # Same name appears in two files; main's `seen` set should upsert once.
        _write_monster(tmp_path, "monsters/a/a.json", ["Undead"])
        _write_monster(tmp_path, "monsters/b/b.json", ["Undead", "Dragon"])

        upsert_calls = []

        def fake_upsert(curs, name):
            upsert_calls.append(name)

        # In-memory DB via real get_enrichment_db_connection
        from pfsrd2.sql.enrichment import get_enrichment_db_connection

        memdb = get_enrichment_db_connection(db_path=":memory:")
        monkeypatch.setattr(seed, "get_enrichment_db_connection", lambda: memdb)
        monkeypatch.setattr(seed, "upsert_creature_type", fake_upsert)
        # fetch_all_creature_types is called for before/after snapshots; stub
        # it to empty sets so main's diff print doesn't matter.
        monkeypatch.setattr(seed, "fetch_all_creature_types", lambda curs: set())

        monkeypatch.setattr(sys, "argv", ["pf2_seed_creature_types", str(tmp_path)])
        rc = seed.main()

        assert rc == 0
        assert sorted(upsert_calls) == ["Dragon", "Undead"]  # no duplicate "Undead"

    def test_reads_from_env_when_no_argv(self, tmp_path, monkeypatch):
        _write_monster(tmp_path, "monsters/a/a.json", ["Goblin"])

        from pfsrd2.sql.enrichment import get_enrichment_db_connection

        memdb = get_enrichment_db_connection(db_path=":memory:")
        monkeypatch.setattr(seed, "get_enrichment_db_connection", lambda: memdb)

        recorded = []
        monkeypatch.setattr(seed, "upsert_creature_type", lambda c, n: recorded.append(n))
        monkeypatch.setattr(seed, "fetch_all_creature_types", lambda c: set())

        monkeypatch.setattr(sys, "argv", ["pf2_seed_creature_types"])
        monkeypatch.setenv("PF2_DATA_DIR", str(tmp_path))

        assert seed.main() == 0
        assert recorded == ["Goblin"]
