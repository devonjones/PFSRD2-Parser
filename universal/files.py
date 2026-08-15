import glob
import json
import os
import re
import unicodedata


def char_replace(instr):
    for char in {
        "(",
        ")",
        "[",
        "]",
        ",",
        "/",
        "'",
        "\u2018",
        "\u2019",
        ":",
        ";",
        "&",
        ".",
        "#",
        "!",
        "?",
    }:
        instr = instr.replace(char, "")
    instr = instr.strip()
    instr = instr.replace(" ", "_")
    instr = instr.lower()
    instr = "".join(
        c for c in unicodedata.normalize("NFD", instr) if unicodedata.category(c) != "Mn"
    )
    instr = re.sub(r"[^a-z0-9_\-]", "", instr)
    return instr


def makedirs(output, game_obj, source=None):
    if not source:
        game_obj_dir = os.path.abspath(output + "/" + char_replace(game_obj))
    else:
        game_obj_dir = os.path.abspath(
            output + "/" + char_replace(game_obj) + "/" + char_replace(source)
        )
    if not os.path.exists(game_obj_dir):
        os.makedirs(game_obj_dir)
    return game_obj_dir


def disambiguated_filename(jsondir, struct, label):
    """Path for an entry, disambiguated by aonid when two share a name.

    A book can publish two different entries under one name — Pathfinder #184
    has two "Glyph of Warding" hazards, and AoN lists 19 GM Core curses twice
    under separate aonids. Writing both to the same path silently loses one
    and leaves the second aonid resolving to nothing, so once a name collides
    EVERY entry sharing it takes its aonid, however many there are and in
    whatever order they are parsed.

    Only aonid is compared against what is already on disk. Comparing bodies
    would make any parser change fail the next run against its own stale
    output, and CLAUDE.md guarantees the data directory need not be cleared
    between runs.
    """
    stem = os.path.abspath(jsondir + "/" + char_replace(struct["name"]))
    base = stem + ".json"
    suffixed = f"{stem}_{struct['aonid']}.json"
    if not os.path.exists(base):
        # A sibling already claimed a suffix, so this name is known to collide.
        # _[0-9]* not _*: char_replace turns spaces into underscores, so a
        # bare _* also matches unrelated longer names ("glyph_of_warding" would
        # match "glyph_of_warding_trap"). 51 such pairs exist under monsters/.
        return suffixed if glob.glob(f"{stem}_[0-9]*.json") else base

    with open(base) as fp:
        try:
            existing = json.load(fp)
        except json.JSONDecodeError as e:
            raise ValueError(f"Existing {label} file {base} is not readable JSON") from e
    assert "aonid" in existing, f"Existing {label} file {base} has no aonid"
    if existing["aonid"] == struct["aonid"]:
        return base
    # Move the squatter aside under its own aonid, then take a suffix too.
    os.rename(base, f"{stem}_{existing['aonid']}.json")
    return suffixed
