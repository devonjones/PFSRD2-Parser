import pytest

from pfsrd2.monster_family import _extract_level_table_pass, _level_changes_last

VAMPIRE_TABLE = (
    "<p>Increase the creature's level by 1.</p><table>"
    "<tr><td><b>Starting Level</b></td><td><b>HP Decrease</b></td>"
    "<td><b>Fast Healing/Resistance</b></td></tr>"
    "<tr><td>3–4</td><td>–20</td><td>5</td></tr>"
    "<tr><td>15+</td><td>–60</td><td>15</td></tr></table>"
)
WARPWAVE_TABLE = "<table><tr><td>d8</td><td>Effect</td></tr><tr><td>1</td><td>x</td></tr></table>"


def _struct(*texts):
    sections = [{"name": f"s{i}", "text": t, "sections": []} for i, t in enumerate(texts)]
    # nest the last section to prove the walk recurses (strigoi keeps its
    # table in a section of its own)
    sections[0]["sections"].append(sections.pop())
    return {"name": "Vampire", "sections": sections, "monster_family": {"name": "Vampire"}}


def test_extracts_starting_level_table_and_normalizes_dashes():
    struct = _struct(WARPWAVE_TABLE, VAMPIRE_TABLE)
    _extract_level_table_pass(struct)
    rows = struct["monster_family"]["adjustments"]
    assert [
        (r["starting_level"], r["hp_decrease"], r["fast_healing/resistance"]) for r in rows
    ] == [
        ("3-4", "-20", "5"),
        ("15+", "-60", "15"),
    ]
    # display text keeps the table
    assert "<table>" in struct["sections"][0]["sections"][0]["text"]


def test_ignores_non_level_tables():
    struct = _struct("<p>intro</p>", WARPWAVE_TABLE)
    _extract_level_table_pass(struct)
    assert "adjustments" not in struct["monster_family"]


def test_two_level_tables_fail_loudly():
    struct = _struct(VAMPIRE_TABLE, VAMPIRE_TABLE)
    with pytest.raises(AssertionError):
        _extract_level_table_pass(struct)


def _changes(*cats):
    return [{"text": c, "change_category": c} for c in cats]


def test_level_change_moves_last_when_family_has_table():
    struct = {
        "monster_family": {
            "adjustments": [{}],
            "changes": _changes("level", "hit_points", "traits"),
        }
    }
    _level_changes_last(struct)
    assert [c["text"] for c in struct["monster_family"]["changes"]] == [
        "hit_points",
        "traits",
        "level",
    ]


def test_level_change_stays_put_without_table():
    struct = {"monster_family": {"changes": _changes("level", "hit_points")}}
    _level_changes_last(struct)
    assert [c["text"] for c in struct["monster_family"]["changes"]] == ["level", "hit_points"]


def test_markdown_pass_leaves_skipped_keys_alone():
    from universal.markdown import markdown_pass

    cond = "$.creature_type.level >= 3 && $.creature_type.level <= 4"
    struct = {"effects": [{"conditional": cond, "text": "<i>x</i>"}]}
    markdown_pass(struct, "X", "", skip_keys={"conditional"})
    assert struct["effects"][0] == {"conditional": cond, "text": "*x*"}
