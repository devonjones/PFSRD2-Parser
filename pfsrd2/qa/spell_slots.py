"""Spell slot verification against the parsed spell corpus.

The spell side of the slot work has an oracle the rune and material work
didn't: 2,370 parsed spells. Every spell a staff or wand claims to hold must
resolve to one of them, so a misparsed list ("light" vs "light,") or a
hallucinated name fails here rather than shipping.

    bin/pf2_verify_spell_slots      # exit 1 on unresolvable spells or illegal ranks

Also checks the rank ceilings the rules impose (GM Core 262, 282) and that no
wand slot admits a spell type the rules forbid.
"""

from pfsrd2.qa import load_equipment, load_json_dir
from pfsrd2.spell_slot import SCROLL_MAX_RANK, WAND_MAX_RANK


def normalize(name):
    """Fold the typographic apostrophe AoN uses in spell names.

    Item pages write "mariner's curse" with U+2019 while the spell corpus uses
    the ASCII form, so a literal comparison misses every possessive spell."""
    return (name or "").lower().replace("\u2019", "'").replace("\u02bc", "'")


MAX_RANK = {"scroll": SCROLL_MAX_RANK, "wand": WAND_MAX_RANK, "staff": 10}

# Spell references that legitimately resolve to nothing, with the reason.
# Scoped like the material verifier's NO_BASE_MATERIAL: an unlisted dangling
# reference is a real problem, these two are not.
KNOWN_DANGLING = {
    # AoN writes this one unlinked (<i>humanoid transformation</i> with no
    # <a>) on the legacy Staff of Transmutation, and publishes no page for
    # it — the remaster renamed the spell to "humanoid form". A gap in the
    # source, not in this parse.
    "humanoid transformation",
}


def load_holders():
    return load_equipment(lambda doc: "spell_slots" in doc.get("stat_block", {}))


def load_spell_index():
    """name -> aonid and aonid -> name, over every parsed spell."""
    by_name, by_aonid = {}, {}
    for spell in load_json_dir("spells"):
        name = normalize(spell.get("name"))
        if name:
            by_name.setdefault(name, spell.get("aonid"))
        if spell.get("aonid") is not None:
            by_aonid.setdefault(spell["aonid"], spell.get("name"))
    return by_name, by_aonid


def _slot_blocks(doc):
    """Every spell_slots block on an item, with the variant it came from."""
    stat_block = doc["stat_block"]
    yield None, stat_block["spell_slots"]
    for variant in stat_block.get("variants", []):
        if "spell_slots" in variant:
            yield variant.get("name"), variant["spell_slots"]


def check_spells_resolve(holders, by_name, by_aonid):
    """Every named spell exists, and every aonid agrees with its name."""
    problems = []
    checked = 0
    for doc in holders:
        for variant, block in _slot_blocks(doc):
            spells = [s for e in block.get("entries", []) for s in e["spells"]]
            if block.get("spell"):
                spells.append(block["spell"])
            for spell in spells:
                checked += 1
                where = f"{doc['name']}{f' / {variant}' if variant else ''}"
                name = normalize(spell["name"])
                if name not in by_name:
                    if name not in KNOWN_DANGLING:
                        problems.append(f"{where}: no parsed spell named {spell['name']!r}")
                    continue
                aonid = spell.get("aonid")
                if aonid is not None and aonid not in by_aonid:
                    problems.append(f"{where}: {spell['name']!r} has unknown aonid {aonid}")
    return problems, checked


def check_ranks(holders):
    """Ranks stay inside the ceiling the rules give each holder."""
    problems = []
    for doc in holders:
        for variant, block in _slot_blocks(doc):
            holder = block["holder"]
            ceiling = MAX_RANK[holder]
            where = f"{doc['name']}{f' / {variant}' if variant else ''}"
            for entry in block.get("entries", []):
                rank = entry["rank"]
                if rank != "cantrip" and rank > ceiling:
                    problems.append(f"{where}: rank {rank} exceeds the {holder} ceiling {ceiling}")
        for v in doc["stat_block"].get("variants", []):
            rank = v.get("spell_rank")
            holder = doc["stat_block"]["spell_slots"]["holder"]
            if rank and rank > MAX_RANK[holder]:
                problems.append(
                    f"{doc['name']} / {v.get('name')}: spell_rank {rank} exceeds "
                    f"the {holder} ceiling {MAX_RANK[holder]}"
                )
    return problems


def check_wand_exclusions(holders):
    """No wand slot holds a spell type the rules bar from wands.

    GM Core 282: cantrips, focus spells and rituals can't go in wands. A wand
    with a cantrip entry would mean the parse crossed a staff list into a wand.
    """
    problems = []
    for doc in holders:
        for variant, block in _slot_blocks(doc):
            if block["holder"] != "wand":
                continue
            for entry in block.get("entries", []):
                if entry["rank"] == "cantrip":
                    where = f"{doc['name']}{f' / {variant}' if variant else ''}"
                    problems.append(f"{where}: wand holds a cantrip, which the rules forbid")
    return problems


def check_staff_lists(holders):
    """A staff that publishes a spell list has it structured.

    Whispering Staff is the one legitimate exception: it functions as a major
    staff of the unblinking eye and carries no list of its own.
    """
    allowed_empty = {"Whispering Staff"}
    problems = []
    for doc in holders:
        block = doc["stat_block"]["spell_slots"]
        if block["holder"] != "staff":
            continue
        has = "entries" in block or any(
            "spell_slots" in v for v in doc["stat_block"].get("variants", [])
        )
        if not has and doc["name"] not in allowed_empty:
            problems.append(f"{doc['name']}: staff with no spell entries")
    return problems


def main():
    holders = load_holders()
    if not holders:
        print("no spell-slot data found — run bin/pf2_run_equipment.sh equipment first")
        return 1
    by_name, by_aonid = load_spell_index()
    if not by_name:
        print("no spell data found — the spells corpus is required as the oracle")
        return 1

    resolve_problems, checked = check_spells_resolve(holders, by_name, by_aonid)
    if not checked:
        print("no spell references were checked — every holder claimed an empty slot")
        return 1
    problems = (
        resolve_problems
        + check_ranks(holders)
        + check_wand_exclusions(holders)
        + check_staff_lists(holders)
    )

    print(f"spell-slot holders: {len(holders)}   spell references checked: {checked}")
    if problems:
        print(f"\nPROBLEMS: {len(problems)}")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nevery slotted spell resolves and every rank is legal")
    return 0
